"""Disposable PostgreSQL recommendations: author, restricted login and main."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if (os.environ.get('DALA_ACCEPTANCE_DISPOSABLE') != '1'
        or not os.environ.get('DALA_TEST_DATABASE_URL')):
    print('NOT_RUN: explicit disposable PostgreSQL setup required')
    raise SystemExit(2)
os.environ['DALA_ASSIGNEE_POSTGRES_ACCEPTANCE'] = '1'
sys.path[:0] = [str(ROOT/'backend'), str(ROOT/'backend/tests'),
               str(ROOT/'backend/tests/integration'), str(ROOT/'ops/provision')]

from test_persistence_role import ApplicationRoleTests
from test_assignee_recommendations_postgres import AssigneePostgresTests, SESSION_COOKIE_NAME
from database_profile import grant_existing_runtime_role


class RestrictedAssignees(AssigneePostgresTests):
    def runtime_connect(self):
        return self.pg.connect(ApplicationRoleTests.runtime_dsn, autocommit=True, connect_timeout=3,
            options=f'-c search_path={self.schema} -c statement_timeout=10000 -c lock_timeout=3000',
            row_factory=self.dict_row)

    def setUp(self):
        super().setUp()
        with self.connect() as owner:
            owner.execute((ROOT/'backend/db/proposals/003_auth_rate_limits.sql').read_text())
        grant_existing_runtime_role(self.connect, self.runtime_connect, self.schema)
        self.service.connect = self.runtime_connect
        with self.runtime_connect() as db:
            row = db.execute('SELECT current_user AS role, session_user AS login').fetchone()
        self.assertEqual(row['role'], ApplicationRoleTests.runtime_role)
        self.assertEqual(row['login'], row['role'])


class MountedAssignees(RestrictedAssignees):
    def test_actual_main_protected_recommendations_have_no_effects(self):
        from app.main import create_app
        from app.runtime import RuntimeSettings
        from fastapi.testclient import TestClient
        from hashlib import sha256
        from uuid import uuid4
        from datetime import timedelta

        origin = 'https://recommendations.test'
        settings = RuntimeSettings(mode='demo', database_url=ApplicationRoleTests.runtime_dsn,
            allowed_origin=origin, database_schema=self.schema)
        executor_handle = uuid4().hex
        with self.connect() as owner:
            owner.execute('''INSERT INTO auth_sessions(id,employee_id,token_hash,csrf_token,created_at,expires_at)
                VALUES (%s,%s,%s,%s,%s,%s)''', (str(uuid4()), self.executor,
                sha256(executor_handle.encode()).hexdigest(), uuid4().hex,
                self.real.now()-timedelta(minutes=1), self.real.now()+timedelta(hours=1)))
        before = self.state()
        with patch('app.core.auth_boundary.SystemRealClock', return_value=self.real):
            app = create_app(settings=settings, connect=self.runtime_connect)
        path = '/api/v1/recommendations/assignees'
        with TestClient(app, base_url=origin, client=('127.0.0.1', 45100)) as client:
            self.assertEqual(client.get('/readyz').status_code, 200)
            query = {'section_id': self.section}
            self.assertEqual(client.get(path, params=query).status_code, 401)
            self.assertEqual(client.get(path, params=query,
                headers={'cookie': SESSION_COOKIE_NAME+'='+executor_handle}).status_code, 403)
            headers = {'cookie': SESSION_COOKIE_NAME+'='+self.handle}
            self.assertEqual(client.get(path, params={'section_id': self.hidden_section},
                headers=headers).status_code, 403)
            response = client.get(path, params=query, headers=headers)
            self.assertEqual(response.status_code, 200, 'Mounted recommendations failed')
            self.assertEqual(response.json()['mode'], 'rules_baseline')
            self.assertIsNone(response.json()['model'])
            self.assertEqual(response.json()['eligible_count'], 1)
            self.assertEqual(response.json()['candidates'][0]['executor_id'], self.executor)
            self.assertIn('no-store', response.headers['cache-control'])
            self.assertEqual(client.post(path, json=query, headers=headers).status_code, 405)
        self.assertEqual(before, self.state())


def run(suite, expected, label):
    if suite.countTestCases() != expected:
        raise SystemExit('FAIL: '+label+' case count changed')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.skipped or result.testsRun != expected or not result.wasSuccessful():
        raise SystemExit('FAIL: '+label)
    print(f'PASS: {label}, {expected} actual PostgreSQL tests, zero skips')


run(unittest.defaultTestLoader.loadTestsFromTestCase(AssigneePostgresTests), 13,
    'Assignee author PostgreSQL')
ApplicationRoleTests.setUpClass()
try:
    run(unittest.defaultTestLoader.loadTestsFromTestCase(RestrictedAssignees), 13,
        'Assignee restricted API LOGIN')
    run(unittest.TestSuite([MountedAssignees('test_actual_main_protected_recommendations_have_no_effects')]), 1,
        'Actual app.main recommendations')
finally:
    ApplicationRoleTests.doClassCleanups()
    if ApplicationRoleTests.tearDown_exceptions:
        raise SystemExit('FAIL: recommendation-role cleanup not confirmed')
