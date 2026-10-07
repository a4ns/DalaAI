"""Internal scheduler projection and intents; these are not wire/DB models."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
import re
from typing import TypeAlias
from uuid import UUID, uuid5

from .clocks import utc


ACTIVE_STATUSES = frozenset({"issued", "queued", "accepted", "rejected", "in_progress", "paused", "rework"})
UNACCEPTED_STATUSES = frozenset({"issued", "queued"})
INACTIVE_STATUSES = frozenset({"done", "ai_review", "closed", "cancelled"})
PRIORITIES = frozenset({"normal", "high", "emergency"})
REMINDER_LEAD = timedelta(minutes=30)
NORMAL_ACCEPT_TIMEOUT = timedelta(minutes=10)
EMERGENCY_ACCEPT_TIMEOUT = timedelta(minutes=3)
JOB_NAMESPACE = UUID("848c8d2b-6255-5f74-9466-27f0dd87a9a0")


def identifier(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("UUID string required")
    return str(UUID(value))


class JobKind(StrEnum):
    NEW_ORDER = "new_order"
    DEADLINE_REMINDER = "deadline_reminder"
    OVERDUE = "overdue"
    ACCEPTANCE_ESCALATION = "acceptance_escalation"
    MANAGER_ESCALATION = "manager_escalation"


@dataclass(frozen=True, slots=True)
class ScheduleSnapshot:
    """Trusted projection loaded from the current order and committed events.

    assignment_started_at is the latest current-assignment issue/reassign event,
    NOT necessarily Order.issued_at. rework_submission_id stays set during the
    resumed attempt; a reassign clears it. Never build this from request flags.
    Recipients must already be scoped, active and authorized by the repository.
    """
    order_id: str
    assignment_revision: int
    scheduling_revision: int
    status: str
    priority: str
    executor_id: str
    master_id: str
    due_at: datetime
    assignment_started_at: datetime
    rework_submission_id: str | None = None
    manager_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("order_id", "executor_id", "master_id"):
            object.__setattr__(self, name, identifier(getattr(self, name)))
        for name in ("assignment_revision", "scheduling_revision"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError("revisions must be positive integers")
        if self.status not in ACTIVE_STATUSES | INACTIVE_STATUSES:
            raise ValueError("unknown order status")
        if self.priority not in PRIORITIES:
            raise ValueError("unknown priority")
        for name in ("due_at", "assignment_started_at"):
            object.__setattr__(self, name, utc(getattr(self, name)))
        if self.rework_submission_id is not None:
            object.__setattr__(self, "rework_submission_id", identifier(self.rework_submission_id))
        if self.status == "rework" and self.rework_submission_id is None:
            raise ValueError("rework requires its reviewed submission identity")
        object.__setattr__(self, "manager_ids", tuple(sorted({identifier(x) for x in self.manager_ids})))

    @property
    def deadline_cycle(self) -> str:
        return "initial" if self.rework_submission_id is None else "rework:" + self.rework_submission_id


@dataclass(frozen=True, slots=True)
class SchedulePolicy:
    """One explicitly selected route. Non-case intervals are disabled by default.

    Changing policy must bump scheduling_revision for affected orders, or use a
    new approved policy namespace in the integration adapter. No route is sent.
    """
    channel: str
    overdue_repeat_every: timedelta | None = None
    acceptance_repeat_every: timedelta | None = None
    manager_escalation_after: timedelta | None = None
    manager_repeat_every: timedelta | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.channel, str) or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.channel) is None:
            raise ValueError("explicit channel code required")
        for name in ("overdue_repeat_every", "acceptance_repeat_every", "manager_repeat_every"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, timedelta) or value <= timedelta(0)):
                raise ValueError("repeat intervals must be positive timedeltas")
        delay = self.manager_escalation_after
        if delay is not None and (not isinstance(delay, timedelta) or delay < timedelta(0)):
            raise ValueError("manager escalation delay must be nonnegative")
        if self.manager_repeat_every is not None and delay is None:
            raise ValueError("manager repeat requires an escalation threshold")


JobKey: TypeAlias = tuple[str, int, int, str, str, str, str]


@dataclass(frozen=True, slots=True)
class JobIntent:
    order_id: str
    assignment_revision: int
    scheduling_revision: int
    kind: JobKind
    recipient_id: str
    channel: str
    bucket: str
    due_at: datetime  # DOMAIN threshold, never worker retry/lease time

    @property
    def key(self) -> JobKey:
        return (self.order_id, self.assignment_revision, self.scheduling_revision,
                self.kind.value, self.recipient_id, self.channel, self.bucket)

    @property
    def id(self) -> str:
        # All strings are generated canonical identifiers/codes, no separator
        # ambiguity. Persist tuple uniqueness as well; UUID alone is insufficient.
        return str(uuid5(JOB_NAMESPACE, "|".join(str(x) for x in self.key)))


class IntentState(StrEnum):
    READY = "ready"
    WAIT_DOMAIN = "wait_domain"
    STALE = "stale"
