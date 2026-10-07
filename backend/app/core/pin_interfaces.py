"""Integration requirements only. This module implements NO login or PIN crypto."""
from dataclasses import dataclass
from typing import Protocol


class PinHashVerifier(Protocol):
    def verify(self, pin: str, encoded_hash: str) -> bool:
        """Reviewed password-hashing library only; no direct plaintext comparison.

        Select and pin a supported Argon2id implementation through A5. Handle
        invalid stored hashes generically. Do equivalent dummy-hash work for an
        unknown account. Never log PINs, hashes or request bodies.
        """
        ...


@dataclass(frozen=True)
class AttemptDecision:
    allowed: bool
    retry_after_seconds: int


class PinAttemptLimiter(Protocol):
    def consume(self, *, account_key: str, source_key: str) -> AttemptDecision:
        """Atomically consume BEFORE hash work for BOTH account and source keys.

        Shared durable/central storage for multiple workers; real clock only.
        Bound state cardinality, do not reset on success, fail closed on storage
        outage. Derive source from a trusted proxy config, not arbitrary headers.
        Return generic 429 and Retry-After independent of account existence.
        """
        ...
