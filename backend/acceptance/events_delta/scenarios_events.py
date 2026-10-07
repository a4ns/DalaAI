"""Additional real HTTP orchestration for the frozen per-order events adapter.

No pure parser/serializer probes or concurrency simulation. The only direct
post-seed write is explicit test-session expiry inside the disposable schema.
"""
from contextlib import ExitStack

from vertical_acceptance.fixtures import (EXECUTOR, OTHER, clients, command,
    create_component_app, create_order_command, submission_payload)
from vertical_acceptance.scenarios import execute, response_body, error_response
from vertical_acceptance.support import ensure, route_inventory

EVENT_ROUTE = ("GET", "/api/v1/orders/{order_id}/events")


def create_events_app(connect):
    from app.core.auth_boundary import SystemRealClock
    from app.order_events.http import create_order_events_router
    from app.order_events.service import OrderEventService
    app = create_component_app(connect)
    app.include_router(create_order_events_router(OrderEventService(connect, real_clock=SystemRealClock())))
    # The base construction already compiled OpenAPI; invalidate that cache
    # after mounting this real extra router before inspecting the final surface.
    app.openapi_schema = None
    ensure(EVENT_ROUTE in route_inventory(app), "Events router is absent from component assembly")
    return app


def drain(actor, order_id, after=0, limit=2):
    result = []
    cursor = after
    pages = []
    for _ in range(100):
        body = response_body(actor.get(f"/api/v1/orders/{order_id}/events?after_sequence={cursor}&limit={limit}"), 200)
        ensure(set(body) == {"items", "next_after_sequence", "has_more"}, "Unexpected event-page shape")
        items = body["items"]
        ensure(len(items) <= limit, "Event page exceeds limit")
        ensure(all(item["order_id"] == order_id for item in items), "Event page contains another order")
        ensure(all(item["sequence"] > cursor for item in items), "Event cursor replayed old sequences")
        ensure([item["sequence"] for item in items] == sorted(item["sequence"] for item in items), "Events are not ascending")
        expected = items[-1]["sequence"] if items else cursor
        ensure(body["next_after_sequence"] == expected, "Returned event cursor is not the last returned sequence")
        pages.append({"after": cursor, "next": expected, "count": len(items), "has_more": body["has_more"]})
        result.extend(items)
        cursor = expected
        if not body["has_more"]:
            ensure(len({event["id"] for event in result}) == len(result), "Duplicate event IDs while draining pages")
            return result, cursor, pages
        ensure(bool(items), "has_more without advancing items would loop forever")
    raise AssertionError("Event-page drain did not terminate")


def phase_one(connect, trace):
    with ExitStack() as stack:
        with trace.step("Real sessions and event router assemble with current command/discovery services"):
            master, executor, successor = clients(stack, create_events_app(connect))
        with trace.step("HTTP order lifecycle produces a five-event history, including two submit events at version four"):
            created = response_body(master.post("/api/v1/orders", create_order_command()), 201)
            order_id = created["order"]["id"]
            accepted = execute(executor, order_id, command("accept", 1), "accepted", 2)
            started = execute(executor, order_id, command("start", 2), "in_progress", 3)
            submitted = execute(executor, order_id, command("submit", 3, submission_payload()), "ai_review", 4)
            expected_ids = created["event_ids"] + accepted["event_ids"] + started["event_ids"] + submitted["event_ids"]
            events, cursor, pages = drain(executor, order_id)
            ensure([event["id"] for event in events] == expected_ids, "HTTP event pages differ from command receipt event IDs")
            ensure([event["sequence"] for event in events] == [1, 2, 3, 4, 5], "Lifecycle event sequence is incomplete")
            ensure([event["order_version"] for event in events] == [1, 2, 3, 4, 4], "Submit events must share one aggregate version")
            ensure([event["to_status"] for event in events][-2:] == ["done", "ai_review"], "Submit event order is wrong")
            ensure([page["has_more"] for page in pages] == [True, True, False], "Pagination did not drain all history")
            current = response_body(master.get(f"/api/v1/orders/{order_id}"), 200)
            ensure(current["version"] == 4 and current["status"] == "ai_review", "Snapshot was not reconciled after page drain")
            empty, same_cursor, _ = drain(executor, order_id, after=cursor)
            ensure(empty == [] and same_cursor == 5, "Empty tail did not preserve last sequence")
        with trace.step("Reassignment revokes old assignee event access and grants complete history to the current assignee"):
            error_response(successor.get(f"/api/v1/orders/{order_id}/events"), 403, "FORBIDDEN")
            reassigned = execute(master, order_id, command("reassign", 4,
                {"assignment": {"executor_id": OTHER, "brigade_id": None}, "reason": "Synthetic handover"}), "issued", 5)
            error_response(executor.get(f"/api/v1/orders/{order_id}/events?after_sequence=5&limit=2"), 403, "FORBIDDEN")
            all_events, final_cursor, _ = drain(successor, order_id)
            expected_ids += reassigned["event_ids"]
            ensure([event["id"] for event in all_events] == expected_ids, "Current assignee lost previous assignment history")
            ensure(final_cursor == 6, "Reassignment event cursor is wrong")
            tail, _, _ = drain(successor, order_id, after=5)
            ensure([event["id"] for event in tail] == reassigned["event_ids"], "Reconnection tail did not start after known sequence")
        with trace.step("Expired session cannot read event history, including the already-known tail cursor"):
            # Explicit synthetic fixture mutation to expire the current assignee's
            # session. No fake clock, fake session store, or saved bearer token.
            with connect() as db:
                expired = db.execute("UPDATE auth_sessions SET expires_at=clock_timestamp() WHERE employee_id=%s AND revoked_at IS NULL RETURNING id", (OTHER,)).fetchall()
            ensure(len(expired) == 1, "Expected one test session to expire")
            error_response(successor.get(f"/api/v1/orders/{order_id}/events?after_sequence=5&limit=2"), 401, "UNAUTHENTICATED")
            master_events, _, _ = drain(master, order_id)
            ensure([event["id"] for event in master_events] == expected_ids, "Session expiry altered order history")
            master.logout()
            executor.logout()
        return {"order_id": order_id, "events": all_events, "cursor": final_cursor,
                "snapshot_version": 5, "assignment_revision": 2}


def phase_two(connect, trace, state):
    with ExitStack() as stack:
        with trace.step("Fresh backend process and new sessions recover the same durable event pages"):
            master, old_executor, successor = clients(stack, create_events_app(connect))
            events, cursor, _ = drain(successor, state["order_id"])
            ensure(events == state["events"], "Event content or identity changed across backend restart")
            ensure(cursor == state["cursor"], "Event cursor changed across backend restart")
            snapshot = response_body(successor.get(f"/api/v1/orders/{state['order_id']}"), 200)
            ensure(snapshot["version"] == state["snapshot_version"] and snapshot["assignment_revision"] == state["assignment_revision"], "Current snapshot does not reconcile with persisted history")
        with trace.step("Fresh login cannot restore a previous assignee's event access; current assignee tail is empty"):
            error_response(old_executor.get(f"/api/v1/orders/{state['order_id']}/events"), 403, "FORBIDDEN")
            tail, cursor, _ = drain(successor, state["order_id"], after=state["cursor"])
            ensure(tail == [] and cursor == state["cursor"], "Completed tail changed after restart")
            for session in (master, old_executor, successor):
                session.logout()
