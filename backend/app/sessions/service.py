"""PostgreSQL demo login, revocation and current session; no production fallback."""
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from hashlib import sha256
import ipaddress
import secrets
from uuid import uuid4

from app.core.auth_boundary import (AuthenticationRequired, RequestProtection,
                                   SystemRealClock, authenticate_session)
from app.core.auth_policy import AccessDenied
from app.orders.models import DomainError
from app.persistence.canonical import decode_json
from app.persistence.postgres import PostgresPrincipals, PostgresSessions
from .crypto import Argon2idVerifier
from .limiter import PostgresAttemptLimiter, real_now


class RateLimited(Exception):
    def __init__(self, retry_after_seconds):
        self.retry_after_seconds = max(1, int(retry_after_seconds))
        super().__init__("Try again later")


@dataclass(frozen=True)
class IssuedSession:
    body: dict = field(repr=False)
    session_handle: str = field(repr=False)
    max_age: int


def parse_login(raw):
    value = decode_json(raw)
    if (not isinstance(value, dict) or set(value) != {"employee_code", "pin"}
            or not isinstance(value["employee_code"], str)
            or not 1 <= len(value["employee_code"]) <= 40
            or not isinstance(value["pin"], str) or not 4 <= len(value["pin"]) <= 64):
        raise DomainError("VALIDATION_FAILED", "Invalid login fields")
    try:
        for item in value.values():
            if "\x00" in item:
                raise ValueError()
            item.encode("utf-8")
    except (ValueError, UnicodeError):
        raise DomainError("VALIDATION_FAILED", "Invalid login fields") from None
    # No normalization/case folding: employee_code has one exact DB identity.
    return value["employee_code"], value["pin"]


def source_identity(peer):
    """Only ASGI transport peer, never arbitrary Forwarded/X-Forwarded-For."""
    try:
        address = ipaddress.ip_address(peer)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        # IPv6 privacy addresses on one /64 share a source budget.
        return str(ipaddress.ip_network(f"{address}/64", strict=False)) if address.version == 6 else str(address)
    except (ValueError, TypeError):
        raise DomainError("TEMPORARILY_UNAVAILABLE", "Trusted request source unavailable") from None


