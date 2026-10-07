"""Infrastructure probes, deliberately independent of the domain API contract."""

import asyncio
import os
from collections.abc import Awaitable, Callable

from fastapi import APIRouter
from fastapi.responses import JSONResponse

DatabaseProbe = Callable[[], Awaitable[bool]]
READINESS_TIMEOUT_SECONDS = 3.0


async def check_postgres() -> bool:
    """Check connectivity only; this does not certify migrations or business logic."""
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return False

    # Delay the driver import so liveness still works during a dependency outage.
    import psycopg

    async with await psycopg.AsyncConnection.connect(
        database_url,
        connect_timeout=2,
        options="-c statement_timeout=2000",
        autocommit=True,
    ) as connection:
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT 1")
            return await cursor.fetchone() == (1,)


def health_router(probe: DatabaseProbe) -> APIRouter:
    router = APIRouter()

    @router.get("/healthz", include_in_schema=False)
    async def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok"}, headers={"Cache-Control": "no-store"})

    @router.get("/readyz", include_in_schema=False)
    async def readyz() -> JSONResponse:
        try:
            async with asyncio.timeout(READINESS_TIMEOUT_SECONDS):
                ready = await probe()
        except Exception:
            # Never expose DSNs, passwords, hosts, SQL, or exception text here.
            ready = False
        return JSONResponse(
            {"status": "ready" if ready else "not_ready"},
            status_code=200 if ready else 503,
            headers={"Cache-Control": "no-store"},
        )

    return router
