"""Authorization/integrity/lock-order unit probes; not real PostgreSQL tests."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.core.auth_boundary import AuthContext, AuthenticationRequired, SessionRecord
from app.core.auth_policy import AccessDenied, OrderScope, Principal, Role
from app.orders.models import DomainError
from app.photos.integrity import PhotoIntegrityVerifier
from app.photos.service import PhotoService, _BindingChanged
from app.photos.storage import PrivateFileStore
from app.photos.validation import MAX_BYTES, PhotoUnavailable, decode_raster
from test_photos_unit import image_bytes, SECTION, OPERATION, ORDER

NOW = datetime(2026, 10, 7, 17, tzinfo=timezone.utc)
OWNER = "00000000-0000-4000-8000-000000000011"
OTHER = "00000000-0000-4000-8000-000000000012"


def context(role=Role.MASTER, owner=OWNER, sections=None):
    return AuthContext(Principal(owner, role, frozenset(sections or [SECTION])),
        SessionRecord(owner, NOW - timedelta(hours=1), NOW + timedelta(hours=1), "synthetic-csrf"))


def photo(**updates):
    return {"id": OPERATION, "section_id": SECTION, "owner_id": OWNER, "purpose": "before",
        "order_id": None, "assignment_revision": None, "submission_id": None, "attached_at": None,
        "expires_at": NOW + timedelta(hours=24), "file_valid": True, **updates}


class PhotoPolicyTests(unittest.TestCase):
    def setUp(self):
        self.clock = SimpleNamespace(now=lambda: NOW)
        self.service = PhotoService(lambda: None, allowed_origin="https://photo.test",
            private_blob_store=Mock(), real_clock=self.clock)

    def test_staged_before_owner_role_section_and_ttl(self):
        self.service._authorize_photo(context(), photo(), None)
        for actor in [context(Role.EXECUTOR), context(Role.ADMIN), context(Role.MANAGER),
                      context(owner=OTHER), context(sections=[OTHER])]:
            with self.assertRaises(AccessDenied):
                self.service._authorize_photo(actor, photo(expires_at=NOW), None)
        with self.assertRaises(DomainError) as error:
            self.service._authorize_photo(context(), photo(expires_at=NOW), None)
        self.assertEqual(error.exception.code, "PHOTO_EXPIRED")

    def test_staged_after_current_assignment_before_expiry_error(self):
        order = OrderScope(ORDER, SECTION, OWNER, 1)
        record = photo(purpose="after", order_id=ORDER, assignment_revision=1)
        self.service._authorize_photo(context(Role.EXECUTOR), record, order)
        for actor, current in [(context(Role.MASTER), order), (context(Role.EXECUTOR), OrderScope(ORDER, SECTION, OTHER, 2)),
                               (context(Role.EXECUTOR), OrderScope(ORDER, SECTION, OWNER, 2))]:
            with self.assertRaises(AccessDenied):
                self.service._authorize_photo(actor, {**record, "expires_at": NOW}, current)

    def test_attached_photo_current_order_scope_and_no_staging_ttl(self):
        order = OrderScope(ORDER, SECTION, OTHER, 2)
        record = photo(purpose="after", order_id=ORDER, assignment_revision=1,
                       attached_at=NOW, expires_at=NOW - timedelta(days=1))
        for actor in (context(), context(Role.MANAGER), context(Role.EXECUTOR, owner=OTHER)):
            self.service._authorize_photo(actor, record, order)
        for actor in (context(Role.ADMIN), context(Role.EXECUTOR), context(sections=[OTHER])):
            with self.assertRaises(AccessDenied):
                self.service._authorize_photo(actor, record, order)

    def test_unknown_or_false_validity_refused(self):
        for value in (None, False, "true", 1):
            with self.assertRaises(DomainError):
                self.service._authorize_photo(context(), photo(file_valid=value), None)

    def test_session_expiry_rechecked_after_membership_wait(self):
        auth = context()
        self.clock.now = lambda: auth.session.expires_at
        with patch("app.photos.service.authenticate_session", return_value=auth), self.assertRaises(AuthenticationRequired):
            self.service._auth(Mock(), "synthetic-session")

    def test_read_locks_order_before_photo(self):
        db = Mock()
        record = photo(order_id=ORDER, attached_at=NOW)
        db.execute.side_effect = [Mock(fetchone=lambda: {"order_id": ORDER}),
            Mock(fetchone=lambda: {"id": ORDER, "section_id": SECTION, "executor_id": OWNER, "assignment_revision": 1}),
            Mock(fetchone=lambda: record)]
        result, order = self.service._read_locked(db, OPERATION)
        sql = [call.args[0] for call in db.execute.call_args_list]
        self.assertNotIn("FOR SHARE", sql[0])
        self.assertIn("FROM orders", sql[1])
        self.assertIn("FOR SHARE", sql[1])
        self.assertIn("FROM photos", sql[2])
        self.assertIn("FOR SHARE", sql[2])
        self.assertEqual(order.order_id, ORDER)
        self.assertEqual(result, record)

    def test_binding_change_releases_transaction_for_retry(self):
        db = Mock()
        db.execute.side_effect = [Mock(fetchone=lambda: {"order_id": None}),
                                 Mock(fetchone=lambda: photo(order_id=ORDER, attached_at=NOW))]
        with self.assertRaises(_BindingChanged):
            self.service._read_locked(db, OPERATION)
        self.assertEqual(len(db.execute.call_args_list), 2)
        self.assertTrue(all("FROM orders" not in c.args[0] for c in db.execute.call_args_list))


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = PrivateFileStore(Path(self.temp.name))
        raster = decode_raster(image_bytes())
        self.data = raster.data
        self.key = self.store.put(self.data)
        self.record = {"file_valid": True, "storage_key": self.key, "bytes": len(self.data),
                       "sha256": raster.sha256, "mime_type": raster.mime_type}
        self.verifier = PhotoIntegrityVerifier(self.store)

    def test_exact_sanitized_integrity_and_read(self):
        original = dict(self.record)
        self.assertIs(self.verifier(self.record), True)
        self.assertEqual(self.verifier.read(self.record), self.data)
        self.assertEqual(self.record, original)

    def test_unknown_flag_or_metadata_never_upgraded_by_hash(self):
        updates = [{"file_valid": flag} for flag in (None, False, 1, "true")]
        updates += [{"bytes": 0}, {"bytes": MAX_BYTES + 1}, {"bytes": True},
                    {"sha256": "bad"}, {"mime_type": "text/html"}, {"storage_key": None}]
        with patch.object(self.store, "get") as get:
            for delta in updates:
                self.assertIs(self.verifier({**self.record, **delta}), False)
            get.assert_not_called()

    def test_known_mismatch_is_invalid_not_unavailable(self):
        for delta in ({"sha256": "0" * 64}, {"bytes": len(self.data) + 1}):
            self.assertIs(self.verifier({**self.record, **delta}), False)
        path = Path(self.temp.name) / self.key
        path.write_bytes(b"corrupted")
        self.assertIs(self.verifier(self.record), False)
        with self.assertRaises(PhotoUnavailable):
            self.verifier.read(self.record)

    def test_missing_and_unavailable_store_raise_retryable_failure(self):
        (Path(self.temp.name) / self.key).unlink()
        with self.assertRaises(PhotoUnavailable):
            self.verifier(self.record)
        with patch.object(self.store, "get", side_effect=OSError("sensitive filesystem detail")):
            with self.assertRaises(PhotoUnavailable) as error:
                self.verifier(self.record)
            self.assertNotIn("sensitive", str(error.exception))

    def test_oversize_or_untrusted_store_result_never_passes(self):
        for value in (b"x" * (MAX_BYTES + 1), "not bytes", bytearray(self.data)):
            with patch.object(self.store, "get", return_value=value), self.assertRaises(PhotoUnavailable):
                self.verifier(self.record)


if __name__ == "__main__":
    unittest.main()
