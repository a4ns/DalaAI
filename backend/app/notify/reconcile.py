"""Durable reconciliation of existing pure deadline plans, with no external I/O."""
from dataclasses import dataclass
from uuid import UUID

from app.core.auth_boundary import SystemRealClock
from app.persistence.postgres import PostgresRepository, sid
from app.scheduler import SchedulePolicy, ScheduleSnapshot
from app.scheduler.clocks import utc
from app.scheduler.models import ACTIVE_STATUSES
from app.scheduler.planner import plan_due_jobs


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    order_id: str
    state: str
    due_intents: int = 0  # planned missing keys, not a delivery/phone counter


@dataclass(frozen=True, slots=True)
class ReconcilePage:
    results: tuple[ReconcileResult, ...]
    next_after_id: str | None


class DeadlineReconciler:
    """One current order per transaction; restart re-derives all due work.

    No new scheduler policy or threshold is introduced. The existing pure planner
    owns comparisons and cycle identities. Every insertion uses the existing
    outbox unique key and repository. CommandService still creates immediate
    issue/reassignment jobs atomically with its command receipt.
    """
    def __init__(self, connect, *, channel, domain_clock, real_clock=None, policy=None):
        self.connect, self.channel = connect, channel
        self.domain_clock, self.real_clock = domain_clock, real_clock or SystemRealClock()
        self.policy = policy or SchedulePolicy(channel=channel)
        if channel not in {'web_push','telegram','synthetic'} or self.policy.channel != channel:
            raise ValueError('Explicit matching configured channel required')
        if self.policy.manager_escalation_after is not None:
            raise ValueError('Manager escalation recipient policy is not configured in this slice')

    def _connection(self):
        from psycopg.rows import dict_row
        from psycopg.pq import TransactionStatus
        db = self.connect()
        if not db.autocommit or db.info.transaction_status != TransactionStatus.IDLE:
            db.close()
            raise ValueError('DeadlineReconciler requires a fresh idle autocommit connection')
        db.row_factory = dict_row
        return db

    def reconcile_order(self, order_id):
        order_id = str(UUID(order_id))
        with self._connection() as db:
            with db.transaction():
                # A busy order is retried next scan, not read stale or blocked
                # behind a provider. We hold no delivery row before this lock.
                row = db.execute('SELECT id FROM orders WHERE id=%s FOR UPDATE SKIP LOCKED',
                                 (order_id,)).fetchone()
                if row is None:
                    return ReconcileResult(order_id,'unavailable_or_busy')
                repo = PostgresRepository(db)
                order = repo.load_order(order_id)
                if order.status not in ACTIVE_STATUSES:
                    return ReconcileResult(order_id,'inactive')
                # Lock current recipients/scope in canonical ID order. Their
                # current permission must exist; do not schedule for former staff.
                if order.created_by == order.assignment.executor_id:
                    return ReconcileResult(order_id,'recipient_unavailable')
                roles = {order.created_by:'master',order.assignment.executor_id:'executor'}
                for recipient in sorted(roles):
                    employee = db.execute('SELECT role,active FROM employees WHERE id=%s FOR SHARE',
                                          (recipient,)).fetchone()
                    member = db.execute('''SELECT employee_id FROM employee_sections
                        WHERE employee_id=%s AND section_id=%s FOR SHARE''',
                        (recipient,order.section_id)).fetchone()
                    if employee is None or not employee['active'] or employee['role'] != roles[recipient] or member is None:
                        return ReconcileResult(order_id,'recipient_unavailable')
                event = db.execute('''SELECT occurred_at FROM order_events WHERE order_id=%s
                    AND assignment_revision=%s AND kind IN ('order.created','order.reassigned')
                    ORDER BY sequence DESC LIMIT 1''',(order.id,order.assignment_revision)).fetchone()
                if event is None:
                    return ReconcileResult(order_id,'assignment_clock_unavailable')
                snapshot = ScheduleSnapshot(order.id,order.assignment_revision,order.scheduling_revision,
                    order.status.value,order.priority.value,order.assignment.executor_id,order.created_by,
                    order.due_at,event['occurred_at'],order.current_submission_id)
                rows = db.execute('''SELECT order_id,assignment_revision,scheduling_revision,kind,
                    recipient_id,channel,bucket FROM delivery_jobs WHERE order_id=%s
                    AND assignment_revision=%s AND scheduling_revision=%s AND channel=%s''',
                    (order.id,order.assignment_revision,order.scheduling_revision,self.channel)).fetchall()
                known = frozenset((sid(r['order_id']),r['assignment_revision'],r['scheduling_revision'],
                    r['kind'],sid(r['recipient_id']),r['channel'],r['bucket']) for r in rows)
                # Read real/domain clocks after all potential lock waits. Domain
                # jumps affect threshold planning only, never retry/lease expiry.
                domain_now, real_now = utc(self.domain_clock.now()), utc(self.real_clock.now())
                intents = plan_due_jobs(snapshot,domain_now=domain_now,policy=self.policy,known_keys=known)
                for intent in intents:
                    repo.delivery_job(order=order,kind=intent.kind.value,recipient_id=intent.recipient_id,
                        channel=intent.channel,bucket=intent.bucket,due_at=intent.due_at,
                        real_now=real_now,job_id=intent.id)
            return ReconcileResult(order_id,'reconciled',len(intents))

    def scan_once(self, *, limit=100, after_id=None):
        if type(limit) is not int or not 1<=limit<=1000:
            raise ValueError('Reconciliation batch limit must be in 1..1000')
        if after_id is not None:
            after_id = str(UUID(after_id))
        with self._connection() as db:
            # This selection acquires no aggregate lock. Every chosen ID is
            # reloaded/checked under its own order lock before any insertion.
            rows = db.execute('''SELECT id FROM orders WHERE status=ANY(%s::text[])
                AND (%s::uuid IS NULL OR id>%s::uuid) ORDER BY id LIMIT %s''',
                (sorted(ACTIVE_STATUSES),after_id,after_id,limit+1)).fetchall()
        page = rows[:limit]
        results = tuple(self.reconcile_order(sid(row['id'])) for row in page)
        next_after = sid(page[-1]['id']) if len(rows)>limit else None
        return ReconcilePage(results,next_after)
