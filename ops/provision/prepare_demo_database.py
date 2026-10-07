#!/usr/bin/env python3
"""Owner-only first-start/repeat launcher. Default is a no-DB plan, never a reset.

Applies each exact accepted 001/002/003/004 file once, preserving 003's current
proposals path. Only this exact ready-marked bootstrap can be verified on repeat;
unmarked, foreign or partially initialized schemas are never overwritten.
Operator supplies existing owner/runtime identities; no roles are created.
"""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

from provision_synthetic_demo import schema_name

MIGRATIONS = (
    ("db/migrations/001_vertical_slice.sql", "f6d82acc75611ecdb01ac2b2d058e21eab91fa658101c9150013c44d16684fd3"),
    ("db/migrations/002_trusted_evidence.sql", "c1999e097d079dcd3ca89be162b478061ebefde33c6e92f127605392e5441a98"),
    ("db/proposals/003_auth_rate_limits.sql", "aafe87eead4b7eb2cdf88c74833a0fc8313343e79804b24bfacfc4b9fdd7f5c1"),
    ("db/migrations/004_immutable_reference_keys.sql", "66789e096bdc6bf5c46f93fb49ac3f062d62b27309b26147cc39cf5b74360d64"),
)
BASE_SHA = "dfe9d8f7772b1a1c44f5a506c03e26c55fb5e1ca"


def bundle_hash():
    return sha256(json.dumps(MIGRATIONS, separators=(",", ":")).encode()).hexdigest()


def bootstrap_marker(state):
    if state not in {"initializing", "ready", "seeded"}:
        raise ValueError("Invalid bootstrap state")
    return f"DalaAI isolated synthetic demo bootstrap v1 {state} {bundle_hash()}"


def migration_plan(backend):
    if (backend / "db/migrations/003_auth_rate_limits.sql").exists():
        raise ValueError("Migration 003 is duplicated or moved; use a newly reviewed explicit launcher")
    result = []
    for relative, expected in MIGRATIONS:
        path = backend / relative
        if not path.is_file() or sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Accepted migration file/hash mismatch: {relative}")
        result.append({"path": relative, "sha256": expected})
    return result


