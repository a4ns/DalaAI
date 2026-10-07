"""Nine targeted session checks with a real restricted login, owner-only fixtures."""
import os
from pathlib import Path
import secrets
import sys
import unittest
from uuid import uuid4

if not os.environ.get('DALA_TEST_DATABASE_URL'):
    raise SystemExit('NOT_RUN: explicit disposable PostgreSQL DSN required')
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'backend'), str(ROOT/'backend/tests')]
import test_sessions_postgres as author

class RestrictedSessions(author.SessionPostgresTests):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from psycopg.conninfo import make_conninfo
        cls.role = 'a5_sessions_' + uuid4().hex
        password = secrets.token_urlsafe(32)
        with cls.pg.connect(cls.dsn, autocommit=True) as db:
            db.execute(cls.sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS').format(cls.sql.Identifier(cls.role), cls.sql.Literal(password)))
        cls.runtime_dsn = make_conninfo(cls.dsn, user=cls.role, password=password)
        cls.addClassCleanup(cls.drop_role)

    @classmethod
    def drop_role(cls):
        with cls.pg.connect(cls.dsn, autocommit=True) as db:
            db.execute(cls.sql.SQL('DROP ROLE {}').format(cls.sql.Identifier(cls.role)))

    def runtime_connect(self):
        return self.pg.connect(self.runtime_dsn, autocommit=True, options=f'-c search_path={self.schema}', row_factory=self.dict_row)

    def new_service(self, **kwargs):
        return author.SessionService(self.runtime_connect, allowed_origin=author.ORIGIN, demo_enabled=True, real_clock=self.clock, verifier=self.verifier, **kwargs)

    def setUp(self):
        super().setUp()
        with self.connect() as db:
            role = self.sql.Identifier(self.role)
            db.execute(self.sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(self.sql.Identifier(self.schema), role))
            for table in ('auth_sessions', 'employees', 'employee_sections', 'auth_login_limits'):
                db.execute(self.sql.SQL('GRANT SELECT ON {} TO {}').format(self.sql.Identifier(table), role))
            for table in ('auth_sessions', 'auth_login_limits'):
                db.execute(self.sql.SQL('GRANT INSERT ON {} TO {}').format(self.sql.Identifier(table), role))
            for table, columns in {'auth_sessions':('id','revoked_at'), 'employees':('id',), 'employee_sections':('employee_id',), 'auth_login_limits':('window_started_at','attempts')}.items():
                db.execute(self.sql.SQL('GRANT UPDATE ({}) ON {} TO {}').format(self.sql.SQL(',').join(map(self.sql.Identifier, columns)), self.sql.Identifier(table), role))
        self.service = self.new_service()

    def test_permissions_and_immutable_ownership(self):
        with self.runtime_connect() as db:
            row = db.execute('SELECT current_user,session_user').fetchone()
            self.assertEqual(row, {'current_user':self.role,'session_user':self.role})
            flags = db.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
            self.assertFalse(any(flags.values()))
            self.assertEqual(db.execute('SELECT count(*) AS n FROM pg_tables WHERE schemaname=%s AND tableowner=current_user',(self.schema,)).fetchone()['n'],0)
            for sql in ('UPDATE employees SET role=role', 'UPDATE employees SET pin_hash=pin_hash', 'UPDATE auth_sessions SET token_hash=token_hash', 'UPDATE auth_sessions SET csrf_token=csrf_token', 'DELETE FROM auth_login_limits', 'ALTER TABLE employees DISABLE TRIGGER ALL'):
                with self.subTest(sql=sql), self.assertRaises(self.pg.errors.InsufficientPrivilege):
                    db.execute(sql)
            with self.assertRaises(self.pg.errors.CheckViolation):
                db.execute('UPDATE employee_sections SET employee_id=%s',(str(uuid4()),))
        self.assertEqual(str(self.query('SELECT employee_id FROM employee_sections')[0]['employee_id']),author.USER)

names = [
 'test_issue_persists_only_hash_and_new_service_recovers',
 'test_real_http_login_me_logout',
 'test_unknown_wrong_inactive_corrupt_all_generic_and_consume',
 'test_no_success_reset_and_restart_preserves_limits',
 'test_csrf_and_origin_rejection_never_revokes',
 'test_rotation_and_revocation_reject_old_handle',
 'test_expiry_active_role_and_membership_live',
 'test_concurrent_logout_no_lock_upgrade_deadlock',
 'test_permissions_and_immutable_ownership',
]
suite = unittest.TestSuite(RestrictedSessions(name) for name in names)
result = unittest.TextTestRunner(verbosity=2).run(suite)
if result.skipped or result.testsRun != 9 or not result.wasSuccessful():
    raise SystemExit('FAIL: all nine restricted-session cases must execute')
print('PASS: nine restricted-session cases, zero skips')
