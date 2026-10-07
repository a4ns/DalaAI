"""Offline Telegram adapter checks. Every transport is fake; no credentials."""
from io import StringIO
import json
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.notify.models import DeliveryEnvelope
from app.notifications.telegram import (
    KINDS, TelegramAdapter, TelegramConfig, TelegramConfigurationError,
    TelegramHttpsTransport, TransportResult,
)


RECIPIENT = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"
ORDER = "00000000-0000-4000-8000-000000000003"
JOB = "00000000-0000-4000-8000-000000000004"
CHAT = 123456789
FAKE_TOKEN = "123456:" + "x" * 35


def notice(**changes):
    return SimpleNamespace(**({"job_id": JOB, "order_id": ORDER,
        "recipient_id": RECIPIENT, "kind": "new_order", "channel": "telegram"} | changes))


def settings(**changes):
    return TelegramConfig(**({"mode": "live", "synthetic_demo": True,
        "token": FAKE_TOKEN, "bindings": {RECIPIENT: CHAT}} | changes))


def accepted(message_id=42, chat=CHAT):
    return TransportResult("response", 200, {"ok": True,
        "result": {"message_id": message_id, "chat": {"id": chat, "type": "private"}}})


def rejected(code, **parameters):
    return TransportResult("response", code, {"ok": False, "error_code": code,
        "description": "sensitive remote error " + FAKE_TOKEN,
        "parameters": parameters})


