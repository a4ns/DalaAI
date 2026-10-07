"""Mock/recorded orchestration tests, not PostgreSQL execution."""
from datetime import timedelta
import unittest
from unittest.mock import patch
from app.core.auth_boundary import AuthContext,SessionRecord,AuthenticationRequired
from app.core.auth_policy import Principal,Role,OrderScope,AccessDenied
from app.orders.models import DomainError
from app.order_events.service import OrderEventService
from app.order_events.postgres import EventRepository
from app.order_events.query import parse_query,MAX_SEQUENCE
from test_order_events_pure import event,uid,NOW,ORDER


class Clock:
    def __init__(self):self.value=NOW
    def now(self):return self.value


class DB:
    def __init__(self):self.calls=[]
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def transaction(self):return self
    def execute(self,sql,params=()):self.calls.append((sql,params));return self
    def fetchall(self):return []


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.db=DB()
        self.scope=OrderScope(ORDER,uid(3),uid(2),1)
        self.principal=Principal(uid(2),Role.EXECUTOR,frozenset({uid(3)}))
        self.session=SessionRecord(uid(2),NOW-timedelta(minutes=1),NOW+timedelta(seconds=1),'synthetic')
        self.service=OrderEventService(lambda:None,real_clock=self.clock)
        self.service._connection=lambda:self.db
        self.auth_count=0
        def auth(*args):
            self.auth_count+=1
            if self.clock.now()>=self.session.expires_at:raise AuthenticationRequired()
            return AuthContext(self.principal,self.session)
        self.service._auth=auth
        scope_patch=patch.object(EventRepository,'load_scope',return_value=self.scope)
        self.load=scope_patch.start();self.addCleanup(scope_patch.stop)

    def read(self,query=None):return self.service.list_events(ORDER,query or {},session_handle='synthetic')

    def test_sequence_gaps_and_lookahead_do_not_skip_an_event(self):
        with patch.object(EventRepository,'read_page',return_value=[event(1),event(7),event(11)]):
            page=self.read({'limit':'2'})
        self.assertEqual([r['sequence'] for r in page['items']],[1,7])
        self.assertEqual(page['next_after_sequence'],7);self.assertTrue(page['has_more'])
        self.assertEqual(self.auth_count,3)

    def test_empty_future_cursor_preserved_and_no_fabricated_progress(self):
        with patch.object(EventRepository,'read_page',return_value=[]):
            self.assertEqual(self.read({'after_sequence':str(MAX_SEQUENCE)}),
                             {'items':[],'next_after_sequence':MAX_SEQUENCE,'has_more':False})

    def test_two_events_can_share_one_order_version(self):
        with patch.object(EventRepository,'read_page',return_value=[event(4,kind='order.done',to_status='done'),event(5)]):
            page=self.read({'after_sequence':'3'})
        self.assertEqual([r['order_version'] for r in page['items']],[4,4])
        self.assertEqual(page['next_after_sequence'],5)

    def test_foreign_executor_denied_before_event_query(self):
        self.principal=Principal(uid(99),Role.EXECUTOR,frozenset({uid(3)}))
        with patch.object(EventRepository,'read_page') as read,self.assertRaises(AccessDenied):self.read()
        read.assert_not_called()

    def test_admin_denied_and_manager_scoped_read_allowed(self):
        for role,allowed in ((Role.ADMIN,False),(Role.MANAGER,True),(Role.MASTER,True)):
            self.principal=Principal(uid(5),role,frozenset({uid(3)}))
            with patch.object(EventRepository,'read_page',return_value=[]):
                if allowed:self.assertEqual(self.read()['items'],[])
                else:
                    with self.assertRaises(AccessDenied):self.read()

    def test_missing_order_returns_not_found_without_history(self):
        self.load.return_value=None
        with patch.object(EventRepository,'read_page') as read,self.assertRaises(DomainError) as error:self.read()
        self.assertEqual(error.exception.code,'NOT_FOUND');read.assert_not_called()

    def test_expired_during_order_lock_denied_before_history(self):
        def waited(*args):self.clock.value+=timedelta(seconds=2);return self.scope
        self.load.side_effect=waited
        with patch.object(EventRepository,'read_page') as read,self.assertRaises(AuthenticationRequired):self.read()
        read.assert_not_called()

    def test_expired_during_history_query_denied_before_response(self):
        def waited(*args):self.clock.value+=timedelta(seconds=2);return [event()]
        with patch.object(EventRepository,'read_page',side_effect=waited),self.assertRaises(AuthenticationRequired):self.read()

    def test_changed_scope_at_final_auth_denies_history(self):
        def changed(*args):self.principal=Principal(uid(2),Role.EXECUTOR,frozenset());return [event()]
        with patch.object(EventRepository,'read_page',side_effect=changed),self.assertRaises(AccessDenied):self.read()

    def test_bad_repository_ordering_and_scope_fails_closed(self):
        for rows in ([event(3),event(2)],[event(2),event(2)],[event(1,order_id=uid(99))]):
            with self.subTest(rows=rows),patch.object(EventRepository,'read_page',return_value=rows),self.assertRaises(DomainError):self.read()

    def test_recorded_sql_is_order_scoped_ascending_bounded_and_explicit(self):
        EventRepository(self.db).read_page(ORDER,parse_query({'after_sequence':'10','limit':'2'}))
        sql,params=self.db.calls[-1]
        self.assertIn('WHERE order_id=%s AND sequence>%s ORDER BY sequence ASC LIMIT %s',sql)
        self.assertNotIn('SELECT *',sql);self.assertNotIn(ORDER,sql)
        self.assertEqual(params,(ORDER,10,3))
