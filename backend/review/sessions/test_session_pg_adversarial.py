"""Four independent real-PG scenarios supplementing the author's session suite.

NOT_RUN locally: no PostgreSQL service. Reuses only the author's isolated-schema
fixture/helpers. load_tests deliberately excludes inherited author scenarios.
No app-role/privilege matrix duplication. Run with run_pg_adversarial.sh.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import unittest

import test_sessions_postgres as author_suite

from app.core.auth_boundary import AuthenticationRequired, SESSION_COOKIE_NAME
from app.core.auth_policy import AccessDenied
from app.sessions.limiter import LimitPolicy, PostgresAttemptLimiter, bucket
from app.sessions.service import SessionService

ORIGIN = author_suite.ORIGIN


class AdversarialSessionPostgresTests(author_suite.SessionPostgresTests):
    def test_source_capacity_race_with_distinct_account_buckets(self):
        keys = []
        used = set()
        counter = 0
        while len(keys) < 12:
            candidate = "review-account-" + str(counter)
            counter += 1
            if bucket(candidate) not in used:
                used.add(bucket(candidate))
                keys.append(candidate)
        barrier = Barrier(len(keys))
        def consume(account):
            limiter = PostgresAttemptLimiter(self.connect, real_clock=self.clock,
                         policy=LimitPolicy(account_attempts=5, source_attempts=3, window_seconds=300))
            barrier.wait(timeout=10)
            return limiter.consume(account_key=account, source_key="192.0.2.10").allowed
        with ThreadPoolExecutor(max_workers=len(keys)) as pool:
            results = list(pool.map(consume, keys))
        self.assertEqual(sum(results), 3)
        self.assertEqual(self.query("SELECT attempts FROM auth_login_limits WHERE kind='source'")[0]["attempts"], 3)

    def test_cross_account_csrf_scope_and_account_switch(self):
        user_b = "00000000-0000-4000-8000-000000000101"
        section_b = "00000000-0000-4000-8000-000000000102"
        self.query("INSERT INTO sections VALUES (%s,'REVIEW-B','Synthetic B')", (section_b,))
        self.query("""INSERT INTO employees(id,employee_code,role,pin_hash)
                    VALUES (%s,'REVIEW-B','manager',%s)""", (user_b, self.pin_hash))
        self.query("INSERT INTO employee_sections VALUES (%s,%s)", (user_b, section_b))
        first = self.login()
        second = self.login(code="REVIEW-B")
        self.assertEqual(second.body["principal"]["user_id"], user_b)
        self.assertEqual(second.body["principal"]["section_ids"], [section_b])
        self.assertNotEqual(first.body["csrf_token"], second.body["csrf_token"])
        with self.assertRaises(AccessDenied):
            self.service.logout(session_handle=first.session_handle, origin=ORIGIN,
                                csrf_token=second.body["csrf_token"])
        self.assertEqual(self.service.me(session_handle=first.session_handle), first.body)
        self.assertEqual(self.service.me(session_handle=second.session_handle), second.body)
        replacement = self.login(code="REVIEW-B", previous=first.session_handle)
        self.assertEqual(replacement.body["principal"]["user_id"], user_b)
        with self.assertRaises(AuthenticationRequired):
            self.service.me(session_handle=first.session_handle)

    def test_issuance_failure_rolls_back_rotation_but_keeps_attempt(self):
        first = self.login()
        class FailAfterSessionInsert(SessionService):
            def _wire(self, db, context):
                raise RuntimeError("synthetic failure after session insert")
        failing = FailAfterSessionInsert(self.connect, allowed_origin=ORIGIN,
                    demo_enabled=True, real_clock=self.clock, verifier=self.verifier)
        with self.assertRaises(RuntimeError):
            self.login(service=failing, previous=first.session_handle)
        rows = self.query("SELECT revoked_at FROM auth_sessions")
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["revoked_at"])
        self.assertEqual(self.service.me(session_handle=first.session_handle), first.body)
        self.assertEqual(self.query("SELECT attempts FROM auth_login_limits WHERE kind='account'")[0]["attempts"], 2)
        self.assertEqual(self.query("SELECT attempts FROM auth_login_limits WHERE kind='source'")[0]["attempts"], 2)

    def test_commit_failure_http_never_sets_success_cookie(self):
        first = self.login()
        # Fault injection confined to this test's random disposable schema.
        # A deferred trigger proves success is not returned before COMMIT.
        self.query("""CREATE FUNCTION review_fail_auth_commit() RETURNS trigger LANGUAGE plpgsql AS $$
                       BEGIN RAISE EXCEPTION 'synthetic commit failure' USING ERRCODE='40001'; END $$""")
        self.query("""CREATE CONSTRAINT TRIGGER review_auth_commit_failure AFTER INSERT ON auth_sessions
                       DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
                       EXECUTE FUNCTION review_fail_auth_commit()""")
        client = self.client()
        response = client.post("/api/v1/auth/login",
                    json={"employee_code": "SYNTHETIC", "pin": author_suite.PIN},
                    headers={"Origin": ORIGIN, "Cookie": SESSION_COOKIE_NAME + "=" + first.session_handle})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("set-cookie", response.headers)
        self.assertNotIn("synthetic commit failure", response.text)
        self.assertNotIn("review_fail_auth_commit", response.text)
        rows = self.query("SELECT revoked_at FROM auth_sessions")
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["revoked_at"])
        self.assertEqual(self.service.me(session_handle=first.session_handle), first.body)
        self.assertEqual(self.query("SELECT attempts FROM auth_login_limits WHERE kind='account'")[0]["attempts"], 2)


def load_tests(loader, standard_tests, pattern):
    # Do not duplicate the inherited author tests; run only these four methods.
    names = sorted(name for name in AdversarialSessionPostgresTests.__dict__ if name.startswith("test_"))
    return unittest.TestSuite(AdversarialSessionPostgresTests(name) for name in names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
