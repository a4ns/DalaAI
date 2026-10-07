"""Explicit protected report mount. Host owns TLS, readiness and session cookies."""
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from app.analytics.c3_facts import facts_to_dict
from app.core.auth_boundary import AuthenticationRequired
from app.core.auth_policy import AccessDenied
from app.orders.models import DomainError
from app.persistence.http import _session
from .c4_render import (order_report_data, render_order_html, render_shift_html,
                        shift_report_data)

HEADERS = {"Cache-Control": "private, no-store", "Vary": "Cookie",
           "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}
HTML_HEADERS = {**HEADERS, "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; "
                "base-uri 'none'; form-action 'none'; frame-ancestors 'none'; sandbox"}
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


def create_c_runtime_router(service):
    router = APIRouter(prefix="/api/v1")

    def render(query, *, session_handle, kind, order_id):
        def project(facts, output):
            selected_id = facts.orders[0].order.id if order_id is not None else None
            if kind == "analytics":
                response = JSONResponse(facts_to_dict(facts), headers=HEADERS)
            elif output == "html":
                html = render_order_html(facts, selected_id) if selected_id else render_shift_html(facts)
                response = HTMLResponse(html, headers=HTML_HEADERS)
            else:
                data = order_report_data(facts, selected_id) if selected_id else shift_report_data(facts)
                response = JSONResponse(data, headers=HEADERS)
            if len(response.body) > MAX_RESPONSE_BYTES:
                raise DomainError("REPORT_LIMIT_EXCEEDED", "Report output exceeds capture limits")
            return response
        # Serialization occurs before the service's final current-session check.
        return service.capture(query, session_handle=session_handle, order_id=order_id,
                               allow_html=kind != "analytics", project=project)

    async def call(request, *, kind, order_id=None):
        try:
            # Do not use actor/role/section headers, bearer tokens, or query tokens.
            return await run_in_threadpool(render, list(request.query_params.multi_items()),
                session_handle=_session(request), kind=kind, order_id=order_id)
        except AuthenticationRequired:
            code, status, message = "UNAUTHENTICATED", 401, "Authentication required"
        except AccessDenied:
            code, status, message = "FORBIDDEN", 403, "Access denied"
        except DomainError as error:
            code = error.code
            status = {"INVALID_REQUEST": 400, "VALIDATION_FAILED": 422, "NOT_FOUND": 404,
                      "REPORT_LIMIT_EXCEEDED": 422, "TEMPORARILY_UNAVAILABLE": 503}.get(code, 503)
            message = "Report capture is unavailable" if status == 503 else str(error)
        except Exception:
            # Includes serialization conflicts, missing schema, corruption and
            # renderer failure. No retry/downgrade, raw exception or partial body.
            code, status, message = "TEMPORARILY_UNAVAILABLE", 503, "Report capture is unavailable"
        headers = dict(HEADERS)
        if status == 503:
            headers["Retry-After"] = "1"
        return JSONResponse({"code": code, "message": message, "request_id": str(uuid4()),
            "retryable": status == 503, "current_version": None, "field_errors": []},
            status_code=status, headers=headers)

    @router.get("/analytics/shift", operation_id="getRuntimeShiftAnalytics")
    async def analytics(request: Request):
        return await call(request, kind="analytics")

    @router.get("/reports/shift", operation_id="getRuntimeShiftReport")
    async def shift(request: Request):
        return await call(request, kind="shift")

    @router.get("/reports/orders/{order_id}", operation_id="getRuntimeOrderReport")
    async def order(request: Request, order_id: str):
        return await call(request, kind="order", order_id=order_id)

    return router
