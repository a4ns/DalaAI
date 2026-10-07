"""Real PostgreSQL gate; uses unchanged frozen persistence fixture setup only.

No SQLite or mock fallback. Missing DSN => NOT_RUN in ordinary local discovery;
configured DSN errors fail. Production integrations must use the non-skipping gate.
"""
from datetime import timedelta
import unittest
from unittest.mock import patch

# Module import avoids re-discovering the parent TestCase's 24 transaction tests.
import test_persistence_postgres as fixtures
from app.core.auth_boundary import AuthenticationRequired
from app.core.auth_policy import AccessDenied
from app.orders.models import DomainError
from app.discovery.service import DiscoveryService
from app.discovery.postgres import DiscoveryRepository
from app.discovery.workload import WorkloadPolicy,POLICY_NAME


class DiscoveryPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.PostgresCommandTests.setUpClass()

    def setUp(self):
        self.fixture=fixtures.PostgresCommandTests(methodName='runTest')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.service=DiscoveryService(self.fixture.connect,domain_clock=self.fixture.domain,
            real_clock=self.fixture.real,dictionary_policy=WorkloadPolicy(POLICY_NAME))

    def create(self,actor=None):
        result,command=self.fixture.create()
        if actor is not None:
            self.fixture.query('UPDATE orders SET executor_id=%s WHERE id=%s RETURNING id',
                               (actor,result.body['order']['id']))
        return result.body['order']

    def page(self,query=None,actor=fixtures.MASTER):
        return self.service.list_orders(query or {},session_handle=actor)

    def dictionaries(self,actor=fixtures.MASTER):
        return self.service.get_dictionaries(session_handle=actor)

    def test_numeric_keyset_walk_covers_all_rows_without_lexical_order(self):
        for _ in range(12):self.create()
        numbers=[];cursor=None
        while True:
            query={'limit':'5'}
            if cursor:query['cursor']=cursor
            page=self.page(query)
            numbers.extend(int(item['number']) for item in page['items'])
            cursor=page['next_cursor']
            if cursor is None:break
        self.assertEqual(numbers,list(range(12,0,-1)))

    def test_new_create_excluded_from_current_sweep_discovered_on_restart(self):
        for _ in range(4):self.create()
        first=self.page({'limit':'2'})
        new=self.create()
        second=self.page({'limit':'2','cursor':first['next_cursor']})
        self.assertEqual([item['number'] for item in second['items']],['2','1'])
        self.assertIsNone(second['next_cursor'])
        self.assertEqual(self.page({'limit':'1'})['items'][0]['id'],new['id'])

    def test_cursor_actor_and_filter_binding(self):
        for _ in range(3):self.create()
        first=self.page({'limit':'1','status':'issued'})
        for actor,extra in ((fixtures.EXECUTOR,{'status':'issued'}),(fixtures.MASTER,{'status':'queued'})):
            with self.subTest(actor=actor,extra=extra),self.assertRaises(DomainError) as error:
                self.page({'limit':'1','cursor':first['next_cursor'],**extra},actor)
            self.assertEqual(error.exception.code,'INVALID_REQUEST')

    def test_foreign_executor_filter_cannot_expand_object_scope(self):
        own=self.create();foreign=self.create(fixtures.OTHER)
        self.assertEqual([r['id'] for r in self.page(actor=fixtures.EXECUTOR)['items']],[own['id']])
        self.assertEqual(self.page({'executor_id':fixtures.OTHER},fixtures.EXECUTOR)['items'],[])
        self.assertEqual([r['id'] for r in self.page({'executor_id':fixtures.OTHER})['items']],[foreign['id']])

    def test_scope_revocation_between_pages_is_effective(self):
        for _ in range(3):self.create()
        first=self.page({'limit':'1'},fixtures.EXECUTOR)
        self.fixture.query('DELETE FROM employee_sections WHERE employee_id=%s RETURNING employee_id',(fixtures.EXECUTOR,))
        second=self.page({'limit':'1','cursor':first['next_cursor']},fixtures.EXECUTOR)
        self.assertEqual(second,{'items':[],'next_cursor':None})

    def test_old_reassigned_order_is_found_beyond_first_page(self):
        oldest=self.create(fixtures.OTHER)
        for _ in range(4):self.create()
        first=self.page({'limit':'2'},fixtures.EXECUTOR)
        self.fixture.action(oldest['id'],1,'reassign',fixtures.MASTER,
            {'assignment':{'executor_id':fixtures.EXECUTOR,'brigade_id':None},'reason':'Synthetic reassignment'})
        ids=[item['id'] for item in first['items']]
        cursor=first['next_cursor']
        while cursor:
            page=self.page({'limit':'2','cursor':cursor},fixtures.EXECUTOR)
            ids.extend(item['id'] for item in page['items']);cursor=page['next_cursor']
        self.assertIn(oldest['id'],ids)
        self.assertNotIn(oldest['id'],[item['id'] for item in first['items']])

    def test_dictionary_multiple_active_representative_and_explicit_queue(self):
        statuses=['paused','in_progress','queued','queued','issued','accepted','rework','closed','ai_review']
        created=[]
        for status in statuses:
            item=self.create();created.append(item)
            self.fixture.query('UPDATE orders SET status=%s WHERE id=%s RETURNING id',(status,item['id']))
        worker=next(item for item in self.dictionaries()['executors'] if item['id']==fixtures.EXECUTOR)
        self.assertEqual(worker['active_order_id'],created[0]['id'])
        self.assertEqual(worker['queue_count'],2)
        self.assertEqual(self.dictionaries(fixtures.EXECUTOR)['executors'],[worker])

    def test_dictionary_hides_foreign_sections_brigades_equipment_and_workers(self):
        foreign_brigade=fixtures.uid(80)
        self.fixture.query('INSERT INTO brigades VALUES (%s,%s,%s,%s) RETURNING id',
                           (foreign_brigade,fixtures.SECOND_SECTION,'PRIVATE','Private foreign brigade'))
        self.fixture.query('UPDATE employees SET brigade_id=%s WHERE id=%s RETURNING id',(foreign_brigade,fixtures.OTHER))
        self.fixture.query('DELETE FROM employee_sections WHERE employee_id=%s RETURNING employee_id',(fixtures.OTHER,))
        self.fixture.query('INSERT INTO employee_sections VALUES (%s,%s) RETURNING employee_id',(fixtures.OTHER,fixtures.SECOND_SECTION))
        self.fixture.query('DELETE FROM employee_sections WHERE employee_id=%s AND section_id=%s RETURNING employee_id',
                           (fixtures.MASTER,fixtures.SECOND_SECTION))
        data=self.dictionaries()
        self.assertEqual([item['id'] for item in data['sections']],[fixtures.SECTION])
        self.assertEqual([item['id'] for item in data['equipment']],[fixtures.EQUIPMENT])
        self.assertEqual(data['brigades'],[])
        self.assertNotIn(fixtures.OTHER,[item['id'] for item in data['executors']])
        self.assertNotIn(foreign_brigade,str(data));self.assertNotIn(fixtures.SECOND_SECTION,str(data))
        self.assertTrue(data['work_codes']);self.assertTrue(data['materials']) # explicitly global catalogues
        self.assertNotIn('pin_hash',str(data));self.assertNotIn('token_hash',str(data))

    def test_visible_worker_does_not_expose_hidden_membership_or_brigade_id(self):
        foreign_brigade=fixtures.uid(81)
        self.fixture.query('INSERT INTO brigades VALUES (%s,%s,%s,%s) RETURNING id',
                           (foreign_brigade,fixtures.SECOND_SECTION,'PRIVATE','Private'))
        self.fixture.query('INSERT INTO employee_sections VALUES (%s,%s) RETURNING employee_id',
                           (fixtures.EXECUTOR,fixtures.SECOND_SECTION))
        self.fixture.query('UPDATE employees SET brigade_id=%s WHERE id=%s RETURNING id',(foreign_brigade,fixtures.EXECUTOR))
        self.fixture.query('DELETE FROM employee_sections WHERE employee_id=%s AND section_id=%s RETURNING employee_id',
                           (fixtures.MASTER,fixtures.SECOND_SECTION))
        worker=next(item for item in self.dictionaries()['executors'] if item['id']==fixtures.EXECUTOR)
        self.assertEqual(worker['section_ids'],[fixtures.SECTION]);self.assertIsNone(worker['brigade_id'])
        self.assertNotIn(foreign_brigade,str(worker))

    def test_admin_catalogues_without_workload_and_no_order_list(self):
        self.create()
        self.fixture.query("UPDATE employees SET role='admin' WHERE id=%s RETURNING id",(fixtures.MASTER,))
        data=self.dictionaries()
        self.assertEqual(data['executors'],[]);self.assertTrue(data['equipment'])
        with self.assertRaises(AccessDenied):self.page()

    def test_empty_scope_and_inactive_executor_are_not_disclosed(self):
        self.fixture.query('UPDATE employees SET active=false WHERE id=%s RETURNING id',(fixtures.OTHER,))
        self.assertNotIn(fixtures.OTHER,[item['id'] for item in self.dictionaries()['executors']])
        self.fixture.query('DELETE FROM employee_sections WHERE employee_id=%s RETURNING employee_id',(fixtures.MASTER,))
        self.assertTrue(all(not values for values in self.dictionaries().values()))

    def test_security_time_refreshed_after_list_or_dictionary_reads(self):
        self.create()
        for method,call in (('list_orders',lambda:self.page()),('dictionaries',lambda:self.dictionaries())):
            self.fixture.real.value=fixtures.NOW
            original=getattr(DiscoveryRepository,method)
            def waited(repo,*args,_original=original):
                result=_original(repo,*args)
                self.fixture.real.value=fixtures.NOW+timedelta(days=6)
                return result
            with patch.object(DiscoveryRepository,method,waited),self.assertRaises(AuthenticationRequired):call()

    def test_list_current_snapshots_after_state_change_and_restart(self):
        item=self.create()
        self.fixture.action(item['id'],1,'accept')
        restarted=DiscoveryService(self.fixture.connect,domain_clock=self.fixture.domain,real_clock=self.fixture.real,
            dictionary_policy=WorkloadPolicy(POLICY_NAME))
        data=restarted.list_orders({'status':'accepted'},session_handle=fixtures.EXECUTOR)
        self.assertEqual(data['items'][0]['version'],2)
        self.assertEqual(data['items'][0]['status'],'accepted')
        self.assertEqual(self.page({'status':'issued'})['items'],[])


if __name__=='__main__':unittest.main()
