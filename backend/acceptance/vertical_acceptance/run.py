"""Fail-closed CLI: 0 = real component gate PASS, 1 = FAIL, 2 = NOTRUN.

The coordinator owns setup/cleanup; phase subprocesses own only real HTTP reads
and writes in one random schema. No network other than explicit local PostgreSQL.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4

from .support import (file_inventory, inspect_main_wiring, module_inventory,
                      require_local_dsn, schema_name, utc_now, write_json)

LIMITATIONS = {
    "production_application_wiring": "Inspected separately; test-owned component assembly is not app.main execution",
    "physical_database_restart": "NOTRUN: only backend Python processes are restarted",
    "deployed_network_tls": "NOTRUN: HTTP is in-process ASGI at an HTTPS logical origin",
    "browser_android_draft_retention": "NOTRUN: API recovery contract and retained harness intent only",
    "photo_upload_decode_storage": "NOTRUN: planned path has no required photo; unplanned missing-photo close is denied",
    "ai_provider_or_worker_execution": "NOTRUN: AI intent persistence only; no model calls or fabricated assessments",
    "notification_delivery": "NOTRUN: durable intents only; no delivery worker or external recipient",
    "order_events_http": "NOTRUN: no event-list route in current component candidates; audit checked read-only in DB",
    "production_role_key_update_hardening": "NOTRUN: schema-owner component gate; A5 owns restricted-role security gate",
    "reports_and_device_e2e": "NOTRUN: separate C0/C4/device scope",
}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--backend", type=Path, required=True, help="One already assembled backend directory")
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--source-sha", default="UNCOMMITTED_LOCAL_ASSEMBLY", help="Exact source commit if applicable; tree hash is always recorded")
    p.add_argument("--run", action="store_true", help="Run against explicitly supplied local disposable PostgreSQL")
    p.add_argument("--phase", choices=("one", "two"), help=argparse.SUPPRESS)
    p.add_argument("--schema", help=argparse.SUPPRESS)
    p.add_argument("--state", type=Path, help=argparse.SUPPRESS)
    return p


def safe_error(error):
    # psycopg errors can contain a DSN, identifiers or query values. Never print
    # the raw exception or traceback into reusable acceptance evidence.
    result = {"error_type": type(error).__name__}
    if isinstance(error, AssertionError):
        result["reason"] = str(error)
    return result


def phase(args):
    from .fixtures import connect_factory
    from .scenarios import Trace, phase_one, phase_two
    trace = Trace()
    report = {"phase": args.phase, "process_id": os.getpid(), "started_at": utc_now(), "steps": trace.steps}
    try:
        connect = connect_factory(schema_name(args.schema))
        if args.phase == "one":
            state = phase_one(connect, trace)
            write_json(args.state, state)  # Only synthetic order payloads and receipts, no session secrets.
        else:
            phase_two(connect, trace, json.loads(args.state.read_text()))
        report["status"] = "PASS"
        code = 0
    except Exception as error:
        report.update(status="FAIL", **safe_error(error))
        code = 1
    report["finished_at"] = utc_now()
    write_json(args.report, report)
    return code


def preflight(args):
    backend = args.backend.resolve()
    checks = []
    report = {"started_at": utc_now(), "scope": "REAL_COMPONENT_ASSEMBLY_HTTP_ASGI_PLUS_POSTGRESQL",
              "source_sha": args.source_sha, "source_inventory": file_inventory(backend),
              "limitations": LIMITATIONS, "checks": checks}
    modules = module_inventory()
    report["modules"] = modules
    missing = [entry["module"] for entry in modules if entry["status"] != "AVAILABLE"]
    if missing:
        checks.append({"name": "required_runtime_modules", "status": "NOTRUN", "missing": missing})
    else:
        checks.append({"name": "required_runtime_modules", "status": "AVAILABLE"})
    migrations = sorted((backend / "db" / "migrations").glob("*.sql"))
    names = [path.name for path in migrations]
    expected = {"001_vertical_slice.sql", "002_trusted_evidence.sql", "003_auth_rate_limits.sql"}
    absent = sorted(expected - set(names))
    checks.append({"name": "migrations", "status": "NOTRUN" if absent else "AVAILABLE", "files": names, "missing": absent})
    try:
        report["application_entrypoint"] = inspect_main_wiring()
    except Exception as error:
        report["application_entrypoint"] = {"status": "NOTRUN", "reason": "Entry-point inspection could not finish", **safe_error(error)}
    if not os.environ.get("DALA_TEST_DATABASE_URL"):
        checks.append({"name": "explicit_local_disposable_database", "status": "NOTRUN", "reason": "DALA_TEST_DATABASE_URL absent"})
    elif not missing:
        from psycopg.conninfo import conninfo_to_dict
        try:
            require_local_dsn(os.environ["DALA_TEST_DATABASE_URL"], conninfo_to_dict)
            if os.environ.get("PGSERVICE") or os.environ.get("PGSERVICEFILE") or os.environ.get("PGHOSTADDR"):
                raise ValueError("Ambient PostgreSQL service/hostaddr configuration is not allowed")
            checks.append({"name": "explicit_local_disposable_database", "status": "AVAILABLE"})
        except Exception:
            checks.append({"name": "explicit_local_disposable_database", "status": "NOTRUN", "reason": "DSN must explicitly select one local host and database without service indirection"})
    if os.environ.get("DALA_ACCEPTANCE_DISPOSABLE") != "1":
        checks.append({"name": "disposable_database_acknowledgement", "status": "NOTRUN", "reason": "Set DALA_ACCEPTANCE_DISPOSABLE=1 only for a synthetic disposable DB"})
    ready = not any(check["status"] == "NOTRUN" for check in checks)
    return report, migrations, ready


def run(args):
    report, migrations, ready = preflight(args)
    if not args.run or not ready:
        report.update(status="NOTRUN", reason="Preflight only" if not args.run else "Required runtime prerequisites are unavailable", finished_at=utc_now())
        write_json(args.report, report)
        print("NOTRUN: no HTTP+PostgreSQL acceptance executed; inspect the report")
        return 2
    import psycopg
    from psycopg import sql
    from .fixtures import connect_factory, seed_catalogues
    schema = "vertical_acceptance_" + uuid4().hex
    created_schema = False
    report["schema"] = schema
    report["phases"] = [{"phase": name, "status": "NOTRUN", "reason": "Not reached"} for name in ("one", "two")]
    code = 1
    try:
        with psycopg.connect(os.environ["DALA_TEST_DATABASE_URL"], autocommit=True, connect_timeout=5) as db:
            db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            created_schema = True
        connect = connect_factory(schema)
        with connect() as db:
            for migration in migrations:
                db.execute(migration.read_text())
        seed_catalogues(connect)
        report["setup"] = {"status": "PASS", "migrations": [p.name for p in migrations],
                           "synthetic_catalogues": True, "seeded_orders": 0, "seeded_sessions": 0}
        with tempfile.TemporaryDirectory(prefix="dalaai-vertical-") as temporary:
            root = Path(temporary)
            state = root / "synthetic-order-state.json"
            for index, name in enumerate(("one", "two")):
                target = root / f"phase-{name}.json"
                argv = [sys.executable, "-m", "vertical_acceptance.run", "--backend", str(args.backend.resolve()),
                        "--report", str(target), "--phase", name, "--schema", schema, "--state", str(state)]
                environment = dict(os.environ)
                environment["PYTHONPATH"] = os.pathsep.join([str(Path(__file__).resolve().parents[1]), str(args.backend.resolve()), environment.get("PYTHONPATH", "")])
                completed = subprocess.run(argv, env=environment, capture_output=True, text=True, timeout=180)
                if target.exists():
                    report["phases"][index] = json.loads(target.read_text())
                else:
                    report["phases"][index] = {"phase": name, "status": "FAIL", "reason": "Child exited without structured evidence", "returncode": completed.returncode}
                if completed.returncode != 0:
                    raise AssertionError(f"HTTP acceptance phase {name} failed; later phase was not run")
            if report["phases"][0]["process_id"] == report["phases"][1]["process_id"]:
                raise AssertionError("Backend restart evidence requires two distinct Python processes")
        after = file_inventory(args.backend)
        if after["tree_sha256"] != report["source_inventory"]["tree_sha256"]:
            raise AssertionError("Candidate source changed while acceptance was running")
        report["status"] = "PASS"
        code = 0
    except Exception as error:
        report.update(status="FAIL", **safe_error(error))
    finally:
        if created_schema:
            try:
                with psycopg.connect(os.environ["DALA_TEST_DATABASE_URL"], autocommit=True, connect_timeout=5) as db:
                    db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name(schema))))
                report["cleanup"] = {"status": "PASS", "scope": "Only the schema created by this invocation"}
            except Exception as error:
                report["cleanup"] = {"status": "FAIL", **safe_error(error)}
                report["status"] = "FAIL"
                code = 1
        else:
            report["cleanup"] = {"status": "NOT_NEEDED"}
        report["finished_at"] = utc_now()
        write_json(args.report, report)
    print(f"{report['status']}: component HTTP+PostgreSQL gate; application wiring and excluded gates are separate")
    return code


def main():
    args = parser().parse_args()
    sys.path.insert(0, str(args.backend.resolve()))
    return phase(args) if args.phase else run(args)


if __name__ == "__main__":
    raise SystemExit(main())
