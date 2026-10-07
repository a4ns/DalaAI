# Versioned derivation of frozen v1 scenarios: only imports and app_factory
# injection differ. No service, repository, verifier or response is mocked.
"""Cross-role HTTP orchestration only; does not reproduce transaction/race tests."""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
import json
from uuid import UUID

from vertical_acceptance.fixtures import (CODE, EQUIPMENT, EXECUTOR, FOREIGN_EQUIPMENT, FOREIGN_SECTION,
                       MATERIAL, MASTER, OTHER, SECTION, clients, command,
                       create_order_command, submission_payload)
from vertical_acceptance.support import ensure, utc_now


class Trace:
    def __init__(self):
        self.steps = []

    @contextmanager
    def step(self, name):
        entry = {"name": name, "status": "RUNNING", "started_at": utc_now()}
        self.steps.append(entry)
        try:
            yield
        except Exception as error:
            entry.update(status="FAIL", error_type=type(error).__name__)
            if isinstance(error, AssertionError):
                entry["reason"] = str(error)
            raise
        else:
            entry["status"] = "PASS"
        finally:
            entry["finished_at"] = utc_now()


def response_body(response, status):
    ensure(response.status_code == status, f"HTTP expected {status}, received {response.status_code}")
    ensure("no-store" in response.headers.get("cache-control", ""), "Response missing no-store")
    return response.json()


def error_response(response, status, code, current_version=None):
    body = response_body(response, status)
    ensure(body["code"] == code, f"Expected error code {code}")
    ensure(body["current_version"] == current_version, "Wrong or unauthorized current_version")
    ensure(body["retryable"] is False, "Conflict/authorization error must not encourage blind retry")
    UUID(body["request_id"])
    ensure(set(body) == {"code", "message", "request_id", "retryable", "current_version", "field_errors"},
           "Unexpected error fields could leak object data")
    return body


def effects(connect, order_id):
    """Read-only postconditions, not an alternate implementation of commands."""
    with connect() as db:
        result = db.execute("SELECT id::text,status,version,current_submission_id::text FROM orders WHERE id=%s", (order_id,)).fetchone()
        result["events"] = db.execute("SELECT id::text,sequence,order_version,to_status,actor_id::text FROM order_events WHERE order_id=%s ORDER BY sequence", (order_id,)).fetchall()
        result["receipt_count"] = db.execute("SELECT count(*) AS n FROM operation_receipts WHERE resource_id=%s", (order_id,)).fetchone()["n"]
        result["submission_count"] = db.execute("SELECT count(*) AS n FROM submissions WHERE order_id=%s", (order_id,)).fetchone()["n"]
        result["review_count"] = db.execute("SELECT count(*) AS n FROM reviews r JOIN submissions s ON s.id=r.submission_id WHERE s.order_id=%s", (order_id,)).fetchone()["n"]
        result["delivery_count"] = db.execute("SELECT count(*) AS n FROM delivery_jobs WHERE order_id=%s", (order_id,)).fetchone()["n"]
        result["ai_job_count"] = db.execute("SELECT count(*) AS n FROM ai_jobs a JOIN submissions s ON s.id=a.submission_id WHERE s.order_id=%s", (order_id,)).fetchone()["n"]
        return result


def failed_command_has_no_receipt(connect, intent):
    with connect() as db:
        count = db.execute("SELECT count(*) AS n FROM operation_receipts WHERE operation_id=%s", (intent["operation_id"],)).fetchone()["n"]
    ensure(count == 0, "Failed HTTP intent left a successful receipt")


def execute(actor, order_id, intent, status, version):
    body = response_body(actor.post(f"/api/v1/orders/{order_id}/commands", intent), 200)
    ensure(body["order"]["status"] == status, f"Expected order state {status}")
    ensure(body["order"]["version"] == version, "Unexpected aggregate version")
    ensure(bool(body["event_ids"]), "Successful command returned no event IDs")
    return body


