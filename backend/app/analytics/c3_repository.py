"""Bounded, protected runtime captures; no mutation SQL or alternate auth scheme.

A5 supplies the existing SessionService. Its private connection/auth seams are
intentionally reused until A2 offers a public transaction-scoped read seam.
REPEATABLE READ is logically read-only, not SQL READ ONLY: existing auth stores
need FOR SHARE locks. Never downgrade isolation or return a truncated capture.
"""
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import TYPE_CHECKING
from uuid import UUID, uuid4, uuid5

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


# C107 v1.1.0 stores this provenance in immutable creation events. Only its
# canonical actor map is recognizable; alternate actor-map hashes cannot prove
# a mapping and do not receive the historical missing-evidence exception.
HISTORY_SOURCE = "8af3897f03aa2f41f0af07ec74ec2c807a4a535a"
HISTORY_SHA256 = "7d888cdd5bb6a9c01ca7c543fae9e393335d07210dab811aa754f12331d1d2e1"
HISTORY_NAMESPACE = UUID("716a1c94-5fd0-5c11-a9e9-13d12b739639")
HISTORY_WATERMARK = "Синтетические данные — не история предприятия"
HISTORY_PHOTO_POLICY = "metadata_only_no_image_bytes_no_file_valid_claim"


def _history_id(kind, number):
    return str(uuid5(HISTORY_NAMESPACE, f"1.0.0/20261008/{kind}/{number}"))


_CANONICAL_ACTORS = {**{f"SYN-M-{n:02}": _history_id("master", n) for n in range(1, 3)},
                     **{f"SYN-E-{n:02}": _history_id("executor", n) for n in range(1, 16)}}
_CANONICAL_ORDER_IDS = frozenset(_history_id("order", n) for n in range(1, 541))
HISTORY_ACTOR_MAP_SHA256 = sha256((json.dumps(_CANONICAL_ACTORS, ensure_ascii=False,
    sort_keys=True, separators=(",", ":")) + "\n").encode()).hexdigest()


