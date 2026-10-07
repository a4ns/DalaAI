"""Small psycopg3 repositories. Every instance belongs to one command transaction."""
from datetime import datetime
from hashlib import sha256
from uuid import UUID, uuid5

from app.ai.models import PhotoEvidence
from app.core.auth_boundary import SessionRecord
from app.core.auth_policy import (AccessDenied, Principal, Role, OrderScope,
    StagedPhotoScope, require_staged_attachment, require_create_order, require_order_access, OrderAction)
from app.orders.models import (Assignment, Completeness, DomainError, MaterialUse,
    MissingEvidence, Order, OrderType, Priority, Status, Submission, SubmitPayload)
from .canonical import canonical_json


def jsonb(value):
    from psycopg.types.json import Jsonb
    return Jsonb(value, dumps=canonical_json)


def sid(value):
    return None if value is None else str(value)


def scope(order):
    return OrderScope(order.id, order.section_id, order.assignment.executor_id,
                      order.assignment_revision)


class PostgresSessions:
    def __init__(self, connection):
        self.db = connection

    def lookup(self, session_handle):
        row = self.db.execute("""SELECT employee_id,created_at,expires_at,csrf_token,revoked_at
            FROM auth_sessions WHERE token_hash=%s FOR SHARE""",
            (sha256(session_handle.encode("utf-8")).hexdigest(),)).fetchone()
        if row is None:
            return None
        return SessionRecord(sid(row["employee_id"]), row["created_at"], row["expires_at"],
                             row["csrf_token"], row["revoked_at"] is not None)


class PostgresPrincipals:
    def __init__(self, connection):
        self.db = connection

    def lookup(self, user_id):
        row = self.db.execute("SELECT id,role,active FROM employees WHERE id=%s FOR SHARE",
                              (user_id,)).fetchone()
        if row is None:
            return None
        sections = self.db.execute("""SELECT section_id FROM employee_sections
            WHERE employee_id=%s ORDER BY section_id FOR SHARE""", (user_id,)).fetchall()
        return Principal(sid(row["id"]), Role(row["role"]),
                         frozenset(sid(r["section_id"]) for r in sections), row["active"])


