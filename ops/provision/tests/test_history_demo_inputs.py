"""Offline source/contract checks; never database or deployment evidence."""
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "ops/provision"))
import history_demo as fixture
from provision_synthetic_demo import public_manifest as minimal_manifest


class HistoryInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loader, cls.history, cls.raw, cls.mapping = fixture.canonical_inputs()

    def test_exact_unchanged_canonical_history_and_identity_mapping(self):
        self.assertEqual(sha256(self.raw).hexdigest(), fixture.HISTORY_SHA256)
        self.assertEqual(len(self.history["orders"]), 540)
        self.assertEqual(self.mapping, {row["employee_code"]: row["id"] for row in self.history["employees"]})
        self.assertTrue(set(self.mapping.values()).isdisjoint(fixture.IDENTITY.values()))

    def test_live_master_has_all_history_sections_executor_one_canonical_section(self):
        manifest = fixture.public_manifest(self.history)
        master, executor = manifest["users"]
        self.assertEqual(set(master["section_ids"]), {row["id"] for row in self.history["sections"]})
        self.assertEqual(len(executor["section_ids"]), 1)
        self.assertEqual(executor["section_ids"], [manifest["live_path"]["section_id"]])
        self.assertIn(manifest["live_path"]["equipment_id"],
                      {row["id"] for row in self.history["equipment"] if row["section_id"] in executor["section_ids"]})
        self.assertEqual(manifest["historical_actor_state"], "disabled_no_login")
        self.assertEqual(manifest["live_orders_seeded"], 0)
        self.assertEqual(manifest["sessions_seeded"], 0)
        self.assertEqual(manifest["photos_seeded"], 0)

    def test_minimal_default_contract_unchanged_and_separate(self):
        minimal = minimal_manifest()
        self.assertFalse(minimal["historical_dataset"])
        self.assertEqual(minimal["orders_seeded"], 0)
        self.assertEqual(len(minimal["users"][0]["section_ids"]), 1)
        self.assertNotIn(minimal["section"]["id"], {row["id"] for row in self.history["sections"]})

    def test_receipt_binds_exact_scopes_and_state(self):
        manifest = fixture.public_manifest(self.history)
        changed = deepcopy(manifest)
        changed["users"][0]["section_ids"].pop()
        self.assertNotEqual(fixture.receipt(manifest, "complete"), fixture.receipt(changed, "complete"))
        self.assertNotEqual(fixture.receipt(manifest, "complete"), fixture.receipt(manifest, "initializing"))

    def test_pinned_source_edit_is_refused_before_execution(self):
        with TemporaryDirectory() as temp:
            target = Path(temp) / "scripts/synthetic/load_demo.py"
            target.parent.mkdir(parents=True)
            target.write_text("raise AssertionError('must not execute unreviewed code')\n")
            with self.assertRaisesRegex(fixture.FixtureConflict, "PINNED_SOURCE_MISMATCH"):
                fixture.canonical_inputs(temp)

    def test_invalid_pins_fail_before_database_connection(self):
        def forbidden():
            self.fail("Invalid operator input reached database")
        for pins in ({}, {"master": "71426839", "executor": "71426839"}):
            with self.assertRaises(ValueError):
                fixture.apply_fixture(forbidden, "unused", pins)

    def test_dry_plan_never_connects_or_prints_secrets(self):
        markers = {"DALA_DEMO_OWNER_DATABASE_URL": "private-invalid-dsn-must-not-be-opened",
                   "DALA_DEMO_MASTER_PIN": "private-master-must-not-be-printed",
                   "DALA_DEMO_EXECUTOR_PIN": "private-executor-must-not-be-printed"}
        result = subprocess.run([sys.executable, str(ROOT / "ops/provision/history_demo.py")],
                                capture_output=True, text=True, env=dict(os.environ, **markers), timeout=20)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["status"], "PLAN_ONLY_NO_DATABASE_ACCESS")
        for value in markers.values():
            self.assertNotIn(value, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
