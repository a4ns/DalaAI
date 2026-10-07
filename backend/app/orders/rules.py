"""Pure transition planning. Never publishes, commits, notifies, or invokes AI."""
from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID, uuid5

from .models import (
    Action, Actor, Command, Completeness, CreatePayload, Decision, DomainError, Event,
    MissingEvidence, MutationPlan, Order, OrderType, PriorityPayload, ReassignPayload,
    Review, ReviewPayload, Role, Status, Submission, SubmitPayload,
)
from .ports import References
from .validation import invalid, parse_command, string

TERMINAL = frozenset({Status.CLOSED, Status.CANCELLED})
MASTER_ACTIONS = frozenset({Action.CREATE, Action.REVIEW, Action.REASSIGN, Action.CANCEL, Action.CHANGE_PRIORITY})
EXECUTOR_TRANSITIONS = {
    Action.QUEUE: ({Status.ISSUED}, Status.QUEUED, "order.queued"),
    Action.ACCEPT: ({Status.ISSUED, Status.QUEUED}, Status.ACCEPTED, "order.accepted"),
    Action.REJECT: ({Status.ISSUED}, Status.REJECTED, "order.rejected"),
    Action.START: ({Status.ACCEPTED, Status.REWORK}, Status.IN_PROGRESS, "order.started"),
    Action.PAUSE: ({Status.IN_PROGRESS}, Status.PAUSED, "order.paused"),
    Action.RESUME: ({Status.PAUSED}, Status.IN_PROGRESS, "order.resumed"),
}


def utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        invalid("domain_now", "AWARE_TIME_REQUIRED")
    return value.astimezone(timezone.utc)


def authorize(actor: Actor, section_id: str, action: Action, order: Order | None) -> None:
    needed = Role.MASTER if action in MASTER_ACTIONS else Role.EXECUTOR
    if actor.role != needed or section_id not in actor.section_ids:
        raise DomainError("FORBIDDEN", "Action is outside the current actor's scope")
    if needed == Role.EXECUTOR and (order is None or order.assignment.executor_id != actor.id):
        raise DomainError("FORBIDDEN", "Only the currently assigned executor may act")


def require_status(order: Order, allowed: set[Status] | frozenset[Status]) -> None:
    if order.status not in allowed:
        raise DomainError("TRANSITION_CONFLICT", "Action is not allowed from the current status",
                          current_version=order.version)


def check_assignment(payload: CreatePayload | ReassignPayload, section_id: str, refs: References) -> None:
    if refs.assignment_in_section(payload.assignment, section_id) is not True:
        invalid("payload.assignment", "UNKNOWN_OR_OUT_OF_SCOPE_ASSIGNMENT")


def check_photos(ids: tuple[str, ...], purpose: str, actor: Actor, destination_section_id: str,
                 order: Order | None, refs: References) -> None:
    for photo_id in ids:
        if refs.staged_photo_usable(photo_id, purpose, actor.id, destination_section_id,
                                    order.id if order else None,
                                    order.assignment_revision if order else None) is not True:
            raise DomainError("FORBIDDEN", "Photo is not usable for this actor and assignment")


def missing_evidence(payload: SubmitPayload, order_type: OrderType) -> tuple[MissingEvidence, ...]:
    missing = []
    if payload.work_code_id is None:
        missing.append(MissingEvidence.WORK_CODE_REQUIRED)
    if order_type == OrderType.UNPLANNED and not payload.after_photo_ids:
        missing.append(MissingEvidence.AFTER_PHOTO_REQUIRED)
    return tuple(missing)


def is_overdue(order: Order, domain_now: datetime) -> bool:
    return (order.status not in TERMINAL | {Status.DONE, Status.AI_REVIEW}
            and utc(domain_now) > order.due_at)


def assessment_is_current(order: Order, submission: Submission, assignment_revision: int) -> bool:
    """Old/background AI output cannot affect a reassigned, superseded or final order."""
    return (order.status == Status.AI_REVIEW
            and order.current_submission_id == submission.id
            and submission.order_id == order.id
            and order.assignment_revision == submission.assignment_revision == assignment_revision)


