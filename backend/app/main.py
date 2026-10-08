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
    from app.order_events.http import create_order_events_router
    from app.order_events.service import OrderEventService
    from app.discovery.http import create_discovery_router
    from app.discovery.service import DiscoveryService
    from app.discovery.workload import POLICY_NAME, WorkloadPolicy
    connector = connect or connection_factory(settings)
    clock = SystemRealClock()
    domain_clock = clock
    if settings.demo_clock_enabled:
        from app.demo_clock.clock import DemoClockSettings
        from app.demo_clock.postgres import build_domain_clock
        domain_clock = build_domain_clock(DemoClockSettings(enabled=True,mode='demo',isolated_demo=True),
            connect=connector,instance_id=settings.demo_clock_instance_id)
    photo_enabled = bool(settings.photo_storage_root)
    references_factory = UnavailablePhotoReferences
    photo_service = None
    if photo_enabled:
        from functools import partial
        from app.photos.storage import PrivateFileStore
        from app.photos.service import PhotoService
        from app.photos.integrity import PhotoIntegrityVerifier
        from app.integration.photo_evidence import VerifiedPhotoReferences
        store = PrivateFileStore(settings.photo_storage_root, max_total_bytes=settings.photo_max_total_bytes)
        photo_service = PhotoService(connector, allowed_origin=settings.allowed_origin,
                                     private_blob_store=store, real_clock=clock)
        references_factory = partial(VerifiedPhotoReferences, verifier=PhotoIntegrityVerifier(store))

    def check_database():
        if settings.demo_clock_enabled:
            return validate_database(connector,photo_enabled=photo_enabled,
                notification_enabled=settings.notification_enabled,push_enabled=settings.push_enabled,
                demo_clock_enabled=True,demo_clock_instance_id=settings.demo_clock_instance_id)
        if settings.notification_enabled or settings.push_enabled:
            return validate_database(connector, photo_enabled=photo_enabled,
                notification_enabled=settings.notification_enabled, push_enabled=settings.push_enabled)
        if photo_enabled:
            return validate_database(connector, photo_enabled=True)
        return validate_database(connector)

    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(check_database)
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
            await asyncio.to_thread(check_database)
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
    session_service = SessionService(connector, allowed_origin=settings.allowed_origin,
                                    demo_enabled=True, real_clock=clock)
    app.include_router(session_router(session_service))
    if settings.demo_clock_enabled:
        from app.core.auth_policy import Role
        from app.demo_clock.runtime import DEMO_MASTER_ID
        from app.demo_clock.service import DemoClockService, postgres_authorization_scope
        from app.demo_clock.http import create_demo_clock_router
        app.include_router(create_demo_clock_router(DemoClockService(domain_clock,
            authorization_scope=postgres_authorization_scope(connector),allowed_origin=settings.allowed_origin,
            allowed_operator_ids=frozenset({DEMO_MASTER_ID}),operator_roles=frozenset({Role.MASTER}),real_clock=clock)))

    app.include_router(command_router(CommandService(connector, allowed_origin=settings.allowed_origin,
                       delivery_channel=settings.delivery_channel, domain_clock=domain_clock, real_clock=clock,
                       references_factory=references_factory)))
    app.include_router(create_discovery_router(DiscoveryService(connector, domain_clock=domain_clock,
                       real_clock=clock, dictionary_policy=WorkloadPolicy(POLICY_NAME))))
    app.include_router(create_order_events_router(OrderEventService(connector, real_clock=clock)))
    from app.recommendations.assignee import AssigneeRecommendationService
    from app.recommendations.assignee_routes import create_assignee_router
    app.include_router(create_assignee_router(AssigneeRecommendationService(connector,
        domain_clock=domain_clock, real_clock=clock, synthetic=True)))
    from app.analytics.c3_repository import RuntimeReportService
    from app.reports.c4_routes import create_c_runtime_router
    from app.reports.c5_export_routes import create_c_export_router
    report_service = RuntimeReportService(session_service, domain_clock=domain_clock, synthetic=True)
    # Suffix export routes must precede the generic order-report UUID route.
    app.include_router(create_c_export_router(report_service))
    app.include_router(create_c_runtime_router(report_service))
    if photo_service is not None:
        from app.photos.http import create_photo_router
        app.include_router(create_photo_router(photo_service))
    if settings.push_enabled:
        from app.push.http import create_push_router
        from app.push.service import PushService
        from app.push.settings import PushSettings
        app.include_router(create_push_router(PushService(connector,
            allowed_origin=settings.allowed_origin, settings=PushSettings.from_env(), real_clock=clock)))
    return app


app = create_app()