class PostgresRepository:
    def __init__(self, connection):
        self.db = connection

    def load_order(self, order_id, *, lock=False, share=False):
        suffix = " FOR UPDATE" if lock else " FOR SHARE" if share else ""
        row = self.db.execute("SELECT * FROM orders WHERE id=%s" + suffix,
                              (order_id,)).fetchone()
        if row is None:
            return None
        photos = self.db.execute("""SELECT id FROM photos WHERE order_id=%s AND purpose='before'
            AND attached_at IS NOT NULL ORDER BY id""", (order_id,)).fetchall()
        return Order(sid(row["id"]), str(row["number"]), row["version"], row["assignment_revision"],
            row["scheduling_revision"], Status(row["status"]), OrderType(row["type"]),
            row["description"], sid(row["section_id"]), sid(row["equipment_id"]),
            Assignment(sid(row["executor_id"]), sid(row["brigade_id"])), sid(row["created_by"]),
            row["issued_at"], row["due_at"], row["norm_minutes"], Priority(row["priority"]),
            row["comment"], tuple(sid(r["id"]) for r in photos), sid(row["current_submission_id"]),
            row["updated_at"])

    def load_submission(self, submission_id):
        row = self.db.execute("SELECT * FROM submissions WHERE id=%s", (submission_id,)).fetchone()
        if row is None:
            return None
        materials = self.db.execute("""SELECT material_id,quantity FROM material_writeoffs
            WHERE submission_id=%s ORDER BY material_id""", (submission_id,)).fetchall()
        payload = SubmitPayload(row["work_description"], sid(row["work_code_id"]),
            tuple(MaterialUse(sid(r["material_id"]), r["quantity"]) for r in materials),
            tuple(sid(photo_id) for photo_id in row["after_photo_ids"]), row["comment"])
        return Submission(sid(row["id"]), sid(row["order_id"]), row["assignment_revision"],
            row["attempt_number"], sid(row["submitted_by"]), row["submitted_at"], row["done_late"],
            payload, None if row["completeness"] is None else Completeness(row["completeness"]),
            tuple(MissingEvidence(item) for item in row["missing_evidence"]))

    def receipt(self, actor_id, operation_id):
        return self.db.execute("""SELECT * FROM operation_receipts
            WHERE actor_id=%s AND operation_id=%s""", (actor_id, operation_id)).fetchone()

    def reserve(self, actor_id, operation_id, digest, real_now):
        # READ COMMITTED: an INSERT loser waits for the winner, then a NEW SELECT
        # sees the committed receipt. A rolled-back winner permits our INSERT.
        return self.db.execute("""INSERT INTO operation_receipts
            (actor_id,operation_id,canonical_hash,resource_kind,created_at)
            VALUES (%s,%s,%s,'order',%s) ON CONFLICT (actor_id,operation_id) DO NOTHING
            RETURNING actor_id""", (actor_id, operation_id, digest, real_now)).fetchone() is not None

    def finalize_receipt(self, actor_id, operation_id, order_id, status, body, real_now):
        count = self.db.execute("""UPDATE operation_receipts SET resource_id=%s,response_status=%s,
            response_body=%s,committed_at=%s WHERE actor_id=%s AND operation_id=%s
            AND committed_at IS NULL""", (order_id, status, jsonb(body), real_now,
                                          actor_id, operation_id)).rowcount
        if count != 1:
            raise RuntimeError("Receipt reservation was not owned")

    def allocate_number(self):
        row = self.db.execute("SELECT nextval(pg_get_serial_sequence('orders','number')) AS n").fetchone()
        return str(row["n"])

    def next_attempt(self, order):
        return self.db.execute("""SELECT COALESCE(MAX(attempt_number),0)+1 AS n
            FROM submissions WHERE order_id=%s AND assignment_revision=%s""",
            (order.id, order.assignment_revision)).fetchone()["n"]

    def persist_order(self, plan):
        o = plan.order
        values = (o.version, o.assignment_revision, o.scheduling_revision, o.status.value,
            o.type.value, o.description, o.section_id, o.equipment_id, o.assignment.executor_id,
            o.assignment.brigade_id, o.created_by, o.issued_at, o.due_at, o.norm_minutes,
            o.priority.value, o.comment, o.current_submission_id, o.updated_at)
        if plan.expected_version == 0:
            self.db.execute("""INSERT INTO orders
                (id,number,version,assignment_revision,scheduling_revision,status,type,description,
                 section_id,equipment_id,executor_id,brigade_id,created_by,issued_at,due_at,
                 norm_minutes,priority,comment,current_submission_id,updated_at)
                OVERRIDING SYSTEM VALUE VALUES
                (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (o.id, int(o.number), *values))
        else:
            count = self.db.execute("""UPDATE orders SET version=%s,assignment_revision=%s,
                scheduling_revision=%s,status=%s,type=%s,description=%s,section_id=%s,
                equipment_id=%s,executor_id=%s,brigade_id=%s,created_by=%s,issued_at=%s,
                due_at=%s,norm_minutes=%s,priority=%s,comment=%s,current_submission_id=%s,updated_at=%s
                WHERE id=%s AND version=%s""", (*values, o.id, plan.expected_version)).rowcount
            if count != 1:
                raise DomainError("VERSION_CONFLICT", "Order changed; refresh before a new action")

    def persist_submission(self, sub):
        p = sub.payload
        self.db.execute("""INSERT INTO submissions
            (id,order_id,assignment_revision,attempt_number,submitted_by,submitted_at,done_late,
             work_description,work_code_id,comment,completeness,missing_evidence,after_photo_ids)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::uuid[])""",
            (sub.id, sub.order_id, sub.assignment_revision, sub.attempt_number, sub.submitted_by,
             sub.submitted_at, sub.done_late, p.work_description, p.work_code_id, p.comment,
             sub.completeness.value, jsonb([item.value for item in sub.missing_evidence]),
             list(p.after_photo_ids)))
        for material in p.materials:
            self.db.execute("""INSERT INTO material_writeoffs (submission_id,material_id,quantity)
                VALUES (%s,%s,%s)""", (sub.id, material.material_id, material.quantity))

    def persist_review(self, review):
        self.db.execute("""INSERT INTO reviews
            (id,submission_id,reviewer_id,decision,reason,final_score,created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s)""", (review.id, review.submission_id, review.reviewer_id,
                review.decision.value, review.reason, review.final_score, review.created_at))

    def persist_events(self, events, real_now):
        sequence = self.db.execute("SELECT COALESCE(MAX(sequence),0) AS n FROM order_events WHERE order_id=%s",
                                   (events[0].order_id,)).fetchone()["n"]
        for event in events:
            sequence += 1
            self.db.execute("""INSERT INTO order_events
                (id,order_id,sequence,order_version,assignment_revision,scheduling_revision,kind,reason,
                 details,actor_id,operation_id,from_status,to_status,submission_id,occurred_at,recorded_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (event.id,event.order_id,sequence,event.order_version,event.assignment_revision,
                 event.scheduling_revision,event.kind,event.reason,jsonb(dict(event.details)),event.actor_id,
                 event.operation_id,None if event.from_status is None else event.from_status.value,
                 event.to_status.value,event.submission_id,event.occurred_at,real_now))

    def attach_photos(self, photo_ids, plan, actor_id, real_now):
        for photo_id in sorted(photo_ids):
            count = self.db.execute("""UPDATE photos SET order_id=%s,submission_id=%s,attached_at=%s
                WHERE id=%s AND attached_at IS NULL AND owner_id=%s AND section_id=%s
                AND expires_at>%s""", (plan.order.id,
                plan.submission.id if plan.submission else None, real_now, photo_id,
                actor_id, plan.order.section_id, real_now)).rowcount
            if count != 1:
                raise AccessDenied()

    def ai_job(self, submission, real_now):
        self.db.execute("""INSERT INTO ai_jobs
            (id,submission_id,assignment_revision,state,next_attempt_at,created_at)
            VALUES (%s,%s,%s,'pending',%s,%s)""",
            (str(uuid5(UUID(submission.id), "assessment-job")), submission.id,
             submission.assignment_revision, real_now, real_now))

    def delivery_job(self, *, order, kind, recipient_id, channel, bucket, due_at, real_now, job_id=None):
        identity = f"{order.assignment_revision}:{order.scheduling_revision}:{kind}:{recipient_id}:{channel}:{bucket}"
        self.db.execute("""INSERT INTO delivery_jobs
            (id,order_id,assignment_revision,scheduling_revision,kind,recipient_id,channel,bucket,
             due_at,state,next_attempt_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s)
            ON CONFLICT (order_id,assignment_revision,scheduling_revision,kind,recipient_id,channel,bucket)
            DO NOTHING""", (job_id or str(uuid5(UUID(order.id), identity)),order.id,order.assignment_revision,
            order.scheduling_revision,kind,recipient_id,channel,bucket,due_at,real_now))

    def invalidate_jobs(self, order):
        # Pending/in-flight old revision or execution-cycle work must never revive
        # after submit/rework. A dispatcher STILL rechecks DB scope before sending.
        self.db.execute("""UPDATE delivery_jobs SET state='cancelled'
            WHERE order_id=%s AND state IN ('pending','retry','sending') AND
            (assignment_revision<>%s OR scheduling_revision<>%s OR
             (%s AND kind IN ('new_order','deadline_reminder','overdue','acceptance_escalation','manager_escalation')))""",
            (order.id,order.assignment_revision,order.scheduling_revision,
             order.status in {Status.AI_REVIEW,Status.CLOSED,Status.CANCELLED,Status.REWORK}))