def prepare_new_command(raw: object, actor: Actor, *, order: Order | None,
                        references: References, domain_now: datetime,
                        order_number: str | None = None,
                        current_submission: Submission | None = None,
                        next_attempt_number: int = 1) -> MutationPlan:
    """Plan one NEW command after current authorization and receipt lookup.

    Replays must bypass this function and return their committed receipt. A
    caller must not save just ``plan.order``: the full plan is one transaction.
    IDs are stable for actor+operation_id; this does not implement idempotency.
    """
    command = parse_command(raw)
    now = utc(domain_now)
    payload = command.payload
    if command.action == Action.CREATE:
        assert isinstance(payload, CreatePayload)
        authorize(actor, payload.section_id, command.action, None)
        if order is not None:
            raise DomainError("TRANSITION_CONFLICT", "Create requires a new order")
        if payload.due_at <= now:
            invalid("payload.due_at", "FUTURE_DEADLINE_REQUIRED")
        if references.equipment_in_section(payload.equipment_id, payload.section_id) is not True:
            invalid("payload.equipment_id", "UNKNOWN_OR_OUT_OF_SCOPE_EQUIPMENT")
        check_assignment(payload, payload.section_id, references)
        check_photos(payload.before_photo_ids, "before", actor, payload.section_id, None, references)
        string(order_number, "order_number", maximum=80)
        new = Order(_id(actor, command, "order"), order_number, 1, 1, 1, Status.ISSUED,
                    payload.type, payload.description, payload.section_id, payload.equipment_id,
                    payload.assignment, actor.id, now, payload.due_at, payload.norm_minutes,
                    payload.priority, payload.comment, payload.before_photo_ids, None, now)
        event = _event(new, command, actor.id, None, Status.ISSUED, "order.created", now)
        return MutationPlan(new, 0, (event,))
    if order is None:
        raise DomainError("NOT_FOUND", "Order does not exist")
    authorize(actor, order.section_id, command.action, order)
    if command.expected_version != order.version:
        raise DomainError("VERSION_CONFLICT", "Order changed; refresh before a new action",
                          current_version=order.version)
    if order.status in TERMINAL:
        raise DomainError("TRANSITION_CONFLICT", "Final orders cannot be changed",
                          current_version=order.version)
    new = replace(order, version=order.version + 1, updated_at=now)
    reason = getattr(payload, "reason", None)
    details = ()
    if command.action in EXECUTOR_TRANSITIONS:
        allowed, target, kind = EXECUTOR_TRANSITIONS[command.action]
        require_status(order, allowed)
        new = replace(new, status=target)
    elif command.action == Action.CANCEL:
        kind = "order.cancelled"
        new = replace(new, status=Status.CANCELLED, scheduling_revision=order.scheduling_revision + 1)
    elif command.action == Action.REASSIGN:
        assert isinstance(payload, ReassignPayload)
        check_assignment(payload, order.section_id, references)
        if payload.assignment == order.assignment:
            invalid("payload.assignment", "NEW_ASSIGNMENT_REQUIRED")
        kind = "order.reassigned"
        details = (("previous_executor_id", order.assignment.executor_id),
                   ("new_executor_id", payload.assignment.executor_id),
                   ("previous_brigade_id", order.assignment.brigade_id),
                   ("new_brigade_id", payload.assignment.brigade_id))
        new = replace(new, status=Status.ISSUED, assignment=payload.assignment,
                      assignment_revision=order.assignment_revision + 1,
                      scheduling_revision=order.scheduling_revision + 1,
                      current_submission_id=None)
    elif command.action == Action.CHANGE_PRIORITY:
        assert isinstance(payload, PriorityPayload)
        kind = "order.priority_changed"
        details = (("previous_priority", order.priority.value), ("new_priority", payload.priority.value))
        new = replace(new, priority=payload.priority, scheduling_revision=order.scheduling_revision + 1)
    elif command.action == Action.SUBMIT:
        assert isinstance(payload, SubmitPayload)
        require_status(order, {Status.IN_PROGRESS})
        if type(next_attempt_number) is not int or next_attempt_number < 1:
            invalid("next_attempt_number")
        if payload.work_code_id is not None and references.work_code_exists(payload.work_code_id) is not True:
            invalid("payload.work_code_id", "UNKNOWN_WORK_CODE")
        for material in payload.materials:
            if references.material_exists(material.material_id) is not True:
                invalid("payload.materials", "UNKNOWN_MATERIAL")
        check_photos(payload.after_photo_ids, "after", actor, order.section_id, order, references)
        missing = missing_evidence(payload, order.type)
        sub = Submission(_id(actor, command, "submission"), order.id, order.assignment_revision,
                         next_attempt_number, actor.id, now, now > order.due_at, payload,
                         Completeness.INCOMPLETE if missing else Completeness.COMPLETE, missing)
        new = replace(new, status=Status.AI_REVIEW, current_submission_id=sub.id)
        events = (
            _event(new, command, actor.id, order.status, Status.DONE, "order.done", now, submission_id=sub.id),
            _event(new, command, None, Status.DONE, Status.AI_REVIEW, "order.ai_review_requested", now, submission_id=sub.id),
        )
        return MutationPlan(new, order.version, events, submission=sub)
    elif command.action == Action.REVIEW:
        assert isinstance(payload, ReviewPayload)
        require_status(order, {Status.AI_REVIEW})
        sub = current_submission
        if (sub is None or payload.submission_id != order.current_submission_id or sub.id != payload.submission_id
                or sub.order_id != order.id or sub.assignment_revision != order.assignment_revision):
            raise DomainError("STALE_ASSIGNMENT", "Review must target the current submission and assignment",
                              current_version=order.version)
        if payload.decision == Decision.CLOSE:
            if (sub.completeness != Completeness.COMPLETE or sub.missing_evidence
                    or missing_evidence(sub.payload, order.type)):
                raise DomainError("INCOMPLETE_SUBMISSION", "Required evidence has not been verified",
                                  current_version=order.version)
        new = replace(new, status=Status.CLOSED if payload.decision == Decision.CLOSE else Status.REWORK)
        review = Review(_id(actor, command, "review"), sub.id, actor.id, payload.decision,
                        payload.reason, payload.final_score, now)
        event = _event(new, command, actor.id, order.status, new.status, "order.reviewed", now,
                       submission_id=sub.id, reason=payload.reason,
                       details=(("decision", payload.decision.value),))
        return MutationPlan(new, order.version, (event,), review=review)
    else:
        raise DomainError("VALIDATION_FAILED", "Unsupported action")
    event = _event(new, command, actor.id, order.status, new.status, kind, now, reason=reason, details=details)
    return MutationPlan(new, order.version, (event,))


def _id(actor: Actor, command: Command, name: str) -> str:
    return str(uuid5(UUID(actor.id), command.operation_id + ":" + name))


def _event(order: Order, command: Command, actor_id: str | None, previous: Status | None,
           target: Status, kind: str, now: datetime, *, submission_id: str | None = None,
           reason: str | None = None, details: tuple[tuple[str, str | None], ...] = ()) -> Event:
    return Event(str(uuid5(UUID(order.id), command.operation_id + ":" + kind)), order.id,
                 order.version, order.assignment_revision, order.scheduling_revision, kind,
                 actor_id, command.operation_id, previous, target, submission_id, now, reason, details)
