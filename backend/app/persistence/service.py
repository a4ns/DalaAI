"""Transactional vertical slice. No login issuer, provider calls, or shared state."""
from dataclasses import asdict, dataclass
import json
from uuid import UUID

from app.ai.models import InputValidationError
from app.ai.order_adapter import from_order_snapshot
from app.ai.rules import evaluate_gates
from app.core.auth_boundary import RequestProtection, SystemRealClock, authenticate_session
from app.core.auth_policy import OrderAction, require_create_order, require_order_access
from app.integration.principal_bridge import actor_from_auth_context
from app.orders.models import Action, Decision, DomainError
from app.orders.rules import is_overdue, prepare_new_command
from app.orders.validation import parse_command, uid
from app.scheduler import SchedulePolicy, ScheduleSnapshot, plan_assignment_notice
from .canonical import canonical_json, command_hash, decode_json
from .postgres import (PostgresPrincipals, PostgresReferences, PostgresRepository,
                       PostgresSessions, scope, sid)


@dataclass(frozen=True)
class CommandResult:
    status: int
    body: dict
    replayed: bool = False  # internal telemetry only, not an extra wire field


def wire(value):
    return json.loads(canonical_json(value))


def order_wire(order, now):
    body = asdict(order)
    body.update(is_overdue=is_overdue(order, now), domain_now=now)
    return wire(body)


