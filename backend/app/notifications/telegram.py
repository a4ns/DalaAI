"""Opt-in Telegram Bot API adapter for an allowlisted synthetic demo.

Only the durable delivery worker may call send(). Telegram sendMessage has no
idempotency key: a timeout after dispatch is ambiguous, NOT retryable. The worker
owns durable deduplication and the dispatch fence. Provider acceptance does not
prove a notification was displayed, sounded, or read on a phone.
"""
from dataclasses import dataclass, field
import http.client
import json
import math
import os
from queue import Empty, Queue
import re
import ssl
from threading import Lock, Thread
from time import monotonic
from types import MappingProxyType
from typing import Mapping
from uuid import UUID

from app.notify.models import DeliveryEnvelope, DeliveryOutcome


KINDS = MappingProxyType({
    "new_order": "Вам выдан новый наряд",
    "deadline_reminder": "Приближается срок наряда",
    "overdue": "Срок наряда истёк",
    "acceptance_escalation": "Наряд ещё не принят исполнителем",
    "manager_escalation": "Наряд требует внимания руководителя",
    "submission_ready": "Результат наряда ожидает проверки мастера",
    "review_result": "Мастер принял решение по результату наряда",
})
_TOKEN = re.compile(r"[1-9][0-9]{4,19}:[A-Za-z0-9_-]{20,128}\Z")
_MAX_RESPONSE_BYTES = 65536
_MAX_RETRY_SECONDS = 7 * 24 * 60 * 60


class TelegramConfigurationError(ValueError):
    """Static errors only: never include settings, tokens, or recipient values."""


def _canonical_uuid(value):
    try:
        valid = type(value) is str and str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise TelegramConfigurationError("TELEGRAM_INVALID_IDENTIFIER") from None
    return value


@dataclass(frozen=True, slots=True)
class TelegramConfig:
    """Trusted host settings, never an HTTP request body or checked-in secret.

    Enabling live mode asserts that the owner approved the token's use and each
    employee-to-private-chat binding for synthetic notifications. It does not
    create such permission. The host must collect it before configuring these.
    """
    mode: str = "disabled"
    synthetic_demo: bool = False
    token: str = field(default="", repr=False)
    bindings: Mapping[str, int] = field(default_factory=dict, repr=False)
    max_call_seconds: float = 10.0

    def __post_init__(self):
        if self.mode not in {"disabled", "dry_run", "live"}:
            raise TelegramConfigurationError("TELEGRAM_INVALID_MODE")
        if type(self.synthetic_demo) is not bool:
            raise TelegramConfigurationError("TELEGRAM_INVALID_DEMO_SCOPE")
        if (type(self.max_call_seconds) not in {int, float}
                or not math.isfinite(self.max_call_seconds)
                or not 0 < self.max_call_seconds <= 30):
            raise TelegramConfigurationError("TELEGRAM_INVALID_TIMEOUT")
        if not isinstance(self.bindings, Mapping) or len(self.bindings) > 100:
            raise TelegramConfigurationError("TELEGRAM_INVALID_BINDINGS")
        copied = {}
        for recipient, chat in self.bindings.items():
            _canonical_uuid(recipient)
            # P0 deliberately supports only private chats, never @usernames,
            # groups/channels, negative IDs, or automatic migrated destinations.
            if type(chat) is not int or not 0 < chat < 2**52:
                raise TelegramConfigurationError("TELEGRAM_INVALID_PRIVATE_CHAT")
            copied[recipient] = chat
        object.__setattr__(self, "bindings", MappingProxyType(copied))
        if self.mode == "live":
            if (not self.synthetic_demo or not copied or type(self.token) is not str
                    or not _TOKEN.fullmatch(self.token)):
                raise TelegramConfigurationError("TELEGRAM_LIVE_CONFIG_INCOMPLETE")
        elif self.token:
            # Dry runs must not unnecessarily load a live credential.
            raise TelegramConfigurationError("TELEGRAM_TOKEN_ONLY_FOR_LIVE_MODE")

    @classmethod
    def from_environment(cls, environment=None):
        """Read only named settings; disabled mode does not read the token."""
        env = os.environ if environment is None else environment
        mode = env.get("TELEGRAM_MODE", "disabled")
        try:
            raw = env.get("TELEGRAM_DEMO_BINDINGS_JSON", "{}")
            if type(raw) is not str or len(raw) > 16384:
                raise ValueError()
            # Reject duplicate keys; silently replacing an approved binding is
            # unsafe and makes configuration review misleading.
            def pairs(items):
                result = {}
                for key, value in items:
                    if key in result:
                        raise ValueError()
                    result[key] = value
                return result
            bindings = json.loads(raw, object_pairs_hook=pairs)
            timeout = float(env.get("TELEGRAM_MAX_CALL_SECONDS", "10"))
            return cls(mode=mode,
                synthetic_demo=env.get("TELEGRAM_SYNTHETIC_DEMO", "0") == "1",
                token=env.get("TELEGRAM_BOT_TOKEN", "") if mode == "live" else "",
                bindings=bindings, max_call_seconds=timeout)
        except (ValueError, TypeError, RecursionError):
            raise TelegramConfigurationError("TELEGRAM_INVALID_ENVIRONMENT") from None


