#!/usr/bin/env python3
"""Guarded historical import of the pinned C1 synthetic export, never live HTTP.

The CLI is offline only. An authorized operator supplies an already-open OWNER
connection to load_demo(); this module never discovers connection credentials.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
from uuid import UUID


SOURCE_COMMIT = "8af3897f03aa2f41f0af07ec74ec2c807a4a535a"
HISTORY_SHA256 = "7d888cdd5bb6a9c01ca7c543fae9e393335d07210dab811aa754f12331d1d2e1"
LOADER_VERSION = "1.0.0"
WATERMARK = "Синтетические данные — не история предприятия"
PHOTO_POLICY = "metadata_only_no_image_bytes_no_file_valid_claim"
MAX_HISTORY_BYTES = 8 * 1024 * 1024
LOCK_KEY = 0x44414C4141494331
LIVE_DEMO_ACCOUNT_IDS = frozenset({
    "8d27067c-4e86-50a2-87c4-f1012f53a2bb",  # DALA-DEMO-MASTER: live fixture only
    "37baa480-be02-54bc-837c-6c0b2a00ec12",  # DALA-DEMO-EXECUTOR: live fixture only
})

# Static column allowlists, also used for comparison: never SELECT * from auth.
COLUMNS = {
    "sections": ("id", "code", "label"),
    "brigades": ("id", "section_id", "code", "label"),
    "equipment": ("id", "section_id", "code", "label"),
    "work_codes": ("id", "code", "label"),
    "materials": ("id", "code", "label", "unit"),
    "orders": ("id", "version", "assignment_revision", "scheduling_revision", "status",
               "type", "description", "section_id", "equipment_id", "executor_id",
               "brigade_id", "created_by", "issued_at", "due_at", "norm_minutes",
               "priority", "comment", "current_submission_id", "updated_at"),
    "submissions": ("id", "order_id", "assignment_revision", "attempt_number",
                    "submitted_by", "submitted_at", "done_late", "work_description",
                    "work_code_id", "comment", "completeness", "missing_evidence",
                    "after_photo_ids"),
    "material_writeoffs": ("submission_id", "material_id", "quantity"),
    "reviews": ("id", "submission_id", "reviewer_id", "decision", "reason", "final_score", "created_at"),
    "order_events": ("id", "order_id", "sequence", "order_version", "assignment_revision",
                     "scheduling_revision", "kind", "reason", "details", "actor_id",
                     "operation_id", "from_status", "to_status", "submission_id",
                     "occurred_at", "recorded_at"),
}
CATALOGUES = ("sections", "brigades", "equipment", "work_codes", "materials")
EMPTY_TABLES = ("photos", "ai_assessments", "ai_jobs", "delivery_jobs", "operation_receipts")
ACCOUNT_TABLES = ("employees", "employee_sections")
ALL_TABLES = (*COLUMNS, *EMPTY_TABLES, *ACCOUNT_TABLES)
JSON_COLUMNS = {"details", "missing_evidence"}
TIMESTAMPS = {"issued_at", "due_at", "updated_at", "submitted_at", "created_at", "occurred_at", "recorded_at"}


class ImportBlocked(ValueError):
    """Fail-closed precondition or conflicting existing data. No repair is made."""


def require(condition, message):
    if not condition:
        raise ImportBlocked(message)


def canonical_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def read_history(raw):
    """Accept only exact bytes of the reviewed default 540-order C1 export.

    Hashing before JSON decoding rejects duplicate-key, NaN, extra-field, truth
    leakage, relabelled real data and alternate serialization inputs alike.
    """
    require(type(raw) is bytes and len(raw) <= MAX_HISTORY_BYTES, "Expected bounded history bytes")
    require(hashlib.sha256(raw).hexdigest() == HISTORY_SHA256,
            "History differs from the approved canonical C1 export")
    return json.loads(raw)


def normalize(value):
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    return value


def identity_map(history, mapping):
    """The non-secret map is {canonical employee_code: existing account UUID}."""
    expected = {item["employee_code"] for item in history["employees"]}
    require(type(mapping) is dict and set(mapping) == expected,
            "Explicit mapping for all 17 canonical synthetic employee codes is required")
    result = {}
    for employee in history["employees"]:
        value = mapping[employee["employee_code"]]
        try:
            require(type(value) is str and str(UUID(value)) == value, "Mapping requires canonical UUID strings")
        except (ValueError, TypeError, AttributeError) as exc:
            raise ImportBlocked("Mapping requires canonical UUID strings") from exc
        result[employee["id"]] = value
    require(len(set(result.values())) == len(result), "Synthetic identities cannot share an account")
    require(not (set(result.values()) & LIVE_DEMO_ACCOUNT_IDS), "Live demo identities cannot receive historical actor mappings")
    business_ids = {row["id"] for table, rows in history.items() if isinstance(rows, list)
                    and table != "employees" for row in rows if "id" in row}
    require(not (set(result.values()) & business_ids), "Mapped account collides with the canonical business namespace")
    return result


def prepare_rows(history, mapping):
    """Private projection; only call with read_history()'s pinned document."""
    identities = identity_map(history, mapping)
    mapped = lambda value: identities[value] if value is not None else None
    mapping_hash = hashlib.sha256(canonical_bytes(mapping)).hexdigest()
    orders = {order["id"]: order for order in history["orders"]}
    photos = {}
    for photo in history["photos"]:
        photos.setdefault(photo["order_id"], []).append(photo)
    rows = {table: [] for table in COLUMNS}
    for table in CATALOGUES:
        rows[table] = [dict(item) for item in history[table]]
    for source in history["orders"]:
        row = {column: source[column] for column in COLUMNS["orders"]
               if column not in {"executor_id", "brigade_id"}}
        row.update(source["assignment"])
        row["executor_id"] = mapped(row["executor_id"])
        row["created_by"] = mapped(row["created_by"])
        row["comment"] = f"{WATERMARK}; historical snapshot; photo bytes unavailable. {source['comment']}"
        rows["orders"].append(row)
    for source in history["submissions"]:
        row = {column: source[column] for column in COLUMNS["submissions"] if column in source}
        row.update({column: source["payload"][column]
                    for column in ("work_description", "work_code_id", "comment", "after_photo_ids")})
        row["submitted_by"] = mapped(row["submitted_by"])
        rows["submissions"].append(row)
    rows["material_writeoffs"] = [dict(row, quantity=Decimal(str(row["quantity"])))
                                   for row in history["material_writeoffs"]]
    rows["reviews"] = [dict(row, reviewer_id=mapped(row["reviewer_id"])) for row in history["reviews"]]
    for source in history["order_events"]:
        row = dict(source, actor_id=mapped(source["actor_id"]), details=dict(source["details"]))
        if source["kind"] == "order.created":
            row["details"]["synthetic_import"] = {
                "synthetic": True, "loader_version": LOADER_VERSION, "source_commit": SOURCE_COMMIT,
                "history_sha256": HISTORY_SHA256, "identity_mapping_sha256": mapping_hash,
                "source_order_number": orders[source["order_id"]]["number"],
                "watermark": WATERMARK, "photo_policy": PHOTO_POLICY,
                "source_photo_placeholders": photos.get(source["order_id"], []),
                "historical_completeness_not_verified_evidence": True,
            }
        rows["order_events"].append(row)
    for table_rows in rows.values():
        for row in table_rows:
            for column in TIMESTAMPS & row.keys():
                row[column] = datetime.fromisoformat(row[column].replace("Z", "+00:00"))
    return rows, identities


