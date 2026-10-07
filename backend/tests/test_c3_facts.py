"""Pure synthetic tests; no authorization, DB, browser or model is exercised."""
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, localcontext
import inspect
import json
import unittest

from app.analytics.c3_facts import build_facts, facts_to_dict
from app.analytics.c3_types import AssessmentFact, MaterialReference, Period, Provenance, TrustedRows
from app.orders.models import (Assignment, Completeness, Decision, MaterialUse, Order,
                               OrderType, Priority, Review, Status, Submission, SubmitPayload)


def at(value):
    return datetime.fromisoformat("2026-09-" + value + "+00:00")


PERIOD = Period(at("02T00:00:00"), at("03T00:00:00"))


def order(identifier, *, issued="02T00:00:00", status=Status.CLOSED, current=None, revision=1):
    return Order(identifier, identifier, 10, revision, 1, status, OrderType.PLANNED,
                 "Работа <script>alert('x')</script>", "section-1", "equipment-1",
                 Assignment("current-executor", None), "master", at(issued),
                 at("03T00:00:00"), 10, Priority.NORMAL, "", (), current, at("03T00:00:00"))


def submission(identifier, oid, when, *, attempt=1, revision=1, late=False, quantity="0.1", executor="worker-1"):
    return Submission(identifier, oid, revision, attempt, executor, at(when), late,
        SubmitPayload("Выполнено", "code", (MaterialUse("material-1", Decimal(quantity)),), (), ""),
        Completeness.COMPLETE, ())


def review(identifier, sid, when, score, decision=Decision.CLOSE):
    return Review(identifier, sid, "master", decision, "Решение", score, at(when))


def fixture():
    """Independent hand-calculated cohorts, including history before the period."""
    orders = (order("o1", issued="01T00:00:00", current="s1"), order("o2", current="s22"),
              order("o3", current="s3"), order("o4", current="s4"),
              order("o5", status=Status.AI_REVIEW), order("o6", status=Status.IN_PROGRESS),
              replace(order("o7", status=Status.PAUSED), due_at=at("02T23:59:59")),
              order("o8", issued="01T00:00:00", current="s82", revision=2),
              order("o9", issued="03T00:00:00", status=Status.ISSUED))
    subs = (submission("s1", "o1", "01T23:00:00"),
            submission("s21", "o2", "02T01:00:00", quantity="9"),
            submission("s22", "o2", "02T01:00:00", attempt=2, late=None, quantity="0.2"),
            submission("s3", "o3", "02T04:00:00", late=True, quantity="0.001"),
            submission("s4", "o4", "02T06:00:00", quantity="7"),
            submission("s81", "o8", "01T20:00:00", executor="old-worker"),
            submission("s82", "o8", "02T07:00:00", revision=2, quantity="1.002", executor="new-worker"))
    reviews = (review("r1", "s1", "02T00:00:00", 0),
               review("r21", "s21", "02T01:00:00", 30, Decision.REWORK),
               review("r22", "s22", "02T02:00:00", 80), review("r3", "s3", "02T05:00:00", None),
               review("r4", "s4", "03T00:00:00", 99),
               review("r81", "s81", "01T21:00:00", 1, Decision.REWORK),
               review("r82", "s82", "02T08:00:00", 100))
    return TrustedRows(Provenance(True, "synthetic-unit:v1", "Один вымышленный участок",
        at("03T00:00:00"), datetime(2026, 8, 1, tzinfo=timezone.utc), "consistent_snapshot", True),
        orders, subs, reviews, materials=(MaterialReference("material-1", "Смазка", "кг"),))


