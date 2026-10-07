"""REAL PostgreSQL gate. Synthetic fixtures only; no transport, keys or sends.

Owner-created isolated schema plus a short-lived least-privilege test role. The
runtime service uses SET ROLE within each connection so permission failures are
real PostgreSQL checks, but this is not the A5 runtime direct-login startup gate.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from threading import Barrier
import unittest
from unittest.mock import Mock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.auth_boundary import AuthenticationRequired, SESSION_COOKIE_NAME
from app.core.auth_policy import AccessDenied
from app.orders.models import DomainError
from app.push.http import create_push_router
from app.push.postgres import PushRepository
from app.push.service import PushService
from test_push_unit import fixture

NOW=datetime(2026,10,7,20,tzinfo=timezone.utc)
ORIGIN='https://naryadai.test'
ROOT=Path(__file__).resolve().parents[1]


class PushPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn=os.environ.get('DALA_TEST_DATABASE_URL')
        if not cls.dsn:
            raise unittest.SkipTest('NOT_RUN: DALA_TEST_DATABASE_URL missing; real PostgreSQL required')
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row
        cls.pg,cls.sql,cls.dict_row=psycopg,sql,staticmethod(dict_row)

    def setUp(self):
        self.schema='push_'+uuid4().hex
        self.role='push_role_'+uuid4().hex
        self.users=[str(uuid4()),str(uuid4())]
        self.handles=['SYNTHETIC_ONLY_A_'+uuid4().hex,'SYNTHETIC_ONLY_B_'+uuid4().hex]
        self.section=str(uuid4())
        self.clock=Mock()
        self.clock.now.return_value=NOW
        _,self.settings,self.body=fixture()
        with self.pg.connect(self.dsn,autocommit=True) as db:
            db.execute(self.sql.SQL('CREATE SCHEMA {}').format(self.sql.Identifier(self.schema)))
            db.execute(self.sql.SQL('CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS').format(self.sql.Identifier(self.role)))
        self.addCleanup(self.cleanup)
        with self.owner() as db:
            for migration in sorted((ROOT/'db/migrations').glob('*.sql')):
                db.execute(migration.read_text())
            db.execute((ROOT/'db/proposals/005_web_push_subscriptions.sql').read_text())
            db.execute('INSERT INTO sections VALUES (%s,\'PUSH-SYNTHETIC\',\'Synthetic section\')',(self.section,))
            for index,(user,handle) in enumerate(zip(self.users,self.handles)):
                db.execute("INSERT INTO employees(id,employee_code,role,pin_hash) VALUES (%s,%s,'executor','not-used')",(user,'PUSH-SYNTHETIC-'+str(index)))
                db.execute('INSERT INTO employee_sections VALUES (%s,%s)',(user,self.section))
                db.execute('''INSERT INTO auth_sessions(id,employee_id,token_hash,csrf_token,created_at,expires_at)
                    VALUES (%s,%s,%s,'synthetic-csrf',%s,%s)''',
                    (str(uuid4()),user,sha256(handle.encode()).hexdigest(),NOW-timedelta(hours=1),NOW+timedelta(hours=1)))
            role=self.sql.Identifier(self.role)
            db.execute(self.sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(self.sql.Identifier(self.schema),role))
            db.execute(self.sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}').format(self.sql.Identifier(self.schema),role))
            for table,column in [('employees','id'),('employee_sections','employee_id'),('auth_sessions','id')]:
                db.execute(self.sql.SQL('GRANT UPDATE({}) ON {} TO {}').format(self.sql.Identifier(column),self.sql.Identifier(table),role))
            db.execute(self.sql.SQL('GRANT INSERT ON push_subscriptions TO {}').format(role))
            db.execute(self.sql.SQL('''GRANT UPDATE(session_hash,endpoint_hash,endpoint,p256dh,auth,expires_at,
                generation,active,updated_at,last_error_code) ON push_subscriptions TO {}''').format(role))
        self.service=PushService(self.connect,allowed_origin=ORIGIN,settings=self.settings,real_clock=self.clock)
        app=FastAPI()
        app.include_router(create_push_router(self.service))
        self.client=TestClient(app,base_url=ORIGIN)

    def owner(self):
        return self.pg.connect(self.dsn,autocommit=True,row_factory=self.dict_row,
            options=f'-c search_path={self.schema} -c statement_timeout=5000 -c lock_timeout=3000')

    def connect(self):
        db=self.owner()
        db.execute(self.sql.SQL('SET ROLE {}').format(self.sql.Identifier(self.role)))
        return db

    def cleanup(self):
        with self.pg.connect(self.dsn,autocommit=True) as db:
            db.execute(self.sql.SQL('DROP SCHEMA {} CASCADE').format(self.sql.Identifier(self.schema)))
            db.execute(self.sql.SQL('DROP ROLE {}').format(self.sql.Identifier(self.role)))

    def register(self, index=0, body=None, csrf='synthetic-csrf'):
        return self.service.mutate(json.dumps(body or self.body).encode(),session_handle=self.handles[index],
                                   origin=ORIGIN,csrf_token=csrf)

    def current(self, index=0):
        with self.connect() as db:
            return PushRepository(db).current(self.users[index],now=self.clock.now())

    def remove(self, index=0, endpoint=None):
        self.service.mutate(json.dumps({'endpoint':endpoint or self.body['endpoint']}).encode(),remove=True,
            session_handle=self.handles[index],origin=ORIGIN,csrf_token='synthetic-csrf')

    def test_actual_http_registration_and_private_config(self):
        headers={'Origin':ORIGIN,'X-CSRF-Token':'synthetic-csrf',
                 'Cookie':f'{SESSION_COOKIE_NAME}={self.handles[0]}'}
        response=self.client.post('/api/v1/push/subscriptions',json=self.body,headers=headers)
        self.assertEqual((response.status_code,response.json()),(200,{'enabled':True}))
        self.assertEqual(self.current().employee_id,self.users[0])
        config=self.client.get('/api/v1/push/config',headers=headers)
        self.assertEqual(config.status_code,200)
        self.assertNotIn(self.settings.private_key,config.text)
        self.assertNotIn(self.body['endpoint'],config.text)

    def test_server_identity_and_csrf_reject_before_write(self):
        with self.assertRaises(AccessDenied):
            self.register(csrf='wrong')
        with self.assertRaises(DomainError):
            self.register(body={**self.body,'employee_id':self.users[1]})
        with self.assertRaises(AuthenticationRequired):
            self.service.config(session_handle='synthetic-missing')
        self.assertIsNone(self.current())

    def test_current_user_removal_cannot_touch_other(self):
        self.register()
        self.remove(1)
        self.assertIsNotNone(self.current())
        self.remove()
        self.assertIsNone(self.current())
        self.remove()  # idempotent

    def test_endpoint_cannot_change_owner(self):
        self.register()
        with self.assertRaises(DomainError) as caught:
            self.register(1)
        self.assertEqual(caught.exception.code,'SUBSCRIPTION_CONFLICT')
        self.assertEqual(self.current().employee_id,self.users[0])
        self.assertIsNone(self.current(1))

    def test_late_gone_cleanup_does_not_disable_rotated_generation(self):
        self.register()
        previous=self.current()
        self.register(body={**self.body,'endpoint':self.body['endpoint']+'-rotated'})
        current=self.current()
        self.assertNotEqual(previous.generation,current.generation)
        with self.connect() as db:
            PushRepository(db).deactivate(previous,now=NOW,code='PUSH_GONE')
        self.assertIsNotNone(self.current())
        with self.connect() as db:
            PushRepository(db).deactivate(current,now=NOW,code='PUSH_GONE')
        self.assertIsNone(self.current())

    def test_session_revoke_expiry_and_employee_inactive_disable_selection(self):
        self.register()
        self.clock.now.return_value=NOW+timedelta(hours=2)
        self.assertIsNone(self.current())
        self.clock.now.return_value=NOW
        with self.owner() as db:
            db.execute('UPDATE auth_sessions SET revoked_at=%s WHERE employee_id=%s',(NOW,self.users[0]))
        self.assertIsNone(self.current())
        with self.assertRaises(AuthenticationRequired):
            self.register()
        with self.owner() as db:
            db.execute('UPDATE employees SET active=false WHERE id=%s',(self.users[0],))
        self.assertIsNone(self.current())

    def test_one_device_bounded_storage_and_repeat_safe(self):
        for suffix in range(8):
            self.register(body={**self.body,'endpoint':self.body['endpoint']+'-'+str(suffix)})
        with self.connect() as db:
            count=db.execute('SELECT count(*) AS n FROM push_subscriptions').fetchone()['n']
        self.assertEqual(count,1)
        self.assertTrue(self.current().subscription.endpoint.endswith('-7'))

    def test_concurrent_same_user_registration_no_deadlock(self):
        barrier=Barrier(2)
        def write(suffix):
            barrier.wait()
            return self.register(body={**self.body,'endpoint':self.body['endpoint']+'-'+suffix})
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(write,['concurrent-a','concurrent-b']))
        self.assertEqual(results,[{'enabled':True},{'enabled':True}])
        self.assertIsNotNone(self.current())

    def test_ownership_and_destructive_grants_denied(self):
        self.register()
        with self.connect() as db:
            for query in ['DELETE FROM push_subscriptions','TRUNCATE push_subscriptions',
                          'UPDATE push_subscriptions SET employee_id=employee_id']:
                with self.assertRaises(self.pg.errors.InsufficientPrivilege):
                    db.execute(query)
        with self.owner() as db:
            with self.assertRaises(self.pg.errors.CheckViolation):
                db.execute('UPDATE push_subscriptions SET employee_id=%s WHERE employee_id=%s',(self.users[1],self.users[0]))


if __name__=='__main__':
    unittest.main()
