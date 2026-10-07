"""Unmounted, single-owner synthetic business-time candidate; never a real clock."""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import RLock
from uuid import uuid4

from app.core.auth_boundary import SystemRealClock
from app.orders.models import DomainError
from app.scheduler.clocks import DemoDomainClock, utc

from .commands import MAX_ADVANCE_SECONDS, MAX_SCALE, parse_control

MAX_BUSINESS_SPAN = timedelta(days=7)
LABEL = "Синтетическое демо-время"


@dataclass(frozen=True)
class DemoClockSettings:
    enabled: bool = False
    mode: str = "health"
    isolated_demo: bool = False
    single_process: bool = False

    def __post_init__(self):
        if any(type(v) is not bool for v in (self.enabled, self.isolated_demo, self.single_process)):
            raise ValueError("Explicit boolean demo-clock flags required")
        if self.enabled and (self.mode != "demo" or not self.isolated_demo):
            raise ValueError("Demo clock requires an explicitly isolated demo")


class DemoClockUnavailable(RuntimeError):
    """Fixed safe failure; no wall-time fallback after business timestamps exist."""


@dataclass(frozen=True)
class ClockSnapshot:
    instance_id: str
    revision: int
    real_anchor: datetime
    business_anchor: datetime
    scale: int
    real_now: datetime
    business_now: datetime
    business_limit: datetime
    storage: str = "ephemeral_single_process"

    def domain_now(self, real_now):
        """Pinned scheduler mapping. Use the same captured snapshot for one tick."""
        real_now = utc(real_now)
        if real_now < self.real_anchor:
            raise DemoClockUnavailable("Real clock predates the pinned anchor")
        try:
            result = DemoDomainClock(self.real_anchor, self.business_anchor, self.scale).domain_now(real_now)
            if result > self.business_limit:
                raise DemoClockUnavailable("Demo business-time horizon exhausted")
            return result
        except (OverflowError, ValueError):
            raise DemoClockUnavailable("Business time is outside the supported range") from None

    def wire(self):
        stamp = lambda value: value.isoformat().replace("+00:00", "Z")
        return {"mode": "synthetic_demo", "label": LABEL, "instance_id": self.instance_id,
                "version": self.revision, "scale": self.scale,
                "real_now": stamp(self.real_now), "domain_now": stamp(self.business_now),
                "real_anchor": stamp(self.real_anchor), "domain_anchor": stamp(self.business_anchor),
                "domain_limit": stamp(self.business_limit),
                "storage": self.storage, "reset_supported": False,
                "limits": {"max_scale": MAX_SCALE, "max_advance_seconds": MAX_ADVANCE_SECONDS}}


class DemoBusinessClock:
    """One owner ONLY: immutable captures and CAS controls serialized by one lock.

    No env parsing, route mounting, SQL, security clock substitution, or reset.
    Restart loses the mapping. Do not bind this to surviving business data or
    separate worker processes: a shared durable checkpoint is a hard next gate.
    """
    def __init__(self, settings=None, *, real_clock=None):
        self.settings = settings or DemoClockSettings()
        self._real_clock = real_clock or SystemRealClock()
        self._lock = RLock()
        self._state = None
        self._last_real = None
        if self.settings.enabled:
            if not self.settings.single_process:
                raise ValueError("In-memory clock requires a single process")
            now = utc(self._real_clock.now())
            self._state = ClockSnapshot(str(uuid4()), 0, now, now, 1, now, now, now + MAX_BUSINESS_SPAN)
            self._start = now

    @contextmanager
    def locked(self):
        with self._lock:
            if not self.settings.enabled:
                raise DomainError("NOT_FOUND", "Demo clock is unavailable")
            yield

    def capture(self, *, authorize=None):
        with self.locked():
            if authorize is not None:
                authorize()
            now = utc(self._real_clock.now())
            if self._last_real is not None and now < self._last_real:
                raise DemoClockUnavailable("Real clock moved backwards")
            business_now = self._state.domain_now(now)
            if business_now > self._start + MAX_BUSINESS_SPAN:
                raise DemoClockUnavailable("Demo business-time horizon exhausted")
            self._last_real = now
            return ClockSnapshot(self._state.instance_id, self._state.revision,
                self._state.real_anchor, self._state.business_anchor, self._state.scale, now, business_now,
                self._state.business_limit)

    def now(self):
        """Command/discovery/worker domain_clock.now() port, NEVER real_clock."""
        return self.capture().business_now

    def apply(self, command, *, authorize=None):
        """Trusted service calls only, after current admin + Origin + CSRF checks."""
        with self.locked():
            command = parse_control(command)
            if authorize is not None:
                authorize()
            old = self.capture()
            if command["instance_id"] != old.instance_id or command["expected_version"] != old.revision:
                raise DomainError("VERSION_CONFLICT", "Clock changed; refresh before a new action",
                                  current_version=old.revision)
            if old.revision >= 2147483647:
                raise DemoClockUnavailable("Demo clock revision exhausted")
            scale, business_now = old.scale, old.business_now
            if command["action"] == "set_scale":
                scale = command["scale"]
            elif command["action"] == "advance":
                business_now += timedelta(seconds=command["seconds"])
            else:
                raise DomainError("INVALID_REQUEST", "Unsupported demo-clock action")
            if business_now > self._start + MAX_BUSINESS_SPAN:
                raise DomainError("VALIDATION_FAILED", "Demo business-time horizon exceeded")
            new = ClockSnapshot(old.instance_id, old.revision + 1, old.real_now, business_now,
                                scale, old.real_now, business_now, old.business_limit)
            self._state = new
            return new
