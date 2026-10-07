"""Pure projection of already-authorized rows. No DB, clock reads, I/O or RBAC.

Independent cohorts follow published C3 c5984436 and C4 4a5184fd. This internal
DTO is not a new HTTP contract and does not establish capture completeness.
"""
from collections import defaultdict
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from enum import Enum

from app.orders.models import Completeness, Decision, Order, OrderType, Review, Status, Submission
from .c3_types import (
    AnalyticsFacts, AssessmentFact, AttemptFact, COMPLETE_COVERAGE, ExecutorRating,
    MaterialFact, MaterialReference, MetricFact, OrderFact, Period, Provenance,
    SCHEMA_VERSION, TrustedRows,
)

ACTIVE = frozenset({Status.ISSUED, Status.QUEUED, Status.ACCEPTED, Status.REJECTED,
                    Status.IN_PROGRESS, Status.PAUSED, Status.REWORK})
DECIMAL_CONTEXT = Context(prec=40, rounding=ROUND_HALF_EVEN)
UNSUPPORTED = ("composite_rating:unsupported_inputs", "downtime:unsupported_inputs",
               "repeat_fault_7d:unsupported_inputs", "brigade_rating:unsupported_history",
               "order_event_log:not_supplied", "ai_job_state:not_supplied")


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def _instant(value: datetime) -> datetime:
    _require(isinstance(value, datetime) and value.tzinfo is not None
             and value.utcoffset() is not None, "timestamp.aware_required")
    return value.astimezone(timezone.utc)


def _index(rows, row_type, key="id"):
    result = {}
    for row in rows:
        _require(isinstance(row, row_type), "row.type")
        identifier = getattr(row, key)
        _require(isinstance(identifier, str) and bool(identifier), "row.id")
        _require(identifier not in result, "row.duplicate_id")
        result[identifier] = row
    return result


def _score(value: int | None) -> None:
    _require(value is None or type(value) is int and 0 <= value <= 100, "score.invalid")


def _validate(rows: TrustedRows, period: Period):
    _require(isinstance(rows, TrustedRows) and isinstance(period, Period), "input.typed_required")
    p = rows.provenance
    _require(isinstance(p, Provenance), "provenance.typed_required")
    _require(all(isinstance(items, tuple) for items in (rows.orders, rows.submissions,
             rows.reviews, rows.assessments, rows.materials)), "rows.immutable_tuple_required")
    _require(type(p.synthetic) is bool and type(p.history_complete) is bool, "provenance.boolean")
    _require(all(isinstance(v, str) and v.strip() for v in (p.source_ref, p.scope_description)), "provenance.required")
    _require(p.coverage in COMPLETE_COVERAGE | {"partial_keyset", "drained_moving_keyset"}, "coverage.invalid")
    start, end, as_of = map(_instant, (period.start, period.end, p.domain_as_of))
    _instant(p.captured_at_real)  # Real and domain clocks must not be compared.
    _require(start < end <= as_of and period.display_timezone == "Asia/Almaty", "period.invalid")
    orders = _index(rows.orders, Order)
    subs = _index(rows.submissions, Submission)
    reviews = _index(rows.reviews, Review)
    assessments = _index(rows.assessments, AssessmentFact)
    references = _index(rows.materials, MaterialReference, "material_id")
    for ref in references.values():
        _require(all(isinstance(v, str) and v.strip() for v in (ref.label, ref.unit)), "material.reference")
    attempts, reviewed, closes = set(), set(), {}
    for order in orders.values():
        _require(order.status in set(Status), "order.status")
        _require(_instant(order.issued_at) <= _instant(order.updated_at) <= as_of, "order.snapshot_time")
        _instant(order.due_at)
    for sub in subs.values():
        _require(sub.order_id in orders, "submission.orphan")
        order = orders[sub.order_id]
        _require(type(sub.assignment_revision) is int and 1 <= sub.assignment_revision <= order.assignment_revision
                 and type(sub.attempt_number) is int and sub.attempt_number >= 1, "submission.identity")
        identity = (sub.order_id, sub.assignment_revision, sub.attempt_number)
        _require(identity not in attempts, "submission.duplicate_attempt")
        attempts.add(identity)
        _require(_instant(order.issued_at) <= _instant(sub.submitted_at) <= as_of, "submission.time")
        _require(sub.done_late is None or type(sub.done_late) is bool, "submission.done_late")
        material_ids = set()
        for use in sub.payload.materials:
            _require(use.material_id not in material_ids, "material.duplicate_use")
            material_ids.add(use.material_id)
            q = use.quantity
            _require(isinstance(q, Decimal) and q.is_finite() and 0 < q <= 999999999, "material.quantity")
            with localcontext(DECIMAL_CONTEXT):
                _require(q == q.quantize(Decimal(".001")), "material.precision")
    for review in reviews.values():
        _require(review.submission_id in subs, "review.orphan")
        sub = subs[review.submission_id]
        _require(review.submission_id not in reviewed, "review.duplicate_submission")
        reviewed.add(review.submission_id)
        _require(_instant(sub.submitted_at) <= _instant(review.created_at) <= as_of, "review.time")
        _require(review.decision in {Decision.CLOSE, Decision.REWORK}, "review.decision")
        _score(review.final_score)
        if review.decision == Decision.CLOSE:
            _require(sub.completeness == Completeness.COMPLETE and not sub.missing_evidence
                     and sub.payload.work_code_id is not None
                     and (orders[sub.order_id].type != OrderType.UNPLANNED or bool(sub.payload.after_photo_ids)),
                     "review.incomplete_close")
            _require(sub.order_id not in closes, "review.duplicate_close")
            closes[sub.order_id] = review
    for assessment in assessments.values():
        _require(assessment.submission_id in subs, "assessment.orphan")
        sub = subs[assessment.submission_id]
        _require(assessment.assignment_revision == sub.assignment_revision, "assessment.revision")
        _require(_instant(sub.submitted_at) <= _instant(assessment.created_at) <= as_of, "assessment.time")
        _require(assessment.schema_version == "1" and assessment.mode in {"model", "rules_fallback", "manual"}, "assessment.mode")
        _require(assessment.recommendation in {"satisfactory", "rework_recommended", "needs_master_review"}, "assessment.recommendation")
        _require(type(assessment.stale) is bool and type(assessment.duration_ms) is int
                 and assessment.duration_ms >= 0, "assessment.metadata")
        _score(assessment.score)
    complete = p.coverage in COMPLETE_COVERAGE and p.history_complete
    for order in orders.values():
        current = subs.get(order.current_submission_id)
        if current is not None:
            _require(current.order_id == order.id and current.assignment_revision == order.assignment_revision, "order.current_submission")
        if complete:
            _require(order.current_submission_id is None or current is not None, "order.missing_current_submission")
            _require((order.id in closes) == (order.status == Status.CLOSED), "order.close_status")
            if order.id in closes:
                _require(closes[order.id].submission_id == order.current_submission_id, "order.close_current")
    return orders, subs, reviews, assessments, references, closes, complete


