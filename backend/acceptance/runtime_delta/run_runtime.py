#!/usr/bin/env python3
"""Actual app.main lifecycle gate, with owner fixtures and a restricted LOGIN."""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from vertical_acceptance.run import parser, preflight, safe_error
from vertical_acceptance.support import (ORIGIN, REQUIRED_ROUTES, ensure, file_inventory,
    require_local_dsn, route_inventory, schema_name, utc_now, write_json)


def worker(args):
    from fastapi.testclient import TestClient
    from vertical_acceptance.fixtures import connect_factory
    from fixtures_runtime import actual_app_factory, runtime_connect_factory
    from scenarios_runtime import Trace, phase_one, phase_two
    trace = Trace()
    report = {"phase": args.phase, "process_id": os.getpid(), "started_at": utc_now(), "steps": trace.steps}
    try:
        owner_connect = connect_factory(schema_name(args.schema))
        runtime_connect = runtime_connect_factory(args.schema)
        factory = lambda: actual_app_factory(args.schema, runtime_connect)
        with trace.step("Actual app.main mounts required routes, enters validated nonowner lifespan and returns ready"):
            app = factory()
            ensure(REQUIRED_ROUTES <= route_inventory(app), "Actual demo app.main is missing required routes")
            with TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 43000)) as client:
                ensure(app.state.runtime_ready is True, "Actual application did not complete startup validation")
                ensure(client.get("/healthz").status_code == 200, "Actual application health failed")
                ensure(client.get("/readyz").status_code == 200, "Actual restricted runtime readiness failed")
            ensure(app.state.runtime_ready is False, "Actual application did not leave ready state on shutdown")
        if args.phase == "one":
            write_json(args.state, phase_one(owner_connect, trace, factory))
        else:
            phase_two(owner_connect, trace, json.loads(args.state.read_text()), factory)
        report["status"] = "PASS"
        code = 0
    except Exception as error:
        report.update(status="FAIL", **safe_error(error))
        if type(error).__name__ == "RuntimePrerequisiteError":
            report["runtime_error_code"] = getattr(error, "code", "UNKNOWN")
        code = 1
    report["finished_at"] = utc_now()
    write_json(args.report, report)
    return code


def owner_must_be_rejected(owner_connect, schema):
    from fastapi.testclient import TestClient
    from app.runtime import RuntimePrerequisiteError
    from fixtures_runtime import actual_app_factory
    try:
        with TestClient(actual_app_factory(schema, owner_connect, owner_probe=True), base_url=ORIGIN):
            pass
    except RuntimePrerequisiteError as error:
        ensure(error.code in {"ROLE_NOT_RESTRICTED", "ROLE_OWNS_OBJECTS"}, "Owner startup failed for an unrelated prerequisite")
        return {"status": "PASS", "rejection_code": error.code}
    raise AssertionError("Actual application accepted a schema-owning/superuser connection")