def apply_fresh(args, plan):
    if os.environ.get("DALA_API_MODE") != "demo" or os.environ.get("DALA_DEMO_SEED_ALLOWED") != "1":
        raise ValueError("Applying requires DALA_API_MODE=demo and DALA_DEMO_SEED_ALLOWED=1")
    if not args.expected_database:
        raise ValueError("--expected-database must explicitly identify the isolated demo database")
    if not os.environ.get("DALA_DEMO_OWNER_DATABASE_URL") or not os.environ.get("DALA_DEMO_RUNTIME_DATABASE_URL"):
        raise ValueError("Operator-supplied existing owner and restricted runtime database identities are required")
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
    from database_profile import grant_existing_runtime_role, identity
    sys.path.insert(0, str(args.backend.resolve()))
    from app.runtime import validate_database
    def connector(variable, *, scoped=True):
        def connect():
            kwargs = {"autocommit": True, "connect_timeout": 5, "row_factory": dict_row}
            if scoped:
                kwargs["options"] = f"-c search_path={args.schema} -c statement_timeout=10000 -c lock_timeout=5000"
            return psycopg.connect(os.environ[variable], **kwargs)
        return connect
    owner = connector("DALA_DEMO_OWNER_DATABASE_URL")
    runtime = connector("DALA_DEMO_RUNTIME_DATABASE_URL")
    with connector("DALA_DEMO_OWNER_DATABASE_URL", scoped=False)() as db:
        if db.execute("SELECT current_database() AS name").fetchone()["name"] != args.expected_database:
            raise ValueError("Connected database does not match --expected-database")
        exists = db.execute("SELECT obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s", (args.schema,)).fetchone()
        if exists:
            if exists["marker"] not in {bootstrap_marker("ready"), bootstrap_marker("seeded")}:
                raise ValueError("Target schema exists without the exact ready marker; no adoption, migration replay or reset permitted")
            owner_identity, runtime_identity = identity(owner), identity(runtime)
            if any(owner_identity[key] != runtime_identity[key] for key in ("database_name", "server_address", "server_port")):
                raise ValueError("Owner and runtime must target the same isolated database")
            validate_database(runtime)
            return {"status": "EXISTING_DEMO_SCHEMA_VERIFIED", "schema": args.schema,
                    "runtime_validation": "PASS", "migration_bundle_sha256": bundle_hash(),
                    "migrations_replayed": False, "grants_replayed": False, "roles_created": 0,
                    "credentials_saved": False, "seeded_accounts": 0, "deployment_started": False}, 0
        with db.transaction():
            db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(args.schema)))
            db.execute(sql.SQL("COMMENT ON SCHEMA {} IS {}").format(sql.Identifier(args.schema), sql.Literal(bootstrap_marker("initializing"))))
    # Original migration files carry their own transaction boundaries. Never
    # pretend these four files are one atomic transaction. A partial failure is
    # preserved and must be inspected by the operator; it cannot become ready.
    applied = []
    try:
        with owner() as db:
            for entry in plan:
                data = (args.backend / entry["path"]).read_bytes()
                if sha256(data).hexdigest() != entry["sha256"]:
                    raise ValueError("Migration source changed after planning")
                db.execute(data.decode("utf-8"))
                applied.append(entry["path"])
        role = grant_existing_runtime_role(owner, runtime, args.schema)
        validate_database(runtime)
        with owner() as db:
            db.execute(sql.SQL("COMMENT ON SCHEMA {} IS {}").format(sql.Identifier(args.schema), sql.Literal(bootstrap_marker("ready"))))
    except Exception as error:
        result = {"status": "INITIALIZATION_FAILED_SCHEMA_PRESERVED", "schema": args.schema,
                  "confirmed_migrations": applied, "error_type": type(error).__name__,
                  "next_action": "Keep runtime disabled; inspect the preserved schema. No automatic cleanup or replay."}
        if type(error).__name__ == "RuntimePrerequisiteError":
            result["runtime_error_code"] = getattr(error, "code", "UNKNOWN")
        return result, 1
    return {"status": "SCHEMA_READY_FOR_SYNTHETIC_SEED", "schema": args.schema,
            "applied_migrations": applied, "runtime_validation": "PASS",
            "runtime_identity": {key: value for key, value in role.items() if key != "role_name"},
            "migration_bundle_sha256": bundle_hash(), "migrations_replayed": False,
            "roles_created": 0, "credentials_saved": False, "seeded_accounts": 0,
            "deployment_started": False}, 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--schema", type=schema_name, required=True, help="New isolated demo schema or the same exact ready/seeded-marked bootstrap")
    parser.add_argument("--expected-database")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        plan = migration_plan(args.backend)
        if not args.apply:
            result, code = {"status": "PLAN_ONLY_NO_DATABASE_ACCESS", "accepted_base_sha": BASE_SHA,
                            "schema": args.schema, "migrations": plan, "roles_created": 0}, 0
        else:
            result, code = apply_fresh(args, plan)
    except Exception as error:
        result, code = {"status": "FAILED_NO_CONFIRMED_INITIALIZATION", "error_type": type(error).__name__}, 1
        if isinstance(error, ValueError):
            result["reason"] = str(error)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

# Explicit separate worker-capable first-start plan. The legacy migration set,
# v1 marker and apply_fresh behavior above remain byte-for-byte unchanged.
WORKER_EXTENSIONS = (
    ('db/proposals/005_web_push_subscriptions.sql', '152c4bada41b8ca7eddd25d8aa06a2cfe0b9b0bed578555fa70a0f265e064477'),
    ('db/migrations/011_durable_job_leases.sql', 'e517a44d247b20f00133f93627ddf43109d5a8a610e39273ef74ffcde6c11495'),
    ('db/migrations/012_delivery_dispatch_attempts.sql', '14351dc30aaec1fd517d5db47644961dbf1982a54ce7af4cb1b0a98def0b49e1'),
)


def worker_migration_plan(backend):
    """Exact seven files, no directory glob, renumbering or partial upgrade."""
    result = migration_plan(backend)
    if (backend / 'db/migrations/005_web_push_subscriptions.sql').exists():
        raise ValueError('Migration 005 is duplicated or moved; use a reviewed explicit plan')
    for relative, expected in WORKER_EXTENSIONS:
        path = backend / relative
        if not path.is_file() or sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f'Accepted worker migration file/hash mismatch: {relative}')
        result.append({'path': relative, 'sha256': expected})
    return result
