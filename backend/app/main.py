"""ASGI entry point; the demo API requires explicit configuration and real DB."""
import asyncio
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.health import DatabaseProbe, check_postgres, health_router
from app.runtime import (RuntimeSettings, UnavailablePhotoReferences,
                         connection_factory, validate_database)


def create_app(database_probe: DatabaseProbe = check_postgres, *, settings=None, connect=None) -> FastAPI:
    settings = settings or RuntimeSettings.from_env()
    if settings.mode == 'health':
        if connect is not None:
            raise ValueError('Connection injection requires explicit demo mode')
        app = FastAPI(title='НарядAI health scaffold', version='0.1.0',
                      docs_url=None, redoc_url=None, openapi_url=None)
        app.include_router(health_router(database_probe))
        return app

    from app.core.auth_boundary import SystemRealClock
    from app.persistence.http import create_router as command_router
    from app.persistence.service import CommandService
    from app.sessions.http import create_router as session_router
    from app.sessions.service import SessionService
    from app.discovery.http import create_discovery_router
    from app.discovery.service import DiscoveryService
    from app.discovery.workload import POLICY_NAME, WorkloadPolicy
    connector = connect or connection_factory(settings)
    clock = SystemRealClock()

    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(validate_database, connector)
        app.state.runtime_ready = True
        try:
            yield
        finally:
            app.state.runtime_ready = False

    app = FastAPI(title='НарядAI isolated demo API', version='0.1.0', lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.runtime_ready = False
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlsplit(settings.allowed_origin).hostname])

    @app.middleware('http')
    async def require_started_runtime(request, call_next):
        if request.url.path.startswith('/api/') and not app.state.runtime_ready:
            return JSONResponse({'code':'TEMPORARILY_UNAVAILABLE', 'message':'Runtime unavailable',
                'request_id':str(uuid4()), 'retryable':True, 'current_version':None, 'field_errors':[]},
                status_code=503, headers={'Cache-Control':'private, no-store', 'Retry-After':'1'})
        return await call_next(request)

    async def runtime_ready():
        if not app.state.runtime_ready:
            return False
        try:
            await asyncio.to_thread(validate_database, connector)
            return True
        except asyncio.CancelledError:
            app.state.runtime_ready = False
            raise
        except Exception:
            # A failed prerequisite check requires operator repair and a new
            # process startup. Never keep accepting commands after detecting it.
            app.state.runtime_ready = False
            return False

    app.include_router(health_router(runtime_ready))
    app.include_router(session_router(SessionService(connector, allowed_origin=settings.allowed_origin,
                       demo_enabled=True, real_clock=clock)))
    app.include_router(command_router(CommandService(connector, allowed_origin=settings.allowed_origin,
                       delivery_channel='synthetic', domain_clock=clock, real_clock=clock,
                       references_factory=UnavailablePhotoReferences)))
    app.include_router(create_discovery_router(DiscoveryService(connector, domain_clock=clock,
                       real_clock=clock, dictionary_policy=WorkloadPolicy(POLICY_NAME))))
    return app


app = create_app()
