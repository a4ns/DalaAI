"""Explicit OpenAI demo wiring. Importing this file makes no calls or key reads.

The owner enables from an existing authorized runtime secret, after approved
synthetic manifests and one shared durable ledger are ready. No credential is
created, saved, copied or returned by this module. No deployment is performed.
"""
import os
from datetime import datetime, timezone

from .model_adapter import ModelSettings, TransportResponse
from .model_budget import BudgetPolicy

OPENAI_ENDPOINT = 'https://api.openai.com/v1/chat/completions'
OPENAI_SNAPSHOT = 'gpt-4.1-mini-2025-04-14'
# Official model context ceiling 1,047,576 input tokens, $0.40/M input,
# max 400 output tokens at $1.60/M output. Reserve ceil upper bound $0.42.
# This intentionally uses the ENTIRE context ceiling, not an unverified tokenizer
# estimate or image-token estimate. No tools, retries or premium service tier.
PER_CALL_UPPER_BOUND_MICROUSD = 420_000
NIGHT_ENDS_AT=datetime(2026,10,8,4,0,tzinfo=timezone.utc)
DEFAULT_DEMO_POLICY_EXPIRES_AT=datetime(2026,10,8,18,59,tzinfo=timezone.utc)


def openai_demo_settings(*, timeout_seconds=8.0):
    return ModelSettings('openai', OPENAI_ENDPOINT, OPENAI_SNAPSHOT, OPENAI_SNAPSHOT,
                         timeout_seconds=timeout_seconds, max_completion_tokens=400)


def openai_demo_budget(*, period_id='2026-10-07-night'):
    """$50 lifetime; <=$10 for starts before Oct8 09:00 UTC+5 (04:00Z).

    Reserve by real request-start time; after the cutoff only the SAME global
    $50 cap remains. No rows/reservations reset. Closure/vision/future reports
    share this approval ID and one persistent ledger across all processes.
    """
    return BudgetPolicy('dalaai-openai-demo', 50_000_000, PER_CALL_UPPER_BOUND_MICROUSD,
                        calls_per_minute=5, max_concurrent=1,
                        period_id=period_id, period_microusd=10_000_000,period_ends_at=NIGHT_ENDS_AT.timestamp())


class OpenAIHTTPTransport:
    """httpx async transport; optional runtime dependency, no SDK retries.

    The existing backend already locks httpx for tests. Hosting owner must make
    the same pinned package an approved runtime dependency before live enable.
    trust_env=False prevents accidental proxy/NETRC credential routing; SSL
    verification is on, redirects are off, endpoint is an exact constant.
    """
    __slots__ = ('_key',)

    def __init__(self, key):
        if not isinstance(key, str) or not key or len(key) > 4096 or any(c.isspace() for c in key):
            raise ValueError('OPENAI_KEY_UNAVAILABLE')
        self._key = key

    def __repr__(self):
        return '<OpenAIHTTPTransport credential=redacted>'

    @classmethod
    def from_env(cls):
        return cls(os.environ.get('OPENAI_API_KEY', ''))

    async def post_json(self, *, endpoint, body, timeout_seconds, max_response_bytes):
        if endpoint != OPENAI_ENDPOINT or body.get('model') != OPENAI_SNAPSHOT:
            raise ValueError('OPENAI_DESTINATION_OR_MODEL_DENIED')
        # Keep the cost guarantee tied to the exact reviewed request profile.
        if (body.get('max_completion_tokens') != 400 or body.get('stream') is not False
                or body.get('store') is not False or 'tools' in body or 'service_tier' in body
                or 'n' in body or 'prediction' in body):
            raise ValueError('OPENAI_REQUEST_PROFILE_DENIED')
        import httpx
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=False,
                                     trust_env=False, verify=True) as client:
            async with client.stream('POST', endpoint, json=body,
                headers={'Authorization': 'Bearer ' + self._key,
                         'Content-Type': 'application/json', 'Accept': 'application/json',
                         'Accept-Encoding': 'identity'}) as response:
                # No exception with raw provider body/key is persisted or logged.
                if response.status_code != 200:
                    return TransportResponse(response.status_code, b'')
                if response.headers.get('content-encoding', 'identity').lower() != 'identity':
                    raise ValueError('OPENAI_ENCODED_RESPONSE_DENIED')
                chunks, count = [], 0
                async for chunk in response.aiter_raw():
                    count += len(chunk)
                    if count > max_response_bytes:
                        raise ValueError('OPENAI_RESPONSE_TOO_LARGE')
                    chunks.append(chunk)
                return TransportResponse(response.status_code, b''.join(chunks))
