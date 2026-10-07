"""Durable bounded account/source attempts; independent transaction commits first."""
from dataclasses import dataclass
from datetime import timedelta, timezone
from hashlib import sha256
from math import ceil

from app.core.auth_boundary import SystemRealClock
from app.core.pin_interfaces import AttemptDecision

BUCKETS = 65536


def bucket(key: str) -> int:
    # Fixed cardinality is deliberate: collisions can only throttle more. Do not
    # persist PINs, employee codes, IP addresses or unbounded attacker-chosen keys.
    return int.from_bytes(sha256(key.encode("utf-8")).digest()[:2], "big")


def real_now(clock):
    now = clock.now()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Security clock must be timezone-aware")
    return now.astimezone(timezone.utc)


@dataclass(frozen=True)
class LimitPolicy:
    account_attempts: int = 5
    source_attempts: int = 30
    window_seconds: int = 300

    def __post_init__(self):
        if any(type(v) is not int or v < 1 for v in
               (self.account_attempts, self.source_attempts, self.window_seconds)):
            raise ValueError("Positive integer limits required")
        if max(self.account_attempts, self.source_attempts) > 1000000 or self.window_seconds > 86400:
            raise ValueError("Limit policy exceeds bounded storage")


class PostgresAttemptLimiter:
    """Every process must use the same policy and schema, changed only at restart.

    Rows are locked in (kind,bucket) order. The attempt reservation commits even
    if PIN validation, authentication, or later session issuance fails. Storage
    outages propagate and prevent hash work/session issue. Limits never reset on
    successful login. No process-local success cache or wall-clock domain demo.
    """
    def __init__(self, connect, *, real_clock=None, policy=None):
        self.connect = connect
        self.clock = real_clock or SystemRealClock()
        self.policy = policy or LimitPolicy()

    def consume(self, *, account_key: str, source_key: str) -> AttemptDecision:
        from psycopg.rows import dict_row
        db = self.connect()
        if not db.autocommit:
            db.close()
            raise ValueError("Limiter requires a fresh autocommit connection")
        db.row_factory = dict_row
        decision = None
        with db:
            with db.transaction():
                keys = (("account", bucket(account_key), self.policy.account_attempts),
                        ("source", bucket(source_key), self.policy.source_attempts))
                rows = []
                for kind, key, limit in keys:
                    # Initial timestamp is rechecked after all blocking locks.
                    db.execute("""INSERT INTO auth_login_limits(kind,bucket,window_started_at,attempts)
                        VALUES (%s,%s,%s,0) ON CONFLICT(kind,bucket) DO NOTHING""",
                        (kind, key, real_now(self.clock)))
                    row = db.execute("""SELECT window_started_at,attempts FROM auth_login_limits
                        WHERE kind=%s AND bucket=%s FOR UPDATE""", (kind, key)).fetchone()
                    rows.append((kind, key, limit, row))
                now = real_now(self.clock)
                retry = 0
                for kind, key, limit, row in rows:
                    start, count = row["window_started_at"], row["attempts"]
                    until = start + timedelta(seconds=self.policy.window_seconds)
                    if now >= until:
                        start, count = now, 0
                        until = start + timedelta(seconds=self.policy.window_seconds)
                    if count >= limit:
                        retry = max(retry, max(1, ceil((until - now).total_seconds())))
                    db.execute("""UPDATE auth_login_limits SET window_started_at=%s,attempts=%s
                        WHERE kind=%s AND bucket=%s""", (start, min(count + 1, limit), kind, key))
                decision = AttemptDecision(retry == 0, retry)
        return decision
