"""Bounded, read-only executor advice from current authorized PostgreSQL facts.

This is a deterministic rules baseline, not AI, a competence assessment, a
reservation, or an assignment command. Existing auth locks require a logically
read-only transaction rather than PostgreSQL's READ ONLY transaction mode.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from uuid import UUID

from app.core.auth_boundary import SystemRealClock, authenticate_session
from app.core.auth_policy import AccessDenied, Role
from app.orders.models import DomainError
from app.persistence.postgres import PostgresPrincipals, PostgresSessions

OUTSTANDING = frozenset({'issued', 'queued', 'accepted', 'in_progress', 'paused', 'rework'})
ACTIVE = frozenset({'in_progress', 'paused'})
AWAITING_REVIEW = frozenset({'done', 'ai_review'})
RANKING_POLICY = 'outstanding_then_active_then_observed_work_code_v1'
MAX_RESPONSE_BYTES = 512 * 1024


@dataclass(frozen=True)
class RecommendationLimits:
    max_sections: int = 100
    max_candidates: int = 100
    max_workload_rows: int = 5000
    max_history_rows: int = 5000
    evidence_per_candidate: int = 5

    def __post_init__(self):
        bounds = {'max_sections': 100, 'max_candidates': 100, 'max_workload_rows': 5000,
                  'max_history_rows': 5000, 'evidence_per_candidate': 5}
        for key, maximum in bounds.items():
            value = getattr(self, key)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError('Recommendation limits must be positive and bounded')


@dataclass(frozen=True)
class RecommendationQuery:
    section_id: str
    work_code_id: str | None = None
    limit: int = 3


def _unavailable():
    return DomainError('TEMPORARILY_UNAVAILABLE', 'Recommendations are temporarily unavailable')


def _instant(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise _unavailable()
    return value.astimezone(timezone.utc)


def parse_query(query):
    pairs = list(query.items()) if isinstance(query, dict) else list(query)
    values = {}
    if len(pairs) > 3:
        raise DomainError('INVALID_REQUEST', 'Unsupported recommendation query')
    for key, value in pairs:
        if key not in {'section_id', 'work_code_id', 'limit'} or key in values:
            raise DomainError('INVALID_REQUEST', 'Unsupported recommendation query')
        if not isinstance(value, str) or not value or len(value) > 64:
            raise DomainError('VALIDATION_FAILED', 'Invalid recommendation query')
        values[key] = value
    try:
        section = str(UUID(values['section_id']))
        code = str(UUID(values['work_code_id'])) if 'work_code_id' in values else None
        raw_limit = values.get('limit', '3')
        if raw_limit not in {'1', '2', '3', '4', '5'}:
            raise ValueError()
        return RecommendationQuery(section, code, int(raw_limit))
    except (KeyError, ValueError, TypeError, AttributeError):
        raise DomainError('VALIDATION_FAILED', 'A section UUID and limit from 1 to 5 are required') from None


class AssigneeRepository:
    def __init__(self, db, limits):
        self.db, self.limits = db, limits

    def _read(self, sql, params, maximum):
        rows = self.db.execute(sql, (*params, maximum + 1)).fetchall()
        if len(rows) > maximum:
            raise DomainError('RECOMMENDATION_LIMIT_EXCEEDED', 'Recommendation scope exceeds capture limits')
        return rows

    def capture(self, principal, query, domain_as_of):
        if query.work_code_id is not None and self.db.execute(
                'SELECT id FROM work_codes WHERE id=%s FOR SHARE',
                (query.work_code_id,)).fetchone() is None:
            raise DomainError('VALIDATION_FAILED', 'Unknown work code')
        employees = self._read('''SELECT e.id,left(e.employee_code,257) AS employee_code FROM employees e
            JOIN employee_sections es ON es.employee_id=e.id
            WHERE es.section_id=%s AND e.active AND e.on_shift AND e.role='executor'
            ORDER BY e.employee_code COLLATE "C",e.id LIMIT %s FOR SHARE OF e,es''',
            (query.section_id,), self.limits.max_candidates)
        if any(not row['employee_code'] or len(row['employee_code']) > 256 for row in employees):
            raise _unavailable()
        ids = [str(row['id']) for row in employees]
        if not ids:
            return employees, [], []
        workload = self._read('''SELECT id,executor_id,status,norm_minutes,due_at,updated_at
            FROM orders WHERE executor_id=ANY(%s::uuid[]) AND section_id=ANY(%s::uuid[])
            AND status=ANY(%s::text[]) ORDER BY id LIMIT %s FOR SHARE''',
            (ids, sorted(principal.section_ids), sorted(OUTSTANDING | AWAITING_REVIEW)),
            self.limits.max_workload_rows)
        # A closed order contributes exactly its final current submission and
        # human close decision, credited to the actual submitting employee.
        # Reassigned former attempts, AI-only scores, and disabled historical
        # actors never become evidence for a different live employee.
        # Lock mutable orders only. Immutable submissions/reviews need no locks
        # and the existing least-privilege profile intentionally denies UPDATE.
        history = self._read('''SELECT o.id AS order_id,s.id AS submission_id,
            s.submitted_by AS executor_id,s.submitted_at,s.work_code_id,s.done_late,
            r.id AS review_id,r.created_at AS reviewed_at,r.final_score
            FROM orders o JOIN submissions s ON s.id=o.current_submission_id
                AND s.order_id=o.id AND s.assignment_revision=o.assignment_revision
                AND s.submitted_by=o.executor_id
            JOIN reviews r ON r.submission_id=s.id AND r.decision='close'
            WHERE o.section_id=%s AND o.status='closed' AND s.submitted_by=ANY(%s::uuid[])
                AND r.created_at>=%s AND r.created_at<=%s AND s.submitted_at<=r.created_at
            ORDER BY r.created_at DESC,o.id LIMIT %s FOR SHARE OF o''',
            (query.section_id, ids, domain_as_of - timedelta(days=90), domain_as_of),
            self.limits.max_history_rows)
        return employees, workload, history


def build_recommendations(employees, workload, history, *, query, domain_as_of, limits):
    """Pure projection: counts are observed facts; absent quality is null, not 0."""
    work_by_employee, history_by_employee = defaultdict(list), defaultdict(list)
    for row in workload:
        work_by_employee[str(row['executor_id'])].append(row)
    for row in history:
        history_by_employee[str(row['executor_id'])].append(row)
    candidates = []
    for employee in employees:
        identifier = str(employee['id'])
        work = sorted(work_by_employee[identifier], key=lambda row: str(row['id']))
        past = sorted(history_by_employee[identifier],
                      key=lambda row: (-_instant(row['reviewed_at']).timestamp(), str(row['order_id'])))
        statuses = Counter(row['status'] for row in work)
        pending = [row for row in work if row['status'] in OUTSTANDING]
        active = sum(statuses[state] for state in ACTIVE)
        scores = [row['final_score'] for row in past if row['final_score'] is not None]
        matches = (sum(str(row['work_code_id']) == query.work_code_id for row in past)
                   if query.work_code_id is not None else None)
        on_time = sum(not row['done_late'] for row in past)
        reasons = ['ACTIVE_ON_SHIFT', 'SELECTED_SECTION_MEMBER',
                   'NO_VISIBLE_OUTSTANDING_ORDERS' if not pending else 'VISIBLE_OUTSTANDING_ORDERS']
        if active:
            reasons.append('ACTIVE_ASSIGNMENTS')
        if not past:
            reasons.append('NO_CLOSED_HISTORY')
        if not scores:
            reasons.append('HUMAN_SCORE_UNKNOWN')
        reasons.append('WORK_CODE_NOT_SELECTED' if matches is None else
                       'MATCHING_WORK_CODE_HISTORY' if matches else 'NO_MATCHING_WORK_CODE_HISTORY')
        candidate = {
            'executor_id': identifier, 'employee_code': employee['employee_code'], 'rank': 0,
            'on_shift': True,
            'workload': {
                'outstanding_count': len(pending), 'active_count': active,
                'queued_count': statuses['queued'],
                'awaiting_review_count': sum(statuses[state] for state in AWAITING_REVIEW),
                'overdue_count': sum(_instant(row['due_at']) < domain_as_of for row in pending),
                'norm_minutes_total': sum(row['norm_minutes'] for row in pending),
                'status_counts': {state: statuses[state] for state in sorted(OUTSTANDING | AWAITING_REVIEW)},
                'scope': 'current_master_authorized_sections',
                'evidence': [{'order_id': str(row['id']), 'status': row['status'],
                              'due_at': _instant(row['due_at']).isoformat(),
                              'updated_at': _instant(row['updated_at']).isoformat()}
                             for row in work[:limits.evidence_per_candidate]],
                'evidence_truncated': len(work) > limits.evidence_per_candidate,
            },
            'history': {
                'status': 'observed' if past else 'no_observations',
                'window_start': (domain_as_of - timedelta(days=90)).isoformat(),
                'window_end': domain_as_of.isoformat(), 'closed_count': len(past),
                'matching_work_code_count': matches,
                'human_score_mean': round(sum(scores) / len(scores), 2) if scores else None,
                'human_score_count': len(scores),
                'on_time_rate': round(on_time / len(past), 4) if past else None,
                'on_time_count': on_time,
                'latest_closed_at': _instant(past[0]['reviewed_at']).isoformat() if past else None,
                'evidence': [{'order_id': str(row['order_id']), 'submission_id': str(row['submission_id']),
                              'review_id': str(row['review_id']),
                              'submitted_at': _instant(row['submitted_at']).isoformat(),
                              'reviewed_at': _instant(row['reviewed_at']).isoformat(),
                              'work_code_id': str(row['work_code_id']) if row['work_code_id'] is not None else None,
                              'final_score': row['final_score'], 'done_late': row['done_late']}
                             for row in past[:limits.evidence_per_candidate]],
                'evidence_truncated': len(past) > limits.evidence_per_candidate,
            },
            'reason_codes': reasons,
        }
        candidates.append(candidate)
    def substantive(candidate):
        return (candidate['workload']['outstanding_count'], candidate['workload']['active_count'],
                -(candidate['history']['matching_work_code_count'] or 0))
    candidates.sort(key=lambda item: (*substantive(item), item['employee_code'].encode('utf-8'), item['executor_id']))
    previous, rank = None, 0
    for candidate in candidates:
        key = substantive(candidate)
        if key != previous:
            rank += 1
            previous = key
        candidate['rank'] = rank
    return candidates[:query.limit]


class AssigneeRecommendationService:
    def __init__(self, connect, *, domain_clock, synthetic, real_clock=None, limits=None):
        if type(synthetic) is not bool:
            raise ValueError('Source provenance must be explicit server configuration')
        if limits is not None and not isinstance(limits, RecommendationLimits):
            raise ValueError('Typed recommendation limits required')
        self.connect, self.domain_clock, self.synthetic = connect, domain_clock, synthetic
        self.real_clock, self.limits = real_clock or SystemRealClock(), limits or RecommendationLimits()

    def _connection(self):
        from psycopg.pq import TransactionStatus
        from psycopg.rows import dict_row
        db = self.connect()
        if not db.autocommit or db.info.transaction_status != TransactionStatus.IDLE:
            db.close()
            raise _unavailable()
        db.row_factory = dict_row
        return db

    def _auth(self, db, handle):
        return authenticate_session(handle, sessions=PostgresSessions(db),
                                    principals=PostgresPrincipals(db), real_clock=self.real_clock)

    def recommend(self, query, *, session_handle, project=None):
        with self._connection() as db:
            with db.transaction():
                db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                db.execute("SET LOCAL statement_timeout = '5000ms'")
                db.execute("SET LOCAL lock_timeout = '1000ms'")
                db.execute("SET LOCAL idle_in_transaction_session_timeout = '10000ms'")
                captured_at = _instant(self.real_clock.now())
                context = self._auth(db, session_handle)
                principal = context.principal
                if principal.role != Role.MASTER or not principal.active:
                    raise AccessDenied()
                query = parse_query(query)
                if query.section_id not in principal.section_ids:
                    raise AccessDenied()
                if len(principal.section_ids) > self.limits.max_sections:
                    raise DomainError('RECOMMENDATION_LIMIT_EXCEEDED', 'Recommendation scope exceeds capture limits')
                domain_as_of = _instant(self.domain_clock.now())
                employees, workload, history = AssigneeRepository(db, self.limits).capture(principal, query, domain_as_of)
                candidates = build_recommendations(employees, workload, history, query=query,
                    domain_as_of=domain_as_of, limits=self.limits)
                expires_at = min(captured_at + timedelta(seconds=30), _instant(context.session.expires_at))
                limitations = ['DETERMINISTIC_RULES_NOT_AI', 'QUALIFICATIONS_UNVERIFIED',
                    'WORKLOAD_VISIBLE_SCOPE_ONLY', 'WORKLOAD_NORM_NOT_REMAINING',
                    'SNAPSHOT_NOT_RESERVATION', 'HISTORICAL_OBSERVATIONS_NOT_SKILL']
                if self.synthetic:
                    limitations.append('SYNTHETIC_DATA')
                if len(employees) == 1:
                    limitations.append('ONLY_ONE_ELIGIBLE_EXECUTOR')
                if not employees:
                    limitations.append('NO_ELIGIBLE_EXECUTORS')
                result = {'schema_version': '1', 'mode': 'rules_baseline', 'model': None,
                    'model_status': 'disabled_for_purpose', 'advisory_only': True, 'synthetic': self.synthetic,
                    'section_id': query.section_id, 'work_code_id': query.work_code_id,
                    'as_of': captured_at.isoformat(), 'domain_as_of': domain_as_of.isoformat(),
                    'expires_at': expires_at.isoformat(), 'eligible_count': len(employees),
                    'returned_count': len(candidates), 'candidates': candidates,
                    'limitations': limitations, 'ranking_policy': RANKING_POLICY}
                # Serialize while authority rows remain locked; an expiry during
                # rendering must not escape in a preconstructed success response.
                if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8')) > MAX_RESPONSE_BYTES:
                    raise DomainError('RECOMMENDATION_LIMIT_EXCEEDED', 'Recommendation output exceeds capture limits')
                rendered = project(result) if project is not None else result
                refreshed = self._auth(db, session_handle)
                if refreshed.principal != principal:
                    raise AccessDenied()
                if _instant(self.real_clock.now()) >= expires_at:
                    raise _unavailable()
        return rendered
