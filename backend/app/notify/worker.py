"""Explicit durable delivery runner with conservative post-dispatch recovery."""
from dataclasses import replace
from datetime import timedelta
from math import isfinite
from uuid import uuid4

from app.core.auth_boundary import SystemRealClock
from app.jobs.models import WorkerPolicy
from app.persistence.postgres import PostgresRepository
from app.scheduler import SchedulePolicy
from app.scheduler.clocks import utc
from app.scheduler.models import IntentState
from .eligibility import check_delivery, recipient_is_current
from .models import DeliveryClaim, DeliveryOutcome, DispatchResult
from .postgres import DeliveryRepository


class DeliveryWorker:
    """One explicitly configured lane, no import/startup activation.

    Provider must impose an end-to-end timeout less than the renewed real lease.
    The single host lane also owns provider rate limiting. No user request may
    inject an adapter/configuration. Network calls occur only after prepare()
    commits intent and closes its connection, never inside a DB transaction.
    """
    def __init__(self, connect, *, adapter, channel, domain_clock, real_clock=None,
                 policy=None, schedule_policy=None):
        self.connect, self.adapter, self.channel = connect, adapter, channel
        self.domain_clock, self.real_clock = domain_clock, real_clock or SystemRealClock()
        self.policy = policy or WorkerPolicy()
        self.schedule_policy = schedule_policy or SchedulePolicy(channel=channel)
        if channel not in {'telegram','web_push','synthetic'} or self.schedule_policy.channel != channel:
            raise ValueError('Explicit consistent delivery channel required')
        bound = getattr(adapter,'max_call_seconds',None)
        if (isinstance(bound,bool) or not isinstance(bound,(int,float)) or not isfinite(bound)
                or bound <= 0 or bound+5 >= self.policy.lease.total_seconds()):
            raise ValueError('Provider total timeout plus safety margin must be below worker lease')
        self.max_call_seconds = float(bound)

    def _connection(self):
        from psycopg.rows import dict_row
        from psycopg.pq import TransactionStatus
        db = self.connect()
        if not db.autocommit or db.info.transaction_status != TransactionStatus.IDLE:
            db.close()
            raise ValueError('DeliveryWorker requires a fresh idle autocommit connection')
        db.row_factory = dict_row
        return db

    def _real(self):
        return utc(self.real_clock.now())

    def claim_one(self):
        with self._connection() as db:
            with db.transaction():
                now = self._real()
                claim = DeliveryRepository(db).claim(real_now=now,domain_now=utc(self.domain_clock.now()),
                    lease_until=now+self.policy.lease,token=str(uuid4()),channel=self.channel,
                    max_attempts=self.policy.max_attempts)
            return claim

    def prepare(self, claim):
        """Returns enriched claim only after durable dispatch intent commits."""
        with self._connection() as db:
            with db.transaction():
                db.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
                jobs = DeliveryRepository(db)
                order = PostgresRepository(db).load_order(claim.envelope.order_id,lock=True)
                allowed = order is not None and recipient_is_current(db,claim.envelope,order)
                # Order/recipient locks precede the job. Refresh time after waits.
                if not jobs.owns(claim,now=self._real(),lock=True) or not jobs.owns(claim,now=self._real()):
                    return DispatchResult('lost_lease',claim.envelope.job_id)
                if jobs.started(claim):
                    return DispatchResult('already_started',claim.envelope.job_id)
                eligibility = (check_delivery(db,claim.envelope,order,
                    domain_now=utc(self.domain_clock.now()),policy=self.schedule_policy)
                    if allowed else IntentState.STALE)
                now = self._real()
                if eligibility != IntentState.READY:
                    state = 'cancelled' if eligibility == IntentState.STALE else 'retry'
                    code = 'STALE_DELIVERY' if eligibility == IntentState.STALE else 'WAIT_DOMAIN'
                    updated = jobs.release(claim,state=state,code=code,now=now,
                        next_attempt_at=now+self.policy.retry_base,waiting=eligibility==IntentState.WAIT_DOMAIN)
                    return DispatchResult(state if updated else 'lost_lease',claim.envelope.job_id,code)
                if not jobs.owns(claim,now=now):
                    return DispatchResult('lost_lease',claim.envelope.job_id)
                lease_until = now+self.policy.lease
                jobs.begin_dispatch(claim,now=now,lease_until=lease_until)
                enriched = replace(claim,envelope=replace(claim.envelope,order_number=order.number),
                                   lease_until=lease_until)
            return enriched

    def finish(self, claim, outcome):
        if not isinstance(outcome,DeliveryOutcome):
            outcome = DeliveryOutcome('ambiguous','DELIVERY_INVALID_PROVIDER_RESULT')
        if outcome.state == 'synthetic_recorded' and self.channel != 'synthetic':
            outcome = DeliveryOutcome('ambiguous','DELIVERY_INVALID_PROVIDER_RESULT')
        with self._connection() as db:
            with db.transaction():
                jobs = DeliveryRepository(db)
                # This phase never waits for an order. It may audit a late response
                # but cannot revive a cancelled or expired/currently different job.
                owned = jobs.owns(claim,now=self._real(),lock=True)
                now = self._real()
                owned = owned and jobs.owns(claim,now=now)
                inserted = jobs.record_outcome(claim,outcome,now=now)
                if not owned or not inserted:
                    return DispatchResult('lost_lease',claim.envelope.job_id,outcome.code)
                state = {'accepted':'provider_accepted','retryable':'retry','permanent_failure':'failed',
                         'ambiguous':'failed','synthetic_recorded':'synthetic_recorded'}[outcome.state]
                if state == 'retry' and claim.attempts >= self.policy.max_attempts:
                    state = 'failed'
                # Never shorten an explicit provider retry-after wait.
                delay = max(self.policy.retry_delay(claim.attempts),
                            timedelta(seconds=outcome.retry_after_seconds or 0))
                updated = jobs.finish(claim,outcome,now=now,next_attempt_at=now+delay,state=state)
            return DispatchResult(state if updated else 'lost_lease',claim.envelope.job_id,outcome.code)

    def _retry_unstarted(self, claim):
        with self._connection() as db:
            with db.transaction():
                jobs = DeliveryRepository(db)
                if not jobs.owns(claim,now=self._real(),lock=True):
                    return DispatchResult('lost_lease',claim.envelope.job_id)
                now = self._real()
                if not jobs.owns(claim,now=now) or jobs.started(claim):
                    return DispatchResult('unconfirmed',claim.envelope.job_id)
                state = 'failed' if claim.attempts>=self.policy.max_attempts else 'retry'
                updated = jobs.release(claim,state=state,code='DELIVERY_PREPARE_ERROR',now=now,
                    next_attempt_at=now+self.policy.retry_delay(claim.attempts))
            return DispatchResult(state if updated else 'lost_lease',claim.envelope.job_id,'DELIVERY_PREPARE_ERROR')

    def run_once(self):
        claim = self.claim_one()
        if claim is None:
            return DispatchResult('idle')
        if isinstance(claim,str):
            return DispatchResult('failed',code=claim)
        try:
            prepared = self.prepare(claim)
        except Exception:
            # No provider call has begun; only retry if durable intent is absent.
            return self._retry_unstarted(claim)
        if not isinstance(prepared,DeliveryClaim):
            return prepared
        # A process may pause after prepare COMMIT. Do not start an external
        # operation with an expired or insufficient renewed lease budget. The
        # committed intent remains conservative; this never auto-resends it.
        if (prepared.lease_until-self._real()).total_seconds() <= self.max_call_seconds+5:
            return self.finish(prepared,DeliveryOutcome(
                'permanent_failure','DELIVERY_NOT_SENT_LEASE_BUDGET'))
        try:
            outcome = self.adapter.send(prepared.envelope)
        except Exception:
            # Transport may have transmitted; never guess safe retry from an exception.
            outcome = DeliveryOutcome('ambiguous','DELIVERY_PROVIDER_EXCEPTION_UNKNOWN')
        return self.finish(prepared,outcome)

    def run_batch(self, *, limit=20):
        if type(limit) is not int or not 1<=limit<=1000:
            raise ValueError('Batch limit must be in 1..1000')
        results=[]
        for _ in range(limit):
            result=self.run_once()
            if result.state=='idle':
                break
            results.append(result)
        return tuple(results)
