"""Independent mounted-factory checks with explicit catalog/service models.

No real PostgreSQL claim. The catalog model exposes dangerous grants and records
all queries; the middleware probes run the actual ASGI factory/lifespan.
"""
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.main import create_app
from app.runtime import (INSERT_TABLES, REQUIRED_TRIGGERS, TABLE_COLUMNS, UPDATE_COLUMNS,
                         RuntimePrerequisiteError, RuntimeSettings, UnavailablePhotoReferences,
                         validate_database)
from app.ai.models import PhotoEvidence

ORIGIN = "https://naryadai.test"


class CatalogModel:
    autocommit = True
    def __init__(self, *, dangerous=None, additional_insert=None, additional_update=None,
                 missing_guard=None, owns=False, direct_login=True):
        self.dangerous = dangerous
        self.additional_insert = additional_insert
        self.additional_update = additional_update
        self.missing_guard = missing_guard
        self.owns = owns
        self.direct_login = direct_login
        self.queries = []
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def execute(self, query, params=()):
        query = query.as_string() if hasattr(query, "as_string") else query
        q = " ".join(query.split())
        self.queries.append((q, params))
        value, rows = None, []
        if "current_user=session_user" in q:
            value = {"direct_login": self.direct_login, "rolsuper": False, "rolcreatedb": False,
                     "rolcreaterole": False, "rolbypassrls": False, "can_create": False}
        elif " AS owns" in q:
            value = {"owns": self.owns}
        elif "FROM pg_trigger" in q:
            rows = [{"relname": table, "tgname": trigger} for table, trigger in REQUIRED_TRIGGERS
                    if (table, trigger) != self.missing_guard]
        elif "FROM pg_attribute" in q:
            table = params[0]
            names = set(TABLE_COLUMNS[table]) | set(UPDATE_COLUMNS.get(table, ()))
            # Extra columns exercise a full deny-by-default column scan, not just
            # the minimum required columns maintained in TABLE_COLUMNS.
            if self.additional_update and self.additional_update[0] == table:
                names.add(self.additional_update[1])
            rows = [{"attname": name} for name in names]
        elif "has_table_privilege" in q:
            table = params[0]
            privilege = params[1] if len(params) > 1 else "INSERT"
            permitted = ((privilege == "INSERT" and (table in INSERT_TABLES or table == self.additional_insert))
                         or (table, privilege) == self.dangerous)
            value = {"ok": permitted}
        elif "has_column_privilege" in q:
            table, column = params
            value = {"ok": column in UPDATE_COLUMNS.get(table, ()) or (table, column) == self.additional_update}
        elif "has_sequence_privilege" in q:
            value = {"ok": True}
        elif q.startswith("SELECT ") and q.endswith(" LIMIT 0"):
            pass
        else:
            raise AssertionError("Catalog model has no response for: " + q)
        return SimpleNamespace(fetchone=lambda: value, fetchall=lambda: rows)


class CatalogSecurityProbes(unittest.TestCase):
    def test_expected_catalog_only_performs_reads(self):
        db = CatalogModel()
        validate_database(lambda: db)
        self.assertTrue(db.queries)
        self.assertTrue(all(q.startswith("SELECT ") for q, _ in db.queries))

    def test_destructive_table_grants_rejected(self):
        for privilege in ["TRUNCATE", "DELETE", "TRIGGER"]:
            with self.subTest(privilege=privilege), self.assertRaises(RuntimePrerequisiteError) as error:
                validate_database(lambda: CatalogModel(dangerous=("order_events", privilege)))
            self.assertEqual(error.exception.code, "FORBIDDEN_GRANT")

    def test_unexpected_insert_and_security_column_update_rejected(self):
        cases = [dict(additional_insert="employees"), dict(additional_insert="photos"),
                 dict(additional_update=("auth_sessions", "expires_at")),
                 dict(additional_update=("auth_sessions", "created_at")),
                 dict(additional_update=("employees", "employee_code"))]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(RuntimePrerequisiteError) as error:
                validate_database(lambda: CatalogModel(**kwargs))
            self.assertEqual(error.exception.code, "FORBIDDEN_GRANT")

    def test_owner_assumed_role_and_missing_guard_rejected(self):
        for kwargs, expected in [(dict(owns=True), "ROLE_OWNS_OBJECTS"),
                                 (dict(direct_login=False), "ROLE_NOT_RESTRICTED"),
                                 (dict(missing_guard=("employee_sections", "employee_sections_ownership_immutable")), "REQUIRED_GUARD_MISSING")]:
            with self.subTest(kwargs=kwargs), self.assertRaises(RuntimePrerequisiteError) as error:
                validate_database(lambda: CatalogModel(**kwargs))
            self.assertEqual(error.exception.code, expected)


