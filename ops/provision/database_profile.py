"""Same reviewed nonowner permission profile used by actual-runtime acceptance.

No role, credential, migration or account creation. Grants only explicit tables
inside the freshly initialized isolated demo schema to an existing LOGIN.
"""
from provision_synthetic_demo import schema_name


def ensure(condition, message):
    if not condition:
        raise ValueError(message)


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

