"""Real disposable PostgreSQL provisioning/login checks, never a fake pass."""
import argparse
from contextlib import ExitStack
import os
import secrets
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare_demo_database import apply_fresh, migration_plan
from provision_synthetic_demo import apply_fixture, FixtureConflict, IDENTITY

PINS = {role: "".join(secrets.SystemRandom().sample("0123456789", 8)) for role in ("master", "executor")}
ORIGIN = "https://demo-provisioning.test"


class DemoPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = ("DALA_TEST_DATABASE_URL", "DALA_ACCEPTANCE_RUNTIME_DATABASE_URL", "DALA_DEMO_TEST_BACKEND")
        if any(not os.environ.get(name) for name in required) or os.environ.get("DALA_ACCEPTANCE_DISPOSABLE") != "1":
            raise unittest.SkipTest("NOTRUN: explicit local disposable DB, existing runtime LOGIN and backend are required")
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row
        from psycopg.conninfo import conninfo_to_dict
        for name in required[:2]:
            values = conninfo_to_dict(os.environ[name])
            host = values.get("host", "")
            if (not host or "," in host or not values.get("dbname")
                    or values.get("service") or values.get("servicefile")
                    or values.get("hostaddr") not in {None, "", "127.0.0.1", "::1"}
                    or (host not in {"localhost", "127.0.0.1", "::1"} and not host.startswith("/"))):
                raise ValueError("PostgreSQL provisioning tests require an explicit local disposable DSN")
        if any(os.environ.get(name) for name in ("PGSERVICE", "PGSERVICEFILE", "PGHOSTADDR")):
            raise ValueError("Ambient PostgreSQL service/hostaddr indirection is not allowed in tests")
        cls.pg, cls.sql, cls.dict_row = psycopg, sql, staticmethod(dict_row)
        cls.backend = Path(os.environ["DALA_DEMO_TEST_BACKEND"]).resolve()
        sys.path.insert(0, str(cls.backend))
        cls.plan = migration_plan(cls.backend)

    def setUp(self):
        self.schema = "demo_fixture_" + uuid4().hex
        self.env = patch.dict(os.environ, {"DALA_API_MODE": "demo", "DALA_DEMO_SEED_ALLOWED": "1",
            "DALA_DEMO_OWNER_DATABASE_URL": os.environ["DALA_TEST_DATABASE_URL"],
            "DALA_DEMO_RUNTIME_DATABASE_URL": os.environ["DALA_ACCEPTANCE_RUNTIME_DATABASE_URL"]})
        self.env.start()
        self.addCleanup(self.env.stop)
        with self.pg.connect(os.environ["DALA_TEST_DATABASE_URL"], autocommit=True) as db:
            self.database = db.execute("SELECT current_database()").fetchone()[0]
        self.addCleanup(self.drop_schema)
        self.args = argparse.Namespace(backend=self.backend, schema=self.schema, expected_database=self.database)
        result, code = apply_fresh(self.args, self.plan)
        self.assertEqual(code, 0, result)
        self.assertEqual(result["runtime_validation"], "PASS")

    def connect(self, runtime=False):
        variable = "DALA_ACCEPTANCE_RUNTIME_DATABASE_URL" if runtime else "DALA_TEST_DATABASE_URL"
        return self.pg.connect(os.environ[variable], autocommit=True, row_factory=self.dict_row,
                               options=f"-c search_path={self.schema}")

    def drop_schema(self):
        with self.pg.connect(os.environ["DALA_TEST_DATABASE_URL"], autocommit=True) as db:
            db.execute(self.sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(self.sql.Identifier(self.schema)))

    def test_fresh_seed_is_idempotent_and_both_real_logins_use_scoped_references(self):
        initial = apply_fixture(self.connect, self.database, PINS)
        self.assertEqual(initial["status"], "APPLIED")
        self.assertEqual(initial["created_rows"]["employees"], 2)
        second = apply_fixture(self.connect, self.database, PINS)
        self.assertEqual(second["status"], "ALREADY_PRESENT")
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) AS n FROM orders").fetchone()["n"], 0)
            self.assertEqual(db.execute("SELECT count(*) AS n FROM auth_sessions").fetchone()["n"], 0)
        # The tested app receives explicit demo settings. Never configure an
        # unused module-global app from the owner-only bootstrap environment.
        with patch.dict(os.environ, {"DALA_API_MODE": "health"}):
            from app.main import create_app
        from app.runtime import RuntimeSettings
        from fastapi.testclient import TestClient
        settings = RuntimeSettings(mode="demo", database_url=os.environ["DALA_ACCEPTANCE_RUNTIME_DATABASE_URL"],
                                   allowed_origin=ORIGIN, database_schema=self.schema)
        app = create_app(settings=settings, connect=lambda: self.connect(runtime=True))
        with ExitStack() as stack:
            for role in ("master", "executor"):
                client = stack.enter_context(TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 44000)))
                login = client.post("/api/v1/auth/login", json={"employee_code": f"DALA-DEMO-{role.upper()}", "pin": PINS[role]}, headers={"Origin": ORIGIN})
                self.assertEqual(login.status_code, 200)
                self.assertEqual(login.json()["principal"]["user_id"], IDENTITY[role])
                catalogues = client.get("/api/v1/dicts")
                self.assertEqual(catalogues.status_code, 200)
                self.assertEqual([row["id"] for row in catalogues.json()["sections"]], [IDENTITY["section"]])

    def test_reseed_with_another_pin_fails_without_resetting_credentials(self):
        apply_fixture(self.connect, self.database, PINS)
        with self.connect() as db:
            before = db.execute("SELECT id::text,pin_hash FROM employees ORDER BY id").fetchall()
        with self.assertRaises(FixtureConflict):
            apply_fixture(self.connect, self.database, dict(PINS, executor=PINS["executor"] + "1"))
        with self.connect() as db:
            after = db.execute("SELECT id::text,pin_hash FROM employees ORDER BY id").fetchall()
        self.assertTrue(before == after, "Reseeding changed an existing PIN hash or identity")

    def test_reseed_never_restores_revoked_membership_or_deleted_account(self):
        apply_fixture(self.connect, self.database, PINS)
        with self.connect() as db:
            db.execute("DELETE FROM employee_sections WHERE employee_id=%s", (IDENTITY["executor"],))
        with self.assertRaises(FixtureConflict):
            apply_fixture(self.connect, self.database, PINS)
        with self.connect() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM employee_sections WHERE employee_id=%s", (IDENTITY["executor"],)).fetchone())
            db.execute("DELETE FROM employees WHERE id=%s", (IDENTITY["executor"],))
        with self.assertRaises(FixtureConflict):
            apply_fixture(self.connect, self.database, PINS)
        with self.connect() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM employees WHERE id=%s", (IDENTITY["executor"],)).fetchone())

    def test_launcher_repeats_only_ready_marker_and_refuses_foreign_schema_or_wrong_database(self):
        result, code = apply_fresh(self.args, self.plan)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "EXISTING_DEMO_SCHEMA_VERIFIED")
        self.assertFalse(result["migrations_replayed"])
        self.assertFalse(result["grants_replayed"])
        with self.connect() as db:
            db.execute(self.sql.SQL("COMMENT ON SCHEMA {} IS 'unrecognized fixture'").format(self.sql.Identifier(self.schema)))
        with self.assertRaisesRegex(ValueError, "without the exact ready marker"):
            apply_fresh(self.args, self.plan)
        fresh = argparse.Namespace(backend=self.backend, schema="demo_fixture_" + uuid4().hex,
                                   expected_database=self.database + "_wrong")
        with self.assertRaisesRegex(ValueError, "does not match"):
            apply_fresh(fresh, self.plan)
        with self.connect() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (fresh.schema,)).fetchone())


if __name__ == "__main__":
    unittest.main()
