#!/usr/bin/env python3
"""C107 real-PostgreSQL acceptance, isolated from the two-login live fixture.

Run from the repository root with the backend's locked dependencies installed:

  DALA_C107_DISPOSABLE=1 DALA_C107_EXPECT_DATABASE=c107_test_ci \
  DALA_C107_DATABASE_URL=<explicit disposable OWNER DSN> \
  python backend/tests/integration/test_c107_history_postgres.py

Only a database explicitly named c107_test_* is accepted. This runner creates
and drops its own random c107_history_* schemas; it never provisions a database,
role, credential, usable account or session. It does not use the ordinary
DALA_TEST_DATABASE_URL, live fixtures, external providers or physical photos.
The operator must provision the disposable database separately. No missing
input, missing dependency, skipped test or connection failure counts as PASS.

Pinned C sources may be present at their repository paths or in the local git
object database. There is no fetch/install/network fallback. --check-inputs is
offline source verification ONLY, explicitly not PostgreSQL evidence.

When the assembly has newer migrations, DALA_C107_MIGRATION_ROOT may point to
a separate fixture root containing only the four pinned backend/db paths below.
The runner must copy those exact files there; hashes and the strict migration
allowlist still apply. Runtime Python code comes from this checkout. This proves
e8a15e53 baseline-schema coverage only, never full newer-worker-schema coverage.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
from queue import Queue
import re
import subprocess
import sys
from threading import Barrier
import time
from types import ModuleType
import unittest
from uuid import UUID, uuid4


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
BASE_COMMIT = "e8a15e5301a460574ec1ddf3424bcd9318270fd4"
LOADER_COMMIT = "2836cec1c5351544c286e72503ad4b5b7590d847"
GENERATOR_COMMIT = "8af3897f03aa2f41f0af07ec74ec2c807a4a535a"
LOADER_SHA256 = "b7d966b471d79f65ec8cb1eb4f086dc57df78ea5e5aea29f2c4a3b9a4fbcfb8c"
GENERATOR_SHA256 = "02825ee7acf5d9ccccb5e3be016266c9a29f35d63d85bde35588acaed5bc5a99"
HISTORY_SHA256 = "7d888cdd5bb6a9c01ca7c543fae9e393335d07210dab811aa754f12331d1d2e1"
LOCKED_PIN = "!DISABLED_SYNTHETIC_HISTORY"
ORIGIN = "https://c107-history.test"
MIGRATIONS = (
    ("backend/db/migrations/001_vertical_slice.sql", "f6d82acc75611ecdb01ac2b2d058e21eab91fa658101c9150013c44d16684fd3"),
    ("backend/db/migrations/002_trusted_evidence.sql", "c1999e097d079dcd3ca89be162b478061ebefde33c6e92f127605392e5441a98"),
    ("backend/db/migrations/004_immutable_reference_keys.sql", "66789e096bdc6bf5c46f93fb49ac3f062d62b27309b26147cc39cf5b74360d64"),
    ("backend/db/proposals/003_auth_rate_limits.sql", "aafe87eead4b7eb2cdf88c74833a0fc8313343e79804b24bfacfc4b9fdd7f5c1"),
)
COUNTS = {"sections": 4, "brigades": 3, "employees": 17,
          "employee_sections": 34, "equipment": 25, "work_codes": 20,
          "materials": 40, "orders": 540, "submissions": 568,
          "material_writeoffs": 568, "reviews": 568, "order_events": 3510}
EMPTY = ("photos", "ai_assessments", "ai_jobs", "delivery_jobs",
         "operation_receipts", "auth_sessions", "auth_login_limits")
EXPECTED_TESTS = 8


def checked_bytes(path, expected, commit=None, *, root=ROOT):
    local = root / path
    if local.is_file():
        raw = local.read_bytes()
    elif commit is not None:
        result = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=ROOT,
                                capture_output=True, timeout=15)
        if result.returncode:
            raise RuntimeError(f"NOT_RUN: pinned input unavailable: {commit}:{path}")
        raw = result.stdout
    else:
        raise RuntimeError(f"NOT_RUN: migration unavailable: {path}")
    if hashlib.sha256(raw).hexdigest() != expected:
        raise RuntimeError(f"BLOCKED: input hash mismatch: {path}")
    return raw


def checked_module(path, expected, commit, name):
    raw = checked_bytes(path, expected, commit)
    module = ModuleType(name)
    module.__file__ = str(ROOT / path)
    exec(compile(raw, module.__file__, "exec"), module.__dict__)
    return module


def inputs():
    loader = checked_module("scripts/synthetic/load_demo.py", LOADER_SHA256,
                            LOADER_COMMIT, "c107_pinned_loader")
    generator = checked_module("scripts/synthetic/generate.py", GENERATOR_SHA256,
                               GENERATOR_COMMIT, "c107_pinned_generator")
    history, _ = generator.build_export()  # Evaluator truth is never imported.
    raw = generator.canonical_bytes(history)
    if hashlib.sha256(raw).hexdigest() != HISTORY_SHA256:
        raise RuntimeError("BLOCKED: generated history is not the reviewed export")
    migration_root = Path(os.environ.get("DALA_C107_MIGRATION_ROOT", str(ROOT))).resolve()
    migrations = [checked_bytes(path, digest, root=migration_root).decode("utf-8")
                  for path, digest in MIGRATIONS]
    actual = {p.name for p in (migration_root / "backend/db/migrations").glob("*.sql")}
    expected = {Path(path).name for path, _ in MIGRATIONS if "/migrations/" in path}
    if actual != expected:
        raise RuntimeError("BLOCKED: migration set changed; re-review this gate")
    return loader, history, raw, migrations


def normalized(value):
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalized(item) for item in value]
    return value


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class C107HistoryPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loader, cls.history, cls.raw, cls.migrations = inputs()
        cls.dsn = os.environ.get("DALA_C107_DATABASE_URL", "")
        cls.database = os.environ.get("DALA_C107_EXPECT_DATABASE", "")
        if (os.environ.get("DALA_C107_DISPOSABLE") != "1" or not cls.dsn
                or re.fullmatch(r"c107_test_[a-z0-9_]{1,40}", cls.database) is None):
            raise RuntimeError("NOT_RUN: explicit C107 disposable OWNER DSN, "
                               "DALA_C107_DISPOSABLE=1 and c107_test_* database required")
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import conninfo_to_dict
        from psycopg.rows import dict_row
        parsed = conninfo_to_dict(cls.dsn)
        if parsed.get("dbname") != cls.database or not parsed.get("host"):
            raise RuntimeError("BLOCKED: DSN must explicitly name the target database and host")
        cls.pg, cls.sql, cls.dict_row = psycopg, sql, staticmethod(dict_row)
        cls.mapping = {actor["employee_code"]: actor["id"] for actor in cls.history["employees"]}
        with cls.control_connection() as db:
            row = db.execute("SELECT current_database() AS name, "
                             "current_user=session_user AS direct_owner").fetchone()
            if row["name"] != cls.database or not row["direct_owner"]:
                raise RuntimeError("BLOCKED: connection does not match explicit direct OWNER target")

    @classmethod
    def control_connection(cls):
        return cls.pg.connect(cls.dsn, autocommit=True, row_factory=cls.dict_row,
                              connect_timeout=5, options="-c search_path=pg_catalog")

    def connect(self):
        return self.pg.connect(self.dsn, autocommit=True, row_factory=self.dict_row,
            connect_timeout=5, options=f"-c search_path={self.schema},pg_catalog")

    def setUp(self):
        self.schema = "c107_history_" + uuid4().hex
        with self.control_connection() as db:
            db.execute(self.sql.SQL("CREATE SCHEMA {}").format(self.sql.Identifier(self.schema)))
        self.addCleanup(self.drop_schema)
        with self.connect() as db:
            for migration in self.migrations:
                db.execute(migration)
        self.assertEqual(self.counts(), {table: 0 for table in (*COUNTS, *EMPTY)})

    def drop_schema(self):
        # Only the exact random namespace created by this test can be removed.
        if re.fullmatch(r"c107_history_[a-f0-9]{32}", self.schema) is None:
            raise RuntimeError("Refusing cleanup of an unexpected schema")
        with self.control_connection() as db:
            db.execute(self.sql.SQL("DROP SCHEMA {} CASCADE").format(self.sql.Identifier(self.schema)))

    def query(self, statement, params=()):
        with self.connect() as db:
            cursor = db.execute(statement, params)
            return normalized(cursor.fetchall()) if cursor.description else []

    def counts(self):
        with self.connect() as db:
            return {table: db.execute(self.sql.SQL("SELECT count(*) AS n FROM {}")
                    .format(self.sql.Identifier(table))).fetchone()["n"]
                    for table in (*COUNTS, *EMPTY)}

    def snapshot(self):
        rows = {}
        for table in (*COUNTS, *EMPTY):
            if table == "employees":
                rows[table] = self.query("SELECT id,employee_code,role,active,on_shift,brigade_id,"
                                         "pin_hash=%s AS locked FROM employees ORDER BY id", (LOCKED_PIN,))
            else:
                # auth_sessions is always empty here; no credentials are created.
                rows[table] = self.query(self.sql.SQL("SELECT * FROM {} ORDER BY to_jsonb({})::text")
                    .format(self.sql.Identifier(table), self.sql.Identifier(table)))
        rows["number_sequence"] = self.query("SELECT last_value,is_called FROM orders_number_seq")
        return rows

    def run_import(self, connection=None, **overrides):
        kwargs = {"demo_only": True, "expected_database": self.database,
                  "expected_schema": self.schema}
        kwargs.update(overrides)
        if connection is not None:
            return self.loader.load_demo(connection, self.raw, self.mapping, **kwargs)
        with self.connect() as db:
            return self.loader.load_demo(db, self.raw, self.mapping, **kwargs)

    def assert_imported(self, result):
        self.assertEqual(result["status"], "IMPORTED")
        self.assertEqual(result["inserted"], COUNTS)
        self.assertEqual(result["history_sha256"], HISTORY_SHA256)
        self.assertIs(result["synthetic"], True)
        self.assertEqual(result["photo_rows_inserted"], 0)
        self.assertEqual(result["evidence_level"],
                         "synthetic_historical_database_snapshot_not_live_workflow")
        self.assertEqual(self.counts(), {**COUNTS, **dict.fromkeys(EMPTY, 0)})

    def test_fresh_import_exact_rows_counts_window_and_provenance(self):
        self.assert_imported(self.run_import())
        source = self.history
        for table in ("sections", "brigades", "equipment", "work_codes", "materials"):
            self.assertEqual(self.query(f"SELECT * FROM {table} ORDER BY id"),
                             sorted(source[table], key=lambda row: row["id"]))
        for table in ("orders", "submissions", "material_writeoffs", "reviews", "order_events"):
            columns = self.loader.COLUMNS[table]
            actual = self.query(f"SELECT {','.join(columns)} FROM {table}")
            key = (lambda row: (row["submission_id"], row["material_id"])) if table == "material_writeoffs" else (lambda row: row["id"])
            actual = {key(row): row for row in actual}
            for original in source[table]:
                expected = {field: original[field] for field in columns if field in original}
                if table == "orders":
                    expected.update(original["assignment"])
                    expected["comment"] = ("Синтетические данные — не история предприятия; "
                        "historical snapshot; photo bytes unavailable. " + original["comment"])
                elif table == "submissions":
                    expected.update({field: original["payload"][field] for field in
                        ("work_description", "work_code_id", "comment", "after_photo_ids")})
                elif table == "material_writeoffs":
                    expected["quantity"] = Decimal(str(expected["quantity"]))
                if table == "order_events":
                    expected["details"] = dict(original["details"])
                    if original["kind"] == "order.created":
                        expected["details"]["synthetic_import"] = actual[key(original)]["details"]["synthetic_import"]
                for field in ("issued_at", "due_at", "updated_at", "submitted_at",
                              "created_at", "occurred_at", "recorded_at"):
                    if field in expected:
                        expected[field] = timestamp(expected[field])
                self.assertEqual(actual[key(original)], expected, f"{table}:{key(original)}")
        orders = {row["id"]: row for row in self.query("SELECT id,number FROM orders")}
        self.assertEqual(sorted(row["number"] for row in orders.values()), list(range(1, 541)))
        mapping_hash = hashlib.sha256(self.loader.canonical_bytes(self.mapping)).hexdigest()
        by_id = {row["id"]: row for row in source["orders"]}
        events = self.query("SELECT order_id,details FROM order_events WHERE kind='order.created'")
        self.assertEqual(len(events), 540)
        for event in events:
            order_id = event["order_id"]
            self.assertEqual(event["details"]["synthetic_import"], {
                "synthetic": True, "loader_version": "1.1.0", "source_commit": GENERATOR_COMMIT,
                "history_sha256": HISTORY_SHA256, "identity_mapping_sha256": mapping_hash,
                "source_order_number": by_id[order_id]["number"],
                "runtime_order_number": orders[order_id]["number"],
                "watermark": "Синтетические данные — не история предприятия",
                "photo_policy": "metadata_only_no_image_bytes_no_file_valid_claim",
                "source_photo_placeholders": [p for p in source["photos"] if p["order_id"] == order_id],
                "historical_completeness_not_verified_evidence": True,
                "historical_actor_state": "disabled_no_login"})
        window = source["metadata"]["window"]
        self.assertEqual((timestamp(window["end_exclusive"]) - timestamp(window["start_inclusive"])).days, 92)
        self.assertEqual(self.query("SELECT DISTINCT to_char(issued_at AT TIME ZONE 'Asia/Almaty', 'YYYY-MM') AS m FROM orders ORDER BY m"),
                         [{"m": "2026-07"}, {"m": "2026-08"}, {"m": "2026-09"}])
        self.assertEqual(self.query("SELECT count(*) AS n FROM reviews WHERE final_score IS NULL"), [{"n": 82}])

    def test_identical_repeat_is_noop_with_identical_rows_and_sequence(self):
        self.assert_imported(self.run_import())
        before = self.snapshot()
        result = self.run_import()
        self.assertEqual(result["status"], "NOOP")
        self.assertEqual(result["inserted"], dict.fromkeys(COUNTS, 0))
        self.assertEqual(self.snapshot(), before)

    def test_conflicting_catalogue_and_target_rejected_without_writes(self):
        section = self.history["sections"][0]
        self.query("INSERT INTO sections(id,code,label) VALUES (%s,%s,%s)",
                   (section["id"], section["code"], "synthetic conflict"))
        before = self.snapshot()
        with self.assertRaisesRegex(self.loader.ImportBlocked, "Conflicting.*sections"):
            self.run_import()
        self.assertEqual(self.snapshot(), before)
        with self.assertRaisesRegex(self.loader.ImportBlocked, "database does not match"):
            self.run_import(expected_database="c107_test_wrong_target")
        self.assertEqual(self.snapshot(), before)

    def test_real_mid_insert_constraint_failure_rolls_back_and_retry_works(self):
        # A real PostgreSQL constraint fails after parent rows, actors, orders,
        # submissions, reviews and two events have already been inserted.
        self.query("ALTER TABLE order_events ADD CONSTRAINT c107_injected_failure CHECK (sequence <> 3)")
        with self.connect() as db:
            with self.assertRaises(self.pg.errors.CheckViolation) as error:
                self.run_import(connection=db)
            self.assertEqual(error.exception.diag.constraint_name, "c107_injected_failure")
            self.assertEqual(db.info.transaction_status, self.pg.pq.TransactionStatus.IDLE)
        self.assertEqual(self.counts(), dict.fromkeys((*COUNTS, *EMPTY), 0))
        # PostgreSQL sequences are intentionally not transactional. Consumed
        # numbers are not mistaken for committed rows or silently reset.
        sequence = self.query("SELECT last_value,is_called FROM orders_number_seq")[0]
        self.assertEqual(sequence, {"last_value": 540, "is_called": True})
        self.query("ALTER TABLE order_events DROP CONSTRAINT c107_injected_failure")
        self.assert_imported(self.run_import())
        self.assertEqual(self.query("SELECT min(number) AS lo,max(number) AS hi FROM orders"),
                         [{"lo": 541, "hi": 1080}])
        before = self.snapshot()
        self.assertEqual(self.run_import()["status"], "NOOP")
        self.assertEqual(self.snapshot(), before)

    def test_concurrent_import_waits_then_one_import_one_noop(self):
        started = Barrier(3)
        pids = Queue()

        def worker():
            with self.connect() as db:
                pids.put(db.info.backend_pid)
                started.wait(timeout=5)
                return self.run_import(connection=db)

        with self.control_connection() as blocker, ThreadPoolExecutor(max_workers=2) as pool:
            blocker.execute("SELECT pg_advisory_lock(%s)", (self.loader.LOCK_KEY,))
            futures = [pool.submit(worker) for _ in range(2)]
            try:
                started.wait(timeout=5)
                worker_ids = [pids.get(timeout=1), pids.get(timeout=1)]
                deadline = time.monotonic() + 2
                waiting = 0
                while time.monotonic() < deadline:
                    waiting = blocker.execute("SELECT count(DISTINCT pid) AS n FROM pg_locks "
                        "WHERE pid=ANY(%s) AND locktype='advisory' AND NOT granted", (worker_ids,)).fetchone()["n"]
                    if waiting == 2:
                        break
                    time.sleep(0.02)
                self.assertEqual(waiting, 2, "Both importers must demonstrably wait on the real lock")
            finally:
                blocker.execute("SELECT pg_advisory_unlock(%s)", (self.loader.LOCK_KEY,))
            results = [future.result(timeout=70) for future in futures]
        self.assertEqual(sorted(result["status"] for result in results), ["IMPORTED", "NOOP"])
        self.assert_imported(next(result for result in results if result["status"] == "IMPORTED"))
        self.assertEqual(next(result for result in results if result["status"] == "NOOP")["inserted"], dict.fromkeys(COUNTS, 0))
        self.assertEqual(self.query("SELECT last_value,is_called FROM orders_number_seq"),
                         [{"last_value": 540, "is_called": True}])

    def test_all_seventeen_actors_locked_inactive_and_cannot_log_in(self):
        from app.core.auth_boundary import AuthenticationRequired
        from app.persistence.postgres import PostgresPrincipals, PostgresReferences, PostgresRepository
        from app.sessions.crypto import Argon2idVerifier
        from app.sessions.service import SessionService
        self.assert_imported(self.run_import())
        actors = self.query("SELECT id,employee_code,role,active,on_shift,brigade_id,"
                            "pin_hash=%s AS locked FROM employees ORDER BY id", (LOCKED_PIN,))
        expected = [{"id": a["id"], "employee_code": a["employee_code"], "role": a["role"],
                     "active": False, "on_shift": False, "brigade_id": a["brigade_id"], "locked": True}
                    for a in self.history["employees"]]
        self.assertEqual(actors, sorted(expected, key=lambda row: row["id"]))
        memberships = [{"employee_id": a["id"], "section_id": section}
                       for a in self.history["employees"] for section in a["section_ids"]]
        self.assertEqual(self.query("SELECT * FROM employee_sections ORDER BY employee_id,section_id"),
                         sorted(memberships, key=lambda row: (row["employee_id"], row["section_id"])))
        self.assertFalse(set(self.mapping.values()) & self.loader.LIVE_DEMO_ACCOUNT_IDS)
        verifier = Argon2idVerifier()
        for pin in ("0000", "1234", LOCKED_PIN):
            self.assertIs(verifier.verify(pin, LOCKED_PIN), False)
        service = SessionService(self.connect, allowed_origin=ORIGIN, demo_enabled=True, verifier=verifier)
        for actor in actors:
            with self.subTest(code=actor["employee_code"]), self.assertRaises(AuthenticationRequired):
                service.login(json.dumps({"employee_code": actor["employee_code"], "pin": "0000"}),
                              origin=ORIGIN, source_key="127.0.0.1")
        self.assertEqual(self.query("SELECT count(*) AS n FROM auth_sessions"), [{"n": 0}])
        self.assertEqual(self.query("SELECT sum(attempts) AS n FROM auth_login_limits WHERE kind='source'"), [{"n": 17}])
        self.assertEqual(self.query("SELECT id,employee_code,role,active,on_shift,brigade_id,"
                                   "pin_hash=%s AS locked FROM employees ORDER BY id", (LOCKED_PIN,)), actors)
        with self.connect() as db, db.transaction():
            repo = PostgresRepository(db)
            for source in self.history["orders"]:
                order = repo.load_order(source["id"])
                principal = PostgresPrincipals(db).lookup(order.assignment.executor_id)
                self.assertIs(principal.active, False)
                refs = PostgresReferences(repo, principal, datetime.now(timezone.utc), order)
                self.assertIs(refs.assignment_in_section(order.assignment, order.section_id), False)

    def test_existing_actor_mismatch_or_scope_is_not_repaired(self):
        self.assert_imported(self.run_import())
        actor = self.history["employees"][0]
        # All changes are synthetic negative fixtures inside this owned schema.
        for field, value in (("active", True), ("on_shift", True), ("pin_hash", "invalid-test-only")):
            with self.subTest(field=field):
                self.query(self.sql.SQL("UPDATE employees SET {}=%s WHERE id=%s")
                           .format(self.sql.Identifier(field)), (value, actor["id"]))
                before = self.snapshot()
                with self.assertRaisesRegex(self.loader.ImportBlocked, "Synthetic account does not match"):
                    self.run_import()
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(self.query(self.sql.SQL("SELECT {}=%s AS unchanged FROM employees WHERE id=%s")
                    .format(self.sql.Identifier(field)), (value, actor["id"])), [{"unchanged": True}])
                original = LOCKED_PIN if field == "pin_hash" else False
                self.query(self.sql.SQL("UPDATE employees SET {}=%s WHERE id=%s")
                           .format(self.sql.Identifier(field)), (original, actor["id"]))
        self.query("DELETE FROM employee_sections WHERE employee_id=%s AND section_id=%s",
                   (actor["id"], actor["section_ids"][0]))
        before = self.snapshot()
        with self.assertRaisesRegex(self.loader.ImportBlocked, "Existing scope mismatch"):
            self.run_import()
        self.assertEqual(self.snapshot(), before)

    def test_missing_physical_photos_remain_unavailable_to_real_evidence_gate(self):
        from app.ai.order_adapter import from_order_snapshot
        from app.ai.rules import evaluate_gates
        from app.integration.photo_evidence import VerifiedPhotoReferences
        from app.persistence.postgres import PostgresPrincipals, PostgresRepository
        self.assert_imported(self.run_import())
        self.assertEqual(len(self.history["photos"]), 444)
        referenced = self.query("SELECT unnest(after_photo_ids) AS id FROM submissions")
        self.assertEqual({row["id"] for row in referenced}, {row["id"] for row in self.history["photos"]})
        self.assertEqual(len(referenced), 444)

        def unexpected_blob_read(_row):
            raise AssertionError("A metadata placeholder must never become a physical blob read")

        checked = 0
        with self.connect() as db, db.transaction():
            repo = PostgresRepository(db)
            for source in self.history["submissions"]:
                if not source["payload"]["after_photo_ids"]:
                    continue
                submission = repo.load_submission(source["id"])
                order = repo.load_order(submission.order_id)
                principal = PostgresPrincipals(db).lookup(order.created_by)
                refs = VerifiedPhotoReferences(repo, principal, datetime.now(timezone.utc), order,
                                               verifier=unexpected_blob_read)
                codes, materials, photos = refs.closure_evidence(submission)
                self.assertEqual(photos, ())
                data, context = from_order_snapshot(order, submission, work_code_ids=codes,
                                                    material_ids=materials, photos=photos)
                gate = evaluate_gates(data, context)
                file_gates = [item for item in gate.gates if item.code == "AFTER_PHOTO_FILE"]
                self.assertEqual(len(file_gates), len(submission.payload.after_photo_ids))
                self.assertTrue(all(item.status == "unknown" for item in file_gates))
                self.assertFalse(gate.closure_permitted)
                checked += len(file_gates)
        self.assertEqual(checked, 444)
        self.assertEqual(self.counts(), {**COUNTS, **dict.fromkeys(EMPTY, 0)})


def main():
    if sys.argv[1:] == ["--check-inputs"]:
        _, history, _, _ = inputs()
        print(json.dumps({"status": "INPUTS_VERIFIED", "postgresql": "NOT_RUN",
            "schema_base": BASE_COMMIT, "schema_scope": "e8a15e53_baseline_only",
            "loader_commit": LOADER_COMMIT,
            "loader_sha256": LOADER_SHA256, "generator_commit": GENERATOR_COMMIT,
            "generator_sha256": GENERATOR_SHA256, "history_sha256": HISTORY_SHA256,
            "counts": {key: len(value) for key, value in history.items() if isinstance(value, list)}}))
        return 0
    if sys.argv[1:]:
        raise SystemExit("Only --check-inputs or no arguments are supported")
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(C107HistoryPostgresTests)
    if suite.countTestCases() != EXPECTED_TESTS:
        raise SystemExit("FAIL: unexpected C107 test count")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    passed = result.wasSuccessful() and not result.skipped and result.testsRun == EXPECTED_TESTS
    print(json.dumps({"status": "PASS" if passed else "FAIL", "postgresql": "EXECUTED" if result.testsRun else "NOT_RUN",
        "tests_run": result.testsRun, "expected_tests": EXPECTED_TESTS, "skips": len(result.skipped),
        "schema_base": BASE_COMMIT, "schema_scope": "e8a15e53_baseline_only",
        "loader_commit": LOADER_COMMIT, "history_sha256": HISTORY_SHA256,
        "scope": "disposable_synthetic_history_only_not_live_workflow_or_deployment"}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
