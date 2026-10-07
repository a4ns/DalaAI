"""Mandatory REAL PostgreSQL gate; skipped without explicit disposable DSN.

Independent random schema per case. Reuses baseline synthetic command fixture
setup/helpers, never inherits or silently repeats its test methods.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_persistence_postgres as fixture
from app.ai.rules import assess_rules
from app.jobs import AssessmentWorker, WorkerPolicy
from app.jobs.postgres import JobRepository
from app.persistence.postgres import PostgresRepository, PostgresReferences


class DurableJobPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.PostgresCommandTests.setUpClass.__func__(cls)

    # Explicit fixture-only reuse avoids inherited test-count inflation.
    for _name in ('connect','drop_schema','query','run_command','create','action','start','stage','submit','review'):
        locals()[_name] = getattr(fixture.PostgresCommandTests, _name)

    def setUp(self):
        fixture.PostgresCommandTests.setUp(self)
        self.worker = AssessmentWorker(self.connect, domain_clock=self.domain, real_clock=self.real)

    def submitted(self, *, complete=True):
        order_id = self.start()
        photos = ()
        if complete:
            photos = (self.stage(owner=fixture.EXECUTOR,purpose='after',order_id=order_id,revision=1),)
        result,_ = self.submit(order_id,photos=photos)
        return order_id,result.body['submission_id'],photos

    def counts(self):
        return {name:self.query(f'SELECT count(*) AS n FROM {name}')[0]['n']
                for name in ('ai_assessments','order_events','delivery_jobs')}

    def test_current_fallback_atomic_visibility_and_manual_decision_boundary(self):
        order_id,submission_id,_ = self.submitted()
        before = self.counts()
        claimed = self.worker.claim_one()
        self.assertEqual(self.query('SELECT state FROM ai_jobs')[0]['state'],'running')
        self.assertEqual(self.query('SELECT * FROM ai_assessments'),[])
        result = self.worker.complete(claimed)
        self.assertEqual((result.state,result.stale),('done',False))
        row = self.query('SELECT * FROM ai_assessments')[0]
        self.assertEqual(row['mode'],'rules_fallback')
        self.assertEqual(row['fallback_reason'],'provider_not_configured')
        self.assertIsNone(row['score']); self.assertIsNone(row['model']); self.assertIsNone(row['model_version'])
        self.assertEqual(row['recommendation'],'needs_master_review')
        order = self.query('SELECT * FROM orders')[0]
        self.assertEqual((order['version'],order['status']),(5,'ai_review'))
        self.assertEqual(self.query('SELECT * FROM reviews'),[])
        self.assertEqual(self.counts(),dict(before,ai_assessments=1,order_events=before['order_events']+1))
        read = self.service.get_submission(order_id,submission_id,session_handle=fixture.MASTER)
        self.assertEqual(read['assessments'][0]['id'],result.assessment_id)
        event = self.query("SELECT * FROM order_events WHERE kind='order.assessment_recorded'")[0]
        self.assertEqual(event['details'],{'assessment_id':result.assessment_id,'mode':'rules_fallback'})
        self.assertEqual(event['order_version'],5)
        job = self.query('SELECT * FROM ai_jobs')[0]
        self.assertEqual(job['state'],'done'); self.assertIsNone(job['lease_token']); self.assertIsNone(job['lease_until'])

    def test_duplicate_completion_and_duplicate_runner_are_noops(self):
        self.submitted()
        claim = self.worker.claim_one()
        self.worker.complete(claim)
        before = self.counts()
        self.assertEqual(self.worker.complete(claim).state,'lost_lease')
        self.assertEqual(self.worker.run_once().state,'idle')
        self.assertEqual(self.counts(),before)
        self.assertEqual(self.query('SELECT version FROM orders')[0]['version'],5)

    def test_crash_reclaim_fences_old_token_even_if_worker_restarts(self):
        self.submitted()
        abandoned = self.worker.claim_one()
        self.assertIsNone(self.worker.claim_one())
        self.real.value = abandoned.lease_until
        replacement = AssessmentWorker(self.connect,domain_clock=self.domain,real_clock=self.real)
        reclaimed = replacement.claim_one()
        self.assertEqual(reclaimed.id,abandoned.id)
        self.assertEqual(reclaimed.attempts,2)
        self.assertNotEqual(reclaimed.lease_token,abandoned.lease_token)
        self.assertEqual(self.worker.complete(abandoned).state,'lost_lease')
        self.assertEqual(self.worker.record_failure(abandoned).state,'lost_lease')
        self.assertEqual(self.query('SELECT * FROM ai_assessments'),[])
        self.assertEqual(replacement.complete(reclaimed).state,'done')
        self.assertEqual(len(self.query('SELECT * FROM ai_assessments')),1)

    def test_expired_unreclaimed_claim_cannot_complete_or_retry(self):
        self.submitted()
        claim = self.worker.claim_one()
        self.real.value = claim.lease_until
        self.assertEqual(self.worker.complete(claim).state,'lost_lease')
        self.assertEqual(self.worker.record_failure(claim).state,'lost_lease')
        self.assertEqual(self.query('SELECT * FROM ai_assessments'),[])
        self.assertEqual(self.query('SELECT state FROM ai_jobs')[0]['state'],'running')

    def test_reassignment_archives_only_old_result(self):
        order_id,_,_ = self.submitted()
        claim = self.worker.claim_one()
        self.action(order_id,4,'reassign',fixture.MASTER,{'assignment':{'executor_id':fixture.OTHER,'brigade_id':None},'reason':'New assignment'})
        before = self.counts()
        result = self.worker.complete(claim)
        self.assertTrue(result.stale)
        self.assertEqual(self.counts(),dict(before,ai_assessments=1))
        order = self.query('SELECT * FROM orders')[0]
        self.assertEqual((order['version'],order['status'],order['assignment_revision']),(5,'issued',2))
        self.assertTrue(self.query('SELECT stale FROM ai_assessments')[0]['stale'])

    def test_rework_same_assignment_new_submission_fences_old_result(self):
        order_id,submission_id,_ = self.submitted()
        claim = self.worker.claim_one()
        self.review(order_id,submission_id,decision='rework')
        self.action(order_id,5,'start')
        second,_ = self.action(order_id,6,'submit',payload={'work_description':'Second attempt',
            'work_code_id':fixture.CODE,'materials':[],'after_photo_ids':[],'comment':''})
        before = self.counts()
        result = self.worker.complete(claim)
        self.assertTrue(result.stale)
        self.assertEqual(self.counts(),dict(before,ai_assessments=1))
        order = self.query('SELECT * FROM orders')[0]
        self.assertEqual((order['version'],order['assignment_revision']),(7,1))
        self.assertEqual(str(order['current_submission_id']),second.body['submission_id'])
        self.assertFalse(self.worker.run_once().stale)
        self.assertEqual(self.query('SELECT version FROM orders')[0]['version'],8)

    def test_human_close_before_result_makes_assessment_historical(self):
        order_id,submission_id,_ = self.submitted()
        claim = self.worker.claim_one()
        self.review(order_id,submission_id)
        before = self.counts()
        self.assertTrue(self.worker.complete(claim).stale)
        self.assertEqual(self.counts(),dict(before,ai_assessments=1))
        self.assertEqual(self.query('SELECT status,version FROM orders')[0],{'status':'closed','version':5})

    def test_current_evidence_is_reloaded_after_claim(self):
        _,_,photos = self.submitted()
        claim = self.worker.claim_one()
        self.query('UPDATE photos SET file_valid=NULL WHERE id=%s RETURNING id',(photos[0],))
        self.worker.complete(claim)
        row = self.query('SELECT * FROM ai_assessments')[0]
        self.assertFalse(row['stale'])
        self.assertTrue(any('недостаточно данных' in reason for reason in row['reasons']))
        self.assertIsNone(row['score'])

    def test_incomplete_submission_honest_rules_recommend_rework_without_transition(self):
        self.submitted(complete=False)
        self.worker.run_once()
        row = self.query('SELECT * FROM ai_assessments')[0]
        self.assertEqual(row['recommendation'],'rework_recommended')
        self.assertIsNone(row['score'])
        self.assertEqual(self.query('SELECT status FROM orders')[0]['status'],'ai_review')

    def test_error_rolls_back_all_results_and_schedules_sanitized_real_retry(self):
        self.submitted()
        before = self.counts()
        original = JobRepository.publish_current
        def fail_after_event(repo,*args,**kwargs):
            original(repo,*args,**kwargs)
            raise RuntimeError('PRIVATE RAW PAYLOAD SHOULD NEVER BE SAVED')
        with patch.object(JobRepository,'publish_current',fail_after_event):
            self.assertEqual(self.worker.run_once().state,'retry')
        self.assertEqual(self.counts(),before)
        self.assertEqual(self.query('SELECT version FROM orders')[0]['version'],4)
        job = self.query('SELECT * FROM ai_jobs')[0]
        self.assertEqual(job['last_error_code'],'ASSESSMENT_WORKER_ERROR')
        self.domain.value += timedelta(days=300)
        self.assertEqual(self.worker.run_once().state,'idle')
        self.real.value = job['next_attempt_at']
        self.assertEqual(self.worker.run_once().state,'done')

    def test_expiry_after_provisional_result_rolls_back_assessment_event_version(self):
        self.submitted()
        before = self.counts()
        claim = self.worker.claim_one()
        original = JobRepository.publish_current
        def expire(repo,*args,**kwargs):
            original(repo,*args,**kwargs)
            self.real.value = claim.lease_until
        with patch.object(JobRepository,'publish_current',expire):
            self.assertEqual(self.worker.complete(claim).state,'lost_lease')
        self.assertEqual(self.counts(),before)
        self.assertEqual(self.query('SELECT version FROM orders')[0]['version'],4)

    def test_readers_never_observe_partial_result_before_commit(self):
        order_id,_,_ = self.submitted()
        before = self.counts()
        inserted,release = Event(),Event()
        original = JobRepository.persist_assessment
        def pause(repo,*args):
            original(repo,*args)
            inserted.set()
            if not release.wait(10):
                raise RuntimeError('test release timeout')
        with patch.object(JobRepository,'persist_assessment',pause),ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.worker.run_once)
            try:
                self.assertTrue(inserted.wait(10))
                self.assertEqual(self.counts(),before)
                self.assertEqual(self.query('SELECT version FROM orders WHERE id=%s',(order_id,))[0]['version'],4)
                self.assertEqual(self.query('SELECT state FROM ai_jobs')[0]['state'],'running')
            finally:
                release.set()
            self.assertEqual(future.result(timeout=10).state,'done')
        self.assertEqual(len(self.query('SELECT * FROM ai_assessments')),1)

    def test_order_wait_does_not_hold_job_lock_and_reclaim_wins(self):
        order_id,_,_ = self.submitted()
        claim = self.worker.claim_one()
        waiting = Event()
        original = PostgresRepository.load_order
        def signal(repo,*args,**kwargs):
            if kwargs.get('lock'):
                waiting.set()
            return original(repo,*args,**kwargs)
        with self.connect() as holder,patch.object(PostgresRepository,'load_order',signal),ThreadPoolExecutor(max_workers=1) as pool:
            with holder.transaction():
                holder.execute('SELECT id FROM orders WHERE id=%s FOR UPDATE',(order_id,))
                future = pool.submit(self.worker.complete,claim)
                self.assertTrue(waiting.wait(10))
                self.real.value = claim.lease_until
                with self.connect() as probe:
                    probe.execute("SET statement_timeout='2s'")
                    with probe.transaction():
                        new = JobRepository(probe).claim(now=self.real.now(),
                            lease_until=self.real.now()+self.worker.policy.lease,token=str(uuid4()),max_attempts=5)
                self.assertEqual(new.attempts,2)
            self.assertEqual(future.result(timeout=10).state,'lost_lease')
        self.assertEqual(self.worker.complete(new).state,'done')

    def test_parallel_claims_never_duplicate_a_running_job(self):
        self.submitted()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _:self.worker.claim_one(),range(2)))
        self.assertEqual(sum(result is not None for result in results),1)
        self.assertEqual(self.query('SELECT attempts FROM ai_jobs')[0]['attempts'],1)

    def test_repeated_crash_exhaustion_is_terminal_and_does_not_publish(self):
        self.submitted()
        worker = AssessmentWorker(self.connect,domain_clock=self.domain,real_clock=self.real,
                                  policy=WorkerPolicy(max_attempts=2))
        first = worker.claim_one(); self.real.value = first.lease_until
        second = worker.claim_one(); self.real.value = second.lease_until
        self.assertEqual(worker.run_once().state,'exhausted')
        self.assertEqual(worker.run_once().state,'idle')
        self.assertEqual(self.query('SELECT state,last_error_code FROM ai_jobs')[0],
                         {'state':'failed','last_error_code':'ATTEMPTS_EXHAUSTED'})
        self.assertEqual(self.query('SELECT * FROM ai_assessments'),[])

    def test_migration_does_not_discard_preexisting_pending_jobs(self):
        # All migrations are installed by fixture setup; verify nullable fencing
        # addition preserves ordinary command-created jobs before first claim.
        self.submitted()
        row = self.query('SELECT * FROM ai_jobs')[0]
        self.assertIsNone(row['lease_token'])
        self.assertEqual(row['attempts'],0)
        self.assertEqual(self.worker.run_once().state,'done')

    def test_default_does_not_treat_past_upload_validation_as_current_blob_integrity(self):
        self.submitted()
        self.worker.run_once()
        row = self.query('SELECT * FROM ai_assessments')[0]
        self.assertTrue(any('Подтверждённая проверка файла фото: недостаточно данных' in reason
                            for reason in row['reasons']))
        self.assertEqual(row['recommendation'],'needs_master_review')
        self.assertIsNone(row['score'])

    def test_explicit_synthetic_verifier_fixture_preserves_verified_file_evidence(self):
        self.submitted()
        class TrustedSyntheticFixtureReferences(PostgresReferences):
            """TEST ONLY: fixture's file_valid flag stands for synthetic verifier output."""
        worker = AssessmentWorker(self.connect,domain_clock=self.domain,real_clock=self.real,
                                  references_factory=TrustedSyntheticFixtureReferences)
        worker.run_once()
        row = self.query('SELECT * FROM ai_assessments')[0]
        self.assertFalse(any('Подтверждённая проверка файла фото: недостаточно данных' in reason
                             for reason in row['reasons']))
        self.assertEqual(row['recommendation'],'needs_master_review')
        self.assertIsNone(row['score']); self.assertIsNone(row['model'])
