"""Offline arithmetic oracle, not an analytics endpoint or a C1 import adapter.

Only synthetic reduced facts. No backend imports, environment/config access,
network, DB, model calls or generated expected answers. Run with Python stdlib.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest

ACTIVE = {"issued", "queued", "accepted", "rejected", "in_progress", "paused", "rework"}
STATUSES = ACTIVE | {"done", "ai_review", "closed", "cancelled"}


def instant(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timezone required")
    return parsed.astimezone(timezone.utc)


def indexed(rows):
    result = {}
    for row in rows:
        if row["id"] in result:
            raise ValueError("duplicate fact ID")
        result[row["id"]] = row
    return result


def dedupe_events(rows):
    """Transport duplicates only; equal order_version never defines identity."""
    result = {}
    for row in rows:
        if row["id"] in result and result[row["id"]] != row:
            raise ValueError("conflicting duplicate event")
        result[row["id"]] = row
    return list(result.values())


def count(ids):
    ids = sorted(set(ids))
    return {"count": len(ids), "source_ids": ids}


def mean(values, source_ids):
    observed = [v for v in values if v is not None]
    eligible, n = len(values), len(observed)
    missing = eligible - n
    status = "no_cohort" if eligible == 0 else "missing" if n == 0 else "partial" if missing else "ok"
    return {"value": sum(observed) / n if n else None,
            "numerator": sum(observed) if n else None,
            "denominator": n, "eligible": eligible, "missing": missing,
            "status": status, "small_sample": 0 < n < 5,
            "source_ids": sorted(source_ids)}


def on_time(submission):
    late = submission["done_late"]
    if late is not None and type(late) is not bool:
        raise ValueError("done_late must be boolean or missing")
    return None if late is None else int(not late)


def summarize(facts):
    """Requires explicit full-history, consistent synthetic capture declarations.

    These declarations are preconditions, not proof of a production extractor.
    This small oracle deliberately rejects incomplete capture instead of
    pretending keyset pages can supply authoritative totals.
    """
    if facts["marker"] != "SYNTHETIC_METRIC_UNIT_ONLY":
        raise ValueError("this oracle accepts synthetic examples only")
    if facts["capture_complete"] is not True or facts["history_complete"] is not True:
        raise ValueError("complete consistent capture and linked history required")
    start, end, as_of = (instant(facts[k]) for k in ("start", "end", "domain_as_of"))
    instant(facts["captured_at_real"])  # Real/domain clocks are not compared.
    if not start < end <= as_of:
        raise ValueError("requires a completed half-open period")
    if instant(facts["snapshots_as_of"]) != as_of:
        raise ValueError("historical state cannot use a current snapshot")
    orders = indexed(facts["orders"])
    subs = indexed(facts["submissions"])
    reviews = indexed(facts["reviews"])
    scope = set(facts["allowed_section_ids"])
    for order in orders.values():
        if order["section_id"] not in scope:
            raise ValueError("out-of-scope fact; do not silently broaden access")
        if order["status"] not in STATUSES:
            raise ValueError("unknown status")
        if instant(order["issued_at"]) > as_of:
            raise ValueError("future order in as_of snapshot")
    attempts = set()
    for sub in subs.values():
        order = orders[sub["order_id"]]
        key = (sub["order_id"], sub["assignment_revision"], sub["attempt_number"])
        if key in attempts or not instant(order["issued_at"]) <= instant(sub["submitted_at"]) <= as_of:
            raise ValueError("invalid attempt identity/time")
        attempts.add(key)
    reviewed_submissions = set()
    closed = {}
    for review in reviews.values():
        sub = subs[review["submission_id"]]
        at = instant(review["created_at"])
        if not instant(sub["submitted_at"]) <= at <= as_of:
            raise ValueError("invalid review chronology")
        if sub["id"] in reviewed_submissions:
            raise ValueError("multiple immutable reviews for one submission")
        reviewed_submissions.add(sub["id"])
        score = review["final_score"]
        if score is not None and (type(score) is not int or not 0 <= score <= 100):
            raise ValueError("invalid human score")
        if review["decision"] not in {"close", "rework"}:
            raise ValueError("unknown human decision")
        if review["decision"] == "close":
            if sub["order_id"] in closed:
                raise ValueError("multiple closes violate terminal MVP")
            closed[sub["order_id"]] = review
    within = lambda value: start <= instant(value) < end
    cohort = [r for r in closed.values() if within(r["created_at"])]
    final_subs = [subs[r["submission_id"]] for r in cohort]
    period_subs = [s for s in subs.values() if within(s["submitted_at"])]
    rework_flags = []
    for final, close_review in zip(final_subs, cohort):
        had_rework = any(
            r["decision"] == "rework"
            and subs[r["submission_id"]]["order_id"] == final["order_id"]
            and subs[r["submission_id"]]["assignment_revision"] == final["assignment_revision"]
            and subs[r["submission_id"]]["attempt_number"] < final["attempt_number"]
            and instant(r["created_at"]) <= instant(close_review["created_at"])
            for r in reviews.values())
        rework_flags.append(int(had_rework))
    return {
        "issued_orders": count(o["id"] for o in orders.values() if within(o["issued_at"])),
        "submitted_orders": count(s["order_id"] for s in period_subs),
        "submission_attempts": count(s["id"] for s in period_subs),
        "closed_orders": count(s["order_id"] for s in final_subs),
        "rework_decisions": count(r["id"] for r in reviews.values()
                                  if r["decision"] == "rework" and within(r["created_at"])),
        "awaiting_review": count(o["id"] for o in orders.values() if o["status"] == "ai_review"),
        "overdue_active": count(o["id"] for o in orders.values()
                                if o["status"] in ACTIVE and instant(o["due_at"]) < as_of),
        "human_score": mean([r["final_score"] for r in cohort], [r["id"] for r in cohort]),
        "closed_on_time": mean([on_time(s) for s in final_subs], [s["id"] for s in final_subs]),
        "closed_with_rework": mean(rework_flags, [s["order_id"] for s in final_subs]),
        "attempt_on_time": mean([on_time(s) for s in period_subs], [s["id"] for s in period_subs]),
    }


def union_minutes_by_equipment(intervals, start, end, as_of):
    """Hypothetical authoritative downtime intervals, NOT pause events."""
    start, end = instant(start), min(instant(end), instant(as_of))
    groups = {}
    for equipment, began, restored in intervals:
        a = instant(began)
        b = instant(restored) if restored is not None else instant(as_of)
        if b < a:
            raise ValueError("reversed downtime interval")
        a, b = max(a, start), min(b, end)
        if a < b:
            groups.setdefault(equipment, []).append((a, b))
    total = 0.0
    for rows in groups.values():
        merged = []
        for a, b in sorted(rows):
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
            else:
                merged.append((a, b))
        total += sum((b - a).total_seconds() / 60 for a, b in merged)
    return total


class Examples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.example = json.loads(Path(__file__).with_name("worked-examples.json").read_text())

    def test_independent_expected_values(self):
        self.assertEqual(summarize(self.example["facts"]), self.example["expected"])

    def test_empty_cohort_is_not_zero_rate(self):
        f = deepcopy(self.example["facts"])
        f.update(start="2026-09-01T00:00:00Z", end="2026-09-02T00:00:00Z")
        result = summarize(f)
        self.assertEqual(result["closed_orders"]["count"], 0)
        self.assertIsNone(result["closed_on_time"]["value"])
        self.assertEqual(result["closed_on_time"]["status"], "no_cohort")

    def test_all_unscored_is_missing_and_ai_does_not_fill(self):
        f = deepcopy(self.example["facts"])
        for r in f["reviews"]:
            r["final_score"] = None
        result = summarize(f)["human_score"]
        self.assertEqual((result["value"], result["denominator"], result["missing"], result["status"]),
                         (None, 0, 4, "missing"))

    def test_missing_timeliness_is_not_on_time(self):
        f = deepcopy(self.example["facts"])
        f["submissions"][0]["done_late"] = None
        result = summarize(f)["closed_on_time"]
        self.assertEqual((result["numerator"], result["denominator"], result["missing"], result["status"]),
                         (2, 3, 1, "partial"))

    def test_score_zero_is_observed(self):
        result = summarize(self.example["facts"])["human_score"]
        self.assertEqual((result["numerator"], result["denominator"]), (180, 3))

    def test_utc_display_and_half_open_boundaries(self):
        self.assertEqual(instant("2026-10-02T00:00:00+05:00"), instant("2026-10-01T19:00:00Z"))
        result = summarize(self.example["facts"])
        self.assertIn("A", result["issued_orders"]["source_ids"])
        self.assertNotIn("F", result["issued_orders"]["source_ids"])
        self.assertNotIn("J", result["overdue_active"]["source_ids"])
        with self.assertRaises(ValueError):
            instant("2026-10-01T19:00:00")

    def test_known_zero_rate_differs_from_missing(self):
        result = mean([0, 0], ["s1", "s2"])
        self.assertEqual((result["value"], result["numerator"], result["denominator"], result["status"]),
                         (0.0, 0, 2, "ok"))

    def test_close_at_end_is_excluded_from_flow(self):
        f = deepcopy(self.example["facts"])
        next(r for r in f["reviews"] if r["id"] == "rG")["created_at"] = f["end"]
        self.assertEqual(summarize(f)["closed_orders"]["source_ids"], ["A", "B", "I"])

    def test_rework_same_domain_instant_uses_attempt_identity(self):
        f = deepcopy(self.example["facts"])
        next(r for r in f["reviews"] if r["id"] == "rB1")["created_at"] = "2026-10-01T23:00:00Z"
        next(s for s in f["submissions"] if s["id"] == "sB2")["submitted_at"] = "2026-10-01T23:00:00Z"
        self.assertEqual(summarize(f)["closed_with_rework"]["numerator"], 1)

    def test_empty_assessment_is_not_job_status_or_human_score(self):
        f = deepcopy(self.example["facts"])
        f["assessments"] = []
        self.assertEqual(summarize(f), self.example["expected"])

    def test_incomplete_capture_and_wrong_asof_are_rejected(self):
        for field, value in (("capture_complete", False), ("history_complete", False),
                             ("snapshots_as_of", "2026-10-03T19:00:00Z")):
            f = deepcopy(self.example["facts"])
            f[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                summarize(f)

    def test_duplicate_fact_and_cross_scope_fail(self):
        f = deepcopy(self.example["facts"])
        f["submissions"].append(deepcopy(f["submissions"][0]))
        with self.assertRaises(ValueError):
            summarize(f)
        f = deepcopy(self.example["facts"])
        f["orders"][0]["section_id"] = "unauthorized"
        with self.assertRaises(ValueError):
            summarize(f)

    def test_event_retry_dedup_is_not_version_dedup(self):
        done = dict(id="ev-done", kind="order.done", order_version=4, submission_id="sA")
        review = dict(id="ev-review", kind="order.ai_review_requested", order_version=4, submission_id="sA")
        result = dedupe_events([done, review, deepcopy(done)])
        self.assertEqual(len(result), 2)
        self.assertEqual(len({e["submission_id"] for e in result if e["kind"] == "order.done"}), 1)
        with self.assertRaises(ValueError):
            dedupe_events([done, {**done, "submission_id": "different"}])

    def test_repeat_fault_mature_cohort_excludes_early_positive(self):
        as_of = instant("2026-10-10T00:00:00Z")
        # These are hypothetical authoritative episode fields, absent from core.
        episodes = [("2026-10-01T00:00:00Z", True, True),
                    ("2026-10-02T00:00:00Z", True, False),
                    ("2026-10-07T00:00:00Z", True, True),
                    ("2026-10-01T00:00:00Z", False, False)]
        mature = [repeat for restored, continuous, repeat in episodes
                  if continuous and instant(restored) + timedelta(days=7) <= as_of]
        self.assertEqual((sum(mature), len(mature), len(episodes) - len(mature)), (1, 2, 2))

    def test_downtime_union_clipping_and_open_interval(self):
        rows = [("E1", "2026-10-02T10:00:00Z", "2026-10-02T10:30:00Z"),
                ("E1", "2026-10-02T10:20:00Z", "2026-10-02T10:50:00Z"),
                ("E2", "2026-10-02T10:10:00Z", "2026-10-02T10:20:00Z")]
        self.assertEqual(union_minutes_by_equipment(rows, "2026-10-02T10:00:00Z",
                         "2026-10-02T11:00:00Z", "2026-10-02T11:00:00Z"), 60)
        self.assertEqual(union_minutes_by_equipment(rows, "2026-10-02T10:15:00Z",
                         "2026-10-02T10:40:00Z", "2026-10-02T11:00:00Z"), 30)
        self.assertEqual(union_minutes_by_equipment([("E1", "2026-10-02T10:00:00Z", None)],
                         "2026-10-02T10:00:00Z", "2026-10-02T12:00:00Z", "2026-10-02T10:30:00Z"), 30)


if __name__ == "__main__":
    unittest.main(verbosity=2)