class PostgresReferences:
    def __init__(self, repository, principal, real_now, order):
        self.repo = repository
        self.db = repository.db
        self.principal = principal
        self.real_now = real_now
        self.order = order

    def equipment_in_section(self, equipment_id, section_id):
        return self.db.execute("SELECT id FROM equipment WHERE id=%s AND section_id=%s FOR SHARE",
                               (equipment_id, section_id)).fetchone() is not None

    def assignment_in_section(self, assignment, section_id):
        employee = self.db.execute("""SELECT id,brigade_id FROM employees WHERE id=%s
            AND active AND on_shift AND role='executor' FOR SHARE""",
            (assignment.executor_id,)).fetchone()
        member = self.db.execute("""SELECT employee_id FROM employee_sections
            WHERE employee_id=%s AND section_id=%s FOR SHARE""",
            (assignment.executor_id, section_id)).fetchone()
        if employee is None or member is None:
            return False
        if assignment.brigade_id is None:
            return True
        brigade = self.db.execute("SELECT id FROM brigades WHERE id=%s AND section_id=%s FOR SHARE",
                                  (assignment.brigade_id, section_id)).fetchone()
        return brigade is not None and sid(employee["brigade_id"]) == assignment.brigade_id

    def work_code_exists(self, work_code_id):
        return self.db.execute("SELECT id FROM work_codes WHERE id=%s FOR SHARE",
                               (work_code_id,)).fetchone() is not None

    def material_exists(self, material_id):
        return self.db.execute("SELECT id FROM materials WHERE id=%s FOR SHARE",
                               (material_id,)).fetchone() is not None

    def lock_stages(self, ids):
        if ids:
            self.db.execute("SELECT id FROM photos WHERE id=ANY(%s::uuid[]) ORDER BY id FOR UPDATE",
                            (list(ids),)).fetchall()

    def staged_photo_usable(self, photo_id, purpose, actor_id, destination_section_id,
                            order_id, assignment_revision):
        row = self.db.execute("SELECT * FROM photos WHERE id=%s FOR UPDATE", (photo_id,)).fetchone()
        if row is None or row["attached_at"] is not None or row["file_valid"] is not True:
            return False
        if actor_id != self.principal.user_id or purpose != row["purpose"]:
            return False
        if (order_id is not None and (self.order is None or self.order.id != order_id
                or self.order.assignment_revision != assignment_revision)):
            return False
        staged = StagedPhotoScope(sid(row["id"]),sid(row["section_id"]),sid(row["owner_id"]),
            row["expires_at"],row["purpose"],sid(row["order_id"]),row["assignment_revision"])
        if staged.expires_at <= self.real_now and staged.uploader_id == self.principal.user_id and staged.section_id == destination_section_id:
            # Reveal expiry only for an otherwise correctly bound, currently
            # authorized owned stage. Foreign/stale binding remains generic 403.
            if purpose == "before" and staged.order_id is None and staged.assignment_revision is None and self.order is None:
                require_create_order(self.principal,destination_section_id)
                raise DomainError("PHOTO_EXPIRED", "Photo stage expired; upload it again")
            if purpose == "after" and self.order is not None and staged.order_id == self.order.id and staged.assignment_revision == self.order.assignment_revision:
                require_order_access(self.principal,OrderAction.SUBMIT,scope(self.order))
                raise DomainError("PHOTO_EXPIRED", "Photo stage expired; upload it again")
        require_staged_attachment(self.principal,staged,section_id=destination_section_id,
            real_now=self.real_now,order=scope(self.order) if self.order else None)
        return True

    def closure_evidence(self, submission):
        code_ids = frozenset({submission.payload.work_code_id}) if (
            submission.payload.work_code_id is not None and
            self.work_code_exists(submission.payload.work_code_id)) else frozenset()
        material_ids = frozenset(m.material_id for m in submission.payload.materials
                                 if self.material_exists(m.material_id))
        rows = self.db.execute("""SELECT * FROM photos WHERE id=ANY(%s::uuid[])
            ORDER BY id FOR SHARE""", (list(submission.payload.after_photo_ids),)).fetchall()
        photos = []
        for row in rows:
            # Missing/malformed/unattached bindings are absent evidence, never
            # reconstructed from the expected IDs or client metadata.
            if (row["attached_at"] is None or row["order_id"] is None
                    or row["submission_id"] is None or row["assignment_revision"] is None):
                continue
            valid = row["file_valid"]
            if (sid(row["section_id"]) != self.order.section_id
                    or sid(row["owner_id"]) != submission.submitted_by):
                valid = False
            photos.append(PhotoEvidence(sid(row["id"]),sid(row["order_id"]),sid(row["submission_id"]),
                                        row["assignment_revision"],row["purpose"],valid))
        return code_ids, material_ids, tuple(photos)
