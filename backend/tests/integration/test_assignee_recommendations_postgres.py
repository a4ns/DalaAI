"""Actual PostgreSQL acceptance; missing explicit opt-in is NOT_RUN, not PASS.

A5 must authorize a disposable DB and set DALA_ASSIGNEE_POSTGRES_ACCEPTANCE=1
plus DALA_TEST_DATABASE_URL. Each case creates/drops its own random schema.
No shared seed/reset, real employees, credentials, provider calls, or deployment.
Owner-role fixtures do not prove deployment least-privilege grants.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import os
from pathlib import Path
from threading import Event
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.auth_boundary import SESSION_COOKIE_NAME
from app.recommendations.assignee import AssigneeRecommendationService, AssigneeRepository, RecommendationLimits
from app.recommendations.assignee_routes import create_assignee_router

NOW = datetime(2026, 10, 8, 1, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.value = NOW
    def now(self):
        return self.value


class AssigneePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get('DALA_ASSIGNEE_POSTGRES_ACCEPTANCE') != '1':
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
        self.schema = 'assignee_' + uuid4().hex
        self.section, self.second_section, self.hidden_section, self.master, self.executor, self.code = [str(uuid4()) for _ in range(6)]
        self.handle = uuid4().hex  # Only a disposable in-memory fixture, never a real login.
        self.real, self.domain = Clock(), Clock()
        with self.pg.connect(self.dsn, autocommit=True) as db:
            db.execute(self.sql.SQL('CREATE SCHEMA {}').format(self.sql.Identifier(self.schema)))
        self.addCleanup(self.drop_schema)
        self.equipment = {}
        with self.connect() as db:
            migrations = Path(__file__).resolve().parents[2] / 'db/migrations'
            for migration in sorted(migrations.glob('*.sql')):
                db.execute(migration.read_text())
            for n, section in enumerate((self.section, self.second_section, self.hidden_section)):
                db.execute('INSERT INTO sections VALUES (%s,%s,\'Synthetic section\')', (section, 'S'+str(n)))
                equipment = str(uuid4())
                self.equipment[section] = equipment
                db.execute('INSERT INTO equipment VALUES (%s,%s,%s,\'Synthetic equipment\')', (equipment, section, 'EQ'+str(n)))
            db.execute('''INSERT INTO employees(id,employee_code,role,pin_hash)
                VALUES (%s,'M-1','master','disabled-not-a-credential')''', (self.master,))
            for section in (self.section, self.second_section):
                db.execute('INSERT INTO employee_sections VALUES (%s,%s)', (self.master, section))
            db.execute('INSERT INTO work_codes VALUES (%s,\'W-1\',\'Synthetic work\')', (self.code,))
            db.execute('''INSERT INTO auth_sessions(id,employee_id,token_hash,csrf_token,created_at,expires_at)
                VALUES (%s,%s,%s,%s,%s,%s)''', (str(uuid4()), self.master, sha256(self.handle.encode()).hexdigest(),
                    uuid4().hex, NOW-timedelta(hours=1), NOW+timedelta(hours=1)))
        self.add_employee('E-1', identifier=self.executor)
        self.service = AssigneeRecommendationService(self.connect, domain_clock=self.domain,
                                                     real_clock=self.real, synthetic=True)
        app = FastAPI()
        app.include_router(create_assignee_router(self.service))
        self.client = TestClient(app)

    def drop_schema(self):
        with self.pg.connect(self.dsn, autocommit=True) as db:
            db.execute(self.sql.SQL('DROP SCHEMA {} CASCADE').format(self.sql.Identifier(self.schema)))

    def execute(self, sql, params=()):
        with self.connect() as db:
            db.execute(sql, params)

    def add_employee(self, code, *, identifier=None, active=True, on_shift=True, role='executor', section=None):
        identifier = identifier or str(uuid4())
        with self.connect() as db:
            db.execute('''INSERT INTO employees(id,employee_code,role,active,on_shift,pin_hash)
                VALUES (%s,%s,%s,%s,%s,'disabled-not-a-credential')''', (identifier, code, role, active, on_shift))
            db.execute('INSERT INTO employee_sections VALUES (%s,%s)', (identifier, section or self.section))
        return identifier

    def add_order(self, status='issued', *, executor=None, section=None, score=None, code=True,
                  closed_days=1, submission_actor=None, due_at=None):
        order, sub = str(uuid4()), str(uuid4())
        executor, section = executor or self.executor, section or self.section
        review_at = NOW-timedelta(days=closed_days)
        with self.connect() as db:
            with db.transaction():
                db.execute('''INSERT INTO orders(id,version,assignment_revision,scheduling_revision,status,type,
                    description,section_id,equipment_id,executor_id,created_by,issued_at,due_at,norm_minutes,
                    priority,updated_at) VALUES (%s,1,1,1,%s,'planned','Synthetic order',%s,%s,%s,%s,%s,%s,60,'normal',%s)''',
                    (order, status, section, self.equipment[section], executor, self.master,
                     NOW-timedelta(days=100), due_at or NOW-timedelta(hours=1), review_at))
                if status == 'closed':
                    db.execute('''INSERT INTO submissions(id,order_id,assignment_revision,attempt_number,submitted_by,
                        submitted_at,done_late,work_description,work_code_id,completeness,missing_evidence,after_photo_ids)
                        VALUES (%s,%s,1,1,%s,%s,false,'Synthetic work',%s,'complete','[]','{}')''',
                        (sub, order, submission_actor or executor, review_at-timedelta(hours=1), self.code if code else None))
                    db.execute('''INSERT INTO reviews(id,submission_id,reviewer_id,decision,reason,final_score,created_at)
                        VALUES (%s,%s,%s,'close','Synthetic master decision',%s,%s)''',
                        (str(uuid4()), sub, self.master, score, review_at))
                    db.execute('UPDATE orders SET current_submission_id=%s WHERE id=%s', (sub, order))
        return order

    def get(self, **query):
        return self.client.get('/api/v1/recommendations/assignees',
            params={'section_id': self.section, **query}, headers={'cookie': SESSION_COOKIE_NAME+'='+self.handle})

    def state(self):
        # Whole-row snapshots detect updates as well as added rows. Every table
        # belongs solely to this case's random schema; no auth secrets are logged.
        with self.connect() as db:
            tables = db.execute('SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename', (self.schema,)).fetchall()
            return {row['tablename']: db.execute(self.sql.SQL(
                'SELECT COALESCE(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),\'[]\'::jsonb) AS rows FROM {} t'
                ).format(self.sql.Identifier(row['tablename']))).fetchone()['rows'] for row in tables}

    def test_real_filter_one_eligible_employee_and_no_business_or_auth_effects(self):
        disabled = self.add_employee('HISTORICAL-LOCKED', active=False)
        self.add_order('closed', executor=disabled, score=100)
        self.add_employee('OFF-SHIFT', on_shift=False)
        self.add_employee('FOREIGN', section=self.hidden_section)
        self.add_employee('NOT-EXECUTOR', role='manager')
        before = self.state()
        response = self.get()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['eligible_count'], 1)
        self.assertEqual([item['executor_id'] for item in body['candidates']], [self.executor])
        self.assertIn('ONLY_ONE_ELIGIBLE_EXECUTOR', body['limitations'])
        self.assertEqual(body['candidates'][0]['history']['closed_count'], 0)
        self.assertNotIn(disabled, response.text)
        self.assertNotIn('HISTORICAL-LOCKED', response.text)
        self.assertEqual(before, self.state())

    def test_scope_roles_session_revocation_and_no_candidates(self):
        self.assertEqual(self.get(section_id=self.hidden_section).status_code, 403)
        for role in ('executor', 'manager', 'admin'):
            self.execute('UPDATE employees SET role=%s WHERE id=%s', (role, self.master))
            self.assertEqual(self.get().status_code, 403)
        self.execute("UPDATE employees SET role='master' WHERE id=%s", (self.master,))
        self.execute('UPDATE employees SET on_shift=false WHERE id=%s', (self.executor,))
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['candidates'], [])
        self.execute('DELETE FROM employee_sections WHERE employee_id=%s AND section_id=%s', (self.master, self.section))
        self.assertEqual(self.get().status_code, 403)
        self.execute('UPDATE auth_sessions SET revoked_at=%s WHERE employee_id=%s', (NOW, self.master))
        self.assertEqual(self.get().status_code, 401)

    def test_workload_all_obligations_visible_other_section_and_current_assignee_only(self):
        statuses = ('issued', 'queued', 'accepted', 'in_progress', 'paused', 'rework', 'done', 'ai_review', 'rejected', 'cancelled')
        for status in statuses:
            self.add_order(status)
        self.add_order('accepted', section=self.second_section)
        hidden = self.add_order('issued', section=self.hidden_section)
        self.add_order('closed')
        other = self.add_employee('OFF-SHIFT-OTHER', on_shift=False)
        self.add_order('issued', executor=other)
        response = self.get()
        self.assertEqual(response.status_code, 200, response.text)
        workload = response.json()['candidates'][0]['workload']
        self.assertEqual(workload['outstanding_count'], 7)
        self.assertEqual(workload['active_count'], 2)
        self.assertEqual(workload['queued_count'], 1)
        self.assertEqual(workload['awaiting_review_count'], 2)
        self.assertEqual(workload['norm_minutes_total'], 420)
        self.assertEqual(workload['overdue_count'], 7)
        self.assertNotIn(hidden, response.text)

    def test_dated_history_unknown_zero_mismatch_old_future_and_foreign_filters(self):
        actual = self.add_order('closed', score=0)
        self.add_order('closed', score=None, code=False)
        old = self.add_order('closed', score=100, closed_days=91)
        future = self.add_order('closed', score=100, closed_days=-1)
        foreign = self.add_order('closed', section=self.second_section, score=100)
        other = self.add_employee('HISTORICAL', active=False)
        mismatched = self.add_order('closed', score=100, submission_actor=other)
        response = self.get(work_code_id=self.code)
        self.assertEqual(response.status_code, 200, response.text)
        history = response.json()['candidates'][0]['history']
        self.assertEqual(history['closed_count'], 2)
        self.assertEqual(history['human_score_count'], 1)
        self.assertEqual(history['human_score_mean'], 0)
        self.assertEqual(history['matching_work_code_count'], 1)
        self.assertEqual(history['on_time_rate'], 1)
        self.assertIn(actual, response.text)
        for excluded in (old, future, foreign, mismatched):
            self.assertNotIn(excluded, response.text)

    def test_actual_stable_ties_low_load_ranking_and_input_bounds(self):
        second = self.add_employee('E-2')
        first = self.get().json()['candidates']
        self.assertEqual([row['executor_id'] for row in first], [self.executor, second])
        self.assertEqual([row['rank'] for row in first], [1, 1])
        self.add_order('accepted')
        self.assertEqual(self.get(limit=1).json()['candidates'][0]['executor_id'], second)
        self.service.limits = RecommendationLimits(max_candidates=1)
        response = self.get()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['code'], 'RECOMMENDATION_LIMIT_EXCEEDED')
        self.assertNotIn('candidates', response.json())

    def test_actual_workload_and_history_overflow_fail_closed(self):
        self.add_order()
        self.add_order()
        self.service.limits = RecommendationLimits(max_workload_rows=1)
        self.assertEqual(self.get().status_code, 422)
        self.service.limits = RecommendationLimits(max_history_rows=1)
        self.add_order('closed')
        self.add_order('closed')
        self.assertEqual(self.get().status_code, 422)

    def test_unknown_code_and_extra_or_duplicate_params(self):
        self.assertEqual(self.get(work_code_id=str(uuid4())).status_code, 422)
        self.assertEqual(self.get(actor_id=self.master).status_code, 400)
        self.assertEqual(self.get(limit=6).status_code, 422)
        response = self.client.get('/api/v1/recommendations/assignees',
            params=[('section_id', self.section), ('section_id', self.hidden_section)],
            headers={'cookie': SESSION_COOKIE_NAME+'='+self.handle})
        self.assertEqual(response.status_code, 400)

    def test_concurrent_candidate_deactivation_after_snapshot_fails_closed(self):
        entered, release = Event(), Event()
        original = AssigneeRepository.capture
        def pause(repo, *args):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('Test barrier timeout')
            return original(repo, *args)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with patch.object(AssigneeRepository, 'capture', new=pause):
                pending = pool.submit(self.get)
                try:
                    self.assertTrue(entered.wait(3))
                    self.execute('UPDATE employees SET active=false WHERE id=%s', (self.executor,))
                finally:
                    release.set()
                response = pending.result(timeout=10)
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(self.get().json()['candidates'], [])

    def test_concurrent_candidate_membership_revocation_after_snapshot_fails_closed(self):
        original = AssigneeRepository.capture
        def change(repo, *args):
            self.execute('DELETE FROM employee_sections WHERE employee_id=%s', (self.executor,))
            return original(repo, *args)
        with patch.object(AssigneeRepository, 'capture', new=change):
            response = self.get()
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(self.get().json()['candidates'], [])

    def test_concurrent_new_assignment_is_excluded_from_snapshot_then_visible(self):
        original = AssigneeRepository.capture
        def append(repo, *args):
            self.add_order('accepted')
            return original(repo, *args)
        with patch.object(AssigneeRepository, 'capture', new=append):
            response = self.get()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['candidates'][0]['workload']['outstanding_count'], 0)
        self.assertEqual(self.get().json()['candidates'][0]['workload']['outstanding_count'], 1)

    def test_existing_order_change_after_snapshot_is_retryable_not_mixed(self):
        identifier = self.add_order()
        original = AssigneeRepository.capture
        def change(repo, *args):
            self.execute("UPDATE orders SET status='accepted' WHERE id=%s", (identifier,))
            return original(repo, *args)
        with patch.object(AssigneeRepository, 'capture', new=change):
            response = self.get()
        self.assertEqual(response.status_code, 503, response.text)
        self.assertTrue(response.json()['retryable'])

    def test_expiry_during_actual_order_lock_wait_is_rechecked(self):
        identifier = self.add_order()
        attempted = Event()
        original = AssigneeRepository._read
        def announce(repo, sql, params, maximum):
            if 'FROM orders WHERE' in sql:
                attempted.set()
            return original(repo, sql, params, maximum)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.connect() as blocker:
                with blocker.transaction():
                    blocker.execute('SELECT id FROM orders WHERE id=%s FOR UPDATE', (identifier,))
                    with patch.object(AssigneeRepository, '_read', new=announce):
                        pending = pool.submit(self.get)
                        self.assertTrue(attempted.wait(3))
                        self.real.value = NOW+timedelta(hours=2)
                response = pending.result(timeout=10)
        self.assertEqual(response.status_code, 401, response.text)

    def test_current_session_and_eligibility_locks_block_revoke_until_response(self):
        from app.recommendations.assignee import build_recommendations
        rendering, release = Event(), Event()
        def pause(*args, **kwargs):
            rendering.set()
            if not release.wait(5):
                raise RuntimeError('Test barrier timeout')
            return build_recommendations(*args, **kwargs)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with patch('app.recommendations.assignee.build_recommendations', side_effect=pause):
                pending = pool.submit(self.get)
                try:
                    self.assertTrue(rendering.wait(3))
                    for sql, params in (
                        ('UPDATE auth_sessions SET revoked_at=%s WHERE employee_id=%s', (NOW, self.master)),
                        ('DELETE FROM employee_sections WHERE employee_id=%s', (self.executor,)),
                        ('UPDATE employees SET on_shift=false WHERE id=%s', (self.executor,))):
                        with self.connect() as db:
                            with self.assertRaises(self.pg.errors.LockNotAvailable):
                                with db.transaction():
                                    db.execute("SET LOCAL lock_timeout = '100ms'")
                                    db.execute(sql, params)
                finally:
                    release.set()
                response = pending.result(timeout=10)
        self.assertEqual(response.status_code, 200, response.text)
        self.execute('UPDATE auth_sessions SET revoked_at=%s WHERE employee_id=%s', (NOW, self.master))
        self.assertEqual(self.get().status_code, 401)


if __name__ == '__main__':
    unittest.main()
