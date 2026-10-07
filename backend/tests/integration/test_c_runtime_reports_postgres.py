"""Actual PostgreSQL acceptance, intentionally opt-in and NEVER a mock substitute.

A5 must authorize an isolated disposable DB before setting BOTH
DALA_C_RUNTIME_POSTGRES_ACCEPTANCE=1 and DALA_TEST_DATABASE_URL. Tests create and
drop only a new random schema. No credentials/PIN files or provider calls.
No owner-role fixture can prove deployment least-privilege grants.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from threading import Event
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4, uuid5

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analytics.c3_repository import CaptureLimits, RuntimeReportRepository, RuntimeReportService
from app.core.auth_boundary import SESSION_COOKIE_NAME
from app.reports.c4_routes import create_c_runtime_router
from app.sessions.service import SessionService

NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.value = NOW
    def now(self):
        return self.value


class RuntimeReportsPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get('DALA_C_RUNTIME_POSTGRES_ACCEPTANCE') != '1':
            raise unittest.SkipTest('NOT_RUN: explicit isolated PostgreSQL acceptance opt-in absent')
        cls.dsn = os.environ.get('DALA_TEST_DATABASE_URL')
        if not cls.dsn:
            raise unittest.SkipTest('NOT_RUN: isolated PostgreSQL DSN absent')
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row
        cls.pg, cls.sql, cls.dict_row = psycopg, sql, staticmethod(dict_row)

    def connect(self):
        return self.pg.connect(self.dsn, autocommit=True, connect_timeout=3,
            options=f'-c search_path={self.schema} -c statement_timeout=10000 -c lock_timeout=3000',
            row_factory=self.dict_row)

    def setUp(self):
        self.schema = 'c_runtime_' + uuid4().hex
        self.section, self.foreign_section, self.equipment, self.master, self.executor, self.code = [str(uuid4()) for _ in range(6)]
        # Random handles exist only in this disposable test schema; no login is enabled.
        self.handle = uuid4().hex
        self.real, self.domain = Clock(), Clock()
        with self.pg.connect(self.dsn, autocommit=True) as db:
            db.execute(self.sql.SQL('CREATE SCHEMA {}').format(self.sql.Identifier(self.schema)))
        self.addCleanup(self.drop_schema)
        with self.connect() as db:
            migrations = Path(__file__).resolve().parents[2] / 'db/migrations'
            for migration in sorted(migrations.glob('*.sql')):
                db.execute(migration.read_text())
            db.execute('INSERT INTO sections VALUES (%s,\'S\',\'Synthetic\'),(%s,\'F\',\'Foreign synthetic\')',
                       (self.section, self.foreign_section))
            for identifier, role in ((self.master, 'master'), (self.executor, 'executor')):
                db.execute('''INSERT INTO employees(id,employee_code,role,pin_hash)
                    VALUES (%s,%s,%s,'disabled-not-a-credential')''', (identifier, identifier, role))
                db.execute('INSERT INTO employee_sections VALUES (%s,%s)', (identifier, self.section))
            db.execute('INSERT INTO equipment VALUES (%s,%s,\'EQ\',\'Synthetic\')', (self.equipment,self.section))
            db.execute('INSERT INTO work_codes VALUES (%s,\'W\',\'Synthetic work\')', (self.code,))
            db.execute('''INSERT INTO auth_sessions(id,employee_id,token_hash,csrf_token,created_at,expires_at)
                VALUES (%s,%s,%s,%s,%s,%s)''', (str(uuid4()), self.master,
                sha256(self.handle.encode()).hexdigest(), uuid4().hex, NOW-timedelta(days=1), NOW+timedelta(hours=1)))
        self.order, self.submission = self.add_closed_order()
        self.sessions = SessionService(self.connect, allowed_origin='https://reports.test', real_clock=self.real)
        self.service = RuntimeReportService(self.sessions, domain_clock=self.domain, synthetic=True)
        app = FastAPI()
        app.include_router(create_c_runtime_router(self.service))
        self.client = TestClient(app)
        self.query = {'start':(NOW-timedelta(days=1)).isoformat(), 'end':NOW.isoformat()}

    def drop_schema(self):
        with self.pg.connect(self.dsn, autocommit=True) as db:
            db.execute(self.sql.SQL('DROP SCHEMA {} CASCADE').format(self.sql.Identifier(self.schema)))

    def execute(self, statement, params=()):
        with self.connect() as db:
            db.execute(statement, params)

    def add_closed_order(self):
        order, submission = str(uuid4()), str(uuid4())
        with self.connect() as db:
            with db.transaction():
                db.execute('''INSERT INTO orders(id,version,assignment_revision,scheduling_revision,status,type,
                    description,section_id,equipment_id,executor_id,created_by,issued_at,due_at,
                    norm_minutes,priority,updated_at) VALUES (%s,5,1,1,'closed','planned','Synthetic',
                    %s,%s,%s,%s,%s,%s,60,'normal',%s)''', (order,self.section,self.equipment,self.executor,
                    self.master,NOW-timedelta(days=40),NOW-timedelta(days=2),NOW-timedelta(hours=1)))
                db.execute('''INSERT INTO submissions(id,order_id,assignment_revision,attempt_number,submitted_by,
                    submitted_at,done_late,work_description,work_code_id,completeness,missing_evidence,after_photo_ids)
                    VALUES (%s,%s,1,1,%s,%s,false,'Synthetic complete',%s,'complete','[]','{}')''',
                    (submission,order,self.executor,NOW-timedelta(days=2),self.code))
                db.execute('''INSERT INTO reviews(id,submission_id,reviewer_id,decision,reason,final_score,created_at)
                    VALUES (%s,%s,%s,'close','Synthetic human decision',NULL,%s)''',
                    (str(uuid4()),submission,self.master,NOW-timedelta(hours=1)))
                db.execute('UPDATE orders SET current_submission_id=%s WHERE id=%s', (submission,order))
        return order, submission

    def get(self, path='/reports/shift', query=None):
        return self.client.get('/api/v1'+path, params=self.query if query is None else query,
            headers={'cookie':SESSION_COOKIE_NAME+'='+self.handle})

    def test_actual_snapshot_and_complete_history_json_html_read_only_effect(self):
        with self.connect() as db:
            before = {table:db.execute('SELECT count(*) AS n FROM '+table).fetchone()['n']
                      for table in ('orders','submissions','reviews','order_events','auth_sessions','delivery_jobs')}
        shift = self.get()
        self.assertEqual(shift.status_code, 200, shift.text)
        metrics = {row['name']:row for row in shift.json()['metrics']}
        self.assertEqual(metrics['issued_orders']['value'], '0')
        self.assertEqual(metrics['closed_orders']['value'], '1')
        self.assertIsNone(metrics['human_score']['value'])
        self.assertTrue(shift.json()['provenance']['synthetic'])
        self.assertEqual(self.get('/reports/orders/'+self.order).status_code,200)
        self.assertIn('СИНТЕТИЧЕСКИЕ ДАННЫЕ', self.get(query={**self.query,'format':'html'}).text)
        with self.connect() as db:
            after = {table:db.execute('SELECT count(*) AS n FROM '+table).fetchone()['n'] for table in before}
        self.assertEqual(before,after)

    def test_canonical_historical_manifest_without_photo_rows_reports_unavailable(self):
        # Independent loader-shaped data, real PostgreSQL transport. No real
        # loader/import or fixture helper can substitute for these DB reads.
        namespace = UUID('716a1c94-5fd0-5c11-a9e9-13d12b739639')
        cid = lambda kind,n: str(uuid5(namespace,f'1.0.0/20261008/{kind}/{n}'))
        section,equipment,brigade = cid('section',1),cid('equipment',1),cid('brigade',1)
        master,executor = cid('master',1),cid('executor',1)
        order,submission,photo = cid('order',1),cid('submission','1/1'),cid('photo','1/1')
        issued,submitted,reviewed = NOW-timedelta(days=40),NOW-timedelta(days=2),NOW-timedelta(hours=1)
        with self.connect() as db:
            with db.transaction():
                db.execute("INSERT INTO sections VALUES (%s,'H-S','Synthetic history')",(section,))
                db.execute("INSERT INTO brigades VALUES (%s,%s,'H-B','Synthetic history')",(brigade,section))
                db.execute("INSERT INTO equipment VALUES (%s,%s,'H-E','Synthetic history')",(equipment,section))
                for identifier,role,code in ((master,'master','SYN-M-01'),(executor,'executor','SYN-E-01')):
                    db.execute("""INSERT INTO employees(id,employee_code,role,active,on_shift,pin_hash)
                        VALUES (%s,%s,%s,false,false,'disabled-not-a-credential')""",(identifier,code,role))
                    db.execute('INSERT INTO employee_sections VALUES (%s,%s)',(identifier,section))
                # A separate authenticated test viewer, never the disabled actors.
                db.execute('INSERT INTO employee_sections VALUES (%s,%s)',(self.master,section))
                number = db.execute("""INSERT INTO orders(id,version,assignment_revision,scheduling_revision,
                    status,type,description,section_id,equipment_id,executor_id,brigade_id,created_by,
                    issued_at,due_at,norm_minutes,priority,updated_at) VALUES (%s,5,1,1,'closed','unplanned',
                    'Synthetic history',%s,%s,%s,%s,%s,%s,%s,60,'normal',%s) RETURNING number""",
                    (order,section,equipment,executor,brigade,master,issued,submitted,reviewed)).fetchone()['number']
                db.execute("""INSERT INTO submissions(id,order_id,assignment_revision,attempt_number,submitted_by,
                    submitted_at,done_late,work_description,work_code_id,completeness,missing_evidence,after_photo_ids)
                    VALUES (%s,%s,1,1,%s,%s,false,'Synthetic history',%s,'complete','[]',%s::uuid[])""",
                    (submission,order,executor,submitted,self.code,[photo]))
                db.execute("""INSERT INTO reviews(id,submission_id,reviewer_id,decision,reason,final_score,created_at)
                    VALUES (%s,%s,%s,'close','Synthetic narrative',NULL,%s)""",
                    (cid('review','1/1'),submission,master,reviewed))
                db.execute('UPDATE orders SET current_submission_id=%s WHERE id=%s',(submission,order))
                descriptor = dict(id=photo,order_id=order,submission_id=submission,assignment_revision=1,
                    owner_id=executor,purpose='after',uploaded_at=(submitted-timedelta(minutes=1)).isoformat(),
                    evidence_kind='synthetic_metadata_placeholder',artifact_available=False)
                marker = dict(synthetic=True,loader_version='1.1.0',
                    source_commit='8af3897f03aa2f41f0af07ec74ec2c807a4a535a',
                    history_sha256='7d888cdd5bb6a9c01ca7c543fae9e393335d07210dab811aa754f12331d1d2e1',
                    identity_mapping_sha256='56ec343e53e4f44208dfd5d5910e235b4626cda7c89f6b642e195c78945a5a64',
                    source_order_number='1',runtime_order_number=number,
                    watermark='Синтетические данные — не история предприятия',
                    photo_policy='metadata_only_no_image_bytes_no_file_valid_claim',
                    historical_completeness_not_verified_evidence=True,historical_actor_state='disabled_no_login',
                    source_photo_placeholders=[descriptor])
                db.execute("""INSERT INTO order_events(id,order_id,sequence,order_version,assignment_revision,
                    scheduling_revision,kind,details,actor_id,operation_id,from_status,to_status,occurred_at,recorded_at)
                    VALUES (%s,%s,1,1,1,1,'order.created',%s::jsonb,%s,%s,NULL,'issued',%s,%s)""",
                    (cid('event','1/1'),order,json.dumps({'synthetic_import':marker}),master,cid('operation','1/1'),issued,issued))
        response = self.get('/reports/orders/'+order)
        self.assertEqual(response.status_code,200,response.text)
        evidence = response.json()['provenance']['historical_evidence']
        self.assertEqual(evidence['historical_order_count'],1)
        self.assertEqual(evidence['missing_after_photo_row_count'],1)
        self.assertFalse(evidence['physical_evidence_verified'])
        html = self.get('/reports/orders/'+order,{**self.query,'format':'html'})
        self.assertEqual(html.status_code,200,html.text)
        self.assertIn('отсутствующих записей фото 1',html.text)

    def test_current_membership_role_active_and_revocation_are_reloaded(self):
        self.assertEqual(self.get().status_code,200)
        self.execute('DELETE FROM employee_sections WHERE employee_id=%s',(self.master,))
        self.assertEqual(self.get().status_code,403)
        self.execute('INSERT INTO employee_sections VALUES (%s,%s)',(self.master,self.foreign_section))
        self.assertEqual(self.get('/reports/orders/'+self.order).status_code,404)
        self.execute('INSERT INTO employee_sections VALUES (%s,%s)',(self.master,self.section))
        for role in ('manager','executor','admin'):
            self.execute('UPDATE employees SET role=%s WHERE id=%s',(role,self.master))
            self.assertEqual(self.get().status_code,403)
        self.execute("UPDATE employees SET role='master',active=false WHERE id=%s",(self.master,))
        self.assertEqual(self.get().status_code,401)
        self.execute('UPDATE employees SET active=true WHERE id=%s',(self.master,))
        self.execute('UPDATE auth_sessions SET revoked_at=%s WHERE employee_id=%s',(NOW,self.master))
        self.assertEqual(self.get().status_code,401)

    def test_actual_row_and_text_bounds_do_not_return_partial_totals(self):
        self.add_closed_order()
        self.service.limits = CaptureLimits(max_orders=1)
        response = self.get()
        self.assertEqual(response.status_code,422)
        self.assertNotIn('metrics',response.json())
        self.service.limits = CaptureLimits()
        self.execute('UPDATE orders SET comment=%s WHERE id=%s',('x'*200000,self.order))
        self.assertEqual(self.get('/reports/orders/'+self.order).status_code,422)

    def test_concurrent_child_commit_is_not_mixed_into_snapshot(self):
        original = RuntimeReportRepository._read
        inserted = False
        def interleave(repo, statement, params, **kwargs):
            nonlocal inserted
            rows = original(repo, statement, params, **kwargs)
            if 'FROM orders ' in statement and not inserted:
                inserted = True
                self.execute('''INSERT INTO ai_assessments(id,submission_id,assignment_revision,mode,schema_version,
                    duration_ms,recommendation,score,reasons,evidence_ids,stale,created_at)
                    VALUES (%s,%s,1,'manual','1',0,'needs_master_review',NULL,'[]','[]',false,%s)''',
                    (str(uuid4()),self.submission,NOW-timedelta(minutes=1)))
            return rows
        with patch.object(RuntimeReportRepository,'_read',new=interleave):
            first = self.get('/reports/orders/'+self.order)
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(first.json()['order']['attempts'][0]['assessments'],[])
        second = self.get('/reports/orders/'+self.order)
        self.assertEqual(len(second.json()['order']['attempts'][0]['assessments']),1)

    def test_order_lock_wait_rechecks_expiry(self):
        attempted = Event()
        original = RuntimeReportRepository._read
        def announce(repo, statement, params, **kwargs):
            if 'FROM orders ' in statement:
                attempted.set()
            return original(repo, statement, params, **kwargs)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.connect() as blocker:
                with blocker.transaction():
                    blocker.execute('SELECT id FROM orders WHERE id=%s FOR UPDATE',(self.order,))
                    with patch.object(RuntimeReportRepository,'_read',new=announce):
                        pending = pool.submit(self.get)
                        self.assertTrue(attempted.wait(3))
                        self.real.value = NOW+timedelta(hours=2)
                response = pending.result(timeout=10)
        self.assertEqual(response.status_code,401,response.text)

    def test_concurrent_order_change_after_auth_snapshot_returns_retryable_503(self):
        entered, release = Event(), Event()
        original = RuntimeReportRepository.capture
        def pause(repo,*args,**kwargs):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('Test barrier timed out')
            return original(repo,*args,**kwargs)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with patch.object(RuntimeReportRepository,'capture',new=pause):
                pending = pool.submit(self.get)
                try:
                    self.assertTrue(entered.wait(3))
                    self.execute('UPDATE orders SET comment=%s WHERE id=%s',('New committed value',self.order))
                finally:
                    release.set()
                response = pending.result(timeout=10)
        self.assertEqual(response.status_code,503,response.text)
        self.assertTrue(response.json()['retryable'])
        self.assertNotIn('New committed value',response.text)

    def test_revocation_waits_for_report_auth_locks_then_blocks_next_read(self):
        rendering, release = Event(), Event()
        from app.reports.c4_routes import shift_report_data
        def pause(facts):
            rendering.set()
            if not release.wait(5):
                raise RuntimeError('Test barrier timed out')
            return shift_report_data(facts)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with patch('app.reports.c4_routes.shift_report_data',side_effect=pause):
                report = pool.submit(self.get)
                try:
                    self.assertTrue(rendering.wait(3))
                    # Prove an actual PostgreSQL lock conflict, not scheduling delay.
                    with self.connect() as db:
                        with self.assertRaises(self.pg.errors.LockNotAvailable):
                            with db.transaction():
                                db.execute("SET LOCAL lock_timeout = '100ms'")
                                db.execute('UPDATE auth_sessions SET revoked_at=%s WHERE employee_id=%s',
                                           (NOW,self.master))
                finally:
                    release.set()
                response = report.result(timeout=10)
        self.assertEqual(response.status_code,200,response.text)
        self.execute('UPDATE auth_sessions SET revoked_at=%s WHERE employee_id=%s',(NOW,self.master))
        self.assertEqual(self.get().status_code,401)


if __name__ == '__main__':
    unittest.main()