class CommandService:
    """Connect factory MUST open a fresh psycopg connection with autocommit=True.

    This class owns the entire transaction, including receipt reservation. Callers
    must not wrap it in an outer transaction or return success before it exits.
    Session/principal rows and current memberships are held SHARE for the short
    command; every order mutation locks the aggregate and additionally uses CAS.
    Domain clock is explicit; real time alone governs sessions/stages/job retries.
    """
    def __init__(self, connect, *, allowed_origin, delivery_channel, domain_clock,
                 real_clock=None, references_factory=PostgresReferences):
        self.connect = connect
        self.references_factory = references_factory
        self.protection = RequestProtection(allowed_origin)
        self.policy = SchedulePolicy(channel=delivery_channel)
        self.domain_clock = domain_clock
        self.real_clock = real_clock or SystemRealClock()

    def _connection(self):
        from psycopg.rows import dict_row
        db = self.connect()
        if not db.autocommit:
            db.close()
            raise ValueError("CommandService requires a fresh autocommit connection")
        db.row_factory = dict_row
        return db

    def _auth(self, db, handle):
        return authenticate_session(handle, sessions=PostgresSessions(db),
            principals=PostgresPrincipals(db), real_clock=self.real_clock)

    def _authorize(self, context, command, order):
        if command.action == Action.CREATE:
            require_create_order(context.principal, command.payload.section_id)
        else:
            if order is None:
                raise DomainError("NOT_FOUND", "Order does not exist")
            require_order_access(context.principal, OrderAction(command.action.value), scope(order))

    def _replay(self, repo, context, command, digest, receipt, requested_order_id, session_handle):
        if receipt is None or receipt["committed_at"] is None:
            raise RuntimeError("Committed receipt unavailable after reservation conflict")
        # Re-check resource access after waiting for a concurrent winner. Initial
        # object authorization was intentionally before the first receipt lookup.
        if requested_order_id is not None:
            current = repo.load_order(requested_order_id, share=True)
            self._authorize(context, command, current)
        if command.action == Action.CREATE and receipt["resource_kind"] == "order":
            created = repo.load_order(sid(receipt["resource_id"]), share=True)
            if created is None:
                raise DomainError("NOT_FOUND", "Order does not exist")
            require_order_access(context.principal, OrderAction.READ, scope(created))
            require_create_order(context.principal, created.section_id)
        context = self._auth(repo.db, session_handle)
        if requested_order_id is not None:
            self._authorize(context, command, current)
        if receipt["canonical_hash"] != digest:
            raise DomainError("OPERATION_ID_REUSED", "Operation ID already identifies another request")
        return CommandResult(receipt["response_status"], receipt["response_body"], True)

    def execute(self, raw, *, session_handle, origin, csrf_token, order_id=None):
        # authenticate before body interpretation, never take an Actor from HTTP.
        with self._connection() as db:
            with db.transaction():
                db.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                context = self._auth(db, session_handle)
                self.protection.require_http(context, method="POST", origin=origin, csrf_token=csrf_token)
                if isinstance(raw, (bytes, str)):
                    raw = decode_json(raw)
                command = parse_command(raw)
                order_id = None if order_id is None else uid(order_id, "order_id")
                digest = command_hash(command, order_id)
                repo = PostgresRepository(db)
                current = None if order_id is None else repo.load_order(order_id)
                self._authorize(context, command, current)
                receipt = repo.receipt(context.principal.user_id, command.operation_id)
                if receipt is not None:
                    return self._replay(repo, context, command, digest, receipt, order_id, session_handle)
                if not repo.reserve(context.principal.user_id, command.operation_id, digest, self.real_clock.now()):
                    # Not a UNIQUE exception in an aborted transaction. This new
                    # READ COMMITTED statement observes the committed winner.
                    context = self._auth(db, session_handle)
                    return self._replay(repo, context, command, digest,
                        repo.receipt(context.principal.user_id, command.operation_id), order_id, session_handle)
                current = None if order_id is None else repo.load_order(order_id, lock=True)
                # Row/receipt lock waits must not keep an expired session alive.
                context = self._auth(db, session_handle)
                self._authorize(context, command, current)
                actor = actor_from_auth_context(context)
                now = self.domain_clock.now()
                real_now = self.real_clock.now()
                refs = self.references_factory(repo, context.principal, real_now, current)
                photo_ids = (getattr(command.payload, "before_photo_ids", ()) or
                             getattr(command.payload, "after_photo_ids", ()))
                refs.lock_stages(photo_ids)
                sub = (repo.load_submission(current.current_submission_id)
                       if current and current.current_submission_id else None)
                plan = prepare_new_command(raw, actor, order=current, references=refs, domain_now=now,
                    order_number=repo.allocate_number() if current is None else None,
                    current_submission=sub,
                    next_attempt_number=repo.next_attempt(current) if current else 1)
                if command.action == Action.REVIEW and command.payload.decision == Decision.CLOSE:
                    codes, materials, photos = refs.closure_evidence(sub)
                    try:
                        data, evidence = from_order_snapshot(current, sub, work_code_ids=codes,
                            material_ids=materials, photos=photos)
                        permitted = evaluate_gates(data, evidence).closure_permitted
                    except InputValidationError:
                        permitted = False
                    if not permitted:
                        raise DomainError("INCOMPLETE_SUBMISSION", "Current required evidence is not verified",
                                          current_version=current.version)
                # Domain/reference/photo reads above can block. All needed rows
                # are now held; refresh security/domain time and revalidate the
                # pure plan before the first effect. Do not reuse pre-lock TTL.
                context = self._auth(db, session_handle)
                self._authorize(context, command, current)
                actor = actor_from_auth_context(context)
                now = self.domain_clock.now()
                real_now = self.real_clock.now()
                refs.real_now = real_now
                plan = prepare_new_command(raw, actor, order=current, references=refs, domain_now=now,
                    order_number=plan.order.number if current is None else None,
                    current_submission=sub,
                    next_attempt_number=plan.submission.attempt_number if plan.submission else 1)
                repo.persist_order(plan)
                if plan.submission:
                    repo.persist_submission(plan.submission)
                repo.attach_photos(photo_ids, plan, actor.id, real_now)
                if plan.review:
                    repo.persist_review(plan.review)
                repo.persist_events(plan.events, real_now)
                repo.invalidate_jobs(plan.order)
                self._outbox(repo, plan, command.action, real_now)
                body = {"order": order_wire(plan.order, now),
                        "event_ids": [event.id for event in plan.events],
                        "submission_id": plan.submission.id if plan.submission else None}
                status = 201 if command.action == Action.CREATE else 200
                repo.finalize_receipt(actor.id, command.operation_id, plan.order.id, status, body, real_now)
                result = CommandResult(status, body)
            # Includes deferred-FK and deferred-receipt-trigger checks at COMMIT.
            return result

    def _outbox(self, repo, plan, action, real_now):
        o = plan.order
        if action in {Action.CREATE, Action.REASSIGN}:
            # The just-persisted current revision's issue/reassign event is the
            # authoritative assignment clock. Never use original issued_at here.
            assignment_event = plan.events[0]
            snapshot = ScheduleSnapshot(o.id,o.assignment_revision,o.scheduling_revision,o.status.value,
                o.priority.value,o.assignment.executor_id,o.created_by,o.due_at,assignment_event.occurred_at,
                o.current_submission_id)
            job = plan_assignment_notice(snapshot, policy=self.policy)
            repo.delivery_job(order=o,kind=job.kind.value,recipient_id=job.recipient_id,
                channel=job.channel,bucket=job.bucket,due_at=job.due_at,real_now=real_now,job_id=job.id)
        if plan.submission:
            repo.ai_job(plan.submission, real_now)
            repo.delivery_job(order=o,kind="submission_ready",recipient_id=o.created_by,
                channel=self.policy.channel,bucket=plan.submission.id,due_at=o.updated_at,real_now=real_now)
        if plan.review:
            repo.delivery_job(order=o,kind="review_result",recipient_id=o.assignment.executor_id,
                channel=self.policy.channel,bucket=plan.review.submission_id,due_at=o.updated_at,real_now=real_now)

    def get_order(self, order_id, *, session_handle):
        with self._connection() as db:
            with db.transaction():
                context = self._auth(db, session_handle)
                repo = PostgresRepository(db)
                order = repo.load_order(uid(order_id, "order_id"), share=True)
                if order is None:
                    raise DomainError("NOT_FOUND", "Order does not exist")
                context = self._auth(db, session_handle)
                require_order_access(context.principal, OrderAction.READ, scope(order))
                return order_wire(order, self.domain_clock.now())

    def get_submission(self, order_id, submission_id, *, session_handle):
        with self._connection() as db:
            with db.transaction():
                context = self._auth(db, session_handle)
                repo = PostgresRepository(db)
                order = repo.load_order(uid(order_id, "order_id"), share=True)
                if order is None:
                    raise DomainError("NOT_FOUND", "Order does not exist")
                require_order_access(context.principal, OrderAction.READ, scope(order))
                sub = repo.load_submission(uid(submission_id, "submission_id"))
                if sub is None:
                    raise DomainError("NOT_FOUND", "Submission does not exist")
                if sub.order_id != order.id:
                    raise DomainError("FORBIDDEN", "Submission is outside this order")
                body = asdict(sub)
                rows = db.execute("SELECT * FROM ai_assessments WHERE submission_id=%s ORDER BY created_at,id",
                                  (sub.id,)).fetchall()
                body["assessments"] = [{key: sid(value) if isinstance(value, UUID) else value
                                         for key, value in row.items()} for row in rows]
                rows = db.execute("SELECT * FROM reviews WHERE submission_id=%s ORDER BY created_at,id",
                                  (sub.id,)).fetchall()
                body["reviews"] = [{key: sid(value) if isinstance(value, UUID) else value
                                     for key, value in row.items()} for row in rows]
                context = self._auth(db, session_handle)
                require_order_access(context.principal, OrderAction.READ, scope(order))
                return wire(body)


def connection_factory(dsn):
    """No pool/global connection; credentials are supplied by the host, never logged."""
    def connect():
        import psycopg
        return psycopg.connect(dsn, autocommit=True)
    return connect