class FakeTransport:
    def __init__(self, result=None):
        self.result = result or accepted()
        self.calls = []

    def send_message(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class TelegramConfigurationTests(unittest.TestCase):
    def test_disabled_by_default_and_no_token_read(self):
        class Environment(dict):
            def get(self, key, default=None):
                if key == "TELEGRAM_BOT_TOKEN":
                    raise AssertionError("Disabled provider read credential")
                return super().get(key, default)
        cfg = TelegramConfig.from_environment(Environment())
        self.assertEqual(cfg.mode, "disabled")
        fake = FakeTransport()
        out = TelegramAdapter(cfg, transport=fake).send(notice())
        self.assertEqual(out.state, "permanent_failure")
        self.assertEqual(out.code, "TELEGRAM_DISABLED")
        self.assertEqual(fake.calls, [])

    def test_env_live_requires_explicit_synthetic_scope_token_and_binding(self):
        good = {"TELEGRAM_MODE": "live", "TELEGRAM_SYNTHETIC_DEMO": "1",
            "TELEGRAM_BOT_TOKEN": FAKE_TOKEN,
            "TELEGRAM_DEMO_BINDINGS_JSON": json.dumps({RECIPIENT: CHAT})}
        self.assertEqual(TelegramConfig.from_environment(good).mode, "live")
        for key in ("TELEGRAM_SYNTHETIC_DEMO", "TELEGRAM_BOT_TOKEN", "TELEGRAM_DEMO_BINDINGS_JSON"):
            with self.subTest(key=key), self.assertRaises(TelegramConfigurationError):
                TelegramConfig.from_environment({k: v for k, v in good.items() if k != key})

    def test_reject_destination_redirect_username_group_and_boolean(self):
        for chat in (-100123456789, 0, "@someone", "12345", True, 2**52):
            with self.subTest(chat=chat), self.assertRaises(TelegramConfigurationError):
                settings(bindings={RECIPIENT: chat})

    def test_reject_duplicate_binding_keys(self):
        raw = '{"' + RECIPIENT + '":123,"' + RECIPIENT + '":456}'
        with self.assertRaises(TelegramConfigurationError):
            TelegramConfig.from_environment({"TELEGRAM_DEMO_BINDINGS_JSON": raw})

    def test_reject_malformed_json_and_nonfinite_timeout_without_echo(self):
        for changes in ({"TELEGRAM_DEMO_BINDINGS_JSON": FAKE_TOKEN},
                        {"TELEGRAM_DEMO_BINDINGS_JSON": "[]"},
                        {"TELEGRAM_MAX_CALL_SECONDS": "nan"},
                        {"TELEGRAM_MAX_CALL_SECONDS": "inf"},
                        {"TELEGRAM_MAX_CALL_SECONDS": "0"},
                        {"TELEGRAM_MAX_CALL_SECONDS": "31"}):
            with self.subTest(changes=changes), self.assertRaises(TelegramConfigurationError) as caught:
                TelegramConfig.from_environment(changes)
            self.assertNotIn(FAKE_TOKEN, str(caught.exception))

    def test_config_copies_bindings_and_redacts_repr(self):
        bindings = {RECIPIENT: CHAT}
        cfg = settings(bindings=bindings)
        bindings[RECIPIENT] = 999
        self.assertEqual(cfg.bindings[RECIPIENT], CHAT)
        with self.assertRaises(TypeError):
            cfg.bindings[OTHER] = CHAT
        for value in (FAKE_TOKEN, RECIPIENT, str(CHAT)):
            self.assertNotIn(value, repr(cfg))

    def test_token_cannot_change_url_or_exist_in_dry_run(self):
        for token in (FAKE_TOKEN + "/redirect", FAKE_TOKEN + "\n", "https://evil.invalid"):
            with self.subTest(token=token), self.assertRaises(TelegramConfigurationError):
                settings(token=token)
        with self.assertRaises(TelegramConfigurationError):
            settings(mode="dry_run")


class TelegramAdapterTests(unittest.TestCase):
    def build(self, result=None, **config_changes):
        self.now = 100.0
        fake = FakeTransport(result)
        return TelegramAdapter(settings(**config_changes), transport=fake,
                               monotonic_clock=lambda: self.now), fake

    def test_accepted_only_means_api_and_has_sanitized_receipt(self):
        adapter, fake = self.build()
        out = adapter.send(notice())
        self.assertEqual(out.state, "accepted")
        self.assertEqual(out.receipt, "telegram:42")
        self.assertEqual(out.code, "TELEGRAM_API_ACCEPTED")
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(adapter.max_call_seconds, 10)
        self.assertNotIn("delivered", repr(out))
        self.assertNotIn(str(CHAT), repr(out))

    def test_static_ru_payload_ignores_extra_personal_fields(self):
        adapter, fake = self.build()
        adapter.send(notice(order_number="REAL EMPLOYEE SECRET", report="PRIVATE REPORT", photo="https://private"))
        payload = fake.calls[0]["payload"]
        self.assertIn("Синтетические данные", payload["text"])
        self.assertIn(ORDER, payload["text"])
        self.assertNotIn("SECRET", payload["text"])
        self.assertNotIn("PRIVATE", payload["text"])
        self.assertNotIn("https://", payload["text"])
        self.assertNotIn("parse_mode", payload)
        self.assertFalse(payload["allow_paid_broadcast"])
        self.assertFalse(payload["disable_notification"])
        self.assertTrue(payload["protect_content"])
        self.assertEqual(payload["chat_id"], CHAT)
        self.assertLess(len(payload["text"]), 4096)

    def test_actual_worker_envelope_and_nontelegram_channel(self):
        adapter, fake = self.build()
        envelope = DeliveryEnvelope(JOB, ORDER, RECIPIENT, "new_order")
        self.assertEqual(adapter.send(envelope).state, "accepted")
        adapter, fake = self.build()
        out = adapter.send(DeliveryEnvelope(JOB, ORDER, RECIPIENT, "new_order", channel="synthetic"))
        self.assertEqual(out.code, "TELEGRAM_INVALID_DEMO_NOTICE")
        self.assertEqual(fake.calls, [])

    def test_unknown_recipient_fails_closed_without_request(self):
        adapter, fake = self.build()
        out = adapter.send(notice(recipient_id=OTHER))
        self.assertEqual(out.code, "TELEGRAM_RECIPIENT_NOT_ALLOWLISTED")
        self.assertEqual(fake.calls, [])

    def test_invalid_kind_and_ids_fail_without_request_or_echo(self):
        for changes in ({"kind": "free text " + FAKE_TOKEN}, {"job_id": "not UUID"},
                        {"order_id": "personal text"}, {"recipient_id": None}):
            adapter, fake = self.build()
            with self.subTest(changes=changes):
                out = adapter.send(notice(**changes))
                self.assertEqual(out.code, "TELEGRAM_INVALID_DEMO_NOTICE")
                self.assertEqual(fake.calls, [])
                self.assertNotIn(FAKE_TOKEN, repr(out))

    def test_all_committed_job_kinds_supported(self):
        for kind in KINDS:
            adapter, fake = self.build()
            self.assertEqual(adapter.send(notice(kind=kind)).state, "accepted")

    def test_dry_run_never_sends_or_claims_acceptance(self):
        adapter, fake = self.build(mode="dry_run", token="")
        out = adapter.send(notice())
        self.assertEqual(out.code, "TELEGRAM_DRY_RUN")
        self.assertEqual(out.state, "permanent_failure")
        self.assertIsNone(out.receipt)
        self.assertEqual(fake.calls, [])

    def test_unspecified_synthetic_demo_fails_dry_run(self):
        adapter, fake = self.build(mode="dry_run", token="", synthetic_demo=False)
        self.assertEqual(adapter.send(notice()).code, "TELEGRAM_INVALID_DEMO_NOTICE")
        self.assertEqual(fake.calls, [])

    def test_one_per_second_global_guard(self):
        adapter, fake = self.build(bindings={RECIPIENT: CHAT, OTHER: CHAT + 1})
        self.assertEqual(adapter.send(notice()).state, "accepted")
        out = adapter.send(notice(recipient_id=OTHER))
        self.assertEqual(out.code, "TELEGRAM_LOCAL_RATE_LIMIT")
        self.assertEqual(out.retry_after_seconds, 1)
        self.assertEqual(len(fake.calls), 1)
        self.now += 1
        fake.result = accepted(chat=CHAT + 1)
        self.assertEqual(adapter.send(notice(recipient_id=OTHER)).state, "accepted")

    def test_explicit_429_honors_provider_delay_and_holds_other_recipients(self):
        adapter, fake = self.build(rejected(429, retry_after=73), bindings={RECIPIENT: CHAT, OTHER: CHAT + 1})
        out = adapter.send(notice())
        self.assertEqual((out.state, out.retry_after_seconds), ("retryable", 73))
        self.now += 2
        held = adapter.send(notice(recipient_id=OTHER))
        self.assertEqual(held.retry_after_seconds, 71)
        self.assertEqual(len(fake.calls), 1)

    def test_429_without_delay_uses_sixty_seconds(self):
        adapter, _ = self.build(rejected(429))
        self.assertEqual(adapter.send(notice()).retry_after_seconds, 60)

    def test_invalid_retry_delays_fail_closed_never_shortened(self):
        for delay in (0, -1, True, 1.1, "100", 604801):
            adapter, _ = self.build(rejected(429, retry_after=delay))
            self.assertEqual(adapter.send(notice()).code, "TELEGRAM_INVALID_RETRY_AFTER")

    def test_auth_recipient_and_request_errors_are_permanent(self):
        for code in (400, 401, 403, 404):
            adapter, _ = self.build(rejected(code))
            out = adapter.send(notice())
            self.assertEqual(out.state, "permanent_failure")
            self.assertNotIn(FAKE_TOKEN, repr(out))

    def test_migrated_chat_not_automatically_followed(self):
        adapter, fake = self.build(rejected(400, migrate_to_chat_id=-10056789))
        self.assertEqual(adapter.send(notice()).code, "TELEGRAM_CHAT_REBIND_REQUIRED")
        self.assertEqual(len(fake.calls), 1)

    def test_explicit_server_rejection_is_retryable_but_html_500_ambiguous(self):
        adapter, _ = self.build(rejected(503))
        self.assertEqual(adapter.send(notice()).state, "retryable")
        adapter, _ = self.build(TransportResult("response", 503, None))
        self.assertEqual(adapter.send(notice()).state, "ambiguous")

    def test_transport_exception_and_unknown_response_are_ambiguous(self):
        for result in (TimeoutError(FAKE_TOKEN), TransportResult("ambiguous"),
                       TransportResult("response", 200, {"ok": True}),
                       TransportResult("response", 302, {"ok": True}),
                       TransportResult("response", 200, {"ok": 1}),
                       TransportResult("response", 200, {"ok": False, "error_code": True}),
                       TransportResult("response", 503, {"ok": False, "error_code": 429}),
                       "unexpected"):
            adapter, fake = self.build(result)
            with self.subTest(result=repr(result)):
                out = adapter.send(notice())
                self.assertEqual(out.state, "ambiguous")
                self.assertEqual(len(fake.calls), 1)
                self.assertNotIn(FAKE_TOKEN, repr(out))

    def test_validated_not_sent_or_busy_is_retryable(self):
        for phase in ("not_sent", "busy"):
            adapter, _ = self.build(TransportResult(phase))
            out = adapter.send(notice())
            self.assertEqual(out.state, "retryable")
            self.assertEqual(out.retry_after_seconds, 2)

    def test_receipt_requires_private_bound_chat_and_integer_id(self):
        variants = [accepted(chat=CHAT + 1), accepted(message_id=0), accepted(message_id=True), accepted(message_id=2**52)]
        for mutation in ({"id": CHAT, "type": "group"}, {"id": str(CHAT), "type": "private"}):
            variants.append(TransportResult("response", 200, {"ok": True,
                "result": {"message_id": 42, "chat": mutation}}))
        for result in variants:
            adapter, _ = self.build(result)
            self.assertEqual(adapter.send(notice()).code, "TELEGRAM_INVALID_RECEIPT")

    def test_no_stdout_or_stderr_for_success_or_secret_exception(self):
        stdout, stderr = StringIO(), StringIO()
        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            adapter, _ = self.build()
            adapter.send(notice())
            adapter, _ = self.build(RuntimeError(FAKE_TOKEN + str(CHAT)))
            adapter.send(notice())
        self.assertEqual(stdout.getvalue() + stderr.getvalue(), "")


class FakeConnection:
    def __init__(self, *, error_at=None, body=None, status=200, connect_release=None, read_release=None):
        self.error_at = error_at
        self.body = body if body is not None else json.dumps(accepted().body).encode()
        self.status = status
        self.connect_release, self.read_release = connect_release, read_release
        self.sock = SimpleNamespace(settimeout=lambda seconds: None)
        self.requests = []
        self.closed = threading.Event()

    def connect(self):
        if self.connect_release:
            self.connect_release.wait(2)
        if self.error_at == "connect":
            raise OSError(FAKE_TOKEN)

    def request(self, *args, **kwargs):
        self.requests.append((args, kwargs))
        if self.error_at == "request":
            raise TimeoutError(FAKE_TOKEN)

    def getresponse(self):
        if self.error_at == "response":
            raise TimeoutError(FAKE_TOKEN)
        return self

    def read(self, limit):
        if self.read_release:
            self.read_release.wait(2)
        return self.body[:limit]

    def close(self):
        self.closed.set()


class TelegramTransportTests(unittest.TestCase):
    def call(self, connection, timeout=0.5, transport=None):
        with patch("app.notifications.telegram.http.client.HTTPSConnection", return_value=connection) as create:
            result = (transport or TelegramHttpsTransport()).send_message(token=FAKE_TOKEN,
                payload={"chat_id": CHAT, "text": "synthetic"}, max_call_seconds=timeout)
        return result, create

    def test_official_https_post_and_verified_tls_context(self):
        connection = FakeConnection()
        result, create = self.call(connection)
        self.assertEqual(result.phase, "response")
        self.assertEqual(create.call_args.args, ("api.telegram.org", 443))
        context = create.call_args.kwargs["context"]
        self.assertTrue(context.check_hostname)
        import ssl
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        args, kwargs = connection.requests[0]
        self.assertEqual(args, ("POST", "/bot" + FAKE_TOKEN + "/sendMessage"))
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")
        self.assertTrue(connection.closed.is_set())
        self.assertNotIn(FAKE_TOKEN, repr(result))

    def test_failure_before_connect_is_definitely_not_sent(self):
        connection = FakeConnection(error_at="connect")
        result, _ = self.call(connection)
        self.assertEqual(result.phase, "not_sent")
        self.assertEqual(connection.requests, [])

    def test_request_and_response_failure_are_ambiguous(self):
        for phase in ("request", "response"):
            result, _ = self.call(FakeConnection(error_at=phase))
            self.assertEqual(result.phase, "ambiguous")

    def test_redirect_is_not_followed(self):
        connection = FakeConnection(status=302, body=b"{}")
        result, create = self.call(connection)
        self.assertEqual(result.status, 302)
        self.assertEqual(create.call_count, 1)
        self.assertEqual(len(connection.requests), 1)

    def test_oversize_and_invalid_json_do_not_escape(self):
        for body in (b"x" * 65537, b"not JSON " + FAKE_TOKEN.encode()):
            result, _ = self.call(FakeConnection(body=body))
            self.assertIn(result.phase, {"ambiguous", "response"})
            self.assertIsNone(result.body)
            self.assertNotIn(FAKE_TOKEN, repr(result))

    def test_total_budget_bounds_wait_and_late_connect_never_sends(self):
        release = threading.Event()
        connection = FakeConnection(connect_release=release)
        transport = TelegramHttpsTransport()
        before = time.monotonic()
        try:
            result, _ = self.call(connection, timeout=0.1, transport=transport)
            self.assertEqual(result.phase, "ambiguous")
            self.assertLess(time.monotonic() - before, 0.8)
            busy = transport.send_message(token=FAKE_TOKEN, payload={}, max_call_seconds=0.1)
            self.assertEqual(busy.phase, "busy")
        finally:
            release.set()
            self.assertTrue(connection.closed.wait(1))
        self.assertEqual(connection.requests, [])

    def test_late_response_cannot_be_reported_as_success_after_timeout(self):
        release = threading.Event()
        connection = FakeConnection(read_release=release)
        transport = TelegramHttpsTransport()
        try:
            result, _ = self.call(connection, timeout=0.1, transport=transport)
            self.assertEqual(result.phase, "ambiguous")
            self.assertEqual(len(connection.requests), 1)
        finally:
            release.set()
            self.assertTrue(connection.closed.wait(1))
        self.assertEqual(result.phase, "ambiguous")


if __name__ == "__main__":
    unittest.main()
