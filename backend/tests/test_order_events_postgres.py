"""Actual PostgreSQL event reads; fixture owner is not a production-role proof."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
import unittest
from unittest.mock import patch
from uuid import uuid4
import test_persistence_postgres as fixtures
from app.core.auth_boundary import AuthenticationRequired
from app.core.auth_policy import AccessDenied
from app.orders.models import DomainError
from app.order_events.service import OrderEventService
from app.order_events.postgres import EventRepository
from app.order_events.query import MAX_SEQUENCE


class OrderEventsPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixtures.PostgresCommandTests.setUpClass()

    def setUp(self):
        self.fixture=fixtures.PostgresCommandTests(methodName='runTest')
        self.addCleanup(self.fixture.doCleanups);self.fixture.setUp()
        self.service=OrderEventService(self.fixture.connect,real_clock=self.fixture.real)

    def read(self,order_id,query=None,actor=fixtures.EXECUTOR):
        return self.service.list_events(order_id,query or {},session_handle=actor)

    def test_pagination_ordered_events_share_version_and_advance_last_only(self):
        order_id=self.fixture.start();self.fixture.submit(order_id)
        first=self.read(order_id,{'limit':'2'})
        second=self.read(order_id,{'limit':'2','after_sequence':str(first['next_after_sequence'])})
        third=self.read(order_id,{'limit':'2','after_sequence':str(second['next_after_sequence'])})
        self.assertEqual([item['sequence'] for item in first['items']],[1,2]);self.assertTrue(first['has_more'])
        self.assertEqual([item['sequence'] for item in second['items']],[3,4]);self.assertTrue(second['has_more'])
        self.assertEqual([item['sequence'] for item in third['items']],[5]);self.assertFalse(third['has_more'])
        self.assertEqual(second['items'][-1]['kind'],'order.done')
        self.assertEqual(third['items'][0]['kind'],'order.ai_review_requested')
        self.assertEqual(second['items'][-1]['order_version'],third['items'][0]['order_version'])
        self.assertEqual(third['next_after_sequence'],5)
        self.assertEqual(self.read(order_id,{'after_sequence':'5'}),{'items':[],'next_after_sequence':5,'has_more':False})

    def test_reason_details_two_clocks_and_system_nullable_actor(self):
        order_id=self.fixture.start()
        self.fixture.domain.value+=timedelta(minutes=3)
        self.fixture.action(order_id,3,'pause',payload={'reason':'Синтетическая пауза'})
        page=self.read(order_id,{'after_sequence':'3'})
        event=page['items'][0]
        self.assertEqual(event['reason'],'Синтетическая пауза');self.assertEqual(event['details'],{})
        self.assertEqual(event['actor_id'],fixtures.EXECUTOR)
        self.assertNotEqual(event['occurred_at'],event['recorded_at'])
        self.fixture.action(order_id,4,'resume')
        self.fixture.action(order_id,5,'submit',payload={'work_description':'Синтетическая работа','work_code_id':fixtures.CODE,
            'materials':[],'after_photo_ids':[],'comment':''})
        events=self.read(order_id,{'after_sequence':'5'})['items']
        self.assertEqual(events[-1]['kind'],'order.ai_review_requested');self.assertIsNone(events[-1]['actor_id'])

    def test_former_assignee_cannot_read_historical_events(self):
        created,_=self.fixture.create();order_id=created.body['order']['id']
        self.assertTrue(self.read(order_id)['items'])
        self.fixture.action(order_id,1,'reassign',fixtures.MASTER,
            {'assignment':{'executor_id':fixtures.OTHER,'brigade_id':None},'reason':'Synthetic reassignment'})
        with self.assertRaises(AccessDenied):self.read(order_id,{'after_sequence':'1'})
        current=self.read(order_id,actor=fixtures.OTHER)
        self.assertEqual([item['sequence'] for item in current['items']],[1,2])
        self.assertEqual(current['items'][-1]['details']['previous_executor_id'],fixtures.EXECUTOR)

    def test_foreign_object_unknown_object_and_admin(self):
        created,_=self.fixture.create();order_id=created.body['order']['id']
        with self.assertRaises(AccessDenied):self.read(order_id,actor=fixtures.OTHER)
        with self.assertRaises(DomainError) as error:self.read(str(uuid4()))
        self.assertEqual(error.exception.code,'NOT_FOUND')
        self.fixture.query("UPDATE employees SET role='admin' WHERE id=%s RETURNING id",(fixtures.MASTER,))
        with self.assertRaises(AccessDenied):self.read(order_id,actor=fixtures.MASTER)

    def test_current_membership_account_and_session_checked_each_page(self):
        order_id=self.fixture.start();first=self.read(order_id,{'limit':'1'})
        self.fixture.query('DELETE FROM employee_sections WHERE employee_id=%s RETURNING employee_id',(fixtures.EXECUTOR,))
        with self.assertRaises(AccessDenied):self.read(order_id,{'after_sequence':str(first['next_after_sequence'])})
        self.fixture.query('INSERT INTO employee_sections VALUES (%s,%s) RETURNING employee_id',(fixtures.EXECUTOR,fixtures.SECTION))
        self.fixture.query('UPDATE employees SET active=false WHERE id=%s RETURNING id',(fixtures.EXECUTOR,))
        with self.assertRaises(AuthenticationRequired):self.read(order_id)
        self.fixture.query('UPDATE employees SET active=true WHERE id=%s RETURNING id',(fixtures.EXECUTOR,))
        self.fixture.query('UPDATE auth_sessions SET revoked_at=%s WHERE employee_id=%s RETURNING id',(fixtures.NOW,fixtures.EXECUTOR))
        with self.assertRaises(AuthenticationRequired):self.read(order_id)

    def test_future_valid_cursor_empty_overflow_rejected(self):
        created,_=self.fixture.create();order_id=created.body['order']['id']
        self.assertEqual(self.read(order_id,{'after_sequence':str(MAX_SEQUENCE)}),
                         {'items':[],'next_after_sequence':MAX_SEQUENCE,'has_more':False})
        with self.assertRaises(DomainError) as error:self.read(order_id,{'after_sequence':str(MAX_SEQUENCE+1)})
        self.assertEqual(error.exception.code,'VALIDATION_FAILED')

    def test_bigint_stored_sequence_and_fractional_details_return_exactly(self):
        created,_=self.fixture.create();order_id=created.body['order']['id']
        self.fixture.query('''INSERT INTO order_events(id,order_id,sequence,order_version,assignment_revision,scheduling_revision,
            kind,reason,details,actor_id,operation_id,from_status,to_status,submission_id,occurred_at,recorded_at)
            VALUES (%s,%s,%s,1,1,1,'order.assessment_recorded',NULL,'{"coverage":0.75}',NULL,NULL,'issued','issued',NULL,%s,%s) RETURNING id''',
            (str(uuid4()),order_id,MAX_SEQUENCE,fixtures.NOW,fixtures.NOW))
        page=self.read(order_id,{'after_sequence':str(MAX_SEQUENCE-1)})
        self.assertEqual(page['items'][0]['sequence'],MAX_SEQUENCE)
        self.assertEqual(page['items'][0]['details'],{'coverage':0.75})
        self.assertEqual(page['next_after_sequence'],MAX_SEQUENCE)

    def test_service_restart_and_new_committed_events_after_cursor(self):
        created,_=self.fixture.create();order_id=created.body['order']['id']
        cursor=self.read(order_id)['next_after_sequence']
        self.fixture.action(order_id,1,'accept')
        restarted=OrderEventService(self.fixture.connect,real_clock=self.fixture.real)
        page=restarted.list_events(order_id,{'after_sequence':str(cursor)},session_handle=fixtures.EXECUTOR)
        self.assertEqual([item['kind'] for item in page['items']],['order.accepted'])
        self.assertEqual(page['next_after_sequence'],2)

    def test_expired_session_after_actual_order_lock_wait_rejected_before_history(self):
        created,_=self.fixture.create();order_id=created.body['order']['id']
        arrived=Event();load=EventRepository.load_scope
        def announce(repo,*args):arrived.set();return load(repo,*args)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.fixture.connect() as owner:
                with owner.transaction():
                    owner.execute('SELECT id FROM orders WHERE id=%s FOR UPDATE',(order_id,))
                    with patch.object(EventRepository,'load_scope',announce):
                        future=pool.submit(self.read,order_id)
                        self.assertTrue(arrived.wait(10),'reader did not reach the held order lock')
                        self.fixture.real.value=fixtures.NOW+timedelta(days=6)
            with self.assertRaises(AuthenticationRequired):future.result(timeout=20)

    def test_assignment_changed_during_actual_lock_wait_is_currently_authorized(self):
        created,_=self.fixture.create();order_id=created.body['order']['id']
        arrived=Event();load=EventRepository.load_scope
        def announce(repo,*args):arrived.set();return load(repo,*args)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.fixture.connect() as owner:
                with owner.transaction():
                    owner.execute('SELECT id FROM orders WHERE id=%s FOR UPDATE',(order_id,))
                    with patch.object(EventRepository,'load_scope',announce):
                        future=pool.submit(self.read,order_id)
                        self.assertTrue(arrived.wait(10),'reader did not reach the held order lock')
                        owner.execute('UPDATE orders SET executor_id=%s WHERE id=%s',(fixtures.OTHER,order_id))
            with self.assertRaises(AccessDenied):future.result(timeout=20)


if __name__=='__main__':unittest.main()