def phase_one(connect, trace, app_factory):
    with ExitStack() as stack:
        with trace.step("Real demo logins create three isolated cookie sessions and recover CSRF via /me"):
            master, executor, other = clients(stack, app_factory())
        with trace.step("Scoped dictionaries provide create-form references without foreign section data"):
            dictionaries = response_body(master.get("/api/v1/dicts"), 200)
            for name, identifier in (("sections", SECTION), ("equipment", EQUIPMENT),
                                     ("work_codes", CODE), ("materials", MATERIAL), ("executors", EXECUTOR)):
                ensure(identifier in {item["id"] for item in dictionaries[name]}, f"Missing required dictionary {name}")
            ensure(FOREIGN_SECTION not in {item["id"] for item in dictionaries["sections"]}, "Foreign section leaked")
            ensure(FOREIGN_EQUIPMENT not in {item["id"] for item in dictionaries["equipment"]}, "Foreign equipment leaked")
        with trace.step("Master issues a planned order; assigned executor discovers it through GET /orders"):
            create_intent = create_order_command()
            created = response_body(master.post("/api/v1/orders", create_intent), 201)
            order_id = created["order"]["id"]
            ensure(created["order"]["status"] == "issued" and created["order"]["version"] == 1, "Create snapshot invalid")
            visible = response_body(executor.get("/api/v1/orders"), 200)
            ensure(order_id in {item["id"] for item in visible["items"]}, "Assigned order absent from executor discovery")
            hidden = response_body(other.get("/api/v1/orders"), 200)
            ensure(order_id not in {item["id"] for item in hidden["items"]}, "Foreign executor discovered order")
        with trace.step("Foreign executor receives object-level 403 on read and command, without effects"):
            before = effects(connect, order_id)
            error_response(other.get(f"/api/v1/orders/{order_id}"), 403, "FORBIDDEN")
            forbidden = command("accept", 1)
            error_response(other.post(f"/api/v1/orders/{order_id}/commands", forbidden), 403, "FORBIDDEN")
            ensure(effects(connect, order_id) == before, "Foreign request changed persisted order effects")
            failed_command_has_no_receipt(connect, forbidden)
        with trace.step("Assigned executor accepts and starts; master sees committed state"):
            execute(executor, order_id, command("accept", 1), "accepted", 2)
            execute(executor, order_id, command("start", 2), "in_progress", 3)
            current = response_body(master.get(f"/api/v1/orders/{order_id}"), 200)
            ensure(current["status"] == "in_progress" and current["version"] == 3, "Master sees stale state")
        with trace.step("Stale draft gets recovery-ready 409; current state is fetched and intent is retained without auto-resend"):
            draft = command("change_priority", 3, {"priority": "high", "reason": "Synthetic retained draft reason"})
            saved_draft = json.dumps(draft, sort_keys=True)
            execute(executor, order_id, command("pause", 3, {"reason": "Synthetic paused inspection"}), "paused", 4)
            before = effects(connect, order_id)
            error_response(master.post(f"/api/v1/orders/{order_id}/commands", draft), 409, "VERSION_CONFLICT", 4)
            ensure(effects(connect, order_id) == before, "Stale write changed persisted order effects")
            failed_command_has_no_receipt(connect, draft)
            latest = response_body(master.get(f"/api/v1/orders/{order_id}"), 200)
            ensure(latest["version"] == 4 and latest["status"] == "paused", "Conflict reconciliation did not fetch current state")
            ensure(json.dumps(draft, sort_keys=True) == saved_draft, "Acceptance client lost its retained intent")
        with trace.step("Executor resumes and submits planned work; immutable result enters ai_review atomically"):
            execute(executor, order_id, command("resume", 4), "in_progress", 5)
            submit_intent = command("submit", 5, submission_payload())
            submitted = execute(executor, order_id, submit_intent, "ai_review", 6)
            submission_id = submitted["submission_id"]
            ensure(len(submitted["event_ids"]) == 2, "Submit must return done and ai_review event IDs")
            submission = response_body(master.get(f"/api/v1/orders/{order_id}/submissions/{submission_id}"), 200)
            ensure(submission["completeness"] == "complete", "Planned result incorrectly marked incomplete")
            ensure(submission["payload"]["after_photo_ids"] == [], "Harness unexpectedly claimed photo evidence")
            ensure(submission["assessments"] == [], "Harness unexpectedly invoked an assessment provider")
        with trace.step("Only the master closes complete work; persisted review and audit match HTTP evidence"):
            review = command("review", 6, {"submission_id": submission_id, "decision": "close",
                                           "reason": "Synthetic planned result checked by master", "final_score": None})
            error_response(executor.post(f"/api/v1/orders/{order_id}/commands", review), 403, "FORBIDDEN")
            closed = execute(master, order_id, review, "closed", 7)
            persisted = effects(connect, order_id)
            ensure(persisted["version"] == 7 and persisted["status"] == "closed", "Close was not persisted")
            ensure(persisted["receipt_count"] == 7 and persisted["submission_count"] == 1 and persisted["review_count"] == 1, "Unexpected lifecycle effects")
            ensure(persisted["ai_job_count"] == 1, "Submission did not persist the AI intent")
            ensure([row["sequence"] for row in persisted["events"]] == list(range(1, 9)), "Lifecycle event sequence incomplete")
            ensure([row["to_status"] for row in persisted["events"]][-3:] == ["done", "ai_review", "closed"], "Submission/review audit ordering invalid")
            ensure(persisted["events"][-1]["actor_id"] == MASTER, "Close audit did not name authenticated master")
            final_submission = response_body(executor.get(f"/api/v1/orders/{order_id}/submissions/{submission_id}"), 200)
            ensure(final_submission["reviews"][0]["decision"] == "close", "Executor cannot read master decision")
        with trace.step("Unplanned work without after-photo can be submitted but master close is blocked; rework remains possible"):
            incomplete = response_body(master.post("/api/v1/orders", create_order_command("unplanned")), 201)
            incomplete_id = incomplete["order"]["id"]
            execute(executor, incomplete_id, command("accept", 1), "accepted", 2)
            execute(executor, incomplete_id, command("start", 2), "in_progress", 3)
            incomplete_submit = execute(executor, incomplete_id, command("submit", 3, submission_payload()), "ai_review", 4)
            incomplete_sub_id = incomplete_submit["submission_id"]
            incomplete_result = response_body(master.get(f"/api/v1/orders/{incomplete_id}/submissions/{incomplete_sub_id}"), 200)
            ensure(incomplete_result["completeness"] == "incomplete" and incomplete_result["missing_evidence"], "Missing unplanned photo was hidden")
            close = command("review", 4, {"submission_id": incomplete_sub_id, "decision": "close",
                                          "reason": "Synthetic forbidden closure", "final_score": 100})
            before = effects(connect, incomplete_id)
            error_response(master.post(f"/api/v1/orders/{incomplete_id}/commands", close), 409, "INCOMPLETE_SUBMISSION", 4)
            ensure(effects(connect, incomplete_id) == before, "Rejected incomplete close changed order effects")
            failed_command_has_no_receipt(connect, close)
            rework = command("review", 4, {"submission_id": incomplete_sub_id, "decision": "rework",
                                           "reason": "Provide required after-photo", "final_score": None})
            execute(master, incomplete_id, rework, "rework", 5)
            execute(executor, incomplete_id, command("start", 5), "in_progress", 6)
        with trace.step("Logout revokes each issued cookie session"):
            for session in (master, executor, other):
                session.logout()
        return {"order_id": order_id, "submission_id": submission_id,
                "create_intent": create_intent, "create_response": created,
                "submit_intent": submit_intent, "submit_response": submitted,
                "closed_response": closed, "persisted_effects": persisted,
                "incomplete_order_id": incomplete_id,
                "incomplete_effects": effects(connect, incomplete_id)}