def validate_handle(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 512:
        raise AuthenticationRequired()
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise AuthenticationRequired() from None
    return value


class SessionService:
    """Opt-in and demo-only. Caller provides fresh autocommit DB connections.

    No implicit seed or hardcoded PIN account. 8h absolute, non-sliding session
    lifetime. Rate limits use real UTC and persist separately before hash work.
    All response success follows COMMIT. No tokens/PINs in logs, URLs or reprs.
    """
    def __init__(self, connect, *, allowed_origin, demo_enabled=False,
                 session_ttl_seconds=28800, real_clock=None, verifier=None, limiter=None):
        if type(demo_enabled) is not bool:
            raise ValueError("demo_enabled must be explicit boolean")
        if type(session_ttl_seconds) is not int or not 1 <= session_ttl_seconds <= 86400:
            raise ValueError("Session TTL must be 1..86400 real seconds")
        self.connect = connect
        self.protection = RequestProtection(allowed_origin)
        self.demo_enabled = demo_enabled
        self.ttl = session_ttl_seconds
        self.clock = real_clock or SystemRealClock()
        self.verifier = verifier or Argon2idVerifier()
        self.limiter = limiter or PostgresAttemptLimiter(connect, real_clock=self.clock)

    def _connection(self):
        from psycopg.rows import dict_row
        db = self.connect()
        if not db.autocommit:
            db.close()
            raise ValueError("SessionService requires a fresh autocommit connection")
        db.row_factory = dict_row
        return db

    def _auth(self, db, handle):
        return authenticate_session(validate_handle(handle), sessions=PostgresSessions(db),
                                    principals=PostgresPrincipals(db), real_clock=self.clock)

    def _wire(self, db, context):
        row = db.execute("SELECT employee_code,on_shift FROM employees WHERE id=%s FOR SHARE",
                         (context.principal.user_id,)).fetchone()
        p = context.principal
        return {"principal": {"user_id": p.user_id, "active": p.active,
                "employee_code": row["employee_code"], "role": p.role.value,
                "section_ids": sorted(p.section_ids), "on_shift": row["on_shift"]},
                "csrf_token": context.session.csrf_token,
                "expires_at": context.session.expires_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")}

    def _lock_session(self, db, handle):
        db.execute("SELECT id FROM auth_sessions WHERE token_hash=%s FOR UPDATE",
                   (sha256(validate_handle(handle).encode("utf-8")).hexdigest(),)).fetchone()

    def login(self, raw, *, origin, source_key, previous_handle=None):
        self.protection.require_origin(origin)
        if not self.demo_enabled:
            raise AccessDenied()
        code, pin = parse_login(raw)
        source_key = source_identity(source_key)
        if previous_handle is not None:
            validate_handle(previous_handle)
        attempt = self.limiter.consume(account_key=code, source_key=source_key)
        if not attempt.allowed:
            raise RateLimited(attempt.retry_after_seconds)
        # No employee locks held during costly hash work. Do not skip the work
        # for unknown/inactive accounts or corrupt stored hashes.
        with self._connection() as db:
            account = db.execute("SELECT id,pin_hash,active FROM employees WHERE employee_code=%s",
                                 (code,)).fetchone()
        encoded = account["pin_hash"] if account else ""
        valid = self.verifier.verify(pin, encoded)
        if not valid or account is None or not account["active"]:
            raise AuthenticationRequired()
        handle, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self._connection() as db:
            with db.transaction():
                # Respect the common session -> employee -> membership lock order.
                if previous_handle is not None:
                    self._lock_session(db, previous_handle)
                current = db.execute("""SELECT id,pin_hash,active FROM employees
                    WHERE id=%s AND employee_code=%s FOR SHARE""", (account["id"], code)).fetchone()
                if current is None or not current["active"] or current["pin_hash"] != encoded:
                    raise AuthenticationRequired()
                principal = PostgresPrincipals(db).lookup(str(current["id"]))
                if principal is None or not principal.active:
                    raise AuthenticationRequired()
                now = real_now(self.clock)  # refresh after blocking locks
                if previous_handle is not None:
                    db.execute("""UPDATE auth_sessions SET revoked_at=%s
                        WHERE token_hash=%s AND revoked_at IS NULL""",
                        (now, sha256(previous_handle.encode("utf-8")).hexdigest()))
                db.execute("""INSERT INTO auth_sessions
                    (id,employee_id,token_hash,csrf_token,created_at,expires_at)
                    VALUES (%s,%s,%s,%s,%s,%s)""", (str(uuid4()), current["id"],
                    sha256(handle.encode("utf-8")).hexdigest(), csrf, now,
                    now + timedelta(seconds=self.ttl)))
                body = self._wire(db, self._auth(db, handle))
                self._auth(db, handle)  # expiry/active recheck after all reads
        return IssuedSession(body, handle, self.ttl)

    def me(self, *, session_handle):
        with self._connection() as db:
            with db.transaction():
                context = self._auth(db, session_handle)
                body = self._wire(db, context)
                self._auth(db, session_handle)
        return body

    def logout(self, *, session_handle, origin, csrf_token):
        self.protection.require_origin(origin)
        with self._connection() as db:
            with db.transaction():
                self._lock_session(db, session_handle)  # no SHARE->UPDATE upgrade
                context = self._auth(db, session_handle)
                self.protection.require_http(context, method="POST", origin=origin, csrf_token=csrf_token)
                context = self._auth(db, session_handle)
                db.execute("""UPDATE auth_sessions SET revoked_at=%s
                    WHERE token_hash=%s AND revoked_at IS NULL""", (real_now(self.clock),
                    sha256(session_handle.encode("utf-8")).hexdigest()))
