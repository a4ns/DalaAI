"""Real PostgreSQL application-role validation; fixtures/migrations stay owner-only.

All inherited command-service cases use an actual non-owner login connection,
not SET ROLE on a superuser session. This is a candidate CI permission profile,
not production account provisioning or a claim of row-level SQL authorization.
"""

import secrets
from uuid import uuid4

import test_persistence_postgres as candidate
from app.persistence.postgres import PostgresRepository, PostgresPrincipals
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


    def test_runtime_cannot_transfer_section_membership(self):
        self.query("INSERT INTO employee_sections VALUES (%s,%s) RETURNING employee_id",
                   (candidate.EXECUTOR, candidate.SECOND_SECTION))
        command = candidate.create_command()
        command["operation_id"] = str(uuid4())
        command["payload"]["section_id"] = candidate.SECOND_SECTION
        command["payload"]["equipment_id"] = candidate.SECOND_EQUIPMENT
        created = self.run_command(command)
        self.query("DELETE FROM employee_sections WHERE employee_id=%s AND section_id=%s RETURNING employee_id",
                   (candidate.EXECUTOR, candidate.SECOND_SECTION))
        with self.assertRaises(self.pg.errors.CheckViolation):
            self.runtime_query("UPDATE employee_sections SET employee_id=%s WHERE employee_id=%s AND section_id=%s RETURNING employee_id",
                               (candidate.EXECUTOR, candidate.MASTER, candidate.SECOND_SECTION))
        rows = self.query("SELECT employee_id FROM employee_sections WHERE section_id=%s", (candidate.SECOND_SECTION,))
        self.assertEqual([str(row["employee_id"]) for row in rows], [candidate.MASTER])
        with self.runtime_connect() as db:
            principal = PostgresPrincipals(db).lookup(candidate.EXECUTOR)
            self.assertNotIn(candidate.SECOND_SECTION, principal.section_ids)
        with self.assertRaises(candidate.AccessDenied):
            self.service.get_order(created.body["order"]["id"], session_handle=candidate.EXECUTOR)

    def test_runtime_cannot_rewrite_lock_key_identifiers(self):
        unused_employee, brigade = str(uuid4()), str(uuid4())
        with self.connect() as db:
            db.execute("INSERT INTO employees(id,employee_code,role,pin_hash) VALUES (%s,%s,'executor','synthetic')",
                       (unused_employee, "unused-" + uuid4().hex))
            db.execute("INSERT INTO brigades(id,section_id,code,label) VALUES (%s,%s,%s,'Synthetic')",
                       (brigade, candidate.SECTION, "brigade-" + uuid4().hex))
        session = self.query("SELECT id FROM auth_sessions WHERE employee_id=%s", (candidate.MASTER,))[0]["id"]
        keys = (("auth_sessions", session), ("employees", unused_employee),
                ("equipment", candidate.EQUIPMENT), ("brigades", brigade),
                ("work_codes", candidate.CODE), ("materials", candidate.MATERIAL))
        for table, current_id in keys:
            with self.subTest(table=table), self.assertRaises(self.pg.errors.CheckViolation):
                statement = self.sql.SQL("UPDATE {} SET id=%s WHERE id=%s RETURNING id").format(self.sql.Identifier(table))
                self.runtime_query(statement, (str(uuid4()), current_id))

    def test_owner_cannot_reassign_immutable_ownership(self):
        with self.assertRaises(self.pg.errors.CheckViolation):
            self.query("UPDATE employee_sections SET section_id=%s WHERE employee_id=%s AND section_id=%s RETURNING employee_id",
                       (candidate.SECOND_SECTION, candidate.OTHER, candidate.SECTION))
        with self.assertRaises(self.pg.errors.CheckViolation):
            self.query("UPDATE auth_sessions SET employee_id=%s WHERE employee_id=%s RETURNING id",
                       (candidate.OTHER, candidate.MASTER))

    def test_reference_noops_and_session_revocation_still_work(self):
        self.assertTrue(self.runtime_query("UPDATE employees SET id=id WHERE id=%s RETURNING id", (candidate.MASTER,)))
        self.assertTrue(self.runtime_query("UPDATE auth_sessions SET id=id WHERE employee_id=%s RETURNING id", (candidate.MASTER,)))
        self.assertTrue(self.runtime_query("UPDATE employee_sections SET employee_id=employee_id WHERE employee_id=%s RETURNING employee_id", (candidate.MASTER,)))
        created, _ = self.create()
        self.query("UPDATE auth_sessions SET revoked_at=%s WHERE employee_id=%s RETURNING id", (candidate.NOW, candidate.MASTER))
        with self.assertRaises(candidate.AuthenticationRequired):
            self.service.get_order(created.body["order"]["id"], session_handle=candidate.MASTER)
