"""Immutable internal types aligned with A6 proposal.1; not transport models."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TypeAlias


class Role(StrEnum):
    MASTER = "master"
    EXECUTOR = "executor"
    MANAGER = "manager"
    ADMIN = "admin"


class Status(StrEnum):
    ISSUED = "issued"
    QUEUED = "queued"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    DONE = "done"
    AI_REVIEW = "ai_review"
    REWORK = "rework"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class Action(StrEnum):
    CREATE = "create"
    QUEUE = "queue"
    ACCEPT = "accept"
    START = "start"
    RESUME = "resume"
    REJECT = "reject"
    PAUSE = "pause"
    SUBMIT = "submit"
    REVIEW = "review"
    REASSIGN = "reassign"
    CANCEL = "cancel"
    CHANGE_PRIORITY = "change_priority"


class OrderType(StrEnum):
    PLANNED = "planned"
    UNPLANNED = "unplanned"


class Priority(StrEnum):
    NORMAL = "normal"
    HIGH = "high"
    EMERGENCY = "emergency"


class Decision(StrEnum):
    CLOSE = "close"
    REWORK = "rework"


class Completeness(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


class MissingEvidence(StrEnum):
    WORK_CODE_REQUIRED = "WORK_CODE_REQUIRED"
    AFTER_PHOTO_REQUIRED = "AFTER_PHOTO_REQUIRED"


@dataclass(frozen=True, slots=True)
class Actor:
    """Trusted session context; never deserialize it from a command body."""
    id: str
    role: Role
    section_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class Assignment:
    executor_id: str
    brigade_id: str | None


@dataclass(frozen=True, slots=True)
class CreatePayload:
    type: OrderType
    description: str
    section_id: str
    equipment_id: str
    assignment: Assignment
    due_at: datetime
    norm_minutes: int
    priority: Priority
    comment: str
    before_photo_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EmptyPayload:
    pass


@dataclass(frozen=True, slots=True)
class ReasonPayload:
    reason: str


@dataclass(frozen=True, slots=True)
class MaterialUse:
    material_id: str
    quantity: Decimal


@dataclass(frozen=True, slots=True)
class SubmitPayload:
    work_description: str
    work_code_id: str | None
    materials: tuple[MaterialUse, ...]
    after_photo_ids: tuple[str, ...]
    comment: str


@dataclass(frozen=True, slots=True)
class ReviewPayload:
    submission_id: str
    decision: Decision
    reason: str
    final_score: int | None


@dataclass(frozen=True, slots=True)
class ReassignPayload:
    assignment: Assignment
    reason: str


@dataclass(frozen=True, slots=True)
class PriorityPayload:
    priority: Priority
    reason: str


Payload: TypeAlias = (CreatePayload | EmptyPayload | ReasonPayload | SubmitPayload
                      | ReviewPayload | ReassignPayload | PriorityPayload)


@dataclass(frozen=True, slots=True)
class Command:
    operation_id: str
    expected_version: int
    action: Action
    payload: Payload


@dataclass(frozen=True, slots=True)
class Order:
    id: str
    number: str
    version: int
    assignment_revision: int
    scheduling_revision: int
    status: Status
    type: OrderType
    description: str
    section_id: str
    equipment_id: str
    assignment: Assignment
    created_by: str
    issued_at: datetime
    due_at: datetime
    norm_minutes: int
    priority: Priority
    comment: str
    before_photo_ids: tuple[str, ...]
    current_submission_id: str | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Submission:
    id: str
    order_id: str
    assignment_revision: int
    attempt_number: int
    submitted_by: str
    submitted_at: datetime
    done_late: bool
    payload: SubmitPayload
    # Unknown hydration/legacy completeness must fail closed.
    completeness: Completeness | None
    missing_evidence: tuple[MissingEvidence, ...]


@dataclass(frozen=True, slots=True)
class Review:
    id: str
    submission_id: str
    reviewer_id: str
    decision: Decision
    reason: str
    final_score: int | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Event:
    id: str
    order_id: str
    order_version: int
    assignment_revision: int
    scheduling_revision: int
    kind: str
    actor_id: str | None
    operation_id: str
    from_status: Status | None
    to_status: Status
    submission_id: str | None
    occurred_at: datetime
    reason: str | None = None
    details: tuple[tuple[str, str | None], ...] = ()


@dataclass(frozen=True, slots=True)
class MutationPlan:
    """Uncommitted changes. An adapter must persist every part atomically."""
    order: Order
    expected_version: int
    events: tuple[Event, ...]
    submission: Submission | None = None
    review: Review | None = None


@dataclass(frozen=True, slots=True)
class FieldError:
    path: str
    code: str


class DomainError(Exception):
    def __init__(self, code: str, message: str, *, current_version: int | None = None,
                 field_errors: tuple[FieldError, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.current_version = current_version
        self.field_errors = field_errors
