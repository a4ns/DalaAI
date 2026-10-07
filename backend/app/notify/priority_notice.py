"""Preserve one unsent assignment notice across an explicit priority edit."""
from app.persistence.postgres import sid
from app.scheduler.models import JobIntent, JobKind, UNACCEPTED_STATUSES

SAFE_UNSTARTED_CODES = frozenset({'DELIVERY_PREPARE_ERROR','WAIT_DOMAIN','NOTICE_RESCHEDULED_UNSENT'})


def safe_to_replace(rows, dispatch_outcomes):
    """Conservative assignment-level dedupe; accepted/uncertain is never reset.

    dispatch_outcomes maps job UUID to every immutable dispatch's normalized
    outcome; None means committed intent with no observed response. This is
    server-owned evidence only. Neither user priority nor retry can erase it.
    """
    for row in rows:
        outcomes = dispatch_outcomes.get(sid(row['id']),())
        if row['state'] in {'provider_accepted','synthetic_recorded','failed'}:
            return False
        if row['state'] == 'sending' and row['lease_token'] is None:
            return False  # pre-token in-flight state cannot prove an unsent request
        if any(outcome not in {'retryable','permanent_failure'} for outcome in outcomes):
            return False  # includes accepted, ambiguous and unfinished intent
        if (row['attempts'] > 0 and not outcomes and row['lease_token'] is None
                and row['last_error_code'] not in SAFE_UNSTARTED_CODES):
            # Pre-migration or otherwise unexplained attempted delivery is not
            # proof of an unsent request. Keep it quarantined.
            return False
    return True


def reschedule_priority_notice(repo, order, *, channel, real_now):
    """Call BEFORE invalidate_jobs, only for CHANGE_PRIORITY under order lock.

    The new row is created in the command receipt transaction. Old rows/audit
    stay intact and normal invalidation cancels their old scheduling revision.
    This function never calls a provider or changes production status/version.
    """
    if order.status not in UNACCEPTED_STATUSES:
        return False
    db = repo.db
    rows = db.execute('''SELECT id,state,attempts,lease_token,last_error_code,next_attempt_at
        FROM delivery_jobs WHERE order_id=%s AND assignment_revision=%s AND kind='new_order'
        AND recipient_id=%s AND channel=%s ORDER BY id FOR UPDATE''',
        (order.id,order.assignment_revision,order.assignment.executor_id,channel)).fetchall()
    if rows:
        outcomes = db.execute('''SELECT d.job_id,r.outcome FROM delivery_dispatches d
            LEFT JOIN delivery_dispatch_results r ON r.lease_token=d.lease_token
            WHERE d.job_id=ANY(%s::uuid[])''',([sid(row['id']) for row in rows],)).fetchall()
    else:
        outcomes = ()
    by_job = {}
    for result in outcomes:
        by_job.setdefault(sid(result['job_id']),[]).append(result['outcome'])
    # A pre-token in-flight row would otherwise become merely 'cancelled'
    # during revision invalidation and lose its uncertainty marker. Quarantine
    # it durably so a second priority edit cannot mistake it for an unsent row.
    legacy = [sid(row['id']) for row in rows
              if row['state'] == 'sending' and row['lease_token'] is None]
    if legacy:
        db.execute("""UPDATE delivery_jobs SET state='failed',last_error_code='DELIVERY_OUTCOME_UNKNOWN',
            lease_until=NULL WHERE id=ANY(%s::uuid[])""",(legacy,))
    if not safe_to_replace(rows,by_job):
        return False
    event = db.execute('''SELECT occurred_at FROM order_events WHERE order_id=%s
        AND assignment_revision=%s AND kind IN ('order.created','order.reassigned')
        ORDER BY sequence DESC LIMIT 1''',(order.id,order.assignment_revision)).fetchone()
    if event is None:
        # Missing trusted anchor cannot become a fabricated immediate notice.
        return False
    intent = JobIntent(order.id,order.assignment_revision,order.scheduling_revision,
        JobKind.NEW_ORDER,order.assignment.executor_id,channel,'initial',event['occurred_at'])
    repo.delivery_job(order=order,kind=intent.kind.value,recipient_id=intent.recipient_id,
        channel=intent.channel,bucket=intent.bucket,due_at=intent.due_at,
        real_now=real_now,job_id=intent.id)
    # A priority edit must not evade a provider Retry-After or reset the logical
    # assignment-notice attempt budget. Durable key still dedupes command retry.
    not_before = max([real_now]+[row['next_attempt_at'] for row in rows])
    attempts = max([0]+[row['attempts'] for row in rows])
    db.execute('''UPDATE delivery_jobs SET next_attempt_at=GREATEST(next_attempt_at,%s),
        attempts=GREATEST(attempts,%s),last_error_code='NOTICE_RESCHEDULED_UNSENT'
        WHERE id=%s AND state='pending' ''',(not_before,attempts,intent.id))
    return True
