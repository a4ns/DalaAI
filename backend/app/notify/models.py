"""Internal delivery adapter seam. No public wire shape or credentials."""
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Literal, Protocol
from uuid import UUID

DELIVERY_KINDS = frozenset({'new_order','deadline_reminder','overdue','acceptance_escalation',
                          'manager_escalation','submission_ready','review_result'})


@dataclass(frozen=True, slots=True)
class DeliveryEnvelope:
    job_id: str
    order_id: str
    recipient_id: str
    kind: str
    assignment_revision: int = 1
    scheduling_revision: int = 1
    bucket: str = 'initial'
    channel: str = 'telegram'
    order_number: str | None = None
    due_at: datetime | None = None

    def __post_init__(self):
        for name in ('job_id','order_id','recipient_id'):
            if str(UUID(getattr(self,name))) != getattr(self,name):
                raise ValueError('Canonical UUID required')
        if self.kind not in DELIVERY_KINDS:
            raise ValueError('Unknown delivery kind')
        for value in (self.assignment_revision,self.scheduling_revision):
            if type(value) is not int or value < 1:
                raise ValueError('Positive revision required')
        if not isinstance(self.bucket,str) or not 1 <= len(self.bucket) <= 256:
            raise ValueError('Bounded nonempty bucket required')
        if self.channel not in {'telegram','web_push','synthetic'}:
            raise ValueError('Explicit approved delivery channel required')
        if self.due_at is not None and (self.due_at.tzinfo is None or self.due_at.utcoffset() is None):
            raise ValueError('Aware domain deadline required')


@dataclass(frozen=True, slots=True)
class DeliveryOutcome:
    state: Literal['accepted','retryable','permanent_failure','ambiguous','synthetic_recorded']
    code: str
    receipt: str | None = None
    retry_after_seconds: int | None = None

    def __post_init__(self):
        if self.state not in {'accepted','retryable','permanent_failure','ambiguous','synthetic_recorded'}:
            raise ValueError('Unknown delivery outcome')
        if not isinstance(self.code,str) or re.fullmatch(r'[A-Z][A-Z0-9_]{0,63}',self.code) is None:
            raise ValueError('Sanitized outcome code required')
        if self.receipt is not None and (not isinstance(self.receipt,str)
                or re.fullmatch(r'[A-Za-z0-9_:-]{1,160}',self.receipt) is None):
            raise ValueError('Bounded opaque provider receipt required')
        if self.state == 'accepted' and not self.receipt:
            raise ValueError('Provider acceptance requires receipt')
        if self.retry_after_seconds is not None and (type(self.retry_after_seconds) is not int
                or not 0 <= self.retry_after_seconds <= 366*86400 or self.state != 'retryable'):
            raise ValueError('Retry delay must be bounded nonnegative real seconds')


class DeliveryAdapter(Protocol):
    # End-to-end wall-time bound, not one timeout per network operation.
    max_call_seconds: float
    def send(self, envelope: DeliveryEnvelope) -> DeliveryOutcome: ...


@dataclass(frozen=True, slots=True)
class DeliveryClaim:
    envelope: DeliveryEnvelope
    attempts: int
    lease_token: str
    lease_until: datetime


@dataclass(frozen=True, slots=True)
class DispatchResult:
    state: str
    job_id: str | None = None
    code: str | None = None
