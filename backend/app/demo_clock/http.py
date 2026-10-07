"""Unmounted proposal: disabled factories return an empty router."""
import asyncio
import math
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.core.auth_boundary import AuthenticationRequired, SESSION_COOKIE_NAME
from app.core.auth_policy import AccessDenied
from app.orders.models import DomainError

NO_STORE = {"Cache-Control": "private, no-store", "Pragma": "no-cache", "Vary": "Cookie"}


def _header(request, name):
    values = request.headers.getlist(name)
    if len(values) > 1:
        raise DomainError("INVALID_REQUEST", "Ambiguous request headers")
    return values[0] if values else None


def _session(request):
    cookies = [part.strip().split("=", 1) for value in request.headers.getlist("cookie")
               for part in value.split(";") if "=" in part]
    handles = [value for name, value in cookies if name == SESSION_COOKIE_NAME]
    if len(handles) > 1:
        raise DomainError("INVALID_REQUEST", "Ambiguous session cookie")
    if len(handles) != 1 or not handles[0]:
        raise AuthenticationRequired()
    return handles[0]


def _problem(error):
    if isinstance(error, AuthenticationRequired):
        status, code, message = 401, "UNAUTHENTICATED", "Authentication required"
    elif isinstance(error, AccessDenied):
        status, code, message = 403, "FORBIDDEN", "Access denied"
    elif isinstance(error, DomainError):
        code, message = error.code, str(error)
        status = {"NOT_FOUND": 404, "VERSION_CONFLICT": 409, "INVALID_REQUEST": 400,
                  "VALIDATION_FAILED": 422, "PAYLOAD_TOO_LARGE": 413, "UNSUPPORTED_MEDIA_TYPE": 415}.get(code, 422)
    else:
        status, code, message = 503, "TEMPORARILY_UNAVAILABLE", "Clock result is unconfirmed; refresh before another action"
    return JSONResponse({"code": code, "message": message, "request_id": str(uuid4()),
        "retryable": False, "current_version": getattr(error, "current_version", None), "field_errors": []},
        status_code=status, headers=NO_STORE)


def create_demo_clock_router(service, *, body_deadline_seconds=5):
    if type(body_deadline_seconds) not in (int, float) or not math.isfinite(body_deadline_seconds) or not 0 < body_deadline_seconds <= 10:
        raise ValueError("Bounded real request-body deadline required")
    router = APIRouter(prefix="/api/v1/demo")
    if not service.clock.settings.enabled:
        return router

    def ingress(request):
        if request.query_params:
            raise DomainError("INVALID_REQUEST", "Query parameters are unsupported")
        site = _header(request, "sec-fetch-site")
        if site is not None and site != "same-origin":
            raise AccessDenied()
        return _session(request)

    @router.get("/clock", operation_id="getSyntheticDemoClockProposal")
    async def get_clock(request: Request):
        try:
            return JSONResponse(await run_in_threadpool(service.get, session_handle=ingress(request)), headers=NO_STORE)
        except Exception as error:
            return _problem(error)

    @router.post("/clock", operation_id="controlSyntheticDemoClockProposal")
    async def control_clock(request: Request):
        try:
            handle = ingress(request)
            origin, csrf = _header(request, "origin"), _header(request, "x-csrf-token")
            service.protection.require_origin(origin)
            media = _header(request, "content-type")
            if media is None or media.split(";", 1)[0].strip().lower() != "application/json":
                raise DomainError("UNSUPPORTED_MEDIA_TYPE", "JSON request required")
            chunks, size = [], 0
            async with asyncio.timeout(body_deadline_seconds):
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > 1024:
                        raise DomainError("PAYLOAD_TOO_LARGE", "Clock command exceeds size limit")
                    chunks.append(chunk)
            result = await run_in_threadpool(service.control, b"".join(chunks),
                session_handle=handle, origin=origin, csrf_token=csrf)
            return JSONResponse(result, headers=NO_STORE)
        except Exception as error:
            return _problem(error)
    return router
