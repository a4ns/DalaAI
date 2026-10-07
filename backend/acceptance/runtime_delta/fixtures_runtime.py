"""Owner setup versus actual nonowner-login application connections.

The runtime role must already exist; A5 owns ephemeral credential provisioning.
This fixture grants only the reviewed profile on its own new synthetic schema.
It never creates roles, accepts SET ROLE as a substitute, or falls back to owner.
"""
import os

from vertical_acceptance.support import ORIGIN, ensure, schema_name

INSERT_TABLES = ("orders", "operation_receipts", "submissions", "material_writeoffs",
                 "reviews", "order_events", "ai_jobs", "delivery_jobs", "auth_sessions", "auth_login_limits")
UPDATE_COLUMNS = {
    "operation_receipts": ("resource_id", "response_status", "response_body", "committed_at"),
    "photos": ("order_id", "submission_id", "attached_at"),
    "auth_sessions": ("id", "revoked_at"), "employees": ("id",),
    "employee_sections": ("employee_id",), "equipment": ("id",),
    "brigades": ("id",), "work_codes": ("id",), "materials": ("id",),
    "auth_login_limits": ("window_started_at", "attempts"),
}


def runtime_connect_factory(schema):
    import psycopg
    from psycopg.rows import dict_row
    schema = schema_name(schema)
    def connect():
        return psycopg.connect(os.environ["DALA_ACCEPTANCE_RUNTIME_DATABASE_URL"], autocommit=True,
            connect_timeout=5, row_factory=dict_row,
            options=f"-c search_path={schema} -c statement_timeout=10000 -c lock_timeout=5000")
    return connect


def identity(connect):
    with connect() as db:
        return db.execute("""SELECT current_database() AS database_name,
            inet_server_addr()::text AS server_address, inet_server_port() AS server_port,
            current_user AS role_name, session_user AS session_role,
            rolsuper,rolcreatedb,rolcreaterole,rolbypassrls
            FROM pg_roles WHERE rolname=current_user""").fetchone()


def grant_existing_runtime_role(owner_connect, runtime_connect, schema):
    from psycopg import sql
    owner, runtime = identity(owner_connect), identity(runtime_connect)
    ensure(all(owner[key] == runtime[key] for key in ("database_name", "server_address", "server_port")),
           "Owner and runtime DSNs must target the same local PostgreSQL database")
    ensure(runtime["role_name"] == runtime["session_role"], "Runtime must authenticate with its own LOGIN, not SET ROLE")
    ensure(runtime["role_name"] != owner["role_name"], "Runtime DSN authenticates as the owner")
    ensure(not any(runtime[key] for key in ("rolsuper", "rolcreatedb", "rolcreaterole", "rolbypassrls")),
           "Runtime LOGIN has elevated PostgreSQL attributes")
    role = sql.Identifier(runtime["role_name"])
    namespace = sql.Identifier(schema_name(schema))
    with owner_connect() as db, db.transaction():
        db.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(namespace, role))
        db.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(namespace, role))
        db.execute(sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}").format(namespace, role))
        for table in INSERT_TABLES:
            db.execute(sql.SQL("GRANT INSERT ON {} TO {}").format(sql.Identifier(schema, table), role))
        for table in ("orders", "delivery_jobs"):
            db.execute(sql.SQL("GRANT UPDATE ON {} TO {}").format(sql.Identifier(schema, table), role))
        for table, columns in UPDATE_COLUMNS.items():
            db.execute(sql.SQL("GRANT UPDATE ({}) ON {} TO {}").format(
                sql.SQL(", ").join(map(sql.Identifier, columns)), sql.Identifier(schema, table), role))
    with runtime_connect() as db:
        state = db.execute("""SELECT has_schema_privilege(current_user,%s,'CREATE') AS can_create,
            (SELECT count(*) FROM pg_tables WHERE schemaname=%s AND tableowner=current_user) AS owned_tables""",
            (schema, schema)).fetchone()
    ensure(not state["can_create"] and state["owned_tables"] == 0, "Runtime has schema CREATE or table ownership")
    return {"role_name": runtime["role_name"], "authenticated_login": True,
            "elevated_attributes": False, "schema_create": False, "owned_tables": 0}


def actual_app_factory(schema, connect, *, owner_probe=False):
    from app.main import create_app
    from app.runtime import RuntimeSettings
    variable = "DALA_TEST_DATABASE_URL" if owner_probe else "DALA_ACCEPTANCE_RUNTIME_DATABASE_URL"
    settings = RuntimeSettings(mode="demo", database_url=os.environ[variable],
                               allowed_origin=ORIGIN, database_schema=schema_name(schema))
    return create_app(settings=settings, connect=connect)
