from dataclasses import dataclass
import re
from typing import Mapping
from app.orders.models import DomainError,FieldError

MAX_SEQUENCE=2**63-1
MAX_JS_SAFE_INTEGER=2**53-1


@dataclass(frozen=True)
class EventQuery:
    after_sequence:int=0
    limit:int=100


def invalid(name):
    raise DomainError('VALIDATION_FAILED','Invalid event page parameter',
                      field_errors=(FieldError(name,'INTEGER_OUT_OF_RANGE'),))


def parse_query(query:Mapping[str,str]|list[tuple[str,str]]) -> EventQuery:
    pairs=query.items() if isinstance(query,Mapping) else query
    values={}
    for name,value in pairs:
        if name not in {'after_sequence','limit'} or name in values or not isinstance(value,str):
            raise DomainError('INVALID_REQUEST','Unknown or repeated event query parameter')
        values[name]=value
    after=values.get('after_sequence','0')
    if len(after)>19 or re.fullmatch(r'(?:0|[1-9][0-9]*)',after) is None:
        invalid('after_sequence')
    if int(after)>MAX_SEQUENCE:
        invalid('after_sequence')
    limit=values.get('limit','100')
    if re.fullmatch(r'[1-9][0-9]{0,2}',limit) is None or int(limit)>200:
        invalid('limit')
    return EventQuery(int(after),int(limit))
