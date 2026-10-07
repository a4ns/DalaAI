"""Argon2id only, fixed reviewed profile, generic failure, equivalent dummy work."""
from threading import BoundedSemaphore

# RFC low-memory is 64MiB per verification. Share this cap across all verifier
# instances in one process; configure process count/memory budget at deployment.
_HASH_SLOTS = BoundedSemaphore(2)


class HashCapacityUnavailable(Exception):
    def __init__(self):
        super().__init__("Authentication temporarily unavailable")


# This public synthetic dummy is not an account credential. It deliberately has
# the exact profile used by permitted account hashes. Unknown/invalid accounts
# still perform a complete password verification; they can never authenticate.
DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$MIIRqgvgQbgj220jfp0MPA$YfwJSVjtjSU0zzV/P3S9nnQ/USre2wvJMjfCIjrTQbg"


class Argon2idVerifier:
    def __init__(self):
        from argon2 import PasswordHasher, extract_parameters
        from argon2.profiles import RFC_9106_LOW_MEMORY
        from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
        self.hasher = PasswordHasher.from_parameters(RFC_9106_LOW_MEMORY)
        self.parameters = RFC_9106_LOW_MEMORY
        self.extract = extract_parameters
        self.invalid = InvalidHashError
        self.verification_error = VerificationError
        self.mismatch = VerifyMismatchError

    def verify(self, pin: str, encoded_hash: str) -> bool:
        if not _HASH_SLOTS.acquire(blocking=False):
            raise HashCapacityUnavailable()
        try:
            return self._verify(pin, encoded_hash)
        finally:
            _HASH_SLOTS.release()

    def _verify(self, pin: str, encoded_hash: str) -> bool:
        # Bound parsing and hash work. Do not accept Argon2i/d or silently cheap
        # profiles. Future profile migrations need a reviewed explicit allowlist.
        supported = False
        if isinstance(encoded_hash, str) and len(encoded_hash) <= 256:
            try:
                supported = self.extract(encoded_hash) == self.parameters
            except (self.invalid, ValueError, TypeError):
                pass
        if not supported:
            return self._dummy(pin)
        try:
            return bool(self.hasher.verify(encoded_hash, pin))
        except self.mismatch:
            return False  # Normal mismatch already performed full Argon2 work.
        except (self.invalid, self.verification_error, UnicodeError):
            # Parameter extraction does not validate encoded salt/hash bytes.
            # Malformed stored base64/non-ASCII may fail before expensive work.
            return self._dummy(pin)

    def _dummy(self, pin):
        try:
            self.hasher.verify(DUMMY_HASH, pin)
        except (self.invalid, self.verification_error, UnicodeError):
            pass
        return False  # Even matching the public dummy can never authenticate.