class C3FactsTests(unittest.TestCase):
    def facts(self, rows=None):
        return build_facts(rows or fixture(), PERIOD)

    def metrics(self, facts=None):
        return {metric.name: metric for metric in (facts or self.facts()).metrics}

    def test_independent_flow_and_snapshot_cohorts(self):
        m = self.metrics()
        self.assertEqual(m["issued_orders"].source_ids, ("o2", "o3", "o4", "o5", "o6", "o7"))
        self.assertEqual(m["submitted_orders"].source_ids, ("o2", "o3", "o4", "o8"))
        self.assertEqual(m["submission_attempts"].value, Decimal(5))
        self.assertEqual(m["closed_orders"].source_ids, ("o1", "o2", "o3", "o8"))
        self.assertEqual(m["rework_decisions"].source_ids, ("r21",))
        self.assertEqual(m["awaiting_review"].source_ids, ("o5",))
        self.assertEqual(m["overdue_active"].source_ids, ("o7",))
        self.assertIsNone(m["issued_orders"].denominator)

    def test_zero_human_score_observed_null_missing_not_ai(self):
        metric = self.metrics()["human_score"]
        self.assertEqual((metric.numerator, metric.denominator, metric.eligible, metric.missing), (180, 3, 4, 1))
        self.assertEqual((metric.value, metric.status, metric.missing_source_ids), (Decimal(60), "partial", ("r3",)))
        self.assertEqual((metric.excluded, metric.excluded_source_ids), (0, ()))
        self.assertTrue(metric.small_sample)

    def test_close_linked_timeliness_differs_from_attempt_rate(self):
        m = self.metrics()
        self.assertEqual((m["closed_on_time"].numerator, m["closed_on_time"].denominator), (2, 3))
        self.assertEqual(m["closed_on_time"].value, Decimal("0.666666666667"))
        self.assertEqual((m["attempt_on_time"].numerator, m["attempt_on_time"].denominator), (3, 4))
        self.assertEqual(m["closed_on_time"].missing_source_ids, ("s22",))
        # Due-at of the current snapshot is deliberately irrelevant to captured done_late.
        self.assertFalse(next(o for o in self.facts().orders if o.order.id == "o3").is_overdue)

    def test_rework_same_instant_and_revision_no_cross_assignment_penalty(self):
        metric = self.metrics()["closed_with_rework"]
        self.assertEqual((metric.numerator, metric.denominator), (1, 4))
        ratings = {r.executor_id: r for r in self.facts().ratings}
        self.assertNotIn("current-executor", ratings)
        self.assertNotIn("old-worker", ratings)
        self.assertEqual(ratings["new-worker"].closed_with_rework.value, Decimal(0))
        self.assertIsNone(ratings["new-worker"].composite_score)
        self.assertEqual(ratings["new-worker"].composite_status, "unsupported_inputs")

    def test_materials_only_final_close_linked_exact_decimal(self):
        item, = self.facts().closed_materials
        self.assertEqual((item.quantity, item.unit), (Decimal("1.303"), "кг"))
        self.assertEqual(item.submission_ids, ("s1", "s22", "s3", "s82"))
        self.assertEqual(item.review_ids, ("r1", "r22", "r3", "r82"))
        item, = self.facts(replace(fixture(), materials=())).closed_materials
        self.assertIsNone(item.unit)
        self.assertIsNone(item.label)

    def test_decimal_context_is_independent_of_caller(self):
        with localcontext() as ctx:
            ctx.prec, ctx.rounding = 2, ROUND_DOWN
            facts = self.facts()
        self.assertEqual(self.metrics(facts)["closed_on_time"].value, Decimal("0.666666666667"))
        self.assertEqual(facts.closed_materials[0].quantity, Decimal("1.303"))

    def test_empty_complete_capture_zero_counts_null_rates(self):
        rows = replace(fixture(), orders=(), submissions=(), reviews=())
        facts = self.facts(rows)
        self.assertTrue(facts.totals_available)
        m = self.metrics(facts)
        self.assertEqual(m["closed_orders"].value, 0)
        self.assertEqual((m["human_score"].value, m["human_score"].denominator, m["human_score"].status), (None, 0, "no_cohort"))
        self.assertEqual(facts.ratings, ())

    def test_all_unscored_is_missing(self):
        rows = fixture()
        rows = replace(rows, reviews=tuple(replace(r, final_score=None) for r in rows.reviews))
        metric = self.metrics(self.facts(rows))["human_score"]
        self.assertEqual((metric.value, metric.numerator, metric.denominator, metric.missing, metric.status), (None, None, 0, 4, "missing"))

    def test_partial_and_drained_pages_never_become_totals(self):
        for coverage, history in (("partial_keyset", True), ("drained_moving_keyset", True), ("consistent_snapshot", False)):
            rows = fixture()
            with self.subTest(coverage=coverage, history=history):
                facts = self.facts(replace(rows, provenance=replace(rows.provenance, coverage=coverage, history_complete=history)))
                self.assertFalse(facts.totals_available)
                self.assertIsNone(facts.metrics)
                self.assertIsNone(facts.ratings)
                self.assertIsNone(facts.closed_materials)
                self.assertEqual(len(facts.orders), 9)

    def test_assessment_modes_preserved_and_never_replace_human_score(self):
        rows = fixture()
        model = AssessmentFact("a1", "s3", 1, "1", "model", "declared-model", "v1", 1,
            "satisfactory", 99, ("model text",), (), None, True, at("02T04:30:00"))
        fallback = replace(model, id="a2", mode="rules_fallback", model=None, model_version=None,
                           score=None, fallback_reason="provider_not_run", stale=False)
        manual = replace(fallback, id="a3", mode="manual", fallback_reason=None)
        facts = self.facts(replace(rows, assessments=(manual, model, fallback)))
        attempt = next(o for o in facts.orders if o.order.id == "o3").attempts[0]
        self.assertEqual(attempt.assessment_status, "recorded")
        self.assertEqual(tuple(a.mode for a in attempt.assessments), ("model", "rules_fallback", "manual"))
        self.assertEqual(self.metrics(facts)["human_score"].missing_source_ids, ("r3",))
        self.assertEqual(next(o for o in facts.orders if o.order.id == "o1").attempts[0].assessment_status, "absent")

    def test_direct_dto_cannot_override_incomplete_coverage_with_arrays(self):
        facts = self.facts()
        variants = [replace(facts, provenance=replace(facts.provenance, coverage=coverage))
                    for coverage in ("partial_keyset", "drained_moving_keyset")]
        variants += [replace(facts, provenance=replace(facts.provenance, history_complete=False)),
                     replace(facts, ratings=None), replace(facts, closed_materials=None)]
        for invalid in variants:
            with self.subTest(provenance=invalid.provenance):
                self.assertFalse(invalid.totals_available)
                wire = facts_to_dict(invalid)
                self.assertFalse(wire["totals_available"])
                for key in ("metrics", "ratings", "closed_materials"):
                    self.assertIsNone(wire[key])
                self.assertTrue(any(reason.startswith("totals:") for reason in wire["unavailable_reasons"]))

    def test_serialization_version_provenance_ids_nulls_and_no_float(self):
        body = facts_to_dict(self.facts())
        self.assertEqual(body["schema_version"], "c3-runtime-facts/1")
        self.assertTrue(body["provenance"]["synthetic"])
        self.assertEqual(body["closed_materials"][0]["quantity"], "1.303")
        self.assertTrue(body["totals_available"])
        self.assertIn("2026-09-03T00:00:00Z", json.dumps(body, allow_nan=False))
        self.assertEqual(body["orders"][0]["attempts"][0]["review"]["final_score"], 0)
        self.assertEqual(body["orders"][0]["order"]["description"], "Работа <script>alert('x')</script>")

    def test_permutation_is_deterministic_and_input_not_changed(self):
        rows = fixture()
        before = repr(rows)
        alternate = replace(rows, orders=rows.orders[::-1], submissions=rows.submissions[::-1], reviews=rows.reviews[::-1])
        self.assertEqual(facts_to_dict(self.facts(rows)), facts_to_dict(self.facts(alternate)))
        self.assertEqual(repr(rows), before)

    def test_utc_equivalent_period_and_half_open_end(self):
        offset_period = Period(datetime.fromisoformat("2026-09-02T05:00:00+05:00"),
                               datetime.fromisoformat("2026-09-03T05:00:00+05:00"))
        self.assertEqual(build_facts(fixture(), offset_period).metrics, self.facts().metrics)
        self.assertNotIn("o4", self.metrics()["closed_orders"].source_ids)
        self.assertNotIn("o9", self.metrics()["issued_orders"].source_ids)

    def test_duplicate_or_orphan_rows_fail_instead_of_disappearing(self):
        rows = fixture()
        invalid = (replace(rows, orders=rows.orders + (rows.orders[0],)),
                   replace(rows, submissions=rows.submissions + (replace(rows.submissions[0], id="another"),)),
                   replace(rows, submissions=(replace(rows.submissions[0], order_id="foreign"),) + rows.submissions[1:]),
                   replace(rows, reviews=rows.reviews + (replace(rows.reviews[0], id="another"),)),
                   replace(rows, orders=(replace(rows.orders[0], current_submission_id="s3"),) + rows.orders[1:]))
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(ValueError):
                self.facts(item)

    def test_bad_values_and_mismatched_snapshot_fail_closed(self):
        rows = fixture()
        for score in (True, 101, -1, Decimal("4.5")):
            with self.subTest(score=score), self.assertRaises(ValueError):
                self.facts(replace(rows, reviews=(replace(rows.reviews[0], final_score=score),) + rows.reviews[1:]))
        for quantity in (0.1, Decimal("NaN"), Decimal("0"), Decimal("1.0001")):
            sub = replace(rows.submissions[0], payload=replace(rows.submissions[0].payload,
                          materials=(MaterialUse("m", quantity),)))
            with self.subTest(quantity=quantity), self.assertRaises(ValueError):
                self.facts(replace(rows, submissions=(sub,) + rows.submissions[1:]))
        with self.assertRaises(ValueError):
            self.facts(replace(rows, orders=(replace(rows.orders[0], status=Status.AI_REVIEW),) + rows.orders[1:]))
        with self.assertRaises(ValueError):
            build_facts(rows, replace(PERIOD, start=PERIOD.start.replace(tzinfo=None)))
        with self.assertRaises(ValueError):
            build_facts(rows, replace(PERIOD, end=at("04T00:00:00")))

    def test_no_client_role_or_scope_authorization_parameter(self):
        self.assertEqual(tuple(inspect.signature(build_facts).parameters), ("rows", "period"))
        with self.assertRaises(ValueError):
            build_facts({"role": "manager", "allowed_section_ids": ["section-1"]}, PERIOD)
        with self.assertRaises(TypeError):
            build_facts(fixture(), PERIOD, role="admin")

    def test_incomplete_close_is_not_reported_as_valid(self):
        rows = fixture()
        for sub in (replace(rows.submissions[0], completeness=None),
                    replace(rows.submissions[0], completeness=Completeness.INCOMPLETE),
                    replace(rows.submissions[0], payload=replace(rows.submissions[0].payload, work_code_id=None))):
            with self.subTest(sub=sub), self.assertRaisesRegex(ValueError, "review.incomplete_close"):
                self.facts(replace(rows, submissions=(sub,) + rows.submissions[1:]))
        with self.assertRaisesRegex(ValueError, "review.incomplete_close"):
            self.facts(replace(rows, orders=(replace(rows.orders[0], type=OrderType.UNPLANNED),) + rows.orders[1:]))


if __name__ == "__main__":
    unittest.main()
