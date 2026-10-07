"""Proposal.2 opt-in routes. No permissive CORS, form login, URL tokens or logs."""
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from app.core.auth_boundary import (AuthenticationRequired, SESSION_COOKIE_NAME,
                                    SESSION_COOKIE_OPTIONS)
from app.core.auth_policy import AccessDenied
from app.orders.models import DomainError
from .service import RateLimited
from .crypto import HashCapacityUnavailable

NO_STORE = {"Cache-Control": "private, no-store", "Pragma": "no-cache", "Vary": "Cookie"}
STATUS = {"INVALID_REQUEST": 400, "VALIDATION_FAILED": 422,
          "PAYLOAD_TOO_LARGE": 413, "UNSUPPORTED_MEDIA_TYPE": 415,
          "TEMPORARILY_UNAVAILABLE": 503}


def header(request, name):
    values = request.headers.getlist(name)
    if len(values) > 1:
        raise DomainError("INVALID_REQUEST", "Ambiguous request headers")
    return values[0] if values else None


def session(request, *, optional=False):
    cookies = [part.strip().split("=", 1) for value in request.headers.getlist("cookie")
               for part in value.split(";") if "=" in part]
    handles = [value for name, value in cookies if name == SESSION_COOKIE_NAME]
    if len(handles) > 1:
        raise DomainError("INVALID_REQUEST", "Ambiguous session cookie")
    if not handles and optional:
        return None
    if len(handles) != 1 or not handles[0]:
        raise AuthenticationRequired()
    return handles[0]


def problem(error):
    headers = dict(NO_STORE)
    retryable = False
    if isinstance(error, AuthenticationRequired):
        status, code, message = 401, "UNAUTHENTICATED", "Authentication required"
    elif isinstance(error, AccessDenied):
        status, code, message = 403, "FORBIDDEN", "Access denied"
    elif isinstance(error, RateLimited):
        status, code, message = 429, "RATE_LIMITED", "Try again later"
        headers["Retry-After"] = str(error.retry_after_seconds)
        retryable = True
    elif isinstance(error, HashCapacityUnavailable):
        status, code, message = 503, "TEMPORARILY_UNAVAILABLE", "Authentication temporarily unavailable"
        headers["Retry-After"] = "1"
        retryable = True
    elif isinstance(error, DomainError):
        code, message = error.code, str(error)
        status = STATUS.get(code, 422)
        if status == 503:
            retryable = True
            headers["Retry-After"] = "1"
    else:
        import psycopg
        if not isinstance(error, psycopg.Error):
            raise error
        # Commit may have succeeded without an HTTP response. Never clear a
        # cookie or claim logout/login success after an unconfirmed DB outcome.
        status, code, message = 503, "TEMPORARILY_UNAVAILABLE", "Session operation is not confirmed; try again"
        retryable = True
        headers["Retry-After"] = "1"
    return JSONResponse({"code": code, "message": message, "request_id": str(uuid4()),
                         "retryable": retryable, "current_version": None, "field_errors": []},
                        status_code=status, headers=headers)


def create_router(service):
    router = APIRouter(prefix="/api/v1")

    def protect_origin(request):
        origin = header(request, "origin")
        service.protection.require_origin(origin)
        site = header(request, "sec-fetch-site")
        if site is not None and site != "same-origin":
            raise AccessDenied()
        return origin

    @router.post("/auth/login", operation_id="loginDemoSession")
    async def login(request: Request):
        try:
            origin = protect_origin(request)
            media = header(request, "content-type")
            if media is None or media.split(";", 1)[0].strip().lower() != "application/json":
                raise DomainError("UNSUPPORTED_MEDIA_TYPE", "JSON request required")
            previous = session(request, optional=True)
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 4096:
                    raise DomainError("PAYLOAD_TOO_LARGE", "Login exceeds size limit")
                chunks.append(chunk)
            issued = await run_in_threadpool(service.login, b"".join(chunks), origin=origin,
                source_key=request.client.host if request.client else None, previous_handle=previous)
            response = JSONResponse(issued.body, headers=NO_STORE)
            response.set_cookie(SESSION_COOKIE_NAME, issued.session_handle,
                                max_age=issued.max_age, **SESSION_COOKIE_OPTIONS)
            return response
        except Exception as error:
            return problem(error)

    @router.get("/me", operation_id="getCurrentSession")
    async def me(request: Request):
        try:
            body = await run_in_threadpool(service.me, session_handle=session(request))
            return JSONResponse(body, headers=NO_STORE)
        except Exception as error:
            return problem(error)

    @router.post("/auth/logout", operation_id="logoutSession")
    async def logout(request: Request):
        try:
            origin = protect_origin(request)
            csrf = header(request, "x-csrf-token")
            if csrf is None or not 1 <= len(csrf) <= 256:
                raise AccessDenied()
            await run_in_threadpool(service.logout, session_handle=session(request), origin=origin, csrf_token=csrf)
            response = Response(status_code=204, headers=NO_STORE)
            response.delete_cookie(SESSION_COOKIE_NAME, **SESSION_COOKIE_OPTIONS)
            return response
        except Exception as error:
            return problem(error)

    return router
