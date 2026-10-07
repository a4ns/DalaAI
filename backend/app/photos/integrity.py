"""Storage integrity of already decoded evidence, never scene authenticity.

Inject this callable into the host's closure-evidence adapter. It does not change
file_valid or any row. A pre-existing unknown/invalid flag can never be upgraded
by merely matching bytes or a hash. The command owner holds order/photo locks.
"""
from hashlib import sha256
import re

from .validation import MAX_BYTES, PhotoUnavailable


def _trusted_metadata(photo):
    return (photo.get("file_valid") is True
        and type(photo.get("bytes")) is int and 0 < photo["bytes"] <= MAX_BYTES
        and photo.get("mime_type") in {"image/jpeg", "image/png", "image/webp"}
        and isinstance(photo.get("sha256"), str)
        and re.fullmatch(r"[a-f0-9]{64}", photo["sha256"]) is not None
        and isinstance(photo.get("storage_key"), str))


class PhotoIntegrityVerifier:
    """Callable(db_photo_mapping) -> bool; storage outage raises PhotoUnavailable.

    Required keys: file_valid, storage_key, bytes, sha256, mime_type. False means
    unknown/invalid evidence or a known length/hash mismatch; block CLOSE with
    its existing mandatory-evidence error. Missing/unavailable/private-store
    errors raise PhotoUnavailable; host returns generic retryable HTTP 503.

    Rows must be server-loaded and locked by the command adapter. Run this for
    every required attached photo immediately before the human-close gate, using
    the SAME durable store used by PhotoService. Never default to allow when this
    verifier is absent. GET and this verifier have no database side effects.
    """
    def __init__(self, private_blob_store):
        self.store = private_blob_store

    def _load(self, photo):
        try:
            data = self.store.get(photo["storage_key"])
        except OSError:
            raise PhotoUnavailable() from None
        if type(data) is not bytes or len(data) > MAX_BYTES:
            raise PhotoUnavailable()
        return data

    @staticmethod
    def _matches(photo, data):
        return len(data) == photo["bytes"] and sha256(data).hexdigest() == photo["sha256"]

    def __call__(self, photo):
        if not _trusted_metadata(photo):
            return False
        return self._matches(photo, self._load(photo))

    def read(self, photo):
        """GET path: return bounded verified bytes or fail closed, no flag writes."""
        if not _trusted_metadata(photo):
            raise PhotoUnavailable()
        data = self._load(photo)
        if not self._matches(photo, data):
            raise PhotoUnavailable()
        return data
