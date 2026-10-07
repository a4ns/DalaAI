"""HTTP parser/transport tests with an explicit service stub, not DB evidence."""
import asyncio
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.auth_boundary import AuthenticationRequired, SESSION_COOKIE_NAME
from app.core.auth_policy import AccessDenied
from app.orders.models import DomainError
from app.persistence.service import CommandResult
from app.photos import http
from app.photos.http import create_photo_router
from app.photos.validation import PhotoUnavailable
from test_photos_unit import fields, image_bytes, multipart, SECTION


class StubService:
    def __init__(self):
        self.calls = []
        self.failure = None

    def preflight(self, **kwargs):
        self.calls.append(("preflight", kwargs))
        if kwargs["session_handle"] != "synthetic-session":
            raise AuthenticationRequired()
        if kwargs["origin"] != "https://photo.test" or kwargs["csrf_token"] != "synthetic-csrf":
            raise AccessDenied()

    def stage(self, form, raw, **kwargs):
        self.calls.append(("stage", form, raw, kwargs))
        if self.failure:
            raise self.failure
        return CommandResult(201, {"id": SECTION})

    def get(self, photo_id, **kwargs):
        self.calls.append(("get", photo_id, kwargs))
        if self.failure:
            raise self.failure
        return image_bytes(), "image/png"


class PhotoHttpTests(unittest.TestCase):
    def setUp(self):
        self.service = StubService()
        self.app = FastAPI()
        self.app.include_router(create_photo_router(self.service))
        self.client = TestClient(self.app, base_url="https://photo.test")
        self.headers = {"cookie": SESSION_COOKIE_NAME + "=synthetic-session",
            "origin": "https://photo.test", "x-csrf-token": "synthetic-csrf"}

    def upload(self, **kwargs):
        return self.client.post("/api/v1/photos/stage", data=fields(),
            files={"file": ("../../ignored.png", image_bytes(), "image/png")},
            headers=kwargs.pop("headers", self.headers), **kwargs)

    def test_upload_passes_exact_bytes_and_declared_type(self):
        response = self.upload()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        call = self.service.calls[-1]
        self.assertEqual(call[0], "stage")
        self.assertEqual(call[1], fields())
        self.assertEqual(call[2], image_bytes())
        self.assertEqual(call[3]["declared_mime"], "image/png")

    def test_auth_csrf_origin_before_body_parser(self):
        for update, status in [({"cookie": ""}, 401), ({"origin": "https://evil.test"}, 403),
                               ({"x-csrf-token": "wrong"}, 403), ({"sec-fetch-site": "cross-site"}, 403)]:
            with self.subTest(update=update), patch("app.photos.http.UploadParser") as parser:
                response = self.upload(headers={**self.headers, **update})
                self.assertEqual(response.status_code, status)
                parser.assert_not_called()

    def test_duplicate_cookie_and_csrf(self):
        bad = {**self.headers, "cookie": self.headers["cookie"] + "; " + self.headers["cookie"]}
        self.assertEqual(self.upload(headers=bad).status_code, 401)
        headers = list(self.headers.items()) + [("x-csrf-token", "second")]
        self.assertEqual(self.upload(headers=headers).status_code, 400)

    def test_json_and_unfinished_multipart_refused(self):
        response = self.client.post("/api/v1/photos/stage", json=fields(), headers=self.headers)
        self.assertEqual(response.status_code, 415)
        response = self.client.post("/api/v1/photos/stage", content=b"--x\r\n",
            headers={**self.headers, "content-type": "multipart/form-data; boundary=x"})
        self.assertEqual(response.status_code, 400)

    def test_lying_length_stream_limit_and_duplicate_field(self):
        content = multipart([(k, v, None, None) for k, v in fields().items()]
            + [("file", image_bytes(), "x", "image/png"), ("purpose", "after", None, None)])
        response = self.client.post("/api/v1/photos/stage", content=content,
            headers={**self.headers, "content-type": "multipart/form-data; boundary=bounded-test"})
        self.assertEqual(response.status_code, 400)
        with patch("app.photos.multipart.MAX_REQUEST_BYTES", 100):
            response = self.client.post("/api/v1/photos/stage", content=[b"x" * 101],
                headers={**self.headers, "content-type": "multipart/form-data; boundary=x", "content-length": "1"})
        self.assertEqual(response.status_code, 413)

    def test_upload_budget_released_on_failure(self):
        http._UPLOAD_SLOTS.acquire()
        http._UPLOAD_SLOTS.acquire()
        try:
            response = self.upload()
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.headers["retry-after"], "1")
        finally:
            http._UPLOAD_SLOTS.release()
            http._UPLOAD_SLOTS.release()
        self.assertEqual(self.upload().status_code, 201)

    def test_photo_is_private_authenticated_bytes(self):
        response = self.client.get("/api/v1/photos/" + SECTION, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, image_bytes())
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertNotIn("location", response.headers)
        self.assertEqual(self.client.get("/api/v1/photos/" + SECTION).status_code, 401)

    def test_error_envelopes_retry_after_and_unknown_commit(self):
        import psycopg
        cases = [(DomainError("RATE_LIMITED", "Outstanding photo limit reached"), 429, "RATE_LIMITED"),
                 (DomainError("PHOTO_EXPIRED", "Staged photo expired"), 422, "PHOTO_EXPIRED"),
                 (PhotoUnavailable(), 503, "TEMPORARILY_UNAVAILABLE"),
                 (psycopg.OperationalError("sensitive DSN not returned"), 503, "TEMPORARILY_UNAVAILABLE")]
        for error, status, code in cases:
            self.service.failure = error
            response = self.upload()
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json()["code"], code)
            self.assertNotIn("sensitive", response.text)
            self.assertEqual(response.headers["cache-control"], "private, no-store")
            if status in (429, 503):
                self.assertGreaterEqual(int(response.headers["retry-after"]), 1)
            if status == 503:
                self.assertTrue(response.json()["retryable"])
                self.assertIn("same operation", response.json()["message"])


class PhotoUploadDeadlineTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_body_releases_upload_capacity_and_cannot_stage(self):
        import httpx
        service = StubService()
        app = FastAPI()
        app.include_router(create_photo_router(service, max_upload_seconds=0.02))
        async def slow_content():
            yield b"--x\r\n"
            await asyncio.sleep(0.1)
            yield b"unfinished"
        headers = {"cookie": SESSION_COOKIE_NAME + "=synthetic-session",
            "origin": "https://photo.test", "x-csrf-token": "synthetic-csrf",
            "content-type": "multipart/form-data; boundary=x"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://photo.test") as client:
            response = await client.post("/api/v1/photos/stage", content=slow_content(), headers=headers)
        self.assertEqual(response.status_code, 503)
        self.assertEqual([call[0] for call in service.calls], ["preflight"])
        self.assertTrue(http._UPLOAD_SLOTS.acquire(blocking=False))
        self.assertTrue(http._UPLOAD_SLOTS.acquire(blocking=False))
        http._UPLOAD_SLOTS.release()
        http._UPLOAD_SLOTS.release()


if __name__ == "__main__":
    unittest.main()