def _historical_placeholders(order, submissions, event, *, synthetic):
    """Validate the entire stored canonical mapping, never a client assertion.

    Return None for ordinary live events. A purported historical marker which
    fails any binding is corruption, not permission to downgrade to live data.
    These public deterministic IDs are not credentials; trust also requires the
    existing immutable, server-authored creation-event boundary.
    """
    details = event.get("details")
    if not isinstance(details, dict) or "synthetic_import" not in details:
        return None
    marker = details["synthetic_import"]
    def require(condition):
        if not condition:
            raise _unavailable()
    require(synthetic is True and isinstance(marker, dict) and set(details) == {"synthetic_import"})
    expected = {"synthetic": True, "loader_version": "1.1.0", "source_commit": HISTORY_SOURCE,
        "history_sha256": HISTORY_SHA256, "identity_mapping_sha256": HISTORY_ACTOR_MAP_SHA256,
        "watermark": HISTORY_WATERMARK, "photo_policy": HISTORY_PHOTO_POLICY,
        "historical_completeness_not_verified_evidence": True, "historical_actor_state": "disabled_no_login"}
    require(set(marker) == set(expected) | {"source_order_number", "runtime_order_number", "source_photo_placeholders"})
    require(all(type(marker[key]) is type(value) and marker[key] == value for key, value in expected.items()))
    source_number = marker["source_order_number"]
    require(isinstance(source_number, str) and source_number.isascii() and source_number.isdecimal())
    number = int(source_number)
    require(1 <= number <= 540 and source_number == str(number))
    require(type(marker["runtime_order_number"]) is int and marker["runtime_order_number"] == int(order.number))
    require(order.id == _history_id("order", number) and order.status == Status.CLOSED
        and order.assignment_revision == order.scheduling_revision == 1 and not order.before_photo_ids)
    sections = {_history_id("section", n): n for n in range(1, 5)}
    require(order.section_id in sections)
    section = sections[order.section_id]
    require(order.created_by == _history_id("master", 1 if section <= 2 else 2))
    require(order.equipment_id in {_history_id("equipment", n) for n in range(1, 26) if (n-1)%4+1 == section})
    require(order.assignment.brigade_id == (_history_id("brigade", section) if section < 4 else None))
    require(order.assignment.executor_id in {_history_id("executor", n) for n in range(1, 16)
        if section == 4 or (n-1)//5+1 == section})
    require(_id(event["id"]) == _history_id("event", f"{number}/1")
        and _id(event["order_id"]) == order.id and event["kind"] == "order.created"
        and event["sequence"] == event["order_version"] == event["assignment_revision"] == event["scheduling_revision"] == 1
        and event["from_status"] is None and event["to_status"] == "issued" and event["submission_id"] is None
        and _id(event["actor_id"]) == order.created_by
        and _id(event["operation_id"]) == _history_id("operation", f"{number}/1") and event["reason"] is None
        and event["occurred_at"] == event["recorded_at"] == order.issued_at)
    descriptors = marker["source_photo_placeholders"]
    require(isinstance(descriptors, list))
    by_submission = {}
    for sub in submissions:
        sid, attempt = _id(sub["id"]), sub["attempt_number"]
        require(type(attempt) is int and 1 <= attempt <= 2 and sub["assignment_revision"] == 1
            and sid == _history_id("submission", f"{number}/{attempt}")
            and _id(sub["order_id"]) == order.id and _id(sub["submitted_by"]) == order.assignment.executor_id)
        manifest = tuple(_id(value) for value in sub["after_photo_ids"])
        expected_manifest = (_history_id("photo", f"{number}/{attempt}"),) if order.type == OrderType.UNPLANNED else ()
        require(manifest == expected_manifest)
        by_submission[sid] = (sub, set(manifest))
    require(1 <= len(by_submission) <= 2
        and {sub["attempt_number"] for sub, _ in by_submission.values()} == set(range(1, len(by_submission)+1)))
    found = set()
    fields = {"id", "order_id", "submission_id", "assignment_revision", "owner_id", "purpose",
              "uploaded_at", "evidence_kind", "artifact_available"}
    for photo in descriptors:
        require(isinstance(photo, dict) and set(photo) == fields)
        require(photo["submission_id"] in by_submission)
        sub, manifest = by_submission[photo["submission_id"]]
        require(photo["id"] in manifest and photo["id"] not in found and photo["order_id"] == order.id
            and type(photo["assignment_revision"]) is int and photo["assignment_revision"] == 1
            and photo["owner_id"] == _id(sub["submitted_by"]) and photo["purpose"] == "after"
            and photo["evidence_kind"] == "synthetic_metadata_placeholder" and photo["artifact_available"] is False)
        require(_instant(datetime.fromisoformat(photo["uploaded_at"].replace("Z", "+00:00")))
                == sub["submitted_at"] - timedelta(minutes=1))
        found.add(photo["id"])
    require(found == {pid for _, manifest in by_submission.values() for pid in manifest})
    return {sid: manifest for sid, (_, manifest) in by_submission.items()}


@dataclass(frozen=True)
class CaptureLimits:
    max_orders: int = 2000
    max_rows: int = 20000  # Total across orders and every related table.
    max_period_days: int = 93
    max_sections: int = 64
    max_bytes: int = 8 * 1024 * 1024
    max_row_bytes: int = 128 * 1024

    def __post_init__(self):
        for name, ceiling in (("max_orders", 10000), ("max_rows", 100000),
                              ("max_period_days", 93), ("max_sections", 256),
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
        creation_rows = self._read("""SELECT id,order_id,sequence,order_version,assignment_revision,
                scheduling_revision,kind,details,actor_id,operation_id,reason,from_status,to_status,
                submission_id,occurred_at,recorded_at FROM order_events
                WHERE order_id = ANY(%s::uuid[]) AND kind='order.created' ORDER BY order_id,sequence""", (ids,))
        creations = {}
        for event in creation_rows:
            parent = _id(event["order_id"])
            if parent not in parents or parent in creations:
                raise _unavailable()
            creations[parent] = event
        sub_groups = defaultdict(list)
        for sub in sub_rows:
            sub_groups[_id(sub["order_id"])].append(sub)
        historical, historical_orders = {}, 0
        for order in orders:
            event = creations.get(order.id, {})
            recognized = _historical_placeholders(order, sub_groups[order.id], event,
                                                   synthetic=provenance.synthetic)
            if recognized is not None:
                historical.update(recognized)
                historical_orders += 1
            elif order.id in _CANONICAL_ORDER_IDS:
                # Even planned canonical history needs its unavailable-evidence
                # provenance; never silently relabel a missing marker as live.
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
        missing_historical = 0
        for sub in sub_rows:
            manifest = tuple(_id(value) for value in sub["after_photo_ids"])
            actual = attached[_id(sub["id"])]
            if len(set(manifest)) != len(manifest) or actual - set(manifest):
                raise _unavailable()
            missing = set(manifest) - actual
            if missing and _id(sub["id"]) not in historical:
                raise _unavailable()
            if _id(sub["id"]) in historical:
                missing_historical += len(missing)
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
        evidence = None
        if historical_orders:
            references = sum(len(manifest) for manifest in historical.values())
            evidence = {"status": "synthetic_historical_evidence_unavailable",
                "historical_order_count": historical_orders,
                "historical_submission_count": len(historical),
                "historical_after_photo_reference_count": references,
                "missing_after_photo_row_count": missing_historical,
                "physical_evidence_verified": False,
                "historical_completeness_is_verified_evidence": False,
                "source_commit": HISTORY_SOURCE, "history_sha256": HISTORY_SHA256,
                "loader_version": "1.1.0", "identity_mapping_sha256": HISTORY_ACTOR_MAP_SHA256}
            disclosure = (f"Синтетическая историческая запись: нарядов {historical_orders}, "
                f"попыток {len(historical)}, ссылок на фото {references}; "
                f"отсутствующих записей фото {missing_historical}. "
                "Историческая полнота не подтверждает проверку фото, работу ИИ или успешное живое закрытие.")
            provenance = replace(provenance, scope_description=provenance.scope_description + "; " + disclosure)
        return TrustedRows(provenance, orders, submissions, reviews, assessments, materials), evidence


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
                    rows, evidence = RuntimeReportRepository(db, limits=self.limits, recheck=recheck).capture(
                        principal, provenance=provenance, order_id=order_id)
                    facts = build_facts(rows, period)
                    if not facts.totals_available:
                        raise _unavailable()
                    if evidence is not None:
                        facts = replace(facts, unavailable_reasons=facts.unavailable_reasons + (
                            "historical_evidence:unavailable:missing_photo_rows="
                            + str(evidence["missing_after_photo_row_count"]),))
                    result = project(facts, output, evidence) if project is not None else (facts, output)
                    recheck()
                except (ValueError, KeyError, TypeError, OverflowError):
                    # Invalid/incomplete stored rows do not become empty or partial totals.
                    raise _unavailable() from None
        return result