@dataclass(frozen=True, slots=True)
class TransportResult:
    """Private transport data; no raw body or provider error in repr/logs."""
    phase: str  # response | not_sent | ambiguous | busy
    status: int | None = None
    body: object = field(default=None, repr=False)


class TelegramHttpsTransport:
    """HTTPS POST only to api.telegram.org, normal certificate verification.

    No proxy override, configurable URL, redirects, retries, telemetry, webhook,
    getUpdates, or credential storage. A bounded wait covers DNS as well as TLS,
    response headers and body. If the OS call outlives the budget, the result is
    ambiguous and a still-active call blocks another transport call. A late DNS
    result may not start a request after the deadline. An already-started remote
    request cannot be undone, and the caller must never automatically retry it.
    """
    def __init__(self):
        self._active = Lock()

    def send_message(self, *, token, payload, max_call_seconds):
        if not self._active.acquire(blocking=False):
            return TransportResult("busy")
        reply = Queue(maxsize=1)
        deadline = monotonic() + max_call_seconds

        def invoke():
            connection = None
            dispatched = False
            result = TransportResult("ambiguous")
            try:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    result = TransportResult("not_sent")
                    return
                # Construct the token-bearing path only here; never stringify
                # exceptions, request/connection objects, payloads or responses.
                connection = http.client.HTTPSConnection("api.telegram.org", 443,
                    timeout=remaining, context=ssl.create_default_context())
                connection.connect()
                remaining = deadline - monotonic()
                if remaining <= 0:
                    result = TransportResult("not_sent")
                    return
                connection.sock.settimeout(remaining)
                body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                remaining = deadline - monotonic()
                if remaining <= 0:
                    result = TransportResult("not_sent")
                    return
                connection.sock.settimeout(remaining)
                dispatched = True
                connection.request("POST", "/bot" + token + "/sendMessage", body=body,
                    headers={"Content-Type": "application/json", "Accept": "application/json"})
                response = connection.getresponse()
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
                if len(raw) > _MAX_RESPONSE_BYTES:
                    return
                try:
                    parsed = json.loads(raw)
                except (ValueError, UnicodeError, RecursionError):
                    parsed = None
                result = TransportResult("response", response.status, parsed)
            except Exception:
                result = TransportResult("ambiguous" if dispatched else "not_sent")
            finally:
                if connection is not None:
                    try:
                        connection.close()
                    except Exception:
                        pass
                reply.put_nowait(result)
                self._active.release()

        try:
            thread = Thread(target=invoke, name="telegram-dispatch", daemon=True)
            thread.start()
        except Exception:
            self._active.release()
            return TransportResult("not_sent")
        try:
            return reply.get(timeout=max(0, deadline - monotonic()))
        except Empty:
            return TransportResult("ambiguous")


