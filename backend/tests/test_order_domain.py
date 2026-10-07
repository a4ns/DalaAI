"""Synthetic pure-domain tests. These are not HTTP, DB-race, or device evidence."""
import math
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.orders.models import Actor, Completeness, DomainError, Role, Status
from app.orders.rules import assessment_is_current, is_overdue, prepare_new_command
from app.orders.validation import parse_command, timestamp


def uid(number):
    return f"00000000-0000-4000-8000-{number:012d}"


NOW = datetime(2026, 10, 7, 17, tzinfo=timezone.utc)
MASTER = Actor(uid(5), Role.MASTER, frozenset({uid(1)}))
EXECUTOR = Actor(uid(3), Role.EXECUTOR, frozenset({uid(1)}))


class SyntheticReferences:
    def equipment_in_section(self, equipment_id, section_id):
        return equipment_id == uid(2) and section_id == uid(1)

    def assignment_in_section(self, assignment, section_id):
        return (assignment.executor_id in {uid(3), uid(30)} and section_id == uid(1)
                and assignment.brigade_id in {None, uid(4)})

    def work_code_exists(self, work_code_id):
        return work_code_id == uid(6)

    def material_exists(self, material_id):
        return material_id == uid(7)

    def staged_photo_usable(self, photo_id, purpose, actor_id, destination_section_id, order_id, assignment_revision):
        if destination_section_id != uid(1):
            return False
        if purpose == "before":
            return photo_id == uid(9) and actor_id == MASTER.id and order_id is None
        return (photo_id == uid(8) and actor_id == EXECUTOR.id and order_id is not None
                and assignment_revision == 1)


def create_request():
    return {"operation_id": uid(101), "expected_version": 0, "action": "create", "payload": {
        "type": "unplanned", "description": "Synthetic belt replacement",
        "section_id": uid(1), "equipment_id": uid(2),
        "assignment": {"executor_id": uid(3), "brigade_id": uid(4)},
        "due_at": "2026-10-07T18:00:00Z", "norm_minutes": 45,
        "priority": "normal", "comment": "Synthetic fixture", "before_photo_ids": []}}


