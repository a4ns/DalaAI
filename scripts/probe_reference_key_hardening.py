"""Controlled before/after reproduction in disposable schemas; never a live reset."""

import os
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch
from uuid import uuid4

if not os.environ.get("DALA_TEST_DATABASE_URL"):
    raise SystemExit("NOT_RUN: an explicit disposable PostgreSQL DSN is required")
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "backend/tests")]
from app.persistence.postgres import PostgresPrincipals
from test_persistence_role import ApplicationRoleTests
import test_persistence_postgres as candidate

ApplicationRoleTests.setUpClass()
try:
    with tempfile.TemporaryDirectory(prefix="a5-pre-fix-migrations-") as directory:
        old_migrations = Path(directory)
        for name in ("001_vertical_slice.sql", "002_trusted_evidence.sql"):
            shutil.copyfile(ROOT / "backend/db/migrations" / name, old_migrations / name)
        case = ApplicationRoleTests("test_runtime_login_is_nonowner_and_nonprivileged")
        try:
            with patch.object(candidate, "MIGRATIONS", old_migrations):
                case.setUp()
            case.test_runtime_login_is_nonowner_and_nonprivileged()
            case.runtime_query(
                "UPDATE employee_sections SET employee_id=%s WHERE employee_id=%s AND section_id=%s RETURNING employee_id",
                (candidate.EXECUTOR, candidate.MASTER, candidate.SECOND_SECTION),
            )
            with case.runtime_connect() as db:
                principal = PostgresPrincipals(db).lookup(candidate.EXECUTOR)
                assert candidate.SECOND_SECTION in principal.section_ids
            session_id = case.query("SELECT id FROM auth_sessions WHERE employee_id=%s", (candidate.MASTER,))[0]["id"]
            changed_id = str(uuid4())
            assert case.runtime_query("UPDATE auth_sessions SET id=%s WHERE id=%s RETURNING id", (changed_id, session_id))
            print("BASELINE ABUSE REPRODUCED: runtime login transferred section membership and rewrote a session ID")
            # Restore only this test's synthetic rows before the additive migration.
            case.query("UPDATE employee_sections SET employee_id=%s WHERE employee_id=%s AND section_id=%s RETURNING employee_id",
                       (candidate.MASTER, candidate.EXECUTOR, candidate.SECOND_SECTION))
            case.query("UPDATE auth_sessions SET id=%s WHERE id=%s RETURNING id", (session_id, changed_id))
            with case.connect() as db:
                db.execute((ROOT / "backend/db/migrations/004_immutable_reference_keys.sql").read_text())
            with case.assertRaises(case.pg.errors.CheckViolation):
                case.runtime_query("UPDATE employee_sections SET employee_id=%s WHERE employee_id=%s AND section_id=%s RETURNING employee_id",
                                   (candidate.EXECUTOR, candidate.MASTER, candidate.SECOND_SECTION))
            with case.assertRaises(case.pg.errors.CheckViolation):
                case.runtime_query("UPDATE auth_sessions SET id=%s WHERE id=%s RETURNING id", (str(uuid4()), session_id))
            with case.runtime_connect() as db:
                principal = PostgresPrincipals(db).lookup(candidate.EXECUTOR)
                assert candidate.SECOND_SECTION not in principal.section_ids
            created, _ = case.create()
            assert created.status == 201
            print("FORWARD FIX PASS: existing synthetic rows preserved, membership/session rewrite denied, command still works")
        finally:
            case.doCleanups()
finally:
    ApplicationRoleTests.doClassCleanups()