def key_for(table, row):
    return (row["submission_id"], row["material_id"]) if table == "material_writeoffs" else row["id"]


def qualified(schema, table):
    # Called only after schema validation; table names are static allowlists.
    return f'"{schema}"."{table}"'


def verify_accounts(db, schema, history, identities):
    accounts = db.execute(f"SELECT id,employee_code,role,active,brigade_id FROM {qualified(schema, 'employees')}").fetchall()
    actual = {str(row["id"]): normalize(row) for row in accounts}
    require(all(type(row["employee_code"]) is str and row["employee_code"].startswith("SYN-") for row in accounts),
            "Non-synthetic account found in the demo schema")
    memberships = db.execute(f"SELECT employee_id,section_id FROM {qualified(schema, 'employee_sections')}").fetchall()
    for source in history["employees"]:
        account_id = identities[source["id"]]
        account = actual.get(account_id)
        require(account is not None, f"Provisioning required for {source['employee_code']}")
        require(account["employee_code"] == source["employee_code"] and account["role"] == source["role"]
                and account["active"] is True and account["brigade_id"] == source["brigade_id"],
                f"Synthetic account does not match {source['employee_code']}")
        scopes = {str(row["section_id"]) for row in memberships if str(row["employee_id"]) == account_id}
        require(scopes == set(source["section_ids"]), f"Existing scope mismatch for {source['employee_code']}")


