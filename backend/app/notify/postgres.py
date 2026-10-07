"""Lease and dispatch-attempt persistence. Network calls never run here."""
from app.persistence.postgres import sid
from .models import DeliveryClaim, DeliveryEnvelope


class DeliveryRepository:
    def __init__(self, db):
        self.db = db

    def claim(self, *, real_now, domain_now, lease_until, token, channel, max_attempts):
        row = self.db.execute("""SELECT * FROM delivery_jobs WHERE channel=%s AND
            ((state IN ('pending','retry') AND next_attempt_at<=%s AND due_at<=%s)
              OR (state='sending' AND (lease_until IS NULL OR lease_until<=%s)))
            ORDER BY next_attempt_at,id FOR UPDATE SKIP LOCKED LIMIT 1""",
            (channel,real_now,domain_now,real_now)).fetchone()
        if row is None:
            return None
        # A prior process may have sent after committing intent, including old
        # pre-migration sending rows without a token. Never blindly redispatch.
        dispatched = row['state'] == 'sending' and (row['lease_token'] is None or
            self.db.execute('SELECT lease_token FROM delivery_dispatches WHERE lease_token=%s',
                            (row['lease_token'],)).fetchone() is not None)
        if dispatched or row['attempts'] >= max_attempts:
            code = 'DELIVERY_OUTCOME_UNKNOWN' if dispatched else 'ATTEMPTS_EXHAUSTED'
            self.db.execute("""UPDATE delivery_jobs SET state='failed',lease_until=NULL,
                lease_token=NULL,last_error_code=%s WHERE id=%s""",(code,row['id']))
            return code
        row = self.db.execute("""UPDATE delivery_jobs SET state='sending',attempts=attempts+1,
            lease_until=%s,lease_token=%s,last_error_code=NULL WHERE id=%s RETURNING *""",
            (lease_until,token,row['id'])).fetchone()
        envelope = DeliveryEnvelope(sid(row['id']),sid(row['order_id']),sid(row['recipient_id']),
            row['kind'],row['assignment_revision'],row['scheduling_revision'],row['bucket'],
            row['channel'],due_at=row['due_at'])
        return DeliveryClaim(envelope,row['attempts'],sid(row['lease_token']),row['lease_until'])

    def owns(self, claim, *, now, lock=False):
        e = claim.envelope
        return self.db.execute("""SELECT id FROM delivery_jobs WHERE id=%s AND state='sending'
            AND lease_token=%s AND attempts=%s AND lease_until>%s
            AND order_id=%s AND assignment_revision=%s AND scheduling_revision=%s
            AND recipient_id=%s AND kind=%s AND channel=%s AND bucket=%s AND due_at=%s"""
            + (' FOR UPDATE' if lock else ''),
            (e.job_id,claim.lease_token,claim.attempts,now,e.order_id,e.assignment_revision,
             e.scheduling_revision,e.recipient_id,e.kind,e.channel,e.bucket,e.due_at)).fetchone() is not None

    def started(self, claim):
        return self.db.execute('SELECT lease_token FROM delivery_dispatches WHERE lease_token=%s',
                               (claim.lease_token,)).fetchone() is not None

    def begin_dispatch(self, claim, *, now, lease_until):
        self.db.execute("""UPDATE delivery_jobs SET lease_until=%s WHERE id=%s""",
                        (lease_until,claim.envelope.job_id))
        self.db.execute("""INSERT INTO delivery_dispatches(lease_token,job_id,attempt_number,started_at)
            VALUES (%s,%s,%s,%s)""",(claim.lease_token,claim.envelope.job_id,claim.attempts,now))

    def release(self, claim, *, state, code, now, next_attempt_at=None, waiting=False):
        return self.db.execute("""UPDATE delivery_jobs SET state=%s,last_error_code=%s,
            lease_token=NULL,lease_until=NULL,next_attempt_at=%s,attempts=attempts-%s
            WHERE id=%s AND state='sending' AND lease_token=%s AND attempts=%s AND lease_until>%s""",
            (state,code,next_attempt_at or now,1 if waiting else 0,claim.envelope.job_id,
             claim.lease_token,claim.attempts,now)).rowcount == 1

    def record_outcome(self, claim, outcome, *, now):
        # Observed response belongs to an already committed intent. Late results
        # remain audit evidence even when the current job was cancelled/reclaimed.
        return self.db.execute("""INSERT INTO delivery_dispatch_results
            (lease_token,outcome,error_code,provider_receipt,retry_after_seconds,observed_at)
            SELECT lease_token,%s,%s,%s,%s,%s FROM delivery_dispatches
            WHERE lease_token=%s AND job_id=%s AND attempt_number=%s
            ON CONFLICT (lease_token) DO NOTHING RETURNING lease_token""",
            (outcome.state,outcome.code,outcome.receipt,outcome.retry_after_seconds,now,
             claim.lease_token,claim.envelope.job_id,claim.attempts)).fetchone() is not None

    def finish(self, claim, outcome, *, now, next_attempt_at, state):
        return self.db.execute("""UPDATE delivery_jobs SET state=%s,last_error_code=%s,
            provider_receipt=%s,sent_at=%s,lease_token=NULL,lease_until=NULL,next_attempt_at=%s
            WHERE id=%s AND state='sending' AND lease_token=%s AND attempts=%s AND lease_until>%s""",
            (state,None if state=='provider_accepted' else outcome.code,outcome.receipt,
             now if state=='provider_accepted' else None,
             next_attempt_at,claim.envelope.job_id,claim.lease_token,claim.attempts,now)).rowcount == 1
