"""Opt-in actual PostgreSQL gate. Provider responses are still RECORDED fixtures.

NOT_RUN until A5 supplies an authorized isolated disposable DSN and sets
DALA_AI_SUMMARY_POSTGRES_ACCEPTANCE=1. No mock substitutes for this gate.
Each test creates/drops a unique random schema using the existing C111 fixture.
"""
from datetime import timedelta
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.ai.demo_policy import build_interactive_demo_policy
from app.ai.model_adapter import DemoProjectContext, TransportResponse
from app.ai.model_budget import SqliteBudgetLedger
from app.ai.openai_runtime import openai_demo_budget, openai_demo_settings
from app.core.auth_boundary import SESSION_COOKIE_NAME
from app.reports.ai_summary import ReportModelAdapter, SummaryService, SELECTION_VERSION
from app.reports.ai_summary_routes import create_ai_summary_router
from integration import test_c_runtime_reports_postgres as c111


class AIReportPostgresTests(unittest.TestCase):
    connect = c111.RuntimeReportsPostgresTests.connect
    drop_schema = c111.RuntimeReportsPostgresTests.drop_schema
    execute = c111.RuntimeReportsPostgresTests.execute
    add_closed_order = c111.RuntimeReportsPostgresTests.add_closed_order

    @classmethod
    def setUpClass(cls):
        if os.environ.get('DALA_AI_SUMMARY_POSTGRES_ACCEPTANCE') != '1':
            raise unittest.SkipTest('NOT_RUN: AI reports PostgreSQL opt-in absent')
        cls.dsn = os.environ.get('DALA_TEST_DATABASE_URL')
        if not cls.dsn:
            raise unittest.SkipTest('NOT_RUN: authorized isolated PostgreSQL DSN absent')
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row
        cls.pg, cls.sql, cls.dict_row = psycopg, sql, staticmethod(dict_row)

    def setUp(self):
        c111.RuntimeReportsPostgresTests.setUp(self)
        with self.connect() as db:
            self.csrf = db.execute('SELECT csrf_token FROM auth_sessions').fetchone()['csrf_token']
        self.body = {'operation_id': str(uuid4()), **self.query, 'report_kind': 'shift'}
        self.mount()

    def mount(self, adapter=None):
        app = FastAPI()
        app.include_router(create_ai_summary_router(SummaryService(self.service, adapter=adapter)))
        self.client = TestClient(app)

    def post(self, *, body=None, csrf=None):
        return self.client.post('/api/v1/reports/ai-summary', json=body or self.body,
            headers={'cookie': SESSION_COOKIE_NAME+'='+self.handle, 'origin': 'https://reports.test',
                     'x-csrf-token': self.csrf if csrf is None else csrf})

    def recorded_adapter(self, effect=None):
        tmp = TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.ledger = SqliteBudgetLedger(Path(tmp.name)/'shared.sqlite3', openai_demo_budget())
        owner = self
        class Recorded:
            calls = 0
            async def post_json(self, **kwargs):
                self.calls += 1
                # No transaction may retain locks on this test's scoped tables.
                with owner.connect() as db:
                    locks = db.execute('''SELECT count(*) AS n FROM pg_locks l
                        JOIN pg_class c ON c.oid=l.relation JOIN pg_namespace n ON n.oid=c.relnamespace
                        WHERE n.nspname=%s AND l.pid<>pg_backend_pid() AND l.granted''', (owner.schema,)).fetchone()['n']
                owner.assertEqual(locks, 0, 'Report/provider call retained a PostgreSQL lock')
                if effect is not None:
                    effect()
                selected = {'schema_version': SELECTION_VERSION,
                            'highlights': ['m_closed_orders'], 'recommendations': []}
                return TransportResponse(200, json.dumps({'model': openai_demo_settings().model_version,
                    'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant',
                        'content': json.dumps(selected)}}]}).encode())
        self.transport = Recorded()
        project = DemoProjectContext('dalaai', 'reports-test')
        policy = build_interactive_demo_policy(project_id=project.project_id, instance_id=project.instance_id,
            expires_at=self.real.now()+timedelta(hours=1), include_grounded_reports=True)
        return ReportModelAdapter.from_operator_policy(settings=openai_demo_settings(), transport=self.transport,
            policy=policy, ledger=self.ledger, project_context=project, runtime_mode='demo', real_clock=self.real)

    def test_scoped_keyless_facts_no_pg_mutations_and_no_get(self):
        with self.connect() as db:
            before = {table: db.execute('SELECT count(*) AS n FROM '+table).fetchone()['n']
                      for table in ('orders', 'submissions', 'reviews', 'order_events', 'auth_sessions', 'ai_jobs')}
        response = self.post()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['mode'], 'deterministic_fallback')
        self.assertEqual(body['fallback_reason'], 'provider_not_configured')
        self.assertIn(self.order, [source for item in body['highlights'] for source in item['source_ids']])
        with self.connect() as db:
            after = {table: db.execute('SELECT count(*) AS n FROM '+table).fetchone()['n'] for table in before}
        self.assertEqual(before, after)
        self.assertEqual(self.client.get('/api/v1/reports/ai-summary').status_code, 405)

    def test_actual_role_csrf_scope_denial(self):
        self.assertEqual(self.post(csrf='wrong').status_code, 403)
        self.execute("UPDATE employees SET role='executor' WHERE id=%s", (self.master,))
        self.assertEqual(self.post().status_code, 403)
        self.execute("UPDATE employees SET role='master' WHERE id=%s", (self.master,))
        self.execute('DELETE FROM employee_sections WHERE employee_id=%s', (self.master,))
        self.assertEqual(self.post().status_code, 403)

    def test_recorded_request_is_outside_pg_transactions_and_retries_cannot_charge_twice(self):
        self.mount(self.recorded_adapter())
        response = self.post()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['mode'], 'recorded_fixture')
        repeated = self.post()
        self.assertEqual(repeated.json()['fallback_reason'], 'operation_already_attempted')
        self.assertEqual(self.transport.calls, 1)
        self.assertEqual(self.ledger.counters()['calls_reserved'], 1)

    def test_real_expiry_during_recorded_call_rejects_entire_response(self):
        self.mount(self.recorded_adapter(lambda: setattr(self.real, 'value', c111.NOW+timedelta(hours=2))))
        response = self.post()
        self.assertEqual(response.status_code, 401, response.text)
        self.assertNotIn('summary', response.json())
        self.assertEqual(self.transport.calls, 1)

    def test_revoked_membership_during_recorded_call_rejects_entire_response(self):
        def revoke():
            self.execute('DELETE FROM employee_sections WHERE employee_id=%s', (self.master,))
        self.mount(self.recorded_adapter(revoke))
        response = self.post()
        self.assertEqual(response.status_code, 403, response.text)
        self.assertNotIn('summary', response.json())
