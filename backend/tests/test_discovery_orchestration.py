"""Mock/recording orchestration only; not SQL execution or PostgreSQL evidence."""
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import unittest
from app.core.auth_boundary import AuthContext,SessionRecord,AuthenticationRequired
from app.core.auth_policy import Principal,Role,AccessDenied
from app.orders.models import Order,Assignment,OrderType,Priority,Status,DomainError
from app.discovery.service import DiscoveryService
from app.discovery.cursor import parse_query,Cursor
from app.discovery.postgres import DiscoveryRepository
from app.discovery.workload import WorkloadPolicy,POLICY_NAME

NOW=datetime(2026,10,7,17,tzinfo=timezone.utc)
def uid(n):return f'00000000-0000-4000-8000-{n:012d}'
MASTER,EXECUTOR,SECTION=uid(1),uid(2),uid(3)


class Clock:
    def __init__(self):self.value=NOW
    def now(self):return self.value


class DB:
    def __init__(self):self.calls=[]
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def transaction(self):return self
    def execute(self,query,params=()):
        self.calls.append((query,params));return self
    def fetchall(self):return []


def order(n):
    return Order(uid(n+100),str(n),1,1,1,Status.ISSUED,OrderType.UNPLANNED,'Synthetic',SECTION,uid(4),
        Assignment(EXECUTOR,None),MASTER,NOW,NOW+timedelta(hours=1),30,Priority.NORMAL,'',(),None,NOW)


class OrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.db=DB()
        self.principal=Principal(MASTER,Role.MASTER,frozenset({SECTION}))
        self.session=SessionRecord(MASTER,NOW-timedelta(hours=1),NOW+timedelta(seconds=1),'synthetic')
        self.service=DiscoveryService(lambda:None,domain_clock=self.clock,real_clock=self.clock,
            dictionary_policy=WorkloadPolicy(POLICY_NAME))
        self.service._connection=lambda:self.db
        self.auth_calls=0
        def authenticate(db,handle):
            self.auth_calls+=1
            if self.clock.now()>=self.session.expires_at:
                raise AuthenticationRequired()
            return AuthContext(self.principal,self.session)
        self.service._auth=authenticate

    def test_page_continuation_uses_extra_row_and_numeric_bounds(self):
        with patch.object(DiscoveryRepository,'list_orders',return_value=[order(12),order(11),order(10)]):
            result=self.service.list_orders({'limit':'2'},session_handle='synthetic')
        self.assertEqual([item['number'] for item in result['items']],['12','11'])
        cursor=Cursor.decode(result['next_cursor'],actor_id=MASTER,filters=parse_query({}).filters)
        self.assertEqual((cursor.upper_number,cursor.last_number),(12,11))
        self.assertEqual(self.auth_calls,2)

    def test_end_and_empty_page_have_null_cursor(self):
        for rows in ([],[order(1)]):
            with patch.object(DiscoveryRepository,'list_orders',return_value=rows):
                result=self.service.list_orders({'limit':'2'},session_handle='synthetic')
            self.assertIsNone(result['next_cursor'])

    def test_expired_session_after_list_lock_wait_is_denied(self):
        def waited(*args):
            self.clock.value+=timedelta(seconds=2)
            return [order(1)]
        with patch.object(DiscoveryRepository,'list_orders',side_effect=waited),self.assertRaises(AuthenticationRequired):
            self.service.list_orders({},session_handle='synthetic')

    def test_expired_session_after_dictionary_reads_is_denied(self):
        def waited(*args):
            self.clock.value+=timedelta(seconds=2)
            return {}
        with patch.object(DiscoveryRepository,'dictionaries',side_effect=waited),self.assertRaises(AuthenticationRequired):
            self.service.get_dictionaries(session_handle='synthetic')

    def test_fresh_authorization_denies_changed_scope(self):
        def changed(*args):
            self.principal=Principal(MASTER,Role.MASTER,frozenset())
            return [order(1)]
        with patch.object(DiscoveryRepository,'list_orders',side_effect=changed),self.assertRaises(AccessDenied):
            self.service.list_orders({},session_handle='synthetic')

    def test_dictionary_projection_denied_when_principal_changed(self):
        def changed(*args):
            self.principal=Principal(MASTER,Role.MANAGER,frozenset({SECTION}))
            return {}
        with patch.object(DiscoveryRepository,'dictionaries',side_effect=changed),self.assertRaises(AccessDenied):
            self.service.get_dictionaries(session_handle='synthetic')

    def test_admin_list_denied_before_repository(self):
        self.principal=Principal(MASTER,Role.ADMIN,frozenset({SECTION}))
        with patch.object(DiscoveryRepository,'list_orders') as read,self.assertRaises(AccessDenied):
            self.service.list_orders({},session_handle='synthetic')
        read.assert_not_called()

    def test_dictionary_policy_must_be_explicitly_enabled(self):
        self.service.dictionary_policy=None
        with patch.object(DiscoveryRepository,'dictionaries') as read,self.assertRaises(DomainError) as error:
            self.service.get_dictionaries(session_handle='synthetic')
        self.assertEqual(error.exception.code,'TEMPORARILY_UNAVAILABLE');read.assert_not_called()

    def test_cursor_reuse_rejected_before_any_list_query(self):
        token=Cursor(EXECUTOR,parse_query({}).filters.fingerprint,12,11).encode()
        with patch.object(DiscoveryRepository,'list_orders') as read,self.assertRaises(DomainError):
            self.service.list_orders({'cursor':token},session_handle='synthetic')
        read.assert_not_called()

    def test_recorded_sql_intersects_executor_scope_filter_and_cursor(self):
        principal=Principal(EXECUTOR,Role.EXECUTOR,frozenset({SECTION}))
        query=parse_query({'limit':'2','executor_id':uid(99),'status':'queued'})
        cursor=Cursor(EXECUTOR,query.filters.fingerprint,12,11)
        DiscoveryRepository(self.db).list_orders(principal,query,cursor)
        sql,params=self.db.calls[-1]
        self.assertIn('o.section_id=ANY(%s::uuid[])',sql)
        self.assertIn('o.executor_id=%s::uuid',sql)
        self.assertIn('o.executor_id=%s',sql)
        self.assertIn('o.number<=%s AND o.number<%s',sql)
        self.assertIn('ORDER BY o.number DESC LIMIT %s FOR SHARE OF o',sql)
        self.assertEqual(params,([SECTION],EXECUTOR,'queued',uid(99),12,11,3))
        self.assertNotIn(uid(99),sql)
