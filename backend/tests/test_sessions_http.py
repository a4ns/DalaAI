"""HTTP transport wiring probes, explicitly stub service (not PostgreSQL proof)."""
import unittest
from unittest.mock import Mock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.auth_boundary import AuthenticationRequired, RequestProtection, SESSION_COOKIE_NAME
from app.core.auth_policy import AccessDenied
from app.sessions.http import create_router
from app.sessions.service import IssuedSession, RateLimited

ORIGIN = "https://naryadai.test"
BODY = {"principal":{"user_id":"00000000-0000-0000-0000-000000000001","active":True,
        "employee_code":"SYNTHETIC","role":"executor","section_ids":[],"on_shift":True},
        "csrf_token":"synthetic-csrf", "expires_at":"2026-10-08T01:00:00Z"}


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.service = Mock()
        self.service.protection = RequestProtection(ORIGIN)
        self.service.login.return_value = IssuedSession(BODY, "synthetic-handle", 28800)
        self.service.me.return_value = BODY
        app = FastAPI()
        app.include_router(create_router(self.service))
        self.client = TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 50000))

    def login(self, **kwargs):
        return self.client.post("/api/v1/auth/login", json={"employee_code":"SYNTHETIC","pin":"1234"},
                                headers={"Origin":ORIGIN}, **kwargs)

    def test_login_cookie_and_no_store(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        cookie = response.headers["set-cookie"]
        for flag in ("__Host-naryadai_session=", "Secure", "HttpOnly", "SameSite=strict", "Path=/", "Max-Age=28800"):
            self.assertIn(flag, cookie)
        self.assertNotIn("Domain", cookie)
        self.assertNotIn("synthetic-handle", response.text)
        self.assertEqual(response.json(), BODY)
        self.assertIn("no-store", response.headers["cache-control"])

    def test_me_and_logout_cookie(self):
        self.login()
        self.assertEqual(self.client.get("/api/v1/me").json(), BODY)
        response = self.client.post("/api/v1/auth/logout", headers={"Origin":ORIGIN,"X-CSRF-Token":"synthetic-csrf"})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertIn("Max-Age=0", response.headers["set-cookie"])
        self.assertIn("Secure", response.headers["set-cookie"])
        self.service.logout.assert_called_once_with(session_handle="synthetic-handle",origin=ORIGIN,csrf_token="synthetic-csrf")

    def test_cross_origin_and_fetch_site_never_call_login(self):
        for headers in ({}, {"Origin":"null"}, {"Origin":"https://evil.test"},
                        {"Origin":ORIGIN,"Sec-Fetch-Site":"cross-site"},
                        {"Origin":ORIGIN,"Sec-Fetch-Site":"same-site"}):
            response = self.client.post("/api/v1/auth/login", json={}, headers=headers)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["code"], "FORBIDDEN")
        self.service.login.assert_not_called()

    def test_forms_and_oversize_rejected(self):
        for content, content_type, status in (("pin=1234", "application/x-www-form-urlencoded",415),
                                               ("a"*4097,"application/json",413)):
            response = self.client.post("/api/v1/auth/login", content=content,
                                       headers={"Origin":ORIGIN,"Content-Type":content_type})
            self.assertEqual(response.status_code, status)
        self.service.login.assert_not_called()

    def test_duplicate_origin_content_type_and_cookie_rejected(self):
        for headers in ([("Origin",ORIGIN),("Origin",ORIGIN)],
                        [("Origin",ORIGIN),("Content-Type","application/json"),("Content-Type","text/plain")],
                        [("Origin",ORIGIN),("Content-Type","application/json"),("Cookie",f"{SESSION_COOKIE_NAME}=a; {SESSION_COOKIE_NAME}=b")]):
            response = self.client.post("/api/v1/auth/login", content="{}", headers=headers)
            self.assertEqual(response.status_code, 400)
        self.service.login.assert_not_called()

    def test_forwarded_source_is_ignored(self):
        self.client.post("/api/v1/auth/login", json={}, headers={"Origin":ORIGIN,"X-Forwarded-For":"8.8.8.8"})
        self.assertEqual(self.service.login.call_args.kwargs["source_key"], "127.0.0.1")

    def test_me_requires_single_cookie_not_query_bearer(self):
        for route, headers in (("/api/v1/me?token=synthetic", {}),
                               ("/api/v1/me",{"Authorization":"Bearer synthetic"}),
                               ("/api/v1/me",{"Cookie":f"{SESSION_COOKIE_NAME}=a; {SESSION_COOKIE_NAME}=b"})):
            response = self.client.get(route, headers=headers)
            self.assertIn(response.status_code,(400,401))
        self.service.me.assert_not_called()

    def test_logout_requires_origin_and_csrf(self):
        self.login()
        for headers in ({}, {"Origin":ORIGIN}, {"Origin":ORIGIN,"X-CSRF-Token":"x"*257},
                        [("Origin",ORIGIN),("X-CSRF-Token","a"),("X-CSRF-Token","b")]):
            response = self.client.post("/api/v1/auth/logout", headers=headers)
            self.assertIn(response.status_code,(400,403))
            self.assertNotIn("set-cookie",response.headers)
        self.service.logout.assert_not_called()

    def test_rate_limit_retry_after_no_cookie(self):
        self.service.login.side_effect = RateLimited(14)
        response = self.login()
        self.assertEqual(response.status_code,429)
        self.assertEqual(response.headers["retry-after"],"14")
        self.assertTrue(response.json()["retryable"])
        self.assertNotIn("set-cookie",response.headers)

    def test_generic_invalid_credentials(self):
        self.service.login.side_effect = AuthenticationRequired()
        response = self.login()
        self.assertEqual(response.status_code,401)
        self.assertEqual(response.json()["message"],"Authentication required")
        self.assertNotIn("set-cookie", response.headers)

    def test_psycopg_failure_never_leaks_or_clears_cookie(self):
        import psycopg
        self.login()
        self.service.logout.side_effect = psycopg.OperationalError("secret-dsn-sensitive-query")
        response = self.client.post("/api/v1/auth/logout", headers={"Origin":ORIGIN,"X-CSRF-Token":"synthetic-csrf"})
        self.assertEqual(response.status_code,503)
        self.assertNotIn("secret",response.text)
        self.assertNotIn("set-cookie",response.headers)
        self.assertEqual(response.headers["retry-after"],"1")

    def test_hash_capacity_safe_retry(self):
        from app.sessions.crypto import HashCapacityUnavailable
        self.service.login.side_effect = HashCapacityUnavailable()
        response = self.login()
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.headers["retry-after"],"1")
        self.assertNotIn("set-cookie",response.headers)

if __name__ == "__main__":
    unittest.main()