def submit_payload():
    return {"work_description": "Synthetic belt replaced", "work_code_id": uid(6),
            "materials": [{"material_id": uid(7), "quantity": 1}],
            "after_photo_ids": [uid(8)], "comment": "Synthetic fixture"}


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.refs = SyntheticReferences()
        self.counter = 200
        self.order = self.create().order

    def create(self, request=None, actor=MASTER):
        return prepare_new_command(request or create_request(), actor, order=None,
                                   references=self.refs, domain_now=NOW, order_number="DEMO-0001")

    def run_command(self, action, payload=None, *, actor=EXECUTOR, order=None, version=None,
                    submission=None, now=NOW, attempt=1):
        target = self.order if order is None else order
        self.counter += 1
        raw = {"operation_id": uid(self.counter), "expected_version": target.version if version is None else version,
               "action": action, "payload": {} if payload is None else payload}
        return prepare_new_command(raw, actor, order=target, references=self.refs, domain_now=now,
                                   current_submission=submission, next_attempt_number=attempt)

    def expect_error(self, code, function, *args, **kwargs):
        with self.assertRaises(DomainError) as caught:
            function(*args, **kwargs)
        self.assertEqual(code, caught.exception.code)
        return caught.exception

    def started(self):
        accepted = self.run_command("accept").order
        return self.run_command("start", order=accepted).order

    def submitted(self, **changes):
        return self.run_command("submit", {**submit_payload(), **changes}, order=self.started())

    def review(self, plan, decision="close", *, actor=MASTER, submission=None, **extra):
        payload = {"submission_id": plan.submission.id, "decision": decision,
                   "reason": "Human checked synthetic evidence", "final_score": 90}
        return self.run_command("review", payload, actor=actor, order=plan.order,
                                submission=plan.submission if submission is None else submission, **extra)

    def test_vertical_slice(self):
        self.assertEqual((self.order.status, self.order.version), (Status.ISSUED, 1))
        plan = self.submitted()
        self.assertEqual((plan.order.status, plan.order.version), (Status.AI_REVIEW, 4))
        self.assertEqual([event.kind for event in plan.events], ["order.done", "order.ai_review_requested"])
        self.assertEqual([event.order_version for event in plan.events], [4, 4])
        self.assertIsNone(plan.events[1].actor_id)
        self.assertEqual(plan.submission.completeness, Completeness.COMPLETE)
        final = self.review(plan)
        self.assertEqual((final.order.status, final.order.version), (Status.CLOSED, 5))
        self.assertEqual(final.review.reviewer_id, MASTER.id)
        self.assertEqual(final.review.final_score, 90)

    def test_queue_accept_pause_resume(self):
        queued = self.run_command("queue").order
        accepted = self.run_command("accept", order=queued).order
        started = self.run_command("start", order=accepted).order
        paused = self.run_command("pause", {"reason": "Synthetic wait"}, order=started)
        self.assertEqual(paused.events[0].reason, "Synthetic wait")
        resumed = self.run_command("resume", order=paused.order).order
        self.assertEqual(resumed.status, Status.IN_PROGRESS)

    def test_reject_and_reassign_preserve_reason(self):
        rejected = self.run_command("reject", {"reason": "Synthetic refusal"})
        self.assertEqual(rejected.order.status, Status.REJECTED)
        reassigned = self.run_command("reassign", {"assignment": {"executor_id": uid(30), "brigade_id": None},
                                     "reason": "Synthetic reassignment"}, actor=MASTER, order=rejected.order)
        self.assertEqual(reassigned.order.status, Status.ISSUED)
        self.assertEqual(reassigned.order.assignment_revision, 2)
        self.assertEqual(reassigned.order.scheduling_revision, 2)
        self.assertEqual(dict(reassigned.events[0].details)["previous_executor_id"], uid(3))

    def test_transition_matrix(self):
        plan = self.submitted()
        allowed = {
            "queue": {Status.ISSUED}, "accept": {Status.ISSUED, Status.QUEUED},
            "reject": {Status.ISSUED}, "start": {Status.ACCEPTED, Status.REWORK},
            "pause": {Status.IN_PROGRESS}, "resume": {Status.PAUSED},
            "submit": {Status.IN_PROGRESS}, "review": {Status.AI_REVIEW},
            "cancel": set(Status) - {Status.CLOSED, Status.CANCELLED},
            "reassign": set(Status) - {Status.CLOSED, Status.CANCELLED},
            "change_priority": set(Status) - {Status.CLOSED, Status.CANCELLED},
        }
        payloads = {
            "queue": {}, "accept": {}, "start": {}, "resume": {},
            "reject": {"reason": "test"}, "pause": {"reason": "test"},
            "cancel": {"reason": "test"}, "submit": submit_payload(),
            "review": {"submission_id": plan.submission.id, "decision": "close",
                       "reason": "Human review", "final_score": None},
            "reassign": {"assignment": {"executor_id": uid(30), "brigade_id": None}, "reason": "test"},
            "change_priority": {"priority": "high", "reason": "test"},
        }
        for action, sources in allowed.items():
            actor = MASTER if action in {"review", "cancel", "reassign", "change_priority"} else EXECUTOR
            for source in Status:
                with self.subTest(action=action, source=source):
                    snapshot = replace(plan.order, status=source)
                    kwargs = dict(actor=actor, order=snapshot, submission=plan.submission)
                    if source in sources:
                        result = self.run_command(action, payloads[action], **kwargs)
                        self.assertEqual(result.order.version, snapshot.version + 1)
                    else:
                        self.expect_error("TRANSITION_CONFLICT", self.run_command, action, payloads[action], **kwargs)

    def test_invalid_transition(self):
        self.expect_error("TRANSITION_CONFLICT", self.run_command, "start")

    def test_other_executor_forbidden(self):
        self.expect_error("FORBIDDEN", self.run_command, "accept", actor=replace(EXECUTOR, id=uid(30)))

    def test_other_section_forbidden(self):
        self.expect_error("FORBIDDEN", self.run_command, "cancel", {"reason": "test"},
                          actor=replace(MASTER, section_ids=frozenset({uid(99)})))

    def test_manager_admin_cannot_mutate(self):
        for role in (Role.MANAGER, Role.ADMIN):
            with self.subTest(role=role):
                self.expect_error("FORBIDDEN", self.run_command, "cancel", {"reason": "test"},
                                  actor=replace(MASTER, role=role))

    def test_only_human_master_final(self):
        plan = self.submitted()
        for actor in (EXECUTOR, replace(MASTER, role=Role.ADMIN), replace(MASTER, role=Role.MANAGER)):
            with self.subTest(role=actor.role):
                self.expect_error("FORBIDDEN", self.review, plan, actor=actor)

    def test_authorization_precedes_version_disclosure(self):
        error = self.expect_error("FORBIDDEN", self.run_command, "accept", version=99,
                                  actor=replace(EXECUTOR, id=uid(30)))
        self.assertIsNone(error.current_version)

    def test_stale_version(self):
        accepted = self.run_command("accept").order
        error = self.expect_error("VERSION_CONFLICT", self.run_command, "start", order=accepted, version=1)
        self.assertEqual(error.current_version, 2)

    def test_cancel_terminal_and_invalidates_jobs(self):
        cancelled = self.run_command("cancel", {"reason": "Synthetic cancellation"}, actor=MASTER).order
        self.assertEqual(cancelled.assignment_revision, 1)
        self.assertEqual(cancelled.scheduling_revision, 2)
        for action, payload, actor in [("accept", {}, EXECUTOR), ("cancel", {"reason": "again"}, MASTER),
                                       ("change_priority", {"priority": "high", "reason": "test"}, MASTER)]:
            self.expect_error("TRANSITION_CONFLICT", self.run_command, action, payload, actor=actor, order=cancelled)

    def test_closed_terminal(self):
        closed = self.review(self.submitted()).order
        self.expect_error("TRANSITION_CONFLICT", self.run_command, "cancel", {"reason": "test"}, actor=MASTER, order=closed)

    def test_missing_photo_submits_but_cannot_close(self):
        plan = self.submitted(after_photo_ids=[])
        self.assertEqual(plan.submission.completeness, Completeness.INCOMPLETE)
        self.assertIn("AFTER_PHOTO_REQUIRED", plan.submission.missing_evidence)
        self.expect_error("INCOMPLETE_SUBMISSION", self.review, plan)

    def test_missing_work_code_submits_but_cannot_close(self):
        plan = self.submitted(work_code_id=None)
        self.expect_error("INCOMPLETE_SUBMISSION", self.review, plan)

    def test_unknown_completeness_fails_closed(self):
        plan = self.submitted()
        for completeness in (None, "unknown"):
            with self.subTest(completeness=completeness):
                self.expect_error("INCOMPLETE_SUBMISSION", self.review, plan,
                                  submission=replace(plan.submission, completeness=completeness))

    def test_complete_flag_cannot_hide_missing_photo(self):
        plan = self.submitted(after_photo_ids=[])
        forged = replace(plan.submission, completeness=Completeness.COMPLETE, missing_evidence=())
        self.expect_error("INCOMPLETE_SUBMISSION", self.review, plan, submission=forged)

    def test_planned_work_does_not_require_photo(self):
        order = replace(self.started(), type="planned")
        plan = self.run_command("submit", {**submit_payload(), "after_photo_ids": []}, order=order)
        self.assertEqual(self.review(plan).order.status, Status.CLOSED)

    def test_rework_then_resubmit_new_attempt(self):
        plan = self.submitted(after_photo_ids=[])
        rework = self.review(plan, decision="rework")
        active = self.run_command("start", order=rework.order).order
        second = self.run_command("submit", submit_payload(), order=active, attempt=2)
        self.assertNotEqual(plan.submission.id, second.submission.id)
        self.assertEqual(second.submission.attempt_number, 2)
        self.assertEqual(plan.submission.completeness, Completeness.INCOMPLETE)
        self.assertEqual(active.due_at, self.order.due_at)

    def test_stale_submission_review(self):
        plan = self.submitted()
        for stale in (replace(plan.submission, assignment_revision=2), replace(plan.submission, order_id=uid(99)),
                      replace(plan.submission, id=uid(98))):
            self.expect_error("STALE_ASSIGNMENT", self.review, plan, submission=stale)

    def test_reassignment_preserves_prior_submission_object(self):
        plan = self.submitted()
        reassigned = self.run_command("reassign", {"assignment": {"executor_id": uid(30), "brigade_id": None},
                                     "reason": "Synthetic change"}, actor=MASTER, order=plan.order)
        self.assertIsNone(reassigned.order.current_submission_id)
        self.assertEqual(plan.submission.assignment_revision, 1)
        self.assertFalse(assessment_is_current(reassigned.order, plan.submission, 1))
        self.assertTrue(assessment_is_current(plan.order, plan.submission, 1))
        self.assertFalse(assessment_is_current(plan.order, plan.submission, 2))
        self.assertFalse(assessment_is_current(self.review(plan).order, plan.submission, 1))

    def test_priority_is_audited(self):
        plan = self.run_command("change_priority", {"priority": "emergency", "reason": "Synthetic urgency"}, actor=MASTER)
        self.assertEqual(dict(plan.events[0].details), {"previous_priority": "normal", "new_priority": "emergency"})
        self.assertEqual(plan.order.scheduling_revision, 2)

    def test_due_and_done_late_differ(self):
        late = NOW + timedelta(hours=2)
        active = self.started()
        self.assertTrue(is_overdue(active, late))
        self.assertFalse(is_overdue(active, active.due_at))
        submitted = self.run_command("submit", submit_payload(), order=active, now=late)
        self.assertTrue(submitted.submission.done_late)
        self.assertFalse(is_overdue(submitted.order, late))
        rework = self.review(submitted, decision="rework")
        self.assertTrue(is_overdue(rework.order, late))

    def test_unknown_material_and_work_code_rejected(self):
        self.expect_error("VALIDATION_FAILED", self.submitted, materials=[{"material_id": uid(99), "quantity": 1}])
        self.expect_error("VALIDATION_FAILED", self.submitted, work_code_id=uid(99))

    def test_foreign_photo_rejected(self):
        self.expect_error("FORBIDDEN", self.submitted, after_photo_ids=[uid(99)])

    def test_staged_before_photo(self):
        request = create_request()
        request["payload"]["before_photo_ids"] = [uid(9)]
        self.assertEqual(self.create(request).order.before_photo_ids, (uid(9),))
        request["payload"]["before_photo_ids"] = [uid(8)]
        self.expect_error("FORBIDDEN", self.create, request)

    def test_photo_validation_receives_destination_section(self):
        calls = []
        original = self.refs.staged_photo_usable
        def inspect(*args):
            calls.append(args)
            return original(*args)
        self.refs.staged_photo_usable = inspect
        raw = create_request()
        raw["payload"]["before_photo_ids"] = [uid(9)]
        self.create(raw)
        self.submitted()
        self.assertEqual([(call[1], call[3]) for call in calls], [("before", uid(1)), ("after", uid(1))])

    def test_photo_staged_in_other_section_is_rejected(self):
        class WrongSectionReferences(SyntheticReferences):
            def staged_photo_usable(self, photo_id, purpose, actor_id, destination_section_id, order_id, assignment_revision):
                staged_section_id = uid(99)
                return staged_section_id == destination_section_id
        self.refs = WrongSectionReferences()
        raw = create_request()
        raw["payload"]["before_photo_ids"] = [uid(9)]
        self.expect_error("FORBIDDEN", self.create, raw)
        self.expect_error("FORBIDDEN", self.submitted)

    def test_past_stored_order_remains_valid_and_no_deadline_extension(self):
        past = replace(self.order, due_at=NOW - timedelta(minutes=1))
        accepted = self.run_command("accept", order=past)
        self.assertEqual(accepted.order.due_at, past.due_at)
        self.assertTrue(is_overdue(accepted.order, NOW))
        raw = create_request()
        raw["payload"]["due_at"] = "2026-10-07T17:00:00Z"
        error = self.expect_error("VALIDATION_FAILED", self.create, raw)
        self.assertEqual(error.field_errors[0].code, "FUTURE_DEADLINE_REQUIRED")
        self.assertEqual(raw["payload"]["due_at"], "2026-10-07T17:00:00Z")

    def test_invalid_create_references(self):
        for key, value in [("equipment_id", uid(99)), ("assignment", {"executor_id": uid(99), "brigade_id": None})]:
            request = create_request()
            request["payload"][key] = value
            self.expect_error("VALIDATION_FAILED", self.create, request)

    def test_create_requires_master_and_future_deadline(self):
        self.expect_error("FORBIDDEN", self.create, actor=EXECUTOR)
        request = create_request()
        request["payload"]["due_at"] = "2026-10-07T16:00:00Z"
        self.expect_error("VALIDATION_FAILED", self.create, request)

    def test_domain_clock_requires_zone(self):
        self.expect_error("VALIDATION_FAILED", self.run_command, "accept", now=NOW.replace(tzinfo=None))

    def test_immutable_input_and_repeat_plan(self):
        original = self.order
        first = self.run_command("accept")
        self.assertEqual(original.status, Status.ISSUED)
        self.assertEqual(first.expected_version, original.version)
        one = self.create()
        two = self.create()
        self.assertEqual(one, two)

    def test_race_contract_only_adapter_cas_can_choose_winner(self):
        # Both plans are valid from the same read snapshot. Pure validation does
        # NOT serialize writers: production DB CAS remains mandatory and untested.
        accept = self.run_command("accept")
        cancel = self.run_command("cancel", {"reason": "Concurrent master"}, actor=MASTER)
        self.assertEqual(accept.expected_version, cancel.expected_version)
        self.assertEqual(accept.order.version, cancel.order.version)
        # Applying the second command after a refreshed snapshot detects staleness.
        self.expect_error("VERSION_CONFLICT", self.run_command, "cancel", {"reason": "Concurrent master"},
                          actor=MASTER, order=accept.order, version=cancel.expected_version)


