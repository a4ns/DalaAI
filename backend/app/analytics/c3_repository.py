"""Bounded, protected runtime captures; no mutation SQL or alternate auth scheme.

A5 supplies the existing SessionService. Its private connection/auth seams are
intentionally reused until A2 offers a public transaction-scoped read seam.
REPEATABLE READ is logically read-only, not SQL READ ONLY: existing auth stores
need FOR SHARE locks. Never downgrade isolation or return a truncated capture.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from psycopg.pq import TransactionStatus

from app.core.auth_policy import AccessDenied, OrderAction, OrderScope, Role, require_order_access
from app.orders.models import (Assignment, Completeness, Decision, DomainError,
    MaterialUse, MissingEvidence, Order, OrderType, Priority, Review, Status,
    Submission, SubmitPayload)
from app.persistence.postgres import scope
from .c3_facts import build_facts
from .c3_types import AssessmentFact, MaterialReference, Period, Provenance, TrustedRows

if TYPE_CHECKING:
    from app.sessions.service import SessionService


@dataclass(frozen=True)
class CaptureLimits:
    max_orders: int = 2000
    max_rows: int = 20000  # Total across orders and every related table.
    max_period_days: int = 31
    max_sections: int = 64
    max_bytes: int = 8 * 1024 * 1024
    max_row_bytes: int = 128 * 1024

    def __post_init__(self):
        for name, ceiling in (("max_orders", 10000), ("max_rows", 100000),
                              ("max_period_days", 92), ("max_sections", 256),
                              ("max_bytes", 32 * 1024 * 1024), ("max_row_bytes", 1024 * 1024)):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError("Invalid report capture limits")


def _unavailable():
    return DomainError("TEMPORARILY_UNAVAILABLE", "Report capture is unavailable")


def _instant(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Aware report clock required")
    return value.astimezone(timezone.utc)


def parse_query(items, *, domain_as_of, limits, allow_html):
    """Strict values only: there is no client role, actor, scope or clock field."""
    values = {}
    for key, value in items:
        if key not in {"start", "end", "format"} or key in values or not isinstance(value, str):
            raise DomainError("INVALID_REQUEST", "Unsupported or repeated report parameter")
        values[key] = value
    if "start" not in values or "end" not in values:
        raise DomainError("VALIDATION_FAILED", "Report start and end are required")
    output = values.get("format", "json")
    if output not in ({"json", "html"} if allow_html else {"json"}):
        raise DomainError("VALIDATION_FAILED", "Unsupported report format")
    try:
        stamps = []
        for name in ("start", "end"):
            text = values[name]
            if not 20 <= len(text) <= 40 or "T" not in text:
                raise ValueError()
            stamps.append(_instant(datetime.fromisoformat(text.replace("Z", "+00:00"))))
        start, end = stamps
        if not start < end <= domain_as_of or end - start > timedelta(days=limits.max_period_days):
            raise ValueError()
    except (ValueError, OverflowError):
        raise DomainError("VALIDATION_FAILED", "Invalid or excessive report period") from None
    return Period(start, end), output


def _id(value):
    return None if value is None else str(value)


class RuntimeReportRepository:
    """Transaction-local capture of complete histories through scoped parent IDs."""
    def __init__(self, db, *, limits, recheck):
        self.db, self.limits, self.recheck = db, limits, recheck
        self.remaining = limits.max_rows
        self.remaining_bytes = limits.max_bytes

    def _read(self, statement, params, *, maximum=None, lock=False):
        cap = min(self.remaining, maximum) if maximum is not None else self.remaining
        bounded = statement + " LIMIT %s" + (" FOR SHARE" if lock else "")
        bound_params = (*params, cap + 1)
        # Bound arbitrary JSON arrays/text BEFORE transferring them. Computing
        # row_to_json is DB-local, timeout-bounded, and never returned to clients.
        size = self.db.execute("""SELECT count(*) AS row_count,
            COALESCE(sum(octet_length(row_to_json(capture_row)::text)),0) AS byte_count,
            COALESCE(max(octet_length(row_to_json(capture_row)::text)),0) AS largest_row
            FROM (""" + bounded + ") AS capture_row", bound_params).fetchone()
        self.recheck()
        if (size["row_count"] > cap or size["byte_count"] > self.remaining_bytes
                or size["largest_row"] > self.limits.max_row_bytes):
            raise DomainError("REPORT_LIMIT_EXCEEDED", "Report scope exceeds capture limits")
        rows = self.db.execute(bounded, bound_params).fetchall()
        self.recheck()  # Re-evaluate real-clock expiry after a potentially blocking read.
        if len(rows) != size["row_count"]:
            raise _unavailable()
        self.remaining -= len(rows)
        self.remaining_bytes -= int(size["byte_count"])
        return rows

    def capture(self, principal, *, provenance, order_id=None):
        columns = """id,number,version,assignment_revision,scheduling_revision,status,type,
            description,section_id,equipment_id,executor_id,brigade_id,created_by,
            issued_at,due_at,norm_minutes,priority,comment,current_submission_id,updated_at"""
        predicate = "section_id = ANY(%s::uuid[])"
        params = (sorted(principal.section_ids),)
        if order_id is not None:
            predicate += " AND id=%s::uuid"
            params += (order_id,)
        order_rows = self._read("SELECT " + columns + " FROM orders WHERE " + predicate + " ORDER BY id",
                                params, maximum=self.limits.max_orders, lock=True)
        if order_id is not None and not order_rows:
            # Missing and foreign IDs share an answer. Do not query foreign rows.
            raise DomainError("NOT_FOUND", "Report order not found")
        ids = [_id(row["id"]) for row in order_rows]
        if len(set(ids)) != len(ids):
            raise _unavailable()
        for row in order_rows:
            require_order_access(principal, OrderAction.REPORT,
                OrderScope(_id(row["id"]), _id(row["section_id"]), _id(row["executor_id"]),
                           row["assignment_revision"]))
        parents = {_id(row["id"]): row for row in order_rows}
        before = defaultdict(list)
        for row in self._read("""SELECT id,order_id,section_id FROM photos WHERE order_id = ANY(%s::uuid[])
                AND purpose='before' AND attached_at IS NOT NULL ORDER BY id""", (ids,)):
            if (_id(row["order_id"]) not in parents or
                    _id(row["section_id"]) != _id(parents[_id(row["order_id"])]["section_id"])):
                raise _unavailable()
            before[_id(row["order_id"])].append(_id(row["id"]))
        orders = tuple(Order(_id(r["id"]), str(r["number"]), r["version"], r["assignment_revision"],
            r["scheduling_revision"], Status(r["status"]), OrderType(r["type"]), r["description"],
            _id(r["section_id"]), _id(r["equipment_id"]), Assignment(_id(r["executor_id"]), _id(r["brigade_id"])),
            _id(r["created_by"]), r["issued_at"], r["due_at"], r["norm_minutes"], Priority(r["priority"]),
            r["comment"], tuple(before[_id(r["id"])]), _id(r["current_submission_id"]), r["updated_at"])
            for r in order_rows)
        for order in orders:
            require_order_access(principal, OrderAction.REPORT, scope(order))
        sub_rows = self._read("""SELECT id,order_id,assignment_revision,attempt_number,submitted_by,
            submitted_at,done_late,work_description,work_code_id,comment,completeness,
            missing_evidence,after_photo_ids FROM submissions
            WHERE order_id = ANY(%s::uuid[]) ORDER BY id""", (ids,))
        sub_ids = [_id(row["id"]) for row in sub_rows]
        sub_index = {_id(row["id"]): row for row in sub_rows}
        for sub in sub_rows:
            if _id(sub["order_id"]) not in parents:
                raise _unavailable()
        attached = defaultdict(set)
        for photo in self._read("""SELECT id,order_id,section_id,submission_id,assignment_revision
                FROM photos WHERE submission_id = ANY(%s::uuid[]) AND purpose='after'
                AND attached_at IS NOT NULL ORDER BY id""", (sub_ids,)):
            sub = sub_index.get(_id(photo["submission_id"]))
            if (sub is None or _id(photo["order_id"]) != _id(sub["order_id"])
                    or photo["assignment_revision"] != sub["assignment_revision"]
                    or _id(photo["section_id"]) != _id(parents[_id(sub["order_id"])]["section_id"])):
                raise _unavailable()
            attached[_id(photo["submission_id"])].add(_id(photo["id"]))
        for sub in sub_rows:
            manifest = tuple(_id(value) for value in sub["after_photo_ids"])
            if len(set(manifest)) != len(manifest) or set(manifest) != attached[_id(sub["id"])]:
                raise _unavailable()
        uses = defaultdict(list)
        for r in self._read("""SELECT submission_id,material_id,quantity FROM material_writeoffs
                WHERE submission_id = ANY(%s::uuid[]) ORDER BY submission_id,material_id""", (sub_ids,)):
            if _id(r["submission_id"]) not in sub_index:
                raise _unavailable()
            uses[_id(r["submission_id"])].append(MaterialUse(_id(r["material_id"]), r["quantity"]))
        submissions = tuple(Submission(_id(r["id"]), _id(r["order_id"]), r["assignment_revision"],
            r["attempt_number"], _id(r["submitted_by"]), r["submitted_at"], r["done_late"],
            SubmitPayload(r["work_description"], _id(r["work_code_id"]), tuple(uses[_id(r["id"])]),
                tuple(_id(value) for value in r["after_photo_ids"]), r["comment"]),
            None if r["completeness"] is None else Completeness(r["completeness"]),
            tuple(MissingEvidence(value) for value in r["missing_evidence"])) for r in sub_rows)
        reviews = tuple(Review(_id(r["id"]), _id(r["submission_id"]), _id(r["reviewer_id"]),
            Decision(r["decision"]), r["reason"], r["final_score"], r["created_at"])
            for r in self._read("""SELECT id,submission_id,reviewer_id,decision,reason,final_score,created_at
                FROM reviews WHERE submission_id = ANY(%s::uuid[]) ORDER BY id""", (sub_ids,)))
        assessments = tuple(AssessmentFact(_id(r["id"]), _id(r["submission_id"]), r["assignment_revision"],
            r["schema_version"], r["mode"], r["model"], r["model_version"], r["duration_ms"],
            r["recommendation"], r["score"], tuple(r["reasons"]), tuple(r["evidence_ids"]),
            r["fallback_reason"], r["stale"], r["created_at"])
            for r in self._read("""SELECT id,submission_id,assignment_revision,schema_version,mode,model,
                model_version,duration_ms,recommendation,score,reasons,evidence_ids,fallback_reason,stale,created_at
                FROM ai_assessments WHERE submission_id = ANY(%s::uuid[]) ORDER BY id""", (sub_ids,)))
        material_ids = sorted({use.material_id for values in uses.values() for use in values})
        materials = tuple(MaterialReference(_id(r["id"]), r["label"], r["unit"])
            for r in self._read("SELECT id,label,unit FROM materials WHERE id = ANY(%s::uuid[]) ORDER BY id",
                                (material_ids,)))
        if {ref.material_id for ref in materials} != set(material_ids):
            raise _unavailable()
        return TrustedRows(provenance, orders, submissions, reviews, assessments, materials)


class RuntimeReportService:
    """Existing session authority + bounded snapshot; an explicit mount only.

    synthetic is required server configuration, never a request parameter.
    There is no session-token fallback, client scope assertion or DB mutation.
    """
    def __init__(self, session_service: "SessionService", *, domain_clock, synthetic,
                 limits=None):
        if type(synthetic) is not bool:
            raise ValueError("Report source mode must be an explicit boolean")
        if limits is not None and not isinstance(limits, CaptureLimits):
            raise ValueError("Typed capture limits required")
        self.sessions, self.domain_clock, self.synthetic = session_service, domain_clock, synthetic
        self.limits = limits or CaptureLimits()

    def capture(self, query, *, session_handle, order_id=None, allow_html=False, project=None):
        with self.sessions._connection() as db:
            if not db.autocommit or db.info.transaction_status != TransactionStatus.IDLE:
                raise _unavailable()
            with db.transaction():
                db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                db.execute("SET LOCAL statement_timeout = '10000ms'")
                db.execute("SET LOCAL lock_timeout = '3000ms'")
                db.execute("SET LOCAL idle_in_transaction_session_timeout = '10000ms'")
                context = self.sessions._auth(db, session_handle)
                principal = context.principal
                if (principal.role != Role.MASTER or not principal.active or not principal.user_id
                        or not principal.section_ids):
                    raise AccessDenied()
                if len(principal.section_ids) > self.limits.max_sections:
                    raise DomainError("REPORT_LIMIT_EXCEEDED", "Report scope exceeds capture limits")
                def recheck():
                    if self.sessions._auth(db, session_handle).principal != principal:
                        raise AccessDenied()
                try:
                    recheck()  # Initial employee/membership lock waits may have consumed the session lifetime.
                    domain_as_of = _instant(self.domain_clock.now())
                    period, output = parse_query(query, domain_as_of=domain_as_of,
                                                 limits=self.limits, allow_html=allow_html)
                    if order_id is not None:
                        try:
                            order_id = str(UUID(order_id))
                        except (ValueError, AttributeError, TypeError):
                            raise DomainError("VALIDATION_FAILED", "Invalid report order ID") from None
                    provenance = Provenance(self.synthetic, "runtime-postgres:" + str(uuid4()),
                        ("Текущие разрешённые участки мастера" if order_id is None else "Один разрешённый наряд"),
                        domain_as_of, _instant(self.sessions.clock.now()), "consistent_snapshot", True)
                    rows = RuntimeReportRepository(db, limits=self.limits, recheck=recheck).capture(
                        principal, provenance=provenance, order_id=order_id)
                    facts = build_facts(rows, period)
                    if not facts.totals_available:
                        raise _unavailable()
                    result = project(facts, output) if project is not None else (facts, output)
                    recheck()
                except (ValueError, KeyError, TypeError, OverflowError):
                    # Invalid/incomplete stored rows do not become empty or partial totals.
                    raise _unavailable() from None
        return result
