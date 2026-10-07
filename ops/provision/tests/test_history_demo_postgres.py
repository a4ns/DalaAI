"""Explicit disposable PostgreSQL gate. No role/credential/provider creation.

Existing owner and restricted LOGIN are provided by A5's isolated runner using
the existing provisioning gate environment; add DALA_HISTORY_DEMO_DISPOSABLE=1.
Missing inputs fail rather than skip. --with-reports additionally requires the
accepted C111 report mount; baseline tests never claim analytics-route coverage.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import secrets
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "ops/provision"), str(Path(__file__).resolve().parent)]
import history_demo as history_fixture
import test_demo_postgres as baseline
from prepare_demo_database import worker_migration_plan
from provision_synthetic_demo import apply_fixture as minimal_fixture, FixtureConflict, IDENTITY

ORIGIN = "https://history-demo.test"
PINS = {role: "".join(secrets.SystemRandom().sample("0123456789", 8)) for role in ("master", "executor")}
while PINS["master"] == PINS["executor"] or "71426839" in PINS.values():
    PINS = {role: "".join(secrets.SystemRandom().sample("0123456789", 8)) for role in ("master", "executor")}


class HistoryDemoPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = ("DALA_TEST_DATABASE_URL", "DALA_ACCEPTANCE_RUNTIME_DATABASE_URL", "DALA_DEMO_TEST_BACKEND")
        if os.environ.get("DALA_HISTORY_DEMO_DISPOSABLE") != "1" or any(not os.environ.get(key) for key in required):
            raise RuntimeError("NOT_RUN: explicit disposable history opt-in and existing local owner/runtime inputs required")
        if os.environ.get("DALA_ACCEPTANCE_DISPOSABLE") != "1":
            raise RuntimeError("NOT_RUN: DALA_ACCEPTANCE_DISPOSABLE=1 is required")
        baseline.DemoPostgresTests.setUpClass()
        cls.loader, cls.history, cls.raw, cls.mapping = history_fixture.canonical_inputs()
        cls.manifest = history_fixture.public_manifest(cls.history)

    def setUp(self):
        self.f = baseline.DemoPostgresTests(methodName="runTest")
        self.addCleanup(self.f.doCleanups)
        self.f.setUp()

    def seed(self):
        return history_fixture.apply_fixture(self.f.connect, self.f.database, PINS)

    def query(self, statement, params=()):
        with self.f.connect() as db:
            return db.execute(statement, params).fetchall()

    def count(self, table):
        return self.query("SELECT count(*) AS n FROM " + table)[0]["n"]

    def app(self):
        with patch.dict(os.environ, {"DALA_API_MODE": "health"}):
            from app.main import create_app
        from app.runtime import RuntimeSettings
        settings = RuntimeSettings(mode="demo", database_url=os.environ["DALA_ACCEPTANCE_RUNTIME_DATABASE_URL"],
                                   allowed_origin=ORIGIN, database_schema=self.f.schema)
        return create_app(settings=settings, connect=lambda: self.f.connect(runtime=True))

    def login(self, stack, app, role):
        from fastapi.testclient import TestClient
        client = stack.enter_context(TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 45000)))
        response = client.post("/api/v1/auth/login", json={"employee_code": "DALA-DEMO-" + role.upper(),
                              "pin": PINS[role]}, headers={"Origin": ORIGIN})
        self.assertEqual(response.status_code, 200, "Real demo login failed")
        self.assertEqual(response.json()["principal"]["user_id"], IDENTITY[role])
        csrf = client.get("/api/v1/me").json()["csrf_token"]
        client.headers.update({"Origin": ORIGIN, "X-CSRF-Token": csrf})
        return client

    def test_fresh_history_exact_actors_and_verify_only_repeat(self):
        self.assertEqual(self.seed()["status"], "APPLIED")
        self.assertEqual(self.count("orders"), 540)
        self.assertEqual(self.count("employees"), 19)
        self.assertEqual(self.count("employee_sections"), 39)
        for table in ("photos", "auth_sessions", "ai_jobs", "delivery_jobs", "operation_receipts"):
            self.assertEqual(self.count(table), 0)
        self.assertEqual(self.seed()["status"], "ALREADY_PRESENT")
        rows = self.query("SELECT id,active,on_shift,pin_hash=%s AS locked FROM employees WHERE employee_code LIKE 'SYN-%%'",
                          (self.loader.DISABLED_PIN_SENTINEL,))
        self.assertEqual(len(rows), 17)
        self.assertTrue(all(not row["active"] and not row["on_shift"] and row["locked"] for row in rows))

    def test_existing_minimal_profile_is_refused_without_expanding_scopes(self):
        minimal_fixture(self.f.connect, self.f.database, PINS)
        before = self.query("SELECT employee_id,section_id FROM employee_sections ORDER BY employee_id,section_id")
        with self.assertRaisesRegex(FixtureConflict, "PROFILE_MISMATCH"):
            self.seed()
        self.assertEqual(before, self.query("SELECT employee_id,section_id FROM employee_sections ORDER BY employee_id,section_id"))
        self.assertEqual(self.count("orders"), 0)

    def test_pin_mismatch_revoked_scope_and_deleted_live_account_never_repaired(self):
        self.seed()
        with self.assertRaises(FixtureConflict):
            history_fixture.apply_fixture(self.f.connect, self.f.database, dict(PINS, master=PINS["master"] + "1"))
        self.query("DELETE FROM employee_sections WHERE employee_id=%s RETURNING employee_id", (IDENTITY["executor"],))
        with self.assertRaisesRegex(FixtureConflict, "LIVE_SCOPE_CHANGED"):
            self.seed()
        self.assertEqual(self.query("SELECT 1 FROM employee_sections WHERE employee_id=%s", (IDENTITY["executor"],)), [])
        self.query("DELETE FROM employees WHERE id=%s RETURNING id", (IDENTITY["executor"],))
        with self.assertRaisesRegex(FixtureConflict, "LIVE_ACCOUNT_CHANGED"):
            self.seed()
        self.assertEqual(self.query("SELECT 1 FROM employees WHERE id=%s", (IDENTITY["executor"],)), [])

    def test_changed_historical_actor_remains_changed_and_blocks_repeat(self):
        self.seed()
        actor = self.history["employees"][0]["id"]
        self.query("UPDATE employees SET active=true WHERE id=%s RETURNING id", (actor,))
        with self.assertRaisesRegex(FixtureConflict, "ACTOR_CHANGED"):
            self.seed()
        self.assertTrue(self.query("SELECT active FROM employees WHERE id=%s", (actor,))[0]["active"])

    def test_partial_initialization_and_wrong_database_fail_closed(self):
        with self.assertRaisesRegex(FixtureConflict, "DATABASE_MISMATCH"):
            history_fixture.apply_fixture(self.f.connect, self.f.database + "_wrong", PINS)
        loader, history, raw, mapping = history_fixture.canonical_inputs()
        # Explicit fault injection at the separately committed import boundary.
        with patch.object(loader, "load_demo", side_effect=RuntimeError("synthetic interrupted import")), \
                patch.object(history_fixture, "canonical_inputs", return_value=(loader, history, raw, mapping)):
            with self.assertRaises(RuntimeError):
                self.seed()
        with self.assertRaisesRegex(FixtureConflict, "NO_PARTIAL_RETRY"):
            self.seed()
        with self.assertRaises(ValueError):
            minimal_fixture(self.f.connect, self.f.database, PINS)
        self.assertEqual(self.count("employees"), 0)
        self.assertEqual(self.count("orders"), 0)

    def test_history_fixture_accepts_full_seven_migration_empty_schema(self):
        plan = worker_migration_plan(self.f.backend)
        with self.f.connect() as db:
            for migration in plan[4:]:
                db.execute((self.f.backend / migration["path"]).read_text())
        self.assertEqual(self.seed()["status"], "APPLIED")
        self.assertEqual(self.seed()["status"], "ALREADY_PRESENT")
        for table in ("push_subscriptions", "delivery_dispatches", "delivery_dispatch_results"):
            self.assertEqual(self.count(table), 0)

    def test_committed_history_without_final_accounts_is_preserved_and_not_retried(self):
        # Fault injection after C107's real successful commit, before live rows.
        with patch.object(history_fixture, "_verify_historical_actors", side_effect=RuntimeError("synthetic final-stage failure")):
            with self.assertRaises(RuntimeError):
                self.seed()
        self.assertEqual(self.count("orders"), 540)
        self.assertEqual(self.count("employees"), 17)
        with self.assertRaisesRegex(FixtureConflict, "NO_PARTIAL_RETRY"):
            self.seed()
        self.assertEqual(self.count("employees"), 17)

    def test_disabled_identity_guard_is_rejected_before_seeding(self):
        with self.f.connect() as db:
            db.execute("ALTER TABLE employee_sections DISABLE TRIGGER employee_sections_ownership_immutable")
        with self.assertRaisesRegex(FixtureConflict, "IDENTITY_GUARDS_REQUIRED"):
            self.seed()
        self.assertEqual(self.count("employees"), 0)
        self.assertEqual(self.count("orders"), 0)

    def test_master_sees_540_history_and_new_executor_runs_real_lifecycle(self):
        self.seed()
        with ExitStack() as stack:
            app = self.app()
            master = self.login(stack, app, "master")
            executor = self.login(stack, app, "executor")
            ids, cursor = set(), None
            for _ in range(10):
                params = {"limit": 100}
                if cursor:
                    params["cursor"] = cursor
                response = master.get("/api/v1/orders", params=params)
                self.assertEqual(response.status_code, 200)
                ids.update(row["id"] for row in response.json()["items"])
                cursor = response.json()["next_cursor"]
                if cursor is None:
                    break
            self.assertIsNone(cursor)
            self.assertEqual(ids, {row["id"] for row in self.history["orders"]})
            self.assertEqual(executor.get("/api/v1/orders").json()["items"], [])
            historic = next(iter(ids))
            self.assertEqual(executor.get("/api/v1/orders/" + historic).status_code, 403)
            dictionaries = master.get("/api/v1/dicts").json()
            self.assertEqual(len(dictionaries["sections"]), 4)
            self.assertEqual([row["id"] for row in dictionaries["executors"]], [IDENTITY["executor"]])
            live = self.manifest["live_path"]
            def command(action, version, payload=None):
                return {"operation_id": str(uuid4()), "expected_version": version,
                        "action": action, "payload": payload or {}}
            create = command("create", 0, {"type": "planned", "description": "Synthetic live history bridge test",
                "section_id": live["section_id"], "equipment_id": live["equipment_id"],
                "assignment": {"executor_id": IDENTITY["executor"], "brigade_id": None},
                "due_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
                "norm_minutes": 30, "priority": "normal", "comment": "Synthetic live flow", "before_photo_ids": []})
            response = master.post("/api/v1/orders", json=create)
            self.assertEqual(response.status_code, 201)
            order = response.json()["order"]["id"]
            self.assertGreater(int(response.json()["order"]["number"]), 540)
            for action, version in (("accept", 1), ("start", 2)):
                self.assertEqual(executor.post(f"/api/v1/orders/{order}/commands", json=command(action, version)).status_code, 200)
            submit = executor.post(f"/api/v1/orders/{order}/commands", json=command("submit", 3,
                {"work_description": "Synthetic planned inspection completed", "work_code_id": live["work_code_id"],
                 "materials": [{"material_id": live["material_id"], "quantity": 1}], "after_photo_ids": [], "comment": "No photo claimed"}))
            self.assertEqual(submit.status_code, 200)
            review = command("review", 4, {"submission_id": submit.json()["submission_id"],
                "decision": "close", "reason": "Synthetic human review", "final_score": None})
            self.assertEqual(executor.post(f"/api/v1/orders/{order}/commands", json=review).status_code, 403)
            close = master.post(f"/api/v1/orders/{order}/commands", json=review)
            self.assertEqual(close.status_code, 200)
            self.assertEqual(close.json()["order"]["status"], "closed")
            before = {table: self.count(table) for table in ("orders", "order_events", "submissions", "reviews", "auth_sessions", "operation_receipts")}
            self.assertEqual(self.seed()["status"], "ALREADY_PRESENT")
            self.assertEqual(before, {table: self.count(table) for table in before})
            self.assertEqual(before["orders"], 541)


class HistoryDemoReportsPostgresTests(HistoryDemoPostgresTests):
    def test_history_visible_in_accepted_mounted_reports(self):
        self.seed()
        with ExitStack() as stack:
            app = self.app()
            master = self.login(stack, app, "master")
            executor = self.login(stack, app, "executor")
            issued = 0
            # Respect C111's default 31-day bounded capture. Three adjacent
            # UTC monthly windows, never rewrite history to look like today.
            for month in (7, 8, 9):
                params = {"start": f"2026-{month:02d}-01T00:00:00Z",
                          "end": f"2026-{month + 1:02d}-01T00:00:00Z"}
                report = master.get("/api/v1/reports/shift", params=params)
                self.assertEqual(report.status_code, 200, "Accepted C111 reports required for this separate gate")
                metrics = {row["name"]: row for row in report.json()["metrics"]}
                issued += int(metrics["issued_orders"]["value"])
                self.assertTrue(report.json()["provenance"]["synthetic"])
            self.assertEqual(issued, 540)
            self.assertEqual(executor.get("/api/v1/reports/shift", params=params).status_code, 403)
            analytics = master.get("/api/v1/analytics/shift", params=params)
            self.assertEqual(analytics.status_code, 200)
            self.assertTrue(analytics.json()["totals_available"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-reports", action="store_true")
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(HistoryDemoPostgresTests)
    expected = 9
    if args.with_reports:
        suite.addTest(HistoryDemoReportsPostgresTests("test_history_visible_in_accepted_mounted_reports"))
        expected += 1
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() and not result.skipped and result.testsRun == expected else 1)