def phase_two(connect, trace, state, app_factory):
    with ExitStack() as stack:
        with trace.step("New backend Python process creates fresh app/services and reauthenticates over the same PostgreSQL schema"):
            master, executor, other = clients(stack, app_factory())
            order_id = state["order_id"]
            latest = response_body(master.get(f"/api/v1/orders/{order_id}"), 200)
            ensure(latest["status"] == "closed" and latest["version"] == 7, "Order did not survive backend restart")
            ensure(latest["current_submission_id"] == state["submission_id"], "Submission link did not survive restart")
            ensure(effects(connect, order_id) == state["persisted_effects"], "Persisted evidence changed across restart")
            ensure(effects(connect, state["incomplete_order_id"]) == state["incomplete_effects"], "Rework evidence changed across restart")
        with trace.step("Unknown-response retry after restart returns exact original create and submit receipts without duplicate effects"):
            original = response_body(master.post("/api/v1/orders", deepcopy(state["create_intent"])), 201)
            ensure(original == state["create_response"], "Create replay changed original snapshot or event IDs")
            original_submit = response_body(executor.post(f"/api/v1/orders/{order_id}/commands", deepcopy(state["submit_intent"])), 200)
            ensure(original_submit == state["submit_response"], "Submit replay changed original result or event IDs")
            ensure(effects(connect, order_id) == state["persisted_effects"], "Replay duplicated persisted effects")
            latest = response_body(executor.get(f"/api/v1/orders/{order_id}"), 200)
            ensure(latest["version"] == 7 and latest["status"] == "closed", "Receipt replay rolled back current state")
        with trace.step("Foreign access remains 403 after backend restart, including historical submission"):
            error_response(other.get(f"/api/v1/orders/{order_id}"), 403, "FORBIDDEN")
            error_response(other.get(f"/api/v1/orders/{order_id}/submissions/{state['submission_id']}"), 403, "FORBIDDEN")
        with trace.step("Fresh sessions can log out after restarted-process verification"):
            for session in (master, executor, other):
                session.logout()