def run(args):
    report, migrations, ready = preflight(args)
    report["scope"] = "ACTUAL_APP_MAIN_ASGI_POSTGRESQL_NONOWNER_LOGIN"
    # Base inventory deliberately uses default app settings. Here acceptance
    # uses explicit demo settings and the actual factory, never router assembly.
    report["default_mode_entrypoint_inventory"] = report.pop("application_entrypoint")
    report["limitations"]["production_application_wiring"] = "Explicit demo app.main and real lifespan are exercised only if both real phases complete"
    report["limitations"]["production_role_key_update_hardening"] = "Real restricted LOGIN and startup policy exercised; exhaustive adversarial grants/key-update tests remain A5's separate suite"
    report["application_entrypoint"] = {"status": "NOTRUN", "mode": "demo", "factory": "app.main.create_app"}
    try:
        runtime_module = importlib.import_module("app.runtime")
        ensure(hasattr(runtime_module, "RuntimeSettings") and hasattr(runtime_module, "RuntimePrerequisiteError"), "Actual runtime interface is incomplete")
        report["actual_runtime_module"] = {"status": "AVAILABLE"}
    except Exception as error:
        report["actual_runtime_module"] = {"status": "NOTRUN", **safe_error(error)}
        ready = False
    runtime_dsn = os.environ.get("DALA_ACCEPTANCE_RUNTIME_DATABASE_URL")
    if not runtime_dsn:
        report["restricted_login_dsn"] = {"status": "NOTRUN", "reason": "DALA_ACCEPTANCE_RUNTIME_DATABASE_URL absent; A5 must supply an existing restricted LOGIN"}
        ready = False
    else:
        try:
            from psycopg.conninfo import conninfo_to_dict
            require_local_dsn(runtime_dsn, conninfo_to_dict)
            report["restricted_login_dsn"] = {"status": "AVAILABLE"}
        except Exception:
            report["restricted_login_dsn"] = {"status": "NOTRUN", "reason": "Runtime DSN must explicitly select the same local disposable DB"}
            ready = False
    if not args.run or not ready:
        report.update(status="NOTRUN", finished_at=utc_now())
        write_json(args.report, report)
        print("NOTRUN: actual app.main/nonowner PostgreSQL lifecycle did not execute")
        return 2
    import psycopg
    from psycopg import sql
    from vertical_acceptance.fixtures import connect_factory, seed_catalogues
    from fixtures_runtime import grant_existing_runtime_role, runtime_connect_factory
    schema = "vertical_acceptance_" + uuid4().hex
    created = False
    report["schema"] = schema
    report["phases"] = [{"phase": name, "status": "NOTRUN", "reason": "Not reached"} for name in ("one", "two")]
    code = 1
    try:
        with psycopg.connect(os.environ["DALA_TEST_DATABASE_URL"], autocommit=True, connect_timeout=5) as db:
            db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            created = True
        owner_connect = connect_factory(schema)
        with owner_connect() as db:
            for migration in migrations:
                db.execute(migration.read_text())
        seed_catalogues(owner_connect)
        report["setup"] = {"status": "PASS", "migrations": [p.name for p in migrations], "seeded_orders": 0, "seeded_sessions": 0}
        report["runtime_identity"] = grant_existing_runtime_role(owner_connect, runtime_connect_factory(schema), schema)
        report["owner_startup_rejection"] = owner_must_be_rejected(owner_connect, schema)
        with tempfile.TemporaryDirectory(prefix="dalaai-main-runtime-") as temporary:
            state = Path(temporary) / "synthetic-lifecycle-state.json"
            for index, name in enumerate(("one", "two")):
                target = Path(temporary) / f"phase-{name}.json"
                argv = [sys.executable, str(HERE / "run_runtime.py"), "--backend", str(args.backend.resolve()),
                        "--report", str(target), "--phase", name, "--schema", schema, "--state", str(state)]
                completed = subprocess.run(argv, capture_output=True, text=True, timeout=240)
                report["phases"][index] = (json.loads(target.read_text()) if target.exists() else
                    {"phase": name, "status": "FAIL", "reason": "Child produced no structured evidence", "returncode": completed.returncode})
                if completed.returncode:
                    raise AssertionError(f"Actual runtime lifecycle phase {name} failed; later phase not run")
            ensure(report["phases"][0]["process_id"] != report["phases"][1]["process_id"], "Actual runtime restart requires distinct Python processes")
        ensure(file_inventory(args.backend)["tree_sha256"] == report["source_inventory"]["tree_sha256"], "Candidate source changed during actual runtime acceptance")
        report["application_entrypoint"]["status"] = "PASS"
        report["status"] = "PASS"
        code = 0
    except Exception as error:
        report.update(status="FAIL", **safe_error(error))
        if type(error).__name__ == "RuntimePrerequisiteError":
            report["runtime_error_code"] = getattr(error, "code", "UNKNOWN")
    finally:
        if created:
            try:
                with psycopg.connect(os.environ["DALA_TEST_DATABASE_URL"], autocommit=True, connect_timeout=5) as db:
                    db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name(schema))))
                report["cleanup"] = {"status": "PASS", "runtime_role": "Preserved for A5 to remove; no role was created here"}
            except Exception as error:
                report["cleanup"] = {"status": "FAIL", **safe_error(error)}
                report["status"] = "FAIL"
                code = 1
        report["finished_at"] = utc_now()
        write_json(args.report, report)
    print(f"{report['status']}: actual app.main lifecycle with real nonowner PostgreSQL LOGIN")
    return code


def main():
    args = parser().parse_args()
    sys.path.insert(0, str(args.backend.resolve()))
    # Prevent inherited deployment settings from triggering the module-global
    # app. The tested factory always receives explicit demo RuntimeSettings.
    os.environ["DALA_API_MODE"] = "health"
    return worker(args) if args.phase else run(args)


if __name__ == "__main__":
    raise SystemExit(main())