def _count(name, table, ids) -> MetricFact:
    source_ids = tuple(sorted(set(ids)))
    n = len(source_ids)
    return MetricFact(name, table, "ok", Decimal(n), None, n, 0, 0,
                      Decimal(n), source_ids, (), (), False)


def _mean(name, table, observations) -> MetricFact:
    observations = sorted(observations)
    ids = tuple(identifier for identifier, _ in observations)
    missing_ids = tuple(identifier for identifier, value in observations if value is None)
    values = [value for _, value in observations if value is not None]
    n, eligible = len(values), len(ids)
    numerator = Decimal(sum(values)) if n else None
    with localcontext(DECIMAL_CONTEXT):
        value = (numerator / n).quantize(Decimal(".000000000001")) if n else None
    status = "no_cohort" if not eligible else "missing" if not n else "partial" if missing_ids else "ok"
    return MetricFact(name, table, status, numerator, n, eligible, len(missing_ids),
                      0, value, ids, missing_ids, (), 0 < n < 5)


def _on_time(submission: Submission) -> int | None:
    return None if submission.done_late is None else int(not submission.done_late)


def build_facts(rows: TrustedRows, period: Period) -> AnalyticsFacts:
    """Project server-trusted rows. Names/declarations here do not authorize them."""
    orders, subs, reviews, assessments, references, closes, complete = _validate(rows, period)
    review_by_sub = {r.submission_id: r for r in reviews.values()}
    ai_by_sub, subs_by_order, rework_by_revision = defaultdict(list), defaultdict(list), defaultdict(list)
    for a in assessments.values():
        ai_by_sub[a.submission_id].append(a)
    for sub in subs.values():
        subs_by_order[sub.order_id].append(sub)
    for review in reviews.values():
        if review.decision == Decision.REWORK:
            sub = subs[review.submission_id]
            rework_by_revision[sub.order_id, sub.assignment_revision].append((sub, review))
    order_facts = []
    for order in sorted(orders.values(), key=lambda o: o.id):
        attempts = []
        for sub in sorted(subs_by_order[order.id], key=lambda s: (s.assignment_revision, s.attempt_number, s.id)):
            ai = tuple(sorted(ai_by_sub[sub.id], key=lambda a: (_instant(a.created_at), a.id)))
            attempts.append(AttemptFact(sub, review_by_sub.get(sub.id), ai, "recorded" if ai else "absent"))
        order_facts.append(OrderFact(order, order.status in ACTIVE and order.due_at < rows.provenance.domain_as_of, tuple(attempts)))
    if not complete:
        return AnalyticsFacts(SCHEMA_VERSION, rows.provenance, period, tuple(order_facts),
                              None, None, None, ("totals:incomplete_or_moving_capture",) + UNSUPPORTED)
    inside = lambda at: period.start <= at < period.end
    cohort = [(subs[r.submission_id], r) for r in closes.values() if inside(r.created_at)]
    period_subs = [s for s in subs.values() if inside(s.submitted_at)]

    def components(selected):
        reworks = [(s.order_id, int(any(earlier.attempt_number < s.attempt_number
                    and r.created_at <= close.created_at for earlier, r in
                    rework_by_revision[s.order_id, s.assignment_revision]))) for s, close in selected]
        return (_mean("human_score", "reviews", [(r.id, r.final_score) for _, r in selected]),
                _mean("closed_on_time", "submissions", [(s.id, _on_time(s)) for s, _ in selected]),
                _mean("closed_with_rework", "orders", reworks))

    metrics = (
        _count("issued_orders", "orders", (o.id for o in orders.values() if inside(o.issued_at))),
        _count("submitted_orders", "orders", (s.order_id for s in period_subs)),
        _count("submission_attempts", "submissions", (s.id for s in period_subs)),
        _count("closed_orders", "orders", (s.order_id for s, _ in cohort)),
        _count("rework_decisions", "reviews", (r.id for r in reviews.values() if r.decision == Decision.REWORK and inside(r.created_at))),
        _count("awaiting_review", "orders", (o.id for o in orders.values() if o.status == Status.AI_REVIEW)),
        _count("overdue_active", "orders", (o.order.id for o in order_facts if o.is_overdue)),
        *components(cohort),
        _mean("attempt_on_time", "submissions", [(s.id, _on_time(s)) for s in period_subs]),
    )
    by_executor = defaultdict(list)
    for sub, review in cohort:
        by_executor[sub.submitted_by].append((sub, review))
    ratings = tuple(ExecutorRating(identifier, *components(selected))
                    for identifier, selected in sorted(by_executor.items()))
    material_uses = defaultdict(list)
    for sub, review in cohort:
        for use in sub.payload.materials:
            material_uses[use.material_id].append((use.quantity, sub, review))
    materials = []
    for identifier, uses in sorted(material_uses.items()):
        ref = references.get(identifier)
        with localcontext(DECIMAL_CONTEXT):
            quantity = sum((q for q, _, _ in uses), Decimal(0))
        materials.append(MaterialFact(identifier, ref.label if ref else None, ref.unit if ref else None, quantity,
            tuple(sorted({s.order_id for _, s, _ in uses})), tuple(sorted(s.id for _, s, _ in uses)),
            tuple(sorted(r.id for _, _, r in uses))))
    return AnalyticsFacts(SCHEMA_VERSION, rows.provenance, period, tuple(order_facts),
                          metrics, ratings, tuple(materials), UNSUPPORTED)


def facts_to_dict(facts: AnalyticsFacts) -> dict[str, object]:
    """Lossless JSON-ready projection: Decimal strings, UTC timestamps, real nulls."""
    _require(isinstance(facts, AnalyticsFacts) and facts.schema_version == SCHEMA_VERSION, "facts.version")

    def wire(value):
        if is_dataclass(value):
            return {f.name: wire(getattr(value, f.name)) for f in fields(value)}
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, datetime):
            return _instant(value).isoformat().replace("+00:00", "Z")
        if isinstance(value, Decimal):
            _require(value.is_finite(), "decimal.finite_required")
            return format(value, "f")
        if isinstance(value, tuple):
            return [wire(item) for item in value]
        if value is None or type(value) in (str, int, bool):
            return value
        raise ValueError("facts.unsupported_value")

    result = wire(facts)
    result["totals_available"] = facts.totals_available
    if not facts.totals_available:
        # Preserve coverage truth even for inconsistently hand-constructed DTOs.
        for key in ("metrics", "ratings", "closed_materials"):
            result[key] = None
        if not any(reason.startswith("totals:") for reason in result["unavailable_reasons"]):
            result["unavailable_reasons"].append("totals:unavailable_or_inconsistent_capture")
    return result
