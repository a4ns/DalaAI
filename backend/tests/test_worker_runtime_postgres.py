"""REAL three-login bootstrap -> mounted HTTP -> rules worker -> persisted verdict.

No fake database, auth session, assessment, provider response or delivery adapter.
Use ops/run_worker_runtime_tests.py for the mandatory no-skip gate. Each case owns
one random schema and a private local photo directory, and cleans only those.
HTTP is in-process ASGI TestClient; this is not hosted HTTPS/mobile/phone evidence.
"""
import argparse
import asyncio
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
import tempfile
import sys
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = ('DALA_TEST_DATABASE_URL', 'DALA_ACCEPTANCE_RUNTIME_DATABASE_URL',
            'DALA_ACCEPTANCE_WORKER_DATABASE_URL', 'DALA_DEMO_MASTER_PIN', 'DALA_DEMO_EXECUTOR_PIN')
ORIGIN = 'https://worker-runtime.test'


class WorkerRuntimePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get('DALA_ACCEPTANCE_DISPOSABLE') != '1' or any(not os.environ.get(k) for k in REQUIRED):
            raise unittest.SkipTest('NOT_RUN: explicit disposable three-login PostgreSQL setup required')
        from psycopg.conninfo import conninfo_to_dict
        if any(os.environ.get(k) for k in ('PGSERVICE', 'PGSERVICEFILE', 'PGHOSTADDR')):
            raise ValueError('Ambient PostgreSQL service indirection is refused')
        for name in REQUIRED[:3]:
            parts = conninfo_to_dict(os.environ[name]); host = parts.get('host', '')
            if (not parts.get('dbname') or not host or ',' in host or parts.get('service') or parts.get('servicefile')
                    or parts.get('hostaddr') not in (None, '', '127.0.0.1', '::1')
                    or host not in ('localhost', '127.0.0.1', '::1') and not host.startswith('/')):
                raise ValueError('Only an explicit local disposable PostgreSQL DSN is allowed')
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row
        cls.pg, cls.sql, cls.dict_row = psycopg, sql, staticmethod(dict_row)
        cls.inputs = {k: os.environ[k] for k in REQUIRED}
        with cls.pg.connect(cls.inputs['DALA_TEST_DATABASE_URL'], autocommit=True) as db:
            cls.database = db.execute('SELECT current_database()').fetchone()[0]

    def setUp(self):
        sys.path.insert(0, str(ROOT/'ops/provision'))
        from enable_worker_capabilities import apply_capabilities
        self.schema = 'worker_flow_' + uuid4().hex
        # Register before bootstrap so even an initialization failure is confined
        # to and cleaned from this test's own newly chosen namespace.
        self.addCleanup(self.drop_schema)
        self.directory = tempfile.TemporaryDirectory(prefix='dala-worker-private-')
        self.addCleanup(self.directory.cleanup)
        self.photo_root = Path(self.directory.name)
        self.environment = dict(self.inputs,
            DALA_ACCEPTANCE_DISPOSABLE='1', DALA_API_MODE='demo',
            DALA_DEMO_SEED_ALLOWED='1', DALA_DEMO_WORKER_CAPABILITY_ALLOWED='1',
            DALA_DEMO_OWNER_DATABASE_URL=self.inputs['DALA_TEST_DATABASE_URL'],
            DALA_DEMO_RUNTIME_DATABASE_URL=self.inputs['DALA_ACCEPTANCE_RUNTIME_DATABASE_URL'],
            DALA_DEMO_WORKER_DATABASE_URL=self.inputs['DALA_ACCEPTANCE_WORKER_DATABASE_URL'],
            DATABASE_URL=self.inputs['DALA_ACCEPTANCE_RUNTIME_DATABASE_URL'],
            DALA_DATABASE_SCHEMA=self.schema, DALA_ALLOWED_ORIGIN=ORIGIN,
            DALA_NOTIFICATION_CAPABILITY='true', DALA_PUSH_CAPABILITY='true',
            DALA_DELIVERY_CHANNEL='web_push', DALA_WEB_PUSH_ENABLED='false',
            DALA_PHOTO_STORAGE_ROOT=str(self.photo_root),
            DALA_WORKER_ENABLED='true', DALA_WORKER_AI_ENABLED='true',
            DALA_WORKER_NOTIFY_ENABLED='true', DALA_WORKER_CHANNEL='web_push',
            DALA_WORKER_DATABASE_URL=self.inputs['DALA_ACCEPTANCE_WORKER_DATABASE_URL'])
        # Clear ambient OpenAI/VAPID/Telegram secrets rather than force-off a
        # configured model: this case proves the genuine absent-key rules path.
        env = patch.dict(os.environ, self.environment, clear=True)
        env.start()
        self.addCleanup(env.stop)
        args = argparse.Namespace(backend=ROOT/'backend', schema=self.schema,
                                  expected_database=self.database, bootstrap=True)
        result = apply_capabilities(args, self.environment)
        self.assertEqual(result['status'], 'WORKER_CAPABILITIES_READY')
        self.assertEqual(result['migration_count'], 7)
        self.assertEqual(result['roles_created'], 0)
        # Prevent a module-global demo app from materializing outside its test
        # lifespan. The actual tested factory below uses real demo settings.
        with patch.dict(os.environ, {'DALA_API_MODE': 'health'}):
            from app.main import create_app
        from app.runtime import RuntimeSettings
        self.api_settings = RuntimeSettings.from_env()
        self.assertTrue(self.api_settings.notification_enabled)
        self.assertTrue(self.api_settings.push_enabled)
        self.assertEqual(self.api_settings.delivery_channel, 'web_push')
        self.app = create_app(settings=self.api_settings)  # Actual API DSN factory.

    def connect(self, *, worker=False):
        name = 'DALA_ACCEPTANCE_WORKER_DATABASE_URL' if worker else 'DALA_TEST_DATABASE_URL'
        return self.pg.connect(self.inputs[name], autocommit=True, connect_timeout=3,
            options=f'-c search_path={self.schema} -c statement_timeout=10000 -c lock_timeout=3000',
            row_factory=self.dict_row)

    def query(self, statement, params=()):
        with self.connect() as db:
            return db.execute(statement, params).fetchall()

    def drop_schema(self):
        with self.pg.connect(self.inputs['DALA_TEST_DATABASE_URL'], autocommit=True) as db:
            db.execute(self.sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(self.sql.Identifier(self.schema)))

    def _login(self, client, role):
        response = client.post('/api/v1/auth/login', headers={'Origin': ORIGIN},
            json={'employee_code': 'DALA-DEMO-' + role.upper(),
                  'pin': self.inputs['DALA_DEMO_' + role.upper() + '_PIN']})
        # Never include a login body, token, cookie, CSRF or PIN in assertion text.
        self.assertEqual(response.status_code, 200, 'Real demo login failed')
        body = response.json()
        self.assertEqual(body['principal']['role'], role)
        return body['csrf_token']

    def _post(self, client, csrf, path, body, *, expected=200):
        response = client.post(path, headers={'Origin': ORIGIN, 'X-CSRF-Token': csrf}, json=body)
        code = response.json().get('code') if response.headers.get('content-type', '').startswith('application/json') else None
        self.assertEqual(response.status_code, expected, f'Order command failed with {code}')
        return response.json()

    def _command(self, client, csrf, order, action, payload):
        return self._post(client, csrf, f"/api/v1/orders/{order['id']}/commands",
            {'operation_id': str(uuid4()), 'expected_version': order['version'], 'action': action, 'payload': payload})

    def _submit(self, master, executor, master_csrf, executor_csrf, *, with_photo):
        from provision_synthetic_demo import IDENTITY
        created = self._post(master, master_csrf, '/api/v1/orders', {
            'operation_id': str(uuid4()), 'expected_version': 0, 'action': 'create', 'payload': {
                'type': 'unplanned', 'description': 'Проверить синтетический тестовый ремень',
                'section_id': IDENTITY['section'], 'equipment_id': IDENTITY['equipment'],
                'assignment': {'executor_id': IDENTITY['executor'], 'brigade_id': None},
                'due_at': (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
                'norm_minutes': 30, 'priority': 'normal', 'comment': '', 'before_photo_ids': []}}, expected=201)
        order = created['order']
        # Exercises the real 012-dependent priority hook under the restricted API
        # login. No provider has been called and the original notice is unsent.
        order = self._command(master, master_csrf, order, 'change_priority',
            {'priority': 'high', 'reason': 'Синтетическая проверка изменения приоритета'})['order']
        for action in ('accept', 'start'):
            order = self._command(executor, executor_csrf, order, action, {})['order']
        photo_id = None
        if with_photo:
            from PIL import Image
            raw = BytesIO()
            with Image.new('RGB', (64, 64), (40, 120, 180)) as image:
                image.save(raw, format='PNG')
            staged = executor.post('/api/v1/photos/stage',
                headers={'Origin': ORIGIN, 'X-CSRF-Token': executor_csrf},
                data={'operation_id': str(uuid4()), 'expected_version': '0',
                      'section_id': IDENTITY['section'], 'purpose': 'after',
                      'order_id': order['id'], 'assignment_revision': str(order['assignment_revision'])},
                files={'file': ('synthetic-worker.png', raw.getvalue(), 'image/png')})
            self.assertEqual(staged.status_code, 201, 'Actual photo upload failed')
            photo_id = staged.json()['id']
            self.assertEqual(executor.get('/api/v1/photos/' + photo_id).status_code, 200)
        submitted = self._command(executor, executor_csrf, order, 'submit', {
            'work_description': 'Синтетический тестовый ремень проверен', 'work_code_id': IDENTITY['work_code'],
            'materials': [], 'after_photo_ids': [photo_id] if photo_id else [], 'comment': ''})
        self.assertEqual(submitted['order']['status'], 'ai_review')
        self.assertEqual(self.query('SELECT state,attempts FROM ai_jobs'), [{'state': 'pending', 'attempts': 0}])
        self.assertEqual(self.query('SELECT id FROM ai_assessments'), [])
        return submitted['order'], submitted['submission_id'], photo_id

    def _worker_tick(self):
        from app.jobs.worker import AssessmentWorker
        from app.worker_runtime import WorkerSettings, build_runtime
        worker = build_runtime(WorkerSettings.from_env(), environment=self.environment)
        self.assertIs(type(worker.assessment), AssessmentWorker)
        self.assertEqual(worker.ai_mode, 'rules_fallback')
        self.assertIsNone(worker.dispatcher)
        self.assertIsNone(worker.reconciler)
        self.assertEqual(worker.notification_state, 'paused_web_push_disabled')
        with worker.assessment.connect() as db:
            row = db.execute('SELECT current_user AS role, session_user AS login').fetchone()
        self.assertEqual(row['role'], row['login'])
        with self.connect() as owner:
            owner_role = owner.execute('SELECT current_user AS role').fetchone()['role']
        self.assertNotEqual(row['role'], owner_role)
        return asyncio.run(worker.tick(stop=threading.Event()))

    def _assert_persisted(self, master, order, submission_id, *, recommendation):
        delivery_before = self.query('SELECT id,state,attempts,lease_token,provider_receipt,sent_at FROM delivery_jobs ORDER BY id')
        self.assertTrue(delivery_before)
        self.assertTrue(all(row['attempts'] == 0 for row in delivery_before))
        tick = self._worker_tick()
        self.assertEqual(tick['ai_states'], {'done': 1})
        self.assertEqual(tick['dispatch_states'], {})
        self.assertEqual(tick['reconciled_orders'], 0)
        assessment = self.query('SELECT * FROM ai_assessments WHERE submission_id=%s', (submission_id,))
        self.assertEqual(len(assessment), 1)
        result = assessment[0]
        self.assertEqual(result['mode'], 'rules_fallback')
        self.assertEqual(result['recommendation'], recommendation)
        self.assertEqual(result['fallback_reason'], 'provider_not_configured')
        self.assertFalse(result['stale'])
        self.assertIsNone(result['model'])
        self.assertIsNone(result['model_version'])
        self.assertIsNone(result['score'])
        self.assertEqual(self.query('SELECT status,version FROM orders WHERE id=%s', (order['id'],)),
                         [{'status': 'ai_review', 'version': order['version'] + 1}])
        self.assertEqual(self.query('SELECT id FROM reviews'), [])  # No automatic human decision.
        self.assertEqual(self.query('SELECT state,attempts,lease_token,lease_until FROM ai_jobs'),
                         [{'state': 'done', 'attempts': 1, 'lease_token': None, 'lease_until': None}])
        event = self.query("SELECT details,order_version FROM order_events WHERE kind='order.assessment_recorded'")
        self.assertEqual(event, [{'details': {'assessment_id': str(result['id']), 'mode': 'rules_fallback'},
                                 'order_version': order['version'] + 1}])
        view = master.get(f"/api/v1/orders/{order['id']}/submissions/{submission_id}")
        self.assertEqual(view.status_code, 200)
        self.assertEqual(view.json()['assessments'][0]['id'], str(result['id']))
        # Restart assembly and tick again: no duplicate assessment/event, no send.
        self.assertEqual(self._worker_tick()['ai_states'], {})
        self.assertEqual(len(self.query('SELECT id FROM ai_assessments')), 1)
        self.assertEqual(len(self.query("SELECT id FROM order_events WHERE kind='order.assessment_recorded'")), 1)
        self.assertEqual(self.query('SELECT id,state,attempts,lease_token,provider_receipt,sent_at FROM delivery_jobs ORDER BY id'), delivery_before)
        self.assertEqual(self.query('SELECT * FROM delivery_dispatches'), [])
        self.assertEqual(self.query('SELECT * FROM delivery_dispatch_results'), [])
        return result

    def _clients(self, stack):
        from fastapi.testclient import TestClient
        master = stack.enter_context(TestClient(self.app, base_url=ORIGIN, client=('127.0.0.1', 43101)))
        # One actual application lifespan; independent cookie jars for both users.
        executor = TestClient(self.app, base_url=ORIGIN, client=('127.0.0.1', 43102))
        stack.callback(executor.close)
        self.assertEqual(master.get('/readyz').status_code, 200)
        return master, executor, self._login(master, 'master'), self._login(executor, 'executor')

    def test_uploaded_private_evidence_rules_verdict_and_human_close(self):
        with ExitStack() as stack:
            master, executor, mcsrf, ecsrf = self._clients(stack)
            order, submission, photo = self._submit(master, executor, mcsrf, ecsrf, with_photo=True)
            stored = self.query('SELECT file_valid,storage_key,sha256 FROM photos WHERE id=%s', (photo,))[0]
            self.assertTrue(stored['file_valid'])
            self.assertEqual(sha256((self.photo_root/stored['storage_key']).read_bytes()).hexdigest(), stored['sha256'])
            result = self._assert_persisted(master, order, submission, recommendation='needs_master_review')
            self.assertIn(photo, result['evidence_ids'])
            self.assertIn('неизвестно 0', result['reasons'][0])  # Would fail if physical verifier were omitted.
            current = dict(order, version=order['version'] + 1)
            closed = self._command(master, mcsrf, current, 'review', {'submission_id': submission,
                'decision': 'close', 'reason': 'Синтетическая проверка мастером завершена', 'final_score': None})
            self.assertEqual(closed['order']['status'], 'closed')
            self.assertEqual(len(self.query('SELECT id FROM reviews')), 1)

    def test_incomplete_submission_persists_rework_recommendation_without_transition(self):
        with ExitStack() as stack:
            master, executor, mcsrf, ecsrf = self._clients(stack)
            order, submission, _ = self._submit(master, executor, mcsrf, ecsrf, with_photo=False)
            self._assert_persisted(master, order, submission, recommendation='rework_recommended')
            body = {'operation_id': str(uuid4()), 'expected_version': order['version'] + 1, 'action': 'review',
                'payload': {'submission_id': submission, 'decision': 'close', 'reason': 'Проверка блокировки', 'final_score': None}}
            response = self._post(master, mcsrf, f"/api/v1/orders/{order['id']}/commands", body, expected=409)
            self.assertEqual(response['code'], 'INCOMPLETE_SUBMISSION')
            self.assertEqual(self.query('SELECT id FROM reviews'), [])

    def test_current_private_bytes_override_stored_valid_flag(self):
        with ExitStack() as stack:
            master, executor, mcsrf, ecsrf = self._clients(stack)
            order, submission, photo = self._submit(master, executor, mcsrf, ecsrf, with_photo=True)
            row = self.query('SELECT storage_key,file_valid FROM photos WHERE id=%s', (photo,))[0]
            self.assertTrue(row['file_valid'])
            path = self.photo_root/row['storage_key']
            raw = path.read_bytes()
            path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])  # This test's private fixture only.
            self._assert_persisted(master, order, submission, recommendation='rework_recommended')
            self.assertTrue(self.query('SELECT file_valid FROM photos WHERE id=%s', (photo,))[0]['file_valid'])


if __name__ == '__main__':
    unittest.main()
