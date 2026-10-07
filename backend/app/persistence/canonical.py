"""Versioned canonical command hash and strict JSON ingress; no float round trips."""
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from enum import Enum

from app.orders.models import Action, Command, DomainError
from app.orders.validation import uid


def decode_json(data: bytes | str) -> object:
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError("duplicate JSON key")
            out[key] = value
        return out

    def nonfinite(value):
        raise ValueError("non-finite JSON number")

    try:
        return json.loads(data, object_pairs_hook=pairs, parse_float=Decimal,
                          parse_constant=nonfinite)
    except (ValueError, UnicodeError, RecursionError):
        raise DomainError("INVALID_REQUEST", "Malformed or ambiguous JSON") from None


def canonical_json(value: object) -> str:
    """UTF-8, sorted keys, exact decimals, UTC instants; array ordering is meaningful.

    This is our internal v1 canonicalization, not a claim of RFC8785 compliance.
    Never apply Unicode normalization: different text remains a different intent.
    """
    if is_dataclass(value):
        return canonical_json(asdict(value))
    if isinstance(value, Enum):
        return canonical_json(value.value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be aware")
        value = value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("finite decimal required")
        if value == 0:
            return "0"
        text = format(value, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text
    if isinstance(value, str):
        if "\x00" in value:
            raise DomainError("VALIDATION_FAILED", "Text cannot contain U+0000")
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(canonical_json(item) for item in value) + "]"
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return "{" + ",".join(canonical_json(key) + ":" + canonical_json(value[key])
                               for key in sorted(value)) + "}"
    raise ValueError("unsupported canonical value")


def command_hash(command: Command, order_id: str | None) -> str:
    if command.action == Action.CREATE:
        if order_id is not None:
            raise DomainError("INVALID_REQUEST", "Create requires the collection route")
        route = "/api/v1/orders"
    else:
        if order_id is None:
            raise DomainError("INVALID_REQUEST", "Command requires an order route")
        route = "/api/v1/orders/" + uid(order_id, "order_id") + "/commands"
    envelope = {"canonical_version": 1, "method": "POST", "route": route,
                "command": command}
    try:
        return sha256(canonical_json(envelope).encode("utf-8")).hexdigest()
    except UnicodeError:
        raise DomainError("INVALID_REQUEST", "Invalid Unicode input") from None
