"""Read-only list/catalogue service composed with the reviewed A2 auth stores."""
from uuid import UUID

from app.core.auth_boundary import SystemRealClock, authenticate_session
from app.core.auth_policy import AccessDenied, Role, OrderAction, require_order_access
from app.orders.models import DomainError
from app.persistence.postgres import PostgresSessions,PostgresPrincipals,scope
from app.persistence.service import order_wire,wire
from .cursor import Cursor,parse_query
from .postgres import DiscoveryRepository
from .workload import WorkloadPolicy


def wire_ids(value):
    if isinstance(value,UUID):
        return str(value)
    if isinstance(value,dict):
        return {key:wire_ids(item) for key,item in value.items()}
    if isinstance(value,(tuple,list)):
        return [wire_ids(item) for item in value]
    return value


class DiscoveryService:
    """No mutation methods. A fresh connection/transaction belongs to each read.

    The optional named dictionary policy must be explicitly supplied once its
    interpretation is accepted. List implementation does not depend on that gate.
    """
    def __init__(self,connect,*,domain_clock,real_clock=None,dictionary_policy=None):
        if dictionary_policy is not None and not isinstance(dictionary_policy,WorkloadPolicy):
            raise ValueError("Explicit typed dictionary policy required")
        self.connect=connect
        self.domain_clock=domain_clock
        self.real_clock=real_clock or SystemRealClock()
        self.dictionary_policy=dictionary_policy

    def _connection(self):
        from psycopg.rows import dict_row
        db=self.connect()
        if not db.autocommit:
            db.close()
            raise ValueError("DiscoveryService requires a fresh autocommit connection")
        db.row_factory=dict_row
        return db

    def _auth(self,db,handle):
        return authenticate_session(handle,sessions=PostgresSessions(db),
            principals=PostgresPrincipals(db),real_clock=self.real_clock)

    def list_orders(self,query,*,session_handle):
        with self._connection() as db:
            with db.transaction():
                db.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                context=self._auth(db,session_handle)
                if context.principal.role not in {Role.MASTER,Role.MANAGER,Role.EXECUTOR}:
                    raise AccessDenied()
                query=parse_query(query)
                cursor=(Cursor.decode(query.cursor_token,actor_id=context.principal.user_id,filters=query.filters)
                        if query.cursor_token is not None else None)
                orders=DiscoveryRepository(db).list_orders(context.principal,query,cursor)
                # All selected order rows are SHARE locked; security time cannot
                # be reused from before a lock wait, even for the extra-page row.
                context=self._auth(db,session_handle)
                if context.principal.role not in {Role.MASTER,Role.MANAGER,Role.EXECUTOR}:
                    raise AccessDenied()
                for order in orders:
                    require_order_access(context.principal,OrderAction.READ,scope(order))
                more=len(orders)>query.limit
                page=orders[:query.limit]
                next_cursor=None
                if more:
                    upper=cursor.upper_number if cursor is not None else int(page[0].number)
                    next_cursor=Cursor(context.principal.user_id,query.filters.fingerprint,upper,
                                       int(page[-1].number)).encode()
                now=self.domain_clock.now()
                return {"items":[order_wire(order,now) for order in page],"next_cursor":next_cursor}

    def get_dictionaries(self,*,session_handle):
        with self._connection() as db:
            with db.transaction():
                db.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                context=self._auth(db,session_handle)
                if self.dictionary_policy is None:
                    raise DomainError("TEMPORARILY_UNAVAILABLE","Dictionary workload semantics are not configured")
                result=DiscoveryRepository(db).dictionaries(context.principal,self.dictionary_policy)
                refreshed=self._auth(db,session_handle)
                if refreshed.principal != context.principal:
                    raise AccessDenied()
                return wire(wire_ids(result))
