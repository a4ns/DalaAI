"""REAL PostgreSQL dispatcher tests; all network adapters are explicitly fake."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_persistence_postgres as fixture
from app.notify.models import DeliveryOutcome
from app.notify.worker import DeliveryWorker
from app.notify.postgres import DeliveryRepository
from app.persistence.postgres import PostgresRepository
from app.scheduler import SchedulePolicy


class FakeAdapter:
    max_call_seconds = 1
    def __init__(self, outcome=None, callback=None):
        self.outcome = outcome or DeliveryOutcome('accepted','TELEGRAM_API_ACCEPTED','telegram:100')
        self.calls = []
        self.callback = callback
    def send(self,envelope):
        self.calls.append(envelope)
        if self.callback:
            self.callback(envelope)
        return self.outcome


class DeliveryPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.PostgresCommandTests.setUpClass.__func__(cls)
    for _name in ('connect','drop_schema','query','run_command','create','action','start','stage','submit','review'):
        locals()[_name] = getattr(fixture.PostgresCommandTests,_name)

    def setUp(self):
        fixture.PostgresCommandTests.setUp(self)
        self.service.policy = SchedulePolicy(channel='telegram')
        self.adapter = FakeAdapter()
        self.worker = DeliveryWorker(self.connect,adapter=self.adapter,channel='telegram',
                                     domain_clock=self.domain,real_clock=self.real)

    def submitted(self):
        order_id = self.start()
        response,_ = self.submit(order_id)
        return order_id,response.body['submission_id']

    def job(self,job_id):
        return self.query('SELECT * FROM delivery_jobs WHERE id=%s',(job_id,))[0]

    def test_api_acceptance_commits_receipt_without_order_mutation(self):
        response,_ = self.create()
        order_id = response.body['order']['id']
        result = self.worker.run_once()
        self.assertEqual(result.state,'provider_accepted')
        job = self.job(result.job_id)
        self.assertEqual(job['provider_receipt'],'telegram:100')
        self.assertEqual(job['sent_at'],self.real.now())
        self.assertEqual(job['attempts'],1)
        self.assertIsNone(job['lease_token'])
        self.assertEqual(self.query('SELECT version,status FROM orders WHERE id=%s',(order_id,))[0],
                         {'version':1,'status':'issued'})
        self.assertEqual(self.query('SELECT count(*) AS n FROM order_events')[0]['n'],1)
        self.assertEqual(len(self.query('SELECT * FROM delivery_dispatches')),1)
        self.assertEqual(self.query('SELECT outcome FROM delivery_dispatch_results')[0]['outcome'],'accepted')
        self.assertEqual(self.worker.run_once().state,'idle')
        self.assertEqual(len(self.adapter.calls),1)

    def test_network_runs_only_after_intent_commit_and_without_database_locks(self):
        self.create()
        def inspect(envelope):
            self.assertEqual(len(self.query('SELECT * FROM delivery_dispatches')),1)
            with self.connect() as db:
                with db.transaction():
                    db.execute('SELECT id FROM orders WHERE id=%s FOR UPDATE NOWAIT',(envelope.order_id,))
                    db.execute('SELECT id FROM delivery_jobs WHERE id=%s FOR UPDATE NOWAIT',(envelope.job_id,))
        self.adapter.callback = inspect
        self.assertEqual(self.worker.run_once().state,'provider_accepted')

    def test_crashed_pre_dispatch_claim_reclaims_and_fences_old_worker(self):
        self.create()
        old = self.worker.claim_one()
        self.real.value = old.lease_until
        current = self.worker.claim_one()
        self.assertEqual(current.attempts,2)
        self.assertNotEqual(current.lease_token,old.lease_token)
        self.assertEqual(self.worker.prepare(old).state,'lost_lease')
        ready = self.worker.prepare(current)
        self.assertEqual(self.worker.finish(ready,self.adapter.send(ready.envelope)).state,'provider_accepted')
        self.assertEqual(len(self.adapter.calls),1)

    def test_crashed_post_dispatch_intent_is_terminal_unknown_never_resent(self):
        self.create()
        ready = self.worker.prepare(self.worker.claim_one())
        self.real.value = ready.lease_until
        result = self.worker.run_once()
        self.assertEqual((result.state,result.code),('failed','DELIVERY_OUTCOME_UNKNOWN'))
        self.assertEqual(self.worker.run_once().state,'idle')
        self.assertEqual(self.adapter.calls,[])
        self.assertEqual(self.job(ready.envelope.job_id)['last_error_code'],'DELIVERY_OUTCOME_UNKNOWN')

    def test_late_accepted_response_is_audited_without_reviving_failed_job(self):
        self.create()
        ready = self.worker.prepare(self.worker.claim_one())
        self.real.value = ready.lease_until
        self.worker.run_once()
        result = self.worker.finish(ready,DeliveryOutcome('accepted','TELEGRAM_API_ACCEPTED','telegram:999'))
        self.assertEqual(result.state,'lost_lease')
        job = self.job(ready.envelope.job_id)
        self.assertEqual(job['state'],'failed'); self.assertIsNone(job['provider_receipt'])
        self.assertEqual(self.query('SELECT provider_receipt FROM delivery_dispatch_results')[0]['provider_receipt'],'telegram:999')

    def test_duplicate_prepare_and_finish_do_not_repeat_provider_effect(self):
        self.create()
        claim = self.worker.claim_one()
        ready = self.worker.prepare(claim)
        self.assertEqual(self.worker.prepare(claim).state,'already_started')
        outcome = self.adapter.send(ready.envelope)
        self.worker.finish(ready,outcome)
        self.assertEqual(self.worker.finish(ready,outcome).state,'lost_lease')
        self.assertEqual(len(self.query('SELECT * FROM delivery_dispatch_results')),1)
        self.assertEqual(len(self.adapter.calls),1)

    def test_uncertain_provider_result_is_not_retried(self):
        self.create()
        self.adapter.outcome = DeliveryOutcome('ambiguous','TELEGRAM_OUTCOME_UNKNOWN')
        result = self.worker.run_once()
        self.assertEqual(result.state,'failed')
        self.real.value += timedelta(days=30)
        self.assertEqual(self.worker.run_once().state,'idle')
        self.assertEqual(len(self.adapter.calls),1)
        self.assertIsNone(self.job(result.job_id)['provider_receipt'])

    def test_unexpected_adapter_exception_is_ambiguous_not_safe_retry(self):
        self.create()
        self.adapter.callback = lambda _:(_ for _ in ()).throw(RuntimeError('SECRET RAW RESPONSE'))
        result = self.worker.run_once()
        self.assertEqual(result.state,'failed')
        self.assertEqual(self.job(result.job_id)['last_error_code'],'DELIVERY_PROVIDER_EXCEPTION_UNKNOWN')
        self.assertNotIn('SECRET',str(self.query('SELECT * FROM delivery_dispatch_results')))

    def test_provider_retry_after_is_never_shortened_and_uses_real_time(self):
        self.create()
        self.adapter.outcome = DeliveryOutcome('retryable','TELEGRAM_RATE_LIMITED',retry_after_seconds=1000)
        result = self.worker.run_once()
        self.assertEqual(result.state,'retry')
        self.assertEqual(self.job(result.job_id)['next_attempt_at'],self.real.now()+timedelta(seconds=1000))
        self.domain.value += timedelta(days=100)
        self.assertEqual(self.worker.run_once().state,'idle')
        self.real.value += timedelta(seconds=1000)
        self.adapter.outcome = DeliveryOutcome('accepted','TELEGRAM_API_ACCEPTED','telegram:101')
        self.assertEqual(self.worker.run_once().state,'provider_accepted')
        self.assertEqual(len(self.adapter.calls),2)

    def test_reassigned_claim_never_calls_adapter(self):
        response,_ = self.create()
        order_id = response.body['order']['id']
        claim = self.worker.claim_one()
        self.action(order_id,1,'reassign',fixture.MASTER,
            {'assignment':{'executor_id':fixture.OTHER,'brigade_id':None},'reason':'New assignment'})
        self.assertEqual(self.worker.prepare(claim).state,'lost_lease')
        self.assertEqual(self.adapter.calls,[])
        self.assertEqual(self.query('SELECT * FROM delivery_dispatches'),[])

    def test_same_assignment_rework_suppresses_old_submission_ready(self):
        order_id,submission_id = self.submitted()
        claim = self.worker.claim_one()
        self.assertEqual(claim.envelope.kind,'submission_ready')
        self.review(order_id,submission_id,decision='rework')
        result = self.worker.prepare(claim)
        self.assertEqual((result.state,result.code),('cancelled','STALE_DELIVERY'))
        self.assertEqual(self.adapter.calls,[])

    def test_revoked_recipient_scope_is_checked_after_claim(self):
        self.create()
        claim = self.worker.claim_one()
        self.query('DELETE FROM employee_sections WHERE employee_id=%s AND section_id=%s RETURNING employee_id',
                   (fixture.EXECUTOR,fixture.SECTION))
        self.assertEqual(self.worker.prepare(claim).state,'cancelled')
        self.assertEqual(self.query('SELECT * FROM delivery_dispatches'),[])
        self.assertEqual(self.adapter.calls,[])

    def test_inactive_recipient_is_never_dispatched(self):
        self.create()
        claim = self.worker.claim_one()
        self.query('UPDATE employees SET active=false WHERE id=%s RETURNING id',(fixture.EXECUTOR,))
        self.assertEqual(self.worker.prepare(claim).state,'cancelled')
        self.assertEqual(self.adapter.calls,[])

    def test_cancellation_during_provider_call_cannot_revive_job(self):
        response,_ = self.create()
        order_id = response.body['order']['id']
        self.adapter.callback = lambda _:self.action(order_id,1,'cancel',fixture.MASTER,{'reason':'Cancelled while in flight'})
        result = self.worker.run_once()
        self.assertEqual(result.state,'lost_lease')
        self.assertEqual(self.job(self.adapter.calls[0].job_id)['state'],'cancelled')
        self.assertEqual(self.query('SELECT outcome FROM delivery_dispatch_results')[0]['outcome'],'accepted')
        self.assertEqual(self.query('SELECT status FROM orders')[0]['status'],'cancelled')

    def test_domain_rewind_does_not_consume_a_delivery_attempt(self):
        self.create()
        claim = self.worker.claim_one()
        self.domain.value -= timedelta(minutes=1)
        result = self.worker.prepare(claim)
        self.assertEqual((result.state,result.code),('retry','WAIT_DOMAIN'))
        self.assertEqual(self.job(claim.envelope.job_id)['attempts'],0)
        self.real.value += timedelta(seconds=10)
        self.assertEqual(self.worker.run_once().state,'idle')
        self.domain.value += timedelta(minutes=1)
        self.assertEqual(self.worker.run_once().state,'provider_accepted')

    def test_order_lock_wait_holds_no_job_lock_and_old_lease_cannot_send(self):
        response,_ = self.create()
        order_id = response.body['order']['id']
        claim = self.worker.claim_one()
        waiting = Event()
        original = PostgresRepository.load_order
        def signal(repo,*args,**kwargs):
            if kwargs.get('lock'):waiting.set()
            return original(repo,*args,**kwargs)
        with self.connect() as holder,patch.object(PostgresRepository,'load_order',signal),ThreadPoolExecutor(max_workers=1) as pool:
            with holder.transaction():
                holder.execute('SELECT id FROM orders WHERE id=%s FOR UPDATE',(order_id,))
                future = pool.submit(self.worker.prepare,claim)
                self.assertTrue(waiting.wait(10))
                self.real.value = claim.lease_until
                with self.connect() as db:
                    db.execute("SET statement_timeout='2s'")
                    with db.transaction():
                        new = DeliveryRepository(db).claim(real_now=self.real.now(),domain_now=self.domain.now(),
                            lease_until=self.real.now()+self.worker.policy.lease,token=str(uuid4()),channel='telegram',max_attempts=5)
            self.assertEqual(future.result(timeout=10).state,'lost_lease')
        self.assertEqual(new.attempts,2)
        self.assertEqual(self.adapter.calls,[])

    def test_outcome_audit_and_job_finish_are_atomic_on_failure(self):
        self.create()
        ready = self.worker.prepare(self.worker.claim_one())
        original = DeliveryRepository.finish
        def fail(repo,*args,**kwargs):
            original(repo,*args,**kwargs)
            raise RuntimeError('database fault after tentative finish')
        with patch.object(DeliveryRepository,'finish',fail),self.assertRaises(RuntimeError):
            self.worker.finish(ready,DeliveryOutcome('accepted','TELEGRAM_API_ACCEPTED','telegram:123'))
        self.assertEqual(self.query('SELECT * FROM delivery_dispatch_results'),[])
        self.assertEqual(self.job(ready.envelope.job_id)['state'],'sending')
        self.real.value = ready.lease_until
        self.assertEqual(self.worker.run_once().code,'DELIVERY_OUTCOME_UNKNOWN')
        self.assertEqual(self.adapter.calls,[])

    def test_synthetic_outcome_is_distinct_and_never_has_sent_at(self):
        self.service.policy = SchedulePolicy(channel='synthetic')
        self.create()
        adapter = FakeAdapter(DeliveryOutcome('synthetic_recorded','SYNTHETIC_NOT_SENT'))
        worker = DeliveryWorker(self.connect,adapter=adapter,channel='synthetic',domain_clock=self.domain,real_clock=self.real)
        result = worker.run_once()
        self.assertEqual(result.state,'synthetic_recorded')
        row = self.job(result.job_id)
        self.assertIsNone(row['sent_at']); self.assertIsNone(row['provider_receipt'])
        self.assertEqual(row['last_error_code'],'SYNTHETIC_NOT_SENT')

    def test_channel_filter_never_claims_an_unconfigured_route(self):
        self.create()
        worker = DeliveryWorker(self.connect,adapter=FakeAdapter(),channel='synthetic',domain_clock=self.domain,real_clock=self.real)
        self.assertEqual(worker.run_once().state,'idle')
        self.assertEqual(self.adapter.calls,[])

    def test_rewound_post_intent_crash_still_resolves_unknown(self):
        self.create()
        ready = self.worker.prepare(self.worker.claim_one())
        self.real.value = ready.lease_until
        self.domain.value -= timedelta(days=1)
        self.assertEqual(self.worker.run_once().code,'DELIVERY_OUTCOME_UNKNOWN')
        self.assertEqual(self.adapter.calls,[])
