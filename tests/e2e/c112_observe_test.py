"""Source-only observer contracts. No database connection or credential-file read."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("c112_observe", Path(__file__).with_name("c112_observe.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ObserverContracts(unittest.TestCase):
    def env(self):
        return {"DALA_C112_AUTHORIZED": "operator-provisioned-synthetic-only",
                "DALA_C112_DATABASE_SCHEMA": "c112_synthetic_test",
                "DALA_C112_OBSERVER_DATABASE_URL": "postgresql://observer:dummy-only@127.0.0.1/demo"}

    def test_explicit_dummy_environment(self):
        self.assertEqual(m.validate_environment(self.env())[1], "c112_synthetic_test")

    def test_no_inherited_credentials_or_libpq_options(self):
        for key in ("PGPASSWORD", "PGPASSFILE", "PGSERVICE", "PGOPTIONS", "PGHOST"):
            with self.subTest(key=key), self.assertRaises(m.Blocked):
                m.validate_environment({**self.env(), key: "dummy"})

    def test_no_remote_socket_owner_override_or_file_fallback(self):
        for dsn in ("postgresql://observer:dummy-only@example.com/demo", "postgresql:///demo",
                    "postgresql://observer@localhost/demo", "postgresql://observer:dummy-only@localhost/demo?passfile=/private",
                    "postgresql://observer:dummy-only@localhost/demo?host=elsewhere",
                    "postgresql://observer:dummy-only@localhost/demo?sslmode=disable&sslmode=require"):
            with self.subTest(dsn=dsn), self.assertRaises(m.Blocked):
                m.validate_environment({**self.env(), "DALA_C112_OBSERVER_DATABASE_URL": dsn})

    def test_system_schemas_and_unapproved_identity_are_rejected(self):
        for schema in ("public", "information_schema", "pg_catalog", "bad;drop schema", ""):
            with self.subTest(schema=schema), self.assertRaises(m.Blocked):
                m.validate_environment({**self.env(), "DALA_C112_DATABASE_SCHEMA": schema})
        with self.assertRaises(m.Blocked):
            m.validate_environment({**self.env(), "DALA_C112_AUTHORIZED": ""})

    def test_sql_source_is_read_only_and_never_reads_auth_secrets(self):
        source = Path(m.__file__).read_text()
        self.assertIn("REPEATABLE READ READ ONLY", source)
        self.assertIn('passfile="/dev/null"', source)
        self.assertNotIn("FROM auth_sessions", source)
        self.assertNotIn("SELECT pin_hash", source)
        self.assertNotIn("read_text()", source)
        self.assertNotIn("read_bytes()", source)
        self.assertNotIn("print(error)", source)
        self.assertEqual(set(m.TABLES), {"orders", "order_events", "submissions", "reviews", "photos", "material_writeoffs", "ai_assessments", "operation_receipts"})


if __name__ == "__main__":
    unittest.main()
