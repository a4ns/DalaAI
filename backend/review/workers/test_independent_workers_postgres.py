"""Independent gaps: event interoperability, lease waits and real populated upgrade.

Author crash/basic-staleness tests are intentionally not duplicated here.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic,sleep
import shutil
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_persistence_postgres as fixture
from test_persistence_postgres import PostgresCommandTests,EXECUTOR,MASTER
from app.jobs import AssessmentWorker
from app.jobs.postgres import JobRepository
from app.order_events.service import OrderEventService

ROOT=Path(__file__).resolve().parents[1]
MIGRATIONS=ROOT/'snapshot/backend/db/migrations'
fixture.MIGRATIONS=MIGRATIONS


class IndependentWorkerPostgresTests(PostgresCommandTests):
 def setUp(self):
  if self._testMethodName=='test_worker_populated_pre_token_running_job_upgrade':
   self.baseline=TemporaryDirectory(prefix='dalaai-review-before011-');self.addCleanup(self.baseline.cleanup)
   for path in MIGRATIONS.glob('*.sql'):
    if not path.name.startswith('011_'):shutil.copyfile(path,Path(self.baseline.name)/path.name)
   fixture.MIGRATIONS=Path(self.baseline.name)
  try:super().setUp()
  finally:fixture.MIGRATIONS=MIGRATIONS
  self.worker=AssessmentWorker(self.connect,domain_clock=self.domain,real_clock=self.real)

 def submitted(self):
  order_id=self.start();result,_=self.submit(order_id)
  return order_id,result.body['submission_id']

 def state(self,job):
  return self.query('SELECT state,attempts,lease_token,lease_until,last_error_code,next_attempt_at FROM ai_jobs WHERE id=%s',(job,))[0]

 def observed_wait(self,pid,future):
  deadline=monotonic()+10
  while monotonic()<deadline:
   rows=self.query('SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s',(pid,))
   if rows and rows[0]['wait_event_type']=='Lock':
    self.assertFalse(future.done());return
   sleep(0.01)
  self.fail('Worker did not reach a PostgreSQL Lock wait')

 def test_worker_current_assessment_consumed_by_frozen_event_endpoint(self):
  order_id,submission_id=self.submitted()
  result=self.worker.run_once();self.assertEqual(result.state,'done')
  events=OrderEventService(self.connect,real_clock=self.real).list_events(order_id,{},session_handle=MASTER)
  self.assertEqual([row['sequence'] for row in events['items']],[1,2,3,4,5,6])
  event=events['items'][-1]
  self.assertEqual(event['kind'],'order.assessment_recorded')
  self.assertEqual(event['details'],{'assessment_id':result.assessment_id,'mode':'rules_fallback'})
  self.assertEqual(event['submission_id'],submission_id)
  self.assertEqual((event['order_version'],event['from_status'],event['to_status']),(5,'ai_review','ai_review'))
  self.assertIsNone(event['actor_id']);self.assertIsNone(event['operation_id'])

 def run_job_wait(self,operation,*,reclaim=False):
  order_id,_=self.submitted();claim=self.worker.claim_one();entered=Event();pid=[]
  def traced_connect():
   db=self.connect();pid.append(db.execute('SELECT pg_backend_pid() AS pid').fetchone()['pid']);entered.set();return db
  new=None
  with patch.object(self.worker,'connect',traced_connect),ThreadPoolExecutor(max_workers=1) as pool:
   with self.connect() as holder:
    with holder.transaction():
     holder.execute('SELECT id FROM ai_jobs WHERE id=%s FOR UPDATE',(claim.id,))
     fn=self.worker.record_failure if operation=='fail' else self.worker.complete
     future=pool.submit(fn,claim)
     self.assertTrue(entered.wait(10));self.observed_wait(pid[0],future)
     self.real.value=claim.lease_until
     if reclaim:
      new=JobRepository(holder).claim(now=self.real.now(),lease_until=self.real.now()+self.worker.policy.lease,
                                     token=str(uuid4()),max_attempts=self.worker.policy.max_attempts)
   result=future.result(timeout=15)
  self.assertEqual(result.state,'lost_lease')
  after=self.state(claim.id)
  self.assertEqual(after['state'],'running');self.assertIsNone(after['last_error_code'])
  self.assertEqual(str(after['lease_token']),new.lease_token if new else claim.lease_token)
  self.assertEqual(after['attempts'],2 if new else 1)
  self.assertEqual(self.query('SELECT count(*) AS n FROM ai_assessments')[0]['n'],0)
  self.assertEqual(self.query('SELECT version FROM orders WHERE id=%s',(order_id,))[0]['version'],4)
  return new

 def test_worker_failure_wait_expiry_cannot_schedule_stale_retry(self):self.run_job_wait('fail')

 def test_worker_failure_wait_reclaim_cannot_damage_replacement_lease(self):
  replacement=self.run_job_wait('fail',reclaim=True)
  self.assertEqual(self.worker.complete(replacement).state,'done')

 def test_worker_finalizer_job_lock_wait_rechecks_expiry(self):self.run_job_wait('complete')

 def test_worker_rework_same_submission_before_new_attempt_is_historical(self):
  order_id,submission_id=self.submitted();claim=self.worker.claim_one()
  self.review(order_id,submission_id,decision='rework')
  before={table:self.query(f'SELECT count(*) AS n FROM {table}')[0]['n'] for table in ['order_events','delivery_jobs']}
  version=self.query('SELECT version FROM orders WHERE id=%s',(order_id,))[0]['version']
  result=self.worker.complete(claim)
  self.assertEqual((result.state,result.stale),('done',True))
  current=self.query('SELECT version,status,current_submission_id FROM orders WHERE id=%s',(order_id,))[0]
  self.assertEqual(current['version'],version);self.assertEqual(current['status'],'rework');self.assertEqual(str(current['current_submission_id']),submission_id)
  self.assertEqual({table:self.query(f'SELECT count(*) AS n FROM {table}')[0]['n'] for table in before},before)
  self.assertTrue(self.query('SELECT stale FROM ai_assessments')[0]['stale'])

 def test_worker_deferred_commit_failure_rolls_back_all_effects_then_retry(self):
  order_id,_=self.submitted()
  with self.connect() as db:
   db.execute("""CREATE FUNCTION reviewer_reject_done() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN IF NEW.state='done' THEN RAISE EXCEPTION 'synthetic commit failure'; END IF; RETURN NEW; END $$""")
   db.execute('''CREATE CONSTRAINT TRIGGER reviewer_deferred_failure AFTER UPDATE ON ai_jobs
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reviewer_reject_done()''')
  before={table:self.query(f'SELECT count(*) AS n FROM {table}')[0]['n'] for table in ['ai_assessments','order_events','delivery_jobs']}
  result=self.worker.run_once();self.assertEqual(result.state,'retry')
  self.assertEqual({table:self.query(f'SELECT count(*) AS n FROM {table}')[0]['n'] for table in before},before)
  self.assertEqual(self.query('SELECT version FROM orders WHERE id=%s',(order_id,))[0]['version'],4)
  state=self.query('SELECT * FROM ai_jobs')[0]
  self.assertEqual(state['state'],'retry');self.assertEqual(state['last_error_code'],'ASSESSMENT_WORKER_ERROR')
  with self.connect() as db:db.execute('DROP TRIGGER reviewer_deferred_failure ON ai_jobs')
  self.real.value=state['next_attempt_at'];self.assertEqual(self.worker.run_once().state,'done')

 def test_worker_populated_pre_token_running_job_upgrade(self):
  order_id,submission_id=self.submitted()
  legacy_expiry=self.real.now()+timedelta(minutes=2)
  self.query("UPDATE ai_jobs SET state='running',attempts=1,lease_until=%s RETURNING id",(legacy_expiry,))
  before=self.query('SELECT * FROM ai_jobs')[0]
  with self.connect() as db:db.execute((MIGRATIONS/'011_durable_job_leases.sql').read_text())
  after=self.query('SELECT * FROM ai_jobs')[0]
  self.assertEqual({name:after[name] for name in before},before);self.assertIsNone(after['lease_token'])
  self.assertIsNone(self.worker.claim_one())
  self.real.value=legacy_expiry
  claimed=self.worker.claim_one();self.assertEqual(claimed.attempts,2)
  self.assertEqual(claimed.submission_id,submission_id);self.assertTrue(claimed.lease_token)
  self.assertEqual(self.worker.complete(claimed).state,'done')


def load_tests(loader,standard_tests,pattern):
 return unittest.TestSuite(IndependentWorkerPostgresTests(name)
  for name in sorted(IndependentWorkerPostgresTests.__dict__) if name.startswith('test_worker_'))


if __name__=='__main__':unittest.main(verbosity=2)
