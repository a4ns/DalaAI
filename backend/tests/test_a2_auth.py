import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app.core.auth_policy import (
    AccessDenied, OrderAction, OrderScope, PhotoScope, Principal, Role,
    StagedPhotoScope, require_create_order, require_demo_management,
    require_dictionary_write, require_order_access, require_photo_read,
    require_section_report, require_staged_attachment, require_staged_photo_read,
)
from app.core.auth_boundary import (
    AuthenticationRequired, RequestProtection, SessionRecord, authenticate_session,
    SESSION_COOKIE_NAME, SESSION_COOKIE_OPTIONS,
)

NOW = datetime(2026, 10, 7, 17, 0, tzinfo=timezone.utc)
ORDER = OrderScope("order-1", "section-1", "worker-1", 2)
MASTER = Principal("master-1", Role.MASTER, frozenset({"section-1"}))
EXECUTOR = Principal("worker-1", Role.EXECUTOR, frozenset({"section-1"}))
MANAGER = Principal("manager-1", Role.MANAGER, frozenset({"section-1"}))
ADMIN = Principal("admin-1", Role.ADMIN, frozenset({"section-1"}))


class PolicyTests(unittest.TestCase):
    def test_complete_role_action_matrix(self):
        reads = {"read", "events", "report"}
        master = reads | {"reassign", "cancel", "change_priority", "review", "upload"}
        executor = reads | {"accept", "queue", "reject", "start", "pause", "resume", "submit", "upload"}
        for principal, allowed in ((MASTER, master), (EXECUTOR, executor), (MANAGER, reads), (ADMIN, set())):
            for action in OrderAction:
                with self.subTest(role=principal.role, action=action):
                    if action in allowed:
                        require_order_access(principal, action, ORDER)
                    else:
                        with self.assertRaises(AccessDenied):
                            require_order_access(principal, action, ORDER)

    def test_foreign_section_denies_every_role_and_action(self):
        for principal in (MASTER, EXECUTOR, MANAGER, ADMIN):
            for action in OrderAction:
                with self.subTest(role=principal.role, action=action), self.assertRaises(AccessDenied):
                    require_order_access(principal, action, replace(ORDER, section_id="section-2"))

    def test_executor_cannot_access_foreign_assignment(self):
        for action in OrderAction:
            with self.subTest(action=action), self.assertRaises(AccessDenied):
                require_order_access(EXECUTOR, action, replace(ORDER, executor_id="worker-2"))

    def test_deactivated_account_denied(self):
        for principal in (MASTER, EXECUTOR, MANAGER, ADMIN):
            with self.assertRaises(AccessDenied):
                require_order_access(replace(principal, active=False), "read", ORDER)

    def test_unknown_action_and_role_denied(self):
        with self.assertRaises(AccessDenied):
            require_order_access(MASTER, "become_admin", ORDER)
        for old_alias in ("priority", "close", "rework"):
            with self.assertRaises(AccessDenied):
                require_order_access(MASTER, old_alias, ORDER)
        with self.assertRaises(AccessDenied):
            require_order_access(replace(MASTER, role="superuser"), "read", ORDER)

    def test_create_master_only_and_scoped(self):
        require_create_order(MASTER, "section-1")
        for principal in (EXECUTOR, MANAGER, ADMIN):
            with self.assertRaises(AccessDenied):
                require_create_order(principal, "section-1")
        with self.assertRaises(AccessDenied):
            require_create_order(MASTER, "section-2")

    def test_section_reports_and_dictionary_scope(self):
        for principal in (MASTER, MANAGER):
            require_section_report(principal, "section-1")
            with self.assertRaises(AccessDenied):
                require_section_report(principal, "section-2")
        for principal in (EXECUTOR, ADMIN):
            with self.assertRaises(AccessDenied):
                require_section_report(principal, "section-1")
        require_dictionary_write(ADMIN, "section-1")
        with self.assertRaises(AccessDenied):
            require_dictionary_write(MASTER, "section-1")
        with self.assertRaises(AccessDenied):
            require_dictionary_write(ADMIN, "section-2")

    def test_demo_requires_explicit_flag_and_admin(self):
        require_demo_management(ADMIN, demo_enabled=True)
        for principal in (MASTER, EXECUTOR, MANAGER, replace(ADMIN, active=False)):
            with self.assertRaises(AccessDenied):
                require_demo_management(principal, demo_enabled=True)
        with self.assertRaises(AccessDenied):
            require_demo_management(ADMIN, demo_enabled=False)

    def test_bound_photo_requires_current_order_and_matching_section(self):
        photo = PhotoScope("photo-1", "section-1", "order-1")
        require_photo_read(EXECUTOR, photo, ORDER)
        for bad_photo in (replace(photo, order_id="order-2"), replace(photo, section_id="section-2")):
            with self.assertRaises(AccessDenied):
                require_photo_read(MASTER, bad_photo, ORDER)
        with self.assertRaises(AccessDenied):
            require_photo_read(EXECUTOR, photo, replace(ORDER, executor_id="worker-2"))

    def test_before_stage_master_owns_and_not_expired(self):
        photo = StagedPhotoScope("stage-1", "section-1", MASTER.user_id, NOW + timedelta(seconds=1), "before")
        require_staged_attachment(MASTER, photo, section_id="section-1", real_now=NOW)
        variants = (replace(photo, uploader_id="master-2"), replace(photo, section_id="section-2"),
                    replace(photo, expires_at=NOW), replace(photo, kind="after"),
                    replace(photo, order_id="other"), replace(photo, assignment_revision=2),
                    replace(photo, expires_at=NOW.replace(tzinfo=None)))
        for variant in variants:
            with self.subTest(variant=variant), self.assertRaises(AccessDenied):
                require_staged_attachment(MASTER, variant, section_id="section-1", real_now=NOW)
        with self.assertRaises(AccessDenied):
            require_staged_attachment(EXECUTOR, replace(photo, uploader_id=EXECUTOR.user_id), section_id="section-1", real_now=NOW)

    def test_after_stage_current_assignment_revision_and_owner(self):
        photo = StagedPhotoScope("stage-2", "section-1", EXECUTOR.user_id,
                                 NOW + timedelta(minutes=5), "after", "order-1", 2)
        require_staged_attachment(EXECUTOR, photo, section_id="section-1", real_now=NOW, order=ORDER)
        for variant in (replace(photo, assignment_revision=1), replace(photo, order_id="other"),
                        replace(photo, uploader_id=MASTER.user_id), replace(photo, kind="before")):
            with self.subTest(variant=variant), self.assertRaises(AccessDenied):
                require_staged_attachment(EXECUTOR, variant, section_id="section-1", real_now=NOW, order=ORDER)
        with self.assertRaises(AccessDenied):
            require_staged_attachment(EXECUTOR, photo, section_id="section-1", real_now=NOW,
                                      order=replace(ORDER, executor_id="worker-2"))

    def test_staged_download_is_owner_only_and_rechecks_assignment(self):
        photo = StagedPhotoScope("stage-2", "section-1", EXECUTOR.user_id,
                                 NOW + timedelta(minutes=5), "after", "order-1", 2)
        require_staged_photo_read(EXECUTOR, photo, real_now=NOW, order=ORDER)
        for principal in (MASTER, MANAGER, ADMIN):
            with self.assertRaises(AccessDenied):
                require_staged_photo_read(principal, photo, real_now=NOW, order=ORDER)
        with self.assertRaises(AccessDenied):
            require_staged_photo_read(EXECUTOR, photo, real_now=NOW)
        with self.assertRaises(AccessDenied):
            require_staged_photo_read(EXECUTOR, photo, real_now=NOW,
                                      order=replace(ORDER, executor_id="worker-2"))


