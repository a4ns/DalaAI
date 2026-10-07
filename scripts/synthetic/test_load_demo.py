"""Synthetic unit/fake-SQL checks ONLY. No PostgreSQL connection or provisioning.

The exact already-available public C1 git object supplies test data in memory.
Missing source objects fail the test setup rather than silently skipping a gate.
"""
from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import mock_open, patch
from uuid import UUID, uuid5

import load_demo as loader


ROOT = Path(__file__).resolve().parents[2]
GENERATOR_SHA256 = "02825ee7acf5d9ccccb5e3be016266c9a29f35d63d85bde35588acaed5bc5a99"


def canonical_fixture():
    command = ["git", "show", f"{loader.SOURCE_COMMIT}:scripts/synthetic/generate.py"]
    source = subprocess.run(command, cwd=ROOT, check=True, capture_output=True).stdout
    if hashlib.sha256(source).hexdigest() != GENERATOR_SHA256:
        raise RuntimeError("BLOCKED: exact reviewed C1 generator source unavailable")
    namespace = {"__name__": "reviewed_c1_fixture", "__file__": str(ROOT / "scripts/synthetic/generate.py")}
    exec(compile(source, "reviewed_c1_generator", "exec"), namespace)
    history, _ = namespace["build_export"]()
    return history, namespace["canonical_bytes"](history)


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchall(self):
        return deepcopy(self.rows)

    def fetchone(self):
        return deepcopy(self.rows[0]) if self.rows else None


class FakeOwner:
    """Minimal SQL recording fake, deliberately NOT a database/constraint proof."""
    def __init__(self, history, mapping):
        self.autocommit = True
        self.info = SimpleNamespace(transaction_status=0)
        self.calls = []
        self.database = "isolated_synthetic_demo"
        self.current_role = self.session_role = "existing_demo_owner"
        self.owned = {table: True for table in loader.ALL_TABLES}
        self.tables = {table: [] for table in loader.ALL_TABLES}
        self.fail_after = None
        self.insert_count = 0
        self.next_number = 1000
        self.commits = self.rollbacks = 0
        # These references/accounts/scopes are preprovisioned by an external
        # operator; no CREATE/INSERT-auth SQL is used by the loader under test.
        for table in ("sections", "brigades"):
            self.tables[table] = deepcopy(history[table])
        for source in history["employees"]:
            target = mapping[source["employee_code"]]
            self.tables["employees"].append({"id": target, "employee_code": source["employee_code"],
                "role": source["role"], "active": True, "brigade_id": source["brigade_id"]})
            self.tables["employee_sections"].extend({"employee_id": target, "section_id": section}
                                                   for section in source["section_ids"])

    @contextmanager
    def transaction(self):
        if self.info.transaction_status:
            raise AssertionError("Loader tried to nest a transaction")
        snapshot = deepcopy(self.tables)
        self.info.transaction_status = 2
        try:
            yield
        except Exception:
            self.tables = snapshot
            self.rollbacks += 1
            raise
        else:
            self.commits += 1
        finally:
            self.info.transaction_status = 0

    def execute(self, statement, params=()):
        self.calls.append((statement, deepcopy(params)))
        if self.info.transaction_status != 2:
            raise AssertionError("SQL executed outside transaction")
        if statement.startswith(("SET ", "LOCK TABLE ", "SELECT pg_catalog.pg_advisory")):
            return Result()
        if "current_database()" in statement:
            return Result([{"database": self.database, "current_role": self.current_role,
                            "session_role": self.session_role}])
        if "pg_catalog.pg_class" in statement:
            return Result([{"name": name, "owned": owned} for name, owned in self.owned.items()])
        table_match = re.search(r'"[a-z][a-z0-9_]*"\."([a-z_]+)"', statement)
        if not table_match:
            raise AssertionError(f"Unmodelled SQL: {statement}")
        table = table_match[1]
        if statement.startswith("SELECT EXISTS"):
            return Result([{"present": bool(self.tables[table])}])
        if statement.startswith("SELECT "):
            columns = statement.split(" FROM ", 1)[0][len("SELECT "):].split(",")
            return Result([{column: row[column] for column in columns} for row in self.tables[table]])
        if statement.startswith("INSERT INTO "):
            self.insert_count += 1
            if self.fail_after == self.insert_count:
                raise RuntimeError("Simulated insert failure; not a PostgreSQL error")
            columns = re.search(r"\(([^)]+)\) VALUES", statement)[1].split(",")
            row = dict(zip(columns, deepcopy(params)))
            for column in loader.JSON_COLUMNS & row.keys():
                row[column] = json.loads(row[column])
            if table == "orders":
                self.next_number += 1
                row["number"] = self.next_number
            if any(loader.key_for(table, old) == loader.key_for(table, row) for old in self.tables[table]):
                raise AssertionError("Duplicate fake primary key")
            self.tables[table].append(row)
            return Result([{"id": row["id"], "number": row["number"]}]) if table == "orders" else Result()
        raise AssertionError(f"Unmodelled SQL: {statement}")


class LoadDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.history, cls.raw = canonical_fixture()
        namespace = UUID("1d019882-7082-4af9-a988-f5e14089a3c0")
        cls.mapping = {employee["employee_code"]: str(uuid5(namespace, employee["employee_code"]))
                       for employee in cls.history["employees"]}

    def setUp(self):
        self.db = FakeOwner(self.history, self.mapping)

    def run_import(self, **overrides):
        kwargs = {"demo_only": True, "expected_database": self.db.database, "expected_schema": "synthetic_demo"}
        kwargs.update(overrides)
        return loader.load_demo(self.db, self.raw, self.mapping, **kwargs)

    def assert_no_writes(self):
        self.assertFalse(any(sql.startswith("INSERT ") for sql, _ in self.db.calls))

    def test_exact_canonical_source_and_scope(self):
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), loader.HISTORY_SHA256)
        self.assertEqual(loader.read_history(self.raw), self.history)
        self.assertEqual(len(self.history["orders"]), 540)
        self.assertEqual(len(self.history["employees"]), 17)

    def test_changed_bytes_and_relabelled_data_fail_before_sql(self):
        changed = deepcopy(self.history)
        changed["orders"][0]["description"] = "unreviewed data"
        for raw in (self.raw + b"\n", b'{"synthetic":true,"synthetic":false}',
                    loader.canonical_bytes(changed), b"", b"x" * (loader.MAX_HISTORY_BYTES + 1)):
            with self.subTest(bytes=len(raw)), self.assertRaises(loader.ImportBlocked):
                loader.load_demo(self.db, raw, self.mapping, demo_only=True,
                                 expected_database=self.db.database, expected_schema="synthetic_demo")
        self.assertEqual(self.db.calls, [])

    def test_explicit_demo_target_and_idle_connection_guards(self):
        for guard in ({"demo_only": False}, {"demo_only": 1}, {"expected_database": ""},
                      {"expected_schema": None}, {"expected_schema": 'a";DROP TABLE orders;--'},
                      {"expected_schema": "pg_catalog"}, {"expected_schema": "information_schema"}):
            with self.subTest(guard=guard), self.assertRaises(loader.ImportBlocked):
                self.run_import(**guard)
        for autocommit, status in ((False, 0), (True, 2)):
            self.db.autocommit, self.db.info.transaction_status = autocommit, status
            with self.assertRaises(loader.ImportBlocked):
                self.run_import()
        self.assertEqual(self.db.calls, [])

    def test_missing_duplicate_or_malformed_mapping_fails_before_sql(self):
        cases = [{}, dict(self.mapping, extra=str(UUID(int=1))),
                 dict(self.mapping, **{"SYN-M-01": "not-a-uuid"}),
                 dict(self.mapping, **{"SYN-M-01": self.mapping["SYN-M-02"]}),
                 dict(self.mapping, **{"SYN-M-01": sorted(loader.LIVE_DEMO_ACCOUNT_IDS)[0]}),
                 dict(self.mapping, **{"SYN-M-01": self.history["orders"][0]["id"]})]
        for mapping in cases:
            with self.subTest(mapping=len(mapping)), self.assertRaises(loader.ImportBlocked):
                loader.load_demo(self.db, self.raw, mapping, demo_only=True,
                                 expected_database=self.db.database, expected_schema="synthetic_demo")
        self.assertEqual(self.db.calls, [])

    def test_complete_import_and_identical_noop(self):
        accounts = deepcopy({table: self.db.tables[table] for table in loader.ACCOUNT_TABLES})
        first = self.run_import()
        self.assertEqual(first["status"], "IMPORTED")
        self.assertEqual(first["inserted"]["orders"], 540)
        self.assertEqual(first["inserted"]["sections"], 0)
        for table in loader.COLUMNS:
            self.assertEqual(len(self.db.tables[table]), len(self.history[table]))
        snapshot = deepcopy(self.db.tables)
        next_number = self.db.next_number
        self.db.calls.clear()
        second = self.run_import()
        self.assertEqual(second["status"], "NOOP")
        self.assert_no_writes()
        self.assertEqual(self.db.tables, snapshot)
        self.assertEqual(self.db.next_number, next_number)
        self.assertEqual(accounts, {table: self.db.tables[table] for table in loader.ACCOUNT_TABLES})
        self.assertEqual(self.db.commits, 2)

    def test_provenance_mapping_and_unavailable_photo_evidence(self):
        self.run_import()
        self.assertTrue(all(not self.db.tables[table] for table in loader.EMPTY_TABLES))
        events = [row for row in self.db.tables["order_events"] if row["kind"] == "order.created"]
        self.assertEqual(len(events), 540)
        source_photos = []
        for event in events:
            provenance = event["details"]["synthetic_import"]
            self.assertEqual(provenance["history_sha256"], loader.HISTORY_SHA256)
            self.assertEqual(provenance["identity_mapping_sha256"], hashlib.sha256(loader.canonical_bytes(self.mapping)).hexdigest())
            self.assertEqual(provenance["photo_policy"], loader.PHOTO_POLICY)
            source_photos.extend(provenance["source_photo_placeholders"])
        self.assertEqual(sorted(source_photos, key=lambda p: p["id"]), sorted(self.history["photos"], key=lambda p: p["id"]))
        source_subs = {row["id"]: row for row in self.history["submissions"]}
        for sub in self.db.tables["submissions"]:
            self.assertEqual(sub["after_photo_ids"], source_subs[sub["id"]]["payload"]["after_photo_ids"])
            self.assertEqual(sub["completeness"], source_subs[sub["id"]]["completeness"])
        self.assertTrue(any(review["final_score"] is None for review in self.db.tables["reviews"]))
        self.assertEqual([r["final_score"] for r in self.db.tables["reviews"]],
                         [r["final_score"] for r in self.history["reviews"]])
        mapped = set(self.mapping.values())
        self.assertTrue(all(row["executor_id"] in mapped and row["created_by"] in mapped for row in self.db.tables["orders"]))
        self.assertTrue(all(row["number"] >= 1001 for row in self.db.tables["orders"]))
        self.assertTrue(all(loader.WATERMARK in row["comment"] for row in self.db.tables["orders"]))

    def test_conflicts_in_every_written_table_fail_without_repair(self):
        self.run_import()
        good = deepcopy(self.db.tables)
        for table in loader.COLUMNS:
            with self.subTest(table=table):
                self.db.tables = deepcopy(good)
                column = "quantity" if table == "material_writeoffs" else "id"
                self.db.tables[table][0][column] = "conflict"
                self.db.calls.clear()
                with self.assertRaises(loader.ImportBlocked):
                    self.run_import()
                self.assert_no_writes()

    def test_extra_non_synthetic_catalogue_fails(self):
        self.db.tables["sections"].append({"id": str(UUID(int=2)), "code": "REAL", "label": "unapproved"})
        with self.assertRaises(loader.ImportBlocked):
            self.run_import()
        self.assert_no_writes()

    def test_runtime_number_tampering_is_detected_by_provenance(self):
        self.run_import()
        self.db.tables["orders"][0]["number"] += 9000
        self.db.calls.clear()
        with self.assertRaisesRegex(loader.ImportBlocked, "order_events"):
            self.run_import()
        self.assert_no_writes()

    def test_partial_existing_history_fails(self):
        rows, _ = loader.prepare_rows(self.history, self.mapping)
        self.db.tables["orders"] = [dict(rows["orders"][0], number=1)]
        with self.assertRaisesRegex(loader.ImportBlocked, "Partial historical"):
            self.run_import()
        self.assert_no_writes()

    def test_operational_rows_block_before_writes(self):
        for table in loader.EMPTY_TABLES:
            with self.subTest(table=table):
                self.db = FakeOwner(self.history, self.mapping)
                self.db.tables[table] = [{"not_read": "only existence is checked"}]
                with self.assertRaises(loader.ImportBlocked):
                    self.run_import()
                self.assert_no_writes()

    def test_unprovisioned_identity_and_scope_mismatch_block(self):
        for field, value in (("role", "admin"), ("active", False), ("employee_code", "REAL-M-01"),
                             ("brigade_id", str(UUID(int=123)))):
            with self.subTest(field=field):
                self.db = FakeOwner(self.history, self.mapping)
                self.db.tables["employees"][0][field] = value
                with self.assertRaises(loader.ImportBlocked):
                    self.run_import()
                self.assert_no_writes()
        self.db = FakeOwner(self.history, self.mapping)
        self.db.tables["employee_sections"].pop(0)
        with self.assertRaisesRegex(loader.ImportBlocked, "scope mismatch"):
            self.run_import()
        self.assert_no_writes()
        self.db = FakeOwner(self.history, self.mapping)
        self.db.tables["employees"].pop(0)
        with self.assertRaisesRegex(loader.ImportBlocked, "Provisioning required"):
            self.run_import()
        self.assert_no_writes()

    def test_database_owner_and_role_guards(self):
        with self.assertRaisesRegex(loader.ImportBlocked, "database"):
            self.run_import(expected_database="some_other_database")
        self.db.current_role = "role_switched_owner"
        with self.assertRaisesRegex(loader.ImportBlocked, "SET ROLE"):
            self.run_import()
        self.db.current_role = self.db.session_role
        self.db.owned["orders"] = False
        with self.assertRaisesRegex(loader.ImportBlocked, "OWNER"):
            self.run_import()
        del self.db.owned["orders"]
        with self.assertRaisesRegex(loader.ImportBlocked, "OWNER"):
            self.run_import()
        self.assert_no_writes()

    def test_transaction_rolls_back_injected_mid_import_error(self):
        before = deepcopy(self.db.tables)
        self.db.fail_after = 150
        with self.assertRaisesRegex(RuntimeError, "Simulated"):
            self.run_import()
        self.assertEqual(self.db.tables, before)
        self.assertEqual(self.db.rollbacks, 1)
        self.assertEqual(self.db.commits, 0)
        self.assertEqual(self.db.info.transaction_status, 0)

    def test_sql_has_no_privilege_auth_or_evidence_writes(self):
        self.run_import()
        statements = [sql for sql, _ in self.db.calls]
        self.assertEqual(statements[0], "SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        advisory = next(i for i, sql in enumerate(statements) if "pg_advisory_xact_lock" in sql)
        lock = next(i for i, sql in enumerate(statements) if sql.startswith("LOCK TABLE "))
        read = next(i for i, sql in enumerate(statements) if sql.startswith("SELECT id,employee_code"))
        write = next(i for i, sql in enumerate(statements) if sql.startswith("INSERT "))
        self.assertLess(advisory, lock)
        self.assertLess(lock, read)
        self.assertLess(read, write)
        self.assertEqual(statements[-1], "SET CONSTRAINTS ALL IMMEDIATE")
        for statement in statements:
            self.assertNotRegex(statement.upper(), r"\b(CREATE|ALTER|UPDATE|DELETE|TRUNCATE|GRANT|REVOKE|SETVAL|NEXTVAL)\b")
            self.assertNotIn("SELECT *", statement)
            self.assertNotIn("pin_hash", statement)
            self.assertNotIn("auth_sessions", statement)
            if statement.startswith("INSERT "):
                self.assertFalse(any(f'"{table}"' in statement for table in (*loader.EMPTY_TABLES, *loader.ACCOUNT_TABLES)))
                self.assertNotIn("file_valid", statement)
                self.assertNotIn("number", statement.split("VALUES", 1)[0] if '"orders"' in statement else "")

    def test_current_accepted_schema_column_compatibility_static_only(self):
        migrations = ROOT / "backend/db/migrations"
        ddl = (migrations / "001_vertical_slice.sql").read_text()
        evidence = (migrations / "002_trusted_evidence.sql").read_text()
        for table, columns in loader.COLUMNS.items():
            body = re.search(rf"CREATE TABLE {table} \((.*?)\n\);", ddl, re.S)[1]
            if table == "submissions":
                body += evidence
            for column in columns:
                with self.subTest(table=table, column=column):
                    self.assertRegex(body, rf"\b{column}\s+(?:uuid|text|bigint|integer|boolean|timestamptz|numeric|jsonb)\b")

    def test_offline_cli_reports_not_run_and_never_connects(self):
        output = io.StringIO()
        with patch("pathlib.Path.open", mock_open(read_data=self.raw)), redirect_stdout(output):
            self.assertEqual(loader.main(["public-history.json"]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "VALIDATED_OFFLINE")
        self.assertEqual(result["postgresql"], "NOT_RUN")
        self.assertEqual(len(result["required_existing_accounts"]), 17)
        self.assertEqual(self.db.calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
