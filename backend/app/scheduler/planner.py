"""Stateless threshold reconciliation; no clock reads, persistence or sending."""
from datetime import datetime, timedelta
from typing import AbstractSet

from .clocks import utc
from .models import (
    ACTIVE_STATUSES, EMERGENCY_ACCEPT_TIMEOUT, NORMAL_ACCEPT_TIMEOUT, REMINDER_LEAD,
    UNACCEPTED_STATUSES, IntentState, JobIntent, JobKey, JobKind, SchedulePolicy,
    ScheduleSnapshot,
)


def is_overdue(order: ScheduleSnapshot, *, domain_now: datetime) -> bool:
    return order.status in ACTIVE_STATUSES and utc(domain_now) > order.due_at


def _job(order: ScheduleSnapshot, policy: SchedulePolicy, kind: JobKind,
         recipient_id: str, bucket: str, due_at: datetime) -> JobIntent:
    return JobIntent(order.order_id, order.assignment_revision, order.scheduling_revision,
                     kind, recipient_id, policy.channel, bucket, due_at)


def _window(anchor: datetime, now: datetime, interval: timedelta | None) -> tuple[int, datetime]:
    # Integer timedelta division avoids floating-point boundary ambiguity.
    index = 0 if interval is None else max(0, (now - anchor) // interval)
    return index, anchor if interval is None else anchor + index * interval


def _candidates(order: ScheduleSnapshot, now: datetime, policy: SchedulePolicy) -> tuple[JobIntent, ...]:
    """Current windows, including future one-shot thresholds for dispatch checks."""
    if order.status not in ACTIVE_STATUSES:
        return ()
    jobs: list[JobIntent] = []
    if order.status in UNACCEPTED_STATUSES:
        timeout = EMERGENCY_ACCEPT_TIMEOUT if order.priority == "emergency" else NORMAL_ACCEPT_TIMEOUT
        anchor = order.assignment_started_at + timeout
        index, threshold = _window(anchor, now, policy.acceptance_repeat_every)
        jobs.append(_job(order, policy, JobKind.ACCEPTANCE_ESCALATION, order.master_id,
                         f"acceptance:{index}", threshold))
    # A missed pre-deadline reminder is obsolete once the deadline is reached.
    if now < order.due_at:
        jobs.append(_job(order, policy, JobKind.DEADLINE_REMINDER, order.executor_id,
                         f"deadline:{order.deadline_cycle}:reminder", order.due_at - REMINDER_LEAD))
    index, threshold = _window(order.due_at, now, policy.overdue_repeat_every)
    for recipient_id in sorted({order.executor_id, order.master_id}):
        jobs.append(_job(order, policy, JobKind.OVERDUE, recipient_id,
                         f"deadline:{order.deadline_cycle}:overdue:{index}", threshold))
    if policy.manager_escalation_after is not None:
        anchor = order.due_at + policy.manager_escalation_after
        index, threshold = _window(anchor, now, policy.manager_repeat_every)
        for recipient_id in order.manager_ids:
            jobs.append(_job(order, policy, JobKind.MANAGER_ESCALATION, recipient_id,
                             f"deadline:{order.deadline_cycle}:manager:{index}", threshold))
    return tuple(jobs)


def _threshold_reached(job: JobIntent, order: ScheduleSnapshot, now: datetime) -> bool:
    if now < order.assignment_started_at:
        return False
    if job.kind in {JobKind.OVERDUE, JobKind.MANAGER_ESCALATION} and now <= order.due_at:
        return False  # A6: overdue is strictly > due_at, not >=.
    return job.due_at <= now


def plan_due_jobs(order: ScheduleSnapshot, *, domain_now: datetime, policy: SchedulePolicy,
                  known_keys: AbstractSet[JobKey] = frozenset()) -> tuple[JobIntent, ...]:
    """Return currently applicable intents, coalescing missed repeat windows.

    No in-memory last-tick cursor is needed. known_keys is an optional optimization
    from durable storage, never proof of concurrency safety. Concurrent planners
    may return identical intents; the outbox UNIQUE tuple is authoritative.
    """
    now = utc(domain_now)
    return tuple(job for job in _candidates(order, now, policy)
                 if _threshold_reached(job, order, now) and job.key not in known_keys)


def plan_assignment_notice(order: ScheduleSnapshot, *, policy: SchedulePolicy) -> JobIntent:
    """Command-transaction hook on create/reassign, not a notification send.

    Caller persists this with the command receipt/events. A periodic deadline
    reconciliation does not invent or repeatedly enqueue initial assignment jobs.
    """
    if order.status != "issued":
        raise ValueError("assignment notice requires a newly issued assignment")
    return _job(order, policy, JobKind.NEW_ORDER, order.executor_id, "initial", order.assignment_started_at)


def check_intent(job: JobIntent, order: ScheduleSnapshot, *, domain_now: datetime,
                 policy: SchedulePolicy) -> IntentState:
    """Recheck a loaded job immediately before an authorized provider call.

    WAIT_DOMAIN is not cancellation: a backwards demo jump may pause an otherwise
    valid job. STALE covers revision/recipient/status/threshold/window changes.
    Provider identity/subscription authorization and real-clock leases are separate.
    """
    now = utc(domain_now)
    if job.kind == JobKind.NEW_ORDER:
        if order.status not in UNACCEPTED_STATUSES:
            return IntentState.STALE
        current = _job(order, policy, JobKind.NEW_ORDER, order.executor_id, "initial", order.assignment_started_at)
        if job != current:
            return IntentState.STALE
        return IntentState.READY if now >= job.due_at else IntentState.WAIT_DOMAIN
    # A future repeat can have a larger bucket than the rewound clock's current
    # bucket. Reconstruct it at its own threshold before declaring it stale.
    comparison_now = max(now, job.due_at)
    for current in _candidates(order, comparison_now, policy):
        if job == current:
            return IntentState.READY if _threshold_reached(job, order, now) else IntentState.WAIT_DOMAIN
    return IntentState.STALE
