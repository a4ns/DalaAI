"""Map a freshly verified A2 context to A1's trusted, immutable actor.

Call authenticate_session for the current request first. This conversion cannot
prove that an arbitrary manually constructed AuthContext was authenticated.
Never build the context, identity, role or section set from request JSON, and do
not cache an AuthContext across requests. HTTP/CSRF, current object access,
receipt ordering and atomic persistence remain adapter responsibilities.
"""

from app.core.auth_boundary import AuthContext, AuthenticationRequired, SessionRecord
from app.core.auth_policy import Principal
from app.orders.models import Actor, Role


def actor_from_auth_context(context: AuthContext) -> Actor:
    """Preserve current identity/role/sections; reject malformed or inactive input."""
    if not isinstance(context, AuthContext):
        raise AuthenticationRequired()
    principal = context.principal
    session = context.session
    if not isinstance(principal, Principal) or not isinstance(session, SessionRecord):
        raise AuthenticationRequired()
    if (
        principal.active is not True
        or not isinstance(principal.user_id, str)
        or not principal.user_id.strip()
        or session.user_id != principal.user_id
        or session.revoked
        or not isinstance(principal.section_ids, frozenset)
        or any(not isinstance(section, str) or not section.strip() for section in principal.section_ids)
    ):
        raise AuthenticationRequired()
    try:
        role = Role(principal.role)
    except (TypeError, ValueError):
        raise AuthenticationRequired() from None
    return Actor(
        id=principal.user_id,
        role=role,
        section_ids=frozenset(principal.section_ids),
    )
