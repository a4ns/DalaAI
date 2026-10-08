"""Disposable PG report-summary gates; provider transport is recorded only."""
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
os.environ['DALA_AI_SUMMARY_POSTGRES_ACCEPTANCE'] = '1'
sys.path[:0] = [str(ROOT/'backend'), str(ROOT/'backend/tests'),
               str(ROOT/'backend/tests/integration'), str(ROOT/'ops/provision')]

from test_persistence_role import ApplicationRoleTests
from test_ai_summary_postgres import AIReportPostgresTests, SESSION_COOKIE_NAME
from database_profile import grant_existing_runtime_role


class RestrictedAIReports(AIReportPostgresTests):
    def runtime_connect(self):
        return self.pg.connect(ApplicationRoleTests.runtime_dsn, autocommit=True, connect_timeout=3,
            options=f'-c search_path={self.schema} -c statement_timeout=10000 -c lock_timeout=3000',
            row_factory=self.dict_row)

    def setUp(self):
        super().setUp()
        with self.connect() as owner:
            owner.execute((ROOT/'backend/db/proposals/003_auth_rate_limits.sql').read_text())
        grant_existing_runtime_role(self.connect, self.runtime_connect, self.schema)
        self.sessions.connect = self.runtime_connect
        with self.runtime_connect() as db:
            row = db.execute('SELECT current_user AS role, session_user AS login').fetchone()
        self.assertEqual(row['role'], ApplicationRoleTests.runtime_role)
        self.assertEqual(row['login'], row['role'])


class MountedAIReports(RestrictedAIReports):
    def test_actual_main_keyless_summary_and_access_checks(self):
        from app.main import create_app
        from app.runtime import RuntimeSettings
        from fastapi.testclient import TestClient
        from hashlib import sha256
        from uuid import uuid4
        from datetime import timedelta

        origin = 'https://reports.test'
        settings = RuntimeSettings(mode='demo', database_url=ApplicationRoleTests.runtime_dsn,
            allowed_origin=origin, database_schema=self.schema)
        executor_handle = uuid4().hex
        with self.connect() as owner:
            owner.execute('''INSERT INTO auth_sessions(id,employee_id,token_hash,csrf_token,created_at,expires_at)
                VALUES (%s,%s,%s,%s,%s,%s)''', (str(uuid4()), self.executor,
                sha256(executor_handle.encode()).hexdigest(), uuid4().hex,
                self.real.now()-timedelta(minutes=1), self.real.now()+timedelta(hours=1)))
            before = {table: owner.execute('SELECT count(*) AS n FROM '+table).fetchone()['n']
                for table in ('orders', 'submissions', 'reviews', 'order_events', 'auth_sessions', 'ai_jobs')}
        with patch('app.core.auth_boundary.SystemRealClock', return_value=self.real):
            app = create_app(settings=settings, connect=self.runtime_connect)
        path = '/api/v1/reports/ai-summary'
        with TestClient(app, base_url=origin, client=('127.0.0.1', 45200)) as client:
            self.assertEqual(client.get('/readyz').status_code, 200)
            self.assertEqual(client.post(path, json=self.body, headers={'origin': origin}).status_code, 401)
            headers = {'cookie': SESSION_COOKIE_NAME+'='+self.handle,
                       'origin': origin, 'x-csrf-token': self.csrf}
            self.assertEqual(client.post(path, json=self.body,
                headers={**headers, 'origin': 'https://foreign.test'}).status_code, 403)
            self.assertEqual(client.post(path, json=self.body,
                headers={**headers, 'x-csrf-token': 'wrong'}).status_code, 403)
            self.assertEqual(client.post(path, json=self.body,
                headers={**headers, 'cookie': SESSION_COOKIE_NAME+'='+executor_handle}).status_code, 403)
            response = client.post(path, json=self.body, headers=headers)
            self.assertEqual(response.status_code, 200, 'Mounted report summary failed')
            body = response.json()
            self.assertEqual(body['operation_id'], self.body['operation_id'])
            self.assertEqual(body['mode'], 'deterministic_fallback')
            self.assertEqual(body['fallback_reason'], 'provider_not_configured')
            self.assertEqual(body['reserved_upper_bound_microusd'], 0)
            self.assertIsNone(body['actual_billed_cost'])
            self.assertIn('no-store', response.headers['cache-control'])
            self.assertEqual(client.get(path).status_code, 405)
        with self.connect() as owner:
            after = {table: owner.execute('SELECT count(*) AS n FROM '+table).fetchone()['n'] for table in before}
        self.assertEqual(before, after)


def run(suite, expected, label):
    if suite.countTestCases() != expected:
        raise SystemExit('FAIL: '+label+' case count changed')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.skipped or result.testsRun != expected or not result.wasSuccessful():
        raise SystemExit('FAIL: '+label)
    print(f'PASS: {label}, {expected} actual PostgreSQL tests, zero skips')


run(unittest.defaultTestLoader.loadTestsFromTestCase(AIReportPostgresTests), 5,
    'Grounded summary author PostgreSQL')
ApplicationRoleTests.setUpClass()
try:
    run(unittest.defaultTestLoader.loadTestsFromTestCase(RestrictedAIReports), 5,
        'Grounded summary restricted API LOGIN')
    run(unittest.TestSuite([MountedAIReports('test_actual_main_keyless_summary_and_access_checks')]), 1,
        'Actual app.main grounded summary')
finally:
    ApplicationRoleTests.doClassCleanups()
    if ApplicationRoleTests.tearDown_exceptions:
        raise SystemExit('FAIL: report-summary role cleanup not confirmed')
