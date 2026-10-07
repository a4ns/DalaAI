#!/usr/bin/env python3
"""One operator entry point: reviewed first-start/repeat setup plus minimal seed."""
import argparse
import json
import os
from pathlib import Path
import sys

from prepare_demo_database import apply_fresh, migration_plan
from provision_synthetic_demo import (FixtureConflict, apply_fixture, preflight_apply,
                                      public_manifest, schema_name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--schema", type=schema_name, required=True)
    parser.add_argument("--expected-database")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        plan = migration_plan(args.backend)
        if not args.apply:
            print(json.dumps({"status": "PLAN_ONLY_NO_DATABASE_ACCESS", "schema": args.schema,
                              "migrations": plan, "fixture": public_manifest()}, ensure_ascii=False, indent=2))
            return 0
        pins = preflight_apply(args, os.environ)
        # Validate all operator inputs before the first schema write.
        if not os.environ.get("DALA_DEMO_RUNTIME_DATABASE_URL"):
            raise ValueError("DALA_DEMO_RUNTIME_DATABASE_URL must identify an existing restricted LOGIN")
        initialized, code = apply_fresh(args, plan)
        if code:
            print(json.dumps(initialized, ensure_ascii=False, indent=2))
            return code
        sys.path.insert(0, str(args.backend.resolve()))
        import psycopg
        from psycopg.rows import dict_row
        def connect():
            return psycopg.connect(os.environ["DALA_DEMO_OWNER_DATABASE_URL"], autocommit=True, connect_timeout=5,
                options=f"-c search_path={args.schema} -c statement_timeout=10000 -c lock_timeout=5000", row_factory=dict_row)
        seeded = apply_fixture(connect, args.expected_database, pins)
        result = {"status": "SYNTHETIC_DEMO_READY_FOR_APP_START", "database": initialized,
                  "seed": seeded, "deployment_started": False, "browser_verified": False}
    except Exception as error:
        result = {"status": "BOOTSTRAP_NOT_CONFIRMED", "error_type": type(error).__name__,
                  "deployment_started": False, "browser_verified": False}
        if isinstance(error, (ValueError, FixtureConflict)):
            result["reason"] = str(error)
        if type(error).__name__ == "RuntimePrerequisiteError":
            result["runtime_error_code"] = getattr(error, "code", "UNKNOWN")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
