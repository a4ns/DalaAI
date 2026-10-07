"""Real PostgreSQL application-role validation; fixtures/migrations stay owner-only.

All inherited command-service cases use an actual non-owner login connection,
not SET ROLE on a superuser session. This is a candidate CI permission profile,
not production account provisioning or a claim of row-level SQL authorization.
"""

import secrets
from uuid import uuid4

import test_persistence_postgres as candidate
from app.persistence.postgres import PostgresRepository
from app.persistence.service import CommandService


class ApplicationRoleTests(candidate.PostgresCommandTests):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from psycopg.conninfo import make_conninfo

        cls.runtime_role = "a5_runtime_" + uuid4().hex
        password = secrets.token_urlsafe(32)
        with cls.pg.connect(cls.dsn, autocommit=True) as db:
            db.execute(cls.sql.SQL(
                "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB "
                "NOCREATEROLE NOINHERIT NOBYPASSRLS"
            ).format(cls.sql.Identifier(cls.runtime_role), cls.sql.Literal(password)))
        cls.runtime_dsn = make_conninfo(cls.dsn, user=cls.runtime_role, password=password)
        cls.addClassCleanup(cls.drop_runtime_role)

    @classmethod
    def drop_runtime_role(cls):
        with cls.pg.connect(cls.dsn, autocommit=True) as db:
            db.execute(cls.sql.SQL("DROP ROLE {}").format(cls.sql.Identifier(cls.runtime_role)))

    def setUp(self):
        super().setUp()
        role = self.sql.Identifier(self.runtime_role)
        schema = self.sql.Identifier(self.schema)
        with self.connect() as db:
            db.execute(self.sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(schema, role))
            db.execute(self.sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(schema, role))
            db.execute(self.sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}").format(schema, role))
            for table in ("orders", "operation_receipts", "submissions", "material_writeoffs",
                          "reviews", "order_events", "ai_jobs", "delivery_jobs"):
                db.execute(self.sql.SQL("GRANT INSERT ON {} TO {}").format(self.sql.Identifier(table), role))
            for table in ("orders", "delivery_jobs"):
                db.execute(self.sql.SQL("GRANT UPDATE ON {} TO {}").format(self.sql.Identifier(table), role))
            grants = {
                "operation_receipts": ("resource_id", "response_status", "response_body", "committed_at"),
                "photos": ("order_id", "submission_id", "attached_at"),
                # PostgreSQL FOR SHARE/UPDATE needs UPDATE on at least one column.
                # This profile deliberately excludes role, active, token and validation fields.
                "auth_sessions": ("id",), "employees": ("id",),
                "employee_sections": ("employee_id",), "equipment": ("id",),
                "brigades": ("id",), "work_codes": ("id",), "materials": ("id",),
            }
            for table, columns in grants.items():
                db.execute(self.sql.SQL("GRANT UPDATE ({}) ON {} TO {}").format(
                    self.sql.SQL(", ").join(map(self.sql.Identifier, columns)),
                    self.sql.Identifier(table), role,
                ))
        self.service = CommandService(self.runtime_connect, allowed_origin=candidate.ORIGIN,
                                      delivery_channel="synthetic", domain_clock=self.domain,
                                      real_clock=self.real)

    def runtime_connect(self):
        return self.pg.connect(self.runtime_dsn, autocommit=True,
                               options=f"-c search_path={self.schema}", row_factory=self.dict_row)

    def runtime_query(self, statement, params=()):
        with self.runtime_connect() as db:
            return db.execute(statement, params).fetchall()

    def test_runtime_login_is_nonowner_and_nonprivileged(self):
        row = self.runtime_query("SELECT current_user, session_user")[0]
        self.assertEqual(row["current_user"], self.runtime_role)
        self.assertEqual(row["session_user"], self.runtime_role)
        flags = self.runtime_query(
            "SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=current_user"
        )[0]
        self.assertFalse(any(flags.values()))
        self.assertEqual(self.runtime_query(
            "SELECT count(*) AS count FROM pg_tables WHERE schemaname=%s AND tableowner=current_user",
            (self.schema,),
        )[0]["count"], 0)

    def test_runtime_cannot_disable_guards_or_take_ownership(self):
        statements = (
            "ALTER TABLE orders DISABLE TRIGGER ALL",
            "DROP TABLE orders CASCADE",
            "CREATE TABLE unauthorized_table(id integer)",
            "SET session_replication_role = replica",
            "SET ROLE postgres",
        )
        for statement in statements:
            with self.subTest(statement=statement), self.assertRaises(self.pg.errors.InsufficientPrivilege):
                self.runtime_query(statement)

    def test_runtime_cannot_write_auth_or_file_validation_fields(self):
        statements = (
            "UPDATE employees SET role='admin'",
            "UPDATE employees SET active=false",
            "UPDATE auth_sessions SET token_hash='unauthorized'",
            "UPDATE auth_sessions SET csrf_token='unauthorized'",
            "UPDATE photos SET file_valid=true",
        )
        for statement in statements:
            with self.subTest(statement=statement), self.assertRaises(self.pg.errors.InsufficientPrivilege):
                self.runtime_query(statement)

    def test_runtime_cannot_truncate_delete_or_rewrite_committed_audit(self):
        self.create()
        for statement in ("TRUNCATE order_events", "DELETE FROM order_events",
                          "UPDATE order_events SET sequence=sequence"):
            with self.subTest(statement=statement), self.assertRaises(self.pg.errors.InsufficientPrivilege):
                self.runtime_query(statement)
        with self.assertRaises(self.pg.Error):
            self.runtime_query("UPDATE operation_receipts SET response_status=200")
        self.assertEqual(len(self.query("SELECT * FROM order_events")), 1)

    def test_runtime_unfinalized_receipt_cannot_commit(self):
        with self.assertRaises(self.pg.Error), self.runtime_connect() as db:
            with db.transaction():
                PostgresRepository(db).reserve(candidate.MASTER, str(uuid4()), "a" * 64, candidate.NOW)
        self.assertEqual(self.query("SELECT * FROM operation_receipts"), [])
