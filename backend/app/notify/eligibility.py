"""Reuse existing scheduler rules; current submission/review notifications are separate."""
from app.scheduler import ScheduleSnapshot
from app.scheduler.models import IntentState, JobIntent, JobKind
from app.scheduler.planner import check_intent
from app.persistence.postgres import sid


def check_delivery(db, envelope, order, *, domain_now, policy):
    """Caller holds order. References and recipients come from the current DB."""
    e = envelope
    if (e.order_id != order.id or e.assignment_revision != order.assignment_revision
            or e.scheduling_revision != order.scheduling_revision or e.channel != policy.channel):
        return IntentState.STALE
    if e.kind == 'submission_ready':
        if (order.status != 'ai_review' or e.bucket != order.current_submission_id
                or e.recipient_id != order.created_by):
            return IntentState.STALE
        row = db.execute('SELECT submitted_at FROM submissions WHERE id=%s',(e.bucket,)).fetchone()
        if row is None or row['submitted_at'] != e.due_at:
            return IntentState.STALE
        return IntentState.READY if domain_now >= e.due_at else IntentState.WAIT_DOMAIN
    if e.kind == 'review_result':
        if (order.status not in {'closed','rework','in_progress','paused'}
                or e.bucket != order.current_submission_id or e.recipient_id != order.assignment.executor_id):
            return IntentState.STALE
        row = db.execute('SELECT created_at FROM reviews WHERE submission_id=%s',(e.bucket,)).fetchone()
        if row is None or row['created_at'] != e.due_at:
            return IntentState.STALE
        return IntentState.READY if domain_now >= e.due_at else IntentState.WAIT_DOMAIN
    row = db.execute("""SELECT occurred_at FROM order_events WHERE order_id=%s
        AND assignment_revision=%s AND kind IN ('order.created','order.reassigned')
        ORDER BY sequence DESC LIMIT 1""",(order.id,order.assignment_revision)).fetchone()
    if row is None:
        return IntentState.STALE  # Never reconstruct reassignment time from original issue.
    snapshot = ScheduleSnapshot(order.id,order.assignment_revision,order.scheduling_revision,
        order.status.value,order.priority.value,order.assignment.executor_id,order.created_by,
        order.due_at,row['occurred_at'],order.current_submission_id)
    intent = JobIntent(e.order_id,e.assignment_revision,e.scheduling_revision,JobKind(e.kind),
                       e.recipient_id,e.channel,e.bucket,e.due_at)
    return check_intent(intent,snapshot,domain_now=domain_now,policy=policy)


def recipient_is_current(db, envelope, order):
    if envelope.recipient_id == order.assignment.executor_id:
        expected_role = 'executor'
    elif envelope.recipient_id == order.created_by:
        expected_role = 'master'
    else:
        # Manager escalation policy is intentionally not activated in this slice.
        return False
    row = db.execute('SELECT id,role,active FROM employees WHERE id=%s FOR SHARE',
                     (envelope.recipient_id,)).fetchone()
    member = db.execute('''SELECT employee_id FROM employee_sections
        WHERE employee_id=%s AND section_id=%s FOR SHARE''',
        (envelope.recipient_id,order.section_id)).fetchone()
    return row is not None and row['active'] and row['role'] == expected_role and member is not None
