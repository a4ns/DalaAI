"""Only synthetic catalogues are seeded. Orders/sessions use real HTTP routes.

No staged photo or trusted file-valid row is invented. No session bypass, fake
verifier, fake limiter, fake repository or dependency override is supported.
"""
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

from .support import ORIGIN, REQUIRED_ROUTES, ensure, route_inventory, schema_name

SECTION = "00000000-0000-4000-8000-000000000001"
EQUIPMENT = "00000000-0000-4000-8000-000000000002"
EXECUTOR = "00000000-0000-4000-8000-000000000003"
MASTER = "00000000-0000-4000-8000-000000000004"
OTHER = "00000000-0000-4000-8000-000000000005"
CODE = "00000000-0000-4000-8000-000000000006"
MATERIAL = "00000000-0000-4000-8000-000000000007"
FOREIGN_SECTION = "00000000-0000-4000-8000-000000000008"
FOREIGN_EQUIPMENT = "00000000-0000-4000-8000-000000000009"
PIN = "71426839"  # Public synthetic test value, never a deployment credential.
EMPLOYEES = ((MASTER, "V-MASTER", "master"),
             (EXECUTOR, "V-EXECUTOR", "executor"),
             (OTHER, "V-OTHER", "executor"))


def connect_factory(schema):
    import psycopg
    from psycopg.rows import dict_row
    schema = schema_name(schema)
    def connect():
        return psycopg.connect(os.environ["DALA_TEST_DATABASE_URL"], autocommit=True,
                               options=f"-c search_path={schema} -c statement_timeout=10000 -c lock_timeout=5000",
                               connect_timeout=5, row_factory=dict_row)
    return connect


def seed_catalogues(connect):
    from argon2 import PasswordHasher
    from argon2.profiles import RFC_9106_LOW_MEMORY
    encoded = PasswordHasher.from_parameters(RFC_9106_LOW_MEMORY).hash(PIN)
    with connect() as db, db.transaction():
        db.execute("INSERT INTO sections VALUES (%s,'VS-1','Synthetic acceptance'),(%s,'VS-2','Synthetic foreign')",
                   (SECTION, FOREIGN_SECTION))
        for employee, code, role in EMPLOYEES:
            db.execute("INSERT INTO employees(id,employee_code,role,on_shift,pin_hash) VALUES (%s,%s,%s,true,%s)",
                       (employee, code, role, encoded))
            db.execute("INSERT INTO employee_sections VALUES (%s,%s)", (employee, SECTION))
        db.execute("INSERT INTO equipment VALUES (%s,%s,'VS-EQ','Synthetic equipment'),(%s,%s,'VS-EQ-2','Foreign equipment')",
                   (EQUIPMENT, SECTION, FOREIGN_EQUIPMENT, FOREIGN_SECTION))
        db.execute("INSERT INTO work_codes VALUES (%s,'VS-WORK','Synthetic planned maintenance')", (CODE,))
        db.execute("INSERT INTO materials VALUES (%s,'VS-MAT','Synthetic consumable','unit')", (MATERIAL,))


def create_component_app(connect):
    """Test-owned assembly. Does not claim app.main integration is implemented."""
    from fastapi import FastAPI
    from app.core.auth_boundary import SystemRealClock
    from app.persistence.http import create_router as command_router
    from app.persistence.service import CommandService
    from app.sessions.http import create_router as session_router
    from app.sessions.service import SessionService
    from app.discovery.http import create_discovery_router
    from app.discovery.service import DiscoveryService
    from app.discovery.workload import POLICY_NAME, WorkloadPolicy
    clock = SystemRealClock()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(session_router(SessionService(connect, allowed_origin=ORIGIN,
                       demo_enabled=True, real_clock=clock)))
    app.include_router(command_router(CommandService(connect, allowed_origin=ORIGIN,
                       delivery_channel="synthetic", domain_clock=clock, real_clock=clock)))
    app.include_router(create_discovery_router(DiscoveryService(connect, domain_clock=clock,
                       real_clock=clock, dictionary_policy=WorkloadPolicy(POLICY_NAME))))
    ensure(REQUIRED_ROUTES <= route_inventory(app), "Component assembly is missing a required route")
    ensure(not app.dependency_overrides, "Dependency overrides are forbidden in this acceptance harness")
    return app


class BrowserSession:
    """Independent cookie jar; HTTP over in-process ASGI, not a browser/device."""
    def __init__(self, client, employee, code, role):
        self.client, self.employee, self.code, self.role = client, employee, code, role
        self.csrf = None

    def login(self):
        response = self.client.post("/api/v1/auth/login", json={"employee_code": self.code, "pin": PIN},
                                    headers={"Origin": ORIGIN})
        ensure(response.status_code == 200, f"Synthetic {self.role} login returned {response.status_code}")
        body = response.json()
        ensure(body["principal"]["user_id"] == self.employee, "Login principal ID mismatch")
        ensure(body["principal"]["role"] == self.role, "Login principal role mismatch")
        cookie = response.headers.get("set-cookie", "").lower()
        ensure(all(flag in cookie for flag in ("__host-naryadai_session=", "secure", "httponly", "samesite=strict", "path=/")),
               "Login cookie lacks required protections")
        ensure("domain=" not in cookie, "__Host cookie must not carry a Domain attribute")
        current = self.client.get("/api/v1/me")
        ensure(current.status_code == 200, "Cookie-authenticated /me failed")
        ensure(current.json()["principal"] == body["principal"], "/me returned another principal")
        self.csrf = current.json()["csrf_token"]
        ensure(self.csrf == body["csrf_token"], "/me did not recover the session-bound CSRF token")

    def get(self, path):
        return self.client.get(path)

    def post(self, path, command):
        return self.client.post(path, json=command, headers={"Origin": ORIGIN, "X-CSRF-Token": self.csrf})

    def logout(self):
        response = self.client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": self.csrf})
        ensure(response.status_code == 204, f"Logout returned {response.status_code}")
        ensure(self.client.get("/api/v1/me").status_code == 401, "Logged-out client remains authenticated")


def clients(stack: ExitStack, app):
    from fastapi.testclient import TestClient
    result = []
    for index, (employee, code, role) in enumerate(EMPLOYEES):
        client = stack.enter_context(TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 42000 + index)))
        result.append(BrowserSession(client, employee, code, role))
    for session in result:
        session.login()
    return result


def command(action, version, payload=None):
    return {"operation_id": str(uuid4()), "expected_version": version,
            "action": action, "payload": {} if payload is None else payload}


def create_order_command(order_type="planned"):
    return command("create", 0, {
        "type": order_type, "description": "Synthetic acceptance maintenance only",
        "section_id": SECTION, "equipment_id": EQUIPMENT,
        "assignment": {"executor_id": EXECUTOR, "brigade_id": None},
        "due_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        "norm_minutes": 30, "priority": "normal", "comment": "Synthetic API acceptance",
        "before_photo_ids": [],
    })


def submission_payload():
    return {"work_description": "Synthetic planned service and inspection completed",
            "work_code_id": CODE, "materials": [{"material_id": MATERIAL, "quantity": 1.25}],
            "after_photo_ids": [], "comment": "Human review required; no model call"}
