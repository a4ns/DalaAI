"""Strict decoder for A6's proposed commands. No HTTP routes or API fork."""
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from .models import (
    Action, Assignment, Command, CreatePayload, Decision, DomainError, EmptyPayload,
    FieldError, MaterialUse, OrderType, Priority, PriorityPayload, ReasonPayload,
    ReassignPayload, ReviewPayload, SubmitPayload,
)


def invalid(path: str, code: str = "INVALID_VALUE") -> None:
    raise DomainError("VALIDATION_FAILED", "Command contains invalid data",
                      field_errors=(FieldError(path, code),))


def obj(value: Any, keys: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        invalid(path, "OBJECT_REQUIRED")
    if set(value) != keys:
        invalid(path, "UNKNOWN_OR_MISSING_FIELD")
    return value


def string(value: Any, path: str, *, maximum: int = 2000, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        invalid(path)
    if not allow_empty and not value.strip():
        invalid(path, "NONEMPTY_REQUIRED")
    return value


def uid(value: Any, path: str) -> str:
    if not isinstance(value, str):
        invalid(path, "UUID_REQUIRED")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        invalid(path, "UUID_REQUIRED")
    if str(parsed) != value.lower():
        invalid(path, "UUID_REQUIRED")
    return str(parsed)


def integer(value: Any, path: str, minimum: int, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        invalid(path, "INTEGER_OUT_OF_RANGE")
    return value


def enum_value(kind: type, value: Any, path: str) -> Any:
    try:
        return kind(value)
    except (ValueError, TypeError):
        invalid(path, "UNKNOWN_VALUE")


# A6's explicit RFC3339 profile: calendar dates, full time, explicit zone;
# leap seconds are intentionally excluded by the shared proposal profile.
RFC3339 = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt]"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
    r"(?:\.[0-9]+)?(?:[Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
)


def timestamp(value: Any, path: str) -> datetime:
    if not isinstance(value, str) or not RFC3339.fullmatch(value):
        invalid(path, "RFC3339_TIMESTAMP_REQUIRED")
    try:
        parsed = datetime.fromisoformat(value.replace("t", "T").replace("z", "Z").replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        invalid(path, "RFC3339_TIMESTAMP_REQUIRED")


def identifiers(value: Any, path: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 5:
        invalid(path, "MAX_FIVE_PHOTOS")
    result = tuple(uid(item, f"{path}[{index}]") for index, item in enumerate(value))
    if len(set(result)) != len(result):
        invalid(path, "DUPLICATE_ID")
    return result


def assignment(value: Any, path: str) -> Assignment:
    p = obj(value, {"executor_id", "brigade_id"}, path)
    return Assignment(uid(p["executor_id"], path + ".executor_id"),
                      None if p["brigade_id"] is None else uid(p["brigade_id"], path + ".brigade_id"))


def materials(value: Any) -> tuple[MaterialUse, ...]:
    if not isinstance(value, list) or len(value) > 40:
        invalid("payload.materials")
    result = []
    for index, item in enumerate(value):
        path = f"payload.materials[{index}]"
        p = obj(item, {"material_id", "quantity"}, path)
        quantity = p["quantity"]
        if type(quantity) not in (int, float, Decimal):
            invalid(path + ".quantity")
        try:
            q = Decimal(str(quantity))
            if not q.is_finite() or not 0 < q <= 999999999 or q != q.quantize(Decimal("0.001")):
                invalid(path + ".quantity")
        except InvalidOperation:
            invalid(path + ".quantity")
        result.append(MaterialUse(uid(p["material_id"], path + ".material_id"), q))
    if len({m.material_id for m in result}) != len(result):
        invalid("payload.materials", "DUPLICATE_MATERIAL")
    return tuple(result)


def parse_command(value: Any) -> Command:
    envelope = obj(value, {"operation_id", "expected_version", "action", "payload"}, "command")
    operation_id = uid(envelope["operation_id"], "operation_id")
    action = enum_value(Action, envelope["action"], "action")
    version = integer(envelope["expected_version"], "expected_version", 0 if action == Action.CREATE else 1)
    if action == Action.CREATE and version != 0:
        invalid("expected_version")
    raw = envelope["payload"]
    if action == Action.CREATE:
        p = obj(raw, {"type", "description", "section_id", "equipment_id", "assignment", "due_at",
                      "norm_minutes", "priority", "comment", "before_photo_ids"}, "payload")
        payload = CreatePayload(
            enum_value(OrderType, p["type"], "payload.type"), string(p["description"], "payload.description"),
            uid(p["section_id"], "payload.section_id"), uid(p["equipment_id"], "payload.equipment_id"),
            assignment(p["assignment"], "payload.assignment"), timestamp(p["due_at"], "payload.due_at"),
            integer(p["norm_minutes"], "payload.norm_minutes", 1, 525600),
            enum_value(Priority, p["priority"], "payload.priority"),
            string(p["comment"], "payload.comment", allow_empty=True),
            identifiers(p["before_photo_ids"], "payload.before_photo_ids"))
    elif action in {Action.QUEUE, Action.ACCEPT, Action.START, Action.RESUME}:
        obj(raw, set(), "payload")
        payload = EmptyPayload()
    elif action in {Action.REJECT, Action.PAUSE, Action.CANCEL}:
        p = obj(raw, {"reason"}, "payload")
        payload = ReasonPayload(string(p["reason"], "payload.reason"))
    elif action == Action.SUBMIT:
        p = obj(raw, {"work_description", "work_code_id", "materials", "after_photo_ids", "comment"}, "payload")
        payload = SubmitPayload(
            string(p["work_description"], "payload.work_description", maximum=6000),
            None if p["work_code_id"] is None else uid(p["work_code_id"], "payload.work_code_id"),
            materials(p["materials"]), identifiers(p["after_photo_ids"], "payload.after_photo_ids"),
            string(p["comment"], "payload.comment", allow_empty=True))
    elif action == Action.REVIEW:
        p = obj(raw, {"submission_id", "decision", "reason", "final_score"}, "payload")
        payload = ReviewPayload(uid(p["submission_id"], "payload.submission_id"),
                                enum_value(Decision, p["decision"], "payload.decision"),
                                string(p["reason"], "payload.reason"),
                                None if p["final_score"] is None else integer(p["final_score"], "payload.final_score", 0, 100))
    elif action == Action.REASSIGN:
        p = obj(raw, {"assignment", "reason"}, "payload")
        payload = ReassignPayload(assignment(p["assignment"], "payload.assignment"), string(p["reason"], "payload.reason"))
    else:
        p = obj(raw, {"priority", "reason"}, "payload")
        payload = PriorityPayload(enum_value(Priority, p["priority"], "payload.priority"), string(p["reason"], "payload.reason"))
    return Command(operation_id, version, action, payload)