class MountedAdmissionProbes(unittest.TestCase):
    def settings(self):
        return RuntimeSettings("demo", "synthetic-secret-marker", ORIGIN, "review_schema")

    def test_unstarted_demo_api_returns_contract_problem_without_connecting(self):
        connector = Mock(side_effect=AssertionError("Connection must not run before lifespan"))
        app = create_app(settings=self.settings(), connect=connector)
        client = TestClient(app, base_url=ORIGIN)
        response = client.get("/api/v1/me")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "TEMPORARILY_UNAVAILABLE")
        self.assertTrue(response.json()["retryable"])
        self.assertEqual(response.headers["retry-after"], "1")
        connector.assert_not_called()

    def test_known_guard_failure_latches_api_and_repair_alone_does_not_recover(self):
        def validate(_):
            if failed[0]:
                raise RuntimePrerequisiteError("REQUIRED_GUARD_MISSING")
        failed = [False]
        with patch("app.main.validate_database", side_effect=validate), \
             patch("app.sessions.service.SessionService.me", return_value={"stub": True}) as route:
            app = create_app(settings=self.settings(), connect=Mock())
            with TestClient(app, base_url=ORIGIN) as client:
                self.assertTrue(app.state.runtime_ready)
                failed[0] = True
                self.assertEqual(client.get("/readyz").status_code, 503)
                self.assertFalse(app.state.runtime_ready)
                self.assertEqual(client.get("/api/v1/me", headers={"cookie": "__Host-naryadai_session=synthetic"}).status_code, 503)
                failed[0] = False
                self.assertEqual(client.get("/readyz").status_code, 503)
                self.assertEqual(client.get("/healthz").status_code, 200)
                route.assert_not_called()

    def test_readiness_timeout_latches_and_late_worker_cannot_reenable(self):
        calls = []
        def validate(_):
            calls.append(1)
            if len(calls) > 1:
                time.sleep(0.08)
        with patch("app.main.validate_database", side_effect=validate), \
             patch("app.health.READINESS_TIMEOUT_SECONDS", 0.01):
            app = create_app(settings=self.settings(), connect=Mock())
            with TestClient(app, base_url=ORIGIN) as client:
                self.assertEqual(client.get("/readyz").status_code, 503)
                self.assertFalse(app.state.runtime_ready)
                time.sleep(0.12)
                self.assertFalse(app.state.runtime_ready)
                self.assertEqual(client.get("/api/v1/me").status_code, 503)

    def test_host_and_exact_origin_guard_remain_active_after_valid_startup(self):
        with patch("app.main.validate_database"), patch("app.sessions.service.SessionService.login") as login:
            app = create_app(settings=self.settings(), connect=Mock())
            with TestClient(app, base_url=ORIGIN) as client:
                self.assertEqual(client.get("/healthz", headers={"host": "foreign.test"}).status_code, 400)
                response = client.post("/api/v1/auth/login", json={"employee_code": "synthetic", "pin": "1234"},
                                       headers={"origin": "https://evil.test"})
                self.assertEqual(response.status_code, 403)
                login.assert_not_called()

    def test_unavailable_blob_boundary_does_not_trust_database_true_flag(self):
        original = PhotoEvidence("p", "o", "s", 1, "after", True)
        with patch("app.persistence.postgres.PostgresReferences.closure_evidence",
                   return_value=(frozenset({"code"}), frozenset(), (original,))):
            reference = object.__new__(UnavailablePhotoReferences)
            _, _, photos = reference.closure_evidence(None)
        self.assertIsNone(photos[0].file_valid)
        self.assertTrue(original.file_valid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
