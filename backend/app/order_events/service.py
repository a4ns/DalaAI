"""Current authorization around each per-order append-only history read."""
from app.core.auth_boundary import SystemRealClock,authenticate_session
from app.core.auth_policy import OrderAction,require_order_access
from app.orders.models import DomainError
from app.orders.validation import uid
from app.persistence.postgres import PostgresSessions,PostgresPrincipals
from .query import parse_query
from .postgres import EventRepository
from .serialization import event_wire,unavailable


class OrderEventService:
    def __init__(self,connect,*,real_clock=None):
        self.connect=connect;self.real_clock=real_clock or SystemRealClock()

    def _connection(self):
        from psycopg.rows import dict_row
        db=self.connect()
        if not db.autocommit:
            db.close();raise ValueError('OrderEventService requires a fresh autocommit connection')
        db.row_factory=dict_row
        return db

    def _auth(self,db,handle):
        return authenticate_session(handle,sessions=PostgresSessions(db),
            principals=PostgresPrincipals(db),real_clock=self.real_clock)

    def list_events(self,order_id,query,*,session_handle):
        with self._connection() as db:
            with db.transaction():
                db.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
                self._auth(db,session_handle)
                order_id=uid(order_id,'order_id');query=parse_query(query)
                repo=EventRepository(db)
                scope=repo.load_scope(order_id)
                context=self._auth(db,session_handle)
                if scope is None:raise DomainError('NOT_FOUND','Order does not exist')
                require_order_access(context.principal,OrderAction.EVENTS,scope)
                rows=repo.read_page(order_id,query)
                context=self._auth(db,session_handle)
                require_order_access(context.principal,OrderAction.EVENTS,scope)
                # The SQL and unique per-order sequence index provide ordering.
                # Keep a fail-closed boundary if a future adapter violates it.
                previous=query.after_sequence
                converted=[]
                for row in rows:
                    event=event_wire(row,order_id=order_id)
                    if event['sequence']<=previous:unavailable()
                    previous=event['sequence'];converted.append(event)
                items=converted[:query.limit]
                return {'items':items,'next_after_sequence':items[-1]['sequence'] if items else query.after_sequence,
                        'has_more':len(rows)>query.limit}
