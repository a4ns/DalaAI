"""ASGI entry point. Domain routers are added only after contract approval."""

from fastapi import FastAPI

from app.health import DatabaseProbe, check_postgres, health_router


def create_app(database_probe: DatabaseProbe = check_postgres) -> FastAPI:
    app = FastAPI(
        title="НарядAI infrastructure scaffold",
        version="0.0.1",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.include_router(health_router(database_probe))
    return app


app = create_app()
