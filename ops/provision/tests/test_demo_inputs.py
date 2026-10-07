"""Preparation checks only; these cannot certify database provisioning."""
import argparse
import json
import secrets
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from provision_synthetic_demo import IDENTITY, preflight_apply, public_manifest, read_pins, schema_name
from prepare_demo_database import MIGRATIONS, migration_plan
from database_profile import UPDATE_COLUMNS


class DemoInputTests(unittest.TestCase):
    def test_stable_minimal_synthetic_manifest_has_no_business_history(self):
        a, b = public_manifest(), public_manifest()
        self.assertEqual(a, b)
        self.assertEqual(len(a["users"]), 2)
        self.assertEqual(a["orders_seeded"], 0)
        self.assertEqual(a["sessions_seeded"], 0)
        self.assertEqual(a["photos_seeded"], 0)
        self.assertFalse(a["historical_dataset"])
        self.assertTrue(all(UUID(value).version == 5 for value in IDENTITY.values()))
        self.assertEqual(a["users"][0]["section_ids"], [a["section"]["id"]])

    def test_schema_is_one_bounded_identifier(self):
        self.assertEqual(schema_name("dalaai_demo"), "dalaai_demo")
        for value in ("", "public,other", "UPPER", "x;DROP SCHEMA public", "x" * 64):
            with self.assertRaises(ValueError):
                schema_name(value)

    def test_apply_is_explicit_and_never_infers_a_database(self):
        args = argparse.Namespace(expected_database=None)
        with self.assertRaises(ValueError):
            preflight_apply(args, {})
        with self.assertRaises(ValueError):
            preflight_apply(args, {"DALA_API_MODE": "demo", "DALA_DEMO_SEED_ALLOWED": "1",
                                  "DALA_DEMO_OWNER_DATABASE_URL": "private-not-printed"})

    def test_private_pins_are_distinct_and_public_test_pin_is_rejected(self):
        values = ["".join(secrets.SystemRandom().sample("0123456789", 8)) for _ in range(2)]
        while values[0] == values[1]:
            values[1] = "".join(secrets.SystemRandom().sample("0123456789", 8))
        environment = dict(zip(("DALA_DEMO_MASTER_PIN", "DALA_DEMO_EXECUTOR_PIN"), values))
        self.assertEqual(set(read_pins(environment)), {"master", "executor"})
        for pin in ("", "1234", "11111111", "71426839", "nondigit-test"):
            with self.assertRaises(ValueError):
                read_pins(dict(environment, DALA_DEMO_MASTER_PIN=pin))
        with self.assertRaises(ValueError):
            read_pins(dict(environment, DALA_DEMO_EXECUTOR_PIN=environment["DALA_DEMO_MASTER_PIN"]))

    def test_migration_plan_keeps_003_at_original_path_once(self):
        self.assertEqual([Path(path).name[:3] for path, _ in MIGRATIONS], ["001", "002", "003", "004"])
        self.assertIn("db/proposals/003_auth_rate_limits.sql", [path for path, _ in MIGRATIONS])
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(ValueError):
                migration_plan(root)
            (root / "db/migrations").mkdir(parents=True)
            (root / "db/migrations/003_auth_rate_limits.sql").write_text("-- never choose this silently")
            with self.assertRaisesRegex(ValueError, "duplicated or moved"):
                migration_plan(root)

    def test_grant_profile_excludes_sensitive_auth_and_validation_updates(self):
        self.assertEqual(UPDATE_COLUMNS["auth_sessions"], ("id", "revoked_at"))
        self.assertEqual(UPDATE_COLUMNS["employees"], ("id",))
        self.assertNotIn("file_valid", UPDATE_COLUMNS["photos"])
        self.assertEqual(UPDATE_COLUMNS["auth_login_limits"], ("window_started_at", "attempts"))

    def test_dry_run_never_opens_database_or_echoes_environment_pins(self):
        import os
        pins = ["".join(secrets.SystemRandom().sample("0123456789", 8)) for _ in range(2)]
        environment = dict(os.environ, DALA_DEMO_OWNER_DATABASE_URL="deliberately-invalid-private-dsn",
                           DALA_DEMO_MASTER_PIN=pins[0], DALA_DEMO_EXECUTOR_PIN=pins[1])
        command = [sys.executable, str(Path(__file__).resolve().parents[1] / "provision_synthetic_demo.py"),
                   "--backend", "/nonexistent/backend"]
        result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["status"], "DRY_RUN_NO_DATABASE_ACCESS")
        for secret in (environment["DALA_DEMO_OWNER_DATABASE_URL"], environment["DALA_DEMO_MASTER_PIN"], environment["DALA_DEMO_EXECUTOR_PIN"]):
            self.assertNotIn(secret, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
