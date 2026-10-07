"""Durable shared business clock. No bootstrap, grants, automatic seeds or reset."""
from contextlib import contextmanager
from uuid import UUID

from app.core.auth_boundary import SystemRealClock
from app.core.auth_policy import AccessDenied
from app.orders.models import DomainError
from .clock import ClockSnapshot, DemoClockSettings, DemoClockUnavailable
from .commands import parse_control


def instance_uuid(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError()
        return value
    except (ValueError, AttributeError):
        raise ValueError("Canonical configured demo-instance UUID required") from None


class PostgresDemoBusinessClock:
    """Every read uses one committed row and a fresh PostgreSQL real-time sample.

    Readers need SELECT only. State/audit writes use one transaction and CAS.
    Authorization callbacks run after state-row lock waits. The outer service
    already holds current auth rows; no new inverse lock order is introduced.
    """
    def __init__(self, connect, *, settings, instance_id):
        if not isinstance(settings, DemoClockSettings) or not settings.enabled:
            raise ValueError("Use wall clock while demo clock is disabled")
        self.settings = settings
        self.connect = connect
        self.instance_id = instance_uuid(instance_id)

    @contextmanager
    def locked(self):
        # Compatibility with the control seam; serialization is in PostgreSQL.
        if not self.settings.enabled:
            raise DomainError("NOT_FOUND", "Demo clock is unavailable")
        yield

    @contextmanager
    def _transaction(self):
        from psycopg.rows import dict_row
        with self.connect() as db:
            if not db.autocommit:
                raise ValueError("Fresh autocommit clock connection required")
            db.row_factory = dict_row
            with db.transaction():
                db.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                db.execute("SET LOCAL lock_timeout = '1000ms'")
                db.execute("SET LOCAL statement_timeout = '3000ms'")
                yield db

    def _row(self, db, *, lock=False):
        # clock_timestamp is evaluated with this one MVCC mapping snapshot.
        query = "SELECT *,clock_timestamp() AS sampled_at FROM demo_clock_state WHERE instance_id=%s"
        row = db.execute(query + (" FOR UPDATE" if lock else ""), (self.instance_id,)).fetchone()
        if row is None or row["synthetic"] is not True:
            raise DemoClockUnavailable("Configured isolated clock state is missing")
        return row

    def _snapshot(self, row, real_now):
        from .clock import MAX_BUSINESS_SPAN
        from app.scheduler.clocks import utc
        if (type(row["version"]) is not int or not 0 <= row["version"] <= 2147483647
                or type(row["scale"]) is not int or not 0 <= row["scale"] <= 60
                or row["domain_limit"] != row["domain_start"] + MAX_BUSINESS_SPAN
                or not row["domain_start"] <= row["domain_anchor"] <= row["domain_limit"]):
            raise DemoClockUnavailable("Configured clock state failed validation")
        real_now = utc(real_now)
        snapshot = ClockSnapshot(str(row["instance_id"]), row["version"], utc(row["real_anchor"]),
            utc(row["domain_anchor"]), row["scale"], real_now, utc(row["domain_anchor"]),
            utc(row["domain_limit"]), "postgres_shared")
        from dataclasses import replace
        return replace(snapshot, business_now=snapshot.domain_now(real_now))

    def capture(self, *, authorize=None):
        with self._transaction() as db:
            row = self._row(db)
            if authorize is not None:
                authorize()
            # Reads have no state-row lock wait. Use the sample from the same
            # SELECT; next operation rereads, never a process-local cached map.
            return self._snapshot(row, row["sampled_at"])

    def now(self):
        return self.capture().business_now

    def apply(self, command, *, authorize=None):
        command = parse_control(command)
        if not callable(authorize):
            raise AccessDenied()
        with self._transaction() as db:
            row = self._row(db, lock=True)
            actor_id = instance_uuid(authorize())
            # Auth/state lock waits are over; never use pre-wait wall time.
            real_now = db.execute("SELECT clock_timestamp() AS sampled_at").fetchone()["sampled_at"]
            old = self._snapshot(row, real_now)
            if command["instance_id"] != old.instance_id or command["expected_version"] != old.revision:
                raise DomainError("VERSION_CONFLICT", "Clock changed; refresh before a new action", current_version=old.revision)
            if old.revision >= 2147483647:
                raise DemoClockUnavailable("Demo clock revision exhausted")
            from datetime import timedelta
            business_now = old.business_now
            scale = command["scale"] if command["action"] == "set_scale" else old.scale
            if command["action"] == "advance":
                business_now += timedelta(seconds=command["seconds"])
            if business_now > old.business_limit:
                raise DomainError("VALIDATION_FAILED", "Demo business-time horizon exceeded")
            changed = db.execute("""UPDATE demo_clock_state SET version=version+1,
                real_anchor=%s,domain_anchor=%s,scale=%s WHERE instance_id=%s AND version=%s""",
                (real_now, business_now, scale, self.instance_id, old.revision))
            if changed.rowcount != 1:
                raise DomainError("VERSION_CONFLICT", "Clock changed; refresh before a new action")
            db.execute("""INSERT INTO demo_clock_controls
                (instance_id,version,actor_id,action,recorded_at,previous_scale,scale,domain_anchor,advance_seconds)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (self.instance_id, old.revision+1, actor_id, command["action"], real_now,
                 old.scale, scale, business_now, command.get("seconds")))
            result = ClockSnapshot(old.instance_id, old.revision+1, real_now, business_now,
                scale, real_now, business_now, old.business_limit, "postgres_shared")
        return result  # Only after state and append-only audit COMMIT succeeds.


def build_domain_clock(settings, *, connect=None, instance_id=None):
    """Explicit assembly seam. Disabled mode performs no DB access or UUID parsing."""
    if not settings.enabled:
        return SystemRealClock()
    if connect is None:
        raise ValueError("Shared PostgreSQL clock store is required")
    return PostgresDemoBusinessClock(connect, settings=settings, instance_id=instance_id)
