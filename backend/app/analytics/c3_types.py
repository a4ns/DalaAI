"""One internal report DTO. TrustedRows is a precondition, never an RBAC grant."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from app.orders.models import Order, Review, Submission

SCHEMA_VERSION = "c3-runtime-facts/1"
COMPLETE_COVERAGE = frozenset({"consistent_snapshot", "frozen_complete_export"})
Coverage = Literal["consistent_snapshot", "frozen_complete_export", "partial_keyset", "drained_moving_keyset"]


@dataclass(frozen=True, slots=True)
class Provenance:
    synthetic: bool
    source_ref: str
    scope_description: str  # Server-authored display text, NOT authorization.
    domain_as_of: datetime
    captured_at_real: datetime
    coverage: Coverage
    history_complete: bool


@dataclass(frozen=True, slots=True)
class Period:
    start: datetime
    end: datetime
    display_timezone: Literal["Asia/Almaty"] = "Asia/Almaty"


@dataclass(frozen=True, slots=True)
class AssessmentFact:
    """Stored recommendation, separate from Review.final_score; no job inference."""
    id: str
    submission_id: str
    assignment_revision: int
    schema_version: str
    mode: Literal["model", "rules_fallback", "manual"]
    model: str | None
    model_version: str | None
    duration_ms: int
    recommendation: Literal["satisfactory", "rework_recommended", "needs_master_review"]
    score: int | None
    reasons: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    fallback_reason: str | None
    stale: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class MaterialReference:
    material_id: str
    label: str
    unit: str


@dataclass(frozen=True, slots=True)
class TrustedRows:
    """ONLY construct inside an authorized server repository or isolated fixture.

    Authentication, current object authorization, related-row scoping and a
    consistent complete extraction happen BEFORE this boundary. There is no
    role/scope input that can prove them. Never bind this class from HTTP JSON.
    """
    provenance: Provenance
    orders: tuple[Order, ...]
    submissions: tuple[Submission, ...]
    reviews: tuple[Review, ...]
    assessments: tuple[AssessmentFact, ...] = ()
    materials: tuple[MaterialReference, ...] = ()


@dataclass(frozen=True, slots=True)
class AttemptFact:
    submission: Submission
    review: Review | None
    assessments: tuple[AssessmentFact, ...]
    assessment_status: Literal["absent", "recorded"]


@dataclass(frozen=True, slots=True)
class OrderFact:
    order: Order
    is_overdue: bool
    attempts: tuple[AttemptFact, ...]


@dataclass(frozen=True, slots=True)
class MetricFact:
    name: str
    source_table: Literal["orders", "submissions", "reviews"]
    status: Literal["ok", "no_cohort", "missing", "partial"]
    numerator: Decimal | None
    denominator: int | None  # None for a count, not a rate with unknown n.
    eligible: int
    missing: int
    excluded: int
    value: Decimal | None
    source_ids: tuple[str, ...]  # Full eligible cohort, including missing.
    missing_source_ids: tuple[str, ...]
    excluded_source_ids: tuple[str, ...]
    small_sample: bool


@dataclass(frozen=True, slots=True)
class ExecutorRating:
    """Descriptive components, sorted by ID, never an ordinal employee ranking."""
    executor_id: str
    human_score: MetricFact
    closed_on_time: MetricFact
    closed_with_rework: MetricFact
    composite_score: None = None
    composite_status: Literal["unsupported_inputs"] = "unsupported_inputs"


@dataclass(frozen=True, slots=True)
class MaterialFact:
    material_id: str
    label: str | None
    unit: str | None
    quantity: Decimal
    order_ids: tuple[str, ...]
    submission_ids: tuple[str, ...]
    review_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AnalyticsFacts:
    schema_version: str
    provenance: Provenance
    period: Period
    orders: tuple[OrderFact, ...]
    metrics: tuple[MetricFact, ...] | None
    ratings: tuple[ExecutorRating, ...] | None
    closed_materials: tuple[MaterialFact, ...] | None
    unavailable_reasons: tuple[str, ...]

    @property
    def totals_available(self) -> bool:
        # Consumers may construct a DTO directly in isolated tests. Do not let
        # attached arrays override an explicitly incomplete provenance label.
        return (self.provenance.coverage in COMPLETE_COVERAGE
                and self.provenance.history_complete is True
                and self.metrics is not None and self.ratings is not None
                and self.closed_materials is not None)
