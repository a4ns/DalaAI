"""Pure/unit/HTTP checks. These do not claim actual PostgreSQL acceptance."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.auth_boundary import AuthContext, AuthenticationRequired, SessionRecord, SESSION_COOKIE_NAME
from app.core.auth_policy import AccessDenied, Principal, Role
from app.orders.models import DomainError
from app.recommendations.assignee import (AssigneeRecommendationService, AssigneeRepository,
    RecommendationLimits, RecommendationQuery, build_recommendations, parse_query)
from app.recommendations.assignee_routes import create_assignee_router

NOW = datetime(2026, 10, 8, 1, tzinfo=timezone.utc)

def uid(number):
    return str(UUID(int=number))

MASTER, EXECUTOR, SECOND, SECTION, OTHER_SECTION, CODE = map(uid, range(1, 7))


class Clock:
    def __init__(self):
        self.value = NOW
    def now(self):
        return self.value


def employee(identifier=EXECUTOR, code='E-1'):
    return {'id': identifier, 'employee_code': code}


def order(number=10, status='issued', executor=EXECUTOR):
    return {'id': uid(number), 'executor_id': executor, 'status': status,
            'norm_minutes': 60, 'due_at': NOW-timedelta(minutes=1), 'updated_at': NOW-timedelta(hours=1)}


def observation(number=100, *, executor=EXECUTOR, score=None, code=CODE, late=False):
    return {'order_id': uid(number), 'submission_id': uid(number+100), 'review_id': uid(number+200),
            'executor_id': executor, 'submitted_at': NOW-timedelta(days=2),
            'reviewed_at': NOW-timedelta(days=1), 'work_code_id': code, 'final_score': score, 'done_late': late}


class ProjectionTests(unittest.TestCase):
    def project(self, employees=None, workload=(), history=(), code=None, limit=5):
        return build_recommendations(employees if employees is not None else [employee()], workload, history,
            query=RecommendationQuery(SECTION, code, limit), domain_as_of=NOW, limits=RecommendationLimits())

    def test_no_candidates_is_empty_and_one_candidate_is_not_fabricated(self):
        self.assertEqual(self.project([]), [])
        candidate, = self.project()
        self.assertEqual(candidate['executor_id'], EXECUTOR)
        self.assertEqual(candidate['rank'], 1)

    def test_no_history_is_unknown_performance_not_bad_performance(self):
        candidate, = self.project()
        history = candidate['history']
        self.assertEqual(history['status'], 'no_observations')
        self.assertEqual(history['closed_count'], 0)
        for key in ('human_score_mean', 'on_time_rate', 'matching_work_code_count', 'latest_closed_at'):
            self.assertIsNone(history[key])
        self.assertIn('NO_CLOSED_HISTORY', candidate['reason_codes'])
        self.assertIn('HUMAN_SCORE_UNKNOWN', candidate['reason_codes'])
        self.assertEqual(candidate['workload']['outstanding_count'], 0)
        self.assertIn('NO_VISIBLE_OUTSTANDING_ORDERS', candidate['reason_codes'])

    def test_observed_zero_score_is_zero_and_missing_score_excluded_from_denominator(self):
        candidate, = self.project(history=[observation(100, score=0), observation(101, score=None, late=True)], code=CODE)
        history = candidate['history']
        self.assertEqual(history['closed_count'], 2)
        self.assertEqual(history['human_score_mean'], 0)
        self.assertEqual(history['human_score_count'], 1)
        self.assertEqual(history['on_time_rate'], .5)
        self.assertEqual(history['matching_work_code_count'], 2)
        self.assertEqual(history['evidence'][0]['reviewed_at'], (NOW-timedelta(days=1)).isoformat())

    def test_workload_is_actual_obligations_not_just_explicit_queue(self):
        statuses = ['issued', 'accepted', 'queued', 'in_progress', 'paused', 'rework', 'done', 'ai_review']
        candidate, = self.project(workload=[order(n+10, s) for n, s in enumerate(statuses)])
        workload = candidate['workload']
        self.assertEqual(workload['outstanding_count'], 6)
        self.assertEqual(workload['active_count'], 2)
        self.assertEqual(workload['queued_count'], 1)
        self.assertEqual(workload['awaiting_review_count'], 2)
        self.assertEqual(workload['overdue_count'], 6)
        self.assertEqual(workload['norm_minutes_total'], 360)
        self.assertEqual(workload['scope'], 'current_master_authorized_sections')
        self.assertEqual(len(workload['evidence']), 5)
        self.assertTrue(workload['evidence_truncated'])

    def test_due_exactly_now_is_not_overdue(self):
        item = order()
        item['due_at'] = NOW
        self.assertEqual(self.project(workload=[item])[0]['workload']['overdue_count'], 0)

    def test_workload_first_historical_observations_only_break_workload_ties(self):
        employees = [employee(), employee(SECOND, 'E-2')]
        rows = self.project(employees, [order()], [observation()], CODE)
        self.assertEqual([row['executor_id'] for row in rows], [SECOND, EXECUTOR])
        rows = self.project(employees, [], [observation()], CODE)
        self.assertEqual([row['executor_id'] for row in rows], [EXECUTOR, SECOND])
        self.assertEqual([row['rank'] for row in rows], [1, 2])
        # A quality score never promotes an otherwise tied employee.
        rows = self.project(employees, [], [observation(executor=SECOND, score=100)])
        self.assertEqual([row['executor_id'] for row in rows], [EXECUTOR, SECOND])
        self.assertEqual([row['rank'] for row in rows], [1, 1])

    def test_active_count_breaks_equal_outstanding_ties(self):
        employees = [employee(), employee(SECOND, 'E-2')]
        rows = self.project(employees, [order(10, 'in_progress'), order(11, 'accepted', SECOND)])
        self.assertEqual([row['executor_id'] for row in rows], [SECOND, EXECUTOR])
        self.assertEqual([row['rank'] for row in rows], [1, 2])

    def test_stable_ties_are_order_independent_and_capped(self):
        employees = [employee(uid(n), 'same-code') for n in range(20, 14, -1)]
        expected = [uid(n) for n in range(15, 18)]
        for source in (employees, list(reversed(employees))):
            rows = self.project(source, limit=3)
            self.assertEqual([row['executor_id'] for row in rows], expected)
            self.assertEqual([row['rank'] for row in rows], [1, 1, 1])

    def test_requested_work_code_zero_is_observed_absence_not_missing_skill(self):
        candidate, = self.project(history=[observation(code=None)], code=CODE)
        self.assertEqual(candidate['history']['matching_work_code_count'], 0)
        self.assertIn('NO_MATCHING_WORK_CODE_HISTORY', candidate['reason_codes'])
        self.assertNotIn('skill', candidate)

    def test_historical_evidence_is_bounded_without_truncating_totals(self):
        candidate, = self.project(history=[observation(n, score=n-100) for n in range(100, 108)])
        self.assertEqual(candidate['history']['closed_count'], 8)
        self.assertEqual(candidate['history']['human_score_count'], 8)
        self.assertEqual(len(candidate['history']['evidence']), 5)
        self.assertTrue(candidate['history']['evidence_truncated'])


class QueryTests(unittest.TestCase):
    def test_default_and_optional_code(self):
        self.assertEqual(parse_query({'section_id': SECTION}), RecommendationQuery(SECTION))
        self.assertEqual(parse_query({'section_id': SECTION, 'work_code_id': CODE, 'limit': '5'}),
                         RecommendationQuery(SECTION, CODE, 5))

    def test_unknown_duplicate_spoofed_scope_and_unbounded_query_rejected(self):
        for query in ({}, {'section_id': 'bad'}, {'section_id': SECTION, 'limit': '6'},
                      {'section_id': SECTION, 'limit': '-1'}, {'section_id': SECTION, 'limit': '01'},
                      {'section_id': SECTION, 'role': 'master'}, {'section_id': SECTION, 'equipment_id': CODE},
                      [('section_id', SECTION), ('section_id', OTHER_SECTION)],
                      {'section_id': SECTION, 'work_code_id': ''}):
            with self.subTest(query=query), self.assertRaises(DomainError):
                parse_query(query)

    def test_limits_cannot_be_unbounded_or_boolean(self):
        for value in (0, -1, 101, True):
            with self.assertRaises(ValueError):
                RecommendationLimits(max_candidates=value)


class DB:
    def __init__(self):
        self.calls, self.rows = [], []
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def transaction(self):
        return self
    def execute(self, statement, params=()):
        self.calls.append((statement, params))
        return self
    def fetchall(self):
        return self.rows
    def fetchone(self):
        return {'id': CODE}


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.db, self.clock = DB(), Clock()
        self.principal = Principal(MASTER, Role.MASTER, frozenset({SECTION}))
        self.session = SessionRecord(MASTER, NOW-timedelta(hours=1), NOW+timedelta(hours=1), 'unit-only')
        self.service = AssigneeRecommendationService(lambda: None, domain_clock=self.clock,
                                                     real_clock=self.clock, synthetic=True)
        self.service._connection = lambda: self.db
        self.auth_calls = 0
        def authenticate(db, handle):
            self.auth_calls += 1
            if self.clock.now() >= self.session.expires_at:
                raise AuthenticationRequired()
            return AuthContext(self.principal, self.session)
        self.service._auth = authenticate
        self.capture = patch.object(AssigneeRepository, 'capture', return_value=([employee()], [], []))
        self.repo = self.capture.start()
        self.addCleanup(self.capture.stop)

    def call(self, project=None):
        return self.service.recommend({'section_id': SECTION}, session_handle='unit-only', project=project)

    def test_truthful_mode_provenance_one_candidate_and_short_freshness(self):
        result = self.call()
        self.assertEqual(result['mode'], 'rules_baseline')
        self.assertIsNone(result['model'])
        self.assertEqual(result['model_status'], 'disabled_for_purpose')
        self.assertTrue(result['advisory_only'])
        self.assertTrue(result['synthetic'])
        self.assertEqual(result['eligible_count'], 1)
        self.assertEqual(result['expires_at'], (NOW+timedelta(seconds=30)).isoformat())
        self.assertIn('ONLY_ONE_ELIGIBLE_EXECUTOR', result['limitations'])
        self.assertIn('QUALIFICATIONS_UNVERIFIED', result['limitations'])
        self.assertEqual(self.auth_calls, 2)
        self.service.synthetic = False
        result = self.call()
        self.assertFalse(result['synthetic'])
        self.assertNotIn('SYNTHETIC_DATA', result['limitations'])
        self.assertTrue(all(sql.startswith('SET ') for sql, params in self.db.calls))

    def test_source_provenance_required(self):
        for flag in (None, 'true', 1):
            with self.assertRaises(ValueError):
                AssigneeRecommendationService(lambda: None, domain_clock=self.clock, synthetic=flag)

    def test_forbidden_roles_and_foreign_section_never_read_candidate_facts(self):
        for role in (Role.ADMIN, Role.EXECUTOR, Role.MANAGER):
            self.principal = Principal(MASTER, role, frozenset({SECTION}))
            with self.assertRaises(AccessDenied):
                self.call()
        self.principal = Principal(MASTER, Role.MASTER, frozenset({OTHER_SECTION}))
        with self.assertRaises(AccessDenied):
            self.call()
        self.repo.assert_not_called()

    def test_no_candidates_is_explicit_and_not_failed_request(self):
        self.repo.return_value = ([], [], [])
        result = self.call()
        self.assertEqual(result['eligible_count'], 0)
        self.assertEqual(result['candidates'], [])
        self.assertIn('NO_ELIGIBLE_EXECUTORS', result['limitations'])

    def test_session_expiry_after_capture_is_denied(self):
        def expired(*args):
            self.clock.value = self.session.expires_at
            return [employee()], [], []
        self.repo.side_effect = expired
        with self.assertRaises(AuthenticationRequired):
            self.call()

    def test_response_rendering_is_inside_final_auth_check(self):
        def render(body):
            self.clock.value = self.session.expires_at
            return body
        with self.assertRaises(AuthenticationRequired):
            self.call(render)

    def test_principal_changes_during_render_fail_closed(self):
        def render(body):
            self.principal = Principal(MASTER, Role.MASTER, frozenset({OTHER_SECTION}))
            return body
        with self.assertRaises(AccessDenied):
            self.call(render)

    def test_long_capture_is_stale_even_if_session_still_valid(self):
        def render(body):
            self.clock.value += timedelta(seconds=30)
            return body
        with self.assertRaises(DomainError) as error:
            self.call(render)
        self.assertEqual(error.exception.code, 'TEMPORARILY_UNAVAILABLE')

    def test_response_byte_limit_refuses_entire_result(self):
        with patch('app.recommendations.assignee.MAX_RESPONSE_BYTES', 1):
            with self.assertRaises(DomainError) as error:
                self.call()
        self.assertEqual(error.exception.code, 'RECOMMENDATION_LIMIT_EXCEEDED')

    def test_accelerated_domain_time_does_not_extend_real_session(self):
        domain = Clock()
        domain.value = NOW+timedelta(days=365)
        self.service.domain_clock = domain
        result = self.call()
        self.assertEqual(result['domain_as_of'], domain.value.isoformat())
        self.assertEqual(result['as_of'], NOW.isoformat())
        self.assertEqual(result['expires_at'], (NOW+timedelta(seconds=30)).isoformat())

    def test_expiry_never_outlives_current_session(self):
        self.session = SessionRecord(MASTER, NOW-timedelta(hours=1), NOW+timedelta(seconds=10), 'unit-only')
        self.assertEqual(self.call()['expires_at'], self.session.expires_at.isoformat())


class RepositoryTests(unittest.TestCase):
    def test_bound_overflow_fails_without_partial_ranking(self):
        db = DB()
        db.rows = [employee(), employee(SECOND, 'E-2')]
        with self.assertRaises(DomainError) as error:
            AssigneeRepository(db, RecommendationLimits(max_candidates=1)).capture(
                Principal(MASTER, Role.MASTER, frozenset({SECTION})), RecommendationQuery(SECTION), NOW)
        self.assertEqual(error.exception.code, 'RECOMMENDATION_LIMIT_EXCEEDED')

    def test_oversized_employee_code_fails_before_other_fact_reads(self):
        db = DB()
        db.rows = [employee(code='x'*257)]
        with self.assertRaises(DomainError) as error:
            AssigneeRepository(db, RecommendationLimits()).capture(
                Principal(MASTER, Role.MASTER, frozenset({SECTION})), RecommendationQuery(SECTION), NOW)
        self.assertEqual(error.exception.code, 'TEMPORARILY_UNAVAILABLE')
        self.assertEqual(len(db.calls), 1)

    def test_sql_uses_only_authorized_candidate_ids_and_full_visible_workload(self):
        db = DB()
        repository = AssigneeRepository(db, RecommendationLimits())
        with patch.object(repository, '_read', side_effect=[[employee()], [], []]) as reads:
            repository.capture(Principal(MASTER, Role.MASTER, frozenset({SECTION, OTHER_SECTION})),
                               RecommendationQuery(SECTION, CODE), NOW)
        candidate, workload, history = reads.call_args_list
        self.assertIn("e.active AND e.on_shift AND e.role='executor'", candidate.args[0])
        self.assertIn('FOR SHARE OF e,es', candidate.args[0])
        self.assertEqual(candidate.args[1], (SECTION,))
        self.assertEqual(workload.args[1][0], [EXECUTOR])
        self.assertEqual(workload.args[1][1], sorted([SECTION, OTHER_SECTION]))
        for excluded in ('closed', 'cancelled', 'rejected'):
            self.assertNotIn(excluded, workload.args[1][2])
        self.assertIn('s.submitted_by=o.executor_id', history.args[0])
        self.assertIn("r.decision='close'", history.args[0])
        self.assertTrue(history.args[0].endswith("FOR SHARE OF o"))
        self.assertNotIn("FOR SHARE OF o,s,r", history.args[0])
        self.assertEqual(history.args[1][0], SECTION)
        self.assertEqual(history.args[1][2], NOW-timedelta(days=90))
        for call in reads.call_args_list:
            self.assertNotIn(EXECUTOR, call.args[0])
            self.assertNotIn('pin_hash', call.args[0])


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.service = SimpleNamespace(recommend=lambda query, **kwargs: kwargs['project']({'ok': True}))
        app = FastAPI()
        app.include_router(create_assignee_router(self.service))
        self.client = TestClient(app)
        self.url = '/api/v1/recommendations/assignees?section_id='+SECTION
        self.cookie = {'cookie': SESSION_COOKIE_NAME+'=unit-only'}

    def test_only_get_cookie_based_no_store(self):
        result = self.client.get(self.url, headers=self.cookie)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {'ok': True})
        self.assertEqual(result.headers['cache-control'], 'private, no-store')
        self.assertEqual(result.headers['vary'], 'Cookie')
        self.assertEqual(self.client.post(self.url, headers=self.cookie).status_code, 405)
        self.assertEqual(self.client.get(self.url, headers={'authorization': 'Bearer unit-only'}).status_code, 401)
        self.assertEqual(self.client.get(self.url, headers={'cookie':
            SESSION_COOKIE_NAME+'=a; '+SESSION_COOKIE_NAME+'=b'}).status_code, 401)

    def test_error_has_no_partial_data_or_sensitive_exception(self):
        for error, expected in [(AuthenticationRequired(), 401), (AccessDenied(), 403),
            (DomainError('VALIDATION_FAILED', 'Bad query'), 422),
            (DomainError('RECOMMENDATION_LIMIT_EXCEEDED', 'Too many rows'), 422),
            (RuntimeError('secret DSN or employee'), 503)]:
            def fail(*args, **kwargs):
                raise error
            self.service.recommend = fail
            result = self.client.get(self.url, headers=self.cookie)
            self.assertEqual(result.status_code, expected)
            self.assertNotIn('candidates', result.json())
            self.assertNotIn('secret', result.text)
            self.assertEqual(result.json()['retryable'], expected == 503)
            self.assertEqual(result.headers['cache-control'], 'private, no-store')


if __name__ == '__main__':
    unittest.main()
