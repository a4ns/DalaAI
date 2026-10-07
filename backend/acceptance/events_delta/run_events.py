#!/usr/bin/env python3
"""Separate events HTTP delta; preserves the frozen v1 harness unchanged."""
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
from vertical_acceptance.support import file_inventory, route_inventory, schema_name, utc_now, write_json


def worker(args):
    from vertical_acceptance.fixtures import connect_factory
    from vertical_acceptance.scenarios import Trace
    from scenarios_events import phase_one, phase_two
    trace = Trace()
    report = {"phase": args.phase, "process_id": os.getpid(), "started_at": utc_now(), "steps": trace.steps}
    try:
        connect = connect_factory(schema_name(args.schema))
        if args.phase == "one":
            write_json(args.state, phase_one(connect, trace))
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


def run(args):
    report, migrations, ready = preflight(args)
    report["scope"] = "REAL_COMPONENT_HTTP_ASGI_POSTGRESQL_EVENT_DELTA"
    report["limitations"]["order_events_http"] = "This delta exercises event pages only if both real phases complete"
    try:
        from scenarios_events import create_events_app, EVENT_ROUTE
        importlib.import_module("app.order_events.service")
        importlib.import_module("app.order_events.http")
        # Construction-only availability check cannot stand in for real HTTP.
        def unexpected_connect():
            raise AssertionError("Event router construction unexpectedly accessed PostgreSQL")
        create_events_app(unexpected_connect)
        report["event_component_construction"] = {"status": "AVAILABLE"}
    except Exception as error:
        report["event_component_construction"] = {"status": "NOTRUN", **safe_error(error)}
        ready = False
    try:
        main = importlib.import_module("app.main")
        mounted = ("GET", "/api/v1/orders/{order_id}/events") in route_inventory(main.create_app())
        report["application_event_endpoint"] = {"status": "MOUNTED_UNEXERCISED" if mounted else "NOT_MOUNTED",
                                                "reason": "Actual app.main route inventory, not test-owned composition"}
    except Exception as error:
        report["application_event_endpoint"] = {"status": "NOTRUN", **safe_error(error)}
    if not args.run or not ready:
        report.update(status="NOTRUN", finished_at=utc_now())
        write_json(args.report, report)
        print("NOTRUN: real event-page HTTP+PostgreSQL delta did not execute")
        return 2
    import psycopg
    from psycopg import sql
    from vertical_acceptance.fixtures import connect_factory, seed_catalogues
    schema = "vertical_acceptance_" + uuid4().hex
    created = False
    report["schema"] = schema
    report["phases"] = [{"phase": name, "status": "NOTRUN", "reason": "Not reached"} for name in ("one", "two")]
    code = 1
    try:
        with psycopg.connect(os.environ["DALA_TEST_DATABASE_URL"], autocommit=True, connect_timeout=5) as db:
            db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            created = True
        connect = connect_factory(schema)
        with connect() as db:
            for migration in migrations:
                db.execute(migration.read_text())
        seed_catalogues(connect)
        report["setup"] = {"status": "PASS", "migrations": [p.name for p in migrations], "seeded_orders": 0, "seeded_sessions": 0}
        with tempfile.TemporaryDirectory(prefix="dalaai-events-vertical-") as temporary:
            state = Path(temporary) / "synthetic-event-state.json"
            for index, name in enumerate(("one", "two")):
                target = Path(temporary) / f"phase-{name}.json"
                argv = [sys.executable, str(HERE / "run_events.py"), "--backend", str(args.backend.resolve()),
                        "--report", str(target), "--phase", name, "--schema", schema, "--state", str(state)]
                completed = subprocess.run(argv, capture_output=True, text=True, timeout=180)
                report["phases"][index] = (json.loads(target.read_text()) if target.exists() else
                    {"phase": name, "status": "FAIL", "reason": "Child produced no structured evidence", "returncode": completed.returncode})
                if completed.returncode:
                    raise AssertionError(f"Real event-page phase {name} failed; later phase not run")
            if report["phases"][0]["process_id"] == report["phases"][1]["process_id"]:
                raise AssertionError("Event restart evidence requires distinct Python processes")
        if file_inventory(args.backend)["tree_sha256"] != report["source_inventory"]["tree_sha256"]:
            raise AssertionError("Candidate source changed during event acceptance")
        report["status"] = "PASS"
        code = 0
    except Exception as error:
        report.update(status="FAIL", **safe_error(error))
    finally:
        if created:
            try:
                with psycopg.connect(os.environ["DALA_TEST_DATABASE_URL"], autocommit=True, connect_timeout=5) as db:
                    db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name(schema))))
                report["cleanup"] = {"status": "PASS"}
            except Exception as error:
                report["cleanup"] = {"status": "FAIL", **safe_error(error)}
                report["status"] = "FAIL"
                code = 1
        report["finished_at"] = utc_now()
        write_json(args.report, report)
    print(f"{report['status']}: component event HTTP gate; app.main endpoint status is separate")
    return code


def main():
    args = parser().parse_args()
    sys.path.insert(0, str(args.backend.resolve()))
    return worker(args) if args.phase else run(args)


if __name__ == "__main__":
    raise SystemExit(main())
