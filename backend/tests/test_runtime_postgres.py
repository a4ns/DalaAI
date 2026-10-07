"""Actual app.main startup/readiness, restricted PostgreSQL and photo fail-closed."""
from pathlib import Path
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient
from app.main import create_app
from app.runtime import RuntimeSettings, RuntimePrerequisiteError
from app.core.auth_boundary import SESSION_COOKIE_NAME
import test_persistence_postgres as data
import test_persistence_role as role_fixture

class MountedRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        role_fixture.ApplicationRoleTests.setUpClass()
        cls.addClassCleanup(role_fixture.ApplicationRoleTests.doClassCleanups)

    def setUp(self):
        self.fixture = role_fixture.ApplicationRoleTests('test_runtime_login_is_nonowner_and_nonprivileged')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        f = self.fixture
        with f.connect() as db:
            db.execute((Path(__file__).resolve().parents[1]/'db/proposals/003_auth_rate_limits.sql').read_text())
            role = f.sql.Identifier(f.runtime_role)
            db.execute(f.sql.SQL('GRANT SELECT, INSERT ON auth_login_limits TO {}').format(role))
            db.execute(f.sql.SQL('GRANT UPDATE (window_started_at,attempts) ON auth_login_limits TO {}').format(role))
            db.execute(f.sql.SQL('GRANT INSERT, UPDATE (revoked_at) ON auth_sessions TO {}').format(role))
        self.settings = RuntimeSettings('demo','synthetic-not-used',data.ORIGIN,f.schema)

    def app(self, connect=None):
        return create_app(settings=self.settings,connect=connect or self.fixture.runtime_connect)

    def owner_exec(self, statement):
        with self.fixture.connect() as db:
            db.execute(statement)

    def rejection(self, code, connect=None):
        with self.assertRaises(RuntimePrerequisiteError) as caught:
            with TestClient(self.app(connect),base_url=data.ORIGIN):
                self.fail('Unsafe runtime started')
        self.assertEqual(caught.exception.code,code)

    def test_actual_factory_starts_ready_and_mounts_authenticated_routes(self):
        with TestClient(self.app(),base_url=data.ORIGIN) as client:
            self.assertEqual(client.get('/healthz').status_code,200)
            self.assertEqual(client.get('/readyz').status_code,200)
            for path in ('/api/v1/me','/api/v1/orders','/api/v1/dicts'):
                self.assertEqual(client.get(path).status_code,401)
            self.assertEqual(client.get('/api/v1/me',headers={'Host':'foreign.test'}).status_code,400)
            client.cookies.set(SESSION_COOKIE_NAME,data.MASTER)
            self.assertEqual(client.get('/api/v1/me').json()['principal']['user_id'],data.MASTER)

    def test_schema_owner_is_rejected(self):
        self.rejection('ROLE_NOT_RESTRICTED',self.fixture.connect)

    def test_missing_rate_migration_is_rejected(self):
        self.owner_exec('DROP TABLE auth_login_limits')
        self.rejection('DATABASE_UNAVAILABLE_OR_SCHEMA_MISSING')

    def test_disabled_identity_guard_is_rejected(self):
        self.owner_exec('ALTER TABLE employee_sections DISABLE TRIGGER employee_sections_ownership_immutable')
        self.rejection('REQUIRED_GUARD_MISSING')

    def test_sensitive_grant_is_rejected(self):
        f=self.fixture
        with f.connect() as db:
            db.execute(f.sql.SQL('GRANT UPDATE (pin_hash) ON employees TO {}').format(f.sql.Identifier(f.runtime_role)))
        self.rejection('FORBIDDEN_GRANT')

    def test_destructive_table_grants_are_rejected(self):
        f=self.fixture
        for privilege in ('DELETE','TRUNCATE','TRIGGER'):
            with self.subTest(privilege=privilege), f.connect() as db:
                db.execute(f.sql.SQL('GRANT {} ON order_events TO {}').format(f.sql.SQL(privilege),f.sql.Identifier(f.runtime_role)))
                self.rejection('FORBIDDEN_GRANT')
                db.execute(f.sql.SQL('REVOKE {} ON order_events FROM {}').format(f.sql.SQL(privilege),f.sql.Identifier(f.runtime_role)))

    def test_extra_auth_column_grant_is_rejected(self):
        f=self.fixture
        with f.connect() as db:
            db.execute(f.sql.SQL('GRANT UPDATE (employee_code) ON employees TO {}').format(f.sql.Identifier(f.runtime_role)))
        self.rejection('FORBIDDEN_GRANT')

    def test_extra_reference_insert_is_rejected(self):
        f=self.fixture
        with f.connect() as db:
            db.execute(f.sql.SQL('GRANT INSERT ON employees TO {}').format(f.sql.Identifier(f.runtime_role)))
        self.rejection('FORBIDDEN_GRANT')

    def test_missing_session_revoke_grant_is_rejected(self):
        f=self.fixture
        with f.connect() as db:
            db.execute(f.sql.SQL('REVOKE UPDATE (revoked_at) ON auth_sessions FROM {}').format(f.sql.Identifier(f.runtime_role)))
        self.rejection('REQUIRED_GRANT_MISSING')

    def test_readiness_detects_lost_guard_while_liveness_stays_up(self):
        with TestClient(self.app(),base_url=data.ORIGIN) as client:
            self.assertEqual(client.get('/readyz').status_code,200)
            self.owner_exec('ALTER TABLE employees DISABLE TRIGGER employees_identity_immutable')
            response=client.get('/readyz')
            self.assertEqual(response.status_code,503)
            self.assertEqual(response.json(),{'status':'not_ready'})
            self.assertEqual(client.get('/healthz').status_code,200)
            self.assertEqual(client.get('/api/v1/orders').status_code,503)
            self.owner_exec('ALTER TABLE employees ENABLE TRIGGER employees_identity_immutable')
            self.assertEqual(client.get('/readyz').status_code,503)
            self.assertEqual(client.get('/api/v1/me').status_code,503)
        # Only a fresh successfully validated application instance recovers.
        with TestClient(self.app(),base_url=data.ORIGIN) as recovered:
            self.assertEqual(recovered.get('/readyz').status_code,200)

    def test_true_database_photo_flag_cannot_close_without_blob_verifier(self):
        f=self.fixture
        order=f.start()
        photo=f.stage(owner=data.EXECUTOR,purpose='after',order_id=order,revision=1)
        submitted,_=f.submit(order,[photo])
        command={'operation_id':str(uuid4()),'expected_version':4,'action':'review',
                 'payload':{'submission_id':submitted.body['submission_id'],'decision':'close',
                            'reason':'Synthetic review','final_score':None}}
        before=len(f.query('SELECT * FROM operation_receipts'))
        with TestClient(self.app(),base_url=data.ORIGIN) as client:
            client.cookies.set(SESSION_COOKIE_NAME,data.MASTER)
            response=client.post(f'/api/v1/orders/{order}/commands',json=command,
                                headers={'Origin':data.ORIGIN,'X-CSRF-Token':'synthetic-csrf'})
            self.assertEqual(response.status_code,409)
            self.assertEqual(response.json()['code'],'INCOMPLETE_SUBMISSION')
        self.assertEqual(f.query('SELECT file_valid FROM photos')[0]['file_valid'],True)
        self.assertEqual(f.query('SELECT status,version FROM orders')[0],{'status':'ai_review','version':4})
        self.assertEqual(f.query('SELECT * FROM reviews'),[])
        self.assertEqual(len(f.query('SELECT * FROM operation_receipts')),before)
