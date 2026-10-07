"""Harness-only safety, source inventory and assertion helpers (stdlib only)."""
from datetime import datetime, timezone
from hashlib import sha256
import importlib
import json
from pathlib import Path
import re

ORIGIN = "https://vertical-acceptance.test"
SCHEMA_PATTERN = re.compile(r"^vertical_acceptance_[0-9a-f]{32}$")
REQUIRED_ROUTES = {
    ("POST", "/api/v1/auth/login"), ("POST", "/api/v1/auth/logout"),
    ("GET", "/api/v1/me"), ("GET", "/api/v1/dicts"),
    ("GET", "/api/v1/orders"), ("POST", "/api/v1/orders"),
    ("GET", "/api/v1/orders/{order_id}"),
    ("POST", "/api/v1/orders/{order_id}/commands"),
    ("GET", "/api/v1/orders/{order_id}/submissions/{submission_id}"),
}
MODULES = (
    "fastapi", "httpx", "psycopg", "argon2", "app.persistence.service", "app.persistence.http",
    "app.sessions.service", "app.sessions.http", "app.sessions.crypto",
    "app.discovery.service", "app.discovery.http", "app.discovery.workload",
)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def ensure(condition, message):
    if not condition:
        raise AssertionError(message)


def schema_name(value):
    if not SCHEMA_PATTERN.fullmatch(value):
        raise ValueError("Only a harness-owned random schema is allowed")
    return value


def require_local_dsn(dsn, parser):
    """No remote host, inherited service or environment-resolved host is accepted.

    Credentials never appear in errors/reports. An explicit Unix socket directory
    or loopback host is required so the harness cannot contact an external DB.
    """
    parsed = parser(dsn)
    if parsed.get("service") or parsed.get("servicefile"):
        raise ValueError("PostgreSQL service indirection is not allowed")
    host = parsed.get("host", "")
    if not host or "," in host:
        raise ValueError("An explicit single local PostgreSQL host is required")
    if host not in {"localhost", "127.0.0.1", "::1"} and not host.startswith("/"):
        raise ValueError("Only a loopback host or local Unix socket is allowed")
    if parsed.get("hostaddr") not in {None, "", "127.0.0.1", "::1"}:
        raise ValueError("Only a loopback hostaddr is allowed")
    if not parsed.get("dbname"):
        raise ValueError("An explicit disposable database name is required")
    return parsed


def file_inventory(root):
    root = Path(root).resolve()
    records = []
    for pattern in ("app/**/*.py", "db/migrations/*.sql"):
        for path in sorted(root.glob(pattern)):
            records.append({"path": str(path.relative_to(root)),
                            "sha256": sha256(path.read_bytes()).hexdigest()})
    digest = sha256(json.dumps(records, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"root": str(root), "tree_sha256": digest, "files": records}


def module_inventory():
    result = []
    for name in MODULES:
        try:
            module = importlib.import_module(name)
            path = getattr(module, "__file__", None)
            result.append({"module": name, "status": "AVAILABLE", "path": path})
        except (ImportError, ModuleNotFoundError) as error:
            result.append({"module": name, "status": "NOTRUN", "missing": error.name})
    return result


def route_inventory(app):
    # FastAPI's pinned release can keep included routers lazily represented as
    # _IncludedRouter objects. Use its public OpenAPI compiler instead of
    # mistaking a lazy route list for missing domain routes.
    openapi = getattr(app, "openapi", None)
    if callable(openapi):
        return {(method.upper(), path) for path, operations in openapi().get("paths", {}).items()
                for method in operations if method in {"get", "post", "put", "patch", "delete", "head", "options"}}
    return {(method, route.path) for route in app.routes for method in getattr(route, "methods", ())}


def inspect_main_wiring():
    try:
        main = importlib.import_module("app.main")
    except ModuleNotFoundError as error:
        return {"status": "NOTRUN", "reason": "Application entry point unavailable", "missing": error.name}
    factory = getattr(main, "create_app", None)
    if factory is None:
        return {"status": "NOTRUN", "reason": "app.main.create_app unavailable"}
    # Inspection only. Do not enter lifespan, migrate, probe DB or start workers.
    app = factory()
    missing = sorted(REQUIRED_ROUTES - route_inventory(app))
    return {"status": "FAIL" if missing else "ROUTES_PRESENT_UNEXERCISED",
            "reason": "Route inventory only; not deployed application acceptance",
            "missing_routes": [f"{method} {path}" for method, path in missing]}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
