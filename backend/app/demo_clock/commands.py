"""Strict bounded commands; no absolute time or rewind/reset operation."""
from uuid import UUID

from app.orders.models import DomainError
from app.persistence.canonical import decode_json

MAX_SCALE = 60
MAX_ADVANCE_SECONDS = 3600


def parse_control(raw):
    data = decode_json(raw) if isinstance(raw, (bytes, str)) else raw
    if not isinstance(data, dict):
        raise DomainError("INVALID_REQUEST", "JSON object required")
    action = data.get("action")
    extra = {"set_scale": "scale", "advance": "seconds"}.get(action) if isinstance(action, str) else None
    if extra is None or set(data) != {"instance_id", "expected_version", "action", extra}:
        raise DomainError("INVALID_REQUEST", "Unsupported demo-clock command fields")
    try:
        if str(UUID(data["instance_id"])) != data["instance_id"]:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise DomainError("VALIDATION_FAILED", "Canonical clock instance ID required") from None
    if type(data["expected_version"]) is not int or not 0 <= data["expected_version"] <= 2147483647:
        raise DomainError("VALIDATION_FAILED", "Clock version must be a bounded integer")
    minimum, maximum = (0, MAX_SCALE) if extra == "scale" else (1, MAX_ADVANCE_SECONDS)
    if type(data[extra]) is not int or not minimum <= data[extra] <= maximum:
        raise DomainError("VALIDATION_FAILED", "Demo-clock value is outside the allowed integer range")
    return data.copy()
