"""Focused mock/HTTP acceptance using real SessionService auth (no real DB).

All identities and data are generated/synthetic. No login/PIN fixture imports.
Transactions/locks here are recorded mocks, never PostgreSQL evidence.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.errors import DeadlockDetected, SerializationFailure
from psycopg.pq import TransactionStatus

from app.analytics.c3_repository import CaptureLimits, RuntimeReportService
from app.core.auth_boundary import SESSION_COOKIE_NAME
from app.reports.c4_routes import create_c_runtime_router
from app.sessions.service import SessionService

NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)


def uid(n):
    return str(UUID(int=n))


class Clock:
    def __init__(self, value=NOW):
        self.value = value
    def now(self):
        return self.value


class Cursor:
    def __init__(self, rows):
        self.rows = rows
    def fetchall(self):
        return deepcopy(self.rows)
    def fetchone(self):
        return deepcopy(self.rows[0]) if self.rows else None


class MockDatabase:
    """Understands only the explicit selects used by existing auth and C111."""
    def __init__(self):
        self.handle = uuid4().hex
        self.role, self.active, self.sections = 'master', True, [uid(1)]
        self.revoked, self.expiry = None, NOW + timedelta(hours=1)
        self.autocommit = True
        self.info = SimpleNamespace(transaction_status=TransactionStatus.IDLE)
        self.calls, self.closed, self.committed = [], False, False
        self.after_read = None
        self.failure = None
        self.size_override = None
        self.tables = {
            'orders': [dict(id=uid(10), number=1, version=5, assignment_revision=1,
                scheduling_revision=1, status='closed', type='planned', description='Synthetic work',
                section_id=uid(1), equipment_id=uid(2), executor_id=uid(4), brigade_id=None,
                created_by=uid(3), issued_at=NOW-timedelta(days=40), due_at=NOW-timedelta(days=2),
                norm_minutes=60, priority='normal', comment='', current_submission_id=uid(20),
                updated_at=NOW-timedelta(hours=1))],
            'submissions': [dict(id=uid(20), order_id=uid(10), assignment_revision=1, attempt_number=1,
                submitted_by=uid(4), submitted_at=NOW-timedelta(days=2), done_late=False,
                work_description='Synthetic completed work', work_code_id=uid(5), comment='',
                completeness='complete', missing_evidence=[], after_photo_ids=[])],
            'photos': [],
            'material_writeoffs': [dict(submission_id=uid(20), material_id=uid(6), quantity=Decimal('1.250'))],
            'reviews': [dict(id=uid(30), submission_id=uid(20), reviewer_id=uid(3), decision='close',
                reason='Synthetic human decision', final_score=None, created_at=NOW-timedelta(hours=1))],
            'ai_assessments': [dict(id=uid(40), submission_id=uid(20), assignment_revision=1,
                schema_version='1', mode='rules_fallback', model=None, model_version=None,
                duration_ms=0, recommendation='satisfactory', score=99, reasons=['Synthetic rule'],
                evidence_ids=[], fallback_reason='Provider not configured', stale=False,
                created_at=NOW-timedelta(days=2))],
            'materials': [dict(id=uid(6), label='Synthetic material', unit='kg')],
        }

    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()
    def close(self):
        self.closed = True
    @contextmanager
    def transaction(self):
        self.info.transaction_status = TransactionStatus.INTRANS
        try:
            yield
            self.committed = True
        finally:
            self.info.transaction_status = TransactionStatus.IDLE

    def execute(self, sql, params=()):
        statement = ' '.join(sql.split())
        self.calls.append((statement, params))
        if self.failure and self.failure[0] in statement:
            raise self.failure[1]
        if statement.startswith('SET '):
            return Cursor([])
        if 'FROM auth_sessions' in statement:
            rows = [] if params[0] != sha256(self.handle.encode()).hexdigest() else [dict(
                employee_id=uid(3), created_at=NOW-timedelta(days=1), expires_at=self.expiry,
                csrf_token='synthetic-non-login-value', revoked_at=self.revoked)]
            return Cursor(rows)
        if 'FROM employees ' in statement:
            return Cursor([dict(id=uid(3), role=self.role, active=self.active)])
        if 'FROM employee_sections' in statement:
            return Cursor([dict(section_id=section) for section in self.sections])
        tables = ('orders', 'submissions', 'photos', 'material_writeoffs', 'reviews', 'ai_assessments', 'materials')
        table = next(name for name in tables if 'FROM ' + name + ' ' in statement)
        rows = deepcopy(self.tables[table])
        if table == 'orders':
            rows = [r for r in rows if r['section_id'] in params[0]]
            if 'AND id=%s::uuid' in statement:
                rows = [r for r in rows if r['id'] == params[1]]
        else:
            key = ('order_id' if table == 'submissions' or table == 'photos' and "purpose='before'" in statement
                   else 'id' if table == 'materials' else 'submission_id')
            rows = [r for r in rows if r[key] in params[0]]
            if table == 'photos':
                purpose = 'before' if "purpose='before'" in statement else 'after'
                rows = [r for r in rows if r['purpose'] == purpose and r['attached_at'] is not None]
        rows = sorted(rows, key=lambda row: row.get('id', row.get('material_id', '')))[:params[-1]]
        if self.after_read:
            self.after_read(table, statement)
        if statement.startswith('SELECT count(*)'):
            sizes = [len(json.dumps(row, default=str).encode()) for row in rows]
            return Cursor([self.size_override or dict(row_count=len(rows), byte_count=sum(sizes),
                                                      largest_row=max(sizes, default=0))])
        return Cursor(rows)


class RuntimeReportTests(unittest.TestCase):
    def setUp(self):
        self.db = MockDatabase()
        self.real, self.domain = Clock(), Clock()
        # Actual SessionService, PostgresSessions, PostgresPrincipals and
        # authenticate_session are exercised; only DB transport is a mock.
        self.sessions = SessionService(lambda: self.db, allowed_origin='https://reports.test',
                                       real_clock=self.real)
        self.service = RuntimeReportService(self.sessions, domain_clock=self.domain, synthetic=True)
        app = FastAPI()
        app.include_router(create_c_runtime_router(self.service))
        self.client = TestClient(app)
        self.headers = {'cookie': SESSION_COOKIE_NAME + '=' + self.db.handle}
        self.query = {'start': (NOW-timedelta(days=1)).isoformat(), 'end': NOW.isoformat()}

    def get(self, path='/reports/shift', query=None, headers=None):
        return self.client.get('/api/v1' + path, params=self.query if query is None else query,
                               headers=self.headers if headers is None else headers)

    def test_shift_uses_old_orders_and_submissions_with_close_in_period(self):
        response = self.get()
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        metrics = {m['name']: m for m in data['metrics']}
        self.assertEqual(metrics['issued_orders']['value'], '0')
        self.assertEqual(metrics['submission_attempts']['value'], '0')
        self.assertEqual(metrics['closed_orders']['value'], '1')
        self.assertEqual(metrics['human_score']['status'], 'missing')
        self.assertIsNone(metrics['human_score']['value'])
        self.assertEqual(data['closed_materials'][0]['quantity'], '1.250')
        self.assertTrue(data['provenance']['synthetic'])
        self.assertTrue(data['totals_available'])
        self.assertEqual(data['provenance']['coverage'], 'consistent_snapshot')
        self.assertEqual(data['provenance']['domain_as_of'], '2026-10-08T00:00:00Z')
        self.assertNotIn('orders', data)

    def test_analytics_and_one_order_json_and_inert_html(self):
        self.assertEqual(self.get('/analytics/shift').json()['orders'][0]['order']['id'], uid(10))
        self.db.tables['orders'][0]['comment'] = '<script>alert(1)</script><img src="https://evil.invalid">'
        response = self.get('/reports/orders/' + uid(10), {**self.query, 'format': 'html'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('СИНТЕТИЧЕСКИЕ ДАННЫЕ', response.text)
        self.assertIn('&lt;script&gt;', response.text)
        self.assertNotIn('<script>', response.text)
        self.assertIn("default-src 'none'", response.headers['content-security-policy'])
        self.assertIn('sandbox', response.headers['content-security-policy'])
        data = self.get('/reports/orders/' + uid(10)).json()
        self.assertEqual(data['report_kind'], 'order')
        self.assertNotIn('metrics', data)
        self.assertIsNone(data['order']['attempts'][0]['review']['final_score'])
        self.assertEqual(data['order']['attempts'][0]['assessments'][0]['score'], 99)

    def test_session_required_cookie_ambiguity_and_no_identity_header_fallback(self):
        for headers in ({}, {'authorization': 'Bearer supplied', 'x-role': 'master'},
                        {'cookie': SESSION_COOKIE_NAME+'=a; '+SESSION_COOKIE_NAME+'=b'},
                        {'cookie': SESSION_COOKIE_NAME+'=unknown'}):
            with self.subTest(headers=headers):
                self.assertEqual(self.get(headers=headers).status_code, 401)
        self.assertFalse(any('FROM orders ' in sql for sql, _ in self.db.calls))

    def test_roles_and_current_membership_not_asserted_by_client(self):
        for role in ('executor', 'manager', 'admin'):
            self.db.role = role
            self.assertEqual(self.get().status_code, 403)
        self.db.role = 'master'
        self.assertEqual(self.get().status_code, 200)
        self.db.sections = []
        self.assertEqual(self.get().status_code, 403)
        self.db.sections = [uid(99)]
        self.assertEqual(self.get('/reports/orders/'+uid(10)).status_code, 404)
        self.db.active = False
        self.assertEqual(self.get().status_code, 401)
        self.db.active = True
        self.db.revoked = NOW
        self.assertEqual(self.get().status_code, 401)

    def test_foreign_and_missing_order_indistinguishable_no_related_load(self):
        self.db.tables['orders'][0]['section_id'] = uid(99)
        for order_id in (uid(10), uid(999)):
            self.db.calls.clear()
            response = self.get('/reports/orders/'+order_id)
            self.assertEqual(response.status_code, 404)
            self.assertNotIn(order_id, response.text)
            self.assertFalse(any('FROM submissions ' in sql or 'FROM photos ' in sql for sql, _ in self.db.calls))

    def test_unknown_duplicate_client_scope_and_clock_parameters_rejected(self):
        for extra in ('section_id', 'section_ids', 'role', 'actor', 'synthetic', 'as_of', 'session_handle'):
            self.assertEqual(self.get(query={**self.query, extra: 'supplied'}).status_code, 400)
        duplicate = list(self.query.items()) + [('start', self.query['start'])]
        self.assertEqual(self.get(query=duplicate).status_code, 400)
        self.assertEqual(self.get(query={**self.query, 'format':'pdf'}).status_code, 422)
        self.assertEqual(self.get('/analytics/shift', {**self.query, 'format':'html'}).status_code, 422)

    def test_period_and_identifier_bounds(self):
        bad = ({}, {'start':'2026-10-07', 'end':self.query['end']},
               {**self.query, 'start':'2026-10-07T00:00:00'},
               {**self.query, 'start':(NOW-timedelta(days=32)).isoformat()},
               {**self.query, 'end':(NOW+timedelta(seconds=1)).isoformat()},
               {**self.query, 'start':self.query['end']})
        for query in bad:
            self.assertEqual(self.get(query=query).status_code, 422, query)
        self.assertEqual(self.get('/reports/orders/not-an-id').status_code, 422)

    def test_order_limit_related_row_limit_and_byte_limit_fail_whole_capture(self):
        other = {**self.db.tables['orders'][0], 'id':uid(11)}
        self.db.tables['orders'].append(other)
        self.service.limits = CaptureLimits(max_orders=1)
        self.assertEqual(self.get().status_code, 422)
        self.db.tables['orders'].pop()
        self.service.limits = CaptureLimits(max_rows=2)
        self.assertEqual(self.get().status_code, 422)
        self.service.limits = CaptureLimits()
        self.db.size_override = dict(row_count=1, byte_count=10**8, largest_row=10**8)
        self.db.calls.clear()
        response = self.get()
        self.assertEqual(response.status_code, 422)
        self.assertNotIn('totals_available', response.text)
        self.assertFalse(any(sql.startswith('SELECT id,number') for sql, _ in self.db.calls))

    def test_rr_precedes_auth_all_parents_locked_and_query_parameters_bound(self):
        self.assertEqual(self.get().status_code, 200)
        sqls = [sql for sql, _ in self.db.calls]
        self.assertEqual(sqls[0], 'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        self.assertNotIn('READ ONLY', ' '.join(sqls))
        self.assertTrue(all('FOR SHARE' in sql for sql in sqls if 'FROM orders ' in sql))
        self.assertTrue(all(sql.startswith(('SELECT ', 'SET ')) for sql in sqls))
        self.assertTrue(all('LIMIT %s' in sql for sql in sqls if any('FROM '+t+' ' in sql
            for t in self.db.tables)))
        self.assertTrue(all(self.db.handle not in sql for sql in sqls))
        self.assertTrue(self.db.committed)

    def test_rechecks_expiry_after_blocking_reads_and_after_render(self):
        def expire(table, sql):
            if table == 'orders':
                self.real.value = self.db.expiry
        self.db.after_read = expire
        self.assertEqual(self.get().status_code, 401)
        self.db.after_read, self.real.value = None, NOW
        from app.reports.c4_routes import shift_report_data
        def slow_render(facts):
            self.real.value = self.db.expiry
            return shift_report_data(facts)
        with patch('app.reports.c4_routes.shift_report_data', side_effect=slow_render):
            self.assertEqual(self.get().status_code, 401)

    def test_changed_principal_after_capture_fails_closed(self):
        self.db.after_read = lambda *_: setattr(self.db, 'sections', [uid(99)])
        self.assertEqual(self.get().status_code, 403)

    def test_serialization_deadlock_and_schema_errors_generic_retryable(self):
        for error in (SerializationFailure('private db details'), DeadlockDetected('private db details'),
                      RuntimeError('private db details')):
            self.db.failure = ('FROM orders', error)
            response = self.get()
            self.assertEqual(response.status_code, 503)
            self.assertTrue(response.json()['retryable'])
            self.assertNotIn('private db details', response.text)
            self.assertEqual(response.headers['retry-after'], '1')

    def test_incomplete_or_invalid_rows_never_produce_successful_totals(self):
        for table in ('submissions', 'reviews', 'materials'):
            saved = self.db.tables[table]
            self.db.tables[table] = []
            self.assertEqual(self.get().status_code, 503, table)
            self.db.tables[table] = saved
        self.db.tables['orders'][0]['updated_at'] = NOW+timedelta(seconds=1)
        self.assertEqual(self.get().status_code, 503)

    def test_after_photo_manifest_and_before_parent_binding_fail_closed(self):
        self.db.tables['submissions'][0]['after_photo_ids'] = [uid(90)]
        self.assertEqual(self.get().status_code, 503)
        self.db.tables['photos'] = [dict(id=uid(90), order_id=uid(10), section_id=uid(1),
            submission_id=uid(20), assignment_revision=1, purpose='after', attached_at=NOW)]
        self.assertEqual(self.get().status_code, 200)
        self.db.tables['photos'][0]['section_id'] = uid(99)
        self.assertEqual(self.get().status_code, 503)
        self.db.tables['submissions'][0]['after_photo_ids'] = []
        self.db.tables['photos'][0].update(purpose='before', submission_id=None)
        self.assertEqual(self.get().status_code, 503)

    def test_preflight_count_mismatch_and_section_cap_never_claim_completeness(self):
        self.db.size_override = dict(row_count=0, byte_count=0, largest_row=0)
        self.assertEqual(self.get().status_code, 503)
        self.db.size_override = None
        self.service.limits = CaptureLimits(max_sections=1)
        self.db.sections = [uid(1),uid(2)]
        self.db.calls.clear()
        self.assertEqual(self.get().status_code, 422)
        self.assertFalse(any('FROM orders ' in sql for sql, _ in self.db.calls))

    def test_initial_membership_wait_expiry_denied_before_parent_data(self):
        original = self.db.execute
        def slow_membership(sql, params=()):
            result = original(sql, params)
            if 'FROM employee_sections' in sql:
                self.real.value = self.db.expiry
            return result
        with patch.object(self.db, 'execute', side_effect=slow_membership):
            response = self.get()
        self.assertEqual(response.status_code, 401)
        self.assertFalse(any('FROM orders ' in sql for sql, _ in self.db.calls))

    def test_missing_and_zero_human_score_stay_distinct_from_ai(self):
        self.db.tables['reviews'][0]['final_score'] = 0
        data = self.get().json()
        score = next(m for m in data['metrics'] if m['name']=='human_score')
        self.assertEqual(score['value'], '0.000000000000')
        self.assertEqual(score['missing'], 0)

    def test_fresh_connection_guard_before_any_sql(self):
        self.db.info.transaction_status = TransactionStatus.INTRANS
        self.assertEqual(self.get().status_code, 503)
        self.assertEqual(self.db.calls, [])
        self.db.info.transaction_status = TransactionStatus.IDLE
        self.db.autocommit = False
        self.assertEqual(self.get().status_code, 503)
        self.assertEqual(self.db.calls, [])
        self.assertTrue(self.db.closed)

    def test_cache_controls_on_success_errors_and_no_mutation_routes(self):
        for response in (self.get(), self.get(headers={}), self.get(query={})):
            self.assertEqual(response.headers['cache-control'], 'private, no-store')
            self.assertEqual(response.headers['vary'], 'Cookie')
            self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
            self.assertEqual(response.headers['referrer-policy'], 'no-referrer')
        self.assertEqual(self.client.post('/api/v1/reports/shift', headers=self.headers).status_code, 405)
        self.assertEqual(set(self.client.app.openapi()['paths']),
            {'/api/v1/reports/shift','/api/v1/analytics/shift','/api/v1/reports/orders/{order_id}'})

    def test_server_only_provenance_and_limits_are_explicit(self):
        with self.assertRaises(TypeError):
            RuntimeReportService(self.sessions, domain_clock=self.domain)
        for value in ('true', 1, None):
            with self.assertRaises(ValueError):
                RuntimeReportService(self.sessions, domain_clock=self.domain, synthetic=value)
        with self.assertRaises(ValueError):
            CaptureLimits(max_orders=True)
        self.service.synthetic = False
        self.assertFalse(self.get().json()['provenance']['synthetic'])
        self.assertNotIn(self.db.handle, self.get().text)

    def test_response_size_is_bounded_without_partial_response(self):
        with patch('app.reports.c4_routes.MAX_RESPONSE_BYTES', 1):
            response = self.get()
        self.assertEqual(response.status_code, 422)
        self.assertNotIn('metrics', response.json())

    def test_source_has_no_mount_side_effect_or_credentials_projection(self):
        source = Path(__file__).parents[1].joinpath('app/analytics/c3_repository.py').read_text()
        self.assertNotIn('pin_hash', source)
        self.assertNotIn('csrf_token', source)
        self.assertNotIn('DATABASE_URL', source)
        self.assertNotIn('include_router', source)
        self.assertNotIn('SELECT *', source)


if __name__ == '__main__':
    unittest.main()
