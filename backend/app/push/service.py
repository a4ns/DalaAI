"""Current server-authenticated user only. Session revoke/expiry gates sending."""
from hashlib import sha256

from app.core.auth_boundary import RequestProtection, SystemRealClock, authenticate_session
from app.orders.models import DomainError
from app.persistence.postgres import PostgresPrincipals, PostgresSessions
from .postgres import PushRepository
from .validation import parse_subscription, parse_removal


class PushService:
    def __init__(self, connect, *, allowed_origin, settings, real_clock=None):
        self.connect = connect
        self.protection = RequestProtection(allowed_origin)
        self.settings = settings
        self.real_clock = real_clock or SystemRealClock()

    def _connection(self):
        from psycopg.rows import dict_row
        from psycopg.pq import TransactionStatus
        db = self.connect()
        if not db.autocommit or db.info.transaction_status != TransactionStatus.IDLE:
            db.close()
            raise ValueError('Fresh idle autocommit connection required')
        db.row_factory = dict_row
        return db

    def _auth(self, db, handle):
        return authenticate_session(handle,sessions=PostgresSessions(db),
            principals=PostgresPrincipals(db),real_clock=self.real_clock)

    def config(self, *, session_handle):
        with self._connection() as db, db.transaction():
            self._auth(db, session_handle)
            return self.settings.public_config()

    def mutate(self, body, *, remove=False, session_handle, origin, csrf_token):
        with self._connection() as db, db.transaction():
            context = self._auth(db, session_handle)
            self.protection.require_http(context,method='POST',origin=origin,csrf_token=csrf_token)
            if not remove and not self.settings.enabled:
                raise DomainError('PUSH_DISABLED', 'Web Push is not configured')
            now = self.real_clock.now()
            value = parse_removal(body) if remove else parse_subscription(body,now=now)
            repo = PushRepository(db)
            if remove:
                repo.remove(context.principal.user_id,value,now=now)
                result = None
            else:
                result = repo.register(context.principal.user_id,sha256(session_handle.encode()).hexdigest(),value,now=now)
            # Re-evaluate expiry after any lock wait; failed check rolls back.
            refreshed = self._auth(db, session_handle)
            self.protection.require_http(refreshed,method='POST',origin=origin,csrf_token=csrf_token)
            return result
