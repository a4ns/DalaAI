"""Internal durable-worker values. No wire endpoint or provider credentials."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID


@dataclass(frozen=True, slots=True)
class WorkerPolicy:
    lease: timedelta = timedelta(seconds=30)
    retry_base: timedelta = timedelta(seconds=2)
    retry_cap: timedelta = timedelta(minutes=5)
    max_attempts: int = 5

    def __post_init__(self):
        if not isinstance(self.lease, timedelta) or not timedelta(0) < self.lease <= timedelta(minutes=10):
            raise ValueError("Worker lease must be positive and at most ten minutes")
        if (not isinstance(self.retry_base, timedelta) or not isinstance(self.retry_cap, timedelta)
                or not timedelta(0) < self.retry_base <= self.retry_cap <= timedelta(hours=1)):
            raise ValueError("Invalid bounded retry policy")
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 100:
            raise ValueError("max_attempts must be in 1..100")

    def retry_delay(self, attempts):
        return min(self.retry_cap, self.retry_base * (2 ** min(max(attempts - 1, 0), 20)))


@dataclass(frozen=True, slots=True)
class Claim:
    id: str
    submission_id: str
    assignment_revision: int
    attempts: int
    lease_token: str
    lease_until: datetime

    def __post_init__(self):
        for name in ("id", "submission_id", "lease_token"):
            if str(UUID(getattr(self, name))) != getattr(self, name):
                raise ValueError("Canonical UUID required")
        if (type(self.assignment_revision) is not int or self.assignment_revision < 1
                or type(self.attempts) is not int or self.attempts < 1):
            raise ValueError("Positive revision and attempt required")
        if self.lease_until.tzinfo is None or self.lease_until.utcoffset() is None:
            raise ValueError("Aware lease expiry required")


@dataclass(frozen=True, slots=True)
class RunResult:
    state: str
    job_id: str | None = None
    assessment_id: str | None = None
    stale: bool | None = None


class LostLease(Exception):
    """Raised inside a transaction so every provisional effect is rolled back."""


def assessment_event(order, assessment, *, sequence, domain_now, real_now):
    """Internal row follows accepted proposal.2 OrderEvent, including nullable actor."""
    from uuid import uuid5
    return {
        'id':str(uuid5(UUID(assessment.id), 'recorded-event')),
        'order_id':order.id,'sequence':sequence,'order_version':order.version+1,
        'assignment_revision':order.assignment_revision,'scheduling_revision':order.scheduling_revision,
        'kind':'order.assessment_recorded','reason':None,
        'details':{'assessment_id':assessment.id,'mode':'rules_fallback'},
        'actor_id':None,'operation_id':None,'from_status':'ai_review','to_status':'ai_review',
        'submission_id':assessment.submission_id,'occurred_at':domain_now,'recorded_at':real_now,
    }
