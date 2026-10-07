"""REAL PostgreSQL command-hook regressions; every adapter is fake, no sends."""
from datetime import timedelta
import unittest
from unittest.mock import patch

import test_persistence_postgres as fixture
from test_delivery_postgres import FakeAdapter
from app.notify.worker import DeliveryWorker
from app.notify.models import DeliveryOutcome
from app.persistence.postgres import PostgresRepository
from app.scheduler import SchedulePolicy


class PriorityNoticePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixture.PostgresCommandTests.setUpClass.__func__(cls)
    for _name in ('connect','drop_schema','query','run_command','create','action','start','stage','submit','review'):
        locals()[_name]=getattr(fixture.PostgresCommandTests,_name)

    def setUp(self):
        fixture.PostgresCommandTests.setUp(self)
        self.service.policy=SchedulePolicy(channel='web_push')
        self.adapter=FakeAdapter()
        self.worker=DeliveryWorker(self.connect,adapter=self.adapter,channel='web_push',
                                   domain_clock=self.domain,real_clock=self.real)
        response,_=self.create();self.order_id=response.body['order']['id']

    def notices(self):return self.query("SELECT * FROM delivery_jobs WHERE kind='new_order' ORDER BY scheduling_revision")
    def priority(self,version=1,priority='high',operation=None):
        return self.action(self.order_id,version,'change_priority',fixture.MASTER,
                           {'priority':priority,'reason':'Urgency update'},operation=operation)

    def test_priority_replaces_pending_notice_without_extra_order_effect(self):
        self.priority()
        rows=self.notices();self.assertEqual(len(rows),2)
        self.assertEqual([r['state'] for r in rows],['cancelled','pending'])
        self.assertEqual(rows[1]['scheduling_revision'],2)
        self.assertEqual((rows[1]['due_at'],rows[1]['next_attempt_at']),(fixture.NOW,fixture.NOW))
        self.assertEqual(str(rows[1]['recipient_id']),fixture.EXECUTOR)
        self.assertEqual(self.query('SELECT version FROM orders')[0]['version'],2)
        self.assertEqual(len(self.query('SELECT * FROM order_events')),2)
        self.assertEqual(self.worker.run_once().state,'provider_accepted')
        self.assertEqual(len(self.adapter.calls),1)

    def test_queued_unaccepted_assignment_keeps_notice(self):
        self.action(self.order_id,1,'queue')
        self.priority(2)
        self.assertEqual([r['state'] for r in self.notices()],['cancelled','pending'])
        self.assertEqual(self.worker.run_once().state,'provider_accepted')

    def test_accepted_assignment_does_not_generate_another_assignment_notice(self):
        self.action(self.order_id,1,'accept')
        self.priority(2)
        self.assertEqual(len(self.notices()),1)
        self.assertEqual(self.notices()[0]['state'],'cancelled')
        self.assertEqual(self.worker.run_once().state,'idle')

    def test_rejected_assignment_does_not_generate_another_assignment_notice(self):
        self.action(self.order_id,1,'reject',payload={'reason':'Cannot take this work'})
        self.priority(2)
        self.assertEqual(len(self.notices()),1)
        self.assertEqual(self.worker.run_once().state,'idle')

    def test_claim_without_dispatch_intent_is_replaced_and_old_claim_is_fenced(self):
        old=self.worker.claim_one()
        self.priority()
        self.assertEqual(self.worker.prepare(old).state,'lost_lease')
        current=self.notices()[-1]
        self.assertEqual(current['attempts'],1)
        self.assertEqual(self.worker.run_once().state,'provider_accepted')
        self.assertEqual(len(self.adapter.calls),1)
        self.assertEqual(self.adapter.calls[0].scheduling_revision,2)

    def test_unfinished_dispatch_intent_blocks_replacement_across_repeated_priority_edits(self):
        ready=self.worker.prepare(self.worker.claim_one())
        self.priority()
        self.priority(2,'emergency')
        self.assertEqual(len(self.notices()),1)
        self.assertEqual(self.notices()[0]['state'],'cancelled')
        self.assertEqual(self.worker.run_once().state,'idle')
        self.assertEqual(self.adapter.calls,[])
        late=self.worker.finish(ready,DeliveryOutcome('accepted','WEB_PUSH_API_ACCEPTED','webpush:123'))
        self.assertEqual(late.state,'lost_lease')
        self.priority(3,'normal')
        self.assertEqual(len(self.notices()),1)

    def test_provider_accepted_notice_is_never_resent_on_priority_change(self):
        self.worker.run_once()
        self.priority();self.priority(2,'emergency')
        self.assertEqual(len(self.notices()),1)
        self.assertEqual(self.notices()[0]['state'],'provider_accepted')
        self.assertEqual(len(self.adapter.calls),1)

    def test_ambiguous_failed_notice_is_never_blindly_retried(self):
        self.adapter.outcome=DeliveryOutcome('ambiguous','WEB_PUSH_OUTCOME_UNKNOWN')
        self.worker.run_once()
        self.priority();self.priority(2,'emergency')
        self.assertEqual(len(self.notices()),1)
        self.assertEqual(self.notices()[0]['state'],'failed')
        self.assertEqual(self.worker.run_once().state,'idle')
        self.assertEqual(len(self.adapter.calls),1)

    def test_priority_cannot_bypass_provider_retry_after_or_reset_attempt_budget(self):
        self.adapter.outcome=DeliveryOutcome('retryable','WEB_PUSH_RATE_LIMIT',retry_after_seconds=900)
        self.worker.run_once()
        self.priority();self.priority(2,'emergency')
        rows=self.notices();self.assertEqual(len(rows),3)
        self.assertEqual(rows[-1]['attempts'],1)
        self.assertEqual(rows[-1]['next_attempt_at'],fixture.NOW+timedelta(seconds=900))
        self.assertEqual(self.worker.run_once().state,'idle')
        self.real.value+=timedelta(seconds=900)
        self.adapter.outcome=DeliveryOutcome('accepted','WEB_PUSH_API_ACCEPTED','webpush:900')
        self.assertEqual(self.worker.run_once().state,'provider_accepted')
        self.assertEqual(self.notices()[-1]['attempts'],2)
        self.assertEqual(len(self.adapter.calls),2)  # one explicit rejection, one API acceptance

    def test_legacy_sending_without_fencing_token_is_quarantined(self):
        self.query("UPDATE delivery_jobs SET state='sending',attempts=0,lease_token=NULL RETURNING id")
        self.priority();self.priority(2,'emergency')
        self.assertEqual(len(self.notices()),1)
        self.assertEqual(self.worker.run_once().state,'idle')

    def test_receipt_replay_of_priority_edit_cannot_duplicate_replacement(self):
        result,command=self.priority()
        replay=self.run_command(command,fixture.MASTER,self.order_id)
        self.assertTrue(replay.replayed);self.assertEqual(replay.body,result.body)
        self.assertEqual(len(self.notices()),2)
        self.assertEqual(len(self.query('SELECT * FROM order_events')),2)

    def test_replacement_is_atomic_with_command_receipt_and_priority(self):
        original=PostgresRepository.delivery_job
        def fail(repo,**kwargs):
            original(repo,**kwargs)
            raise RuntimeError('Fault after replacement insertion')
        with patch.object(PostgresRepository,'delivery_job',fail),self.assertRaises(RuntimeError):self.priority()
        self.assertEqual(len(self.notices()),1)
        self.assertEqual(self.notices()[0]['state'],'pending')
        self.assertEqual(self.query('SELECT version,priority FROM orders')[0],{'version':1,'priority':'normal'})
        self.assertEqual(len(self.query('SELECT * FROM operation_receipts')),1)
        self.assertEqual(len(self.query('SELECT * FROM order_events')),1)

    def test_prior_assignment_unknown_does_not_erase_explicit_new_assignment_notice(self):
        self.worker.prepare(self.worker.claim_one())
        self.action(self.order_id,1,'reassign',fixture.MASTER,
            {'assignment':{'executor_id':fixture.OTHER,'brigade_id':None},'reason':'Different responsible person'})
        self.priority(2)
        current=[r for r in self.notices() if r['assignment_revision']==2 and r['state']=='pending']
        self.assertEqual(len(current),1)
        self.assertEqual(str(current[0]['recipient_id']),fixture.OTHER)

    def test_failed_retry_budget_cannot_be_reset_by_priority(self):
        self.query("UPDATE delivery_jobs SET state='failed',attempts=5,last_error_code='ATTEMPTS_EXHAUSTED' RETURNING id")
        self.priority()
        self.assertEqual(len(self.notices()),1)
        self.assertEqual(self.notices()[0]['attempts'],5)
