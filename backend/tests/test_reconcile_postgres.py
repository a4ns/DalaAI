"""REAL PostgreSQL deadline/job generation; no provider is called by this suite."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import unittest

import test_persistence_postgres as fixture
from app.notify.reconcile import DeadlineReconciler
from app.scheduler import SchedulePolicy


class ReconciliationPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.PostgresCommandTests.setUpClass.__func__(cls)
    for _name in ('connect','drop_schema','query','run_command','create','action','start','stage','submit','review'):
        locals()[_name] = getattr(fixture.PostgresCommandTests,_name)

    def setUp(self):
        fixture.PostgresCommandTests.setUp(self)
        self.service.policy = SchedulePolicy(channel='web_push')
        self.reconciler = DeadlineReconciler(self.connect,channel='web_push',
                                            domain_clock=self.domain,real_clock=self.real)

    def created(self):
        response,_=self.create()
        return response.body['order']['id']

    def jobs(self,kind=None):
        return self.query('SELECT * FROM delivery_jobs'+(' WHERE kind=%s' if kind else ''),
                          (kind,) if kind else ())

    def test_issue_generates_immediate_web_push_job_atomically_without_scheduler(self):
        order_id=self.created()
        job=self.jobs()[0]
        self.assertEqual((str(job['order_id']),job['kind'],job['channel'],job['bucket']),
                         (order_id,'new_order','web_push','initial'))
        self.assertEqual((job['due_at'],job['next_attempt_at']),(self.domain.now(),self.real.now()))
        self.assertEqual(len(self.query('SELECT * FROM operation_receipts')),1)
        self.assertEqual(len(self.query('SELECT * FROM order_events')),1)

    def test_reassignment_generates_new_notice_with_latest_revision_and_domain_time(self):
        order_id=self.created()
        self.domain.value+=timedelta(minutes=20)
        self.action(order_id,1,'reassign',fixture.MASTER,
            {'assignment':{'executor_id':fixture.OTHER,'brigade_id':None},'reason':'New assignment'})
        rows=sorted(self.jobs(),key=lambda r:r['assignment_revision'])
        self.assertEqual(rows[0]['state'],'cancelled')
        self.assertEqual((rows[1]['assignment_revision'],rows[1]['scheduling_revision'],rows[1]['channel']),(2,2,'web_push'))
        self.assertEqual(str(rows[1]['recipient_id']),fixture.OTHER)
        self.assertEqual(rows[1]['due_at'],self.domain.now())
        self.assertEqual(self.query('SELECT issued_at FROM orders')[0]['issued_at'],fixture.NOW)

    def test_reminder_crossing_and_strict_overdue_boundary_use_existing_thresholds(self):
        order_id=self.created();self.action(order_id,1,'accept')
        self.domain.value=fixture.NOW+timedelta(minutes=30)-timedelta(microseconds=1)
        self.reconciler.reconcile_order(order_id)
        self.assertEqual(self.jobs('deadline_reminder'),[])
        self.domain.value+=timedelta(microseconds=1)
        self.reconciler.reconcile_order(order_id)
        reminder=self.jobs('deadline_reminder')[0]
        self.assertEqual(reminder['due_at'],fixture.NOW+timedelta(minutes=30))
        self.assertEqual(reminder['next_attempt_at'],fixture.NOW)
        self.domain.value=fixture.NOW+timedelta(hours=1)
        self.reconciler.reconcile_order(order_id)
        self.assertEqual(self.jobs('overdue'),[])
        self.domain.value+=timedelta(microseconds=1)
        self.reconciler.reconcile_order(order_id)
        rows=self.jobs('overdue')
        self.assertEqual(len(rows),2)
        self.assertEqual({str(row['recipient_id']) for row in rows},{fixture.MASTER,fixture.EXECUTOR})
        self.assertTrue(all(row['due_at']==fixture.NOW+timedelta(hours=1) for row in rows))

    def test_normal_and_emergency_acceptance_thresholds_do_not_drift(self):
        order_id=self.created()
        self.domain.value=fixture.NOW+timedelta(minutes=10)-timedelta(microseconds=1)
        self.reconciler.reconcile_order(order_id)
        self.assertEqual(self.jobs('acceptance_escalation'),[])
        self.domain.value+=timedelta(microseconds=1)
        self.reconciler.reconcile_order(order_id)
        self.assertEqual(self.jobs('acceptance_escalation')[0]['due_at'],fixture.NOW+timedelta(minutes=10))
        self.action(order_id,1,'change_priority',fixture.MASTER,{'priority':'emergency','reason':'Urgent'})
        self.reconciler.reconcile_order(order_id)
        rows=sorted(self.jobs('acceptance_escalation'),key=lambda r:r['scheduling_revision'])
        self.assertEqual(rows[0]['state'],'cancelled')
        self.assertEqual(rows[1]['due_at'],fixture.NOW+timedelta(minutes=3))
        self.assertEqual(rows[1]['scheduling_revision'],2)

    def test_reassignment_acceptance_anchor_is_current_event_not_original_issue(self):
        order_id=self.created();self.domain.value+=timedelta(minutes=20)
        self.action(order_id,1,'reassign',fixture.MASTER,
            {'assignment':{'executor_id':fixture.OTHER,'brigade_id':None},'reason':'New assignment'})
        self.reconciler.reconcile_order(order_id)
        self.assertEqual(self.jobs('acceptance_escalation'),[])
        self.domain.value+=timedelta(minutes=10)
        self.reconciler.reconcile_order(order_id)
        row=self.jobs('acceptance_escalation')[0]
        self.assertEqual(row['due_at'],fixture.NOW+timedelta(minutes=30))
        self.assertEqual(row['assignment_revision'],2)

    def test_restart_and_repeat_scan_preserve_job_identity_and_order_version(self):
        order_id=self.created();self.domain.value+=timedelta(hours=2)
        before=self.query('SELECT version FROM orders')[0]['version']
        self.reconciler.reconcile_order(order_id)
        ids={str(row['id']) for row in self.jobs()}
        restarted=DeadlineReconciler(self.connect,channel='web_push',domain_clock=self.domain,real_clock=self.real)
        for _ in range(3):self.assertEqual(restarted.reconcile_order(order_id).due_intents,0)
        self.assertEqual({str(row['id']) for row in self.jobs()},ids)
        self.assertEqual(self.query('SELECT version FROM orders')[0]['version'],before)
        self.assertEqual(len(self.query('SELECT * FROM order_events')),1)

    def test_concurrent_reconcilers_deduplicate_durable_keys(self):
        order_id=self.created();self.domain.value+=timedelta(hours=2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.reconciler.reconcile_order(order_id),range(2)))
        self.assertTrue(all(result.state in {'reconciled','unavailable_or_busy'} for result in results))
        self.assertEqual(len(self.jobs('overdue')),2)
        self.assertEqual(len(self.jobs('acceptance_escalation')),1)

    def test_same_assignment_rework_gets_new_deadline_cycle_without_deadline_rewrite(self):
        order_id=self.start()
        self.domain.value+=timedelta(hours=2)
        self.reconciler.reconcile_order(order_id)
        response,_=self.submit(order_id)
        submission_id=response.body['submission_id']
        self.assertEqual(self.reconciler.reconcile_order(order_id).state,'inactive')
        self.review(order_id,submission_id,decision='rework')
        self.reconciler.reconcile_order(order_id)
        rows=self.jobs('overdue')
        self.assertEqual(len(rows),4)
        current=[r for r in rows if r['state']=='pending']
        self.assertEqual(len(current),2)
        self.assertTrue(all(r['bucket']==f'deadline:rework:{submission_id}:overdue:0' for r in current))
        self.assertTrue(all(r['assignment_revision']==1 for r in rows))
        self.assertEqual(self.query('SELECT due_at FROM orders')[0]['due_at'],fixture.NOW+timedelta(hours=1))

    def test_revoked_or_inactive_recipient_prevents_new_due_work(self):
        order_id=self.created();self.domain.value+=timedelta(hours=2)
        self.query('DELETE FROM employee_sections WHERE employee_id=%s AND section_id=%s RETURNING employee_id',
                   (fixture.EXECUTOR,fixture.SECTION))
        self.assertEqual(self.reconciler.reconcile_order(order_id).state,'recipient_unavailable')
        self.assertEqual(len(self.jobs()),1)
        self.query('INSERT INTO employee_sections VALUES (%s,%s) RETURNING employee_id',(fixture.EXECUTOR,fixture.SECTION))
        self.query('UPDATE employees SET active=false WHERE id=%s RETURNING id',(fixture.MASTER,))
        self.assertEqual(self.reconciler.reconcile_order(order_id).state,'recipient_unavailable')
        self.assertEqual(len(self.jobs()),1)

    def test_scan_paginates_current_active_orders_and_can_restart(self):
        expected={self.created() for _ in range(3)}
        ids=set();after=None
        for _ in range(3):
            page=self.reconciler.scan_once(limit=1,after_id=after)
            ids.update(result.order_id for result in page.results)
            after=page.next_after_id
        self.assertIsNone(after);self.assertEqual(ids,expected)
        self.assertEqual(len(self.reconciler.scan_once(limit=100).results),3)
        self.assertEqual(len(self.jobs()),3)  # immediate commands only; not due yet

    def test_busy_order_is_skipped_without_holding_delivery_lock(self):
        order_id=self.created();self.domain.value+=timedelta(hours=2)
        with self.connect() as holder:
            with holder.transaction():
                holder.execute('SELECT id FROM orders WHERE id=%s FOR UPDATE',(order_id,))
                result=self.reconciler.reconcile_order(order_id)
                self.assertEqual(result.state,'unavailable_or_busy')
        self.assertEqual(len(self.jobs()),1)
        self.reconciler.reconcile_order(order_id)
        self.assertEqual(len(self.jobs('overdue')),2)

    def test_real_clock_cannot_trigger_domain_deadline_but_controls_retry_timestamp(self):
        order_id=self.created();self.real.value+=timedelta(days=20)
        self.reconciler.reconcile_order(order_id)
        self.assertEqual(len(self.jobs()),1)
        self.domain.value+=timedelta(hours=2)
        self.reconciler.reconcile_order(order_id)
        self.assertTrue(all(r['next_attempt_at']==self.real.now() for r in self.jobs('overdue')))
        self.assertTrue(all(r['due_at']==fixture.NOW+timedelta(hours=1) for r in self.jobs('overdue')))

    def test_terminal_and_ai_review_orders_do_not_generate_deadline_jobs(self):
        order_id=self.created()
        self.action(order_id,1,'cancel',fixture.MASTER,{'reason':'Cancelled'})
        self.domain.value+=timedelta(hours=2)
        self.assertEqual(self.reconciler.reconcile_order(order_id).state,'inactive')
        self.assertEqual(self.jobs('overdue'),[])
        self.assertEqual(self.reconciler.scan_once().results,())

    def test_failed_or_cancelled_durable_key_is_not_reissued_by_reconciliation(self):
        order_id=self.created();self.domain.value+=timedelta(hours=2)
        self.reconciler.reconcile_order(order_id)
        self.query("UPDATE delivery_jobs SET state='failed',last_error_code='DELIVERY_OUTCOME_UNKNOWN' WHERE kind='overdue' RETURNING id")
        ids={str(row['id']) for row in self.jobs()}
        self.assertEqual(self.reconciler.reconcile_order(order_id).due_intents,0)
        self.assertEqual({str(row['id']) for row in self.jobs()},ids)
        self.assertTrue(all(row['state']=='failed' for row in self.jobs('overdue')))
