"""Proposal.2 event wire shape; invalid stored data fails closed, never rounds ints."""
from datetime import datetime,timezone
import json
from uuid import UUID
from app.orders.models import DomainError,Status
from .query import MAX_SEQUENCE

EVENT_FIELDS=('id','order_id','sequence','order_version','assignment_revision','scheduling_revision',
    'reason','details','kind','actor_id','operation_id','from_status','to_status','submission_id',
    'occurred_at','recorded_at')
EVENT_KINDS=frozenset({'order.created','order.queued','order.accepted','order.rejected','order.started',
    'order.paused','order.resumed','order.done','order.ai_review_requested','order.assessment_recorded',
    'order.reviewed','order.reassigned','order.cancelled','order.priority_changed'})


def unavailable():
    raise DomainError('TEMPORARILY_UNAVAILABLE','Event data is not valid for the current contract')


def identifier(value,*,nullable=False):
    if value is None and nullable:return None
    if not isinstance(value,(str,UUID)):unavailable()
    try:return str(UUID(str(value)))
    except (ValueError,AttributeError):unavailable()


def timestamp(value):
    if not isinstance(value,datetime) or value.tzinfo is None or value.utcoffset() is None:unavailable()
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z')


def event_wire(row,*,order_id):
    if any(name not in row for name in EVENT_FIELDS):unavailable()
    body={name:row[name] for name in EVENT_FIELDS}
    for name in ('id','order_id'):
        body[name]=identifier(body[name])
    if body['order_id']!=order_id:unavailable()
    for name in ('actor_id','operation_id','submission_id'):
        body[name]=identifier(body[name],nullable=True)
    for name in ('sequence','order_version','assignment_revision','scheduling_revision'):
        if type(body[name]) is not int or not 1<=body[name]<=MAX_SEQUENCE:unavailable()
    if not isinstance(body['kind'],str) or body['kind'] not in EVENT_KINDS:unavailable()
    try:
        body['to_status']=Status(body['to_status']).value
        if body['from_status'] is not None:body['from_status']=Status(body['from_status']).value
    except (ValueError,TypeError):unavailable()
    reason=body['reason']
    if reason is not None and (not isinstance(reason,str) or not 1<=len(reason)<=2000):unavailable()
    if not isinstance(body['details'],dict):unavailable()
    try:
        # JSONB may contain fractional metadata. This is wire validation, not
        # request-hash canonicalization; preserve finite floats instead of
        # rejecting or silently rounding them. JSON integer output stays exact.
        json.dumps(body['details'],allow_nan=False,ensure_ascii=False)
    except (ValueError,TypeError,OverflowError,RecursionError):unavailable()
    for name in ('occurred_at','recorded_at'):
        body[name]=timestamp(body[name])
    return body
