"""Read-only PostgreSQL corroboration; no fixture/credential file or mutation.

A5 supplies an existing restricted LOGIN and isolated schema through environment.
The output excludes sessions, hashes, DSNs, raw receipt bodies and storage paths.
"""
from datetime import datetime
from decimal import Decimal
import json
import os
import re
import sys
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID


class Blocked(Exception):
    pass


def validate_environment(env):
    if env.get("DALA_C110_AUTHORIZED") != "operator-provisioned-synthetic-only":
        raise Blocked("operator fixture authorization required")
    if any(name.startswith("PG") and value for name, value in env.items()):
        raise Blocked("inherited libpq configuration is forbidden; use the explicit observer URI")
    schema = env.get("DALA_C110_DATABASE_SCHEMA", "")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", schema) or schema == "public":
        raise Blocked("isolated schema required")
    dsn = env.get("DALA_C110_OBSERVER_DATABASE_URL", "")
    parts = urlsplit(dsn)
    if (parts.scheme not in {"postgres", "postgresql"}
            or parts.hostname not in {"127.0.0.1", "localhost", "::1"}
            or not parts.username or parts.password is None
            or not parts.path.strip("/") or parts.fragment):
        raise Blocked("explicit loopback observer URI required; no credential-file fallback")
    # Reject service/passfile/host overrides. Avoid implicit .pgpass reads.
    if any(k not in {"sslmode", "connect_timeout", "application_name"} for k, _ in parse_qsl(parts.query)):
        raise Blocked("observer URI options outside allowlist")
    return dsn, schema


def observe(order_id, env=os.environ):
    order_id = str(UUID(order_id))
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
        if not identity or not all(identity[k] for k in ("direct_login", "read_only", "isolated_schema")) or any(identity[k] for k in ("rolsuper", "rolcreatedb", "rolcreaterole", "rolbypassrls", "schema_create")):
            raise Blocked("restricted observer identity required")
        order = db.execute("""SELECT id,number::text,version,status,type,description,section_id,
            equipment_id,executor_id,created_by,current_submission_id,assignment_revision
            FROM orders WHERE id=%s""", (order_id,)).fetchone()
        events = db.execute("""SELECT id,sequence,order_version,kind,actor_id,operation_id,
            from_status,to_status,submission_id,reason FROM order_events
            WHERE order_id=%s ORDER BY sequence LIMIT 128""", (order_id,)).fetchall()
        submissions = db.execute("""SELECT id,attempt_number,submitted_by,completeness,
            missing_evidence,work_description,work_code_id
            FROM submissions WHERE order_id=%s ORDER BY attempt_number LIMIT 16""", (order_id,)).fetchall()
        reviews = db.execute("""SELECT r.submission_id,r.reviewer_id,r.decision,r.reason,r.final_score
            FROM reviews r JOIN submissions s ON s.id=r.submission_id
            WHERE s.order_id=%s ORDER BY s.attempt_number LIMIT 16""", (order_id,)).fetchall()
        photos = db.execute("""SELECT id,owner_id,purpose,submission_id,assignment_revision,
            attached_at IS NOT NULL AS attached,file_valid,exif_removed,bytes,mime_type,sha256
            FROM photos WHERE order_id=%s ORDER BY id LIMIT 32""", (order_id,)).fetchall()
        receipts = db.execute("""SELECT actor_id,operation_id,response_status,committed_at IS NOT NULL AS committed
            FROM operation_receipts WHERE resource_kind='order' AND resource_id=%s
            ORDER BY created_at,operation_id LIMIT 64""", (order_id,)).fetchall()
        materials = db.execute("""SELECT m.submission_id,m.material_id,m.quantity
            FROM material_writeoffs m JOIN submissions s ON s.id=m.submission_id
            WHERE s.order_id=%s ORDER BY s.attempt_number,m.material_id LIMIT 128""", (order_id,)).fetchall()
        assessments = db.execute("""SELECT a.submission_id,a.mode,a.stale FROM ai_assessments a
            JOIN submissions s ON s.id=a.submission_id WHERE s.order_id=%s LIMIT 32""", (order_id,)).fetchall()
        return {"schema_version": 1, "source": "actual_postgresql_read_only", "identity": identity,
                "order": order, "events": events, "submissions": submissions, "reviews": reviews,
                "photos": photos, "receipts": receipts, "materials": materials, "assessments": assessments}


def encode(value):
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError("unsupported database projection")


def main():
    try:
        if len(sys.argv) != 2:
            raise Blocked("one order UUID required")
        print(json.dumps(observe(sys.argv[1]), default=encode))
        return 0
    except Exception as error:
        # Do not echo driver errors, DSN, SQL, environment values or traceback.
        print(json.dumps({"status": "BLOCKED", "code": "C110_DB_OBSERVATION_UNAVAILABLE",
                          "error_type": type(error).__name__}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
