"""Independent live-database discovery tests; NOT_RUN without explicit test DSN.

Imports only frozen synthetic fixture helpers from the separately reviewed
persistence suite. No fake SQL backend and no installation fallback.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import os
from pathlib import Path
from threading import Event
from time import monotonic, sleep
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_persistence_postgres as fixture
from test_persistence_postgres import (PostgresCommandTests, MASTER, EXECUTOR, OTHER,
    SECTION, SECOND_SECTION, EQUIPMENT, SECOND_EQUIPMENT, uid)
from app.core.auth_boundary import AuthenticationRequired
from app.core.auth_policy import AccessDenied
from app.discovery.cursor import Cursor, OrderFilters, MAX_BIGINT
from app.discovery.postgres import DiscoveryRepository
from app.discovery.service import DiscoveryService
from app.discovery.workload import WorkloadPolicy, POLICY_NAME

# The helper otherwise resolves migration paths relative to its original test
# layout. Point it at the same frozen snapshot as the imported app package.
fixture.MIGRATIONS = Path(__file__).resolve().parents[1]/'snapshot/backend/db/migrations'


class IndependentDiscoveryPostgresTests(PostgresCommandTests):
    def setUp(self):
        super().setUp()
        self.discovery=DiscoveryService(self.connect,domain_clock=self.domain,real_clock=self.real,
            dictionary_policy=WorkloadPolicy(POLICY_NAME))

    def list(self,actor=EXECUTOR,**query):
        return self.discovery.list_orders({name:str(value) for name,value in query.items()},session_handle=actor)

    def dictionary(self,actor=MASTER):
        return self.discovery.get_dictionaries(session_handle=actor)

    def create_for(self,actor=EXECUTOR):
        request=fixture.create_command(); request['operation_id']=str(uuid4())
        request['payload']['assignment']['executor_id']=actor
        return self.run_command(request).body['order']

    def test_discovery_numeric_pages_exclude_newer_inserts(self):
        originals=[self.create_for() for _ in range(12)]
        page=self.list(limit=3)
        self.assertEqual([int(row['number']) for row in page['items']],[12,11,10])
        newcomer=self.create_for()
        rows=list(page['items'])
        while page['next_cursor']:
            page=self.list(limit=3,cursor=page['next_cursor'])
            rows+=page['items']
        self.assertEqual([int(row['number']) for row in rows],list(range(12,0,-1)))
        self.assertNotIn(newcomer['id'],[row['id'] for row in rows])
        self.assertEqual(len({row['id'] for row in rows}),12)

    def test_discovery_older_reassignment_enters_later_page_current_assignment_leaves(self):
        old=self.create_for(OTHER)
        moving_out=self.create_for()
        top=self.create_for()
        first=self.list(limit=1)
        self.assertEqual([row['id'] for row in first['items']],[top['id']])
        self.action(old['id'],1,'reassign',MASTER,{'assignment':{'executor_id':EXECUTOR,'brigade_id':None},'reason':'Synthetic reassignment in'})
        self.action(moving_out['id'],1,'reassign',MASTER,{'assignment':{'executor_id':OTHER,'brigade_id':None},'reason':'Synthetic reassignment out'})
        second=self.list(limit=1,cursor=first['next_cursor'])
        self.assertEqual([row['id'] for row in second['items']],[old['id']])
        self.assertEqual(second['items'][0]['assignment_revision'],2)
        self.assertIsNone(second['next_cursor'])

    def test_discovery_filters_are_intersected_and_cursor_never_grants_access(self):
        own=self.create_for(); foreign=self.create_for(OTHER)
        self.assertEqual(self.list(executor_id=OTHER)['items'],[])
        self.assertEqual(self.list(section_id=SECOND_SECTION)['items'],[])
        self.assertEqual(self.list(equipment_id=SECOND_EQUIPMENT)['items'],[])
        forged=Cursor(EXECUTOR,OrderFilters().fingerprint,MAX_BIGINT,MAX_BIGINT).encode()
        result=self.list(cursor=forged)
        self.assertEqual([row['id'] for row in result['items']],[own['id']])
        self.assertNotIn(foreign['id'],str(result))

    def test_discovery_per_page_membership_role_active_and_session_revocation(self):
        for _ in range(3): self.create_for()
        first=self.list(limit=1)
        self.query('DELETE FROM employee_sections WHERE employee_id=%s AND section_id=%s RETURNING employee_id',(EXECUTOR,SECTION))
        self.assertEqual(self.list(limit=1,cursor=first['next_cursor'])['items'],[])
        self.query('INSERT INTO employee_sections VALUES (%s,%s) RETURNING employee_id',(EXECUTOR,SECTION))
        self.query("UPDATE employees SET role='admin' WHERE id=%s RETURNING id",(EXECUTOR,))
        with self.assertRaises(AccessDenied): self.list(limit=1,cursor=first['next_cursor'])
        self.query("UPDATE employees SET role='executor',active=false WHERE id=%s RETURNING id",(EXECUTOR,))
        with self.assertRaises(AuthenticationRequired): self.list(limit=1,cursor=first['next_cursor'])
        self.query('UPDATE employees SET active=true WHERE id=%s RETURNING id',(EXECUTOR,))
        self.query('UPDATE auth_sessions SET revoked_at=%s WHERE employee_id=%s RETURNING id',(self.real.now(),EXECUTOR))
        with self.assertRaises(AuthenticationRequired): self.list(limit=1,cursor=first['next_cursor'])

    def test_discovery_dictionary_visible_assignment_survives_executor_scope_removal(self):
        active_id=self.start()
        self.query('INSERT INTO employee_sections VALUES (%s,%s) RETURNING employee_id',(EXECUTOR,SECOND_SECTION))
        self.query('DELETE FROM employee_sections WHERE employee_id=%s AND section_id=%s RETURNING employee_id',(EXECUTOR,SECTION))
        master_worker=next(row for row in self.dictionary()['executors'] if row['id']==EXECUTOR)
        self.assertEqual(master_worker['section_ids'],[SECOND_SECTION])
        self.assertEqual(master_worker['active_order_id'],active_id)
        executor_worker=self.dictionary(EXECUTOR)['executors']
        self.assertEqual(len(executor_worker),1)
        self.assertIsNone(executor_worker[0]['active_order_id'])
        self.assertEqual(executor_worker[0]['queue_count'],0)
        self.assertEqual(self.list()['items'],[])
        self.assertIn(active_id,[row['id'] for row in self.list(MASTER)['items']])

    def test_discovery_dictionary_offshift_multiple_actives_and_explicit_queue(self):
        first=self.start(); second=self.start()
        self.action(first,3,'pause',payload={'reason':'Synthetic pause'})
        queued=self.create_for(); self.action(queued['id'],1,'queue')
        issued=self.create_for()
        accepted=self.create_for(); self.action(accepted['id'],1,'accept')
        self.query('UPDATE employees SET on_shift=false WHERE id=%s RETURNING id',(EXECUTOR,))
        worker=next(row for row in self.dictionary()['executors'] if row['id']==EXECUTOR)
        self.assertEqual(worker['active_order_id'],first)
        self.assertEqual(worker['queue_count'],1)
        self.assertFalse(worker['on_shift'])
        self.query("UPDATE employees SET role='admin' WHERE id=%s RETURNING id",(MASTER,))
        result=self.dictionary()
        self.assertEqual(result['executors'],[])
        self.assertNotIn(first,str(result)); self.assertNotIn(second,str(result))

    def test_discovery_session_expiry_after_order_lock_wait_is_denied(self):
        item=self.create_for()
        entered=Event()
        waiting_pid=[]
        original=DiscoveryRepository.list_orders
        def watched(repo,*args):
            waiting_pid.append(repo.db.execute('SELECT pg_backend_pid() AS pid').fetchone()['pid'])
            entered.set()
            return original(repo,*args)
        with patch.object(DiscoveryRepository,'list_orders',watched),ThreadPoolExecutor(max_workers=1) as pool:
            with self.connect() as blocker:
                with blocker.transaction():
                    blocker.execute('SELECT id FROM orders WHERE id=%s FOR UPDATE',(item['id'],))
                    result=pool.submit(self.list)
                    self.assertTrue(entered.wait(10))
                    deadline=monotonic()+10
                    while monotonic()<deadline:
                        state=self.query('SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s',(waiting_pid[0],))
                        if state and state[0]['wait_event_type']=='Lock':
                            break
                        sleep(0.01)
                    else:
                        self.fail('Worker never reached an observed PostgreSQL lock wait')
                    self.assertFalse(result.done())
                    self.real.value+=timedelta(days=6)
            with self.assertRaises(AuthenticationRequired): result.result(timeout=15)


def load_tests(loader,standard_tests,pattern):
    # Avoid rerunning the inherited 33-test persistence suite in the reviewer lane.
    return unittest.TestSuite(IndependentDiscoveryPostgresTests(name)
        for name in sorted(IndependentDiscoveryPostgresTests.__dict__) if name.startswith('test_discovery_'))


if __name__=='__main__': unittest.main(verbosity=2)
