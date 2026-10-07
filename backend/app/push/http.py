"""No request endpoint is fetched here; body/cookie/Origin ambiguity fail closed."""
from uuid import uuid4
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from app.core.auth_policy import AccessDenied
from app.orders.models import DomainError
from app.sessions.http import header, session, problem, NO_STORE


def create_push_router(service):
    router = APIRouter(prefix='/api/v1/push')

    def push_problem(error):
        if isinstance(error, DomainError) and error.code in {'SUBSCRIPTION_CONFLICT','PUSH_DISABLED'}:
            status = 409 if error.code == 'SUBSCRIPTION_CONFLICT' else 503
            return JSONResponse({'code':error.code,'message':str(error),'request_id':str(uuid4()),
                'retryable':False,'current_version':None,'field_errors':[]},status_code=status,headers=NO_STORE)
        try:
            import psycopg
            if isinstance(error, psycopg.errors.UniqueViolation):
                return push_problem(DomainError('SUBSCRIPTION_CONFLICT','Unsubscribe in this browser before switching accounts'))
        except ImportError:
            pass
        return problem(error)

    @router.get('/config', operation_id='getPushConfiguration')
    async def config(request: Request):
        try:
            if request.query_params:
                raise DomainError('INVALID_REQUEST','Query parameters are not supported')
            result = await run_in_threadpool(service.config,session_handle=session(request))
            return JSONResponse(result,headers=NO_STORE)
        except Exception as error:
            return push_problem(error)

    async def mutate(request, *, remove=False):
        try:
            if request.query_params:
                raise DomainError('INVALID_REQUEST','Query parameters are not supported')
            origin = header(request,'origin')
            service.protection.require_origin(origin)
            if header(request,'sec-fetch-site') not in (None,'same-origin'):
                raise AccessDenied()
            csrf = header(request,'x-csrf-token')
            if not csrf or len(csrf) > 512:
                raise AccessDenied()
            handle = session(request)
            media = header(request,'content-type')
            if media is None or media.split(';',1)[0].strip().lower() != 'application/json':
                raise DomainError('UNSUPPORTED_MEDIA_TYPE','JSON request required')
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 4096:
                    raise DomainError('PAYLOAD_TOO_LARGE','Subscription exceeds size limit')
                chunks.append(chunk)
            result = await run_in_threadpool(service.mutate,b''.join(chunks),remove=remove,
                session_handle=handle,origin=origin,csrf_token=csrf)
            return Response(status_code=204,headers=NO_STORE) if remove else JSONResponse(result,headers=NO_STORE)
        except Exception as error:
            return push_problem(error)

    @router.post('/subscriptions', operation_id='registerCurrentPushSubscription')
    async def register(request: Request):
        return await mutate(request)

    @router.post('/subscriptions/remove', operation_id='removeCurrentPushSubscription')
    async def remove(request: Request):
        return await mutate(request,remove=True)

    return router
