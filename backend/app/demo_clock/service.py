"""Proposed privileged control service; the caller cannot supply a principal."""
from contextlib import contextmanager

from app.core.auth_boundary import RequestProtection, SystemRealClock, authenticate_session
from app.core.auth_policy import AccessDenied, Role
from .commands import parse_control


def postgres_authorization_scope(connect):
    """Existing session/role stores, with their SHARE locks held through control.

    Only reads; no SQL grants/migrations are introduced. Runtime verification of
    this adapter against a real restricted DB remains an integration gate.
    """
    @contextmanager
    def scope():
        from psycopg.rows import dict_row
        from app.persistence.postgres import PostgresPrincipals, PostgresSessions
        with connect() as db:
            if not db.autocommit:
                raise ValueError("A fresh autocommit connection is required")
            db.row_factory = dict_row
            with db.transaction():
                yield PostgresSessions(db), PostgresPrincipals(db)
    return scope


class DemoClockService:
    def __init__(self, clock, *, authorization_scope, allowed_origin, allowed_operator_ids, operator_roles, real_clock=None):
        if (not isinstance(allowed_operator_ids, frozenset) or not allowed_operator_ids
                or any(not isinstance(v, str) or not v or len(v) > 128 for v in allowed_operator_ids)):
            raise ValueError("Explicit existing demo-operator allowlist required")
        if not isinstance(operator_roles, frozenset) or not operator_roles or any(not isinstance(role, Role) for role in operator_roles):
            raise ValueError("Explicit existing operator-role set required")
        self.operator_roles = operator_roles
        self.clock = clock
        self.authorization_scope = authorization_scope
        self.protection = RequestProtection(allowed_origin)
        self.allowed_operator_ids = allowed_operator_ids
        self.real_clock = real_clock or SystemRealClock()
        if self.real_clock is clock:
            raise ValueError("Business clock cannot be the authentication clock")

    def _auth(self, stores, handle):
        context = authenticate_session(handle, sessions=stores[0], principals=stores[1], real_clock=self.real_clock)
        if context.principal.role not in self.operator_roles or context.principal.user_id not in self.allowed_operator_ids:
            raise AccessDenied()
        return context

    def get(self, *, session_handle):
        with self.clock.locked():
            with self.authorization_scope() as stores:
                self._auth(stores, session_handle)
                return self.clock.capture(authorize=lambda: self._auth(stores, session_handle)).wire()

    def control(self, raw, *, session_handle, origin, csrf_token):
        with self.clock.locked():
            with self.authorization_scope() as stores:
                context = self._auth(stores, session_handle)
                self.protection.require_http(context, method="POST", origin=origin, csrf_token=csrf_token)
                command = parse_control(raw)
                def authorize():
                    context = self._auth(stores, session_handle)
                    self.protection.require_http(context, method="POST", origin=origin, csrf_token=csrf_token)
                    return context.principal.user_id
                return self.clock.apply(command, authorize=authorize).wire()
