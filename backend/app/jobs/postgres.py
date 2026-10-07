"""SQL for ai_jobs, using short claim and order-first result transactions."""
from app.persistence.postgres import jsonb, sid
from .models import Claim, assessment_event


class JobRepository:
    def __init__(self, db):
        self.db = db

    def claim(self, *, now, lease_until, token, max_attempts):
        row = self.db.execute("""SELECT * FROM ai_jobs
            WHERE ((state IN ('pending','retry') AND next_attempt_at<=%s)
                OR (state='running' AND (lease_until IS NULL OR lease_until<=%s)))
            ORDER BY next_attempt_at,id FOR UPDATE SKIP LOCKED LIMIT 1""", (now, now)).fetchone()
        if row is None:
            return None
        if row['attempts'] >= max_attempts:
            self.db.execute("""UPDATE ai_jobs SET state='failed',lease_token=NULL,lease_until=NULL,
                last_error_code='ATTEMPTS_EXHAUSTED' WHERE id=%s""", (row['id'],))
            return False
        row = self.db.execute("""UPDATE ai_jobs SET state='running',attempts=attempts+1,
            lease_until=%s,lease_token=%s,last_error_code=NULL WHERE id=%s RETURNING *""",
            (lease_until, token, row['id'])).fetchone()
        return Claim(sid(row['id']), sid(row['submission_id']), row['assignment_revision'],
                     row['attempts'], sid(row['lease_token']), row['lease_until'])

    def owns(self, claim, *, now, lock=False):
        # This lock is acquired only AFTER order/evidence locks, never before.
        suffix = ' FOR UPDATE' if lock else ''
        return self.db.execute("""SELECT id FROM ai_jobs WHERE id=%s AND submission_id=%s
            AND assignment_revision=%s AND state='running' AND attempts=%s AND lease_token=%s
            AND lease_until>%s""" + suffix,
            (claim.id, claim.submission_id, claim.assignment_revision, claim.attempts,
             claim.lease_token, now)).fetchone() is not None

    def finish(self, claim, *, now):
        return self.db.execute("""UPDATE ai_jobs SET state='done',lease_token=NULL,lease_until=NULL,
            last_error_code=NULL WHERE id=%s AND state='running' AND attempts=%s
            AND lease_token=%s AND lease_until>%s""",
            (claim.id, claim.attempts, claim.lease_token, now)).rowcount == 1

    def fail(self, claim, *, now, next_attempt_at, terminal, code):
        # No order read/lock in this independent failure transaction.
        return self.db.execute("""UPDATE ai_jobs SET state=%s,next_attempt_at=%s,
            lease_token=NULL,lease_until=NULL,last_error_code=%s WHERE id=%s
            AND state='running' AND attempts=%s AND lease_token=%s AND lease_until>%s""",
            ('failed' if terminal else 'retry', next_attempt_at, code, claim.id,
             claim.attempts, claim.lease_token, now)).rowcount == 1

    def persist_assessment(self, assessment):
        a = assessment
        # Mode, score and model are fixed by the trusted rules-only worker.
        self.db.execute("""INSERT INTO ai_assessments
            (id,submission_id,assignment_revision,mode,schema_version,model,model_version,
             duration_ms,recommendation,score,reasons,evidence_ids,fallback_reason,stale,created_at)
            VALUES (%s,%s,%s,'rules_fallback','1',NULL,NULL,%s,%s,NULL,%s,%s,%s,%s,%s)""",
            (a.id,a.submission_id,a.assignment_revision,a.duration_ms,a.recommendation,
             jsonb(list(a.reasons)),jsonb(list(a.evidence_ids)),a.fallback_reason,a.stale,a.created_at))

    def publish_current(self, order, assessment, *, domain_now, real_now):
        # The caller holds order FOR UPDATE. Never change production status.
        count = self.db.execute("""UPDATE orders SET version=version+1,updated_at=%s
            WHERE id=%s AND version=%s AND assignment_revision=%s
            AND current_submission_id=%s AND status='ai_review'""",
            (domain_now,order.id,order.version,assessment.assignment_revision,assessment.submission_id)).rowcount
        if count != 1:
            raise RuntimeError('Assessment current-order fence failed')
        sequence = self.db.execute("SELECT COALESCE(MAX(sequence),0)+1 AS n FROM order_events WHERE order_id=%s",
                                   (order.id,)).fetchone()['n']
        event = assessment_event(order, assessment, sequence=sequence,
                                 domain_now=domain_now, real_now=real_now)
        event['details'] = jsonb(event['details'])
        self.db.execute("""INSERT INTO order_events
            (id,order_id,sequence,order_version,assignment_revision,scheduling_revision,kind,reason,
             details,actor_id,operation_id,from_status,to_status,submission_id,occurred_at,recorded_at)
            VALUES (%(id)s,%(order_id)s,%(sequence)s,%(order_version)s,%(assignment_revision)s,
                %(scheduling_revision)s,%(kind)s,%(reason)s,%(details)s,%(actor_id)s,%(operation_id)s,
                %(from_status)s,%(to_status)s,%(submission_id)s,%(occurred_at)s,%(recorded_at)s)""", event)
