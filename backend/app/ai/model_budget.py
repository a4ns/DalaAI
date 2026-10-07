"""Atomic, restart-safe conservative reservations, not actual billed cost.

Host supplies one persistent SQLite path and stable approval ID across all workers.
No credentials, prompts, images, identities or provider response text are stored.
A reservation is never refunded, including timeout/429/cancellation/crash. Therefore
unknown remote outcomes cannot reset or silently exceed the approved local cap.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
from uuid import uuid4


class BudgetBlocked(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class BudgetPolicy:
    approval_id: str
    total_microusd: int
    per_call_microusd: int
    calls_per_minute: int = 5
    max_concurrent: int = 1
    period_id: str = 'default'
    period_microusd: int | None = None
    period_ends_at: float | None = None

    def __post_init__(self):
        if not isinstance(self.approval_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', self.approval_id):
            raise ValueError('BUDGET_APPROVAL_ID_INVALID')
        if not isinstance(self.period_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', self.period_id):
            raise ValueError('BUDGET_PERIOD_ID_INVALID')
        if self.period_microusd is None:
            object.__setattr__(self, 'period_microusd', self.total_microusd)
        for value in (self.total_microusd, self.period_microusd, self.per_call_microusd, self.calls_per_minute, self.max_concurrent):
            if type(value) is not int or value < 1:
                raise ValueError('BUDGET_POSITIVE_INTEGER_REQUIRED')
        if not self.per_call_microusd <= self.period_microusd <= self.total_microusd <= 1_000_000_000:
            raise ValueError('BUDGET_RANGE_INVALID')
        if self.period_ends_at is not None:
            import math
            if type(self.period_ends_at) not in (int,float) or not math.isfinite(self.period_ends_at) or self.period_ends_at<=0:
                raise ValueError('BUDGET_PERIOD_END_INVALID')
        if self.calls_per_minute > 60 or self.max_concurrent > 4:
            raise ValueError('BUDGET_RATE_RANGE_INVALID')


class SqliteBudgetLedger:
    """Short local transactions only; never hold a ledger lock over network I/O.

    Per-call upper bound must be calculated from the chosen provider's verified
    prices and the request's maximum text/image/output limits BEFORE activation.
    No supplied price is assumed correct here. Keep the same durable path; no
    automatic reset, refund, cleanup or budget expansion is provided.
    """
    def __init__(self, path: str | Path, policy: BudgetPolicy):
        if str(path) == ':memory:' or not isinstance(policy, BudgetPolicy):
            raise ValueError('PERSISTENT_BUDGET_PATH_REQUIRED')
        self.path, self.policy = str(path), policy
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS model_budget_policy '
                       '(id TEXT PRIMARY KEY, total INTEGER, per_call INTEGER, rate INTEGER, concurrency INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS model_budget_reservation '
                       '(id TEXT PRIMARY KEY, approval_id TEXT NOT NULL, period_id TEXT NOT NULL, reserved_at REAL NOT NULL, '
                       'amount INTEGER NOT NULL, outcome TEXT)')
            db.execute('CREATE INDEX IF NOT EXISTS model_budget_by_approval '
                       'ON model_budget_reservation(approval_id,reserved_at)')
            db.execute('CREATE TABLE IF NOT EXISTS model_budget_period '
                       '(approval_id TEXT, period_id TEXT, amount INTEGER, ends_at REAL, PRIMARY KEY(approval_id,period_id))')
            columns={r[1] for r in db.execute('PRAGMA table_info(model_budget_period)')}
            if 'ends_at' not in columns:
                db.execute('ALTER TABLE model_budget_period ADD COLUMN ends_at REAL')
            p = policy
            db.execute('INSERT OR IGNORE INTO model_budget_period(approval_id,period_id,amount,ends_at) VALUES(?,?,?,?)',
                       (p.approval_id, p.period_id, p.period_microusd,p.period_ends_at))
            period = db.execute('SELECT amount,ends_at FROM model_budget_period WHERE approval_id=? AND period_id=?',
                                (p.approval_id, p.period_id)).fetchone()
            if period != (p.period_microusd,p.period_ends_at):
                raise ValueError('BUDGET_PERIOD_CHANGED')
            db.execute('INSERT OR IGNORE INTO model_budget_policy VALUES(?,?,?,?,?)',
                       (p.approval_id, p.total_microusd, p.per_call_microusd, p.calls_per_minute, p.max_concurrent))
            row = db.execute('SELECT total,per_call,rate,concurrency FROM model_budget_policy WHERE id=?',
                             (p.approval_id,)).fetchone()
            if row != (p.total_microusd, p.per_call_microusd, p.calls_per_minute, p.max_concurrent):
                raise ValueError('BUDGET_POLICY_CHANGED')

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=1.0)
        try:
            with db:
                yield db
        finally:
            db.close()

    def reserve(self, *, now: float) -> str:
        import math
        if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
            raise ValueError('BUDGET_REAL_TIME_REQUIRED')
        p = self.policy
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            spent, calls, active = db.execute('SELECT COALESCE(SUM(amount),0), '
                'COALESCE(SUM(reserved_at>?),0), COALESCE(SUM(outcome IS NULL),0) '
                'FROM model_budget_reservation WHERE approval_id=?', (now - 60, p.approval_id)).fetchone()
            if spent + p.per_call_microusd > p.total_microusd:
                raise BudgetBlocked('provider_budget_exhausted')
            period_spent = db.execute('SELECT COALESCE(SUM(amount),0) FROM model_budget_reservation '
                'WHERE approval_id=? AND ((? IS NULL AND period_id=?) OR (? IS NOT NULL AND reserved_at<?))',
                (p.approval_id,p.period_ends_at,p.period_id,p.period_ends_at,p.period_ends_at)).fetchone()[0]
            if (p.period_ends_at is None or now<p.period_ends_at) and period_spent+p.per_call_microusd>p.period_microusd:
                raise BudgetBlocked('provider_period_budget_exhausted')
            if calls >= p.calls_per_minute:
                raise BudgetBlocked('provider_rate_limited')
            if active >= p.max_concurrent:
                raise BudgetBlocked('provider_concurrency_limited')
            token = str(uuid4())
            db.execute('INSERT INTO model_budget_reservation VALUES(?,?,?,?,?,NULL)',
                       (token, p.approval_id, p.period_id, now, p.per_call_microusd))
            return token

    def finish(self, token: str, outcome: str) -> None:
        if outcome not in {'valid', 'invalid', 'timeout', 'unavailable', 'rate_limited', 'cancelled'}:
            raise ValueError('BUDGET_OUTCOME_INVALID')
        with self._db() as db:
            db.execute('UPDATE model_budget_reservation SET outcome=? '
                       'WHERE id=? AND approval_id=? AND outcome IS NULL',
                       (outcome, token, self.policy.approval_id))

    def counters(self) -> dict:
        with self._db() as db:
            total, count, active = db.execute('SELECT COALESCE(SUM(amount),0), COUNT(*), '
                'COALESCE(SUM(outcome IS NULL),0) FROM model_budget_reservation WHERE approval_id=?',
                (self.policy.approval_id,)).fetchone()
            outcomes = dict(db.execute('SELECT outcome,COUNT(*) FROM model_budget_reservation '
                'WHERE approval_id=? AND outcome IS NOT NULL GROUP BY outcome', (self.policy.approval_id,)))
            period_spent = db.execute('SELECT COALESCE(SUM(amount),0) FROM model_budget_reservation '
                'WHERE approval_id=? AND ((? IS NULL AND period_id=?) OR (? IS NOT NULL AND reserved_at<?))',
                (self.policy.approval_id,self.policy.period_ends_at,self.policy.period_id,
                 self.policy.period_ends_at,self.policy.period_ends_at)).fetchone()[0]
        return {'period_ends_at':self.policy.period_ends_at,'period_reserved_upper_bound_microusd': period_spent, 'reserved_upper_bound_microusd': total, 'calls_reserved': count,
                'active_or_crash_unknown_client_calls': active, 'outcomes': outcomes, 'actual_billed_cost': None}
