"""Framework-independent, deny-by-default authorization. Trusted DB objects only."""
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum


class Role(StrEnum):
    MASTER = "master"
    EXECUTOR = "executor"
    MANAGER = "manager"
    ADMIN = "admin"


class OrderAction(StrEnum):
    READ = "read"
    EVENTS = "events"
    REPORT = "report"
    ACCEPT = "accept"
    QUEUE = "queue"
    REJECT = "reject"
    START = "start"
    PAUSE = "pause"
    RESUME = "resume"
    SUBMIT = "submit"
    REASSIGN = "reassign"
    CANCEL = "cancel"
    CHANGE_PRIORITY = "change_priority"
    REVIEW = "review"
    UPLOAD = "upload"


class AccessDenied(Exception):
    """Map to generic HTTP 403; do not put object IDs or secrets in messages."""
    code = "forbidden"

    def __init__(self):
        super().__init__("Access denied")


@dataclass(frozen=True)
class Principal:
    user_id: str
    role: Role
    section_ids: frozenset[str]
    active: bool = True


@dataclass(frozen=True)
class OrderScope:
    order_id: str
    section_id: str
    executor_id: str
    assignment_revision: int


@dataclass(frozen=True)
class PhotoScope:
    photo_id: str
    section_id: str
    order_id: str


@dataclass(frozen=True)
class StagedPhotoScope:
    photo_id: str
    section_id: str
    uploader_id: str
    expires_at: datetime
    kind: str
    order_id: str | None = None
    assignment_revision: int | None = None


_READ = frozenset({OrderAction.READ, OrderAction.EVENTS, OrderAction.REPORT})
_EXECUTOR = frozenset({OrderAction.ACCEPT, OrderAction.QUEUE, OrderAction.REJECT,
                      OrderAction.START, OrderAction.PAUSE, OrderAction.RESUME,
                      OrderAction.SUBMIT, OrderAction.UPLOAD})
_MASTER = frozenset({OrderAction.REASSIGN, OrderAction.CANCEL, OrderAction.CHANGE_PRIORITY,
                    OrderAction.REVIEW, OrderAction.UPLOAD})


def _in_section(principal: Principal, section_id: str) -> bool:
    return bool(principal.active and principal.user_id and section_id
                and section_id in principal.section_ids)


def require_order_access(principal: Principal, action: OrderAction | str,
                         order: OrderScope) -> None:
    """Does NOT validate workflow status/version; A1 owns those checks.

    Re-read scope before receipts, each event delivery, and each file download.
    Admin intentionally has no order privileges, including read privileges.
    """
    if not _in_section(principal, order.section_id) or not order.order_id:
        raise AccessDenied()
    if principal.role == Role.MASTER and action in _READ | _MASTER:
        return
    if principal.role == Role.MANAGER and action in _READ:
        return
    if (principal.role == Role.EXECUTOR and order.executor_id == principal.user_id
            and action in _READ | _EXECUTOR):
        return
    raise AccessDenied()


def require_create_order(principal: Principal, section_id: str) -> None:
    if principal.role != Role.MASTER or not _in_section(principal, section_id):
        raise AccessDenied()


def require_section_report(principal: Principal, section_id: str) -> None:
    if principal.role not in (Role.MASTER, Role.MANAGER) or not _in_section(principal, section_id):
        raise AccessDenied()


def require_dictionary_write(principal: Principal, section_id: str) -> None:
    if principal.role != Role.ADMIN or not _in_section(principal, section_id):
        raise AccessDenied()


def require_demo_management(principal: Principal, *, demo_enabled: bool) -> None:
    if not demo_enabled or not principal.active or not principal.user_id or principal.role != Role.ADMIN:
        raise AccessDenied()


def require_photo_read(principal: Principal, photo: PhotoScope, order: OrderScope) -> None:
    if photo.order_id != order.order_id or photo.section_id != order.section_id:
        raise AccessDenied()
    require_order_access(principal, OrderAction.READ, order)


def require_staged_attachment(principal: Principal, photo: StagedPhotoScope,
                              *, section_id: str, real_now: datetime,
                              order: OrderScope | None = None) -> None:
    """Before-photo create or after-photo submit. Caller supplies real clock only.

    Atomic consumption, MIME/bytes validation and TTL cleanup are adapter duties.
    Never trust body-supplied ownership/section/revision metadata.
    """
    if (real_now.tzinfo is None or real_now.utcoffset() is None
            or photo.expires_at.tzinfo is None or photo.expires_at.utcoffset() is None):
        raise AccessDenied()
    if (photo.uploader_id != principal.user_id or photo.section_id != section_id
            or not _in_section(principal, section_id)
            or photo.expires_at <= real_now.astimezone(timezone.utc)):
        raise AccessDenied()
    if order is None:
        require_create_order(principal, section_id)
        if photo.kind != "before" or photo.order_id is not None or photo.assignment_revision is not None:
            raise AccessDenied()
        return
    if (order.section_id != section_id or photo.kind != "after"
            or photo.order_id != order.order_id
            or photo.assignment_revision != order.assignment_revision):
        raise AccessDenied()
    require_order_access(principal, OrderAction.SUBMIT, order)


def require_staged_photo_read(principal: Principal, photo: StagedPhotoScope,
                              *, real_now: datetime,
                              order: OrderScope | None = None) -> None:
    """A staged object is private to its uploader, with current assignment checks.

    Use a DB-loaded order for an after stage; an ID alone never grants access.
    """
    require_staged_attachment(principal, photo, section_id=photo.section_id,
                              real_now=real_now, order=order)
