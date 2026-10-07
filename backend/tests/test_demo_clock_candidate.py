"""Local synthetic proof only: no mounted API, PostgreSQL, providers or phone."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import asyncio
import json
import httpx
from threading import Event
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.auth_boundary import AuthenticationRequired, SessionRecord, SESSION_COOKIE_NAME, authenticate_session
from app.core.auth_policy import AccessDenied, Principal, Role, StagedPhotoScope, require_staged_attachment
from app.demo_clock.clock import DemoBusinessClock, DemoClockSettings, DemoClockUnavailable
from app.demo_clock.commands import parse_control
from app.demo_clock.http import create_demo_clock_router
from app.demo_clock.service import DemoClockService
from app.orders.models import DomainError
from app.scheduler import ScheduleSnapshot, SchedulePolicy, plan_due_jobs

T0 = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
ORIGIN = "https://demo.invalid"
ADMIN = "00000000-0000-0000-0000-000000000001"
FLAGS = DemoClockSettings(enabled=True, mode="demo", isolated_demo=True, single_process=True)


class RealClock:
    def __init__(self):
        self.value = T0
    def now(self):
        return self.value


class Stores:
    """In-memory auth substitute, not DB locks/revocation concurrency evidence."""
    def __init__(self):
        self.record = SessionRecord(ADMIN, T0 - timedelta(seconds=1), T0 + timedelta(minutes=10), "csrf")
        self.principal = Principal(ADMIN, Role.ADMIN, frozenset())
        self.lookups = 0
        self.on_principal = None
    def lookup(self, key):
        if key == "handle":
            self.lookups += 1
            return self.record
        if key == ADMIN:
            if self.on_principal:
                self.on_principal()
            return self.principal
        return None
    @contextmanager
    def scope(self):
        yield self, self


class Fixture(unittest.TestCase):
    def setUp(self):
        self.real = RealClock()
        self.clock = DemoBusinessClock(FLAGS, real_clock=self.real)
        self.stores = Stores()
        self.service = DemoClockService(self.clock, authorization_scope=self.stores.scope,
            allowed_origin=ORIGIN, allowed_operator_ids=frozenset({ADMIN}), operator_roles=frozenset({Role.ADMIN}), real_clock=self.real)
    def command(self, action="set_scale", value=30, snapshot=None):
        snap = snapshot or self.clock.capture()
        return {"instance_id": snap.instance_id, "expected_version": snap.revision,
                "action": action, "scale" if action == "set_scale" else "seconds": value}
    def control(self, command):
        return self.service.control(command, session_handle="handle", origin=ORIGIN, csrf_token="csrf")


class ClockTests(Fixture):
    def test_default_off_and_bad_environment_fail_closed(self):
        with self.assertRaises(DomainError):
            DemoBusinessClock().now()
        for bad in ({"enabled": 1}, {"enabled": True}, {"enabled": True, "mode": "production", "isolated_demo": True, "single_process": True},
                    {"enabled": True, "mode": "demo", "isolated_demo": False, "single_process": True}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                DemoClockSettings(**bad)
        with self.assertRaises(ValueError):
            DemoBusinessClock(DemoClockSettings(enabled=True, mode="demo", isolated_demo=True))

    def test_acceleration_pause_resume_and_advance_are_continuous(self):
        self.control(self.command(value=30))
        self.real.value += timedelta(seconds=10)
        self.assertEqual(self.clock.now(), T0 + timedelta(minutes=5))
        self.control(self.command(value=0))
        self.real.value += timedelta(seconds=90)
        self.assertEqual(self.clock.now(), T0 + timedelta(minutes=5))
        self.control(self.command("advance", 60))
        self.assertEqual(self.clock.now(), T0 + timedelta(minutes=6))
        self.control(self.command(value=1))
        self.real.value += timedelta(seconds=1)
        self.assertEqual(self.clock.now(), T0 + timedelta(minutes=6, seconds=1))

    def test_snapshot_is_immutable_and_mapping_is_consistent(self):
        self.control(self.command(value=30))
        before = self.clock.capture()
        with self.assertRaises(FrozenInstanceError):
            before.scale = 60
        self.control(self.command(value=60))
        self.real.value += timedelta(seconds=10)
        self.assertEqual(before.domain_now(self.real.now()), T0 + timedelta(minutes=5))
        current = self.clock.capture()
        self.assertEqual(current.business_now, current.domain_now(current.real_now))
        self.assertEqual(current.business_now, T0 + timedelta(minutes=10))
        self.assertEqual(current.wire()["mode"], "synthetic_demo")
        self.assertFalse(current.wire()["reset_supported"])

    def test_stale_and_restart_fences_reject_replayed_advance(self):
        command = self.command("advance", 60)
        self.control(command)
        for target in (self.clock, DemoBusinessClock(FLAGS, real_clock=self.real)):
            with self.assertRaises(DomainError) as caught:
                target.apply(command)
            self.assertEqual(caught.exception.code, "VERSION_CONFLICT")
        self.assertEqual(self.clock.now(), T0 + timedelta(seconds=60))

    def test_concurrent_cas_has_one_winner_and_no_double_advance(self):
        command = self.command("advance", 60)
        def action(_):
            try:
                self.control(command)
                return "changed"
            except DomainError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(action, range(20)))
        self.assertEqual(outcomes.count("changed"), 1)
        self.assertEqual(outcomes.count("VERSION_CONFLICT"), 19)
        self.assertEqual(self.clock.now(), T0 + timedelta(seconds=60))

    def test_bad_controls_never_change_state_even_on_direct_engine_call(self):
        bad = []
        for value in (-1, 61, True, 1.5, "30", None, float("nan"), float("inf")):
            bad.append(self.command(value=value))
        for value in (-60, 0, 3601, True, 1.5):
            bad.append(self.command("advance", value))
        bad += [dict(self.command(), action="reset"), dict(self.command(), actor_id=ADMIN),
                dict(self.command(), expected_version=True), dict(self.command(), instance_id="bad")]
        for command in bad:
            with self.subTest(command=command), self.assertRaises(DomainError):
                self.clock.apply(command)
        self.assertEqual(self.clock.capture().revision, 0)

    def test_strict_json_rejects_duplicate_nonfinite_and_extra_fields(self):
        for raw in ('{"action":"advance","action":"reset"}', '{"seconds":NaN}', '[]', '{', '{"scale":Infinity}'):
            with self.subTest(raw=raw), self.assertRaises(DomainError):
                parse_control(raw)

    def test_backward_real_time_and_business_horizon_fail_closed(self):
        self.clock.capture()
        self.real.value -= timedelta(seconds=1)
        with self.assertRaises(DemoClockUnavailable):
            self.clock.now()
        self.real.value = T0
        self.control(self.command(value=60))
        pinned = self.clock.capture()
        self.real.value += timedelta(days=1)
        with self.assertRaises(DemoClockUnavailable):
            self.clock.now()
        with self.assertRaises(DemoClockUnavailable):
            pinned.domain_now(self.real.now())

    def test_invalid_timezone_rejected(self):
        self.real.value = datetime(2026, 10, 7)
        with self.assertRaises(ValueError):
            self.clock.capture()

    def test_deadline_crossed_with_security_clock_unchanged(self):
        self.control(self.command(value=60))
        self.real.value += timedelta(seconds=4)
        order = ScheduleSnapshot("00000000-0000-0000-0000-000000000010", 1, 1, "issued", "emergency", "00000000-0000-0000-0000-000000000011", ADMIN, T0 + timedelta(minutes=10), T0, None)
        jobs = plan_due_jobs(order, domain_now=self.clock.now(), policy=SchedulePolicy(channel="synthetic"))
        self.assertTrue(any(job.kind.value == "acceptance_escalation" for job in jobs))
        self.assertEqual(self.real.now(), T0 + timedelta(seconds=4))
        self.assertEqual(authenticate_session("handle", sessions=self.stores, principals=self.stores,
            real_clock=self.real).principal.user_id, ADMIN)
        self.real.value = T0 + timedelta(minutes=10)
        with self.assertRaises(AuthenticationRequired):
            authenticate_session("handle", sessions=self.stores, principals=self.stores, real_clock=self.real)


class SecurityTests(Fixture):
    def test_auth_role_allowlist_revocation_and_inactive_fail_closed(self):
        for role in (Role.MASTER, Role.EXECUTOR, Role.MANAGER):
            self.stores.principal = replace(self.stores.principal, role=role)
            with self.subTest(role=role), self.assertRaises(AccessDenied):
                self.control(self.command())
        self.stores.principal = replace(self.stores.principal, role=Role.ADMIN, active=False)
        with self.assertRaises(AuthenticationRequired):
            self.control(self.command())
        self.stores.principal = replace(self.stores.principal, active=True)
        self.service.allowed_operator_ids = frozenset({"another-admin"})
        with self.assertRaises(AccessDenied):
            self.control(self.command())
        self.service.allowed_operator_ids = frozenset({ADMIN})
        self.stores.record = replace(self.stores.record, revoked=True)
        with self.assertRaises(AuthenticationRequired):
            self.control(self.command())
        self.assertEqual(self.clock.capture().revision, 0)

    def test_origin_and_csrf_cannot_be_overridden_by_body(self):
        for origin, csrf in ((None, "csrf"), ("null", "csrf"), ("https://evil.invalid", "csrf"), (ORIGIN, None), (ORIGIN, "bad")):
            with self.subTest(origin=origin, csrf=csrf), self.assertRaises(AccessDenied):
                self.service.control(self.command(), session_handle="handle", origin=origin, csrf_token=csrf)
        self.assertEqual(self.clock.capture().revision, 0)

    def test_real_expiry_after_principal_lock_wait_is_rechecked(self):
        self.stores.on_principal = lambda: setattr(self.real, "value", T0 + timedelta(minutes=10))
        with self.assertRaises(AuthenticationRequired):
            self.control(self.command())
        self.assertEqual(self.clock.capture().revision, 0)

    def test_real_expiry_while_waiting_for_controller_lock_is_rechecked(self):
        command = self.command()
        started = Event()
        def action():
            started.set()
            return self.control(command)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.clock.locked():
                future = pool.submit(action)
                self.assertTrue(started.wait(timeout=1))
                self.real.value = T0 + timedelta(minutes=10)
            with self.assertRaises(AuthenticationRequired):
                future.result(timeout=2)
        self.assertEqual(self.clock.capture().revision, 0)

    def test_acceleration_and_pause_do_not_change_staged_photo_real_ttl(self):
        principal = Principal("master", Role.MASTER, frozenset({"section"}))
        photo = StagedPhotoScope("photo", "section", "master", T0 + timedelta(seconds=10), "before", None, None)
        self.control(self.command(value=60))
        self.real.value += timedelta(seconds=4)
        require_staged_attachment(principal, photo, section_id="section", real_now=self.real.now())
        self.control(self.command(value=0))
        self.real.value = T0 + timedelta(seconds=10)
        with self.assertRaises(AccessDenied):
            require_staged_attachment(principal, photo, section_id="section", real_now=self.real.now())
        self.assertEqual(self.clock.now(), T0 + timedelta(minutes=4))

    def test_get_requires_current_admin_and_does_not_change_revision(self):
        for role in (Role.MASTER, Role.EXECUTOR, Role.MANAGER):
            self.stores.principal = replace(self.stores.principal, role=role)
            with self.subTest(role=role), self.assertRaises(AccessDenied):
                self.service.get(session_handle="handle")
        self.stores.principal = replace(self.stores.principal, role=Role.ADMIN)
        for _ in range(3):
            self.assertEqual(self.service.get(session_handle="handle")["version"], 0)

    def test_explicit_existing_master_operator_does_not_need_promotion(self):
        self.stores.principal = replace(self.stores.principal, role=Role.MASTER)
        with self.assertRaises(AccessDenied):
            self.control(self.command())
        self.service.operator_roles = frozenset({Role.MASTER})
        self.assertEqual(self.control(self.command())["version"], 1)
        self.assertEqual(self.stores.principal.role, Role.MASTER)
        self.service.allowed_operator_ids = frozenset({"different-master"})
        with self.assertRaises(AccessDenied):
            self.control(self.command())

    def test_authentication_precedes_body_interpretation(self):
        with self.assertRaises(AuthenticationRequired):
            self.service.control(b"{", session_handle="unknown", origin=ORIGIN, csrf_token="csrf")

    def test_business_clock_cannot_be_authentication_clock(self):
        with self.assertRaises(ValueError):
            DemoClockService(self.clock, authorization_scope=self.stores.scope, allowed_origin=ORIGIN,
                allowed_operator_ids=frozenset({ADMIN}), operator_roles=frozenset({Role.ADMIN}), real_clock=self.clock)


class HttpTests(Fixture):
    def setUp(self):
        super().setUp()
        app = FastAPI()
        app.include_router(create_demo_clock_router(self.service))
        self.client = TestClient(app, base_url=ORIGIN)
        self.headers = {"Cookie": f"{SESSION_COOKIE_NAME}=handle", "Origin": ORIGIN, "X-CSRF-Token": "csrf"}

    def test_control_snapshot_no_store_and_no_cookie_or_credentials(self):
        response = self.client.post("/api/v1/demo/clock", json=self.command(), headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["scale"], 30)
        self.assertIn("no-store", response.headers["cache-control"])
        self.assertNotIn("set-cookie", response.headers)
        self.assertNotIn("csrf", response.text)
        self.assertEqual(self.client.get("/api/v1/demo/clock", headers=self.headers).json()["version"], 1)

    def test_disabled_router_has_no_routes_and_reset_is_absent(self):
        self.service.clock = DemoBusinessClock()
        self.assertEqual(create_demo_clock_router(self.service).routes, [])
        self.assertEqual(self.client.post("/api/v1/demo/reset", headers=self.headers).status_code, 404)

    def test_unauthenticated_role_and_csrf_failure_no_changes(self):
        for headers, status in (({}, 401), ({"Cookie": self.headers["Cookie"], "Origin": ORIGIN}, 403),
                                (dict(self.headers, Origin="https://evil.invalid"), 403),
                                (dict(self.headers, **{"Sec-Fetch-Site": "cross-site"}), 403)):
            response = self.client.post("/api/v1/demo/clock", json=self.command(), headers=headers)
            self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(self.clock.capture().revision, 0)

    def test_duplicate_headers_cookies_query_and_oversize_rejected(self):
        for name, value in (("Origin", ORIGIN), ("X-CSRF-Token", "csrf"), ("Content-Type", "application/json")):
            headers = list(self.headers.items()) + [("Content-Type", "application/json"), (name, value)]
            response = self.client.post("/api/v1/demo/clock", content=json.dumps(self.command()), headers=headers)
            self.assertEqual(response.status_code, 400, response.text)
        headers = dict(self.headers, Cookie=self.headers["Cookie"] + "; " + self.headers["Cookie"])
        self.assertEqual(self.client.get("/api/v1/demo/clock", headers=headers).status_code, 400)
        self.assertEqual(self.client.get("/api/v1/demo/clock?admin=true", headers=self.headers).status_code, 400)
        self.assertEqual(self.client.post("/api/v1/demo/clock", content="x"*1025,
            headers=dict(self.headers, **{"Content-Type": "application/json"})).status_code, 413)
        self.assertEqual(self.clock.capture().revision, 0)

    def test_stale_control_returns_409_and_never_retries_advance(self):
        command = self.command("advance", 60)
        self.assertEqual(self.client.post("/api/v1/demo/clock", json=command, headers=self.headers).status_code, 200)
        retry = self.client.post("/api/v1/demo/clock", json=command, headers=self.headers)
        self.assertEqual(retry.status_code, 409)
        self.assertEqual(retry.json()["current_version"], 1)
        self.assertFalse(retry.json()["retryable"])

    def test_forms_bearer_urls_unknown_reset_and_actor_overrides_rejected(self):
        self.assertEqual(self.client.post("/api/v1/demo/clock", content="scale=30", headers=self.headers).status_code, 415)
        self.assertEqual(self.client.get("/api/v1/demo/clock", headers={"Authorization": "Bearer handle"}).status_code, 401)
        for body in (dict(self.command(), action="reset"), dict(self.command(), actor_id=ADMIN),
                     dict(self.command(), role="admin")):
            self.assertEqual(self.client.post("/api/v1/demo/clock", json=body, headers=self.headers).status_code, 400)
        self.assertEqual(self.clock.capture().revision, 0)

    def test_stalled_request_body_has_real_deadline_and_no_effect(self):
        app = FastAPI()
        app.include_router(create_demo_clock_router(self.service, body_deadline_seconds=0.01))
        async def run():
            async def stream():
                yield b"{"
                await asyncio.sleep(0.2)
                yield b"}"
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
                return await client.post("/api/v1/demo/clock", content=stream(),
                    headers=dict(self.headers, **{"Content-Type": "application/json"}))
        response = asyncio.run(run())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.clock.capture().revision, 0)

    def test_auth_store_failure_is_generic_and_has_no_success(self):
        @contextmanager
        def broken():
            raise RuntimeError("secret-database-url")
            yield
        self.service.authorization_scope = broken
        response = self.client.post("/api/v1/demo/clock", json=self.command(), headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret", response.text)
        self.assertFalse(response.json()["retryable"])
        self.assertEqual(self.clock.capture().revision, 0)


if __name__ == "__main__":
    unittest.main()
