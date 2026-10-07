#!/usr/bin/env python3
"""Explicit fresh history fixture; existing identities/scopes are never repaired.

Called by the authorized bootstrap only after migrations and grants. This module
does not create DB roles, discover secrets, start services, or make HTTP calls.
The CLI only prints a public offline plan. Minimal provisioning remains separate.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from types import ModuleType

from prepare_demo_database import bootstrap_marker
from provision_synthetic_demo import EMPLOYEES, IDENTITY, FixtureConflict, read_pins, schema_name

ROOT = Path(__file__).resolve().parents[2]
VERSION = "dalaai-canonical-history-live-demo-v1"
LOADER_SHA256 = "b7d966b471d79f65ec8cb1eb4f086dc57df78ea5e5aea29f2c4a3b9a4fbcfb8c"
GENERATOR_SHA256 = "02825ee7acf5d9ccccb5e3be016266c9a29f35d63d85bde35588acaed5bc5a99"
HISTORY_SHA256 = "7d888cdd5bb6a9c01ca7c543fae9e393335d07210dab811aa754f12331d1d2e1"
# Same key as the minimal fixture: incompatible profile attempts serialize too.
FIXTURE_LOCK = 74740825410424401


def require(condition, code):
    if not condition:
        raise FixtureConflict(code)


def checked_module(root, relative, digest, name):
    path = Path(root) / relative
    raw = path.read_bytes()
    require(sha256(raw).hexdigest() == digest, "HISTORY_PINNED_SOURCE_MISMATCH")
    module = ModuleType(name)
    module.__file__ = str(path)
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def canonical_inputs(source_root=ROOT):
    """No alternate mapping, changed dates, external inputs or truth persisted."""
    loader = checked_module(source_root, "scripts/synthetic/load_demo.py", LOADER_SHA256,
                            "history_demo_pinned_loader")
    generator = checked_module(source_root, "scripts/synthetic/generate.py", GENERATOR_SHA256,
                               "history_demo_pinned_generator")
    history, _ = generator.build_export()
    raw = generator.canonical_bytes(history)
    require(sha256(raw).hexdigest() == HISTORY_SHA256, "HISTORY_CANONICAL_EXPORT_MISMATCH")
    history = loader.read_history(raw)
    mapping = {row["employee_code"]: row["id"] for row in history["employees"]}
    require(len(mapping) == 17 and len(history["orders"]) == 540, "HISTORY_CANONICAL_COUNTS_MISMATCH")
    return loader, history, raw, mapping


def public_manifest(history=None):
    if history is None:
        _, history, _, _ = canonical_inputs()
    sections = sorted(history["sections"], key=lambda row: row["code"])
    scopes = {"master": [row["id"] for row in sections], "executor": [sections[0]["id"]]}
    equipment = next(row for row in history["equipment"] if row["section_id"] == sections[0]["id"])
    return {
        "fixture_version": VERSION, "fixture_mode": "history", "synthetic": True,
        "history_sha256": HISTORY_SHA256, "history_orders": 540,
        "history_period_utc": ["2026-07-01T00:00:00Z", "2026-10-01T00:00:00Z"],
        "historical_actor_count": 17, "historical_actor_state": "disabled_no_login",
        "historical_photos": "metadata_only_no_image_bytes_no_file_valid_claim",
        "watermark": "Синтетические данные — не история предприятия",
        "users": [{"id": IDENTITY[role], "employee_code": code, "role": role,
                   "section_ids": scopes[role], "on_shift": True}
                  for role, code, _ in EMPLOYEES],
        "live_path": {"section_id": sections[0]["id"], "equipment_id": equipment["id"],
                      "executor_id": IDENTITY["executor"], "work_code_id": history["work_codes"][0]["id"],
                      "material_id": history["materials"][0]["id"]},
        "live_orders_seeded": 0, "sessions_seeded": 0, "photos_seeded": 0,
        "credentials": "Operator-supplied distinct private PINs; no generated or printed credentials",
        "repeat": "verify_only_no_import_no_scope_repair_no_pin_reset",
    }


def receipt(manifest, state):
    require(state in {"initializing", "complete"}, "HISTORY_INVALID_RECEIPT_STATE")
    digest = sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False).encode()).hexdigest()
    return f"DalaAI isolated history fixture v1 {state} {digest}"


def _context(db, expected_database):
    require(db.autocommit is True and db.info.transaction_status == 0, "HISTORY_IDLE_OWNER_REQUIRED")
    row = db.execute("SELECT current_database() AS database, current_schema() AS schema, "
                     "current_user=session_user AS direct").fetchone()
    require(bool(expected_database) and row["database"] == expected_database,
            "HISTORY_DATABASE_MISMATCH")
    schema = row["schema"]
    require(isinstance(schema, str) and schema_name(schema) == schema
            and schema != "public" and not schema.startswith("pg_")
            and schema != "information_schema", "HISTORY_ISOLATED_SCHEMA_REQUIRED")
    require(row["direct"] is True, "HISTORY_DIRECT_OWNER_REQUIRED")
    owner = db.execute("SELECT nspowner=(SELECT oid FROM pg_roles WHERE rolname=current_user) AS owned "
                       "FROM pg_namespace WHERE nspname=%s", (schema,)).fetchone()
    require(owner and owner["owned"] is True, "HISTORY_SCHEMA_OWNER_REQUIRED")
    return schema


def _state(db, schema):
    return db.execute("SELECT obj_description(n.oid,'pg_namespace') AS schema_marker, "
                      "obj_description(c.oid,'pg_class') AS receipt FROM pg_namespace n "
                      "LEFT JOIN pg_class c ON c.relnamespace=n.oid AND c.relname='sections' "
                      "AND c.relkind='r' WHERE n.nspname=%s", (schema,)).fetchone()


def _verify_identity_guards(db, schema):
    guards = db.execute("SELECT c.relname,t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                        "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s "
                        "AND t.tgenabled IN ('O','A')", (schema,)).fetchall()
    require({("employees", "employees_identity_immutable"),
             ("employee_sections", "employee_sections_ownership_immutable"),
             ("auth_sessions", "auth_sessions_identity_immutable")} <=
            {(row["relname"], row["tgname"]) for row in guards}, "HISTORY_IDENTITY_GUARDS_REQUIRED")


def _verify_historical_actors(db, history, loader):
    # Never retrieve historical hashes; SQL compares the public disabled sentinel.
    ids = [row["id"] for row in history["employees"]]
    rows = db.execute("SELECT id,employee_code,role,active,on_shift,brigade_id,pin_hash=%s AS locked "
                      "FROM employees WHERE id=ANY(%s::uuid[]) FOR SHARE",
                      (loader.DISABLED_PIN_SENTINEL, ids)).fetchall()
    actual = {str(row["id"]): loader.normalize(row) for row in rows}
    memberships = db.execute("SELECT employee_id,section_id FROM employee_sections "
                            "WHERE employee_id=ANY(%s::uuid[]) FOR SHARE", (ids,)).fetchall()
    for source in history["employees"]:
        wanted = {key: source[key] for key in ("id", "employee_code", "role", "brigade_id")}
        wanted.update(active=False, on_shift=False, locked=True)
        require(actual.get(source["id"]) == wanted, "HISTORY_ACTOR_CHANGED_NO_REPAIR")
        scopes = {str(row["section_id"]) for row in memberships if str(row["employee_id"]) == source["id"]}
        require(scopes == set(source["section_ids"]), "HISTORY_ACTOR_SCOPE_CHANGED_NO_REPAIR")


def _verify_provenance(db, history, loader, mapping):
    """Only immutable import creation events; newer live orders remain untouched."""
    expected_rows, _ = loader.prepare_rows(history, mapping)
    events = [row for row in expected_rows["order_events"] if row["kind"] == "order.created"]
    ids = [row["id"] for row in events]
    actual = db.execute("SELECT e.id,e.order_id,e.details,o.number FROM order_events e "
                        "JOIN orders o ON o.id=e.order_id WHERE e.id=ANY(%s::uuid[]) FOR SHARE OF e,o",
                        (ids,)).fetchall()
    require(len(actual) == 540, "HISTORY_PROVENANCE_MISSING_NO_REPAIR")
    numbers = {str(row["order_id"]): row["number"] for row in actual}
    loader.add_runtime_numbers(events, numbers)
    expected = {row["id"]: (row["order_id"], row["details"]) for row in events}
    require(all(expected.get(str(row["id"])) == (str(row["order_id"]), row["details"])
                for row in actual), "HISTORY_PROVENANCE_CHANGED_NO_REPAIR")


def _verify_live(db, manifest, pins):
    from app.sessions.crypto import Argon2idVerifier
    verifier = Argon2idVerifier()
    for user in manifest["users"]:
        row = db.execute("SELECT employee_code,role,active,on_shift,brigade_id,pin_hash "
                         "FROM employees WHERE id=%s FOR SHARE", (user["id"],)).fetchone()
        require(row is not None and row["employee_code"] == user["employee_code"]
                and row["role"] == user["role"] and row["active"] is True and row["on_shift"] is True
                and row["brigade_id"] is None and verifier.verify(pins[user["role"]], row["pin_hash"]),
                "HISTORY_LIVE_ACCOUNT_CHANGED_NO_REPAIR")
        memberships = db.execute("SELECT section_id FROM employee_sections WHERE employee_id=%s FOR SHARE",
                                 (user["id"],)).fetchall()
        require({str(row["section_id"]) for row in memberships} == set(user["section_ids"]),
                "HISTORY_LIVE_SCOPE_CHANGED_NO_REPAIR")


def apply_fixture(connect, expected_database, pins, *, source_root=ROOT):
    """Owner bootstrap seam. Fresh ready schema only, or exact complete receipt.

    Three durable stages: initialization receipt, C107's atomic import, then
    atomic two-account creation + completion receipt. An incomplete/uncertain
    stage stays blocked for operator inspection; there is no automatic recovery.
    The caller owns explicit authorization and a stopped-runtime startup barrier.
    """
    # Validate all source bytes and human inputs before touching the database.
    pins = read_pins({variable: pins.get(role, "") for role, _, variable in EMPLOYEES})
    loader, history, raw, mapping = canonical_inputs(source_root)
    manifest = public_manifest(history)
    from psycopg import sql
    from argon2 import PasswordHasher
    from argon2.profiles import RFC_9106_LOW_MEMORY
    with connect() as db:
        schema = _context(db, expected_database)
        # Session lock spans the loader's own transaction boundaries; connection
        # closure releases it on failure. Never try to wrap C107 in a fake atomic unit.
        db.execute("SELECT pg_advisory_lock(%s)", (FIXTURE_LOCK,))
        _verify_identity_guards(db, schema)
        current = _state(db, schema)
        require(current is not None, "HISTORY_BOOTSTRAP_STATE_MISSING")
        if current["schema_marker"] == bootstrap_marker("seeded"):
            require(current["receipt"] == receipt(manifest, "complete"), "HISTORY_PROFILE_MISMATCH_NO_ADOPTION")
            with db.transaction():
                _verify_historical_actors(db, history, loader)
                _verify_live(db, manifest, pins)
                _verify_provenance(db, history, loader, mapping)
            return {"status": "ALREADY_PRESENT", "fixture": manifest, "history_import_replayed": False,
                    "created_live_accounts": 0, "existing_credentials_updated": False,
                    "existing_scopes_updated": False, "existing_business_data_changed": False}
        require(current["schema_marker"] == bootstrap_marker("ready") and current["receipt"] is None,
                "HISTORY_FRESH_READY_REQUIRED_NO_PARTIAL_RETRY")
        with db.transaction():
            # Lock and inspect every table in the dedicated schema. No sessions,
            # worker jobs, unknown rows or preimported actors may be adopted.
            tables = db.execute("SELECT c.relname,c.relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user) "
                                "AS owned FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                                "WHERE n.nspname=%s AND c.relkind IN ('r','p') ORDER BY c.relname", (schema,)).fetchall()
            require(set(loader.ALL_TABLES) <= {row["relname"] for row in tables}
                    and all(row["owned"] is True for row in tables), "HISTORY_TABLE_OWNER_REQUIRED")
            for row in tables:
                table = sql.Identifier(schema, row["relname"])
                db.execute(sql.SQL("LOCK TABLE {} IN SHARE ROW EXCLUSIVE MODE").format(table))
                require(db.execute(sql.SQL("SELECT 1 FROM {} LIMIT 1").format(table)).fetchone() is None,
                        "HISTORY_NONEMPTY_SCHEMA_NO_ADOPTION")
            db.execute(sql.SQL("COMMENT ON SCHEMA {} IS {}").format(
                sql.Identifier(schema), sql.Literal(receipt(manifest, "initializing"))))
        imported = loader.load_demo(db, raw, mapping, demo_only=True,
                                    expected_database=expected_database, expected_schema=schema)
        require(imported["status"] == "IMPORTED", "HISTORY_EXPECTED_FRESH_IMPORT")
        with db.transaction():
            require(_state(db, schema)["schema_marker"] == receipt(manifest, "initializing"),
                    "HISTORY_INITIALIZATION_RECEIPT_CHANGED")
            _verify_historical_actors(db, history, loader)
            _verify_provenance(db, history, loader, mapping)
            hasher = PasswordHasher.from_parameters(RFC_9106_LOW_MEMORY)
            for user in manifest["users"]:
                db.execute("INSERT INTO employees(id,employee_code,role,active,on_shift,brigade_id,pin_hash) "
                           "VALUES (%s,%s,%s,true,true,NULL,%s)",
                           (user["id"], user["employee_code"], user["role"], hasher.hash(pins[user["role"]])))
                for section in user["section_ids"]:
                    db.execute("INSERT INTO employee_sections(employee_id,section_id) VALUES (%s,%s)",
                               (user["id"], section))
            db.execute(sql.SQL("COMMENT ON TABLE {} IS {}").format(
                sql.Identifier(schema, "sections"), sql.Literal(receipt(manifest, "complete"))))
            db.execute(sql.SQL("COMMENT ON SCHEMA {} IS {}").format(
                sql.Identifier(schema), sql.Literal(bootstrap_marker("seeded"))))
    return {"status": "APPLIED", "fixture": manifest, "history_import": imported,
            "created_live_accounts": 2, "existing_credentials_updated": False,
            "existing_scopes_updated": False, "existing_business_data_changed": False}


if __name__ == "__main__":
    # No apply CLI: only the reviewed capability launcher owns database setup.
    try:
        print(json.dumps({"status": "PLAN_ONLY_NO_DATABASE_ACCESS", "fixture": public_manifest()},
                         ensure_ascii=False, indent=2))
    except Exception as error:
        print(json.dumps({"status": "HISTORY_PLAN_NOT_CONFIRMED", "error_type": type(error).__name__}))
        raise SystemExit(1) from None
