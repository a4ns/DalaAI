"""Two GET routes only, mounted alongside the frozen mutation/read router."""
from uuid import uuid4
from fastapi import APIRouter,Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from app.core.auth_boundary import AuthenticationRequired
from app.core.auth_policy import AccessDenied
from app.orders.models import DomainError
from app.persistence.http import _session


def create_discovery_router(service):
    router=APIRouter(prefix="/api/v1")

    async def call(request,method,*args):
        try:
            result=await run_in_threadpool(method,*args,session_handle=_session(request))
            return JSONResponse(result,headers={"Cache-Control":"private, no-store"})
        except (AuthenticationRequired,AccessDenied,DomainError) as error:
            if isinstance(error,AuthenticationRequired):
                code,status,message="UNAUTHENTICATED",401,"Authentication required"
            elif isinstance(error,AccessDenied):
                code,status,message="FORBIDDEN",403,"Access denied"
            else:
                code,message=error.code,str(error)
                status={"INVALID_REQUEST":400,"VALIDATION_FAILED":422,"TEMPORARILY_UNAVAILABLE":503}.get(code,422)
            headers={"Cache-Control":"private, no-store"}
            if status==503:
                headers["Retry-After"]="1"
            return JSONResponse({"code":code,"message":message,"request_id":str(uuid4()),"retryable":status==503,
                "current_version":None,"field_errors":[{"path":f.path,"code":f.code} for f in getattr(error,"field_errors",())]},
                status_code=status,headers=headers)
        except Exception as error:
            import psycopg
            if not isinstance(error,psycopg.Error):
                raise
            return JSONResponse({"code":"TEMPORARILY_UNAVAILABLE","message":"Discovery is temporarily unavailable",
                "request_id":str(uuid4()),"retryable":True,"current_version":None,"field_errors":[]},status_code=503,
                headers={"Cache-Control":"private, no-store","Retry-After":"1"})

    @router.get("/orders",operation_id="listOrders")
    async def orders(request:Request):
        return await call(request,service.list_orders,list(request.query_params.multi_items()))

    @router.get("/dicts",operation_id="getDictionaries")
    async def dictionaries(request:Request):
        if request.query_params:
            # Contract has no dictionary filter parameters; don't imply a
            # caller-provided section can replace current server-side scope.
            return JSONResponse({"code":"INVALID_REQUEST","message":"Dictionary query parameters are not supported",
                "request_id":str(uuid4()),"retryable":False,"current_version":None,"field_errors":[]},status_code=400,
                headers={"Cache-Control":"private, no-store"})
        return await call(request,service.get_dictionaries)

    return router
