"""Opt-in same-origin stage/retrieval router. Host owns TLS/proxy limits."""
import asyncio
from threading import BoundedSemaphore
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from app.core.auth_boundary import AuthenticationRequired
from app.core.auth_policy import AccessDenied
from app.orders.models import DomainError
from app.persistence.http import ERROR_STATUS, _header, _session

from .multipart import UploadParser
from .validation import PhotoUnavailable

_UPLOAD_SLOTS = BoundedSemaphore(2)
_HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


def _error(error):
    headers = dict(_HEADERS)
    retryable = False
    if isinstance(error, AuthenticationRequired):
        status, code, message = 401, "UNAUTHENTICATED", "Authentication required"
    elif isinstance(error, AccessDenied):
        status, code, message = 403, "FORBIDDEN", "Access denied"
    elif isinstance(error, DomainError):
        code = error.code
        status = 429 if code == "RATE_LIMITED" else ERROR_STATUS.get(code, 422)
        message = str(error)
        if status == 429:
            # A minimum retry delay, not a promise that quota self-cleans. The
            # client should resolve outstanding stages/operator storage first.
            headers["Retry-After"] = "60"
    else:
        import psycopg
        if not isinstance(error, (PhotoUnavailable, psycopg.Error)):
            raise error
        status, code = 503, "TEMPORARILY_UNAVAILABLE"
        message = "Result is not confirmed; retry the same operation"
        retryable = True
        headers["Retry-After"] = "1"
    return JSONResponse({"code": code, "message": message, "request_id": str(uuid4()),
        "retryable": retryable, "current_version": None,
        "field_errors": [{"path": f.path, "code": f.code} for f in getattr(error, "field_errors", ())]},
        status_code=status, headers=headers)


def create_photo_router(service, *, max_upload_seconds=30):
    if type(max_upload_seconds) not in (int, float) or not 0 < max_upload_seconds <= 120:
        raise ValueError("Bounded real-time upload deadline required")
    router = APIRouter(prefix="/api/v1")

    @router.post("/photos/stage", operation_id="stagePhoto")
    async def stage(request: Request):
        acquired = False
        try:
            handle = _session(request)
            origin, csrf = _header(request, "origin"), _header(request, "x-csrf-token")
            fetch_site = _header(request, "sec-fetch-site")
            if fetch_site not in (None, "same-origin"):
                raise AccessDenied()
            await run_in_threadpool(service.preflight, session_handle=handle, origin=origin, csrf_token=csrf)
            acquired = _UPLOAD_SLOTS.acquire(blocking=False)
            if not acquired:
                raise PhotoUnavailable()
            parser = UploadParser(_header(request, "content-type"))
            # Bound chunked/lying-length requests; no disk spool or form parser
            # sees an unbounded stream before authentication/CSRF succeeds.
            try:
                async with asyncio.timeout(max_upload_seconds):
                    async for chunk in request.stream():
                        parser.write(chunk)
            except TimeoutError:
                raise PhotoUnavailable() from None
            fields, raw, mime = parser.result()
            result = await run_in_threadpool(service.stage, fields, raw, session_handle=handle,
                origin=origin, csrf_token=csrf, declared_mime=mime)
            return JSONResponse(result.body, status_code=result.status, headers=_HEADERS)
        except Exception as error:
            return _error(error)
        finally:
            if acquired:
                _UPLOAD_SLOTS.release()

    @router.get("/photos/{photo_id}", operation_id="getPhoto")
    async def get(photo_id: str, request: Request):
        try:
            handle = _session(request)
            data, mime = await run_in_threadpool(service.get, photo_id, session_handle=handle)
            return Response(data, media_type=mime, headers={**_HEADERS, "Content-Disposition": "inline"})
        except Exception as error:
            return _error(error)

    return router
