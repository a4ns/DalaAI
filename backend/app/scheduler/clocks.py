"""Explicit clock domains. Demo time never controls a delivery lease or retry."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Protocol


def utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware datetime required")
    return value.astimezone(timezone.utc)


class RealClock(Protocol):
    def real_now(self) -> datetime: ...


class DomainClock(Protocol):
    def domain_now(self, real_now: datetime) -> datetime: ...


class SystemRealClock:
    def real_now(self) -> datetime:
        return datetime.now(timezone.utc)


class WallDomainClock:
    def domain_now(self, real_now: datetime) -> datetime:
        return utc(real_now)


@dataclass(frozen=True, slots=True)
class DemoDomainClock:
    """Pure explicit mapping, not a production setting or an admin endpoint.

    Recreate with new anchors to advance/reset the demo deliberately. A zero
    scale freezes the domain clock. Access control belongs to the host app.
    """
    real_anchor: datetime
    domain_anchor: datetime
    scale: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "real_anchor", utc(self.real_anchor))
        object.__setattr__(self, "domain_anchor", utc(self.domain_anchor))
        if isinstance(self.scale, bool) or not isinstance(self.scale, (int, float)):
            raise ValueError("scale must be a finite nonnegative number")
        if not isfinite(self.scale) or self.scale < 0:
            raise ValueError("scale must be a finite nonnegative number")

    def domain_now(self, real_now: datetime) -> datetime:
        elapsed = utc(real_now) - self.real_anchor
        return self.domain_anchor + timedelta(seconds=elapsed.total_seconds() * self.scale)


@dataclass(frozen=True, slots=True)
class ClockReadings:
    real_now: datetime
    domain_now: datetime


def read_clocks(real_clock: RealClock, domain_clock: DomainClock) -> ClockReadings:
    real_now = utc(real_clock.real_now())
    return ClockReadings(real_now, utc(domain_clock.domain_now(real_now)))