def inspect_existing(db, schema, rows):
    missing = {}
    runtime_numbers = {}
    for table, columns in COLUMNS.items():
        # Runtime order numbers belong to the database identity sequence. The
        # separate offline source number is retained in import provenance.
        selected = (*columns, "number") if table == "orders" else columns
        existing = db.execute(f"SELECT {','.join(selected)} FROM {qualified(schema, table)}").fetchall()
        if table == "order_events":
            add_runtime_numbers(rows[table], runtime_numbers)
        wanted = {key_for(table, row): row for row in rows[table]}
        seen = set()
        for record in existing:
            row = normalize(record)
            if table == "orders":
                require(type(row["number"]) is int and row["number"] > 0, "Invalid runtime order number")
                runtime_numbers[row["id"]] = row["number"]
                row = {column: row[column] for column in columns}
            key = key_for(table, row)
            require(key not in seen and key in wanted and row == wanted[key],
                    f"Conflicting or non-synthetic row in {table}; no changes made")
            seen.add(key)
        missing[table] = [row for key, row in wanted.items() if key not in seen]
    for table in EMPTY_TABLES:
        result = db.execute(f"SELECT EXISTS (SELECT 1 FROM {qualified(schema, table)}) AS present").fetchone()
        require(result["present"] is False, f"{table} must be empty; import never rewrites operational/evidence data")
    business = [table for table in COLUMNS if table not in CATALOGUES]
    entirely_absent = all(len(missing[table]) == len(rows[table]) for table in business)
    entirely_present = all(not missing[table] for table in business)
    require(entirely_absent or entirely_present, "Partial historical import found; no automatic repair")
    return missing


def add_runtime_numbers(events, numbers):
    for event in events:
        if event["kind"] == "order.created" and event["order_id"] in numbers:
            event["details"]["synthetic_import"]["runtime_order_number"] = numbers[event["order_id"]]


def insert_rows(db, schema, missing):
    counts = {}
    runtime_numbers = {}
    for table, columns in COLUMNS.items():
        if table == "order_events":
            add_runtime_numbers(missing[table], runtime_numbers)
        placeholders = ["%s::jsonb" if column in JSON_COLUMNS else "%s::uuid[]"
                        if column == "after_photo_ids" else "%s" for column in columns]
        statement = (f"INSERT INTO {qualified(schema, table)} ({','.join(columns)}) "
                     f"VALUES ({','.join(placeholders)})")
        if table == "orders":
            statement += " RETURNING id,number"
        for row in missing[table]:
            values = [json.dumps(row[column], ensure_ascii=False, sort_keys=True, allow_nan=False)
                      if column in JSON_COLUMNS else row[column] for column in columns]
            result = db.execute(statement, values)
            if table == "orders":
                assigned = result.fetchone()
                require(assigned is not None and str(assigned["id"]) == row["id"]
                        and type(assigned["number"]) is int and assigned["number"] > 0,
                        "Expected database-assigned order number")
                runtime_numbers[row["id"]] = assigned["number"]
        counts[table] = len(missing[table])
    return counts


