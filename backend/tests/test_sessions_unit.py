"""Synthetic local policy, parser and real Argon2id library tests."""
from datetime import datetime, timezone
import importlib.util
import json
import unittest
from unittest.mock import Mock

from app.core.auth_policy import AccessDenied
from app.orders.models import DomainError
from app.sessions.crypto import Argon2idVerifier, DUMMY_HASH
from app.sessions.limiter import LimitPolicy, bucket, real_now
from app.sessions.service import (IssuedSession, SessionService, parse_login,
                                  source_identity, validate_handle)
from app.core.auth_boundary import AuthenticationRequired


class SessionPolicyTests(unittest.TestCase):
    def test_strict_login_fields(self):
        self.assertEqual(parse_login(b'{"employee_code":"E1","pin":"1234"}'), ("E1", "1234"))
        for value in ({"employee_code":"E1","pin":"1234","role":"admin"},
                      {"employee_code":"E1","pin":1234}, {"employee_code":"","pin":"1234"},
                      {"employee_code":"E1","pin":"123"}, {"employee_code":"E1","pin":"p"*65},
                      {"employee_code":"E"*41,"pin":"1234"}, [], None,
                      {"employee_code":"E1","pin":"a\u0000bc"},
                      {"employee_code":"E1","pin":"\ud800abc"}):
            with self.subTest(value=repr(value)), self.assertRaises(DomainError):
                parse_login(json.dumps(value))

    def test_ambiguous_json_rejected(self):
        for raw in (b'{"employee_code":"E1","pin":"1234","pin":"9999"}', b'{', b'NaN'):
            with self.subTest(raw=raw), self.assertRaises(DomainError):
                parse_login(raw)

    def test_values_are_not_normalized(self):
        self.assertEqual(parse_login('{"employee_code":" E1 ","pin":" 1234 "}'), (" E1 ", " 1234 "))

    def test_transport_source_and_ipv6_group(self):
        self.assertEqual(source_identity("127.0.0.1"), "127.0.0.1")
        self.assertEqual(source_identity("::ffff:127.0.0.1"), "127.0.0.1")
        self.assertEqual(source_identity("2001:db8::aaaa"), source_identity("2001:db8::bbbb"))
        for value in (None, "unknown", "127.0.0.1, 8.8.8.8"):
            with self.assertRaises(DomainError):
                source_identity(value)

    def test_handles_bounded_unicode_safe(self):
        for value in (None, "", "a"*513, "\ud800"):
            with self.assertRaises(AuthenticationRequired):
                validate_handle(value)

    def test_bucket_storage_is_bounded(self):
        values = [bucket(str(n)) for n in range(1000)]
        self.assertTrue(all(0 <= key < 65536 for key in values))
        self.assertEqual(bucket("employee"), bucket("employee"))

    def test_policy_invalid_and_real_clock(self):
        for kwargs in ({"account_attempts":0}, {"source_attempts":True}, {"window_seconds":86401}):
            with self.assertRaises(ValueError):
                LimitPolicy(**kwargs)
        clock = Mock()
        clock.now.return_value = datetime(2026, 10, 7)
        with self.assertRaises(ValueError):
            real_now(clock)

    def test_demo_disabled_and_origin_rejected_before_attempt(self):
        limiter, verifier, connect = Mock(), Mock(), Mock()
        service = SessionService(connect, allowed_origin="https://test.example", verifier=verifier, limiter=limiter)
        for origin in ("https://test.example", "https://evil.example", None):
            with self.assertRaises(AccessDenied):
                service.login(b'{}', origin=origin, source_key="127.0.0.1")
        limiter.consume.assert_not_called()
        verifier.verify.assert_not_called()
        connect.assert_not_called()

    def test_session_repr_never_contains_tokens(self):
        issued = IssuedSession({"csrf_token":"sensitive-csrf"}, "sensitive-handle", 123)
        self.assertNotIn("sensitive", repr(issued))

    def test_config_rejects_unbounded_ttl_and_nonboolean_demo(self):
        for kwargs in ({"session_ttl_seconds":0}, {"session_ttl_seconds":86401}, {"demo_enabled":"true"}):
            with self.assertRaises(ValueError):
                SessionService(Mock(), allowed_origin="https://test.example", verifier=Mock(), **kwargs)


@unittest.skipUnless(importlib.util.find_spec("argon2"), "NOT_RUN: argon2-cffi is not installed")
class Argon2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.verifier = Argon2idVerifier()
        cls.encoded = cls.verifier.hasher.hash("synthetic-only-pin")

    def test_real_argon2id_match_and_mismatch(self):
        self.assertTrue(self.verifier.verify("synthetic-only-pin", self.encoded))
        self.assertFalse(self.verifier.verify("different-only-pin", self.encoded))

    def test_unknown_invalid_and_dummy_never_authenticate(self):
        for encoded in ("", "not-a-hash", "$argon2id$broken", "a"*257):
            with self.subTest(encoded=encoded[:20]):
                self.assertFalse(self.verifier.verify("correct horse battery staple", encoded))

    def test_cheaper_hash_refused(self):
        from argon2 import PasswordHasher
        from argon2.profiles import CHEAPEST
        encoded = PasswordHasher.from_parameters(CHEAPEST).hash("synthetic-only-pin")
        self.assertFalse(self.verifier.verify("synthetic-only-pin", encoded))

    def test_unknown_and_malformed_use_same_real_dummy_work(self):
        from unittest.mock import patch
        with patch.object(self.verifier, "hasher", wraps=self.verifier.hasher) as hasher:
            self.verifier.verify("bad-synthetic-pin", "")
            hasher.verify.assert_called_once_with(DUMMY_HASH, "bad-synthetic-pin")

    def test_malformed_digest_and_nonascii_perform_dummy_not_500(self):
        from unittest.mock import patch
        for suffix in ("я" * 43, "!" * 43):
            encoded = DUMMY_HASH.rsplit("$", 1)[0] + "$" + suffix
            with self.subTest(suffix=suffix[:1]):
                with patch.object(self.verifier, "hasher", wraps=self.verifier.hasher) as hasher:
                    self.assertFalse(self.verifier.verify("1234", encoded))
                    self.assertEqual(hasher.verify.call_count, 2)
                    self.assertEqual(hasher.verify.call_args.args, (DUMMY_HASH, "1234"))

    def test_hash_capacity_fails_fast_and_recovers(self):
        from app.sessions.crypto import _HASH_SLOTS, HashCapacityUnavailable
        self.assertTrue(_HASH_SLOTS.acquire(blocking=False))
        self.assertTrue(_HASH_SLOTS.acquire(blocking=False))
        try:
            with self.assertRaises(HashCapacityUnavailable):
                self.verifier.verify("1234", "")
        finally:
            _HASH_SLOTS.release()
            _HASH_SLOTS.release()
        self.assertFalse(self.verifier.verify("1234", ""))


if __name__ == "__main__":
    unittest.main()
