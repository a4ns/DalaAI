"""Unit/HTTP checks. Fake probes do not prove a real PostgreSQL connection."""

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.health import check_postgres
from app.main import create_app


class HealthTests(unittest.TestCase):
    def test_liveness_does_not_query_database(self):
        probe = AsyncMock(side_effect=RuntimeError("database unavailable"))
        with TestClient(create_app(probe)) as client:
            response = client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertEqual(response.headers["cache-control"], "no-store")
        probe.assert_not_awaited()

    def test_readiness_success(self):
        probe = AsyncMock(return_value=True)
        with TestClient(create_app(probe)) as client:
            response = client.get("/readyz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ready"})
        probe.assert_awaited_once()

    def test_readiness_false_is_not_success(self):
        with TestClient(create_app(AsyncMock(return_value=False))) as client:
            response = client.get("/readyz")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "not_ready"})
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_exception_details_are_not_exposed(self):
        probe = AsyncMock(side_effect=RuntimeError("postgresql://private:secret@host/db"))
        with TestClient(create_app(probe)) as client:
            response = client.get("/readyz")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "not_ready"})
        self.assertNotIn("secret", response.text)

    def test_readiness_timeout_is_bounded_and_cancels_probe(self):
        cancelled = []

        async def stalled():
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.append(True)

        with patch("app.health.READINESS_TIMEOUT_SECONDS", 0.01):
            with TestClient(create_app(stalled)) as client:
                response = client.get("/readyz")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(cancelled, [True])

    def test_unconfigured_database_reports_unready(self):
        with patch.dict(os.environ, {}, clear=True):
            with TestClient(create_app()) as client:
                response = client.get("/readyz")
        self.assertEqual(response.status_code, 503)

    def test_unknown_domain_route_is_not_fake_success(self):
        with TestClient(create_app()) as client:
            self.assertEqual(client.get("/api/v1/orders").status_code, 404)
            self.assertEqual(client.post("/healthz").status_code, 405)


class DatabaseProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_driver_query_and_connection_are_closed(self):
        cursor = AsyncMock()
        cursor.fetchone.return_value = (1,)
        cursor_context = MagicMock()
        cursor_context.__aenter__ = AsyncMock(return_value=cursor)
        cursor_context.__aexit__ = AsyncMock(return_value=False)
        connection = MagicMock()
        connection.cursor.return_value = cursor_context
        connection_context = MagicMock()
        connection_context.__aenter__ = AsyncMock(return_value=connection)
        connection_context.__aexit__ = AsyncMock(return_value=False)
        connect = AsyncMock(return_value=connection_context)
        fake_driver = SimpleNamespace(AsyncConnection=SimpleNamespace(connect=connect))
        with patch.dict("sys.modules", {"psycopg": fake_driver}):
            with patch.dict(os.environ, {"DATABASE_URL": "postgresql://test/db"}):
                self.assertTrue(await check_postgres())
        connect.assert_awaited_once_with(
            "postgresql://test/db", connect_timeout=2,
            options="-c statement_timeout=2000", autocommit=True,
        )
        cursor.execute.assert_awaited_once_with("SELECT 1")
        cursor_context.__aexit__.assert_awaited_once()
        connection_context.__aexit__.assert_awaited_once()

    async def test_missing_or_blank_database_url(self):
        for value in ("", "   "):
            with self.subTest(value=value), patch.dict(os.environ, {"DATABASE_URL": value}):
                self.assertFalse(await check_postgres())


if __name__ == "__main__":
    unittest.main()
