"""Cookie/session request checks; no credential generation or session issuance."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hmac import compare_digest
from typing import Protocol
from urllib.parse import urlsplit

from .auth_policy import AccessDenied, Principal

SESSION_COOKIE_NAME = "__Host-naryadai_session"
SESSION_COOKIE_OPTIONS = {"secure": True, "httponly": True, "samesite": "strict", "path": "/"}
CSRF_HEADER = "X-CSRF-Token"


class AuthenticationRequired(Exception):
    code = "unauthorized"

    def __init__(self):
        super().__init__("Authentication required")


@dataclass(frozen=True)
class SessionRecord:
    user_id: str
    created_at: datetime
    expires_at: datetime
    csrf_token: str = field(repr=False)
    revoked: bool = False


@dataclass(frozen=True)
class AuthContext:
    principal: Principal
    session: SessionRecord = field(repr=False)


class SessionStore(Protocol):
    def lookup(self, session_handle: str) -> SessionRecord | None:
        """Server lookup only; persistent adapters should store a handle digest."""
        ...


class PrincipalStore(Protocol):
    def lookup(self, user_id: str) -> Principal | None:
        """Load current active/role/section state, never claims from request body."""
        ...


class RealClock(Protocol):
    def now(self) -> datetime: ...


class SystemRealClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def authenticate_session(session_handle: str | None, *, sessions: SessionStore,
                         principals: PrincipalStore,
                         real_clock: RealClock | None = None) -> AuthContext:
    """Use once per HTTP request and again during event delivery/long connections.

    Cookie adapter must reject ambiguous/duplicate cookies. Store failures propagate
    as failures; never continue as an authenticated user on backend failure.
    """
    if not isinstance(session_handle, str) or not 1 <= len(session_handle) <= 512:
        raise AuthenticationRequired()
    session = sessions.lookup(session_handle)
    now = (real_clock or SystemRealClock()).now()
    if (session is None or session.revoked or not _aware(now)
            or not _aware(session.created_at) or not _aware(session.expires_at)
            or session.created_at > now or session.expires_at <= now
            or session.created_at >= session.expires_at or not session.csrf_token):
        raise AuthenticationRequired()
    principal = principals.lookup(session.user_id)
    if principal is None or not principal.active or not principal.user_id or principal.user_id != session.user_id:
        raise AuthenticationRequired()
    return AuthContext(principal, session)


@dataclass(frozen=True)
class RequestProtection:
    allowed_origin: str

    def __post_init__(self):
        parsed = urlsplit(self.allowed_origin)
        if (parsed.scheme != "https" or not parsed.netloc or parsed.username is not None
                or parsed.password is not None or parsed.path or parsed.query or parsed.fragment
                or "*" in self.allowed_origin):
            raise ValueError("Configure one exact HTTPS origin without a path")

    def require_origin(self, origin: str | None) -> None:
        """Use for login and every WebSocket handshake too; reject null/missing."""
        if origin != self.allowed_origin:
            raise AccessDenied()

    def require_http(self, context: AuthContext, *, method: str,
                     origin: str | None, csrf_token: str | None) -> None:
        if method in {"GET", "HEAD", "OPTIONS"}:
            return  # These handlers MUST have no side effects.
        if method not in {"POST", "PUT", "PATCH", "DELETE"}:
            raise AccessDenied()
        self.require_origin(origin)
        if (not isinstance(csrf_token, str) or not csrf_token
                or len(csrf_token) > 512 or len(context.session.csrf_token) > 512):
            raise AccessDenied()
        # Byte comparison supports malformed non-ASCII input without a 500.
        if not compare_digest(csrf_token.encode("utf-8"), context.session.csrf_token.encode("utf-8")):
            raise AccessDenied()