def load_demo(db, history_bytes, mapping, *, demo_only=False, expected_database=None, expected_schema=None):
    """Import atomically using an existing idle psycopg3 dict-row OWNER connection.

    The caller must separately authorize and provision an isolated demo database,
    the accepted migrations and all 17 accounts/scopes. No connection is opened,
    no account is changed, and no live HTTP command is called here.
    """
    require(demo_only is True, "Explicit demo_only=True is required")
    require(type(expected_database) is str and bool(expected_database), "Expected demo database is required")
    require(type(expected_schema) is str and re.fullmatch(r"[a-z][a-z0-9_]{0,62}", expected_schema)
            and not expected_schema.startswith("pg_") and expected_schema != "information_schema",
            "Explicit safe demo schema is required")
    require(db.autocommit is True and db.info.transaction_status == 0, "Connection must be idle with autocommit=True")
    history = read_history(history_bytes)
    rows, identities = prepare_rows(history, mapping)
    with db.transaction():
        # READ COMMITTED obtains a fresh snapshot after the advisory lock wait;
        # subsequent table locks protect the complete preflight from writers.
        db.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        db.execute("SET LOCAL lock_timeout = '5s'")
        db.execute("SET LOCAL statement_timeout = '60s'")
        db.execute("SET LOCAL search_path = pg_catalog")
        db.execute("SELECT pg_catalog.pg_advisory_xact_lock(%s)", (LOCK_KEY,))
        context = db.execute("SELECT pg_catalog.current_database() AS database, current_user AS current_role, session_user AS session_role").fetchone()
        require(context["database"] == expected_database, "Connected database does not match the explicit demo target")
        require(context["current_role"] == context["session_role"], "Supply an OWNER connection, not SET ROLE")
        owners = db.execute("""SELECT c.relname AS name, c.relowner = r.oid AS owned
            FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            JOIN pg_catalog.pg_roles r ON r.rolname=current_user
            WHERE n.nspname=%s AND c.relname=ANY(%s) AND c.relkind='r'""",
            (expected_schema, list(ALL_TABLES))).fetchall()
        require({row["name"] for row in owners} == set(ALL_TABLES) and all(row["owned"] is True for row in owners),
                "Existing schema and table OWNER connection required; apply/provision outside this loader")
        # Prevent unrelated writers from racing preflight. Canonical order makes
        # lock acquisition deterministic; audit triggers are never disabled.
        tables = ",".join(qualified(expected_schema, table) for table in sorted(ALL_TABLES))
        db.execute(f"LOCK TABLE {tables} IN SHARE ROW EXCLUSIVE MODE")
        verify_accounts(db, expected_schema, history, identities)
        missing = inspect_existing(db, expected_schema, rows)
        counts = insert_rows(db, expected_schema, missing)
        # Force the accepted deferred orders->submissions FK before success.
        db.execute("SET CONSTRAINTS ALL IMMEDIATE")
    return {"status": "NOOP" if not sum(counts.values()) else "IMPORTED", "inserted": counts,
            "history_sha256": HISTORY_SHA256, "synthetic": True, "photo_rows_inserted": 0,
            "evidence_level": "synthetic_historical_database_snapshot_not_live_workflow"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("history", type=Path, help="Public canonical C1 history JSON, never a credential file")
    args = parser.parse_args(argv)
    try:
        with args.history.open("rb") as handle:
            history = read_history(handle.read(MAX_HISTORY_BYTES + 1))
    except (OSError, ImportBlocked) as exc:
        parser.exit(2, f"BLOCKED: {exc}\n")
    print(json.dumps({"status": "VALIDATED_OFFLINE", "history_sha256": HISTORY_SHA256,
        "counts": {table: len(items) for table, items in history.items() if isinstance(items, list)},
        "required_existing_accounts": history["employees"], "postgresql": "NOT_RUN",
        "note": "No database connection opened. An authorized isolated OWNER seam is required."},
        ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
