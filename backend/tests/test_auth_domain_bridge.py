"""Pure A1/A2 boundary tests; no HTTP, PostgreSQL or receipt guarantees."""

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app.core.auth_boundary import (
    AuthContext, AuthenticationRequired, SessionRecord, authenticate_session,
)
from app.core.auth_policy import Principal, Role as AuthRole
from app.integration.principal_bridge import actor_from_auth_context
from app.orders.models import Action, DomainError, Role as DomainRole
from app.orders.rules import authorize

NOW = datetime(2026, 10, 7, 17, tzinfo=timezone.utc)
USER = "11111111-1111-4111-8111-000000000001"
SECTION = "11111111-1111-4111-8111-000000000002"
OTHER_SECTION = "11111111-1111-4111-8111-000000000003"


class Store:
    def __init__(self, value):
        self.value = value

    def lookup(self, key):
        return self.value


class Clock:
    def now(self):
        return NOW


class AuthDomainBridgeTests(unittest.TestCase):
    def setUp(self):
        self.principal = Principal(USER, AuthRole.MASTER, frozenset({SECTION}))
        self.session = SessionRecord(USER, NOW - timedelta(minutes=1),
                                     NOW + timedelta(hours=1), "synthetic-csrf")

    def context(self, principal=None, session=None):
        return AuthContext(principal or self.principal, session or self.session)

    def test_verified_context_preserves_identity_role_and_current_sections(self):
        context = authenticate_session("synthetic-handle", sessions=Store(self.session),
                                       principals=Store(self.principal), real_clock=Clock())
        actor = actor_from_auth_context(context)
        self.assertEqual(actor.id, USER)
        self.assertIs(actor.role, DomainRole.MASTER)
        self.assertEqual(actor.section_ids, frozenset({SECTION}))
        self.assertIsInstance(actor.section_ids, frozenset)

    def test_all_known_roles_are_explicitly_mapped_without_elevation(self):
        for role in AuthRole:
            with self.subTest(role=role):
                actor = actor_from_auth_context(self.context(replace(self.principal, role=role)))
                self.assertIs(actor.role, DomainRole(role.value))

    def test_inactive_principal_is_rejected(self):
        with self.assertRaises(AuthenticationRequired):
            actor_from_auth_context(self.context(replace(self.principal, active=False)))

    def test_truthy_non_boolean_active_is_rejected(self):
        for active in (1, "true"):
            with self.subTest(active=active), self.assertRaises(AuthenticationRequired):
                actor_from_auth_context(self.context(replace(self.principal, active=active)))

    def test_session_identity_mismatch_is_rejected(self):
        with self.assertRaises(AuthenticationRequired):
            actor_from_auth_context(self.context(session=replace(self.session, user_id="another-user")))

    def test_revoked_session_is_rejected(self):
        with self.assertRaises(AuthenticationRequired):
            actor_from_auth_context(self.context(session=replace(self.session, revoked=True)))

    def test_request_json_cannot_be_used_as_auth_context(self):
        with self.assertRaises(AuthenticationRequired):
            actor_from_auth_context({"user_id": USER, "role": "master", "section_ids": [SECTION]})

    def test_malformed_principal_and_session_are_rejected(self):
        for context in (AuthContext({}, self.session), AuthContext(self.principal, {})):
            with self.subTest(context_type=type(context)), self.assertRaises(AuthenticationRequired):
                actor_from_auth_context(context)

    def test_unknown_role_is_rejected(self):
        with self.assertRaises(AuthenticationRequired):
            actor_from_auth_context(self.context(replace(self.principal, role="superadmin")))

    def test_blank_user_or_malformed_section_set_is_rejected(self):
        cases = [replace(self.principal, user_id=" "),
                 replace(self.principal, section_ids=SECTION),
                 replace(self.principal, section_ids=frozenset({" "})),
                 replace(self.principal, section_ids=frozenset({None}))]
        for principal in cases:
            with self.subTest(principal=principal), self.assertRaises(AuthenticationRequired):
                actor_from_auth_context(self.context(principal))

    def test_empty_scope_is_preserved_and_domain_create_denied(self):
        actor = actor_from_auth_context(self.context(replace(self.principal, section_ids=frozenset())))
        self.assertEqual(actor.section_ids, frozenset())
        with self.assertRaises(DomainError):
            authorize(actor, SECTION, Action.CREATE, None)

    def test_master_scope_is_not_expanded_by_bridge(self):
        actor = actor_from_auth_context(self.context())
        authorize(actor, SECTION, Action.CREATE, None)
        with self.assertRaises(DomainError):
            authorize(actor, OTHER_SECTION, Action.CREATE, None)

    def test_manager_and_admin_do_not_gain_master_write(self):
        for role in (AuthRole.MANAGER, AuthRole.ADMIN):
            with self.subTest(role=role), self.assertRaises(DomainError):
                actor = actor_from_auth_context(self.context(replace(self.principal, role=role)))
                authorize(actor, SECTION, Action.CREATE, None)

    def test_new_request_uses_current_store_role_and_sections(self):
        principals = Store(self.principal)
        before = authenticate_session("synthetic-handle", sessions=Store(self.session),
                                      principals=principals, real_clock=Clock())
        old_actor = actor_from_auth_context(before)
        principals.value = replace(self.principal, role=AuthRole.MANAGER,
                                   section_ids=frozenset({OTHER_SECTION}))
        after = authenticate_session("synthetic-handle", sessions=Store(self.session),
                                     principals=principals, real_clock=Clock())
        new_actor = actor_from_auth_context(after)
        self.assertEqual(old_actor.section_ids, frozenset({SECTION}))
        self.assertEqual(new_actor.section_ids, frozenset({OTHER_SECTION}))
        self.assertIs(new_actor.role, DomainRole.MANAGER)
        with self.assertRaises(DomainError):
            authorize(new_actor, OTHER_SECTION, Action.CREATE, None)

    def test_new_request_rechecks_account_deactivation_before_bridge(self):
        principals = Store(replace(self.principal, active=False))
        with self.assertRaises(AuthenticationRequired):
            context = authenticate_session("synthetic-handle", sessions=Store(self.session),
                                           principals=principals, real_clock=Clock())
            actor_from_auth_context(context)


if __name__ == "__main__":
    unittest.main()
