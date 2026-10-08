"""One opt-in GET route. No command, assignment, provider, or side effects."""
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.core.auth_boundary import AuthenticationRequired
from app.core.auth_policy import AccessDenied
from app.orders.models import DomainError
from app.persistence.http import _session

HEADERS = {'Cache-Control': 'private, no-store', 'Vary': 'Cookie',
           'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer'}


def create_assignee_router(service):
    router = APIRouter(prefix='/api/v1')

    @router.get('/recommendations/assignees', operation_id='getAssigneeRecommendations')
    async def recommend(request: Request):
        try:
            return await run_in_threadpool(service.recommend,
                list(request.query_params.multi_items()), session_handle=_session(request),
                project=lambda body: JSONResponse(body, headers=HEADERS))
        except AuthenticationRequired:
            code, status, message = 'UNAUTHENTICATED', 401, 'Authentication required'
        except AccessDenied:
            code, status, message = 'FORBIDDEN', 403, 'Access denied'
        except DomainError as error:
            code = error.code
            status = {'INVALID_REQUEST': 400, 'VALIDATION_FAILED': 422,
                      'RECOMMENDATION_LIMIT_EXCEEDED': 422, 'TEMPORARILY_UNAVAILABLE': 503}.get(code, 503)
            message = str(error) if status != 503 else 'Recommendations are temporarily unavailable'
        except Exception:
            # Includes PostgreSQL serialization/lock errors. No exception, SQL,
            # DSN, partial ranking, or alternate stale fallback in an error body.
            code, status, message = 'TEMPORARILY_UNAVAILABLE', 503, 'Recommendations are temporarily unavailable'
        headers = dict(HEADERS)
        if status == 503:
            headers['Retry-After'] = '1'
        return JSONResponse({'code': code, 'message': message, 'request_id': str(uuid4()),
            'retryable': status == 503, 'current_version': None, 'field_errors': []},
            status_code=status, headers=headers)

    return router
