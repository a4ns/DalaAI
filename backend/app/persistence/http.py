"""Opt-in FastAPI router for the proposal.2 vertical slice, not the full API.

Host mounts this router once, supplies CommandService, and owns login/upload,
TLS/cookie issuance, dependency pins, and application lifecycle. No side effects
at import and no alternate auth scheme. Synchronous DB work uses a threadpool.
"""
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.core.auth_boundary import AuthenticationRequired, SESSION_COOKIE_NAME
from app.core.auth_policy import AccessDenied
from app.orders.models import DomainError

ERROR_STATUS = {"INVALID_REQUEST":400,"VALIDATION_FAILED":422,"NOT_FOUND":404,
    "FORBIDDEN":403,"PHOTO_EXPIRED":422,"UNSUPPORTED_MEDIA_TYPE":415,"VERSION_CONFLICT":409,"TRANSITION_CONFLICT":409,"STALE_ASSIGNMENT":409,
    "OPERATION_ID_REUSED":409,"INCOMPLETE_SUBMISSION":409,"PAYLOAD_TOO_LARGE":413}


def _header(request, name):
    values = request.headers.getlist(name)
    if len(values) > 1:
        raise DomainError("INVALID_REQUEST", "Ambiguous request headers")
    return values[0] if values else None


def _session(request):
    cookies = [part.strip().split("=",1) for value in request.headers.getlist("cookie")
               for part in value.split(";") if "=" in part]
    handles = [value for name,value in cookies if name == SESSION_COOKIE_NAME]
    if len(handles) != 1:
        raise AuthenticationRequired()
    return handles[0]


def create_router(service):
    router = APIRouter(prefix="/api/v1")

    async def call(request, method, *args, mutation=False):
        try:
            handle = _session(request)
            kwargs = {"session_handle":handle}
            if mutation:
                content_type = _header(request,"content-type")
                if content_type is None or content_type.split(";",1)[0].strip().lower() != "application/json":
                    raise DomainError("UNSUPPORTED_MEDIA_TYPE", "JSON request required")
                # Bound streamed bodies too; Content-Length alone is untrusted.
                chunks = []
                size = 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > 65536:
                        raise DomainError("PAYLOAD_TOO_LARGE", "Command exceeds size limit")
                    chunks.append(chunk)
                kwargs.update(origin=_header(request,"origin"),csrf_token=_header(request,"x-csrf-token"))
                if args:
                    kwargs["order_id"] = args[0]
                result = await run_in_threadpool(method,b"".join(chunks),**kwargs)
                return JSONResponse(result.body,status_code=result.status,headers={"Cache-Control":"private, no-store"})
            body = await run_in_threadpool(method,*args,**kwargs)
            return JSONResponse(body,headers={"Cache-Control":"private, no-store"})
        except (AuthenticationRequired,AccessDenied,DomainError) as error:
            if isinstance(error,AuthenticationRequired):
                code,status,message = "UNAUTHENTICATED",401,"Authentication required"
            elif isinstance(error,AccessDenied):
                code,status,message = "FORBIDDEN",403,"Access denied"
            else:
                code,status,message = error.code,ERROR_STATUS.get(error.code,422),str(error)
            body = {"code":code,"message":message,"request_id":str(uuid4()),"retryable":False,
                "current_version":getattr(error,"current_version",None),
                "field_errors":[{"path":f.path,"code":f.code} for f in getattr(error,"field_errors",())]}
            return JSONResponse(body,status_code=status,headers={"Cache-Control":"private, no-store"})
        except Exception as error:
            import psycopg
            if not isinstance(error,psycopg.Error):
                raise
            # Do not leak DSN/query/constraint/object details or claim no commit.
            return JSONResponse({"code":"TEMPORARILY_UNAVAILABLE","message":"Result is not confirmed; retry the same operation",
                "request_id":str(uuid4()),"retryable":True,"current_version":None,"field_errors":[]},
                status_code=503,headers={"Retry-After":"1","Cache-Control":"private, no-store"})

    @router.post("/orders",operation_id="createOrder")
    async def create(request:Request):
        return await call(request,service.execute,mutation=True)

    @router.post("/orders/{order_id}/commands",operation_id="executeOrderCommand")
    async def command(order_id:str,request:Request):
        return await call(request,service.execute,order_id,mutation=True)

    @router.get("/orders/{order_id}",operation_id="getOrder")
    async def order(order_id:str,request:Request):
        return await call(request,service.get_order,order_id)

    @router.get("/orders/{order_id}/submissions/{submission_id}",operation_id="getSubmission")
    async def submission(order_id:str,submission_id:str,request:Request):
        return await call(request,service.get_submission,order_id,submission_id)

    return router
