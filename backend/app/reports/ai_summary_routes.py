"""Explicit POST-only AI report mount. GET/polling can never trigger a provider."""
import asyncio
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.auth_boundary import AuthenticationRequired
from app.core.auth_policy import AccessDenied
from app.orders.models import DomainError
from app.persistence.http import _header, _session
from .ai_summary import MAX_BODY_BYTES
from .c4_routes import HEADERS

MAX_BODY_READ_SECONDS = 5.0


def create_ai_summary_router(service):
    router = APIRouter(prefix='/api/v1')

    @router.post('/reports/ai-summary', operation_id='createGroundedAIReportSummary')
    async def summarize(request: Request):
        try:
            handle = _session(request)
            if request.query_params:
                raise DomainError('INVALID_REQUEST', 'AI report query parameters are unsupported')
            content_type = _header(request, 'content-type')
            if content_type is None or content_type.split(';', 1)[0].strip().lower() != 'application/json':
                raise DomainError('UNSUPPORTED_MEDIA_TYPE', 'JSON request required')
            chunks, size = [], 0
            try:
                async with asyncio.timeout(MAX_BODY_READ_SECONDS):
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > MAX_BODY_BYTES:
                            raise DomainError('PAYLOAD_TOO_LARGE', 'AI report request exceeds limit')
                        chunks.append(chunk)
            except TimeoutError:
                raise DomainError('REQUEST_TIMEOUT', 'AI report request body timed out') from None
            return await service.execute(b''.join(chunks), session_handle=handle,
                origin=_header(request, 'origin'), csrf_token=_header(request, 'x-csrf-token'))
        except AuthenticationRequired:
            code, status, message = 'UNAUTHENTICATED', 401, 'Authentication required'
        except AccessDenied:
            code, status, message = 'FORBIDDEN', 403, 'Access denied'
        except DomainError as error:
            code = error.code
            status = {'INVALID_REQUEST': 400, 'VALIDATION_FAILED': 422, 'REPORT_LIMIT_EXCEEDED': 422,
                'REQUEST_TIMEOUT': 408, 'OPERATION_ID_REUSED': 409, 'PAYLOAD_TOO_LARGE': 413,
                'UNSUPPORTED_MEDIA_TYPE': 415}.get(code, 503)
            message = str(error) if status != 503 else 'AI report capture is unavailable'
        except Exception:
            code, status, message = 'TEMPORARILY_UNAVAILABLE', 503, 'AI report capture is unavailable'
        headers = dict(HEADERS)
        if status == 503:
            headers['Retry-After'] = '1'
        return JSONResponse({'code': code, 'message': message, 'request_id': str(uuid4()),
            'retryable': status == 503, 'current_version': None, 'field_errors': []},
            status_code=status, headers=headers)

    return router
