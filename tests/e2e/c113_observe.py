"""C113 safe PostgreSQL projection. A5 alone executes against its isolated DB.

No credential files, pin_hash, auth_sessions, storage bytes or raw driver output
are read. Business rows are hashed, never emitted wholesale. This is not a seed.
"""
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
import re
import sys
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

TABLES = ("orders", "order_events", "submissions", "reviews", "photos",
          "material_writeoffs", "ai_assessments", "operation_receipts")


class Blocked(Exception):
    pass


def validate_environment(env):
    if env.get("DALA_C113_AUTHORIZED") != "operator-provisioned-synthetic-only":
        raise Blocked()
    if any(k.startswith("PG") and v for k, v in env.items()):
        raise Blocked()
    schema = env.get("DALA_C113_DATABASE_SCHEMA", "")
    if (not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", schema)
            or schema in {"public", "information_schema"} or schema.startswith("pg_")):
        raise Blocked()
    dsn = env.get("DALA_C113_OBSERVER_DATABASE_URL", "")
    p = urlsplit(dsn)
    if (p.scheme not in {"postgres", "postgresql"}
            or p.hostname not in {"127.0.0.1", "localhost", "::1"}
            or not p.username or p.password is None or not p.path.strip("/") or p.fragment):
        raise Blocked()
    options = parse_qsl(p.query, keep_blank_values=True)
    if (len({k for k, _ in options}) != len(options)
            or any(k not in {"sslmode", "connect_timeout", "application_name"} for k, _ in options)):
        raise Blocked()
    return dsn, schema


def observe(master, executor, env=os.environ):
    master, executor = str(UUID(master)), str(UUID(executor))
    if master == executor:
        raise Blocked()
    dsn, schema = validate_environment(env)
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5, passfile="/dev/null",
                          options=f"-c search_path={schema} -c statement_timeout=5000 -c lock_timeout=2000",
                          row_factory=dict_row) as db, db.transaction():
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        identity = db.execute("""SELECT current_user=session_user AS direct_login,
            current_setting('transaction_read_only')='on' AS read_only,
            current_schema()=%s AS isolated_schema,
            has_schema_privilege(current_schema(),'CREATE') AS schema_create,
            rolsuper,rolcreatedb,rolcreaterole,rolbypassrls
            FROM pg_roles WHERE rolname=current_user""", (schema,)).fetchone()
        if (not identity or not all(identity[k] for k in ("direct_login", "read_only", "isolated_schema"))
                or any(identity[k] for k in ("schema_create", "rolsuper", "rolcreatedb", "rolcreaterole", "rolbypassrls"))):
            raise Blocked()
        # Accepted C110 architecture: existing restricted runtime LOGIN with an
        # enforced READ ONLY transaction. This does not claim a SELECT-only role.
        # Historical identities are disabled; no password/hash column is queried.
        employees = db.execute("""SELECT e.id::text,e.employee_code,e.role,e.active,e.on_shift,
            COALESCE(array_agg(s.section_id::text ORDER BY s.section_id) FILTER (WHERE s.section_id IS NOT NULL),ARRAY[]::text[]) AS section_ids
            FROM employees e LEFT JOIN employee_sections s ON s.employee_id=e.id
            GROUP BY e.id ORDER BY e.id""").fetchall()
        historical = [e for e in employees if e["id"] not in {master, executor}]
        if len(employees) != 19 or len(historical) != 17 or any(e["active"] or e["on_shift"] for e in historical):
            raise Blocked()
        counts, business_hash = {}, sha256()
        for table in TABLES:
            # Names are a fixed source allowlist; all returned bytes remain private.
            rows = db.execute(f"SELECT to_jsonb(t)::text AS row FROM {table} t ORDER BY to_jsonb(t)::text LIMIT 20001").fetchall()
            if len(rows) > 20000:
                raise Blocked()
            counts[table] = len(rows)
            business_hash.update(table.encode() + b"\0")
            for row in rows:
                business_hash.update(row["row"].encode() + b"\n")
        orders = db.execute("SELECT id::text,section_id::text FROM orders ORDER BY id").fetchall()
        submission_ids = [r["id"] for r in db.execute("SELECT id::text FROM submissions ORDER BY id").fetchall()]
        # Immutable creation provenance is emitted only as distinct public hashes/counts.
        provenance = db.execute("""SELECT details FROM order_events WHERE kind='order.created' ORDER BY order_id""").fetchall()
        if len(provenance) != 540:
            raise Blocked()
        markers = [r["details"].get("synthetic_import", {}) for r in provenance]
        if any(m.get("synthetic") is not True or m.get("history_sha256") != "7d888cdd5bb6a9c01ca7c543fae9e393335d07210dab811aa754f12331d1d2e1"
               or m.get("source_commit") != "8af3897f03aa2f41f0af07ec74ec2c807a4a535a" or m.get("loader_version") != "1.1.0"
               or m.get("historical_actor_state") != "disabled_no_login" or m.get("historical_completeness_not_verified_evidence") is not True
               or m.get("photo_policy") != "metadata_only_no_image_bytes_no_file_valid_claim" for m in markers):
            raise Blocked()
        mappings = {m.get("identity_mapping_sha256") for m in markers}
        if len(mappings) != 1 or not re.fullmatch(r"[0-9a-f]{64}", next(iter(mappings)) or ""):
            raise Blocked()
        photos = db.execute("SELECT COALESCE(sum(cardinality(after_photo_ids)),0) AS references FROM submissions").fetchone()
        return {"schema_version": 1, "source": "actual_postgresql_read_only", "identity": identity,
                "observer_mode": "existing_restricted_runtime_login_read_only_transaction",
                "observed_at": datetime.now(timezone.utc).isoformat(), "counts": counts,
                "business_sha256": business_hash.hexdigest(), "live_users": [e for e in employees if e["id"] in {master, executor}],
                "history_sha256": markers[0]["history_sha256"], "identity_mapping_sha256": next(iter(mappings)),
                "after_photo_references": int(photos["references"]), "historical_actor_count": len(historical), "historical_actors_disabled": True,
                "order_ids": [r["id"] for r in orders], "section_ids": sorted({r["section_id"] for r in orders}),
                "submission_ids": submission_ids}


def main():
    try:
        if len(sys.argv) != 3:
            raise Blocked()
        print(json.dumps(observe(sys.argv[1], sys.argv[2]), sort_keys=True))
        return 0
    except Exception:
        print('{"status":"BLOCKED","code":"C113_DB_OBSERVATION_UNAVAILABLE"}')
        return 2


if __name__ == "__main__":
    sys.exit(main())
