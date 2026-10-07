"""REAL PostgreSQL+real Argon2id tests. Requires disposable explicit test DB.

Every test has a separate random a2_sessions_* schema and synthetic accounts.
No SQLite/fake transactions. DSN absence is NOT_RUN, configured failure is ERROR.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
import time
from pathlib import Path
from threading import Barrier, Event
import unittest
from uuid import uuid4
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.auth_boundary import AuthenticationRequired, SESSION_COOKIE_NAME
from app.core.auth_policy import AccessDenied
from app.sessions.crypto import Argon2idVerifier
from app.sessions.http import create_router
from app.sessions.limiter import LimitPolicy, PostgresAttemptLimiter
from app.sessions.service import RateLimited, SessionService

NOW = datetime(2026,10,7,18,tzinfo=timezone.utc)
ORIGIN = "https://naryadai.test"
ROOT = Path(__file__).resolve().parents[1]
USER = "00000000-0000-0000-0000-000000000001"
SECTION = "00000000-0000-0000-0000-000000000002"
PIN = "synthetic-pin-1234"


class Clock:
    def __init__(self):
        self.value = NOW
    def now(self):
        return self.value


class SessionPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.environ.get("DALA_TEST_DATABASE_URL")
        if not cls.dsn:
            raise unittest.SkipTest("NOT_RUN: DALA_TEST_DATABASE_URL absent; real PostgreSQL required")
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row
        cls.pg, cls.sql, cls.dict_row = psycopg, sql, staticmethod(dict_row)
        cls.verifier = Argon2idVerifier()
        cls.pin_hash = cls.verifier.hasher.hash(PIN)

    def setUp(self):
        self.schema = "a2_sessions_" + uuid4().hex
        with self.pg.connect(self.dsn,autocommit=True) as db:
            db.execute(self.sql.SQL("CREATE SCHEMA {}").format(self.sql.Identifier(self.schema)))
        self.addCleanup(self.drop_schema)
        with self.connect() as db:
            for migration in sorted((ROOT / "db/migrations").glob("*.sql")):
                db.execute(migration.read_text())
            db.execute((ROOT / "db/proposals/003_auth_rate_limits.sql").read_text())
            db.execute("INSERT INTO sections VALUES (%s,'SYNTHETIC','Synthetic section')", (SECTION,))
            db.execute("""INSERT INTO employees(id,employee_code,role,on_shift,pin_hash)
                       VALUES (%s,'SYNTHETIC','executor',true,%s)""", (USER,self.pin_hash))
            db.execute("INSERT INTO employee_sections VALUES (%s,%s)", (USER,SECTION))
        self.clock = Clock()
        self.service = self.new_service()

    def connect(self):
        return self.pg.connect(self.dsn,autocommit=True,options=f"-c search_path={self.schema}",row_factory=self.dict_row)

    def drop_schema(self):
        with self.pg.connect(self.dsn,autocommit=True) as db:
            db.execute(self.sql.SQL("DROP SCHEMA {} CASCADE").format(self.sql.Identifier(self.schema)))

    def query(self, sql, params=()):
        with self.connect() as db:
            result = db.execute(sql,params)
            return result.fetchall() if result.description else []

    def new_service(self, **kwargs):
        return SessionService(self.connect,allowed_origin=ORIGIN,demo_enabled=True,
                              real_clock=self.clock,verifier=self.verifier,**kwargs)

    def login(self, *, code="SYNTHETIC", pin=PIN, source="127.0.0.1", service=None, previous=None):
        return (service or self.service).login(json.dumps({"employee_code":code,"pin":pin}),
                   origin=ORIGIN, source_key=source, previous_handle=previous)

    def client(self, service=None):
        app = FastAPI()
        app.include_router(create_router(service or self.service))
        return TestClient(app,base_url=ORIGIN,client=("127.0.0.1",50000))

    def test_issue_persists_only_hash_and_new_service_recovers(self):
        issued = self.login()
        rows = self.query("SELECT * FROM auth_sessions")
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["token_hash"],sha256(issued.session_handle.encode()).hexdigest())
        self.assertNotEqual(rows[0]["csrf_token"],issued.session_handle)
        self.assertNotIn(issued.session_handle,str(rows))
        reconstructed = self.new_service().me(session_handle=issued.session_handle)
        self.assertEqual(issued.body,reconstructed)
        self.assertEqual(reconstructed["principal"]["section_ids"],[SECTION])

    def test_real_http_login_me_logout(self):
        client = self.client()
        response = client.post("/api/v1/auth/login",json={"employee_code":"SYNTHETIC","pin":PIN},headers={"Origin":ORIGIN})
        self.assertEqual(response.status_code,200)
        csrf = response.json()["csrf_token"]
        self.assertEqual(client.get("/api/v1/me").status_code,200)
        self.assertEqual(client.post("/api/v1/auth/logout",headers={"Origin":ORIGIN,"X-CSRF-Token":csrf}).status_code,204)
        self.assertEqual(client.get("/api/v1/me").status_code,401)
        self.assertIsNotNone(self.query("SELECT revoked_at FROM auth_sessions")[0]["revoked_at"])

    def test_unknown_wrong_inactive_corrupt_all_generic_and_consume(self):
        for code,pin in (("MISSING",PIN),("SYNTHETIC","wrong-synthetic")):
            with self.assertRaises(AuthenticationRequired):
                self.login(code=code,pin=pin)
        self.query("UPDATE employees SET active=false")
        with self.assertRaises(AuthenticationRequired):
            self.login()
        self.query("UPDATE employees SET active=true,pin_hash='malformed'")
        with self.assertRaises(AuthenticationRequired):
            self.login()
        self.assertEqual(self.query("SELECT count(*) AS n FROM auth_sessions")[0]["n"],0)
        self.assertEqual(self.query("SELECT sum(attempts) AS n FROM auth_login_limits WHERE kind='source'")[0]["n"],4)

    def test_no_success_reset_and_restart_preserves_limits(self):
        for unused in range(5):
            self.login(service=self.new_service())
        with self.assertRaises(RateLimited) as error:
            self.login(service=self.new_service())
        self.assertEqual(error.exception.retry_after_seconds,300)
        self.clock.value += timedelta(seconds=299)
        with self.assertRaises(RateLimited) as error:
            self.login()
        self.assertEqual(error.exception.retry_after_seconds,1)
        self.clock.value += timedelta(seconds=1)
        self.login()

    def test_source_limit_across_accounts_and_account_limit_across_sources(self):
        limiter = PostgresAttemptLimiter(self.connect,real_clock=self.clock,
                     policy=LimitPolicy(account_attempts=2,source_attempts=3,window_seconds=60))
        self.assertTrue(limiter.consume(account_key="A",source_key="S1").allowed)
        self.assertTrue(limiter.consume(account_key="A",source_key="S2").allowed)
        self.assertFalse(limiter.consume(account_key="A",source_key="S3").allowed)
        self.assertTrue(limiter.consume(account_key="B",source_key="S1").allowed)
        self.assertTrue(limiter.consume(account_key="C",source_key="S1").allowed)
        self.assertFalse(limiter.consume(account_key="D",source_key="S1").allowed)

    def test_concurrent_attempts_serialize_exactly(self):
        barrier = Barrier(12)
        def consume(index):
            limiter = PostgresAttemptLimiter(self.connect,real_clock=self.clock)
            barrier.wait()
            return limiter.consume(account_key="same",source_key=f"source-{index}").allowed
        with ThreadPoolExecutor(max_workers=12) as pool:
            allowed = list(pool.map(consume,range(12)))
        self.assertEqual(sum(allowed),5)

    def test_limiter_storage_failure_prevents_hash_and_issue(self):
        verifier = Mock(wraps=self.verifier)
        service = SessionService(self.connect,allowed_origin=ORIGIN,demo_enabled=True,real_clock=self.clock,verifier=verifier)
        self.query("DROP TABLE auth_login_limits")
        with self.assertRaises(self.pg.Error):
            self.login(service=service)
        verifier.verify.assert_not_called()
        self.assertEqual(self.query("SELECT count(*) AS n FROM auth_sessions")[0]["n"],0)

    def test_csrf_and_origin_rejection_never_revokes(self):
        issued = self.login()
        for origin,csrf in (("https://evil.test",issued.body["csrf_token"]),(ORIGIN,"wrong"),(ORIGIN,"é")):
            with self.assertRaises(AccessDenied):
                self.service.logout(session_handle=issued.session_handle,origin=origin,csrf_token=csrf)
        self.assertEqual(self.service.me(session_handle=issued.session_handle),issued.body)

    def test_rotation_and_revocation_reject_old_handle(self):
        first = self.login()
        second = self.login(previous=first.session_handle)
        self.assertNotEqual(first.session_handle,second.session_handle)
        self.assertNotEqual(first.body["csrf_token"],second.body["csrf_token"])
        with self.assertRaises(AuthenticationRequired):
            self.service.me(session_handle=first.session_handle)
        self.assertEqual(self.service.me(session_handle=second.session_handle),second.body)

    def test_expiry_active_role_and_membership_live(self):
        issued = self.login()
        self.query("UPDATE employees SET role='manager',on_shift=false")
        self.query("DELETE FROM employee_sections")
        p = self.service.me(session_handle=issued.session_handle)["principal"]
        self.assertEqual(p["role"],"manager")
        self.assertFalse(p["on_shift"])
        self.assertEqual(p["section_ids"],[])
        self.query("UPDATE employees SET active=false")
        with self.assertRaises(AuthenticationRequired):
            self.service.me(session_handle=issued.session_handle)
        self.query("UPDATE employees SET active=true")
        self.clock.value += timedelta(hours=8)
        with self.assertRaises(AuthenticationRequired):
            self.service.me(session_handle=issued.session_handle)

    def test_hash_changed_during_verification_blocks_issue(self):
        def verify_then_change(pin, encoded):
            result = self.verifier.verify(pin,encoded)
            self.query("UPDATE employees SET pin_hash='changed-synthetic-hash'")
            return result
        service = SessionService(self.connect,allowed_origin=ORIGIN,demo_enabled=True,real_clock=self.clock,
                                 verifier=Mock(verify=verify_then_change))
        with self.assertRaises(AuthenticationRequired):
            self.login(service=service)
        self.assertEqual(self.query("SELECT count(*) AS n FROM auth_sessions")[0]["n"],0)

    def test_inactivation_during_verification_blocks_issue(self):
        def verify_then_disable(pin, encoded):
            result = self.verifier.verify(pin,encoded)
            self.query("UPDATE employees SET active=false")
            return result
        service = SessionService(self.connect,allowed_origin=ORIGIN,demo_enabled=True,real_clock=self.clock,
                                 verifier=Mock(verify=verify_then_disable))
        with self.assertRaises(AuthenticationRequired):
            self.login(service=service)

    def test_concurrent_logout_no_lock_upgrade_deadlock(self):
        issued = self.login()
        barrier = Barrier(2)
        def logout():
            barrier.wait()
            try:
                self.new_service().logout(session_handle=issued.session_handle,origin=ORIGIN,
                                          csrf_token=issued.body["csrf_token"])
                return "revoked"
            except AuthenticationRequired:
                return "unauthenticated"
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(logout) for unused in range(2)]
            results = [f.result(timeout=10) for f in futures]
        self.assertCountEqual(results,["revoked","unauthenticated"])

    def test_expiration_after_blocking_employee_lock(self):
        issued = self.login()
        entered = Event()
        original = self.connect
        waiting_pid = []
        def signalled_connect():
            db = original()
            waiting_pid.append(db.info.backend_pid)
            entered.set()
            return db
        service = SessionService(signalled_connect,allowed_origin=ORIGIN,demo_enabled=True,
                                 real_clock=self.clock,verifier=self.verifier)
        with self.connect() as blocker:
            with ThreadPoolExecutor(max_workers=1) as pool:
                with blocker.transaction():
                    blocker.execute("SELECT id FROM employees WHERE id=%s FOR UPDATE",(USER,))
                    future = pool.submit(service.me,session_handle=issued.session_handle)
                    self.assertTrue(entered.wait(5))
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        state = self.query("SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s", (waiting_pid[0],))
                        if state and state[0]["wait_event_type"] == "Lock":
                            break
                        time.sleep(0.02)
                    else:
                        self.fail("Reader never reached the intended database lock wait")
                    self.clock.value += timedelta(hours=9)
                with self.assertRaises(AuthenticationRequired):
                    future.result(timeout=10)

    def test_database_bucket_constraints_bound_state(self):
        for kind,key in (("anything",0),("account",65536),("source",-1)):
            with self.assertRaises(self.pg.errors.CheckViolation):
                self.query("INSERT INTO auth_login_limits VALUES (%s,%s,%s,0)",(kind,key,NOW))

    def test_clock_rewind_never_resets_limits(self):
        limiter = PostgresAttemptLimiter(self.connect,real_clock=self.clock,
                     policy=LimitPolicy(account_attempts=1,source_attempts=1))
        self.assertTrue(limiter.consume(account_key="A",source_key="S").allowed)
        self.clock.value -= timedelta(seconds=60)
        decision = limiter.consume(account_key="A",source_key="S")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.retry_after_seconds,360)

if __name__ == "__main__":
    unittest.main()
