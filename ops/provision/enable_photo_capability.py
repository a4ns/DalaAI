#!/usr/bin/env python3
"""Explicit optional photos INSERT capability; no seed reset or storage creation.

Install beside the reviewed ops/provision helpers. Default is a no-database plan.
Actual execution belongs to the authorized operator after photo runtime acceptance.
"""
import argparse
import inspect
import json
import os
from pathlib import Path
import re
import sys


def identifier(value):
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", value):
        raise argparse.ArgumentTypeError("One explicit lowercase schema identifier is required")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--schema", type=identifier, required=True)
    parser.add_argument("--expected-database")
    parser.add_argument("--provision-dir", type=Path, default=Path(__file__).resolve().parent,
                        help="Reviewed provision helper directory; defaults to this installed script directory")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--bootstrap", action="store_true", help="Explicit photo-aware first-start/repeat path including the reviewed minimal seed")
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps({"status": "PLAN_ONLY_NO_DATABASE_ACCESS", "schema": args.schema,
            "optional_capability": "photo_storage", "grant": {"table": "photos", "privilege": "INSERT"},
            "role_creation": False, "capability_marker_rewrite": False, "file_valid_update": False,
            "baseline_bootstrap_requested": args.bootstrap,
            "delete_privilege": False, "storage_directory_creation": False}, indent=2))
        return 0
    grant_attempted = False
    try:
        if (os.environ.get("DALA_API_MODE") != "demo" or os.environ.get("DALA_DEMO_SEED_ALLOWED") != "1"
                or os.environ.get("DALA_DEMO_PHOTO_CAPABILITY_ALLOWED") != "1"):
            raise ValueError("Explicit demo provisioning and DALA_DEMO_PHOTO_CAPABILITY_ALLOWED=1 are required")
        if not args.expected_database:
            raise ValueError("--expected-database must identify the isolated demo database")
        if not all(os.environ.get(name) for name in ("DALA_DEMO_OWNER_DATABASE_URL", "DALA_DEMO_RUNTIME_DATABASE_URL")):
            raise ValueError("Existing owner and restricted runtime database identities are required")
        sys.path.insert(0, str(args.provision_dir.resolve()))
        sys.path.insert(0, str(args.backend.resolve()))
        from prepare_demo_database import apply_fresh, bootstrap_marker, migration_plan
        from provision_synthetic_demo import apply_fixture, preflight_apply
        from database_profile import identity
        from app.runtime import validate_database
        if "photo_enabled" not in inspect.signature(validate_database).parameters:
            raise ValueError("Accepted capability-aware runtime validator is not available")
        pins = preflight_apply(args, os.environ) if args.bootstrap else None
        bootstrap_plan = migration_plan(args.backend) if args.bootstrap else None
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row
        def connector(variable):
            def connect():
                return psycopg.connect(os.environ[variable], autocommit=True, connect_timeout=5,
                    options=f"-c search_path={args.schema} -c statement_timeout=10000 -c lock_timeout=5000", row_factory=dict_row)
            return connect
        owner = connector("DALA_DEMO_OWNER_DATABASE_URL")
        runtime = connector("DALA_DEMO_RUNTIME_DATABASE_URL")
        owner_identity, runtime_identity = identity(owner), identity(runtime)
        if owner_identity["database_name"] != args.expected_database:
            raise ValueError("Connected database differs from --expected-database")
        if any(owner_identity[key] != runtime_identity[key] for key in ("database_name", "server_address", "server_port")):
            raise ValueError("Owner and runtime must target the same isolated database")
        if owner_identity["role_name"] == runtime_identity["role_name"]:
            raise ValueError("Runtime must be the existing distinct restricted LOGIN")
        with owner() as db:
            marker = db.execute("SELECT obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s", (args.schema,)).fetchone()
        initialized = None
        if marker is None and args.bootstrap:
            # Only a genuinely new schema uses the frozen photo-off initializer.
            # A ready photo-enabled profile must never replay its off validation.
            initialized, code = apply_fresh(args, bootstrap_plan)
            if code:
                raise ValueError("Fresh baseline initialization failed; schema is preserved, runtime must stay stopped")
            with owner() as db:
                marker = db.execute("SELECT obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s", (args.schema,)).fetchone()
        if marker is None or marker["marker"] not in {bootstrap_marker("ready"), bootstrap_marker("seeded")}:
            raise ValueError("Exact reviewed ready/seeded bootstrap marker required; no schema adoption")
        with runtime() as db:
            already = db.execute("SELECT has_table_privilege('photos','INSERT') AS allowed").fetchone()["allowed"]
        # Off-mode intentionally rejects photos INSERT. Existing photo capability
        # is checked with the photo-aware validator and never downgraded/replayed.
        validate_database(runtime, photo_enabled=bool(already))
        seeded = apply_fixture(owner, args.expected_database, pins) if args.bootstrap else None
        if not already:
            grant_attempted = True
            with owner() as db, db.transaction():
                db.execute(sql.SQL("GRANT INSERT ON {} TO {}").format(
                    sql.Identifier(args.schema, "photos"), sql.Identifier(runtime_identity["role_name"])))
        validate_database(runtime, photo_enabled=True)
        result = {"status": "PHOTO_CAPABILITY_ALREADY_VALID" if already else "PHOTO_CAPABILITY_VALIDATED",
                  "schema": args.schema, "grant": "INSERT photos only", "runtime_validation": "PASS",
                  "capability_marker_rewritten": False, "roles_created": 0, "storage_directory_created": False,
                  "deployment_started": False, "physical_photo_flow_verified": False}
        if args.bootstrap:
            result.update(bootstrap_mode=True, initialization=initialized or {"status": "EXISTING_SCHEMA_NO_REPLAY"}, seed=seeded)
    except Exception as error:
        result = {"status": "PHOTO_CAPABILITY_NOT_CONFIRMED", "error_type": type(error).__name__,
                  "grant_attempted": grant_attempted, "grant_may_have_committed": grant_attempted,
                  "next_action": "Keep the runtime stopped; inspect actual grants before retry. No automatic revoke/reset."}
        if isinstance(error, ValueError):
            result["reason"] = str(error)
        if type(error).__name__ == "RuntimePrerequisiteError":
            result["runtime_error_code"] = getattr(error, "code", "UNKNOWN")
        print(json.dumps(result, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
