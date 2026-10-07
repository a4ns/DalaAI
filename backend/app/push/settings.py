"""Explicit configuration only. No automatic key generation or network access."""
from dataclasses import dataclass, field
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from .validation import decode_key


@dataclass(frozen=True)
class PushSettings:
    enabled: bool = False
    public_key: str = ''
    private_key: str = field(default='', repr=False)
    subject: str = field(default='', repr=False)
    ttl_seconds: int = 60

    def __post_init__(self):
        if type(self.enabled) is not bool or type(self.ttl_seconds) is not int or not 0 <= self.ttl_seconds <= 300:
            raise ValueError('Invalid Web Push settings')
        if self.enabled:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import ec
            from base64 import urlsafe_b64encode
            try:
                public = decode_key(self.public_key, 65)
                ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public)
                raw = decode_key(self.private_key, 32)
                key = ec.derive_private_key(int.from_bytes(raw, 'big'), ec.SECP256R1())
                actual = key.public_key().public_bytes(serialization.Encoding.X962,
                                                      serialization.PublicFormat.UncompressedPoint)
                if actual != public:
                    raise ValueError()
                if (not isinstance(self.subject,str) or not self.subject.isascii()
                        or any(ord(c)<=32 or ord(c)>=127 for c in self.subject)):
                    raise ValueError()
                parsed = urlsplit(self.subject)
                if not (parsed.scheme == 'mailto' and re.fullmatch(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}', parsed.path)
                        and not parsed.query and not parsed.fragment and len(self.subject) <= 254):
                    raise ValueError()
            except Exception:
                raise ValueError('Invalid Web Push VAPID configuration') from None

    @classmethod
    def from_env(cls):
        flag = os.environ.get('DALA_WEB_PUSH_ENABLED', 'false')
        if flag not in ('true', 'false'):
            raise ValueError('DALA_WEB_PUSH_ENABLED must be true or false')
        return cls(enabled=flag == 'true',
                   public_key=os.environ.get('DALA_VAPID_PUBLIC_KEY', ''),
                   private_key=os.environ.get('DALA_VAPID_PRIVATE_KEY', ''),
                   subject=os.environ.get('DALA_VAPID_SUBJECT', ''))

    def public_config(self):
        return {'enabled': self.enabled,
                'application_server_key': self.public_key if self.enabled else None,
                'delivery_semantics': 'provider_acceptance_is_not_device_delivery',
                'device_policy': 'latest_registration_per_user'}
