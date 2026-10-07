"""Closed provider policy and strict browser subscription validation."""
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import ipaddress
import json
import math
import re
import socket
from urllib.parse import urlsplit

from app.orders.models import DomainError

# Exact hosts, never suffix matching or request-controlled configuration. Android
# Chrome/Firefox first. Additional providers require code/security review.
PROVIDERS = {
    'fcm.googleapis.com': ('/fcm/send/', '/wp/'),
    'updates.push.services.mozilla.com': ('/wpush/v1/', '/wpush/v2/', '/push/v1/'),
}


def invalid():
    return DomainError('VALIDATION_FAILED', 'Invalid Web Push subscription')


def endpoint_parts(endpoint):
    if (not isinstance(endpoint, str) or not 1 <= len(endpoint) <= 2048
            or not endpoint.isascii() or any(ord(c) <= 32 or ord(c) >= 127 for c in endpoint)):
        raise invalid()
    try:
        parsed = urlsplit(endpoint)
        host = parsed.hostname
        if (parsed.scheme != 'https' or host not in PROVIDERS or parsed.netloc != host
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or '?' in endpoint or '#' in endpoint):
            raise invalid()
        prefix = next((p for p in PROVIDERS[host] if parsed.path.startswith(p)), None)
        if prefix is None or re.fullmatch(r'[A-Za-z0-9_:-]{8,1900}', parsed.path[len(prefix):]) is None:
            raise invalid()
        return parsed
    except (ValueError, UnicodeError):
        raise invalid() from None


def public_addresses(host, *, resolver=socket.getaddrinfo):
    """Resolve once. Reject the ENTIRE answer if any address is non-global.

    Caller connects to the returned numeric address with original TLS hostname,
    preventing a second lookup / DNS-rebinding gap. Run under wall-clock bound.
    """
    if host not in PROVIDERS:
        raise invalid()
    records = resolver(host, 443, type=socket.SOCK_STREAM)
    addresses = []
    for family, _, _, _, address in records:
        ip = ipaddress.ip_address(address[0])
        if (family not in (socket.AF_INET, socket.AF_INET6) or not ip.is_global
                or ip.is_multicast or ip.is_unspecified or ip.is_loopback
                or ip.is_link_local or ip.is_reserved or getattr(ip, 'ipv4_mapped', None) is not None):
            raise invalid()
        addresses.append(str(ip))
    if not addresses:
        raise invalid()
    return tuple(dict.fromkeys(addresses))


def decode_key(value, size):
    if not isinstance(value, str) or re.fullmatch(r'[A-Za-z0-9_-]+', value) is None:
        raise invalid()
    if len(value) > 100:
        raise invalid()
    try:
        raw = urlsafe_b64decode(value + '=' * (-len(value) % 4))
    except (ValueError, TypeError):
        raise invalid() from None
    if len(raw) != size or urlsafe_b64encode(raw).decode().rstrip('=') != value:
        raise invalid()
    return raw


@dataclass(frozen=True)
class SubscriptionInput:
    endpoint: str = field(repr=False)
    p256dh: str = field(repr=False)
    auth: str = field(repr=False)
    expires_at: datetime | None = None

    @property
    def endpoint_hash(self):
        return sha256(self.endpoint.encode()).hexdigest()

    def wire(self):
        return {'endpoint': self.endpoint, 'keys': {'p256dh': self.p256dh, 'auth': self.auth}}


def strict_json(body):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise invalid()
            result[key] = value
        return result
    try:
        if not isinstance(body, bytes) or len(body) > 4096:
            raise invalid()
        value = json.loads(body, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(invalid()))
        if not isinstance(value, dict):
            raise invalid()
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise invalid() from None


def parse_subscription(body, *, now):
    from cryptography.hazmat.primitives.asymmetric import ec
    value = strict_json(body)
    if set(value) not in ({'endpoint', 'keys'}, {'endpoint', 'keys', 'expirationTime'}):
        raise invalid()
    endpoint_parts(value['endpoint'])
    keys = value['keys']
    if not isinstance(keys, dict) or set(keys) != {'p256dh', 'auth'}:
        raise invalid()
    public = decode_key(keys['p256dh'], 65)
    try:
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public)
    except ValueError:
        raise invalid() from None
    decode_key(keys['auth'], 16)
    expiry = value.get('expirationTime')
    expires_at = None
    if expiry is not None:
        if type(expiry) not in (int, float) or not math.isfinite(expiry) or not 0 < expiry < 253402300799000:
            raise invalid()
        expires_at = datetime.fromtimestamp(expiry / 1000, tz=timezone.utc)
        if expires_at <= now:
            raise invalid()
    return SubscriptionInput(value['endpoint'], keys['p256dh'], keys['auth'], expires_at)


def parse_removal(body):
    value = strict_json(body)
    if set(value) != {'endpoint'}:
        raise invalid()
    endpoint_parts(value['endpoint'])
    return sha256(value['endpoint'].encode()).hexdigest()