class ValidationTests(unittest.TestCase):
    def request(self):
        return {"operation_id": uid(300), "expected_version": 3, "action": "submit", "payload": submit_payload()}

    def rejects(self, request):
        with self.assertRaises(DomainError) as caught:
            parse_command(request)
        self.assertEqual(caught.exception.code, "VALIDATION_FAILED")

    def test_unknown_envelope_fields_and_action(self):
        for key, value in [("actor_id", uid(99)), ("role", "master"), ("unknown", 1)]:
            self.rejects({**self.request(), key: value})
        self.rejects({**self.request(), "action": "auto_close"})

    def test_unknown_payload_and_missing_field(self):
        raw = self.request()
        raw["payload"]["score"] = 100
        self.rejects(raw)
        raw = self.request()
        del raw["payload"]["work_description"]
        self.rejects(raw)

    def test_versions_strict(self):
        for value in (True, "3", 0, -1, 3.0):
            self.rejects({**self.request(), "expected_version": value})
        self.rejects({**create_request(), "expected_version": 1})

    def test_empty_description_rejected(self):
        for value in ("", "   ", None, 123):
            raw = self.request()
            raw["payload"]["work_description"] = value
            self.rejects(raw)

    def test_quantity_is_finite_positive_bounded_three_decimal(self):
        for value in (0, -1, True, "1", math.nan, math.inf, 1.0001, 1000000000):
            with self.subTest(value=value):
                raw = self.request()
                raw["payload"]["materials"][0]["quantity"] = value
                self.rejects(raw)
        raw = self.request()
        raw["payload"]["materials"][0]["quantity"] = 0.125
        self.assertEqual(parse_command(raw).payload.materials[0].quantity, Decimal("0.125"))

    def test_duplicate_material_and_photos(self):
        raw = self.request()
        raw["payload"]["materials"] *= 2
        self.rejects(raw)
        raw = self.request()
        raw["payload"]["after_photo_ids"] *= 2
        self.rejects(raw)

    def test_invalid_uuid_and_time(self):
        self.rejects({**self.request(), "operation_id": "not-uuid"})
        for value in ("2026-10-07T18:00:00", "2026-10-07", "2026-10-07T18:00:00+25:00"):
            raw = create_request()
            raw["payload"]["due_at"] = value
            self.rejects(raw)

    def test_rfc3339_offsets_and_lowercase_normalize_to_utc(self):
        target = datetime(2026, 10, 7, 18, tzinfo=timezone.utc)
        for value in ("2026-10-07T23:00:00+05:00", "2026-10-07t18:00:00z",
                      "2026-10-07T13:00:00-05:00", "2026-10-07T18:00:00+00:00"):
            with self.subTest(value=value):
                self.assertEqual(timestamp(value, "due_at"), target)
                self.assertIs(timestamp(value, "due_at").tzinfo, timezone.utc)
        self.assertEqual(timestamp("2024-02-29t00:00:00.123z", "due_at").microsecond, 123000)

    def test_non_rfc3339_iso_dates_are_rejected(self):
        for value in ("2026-W41-3T18:00:00Z", "20261007T180000Z", "2026-10-07T18Z",
                      "2026-10-07T18:00:00,25Z", "2026-10-07T24:00:00Z",
                      "2026-10-07T18:00:60Z", "2026-02-30T18:00:00Z",
                      "2026-10-07T18:00:00+05:60", "2026-10-07T18:00:00Z\n"):
            with self.subTest(value=value):
                raw = create_request()
                raw["payload"]["due_at"] = value
                self.rejects(raw)

    def test_reason_required_and_no_payload_on_accept(self):
        self.rejects({"operation_id": uid(300), "expected_version": 1, "action": "cancel", "payload": {"reason": " "}})
        self.rejects({"operation_id": uid(300), "expected_version": 1, "action": "accept", "payload": {"reason": "surprise"}})

    def test_more_than_five_photos_rejected(self):
        raw = self.request()
        raw["payload"]["after_photo_ids"] = [uid(i) for i in range(10, 16)]
        self.rejects(raw)


if __name__ == "__main__":
    unittest.main()