class Clock:
    def __init__(self, now=NOW):
        self.value = now

    def now(self):
        return self.value


class Store:
    def __init__(self, mapping):
        self.mapping = mapping

    def lookup(self, key):
        return self.mapping.get(key)


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.session = SessionRecord(MASTER.user_id, NOW - timedelta(minutes=1),
                                     NOW + timedelta(minutes=1), "synthetic-csrf-only-not-a-real-token")
        self.sessions = Store({"synthetic-session-only": self.session})
        self.principals = Store({MASTER.user_id: MASTER})
        self.protection = RequestProtection("https://demo.example")

    def authenticate(self, handle="synthetic-session-only"):
        return authenticate_session(handle, sessions=self.sessions,
                                    principals=self.principals, real_clock=self.clock)

    def test_valid_session_uses_current_principal(self):
        self.assertEqual(self.authenticate().principal, MASTER)
        self.principals.mapping[MASTER.user_id] = replace(MASTER, role=Role.MANAGER)
        self.assertEqual(self.authenticate().principal.role, Role.MANAGER)

    def test_missing_unknown_oversized_session(self):
        for handle in (None, "", "unknown", "x" * 513):
            with self.subTest(handle_length=len(handle or "")), self.assertRaises(AuthenticationRequired):
                self.authenticate(handle)

    def test_expired_revoked_invalid_time_sessions(self):
        variants = (replace(self.session, expires_at=NOW), replace(self.session, revoked=True),
                    replace(self.session, created_at=NOW + timedelta(seconds=1)),
                    replace(self.session, expires_at=NOW.replace(tzinfo=None)),
                    replace(self.session, csrf_token=""))
        for variant in variants:
            self.sessions.mapping["synthetic-session-only"] = variant
            with self.subTest(variant=variant), self.assertRaises(AuthenticationRequired):
                self.authenticate()

    def test_current_account_disabled_missing_or_mismatched(self):
        for principal in (replace(MASTER, active=False), replace(MASTER, user_id="other"), None):
            self.principals.mapping[MASTER.user_id] = principal
            with self.assertRaises(AuthenticationRequired):
                self.authenticate()

    def test_real_clock_expiry_boundary(self):
        self.authenticate()
        self.clock.value += timedelta(minutes=1)
        with self.assertRaises(AuthenticationRequired):
            self.authenticate()

    def test_naive_clock_rejected(self):
        self.clock.value = NOW.replace(tzinfo=None)
        with self.assertRaises(AuthenticationRequired):
            self.authenticate()

    def test_mutating_methods_require_origin_and_bound_csrf(self):
        context = self.authenticate()
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            self.protection.require_http(context, method=method, origin="https://demo.example", csrf_token=self.session.csrf_token)
            for origin in (None, "null", "https://demo.example.attacker.test", "http://demo.example", "https://demo.example/", "https://other.example"):
                with self.subTest(method=method, origin=origin), self.assertRaises(AccessDenied):
                    self.protection.require_http(context, method=method, origin=origin, csrf_token=self.session.csrf_token)
            for csrf in (None, "", "foreign-session-csrf", "☃", "x" * 513):
                with self.subTest(method=method, csrf=csrf), self.assertRaises(AccessDenied):
                    self.protection.require_http(context, method=method, origin="https://demo.example", csrf_token=csrf)

    def test_read_and_unknown_methods(self):
        context = self.authenticate()
        for method in ("GET", "HEAD", "OPTIONS"):
            self.protection.require_http(context, method=method, origin=None, csrf_token=None)
        for method in ("TRACE", "CONNECT", "post", "UNKNOWN"):
            with self.assertRaises(AccessDenied):
                self.protection.require_http(context, method=method, origin="https://demo.example", csrf_token=self.session.csrf_token)

    def test_origin_configuration_requires_exact_https_origin(self):
        for value in ("http://demo.example", "https://demo.example/", "https://user:pass@demo.example", "https://*.example", "https://demo.example?q=1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                RequestProtection(value)

    def test_websocket_login_origin_checks(self):
        self.protection.require_origin("https://demo.example")
        with self.assertRaises(AccessDenied):
            self.protection.require_origin(None)

    def test_session_and_csrf_are_not_in_repr(self):
        self.assertNotIn(self.session.csrf_token, repr(self.session))
        self.assertNotIn(self.session.csrf_token, repr(self.authenticate()))

    def test_cookie_settings_secure_host_only(self):
        self.assertEqual(SESSION_COOKIE_NAME, "__Host-naryadai_session")
        self.assertEqual(SESSION_COOKIE_OPTIONS, {"secure": True, "httponly": True, "samesite": "strict", "path": "/"})
        self.assertNotIn("domain", SESSION_COOKIE_OPTIONS)


if __name__ == "__main__":
    unittest.main()
