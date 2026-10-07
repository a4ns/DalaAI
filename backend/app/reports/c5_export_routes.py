"""Fixed export URLs; mount BEFORE C4's generic /orders/{order_id} route."""
from threading import BoundedSemaphore
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from app.core.auth_boundary import AuthenticationRequired
from app.core.auth_policy import AccessDenied
from app.orders.models import DomainError
from app.persistence.http import _session
from .c4_routes import HEADERS
from .c5_exports import MAX_BYTES, render_export_bounded

# Across all mounted export routers in this API process, not per request/user.
_SLOTS = BoundedSemaphore(2)
_MEDIA = {'pdf': 'application/pdf', 'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}


def create_c_export_router(service):
    router = APIRouter(prefix='/api/v1')

    def render(query, *, session_handle, output, order_id):
        if not _SLOTS.acquire(blocking=False):
            raise DomainError('TEMPORARILY_UNAVAILABLE', 'Report export is unavailable')
        try:
            def project(facts, validated_format, historical_evidence):
                # Fixed route selects binary output; existing parser still owns
                # strict start/end/duplicate/unknown/format query validation.
                selected_id = facts.orders[0].order.id if order_id is not None else None
                body = render_export_bounded(facts, output, order_id=selected_id,
                                             historical_evidence=historical_evidence)
                if len(body) > MAX_BYTES:
                    raise DomainError('REPORT_LIMIT_EXCEEDED', 'Report export exceeds rendering limits')
                filename = 'naryadai-' + ('order-' + selected_id if selected_id else 'shift') + '.' + output
                return Response(body, media_type=_MEDIA[output], headers={**HEADERS,
                    'Content-Disposition': 'attachment; filename="' + filename + '"',
                    'Content-Security-Policy': "default-src 'none'; sandbox"})
            # The complete binary body is created BEFORE the service's final
            # current-role/membership/session real-expiry recheck and commit.
            return service.capture(query, session_handle=session_handle, order_id=order_id,
                                   allow_html=False, project=project)
        finally:
            _SLOTS.release()

    async def call(request, output, order_id=None):
        try:
            return await run_in_threadpool(render, list(request.query_params.multi_items()),
                session_handle=_session(request), output=output, order_id=order_id)
        except AuthenticationRequired:
            code, status, message = 'UNAUTHENTICATED', 401, 'Authentication required'
        except AccessDenied:
            code, status, message = 'FORBIDDEN', 403, 'Access denied'
        except DomainError as error:
            code = error.code
            status = {'INVALID_REQUEST': 400, 'VALIDATION_FAILED': 422, 'NOT_FOUND': 404,
                      'REPORT_LIMIT_EXCEEDED': 422}.get(code, 503)
            message = 'Report export is unavailable' if status == 503 else str(error)
        except Exception:
            code, status, message = 'TEMPORARILY_UNAVAILABLE', 503, 'Report export is unavailable'
        headers = dict(HEADERS)
        if status == 503:
            headers['Retry-After'] = '1'
        return JSONResponse({'code': code, 'message': message, 'request_id': str(uuid4()),
            'retryable': status == 503, 'current_version': None, 'field_errors': []},
            status_code=status, headers=headers)

    @router.get('/reports/shift.pdf', operation_id='exportRuntimeShiftPdf')
    async def shift_pdf(request: Request):
        return await call(request, 'pdf')

    @router.get('/reports/shift.xlsx', operation_id='exportRuntimeShiftXlsx')
    async def shift_xlsx(request: Request):
        return await call(request, 'xlsx')

    @router.get('/reports/orders/{order_id}.pdf', operation_id='exportRuntimeOrderPdf')
    async def order_pdf(request: Request, order_id: str):
        return await call(request, 'pdf', order_id)

    @router.get('/reports/orders/{order_id}.xlsx', operation_id='exportRuntimeOrderXlsx')
    async def order_xlsx(request: Request, order_id: str):
        return await call(request, 'xlsx', order_id)

    return router
