"""Library cryptography and pinned, no-redirect HTTPS under a hard process bound.

No sockets or keys at import. Production caller must opt in and authorize a real
send. Tests inject a fake sender or pool; they cannot establish phone delivery.
"""
from dataclasses import dataclass
from hashlib import sha256
import logging
import multiprocessing
import time
from urllib.parse import urlsplit

from .validation import endpoint_parts, public_addresses


@dataclass(frozen=True)
class TransportResult:
    status: int | None = None
    retry_after: str | None = None
    receipt: str | None = None
    code: str = 'PUSH_OUTCOME_UNKNOWN'


class PinnedSession:
    """Minimal Requests session surface consumed by pywebpush, no proxy lookup.

    Both DNS policy and numeric-IP connect happen within the bounded child. TLS
    SNI/certificate/Host use the reviewed original provider name. No retries,
    redirects, response bodies, endpoint logs, or ambient proxy credentials.
    """
    def __init__(self, endpoint, *, resolver=None, pool_factory=None):
        import socket
        import urllib3
        self.parsed = endpoint_parts(endpoint)
        self.endpoint = endpoint
        self.resolver = resolver or socket.getaddrinfo
        self.pool_factory = pool_factory or urllib3.HTTPSConnectionPool

    def post(self, url, *, data, headers, timeout, **kwargs):
        import certifi
        import requests
        import urllib3
        if url != self.endpoint or kwargs:
            raise ValueError('Unexpected push transport request')
        address = public_addresses(self.parsed.hostname,resolver=self.resolver)[0]
        pool = self.pool_factory(address,port=443,server_hostname=self.parsed.hostname,
            assert_hostname=self.parsed.hostname,cert_reqs='CERT_REQUIRED',ca_certs=certifi.where(),
            maxsize=1,block=True)
        # Never allow an upstream header to select another destination.
        outgoing = dict(headers)
        outgoing['Host'] = self.parsed.hostname
        response = None
        try:
            response = pool.urlopen('POST',self.parsed.path,body=data,headers=outgoing,
                timeout=urllib3.Timeout(total=min(float(timeout),8),connect=3,read=5),
                retries=False,redirect=False,preload_content=False,assert_same_host=False)
            result = requests.Response()
            result.status_code = int(response.status)
            result.reason = 'Web Push response'
            result._content = b''  # Provider error bodies often echo capability URLs.
            result.headers.update({key:str(value)[:2048] for key,value in response.headers.items()
                                   if key.lower() in {'retry-after','location'}})
            return result
        finally:
            if response is not None:
                response.close()
            pool.close()


def send_library(subscription, payload, settings, *, session=None):
    from pywebpush import webpush, WebPushException
    try:
        response = webpush(subscription_info=subscription.wire(),data=payload,
            vapid_private_key=settings.private_key,vapid_claims={'sub':settings.subject},
            content_encoding='aes128gcm',ttl=settings.ttl_seconds,timeout=8,
            headers={'Urgency':'normal'},verbose=False,
            requests_session=session or PinnedSession(subscription.endpoint))
    except WebPushException as error:
        response = error.response
        if response is None:
            return TransportResult()
    status = response.status_code
    location = response.headers.get('Location', '')
    # Opaque audit evidence of observed HTTP acceptance, not a delivery receipt.
    receipt = 'webpush:' + sha256((str(status)+'\n'+location).encode()).hexdigest()
    return TransportResult(status,response.headers.get('Retry-After'),receipt,'PUSH_HTTP_RESPONSE')


def _child(pipe, subscription, payload, settings):
    # Third-party debug output could contain secrets/capability URLs. Keep the
    # isolated sender silent regardless of application's logging configuration.
    logging.disable(logging.CRITICAL)
    try:
        result = send_library(subscription,payload,settings)
    except Exception:
        result = TransportResult()
    try:
        pipe.send(result)
    finally:
        pipe.close()


class BoundedSender:
    max_call_seconds = 12.0

    def send(self, subscription, payload, settings):
        # spawn avoids inheriting open database/socket state into the sender.
        context = multiprocessing.get_context('spawn')
        parent, child = context.Pipe(duplex=False)
        process = context.Process(target=_child,args=(child,subscription,payload,settings),daemon=True)
        started = time.monotonic()
        try:
            process.start()
            child.close()
            remaining = max(0,self.max_call_seconds-1-(time.monotonic()-started))
            if parent.poll(remaining):
                result = parent.recv()
                if isinstance(result,TransportResult):
                    return result
            return TransportResult()
        except Exception:
            return TransportResult()
        finally:
            parent.close()
            child.close()
            if process.pid is not None:
                if process.is_alive():
                    process.kill()
                process.join(timeout=0.5)
                if not process.is_alive():
                    process.close()