class TelegramAdapter:
    """One adapter instance and one worker lane per bot for the demo.

    Conservative local throttling permits at most one request per second across
    all bound private chats. The durable worker persists job retries/receipts;
    this in-process guard is NOT a multi-process/durable rate-limit guarantee.
    """
    channel = "telegram"

    def __init__(self, config=None, *, transport=None, monotonic_clock=monotonic):
        self._config = config or TelegramConfig()
        if not isinstance(self._config, TelegramConfig):
            raise TelegramConfigurationError("TELEGRAM_TYPED_CONFIG_REQUIRED")
        self._transport = transport or TelegramHttpsTransport()
        self._clock = monotonic_clock
        self._lock = Lock()
        self._next_call = 0.0
        self.max_call_seconds = self._config.max_call_seconds

    def send(self, envelope: DeliveryEnvelope) -> DeliveryOutcome:
        """No sleep/retry loop. Outcomes contain only fixed codes and receipt."""
        if self._config.mode == "disabled":
            return DeliveryOutcome("permanent_failure", code="TELEGRAM_DISABLED")
        try:
            for name in ("job_id", "order_id", "recipient_id"):
                _canonical_uuid(getattr(envelope, name, None))
            kind = getattr(envelope, "kind", None)
            if getattr(envelope, "channel", None) != "telegram":
                raise ValueError()
            if type(kind) is not str or kind not in KINDS:
                raise ValueError()
            if not self._config.synthetic_demo:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            return DeliveryOutcome("permanent_failure", code="TELEGRAM_INVALID_DEMO_NOTICE")
        chat = self._config.bindings.get(envelope.recipient_id)
        if chat is None:
            return DeliveryOutcome("permanent_failure", code="TELEGRAM_RECIPIENT_NOT_ALLOWLISTED")
        if self._config.mode == "dry_run":
            # Never report accepted: the queue must not mark a dry run as sent.
            return DeliveryOutcome("permanent_failure", code="TELEGRAM_DRY_RUN")
        with self._lock:
            remaining = self._next_call - self._clock()
            if remaining > 0:
                return DeliveryOutcome("retryable", code="TELEGRAM_LOCAL_RATE_LIMIT",
                                       retry_after_seconds=max(1, math.ceil(remaining)))
            self._next_call = self._clock() + 1.0
        payload = {
            "chat_id": chat,
            "text": ("ДЕМО · Синтетические данные\nНарядAI: " + KINDS[kind]
                     + "\nНаряд: " + envelope.order_id
                     + "\nОткройте НарядAI, чтобы посмотреть актуальное состояние."),
            "disable_notification": False,
            "protect_content": True,
            "allow_paid_broadcast": False,
            "link_preview_options": {"is_disabled": True},
        }
        try:
            response = self._transport.send_message(token=self._config.token,
                payload=payload, max_call_seconds=self.max_call_seconds)
        except Exception:
            # An injected transport throwing gives no proof that bytes weren't
            # sent. Do not leak its exception and do not blindly retry.
            return DeliveryOutcome("ambiguous", code="TELEGRAM_OUTCOME_UNKNOWN")
        return self._classify(response, chat)

    def _classify(self, response, expected_chat):
        if not isinstance(response, TransportResult):
            return DeliveryOutcome("ambiguous", code="TELEGRAM_INVALID_RESPONSE")
        if response.phase in {"not_sent", "busy"}:
            return DeliveryOutcome("retryable", code=("TELEGRAM_NOT_SENT"
                if response.phase == "not_sent" else "TELEGRAM_TRANSPORT_BUSY"), retry_after_seconds=2)
        if response.phase != "response":
            return DeliveryOutcome("ambiguous", code="TELEGRAM_OUTCOME_UNKNOWN")
        body, status = response.body, response.status
        if type(status) is not int or not isinstance(body, dict):
            return DeliveryOutcome("ambiguous", code="TELEGRAM_INVALID_RESPONSE")
        if body.get("ok") is True and 200 <= status < 300:
            result = body.get("result")
            if isinstance(result, dict):
                message_id, chat = result.get("message_id"), result.get("chat")
                if (type(message_id) is int and 0 < message_id < 2**52
                        and isinstance(chat, dict) and type(chat.get("id")) is int
                        and chat["id"] == expected_chat and chat.get("type") == "private"):
                    return DeliveryOutcome("accepted", code="TELEGRAM_API_ACCEPTED", receipt="telegram:" + str(message_id))
            return DeliveryOutcome("ambiguous", code="TELEGRAM_INVALID_RECEIPT")
        if body.get("ok") is not False or type(body.get("error_code")) is not int:
            return DeliveryOutcome("ambiguous", code="TELEGRAM_INVALID_RESPONSE")
        error = body["error_code"]
        # Never follow HTTP redirects or provider migrate_to_chat_id: a different
        # destination requires a separately approved binding.
        params = body.get("parameters")
        if isinstance(params, dict) and "migrate_to_chat_id" in params:
            return DeliveryOutcome("permanent_failure", code="TELEGRAM_CHAT_REBIND_REQUIRED")
        if error == 429 and status in {200, 429}:
            delay = params.get("retry_after", 60) if isinstance(params, dict) else 60
            if type(delay) is not int or not 1 <= delay <= _MAX_RETRY_SECONDS:
                return DeliveryOutcome("permanent_failure", code="TELEGRAM_INVALID_RETRY_AFTER")
            with self._lock:
                self._next_call = max(self._next_call, self._clock() + delay)
            return DeliveryOutcome("retryable", code="TELEGRAM_RATE_LIMIT", retry_after_seconds=delay)
        if error in {400, 401, 403, 404} and status in {200, error}:
            code = {400: "TELEGRAM_REQUEST_REJECTED", 401: "TELEGRAM_AUTH_REJECTED",
                    403: "TELEGRAM_RECIPIENT_UNAVAILABLE", 404: "TELEGRAM_NOT_FOUND"}[error]
            return DeliveryOutcome("permanent_failure", code=code)
        if 500 <= error <= 599 and status in {200, error}:
            return DeliveryOutcome("retryable", code="TELEGRAM_SERVER_REJECTED", retry_after_seconds=2)
        return DeliveryOutcome("ambiguous", code="TELEGRAM_UNCLASSIFIED_RESPONSE")
