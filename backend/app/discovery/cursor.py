"""Bounded opaque v1 keyset cursors are hints, never authorization capabilities."""
from base64 import b64decode, urlsafe_b64encode
from dataclasses import dataclass
from hashlib import sha256
import re
from typing import Mapping

from app.orders.models import DomainError, FieldError, Status
from app.orders.validation import uid
from app.persistence.canonical import canonical_json, decode_json

MAX_BIGINT = 2**63-1
FILTER_NAMES = ("status", "section_id", "equipment_id", "executor_id")
QUERY_NAMES = frozenset((*FILTER_NAMES, "cursor", "limit"))


def invalid_cursor():
    raise DomainError("INVALID_REQUEST", "Invalid or mismatched pagination cursor")


def invalid_field(name):
    raise DomainError("VALIDATION_FAILED", "Invalid list filter",field_errors=(FieldError(name,"INVALID_VALUE"),))


@dataclass(frozen=True)
class OrderFilters:
    status: str | None = None
    section_id: str | None = None
    equipment_id: str | None = None
    executor_id: str | None = None

    @property
    def fingerprint(self):
        return sha256(canonical_json({name:getattr(self,name) for name in FILTER_NAMES}).encode()).hexdigest()


@dataclass(frozen=True)
class Cursor:
    actor_id: str
    filter_hash: str
    upper_number: int
    last_number: int

    def encode(self):
        value={"v":1,"actor":self.actor_id,"filters":self.filter_hash,
               "upper":self.upper_number,"last":self.last_number}
        return urlsafe_b64encode(canonical_json(value).encode()).rstrip(b"=").decode("ascii")

    @classmethod
    def decode(cls, token, *, actor_id, filters):
        if not isinstance(token,str) or not 1<=len(token)<=512 or re.fullmatch(r"[A-Za-z0-9_-]+",token) is None:
            invalid_cursor()
        try:
            raw=b64decode(token+"="*((-len(token))%4),altchars=b"-_",validate=True)
            if urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")!=token:
                invalid_cursor()
            value=decode_json(raw)
            if not isinstance(value,dict) or set(value)!={"v","actor","filters","upper","last"}:
                invalid_cursor()
            if type(value["v"]) is not int or value["v"]!=1:
                invalid_cursor()
            if value["actor"]!=actor_id or value["filters"]!=filters.fingerprint:
                invalid_cursor()
            if any(type(value[name]) is not int or not 1<=value[name]<=MAX_BIGINT for name in ("upper","last")):
                invalid_cursor()
            if value["last"]>value["upper"]:
                invalid_cursor()
            return cls(actor_id,filters.fingerprint,value["upper"],value["last"])
        except (ValueError,UnicodeError,DomainError):
            invalid_cursor()


@dataclass(frozen=True)
class ListQuery:
    filters: OrderFilters
    limit: int = 50
    cursor_token: str | None = None


def parse_query(query: Mapping[str,str] | list[tuple[str,str]]) -> ListQuery:
    pairs=list(query.items()) if isinstance(query,Mapping) else list(query)
    values={}
    for name,value in pairs:
        if name not in QUERY_NAMES or name in values or not isinstance(value,str):
            raise DomainError("INVALID_REQUEST", "Unknown or repeated list query parameter")
        values[name]=value
    raw_limit=values.get("limit","50")
    if re.fullmatch(r"[1-9][0-9]{0,2}",raw_limit) is None or int(raw_limit)>100:
        invalid_field("limit")
    status=values.get("status")
    if status is not None:
        try:
            status=Status(status).value
        except ValueError:
            invalid_field("status")
    ids={name:uid(values[name],name) if name in values else None for name in FILTER_NAMES[1:]}
    token=values.get("cursor")
    if token is not None and not 1<=len(token)<=512:
        invalid_cursor()
    return ListQuery(OrderFilters(status,**ids),int(raw_limit),token)
