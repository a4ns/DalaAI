"""Recoverable, fenced rules_fallback worker; no network or real model calls."""
from time import monotonic_ns
from uuid import UUID, uuid4, uuid5

from app.ai.models import InputValidationError
from app.ai.order_adapter import from_order_snapshot
from app.ai.rules import assess_rules
from app.core.auth_boundary import SystemRealClock
from app.persistence.postgres import PostgresRepository
from app.scheduler.clocks import utc
from .evidence import UnverifiedPhysicalReferences
from .models import LostLease, RunResult, WorkerPolicy
from .postgres import JobRepository


class AssessmentWorker:
    """Host-owned runner. Both clocks expose now(), as CommandService does.

    connect must return a NEW autocommit psycopg connection. claim_one returns
    only after its claim transaction commits and connection closes. complete()
    always starts a new transaction: order -> current evidence -> job. Expired
    token/attempt/lease completion rolls back assessment, event and version too.

    Only the existing small pure rules function runs under locks. This is NOT a
    provider seam: a future network/model adapter must compute outside the
    transaction, then re-evaluate current mandatory gates under the same fence.
    No background thread, global configuration, HTTP mount or scheduled runner
    starts implicitly on import. The application host must explicitly run this.
    """
    def __init__(self, connect, *, domain_clock, real_clock=None, policy=None,
                 references_factory=None):
        self.connect = connect
        self.domain_clock = domain_clock
        self.real_clock = real_clock or SystemRealClock()
        self.policy = policy or WorkerPolicy()
        # Trusted host injection only, never request data. Must be bounded/local:
        # no network I/O or additional out-of-order locks inside this transaction.
        self.references_factory = references_factory or UnverifiedPhysicalReferences
        if not isinstance(self.policy, WorkerPolicy):
            raise ValueError('Typed worker policy required')

    def _connection(self):
        from psycopg.rows import dict_row
        from psycopg.pq import TransactionStatus
        db = self.connect()
        if not db.autocommit or db.info.transaction_status != TransactionStatus.IDLE:
            db.close()
            raise ValueError('AssessmentWorker requires a fresh autocommit connection')
        db.row_factory = dict_row
        return db

    def _real(self):
        return utc(self.real_clock.now())

    def claim_one(self):
        with self._connection() as db:
            with db.transaction():
                now = self._real()
                claim = JobRepository(db).claim(now=now, lease_until=now+self.policy.lease,
                    token=str(uuid4()), max_attempts=self.policy.max_attempts)
            return claim

    def complete(self, claim):
        try:
            with self._connection() as db:
                with db.transaction():
                    db.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
                    repo, jobs = PostgresRepository(db), JobRepository(db)
                    # Immutable submission tells us which aggregate to lock.
                    sub = repo.load_submission(claim.submission_id)
                    if sub is None or sub.assignment_revision != claim.assignment_revision:
                        raise InputValidationError('JOB_SUBMISSION_MISMATCH')
                    order = repo.load_order(sub.order_id, lock=True)
                    if order is None:
                        raise InputValidationError('JOB_ORDER_MISSING')
                    refs = self.references_factory(repo, None, self._real(), order)
                    # Same server-owned evidence loader as human close. Its sorted
                    # photo SHARE locks protect file_valid until this commit.
                    codes, materials, photos = refs.closure_evidence(sub)
                    data, context = from_order_snapshot(order, sub, work_code_ids=codes,
                        material_ids=materials, photos=photos)
                    # This can wait on a competing claim. Refresh real time AFTER
                    # acquiring the row lock, then check again, never trust a
                    # pre-lock SELECT predicate's evaluation time.
                    if not jobs.owns(claim, now=self._real(), lock=True):
                        raise LostLease()
                    if not jobs.owns(claim, now=self._real()):
                        raise LostLease()
                    # Assessment chronology is business time. Sample once after
                    # locks; audit, leases and duration remain real/monotonic.
                    domain_now = utc(self.domain_clock.now())
                    if domain_now < max(order.updated_at, sub.submitted_at):
                        raise RuntimeError('Assessment business clock precedes snapshot')
                    started = monotonic_ns()
                    assessment, _ = assess_rules(data, context,
                        assessment_id=str(uuid5(UUID(claim.id), 'rules-assessment-v1')),
                        created_at=domain_now)
                    # Actual deterministic rule execution duration, never a model latency.
                    from dataclasses import replace
                    assessment = replace(assessment, duration_ms=(monotonic_ns()-started)//1_000_000)
                    jobs.persist_assessment(assessment)
                    if not assessment.stale:
                        jobs.publish_current(order, assessment,
                            domain_now=domain_now, real_now=self._real())
                    if not jobs.finish(claim, now=self._real()):
                        raise LostLease()
                return RunResult('done', claim.id, assessment.id, assessment.stale)
        except LostLease:
            return RunResult('lost_lease', claim.id)

    def record_failure(self, claim, *, invalid_input=False):
        with self._connection() as db:
            with db.transaction():
                jobs = JobRepository(db)
                if not jobs.owns(claim, now=self._real(), lock=True):
                    return RunResult('lost_lease', claim.id)
                # Failure handling may wait too. Re-read real time only after
                # taking this job-only lock; never acquire an order lock here.
                now = self._real()
                if not jobs.owns(claim, now=now):
                    return RunResult('lost_lease', claim.id)
                terminal = invalid_input or claim.attempts >= self.policy.max_attempts
                updated = jobs.fail(claim, now=now,
                    next_attempt_at=now+self.policy.retry_delay(claim.attempts), terminal=terminal,
                    code='ASSESSMENT_INVALID_INPUT' if invalid_input else 'ASSESSMENT_WORKER_ERROR')
            return RunResult(('failed' if terminal else 'retry') if updated else 'lost_lease', claim.id)

    def run_once(self):
        claim = self.claim_one()
        if claim is None:
            return RunResult('idle')
        if claim is False:
            return RunResult('exhausted')
        try:
            return self.complete(claim)
        except InputValidationError:
            return self.record_failure(claim, invalid_input=True)
        except Exception:
            # Never persist/log exception text, prompts, DSNs, images or identifiers
            # from supplied content. If DB is unavailable this update raises too;
            # the committed lease remains reclaimable after real-clock expiry.
            return self.record_failure(claim)

    def run_batch(self, *, limit=20):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('Batch limit must be in 1..1000')
        results = []
        for _ in range(limit):
            result = self.run_once()
            if result.state == 'idle':
                break
            results.append(result)
        return tuple(results)
