"""Real PostgreSQL + real local raster/store integration; no SQLite fallback.

Fixture reuse is setup only. Every uploaded image is generated in this test;
the production service, never a test flag, establishes its initial file_valid.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
import tempfile
from threading import Barrier
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

import test_persistence_postgres as fixtures
from app.core.auth_boundary import AuthenticationRequired, SESSION_COOKIE_NAME
from app.core.auth_policy import AccessDenied
from app.orders.models import DomainError
from app.persistence.postgres import PostgresRepository
from app.photos.http import create_photo_router
from app.photos.service import PhotoService
from app.photos.storage import PrivateFileStore
from app.photos.validation import MAX_BYTES, PhotoUnavailable, decode_raster
from test_photos_unit import image_bytes


class PhotoPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.PostgresCommandTests.setUpClass()

    def setUp(self):
        self.fixture = fixtures.PostgresCommandTests(methodName="runTest")
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = PrivateFileStore(self.root)
        self.service = self.new_service()

    def new_service(self, **kwargs):
        return PhotoService(self.fixture.connect, allowed_origin=fixtures.ORIGIN,
            private_blob_store=self.store, real_clock=self.fixture.real, **kwargs)

    def form(self, **updates):
        return {"operation_id": str(uuid4()), "expected_version": "0", "purpose": "before",
                "section_id": fixtures.SECTION, **updates}

    def upload(self, form=None, raw=None, actor=fixtures.MASTER, **kwargs):
        return self.service.stage(form or self.form(), raw or image_bytes(), session_handle=actor,
            origin=fixtures.ORIGIN, csrf_token="synthetic-csrf", **kwargs)

    def get(self, photo, actor=fixtures.MASTER):
        return self.service.get(photo, session_handle=actor)

    def query(self, sql, params=()):
        return self.fixture.query(sql, params)

    def test_real_http_stage_then_private_bytes_and_restart(self):
        app = FastAPI()
        app.include_router(create_photo_router(self.service))
        client = TestClient(app, base_url=fixtures.ORIGIN)
        headers = {"cookie": SESSION_COOKIE_NAME + "=" + fixtures.MASTER,
                   "origin": fixtures.ORIGIN, "x-csrf-token": "synthetic-csrf"}
        response = client.post("/api/v1/photos/stage", data=self.form(),
            files={"file": ("ignored.png", image_bytes(), "image/png")}, headers=headers)
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertNotIn("storage_key", body)
        row = self.query("SELECT * FROM photos")[0]
        self.assertIs(row["file_valid"], True)
        self.assertIsNone(row["attached_at"])
        self.assertEqual(row["expires_at"] - row["uploaded_at"], timedelta(hours=24))
        read = client.get("/api/v1/photos/" + body["id"], headers=headers)
        self.assertEqual(read.status_code, 200)
        self.assertEqual(read.headers["cache-control"], "private, no-store")
        self.assertEqual(read.content, self.new_service().get(body["id"], session_handle=fixtures.MASTER)[0])

    def test_retry_returns_original_photo_and_expiry_after_restart(self):
        form = self.form()
        first = self.upload(form)
        self.fixture.real.value += timedelta(hours=1)
        self.service = self.new_service()
        second = self.upload(form)
        self.assertTrue(second.replayed)
        self.assertEqual(second.body, first.body)
        self.assertEqual(len(self.query("SELECT * FROM photos")), 1)
        self.assertEqual(len(list(self.root.glob("*.img"))), 1)

    def test_same_operation_changed_raw_or_binding_conflicts(self):
        form = self.form()
        self.upload(form)
        for change, raw in [({}, image_bytes() + b"different raw bytes"),
                            ({"section_id": fixtures.SECOND_SECTION}, image_bytes())]:
            with self.assertRaises(DomainError) as error:
                self.upload({**form, **change}, raw)
            self.assertEqual(error.exception.code, "OPERATION_ID_REUSED")
        self.assertEqual(len(self.query("SELECT * FROM photos")), 1)

    def test_receipt_namespace_conflict_with_order_command(self):
        _, command = self.fixture.create()
        with self.assertRaises(DomainError) as error:
            self.upload(self.form(operation_id=command["operation_id"]))
        self.assertEqual(error.exception.code, "OPERATION_ID_REUSED")
        self.assertEqual(self.query("SELECT * FROM photos"), [])

    def test_identical_operation_race_one_publication(self):
        form = self.form()
        # Decode each real raster serially, then synchronize commits. Production
        # decode capacity remains tested separately; no fake valid flag is used.
        raster = decode_raster(image_bytes())
        barrier = Barrier(2)
        def checked_decode(*args):
            barrier.wait(timeout=10)
            return raster
        with patch("app.photos.service.decode_raster", side_effect=checked_decode), ThreadPoolExecutor(max_workers=2) as pool:
            results = [future.result(timeout=20) for future in [pool.submit(self.upload, form), pool.submit(self.upload, form)]]
        self.assertEqual(results[0].body, results[1].body)
        self.assertEqual(sorted(r.replayed for r in results), [False, True])
        self.assertEqual(len(self.query("SELECT * FROM photos")), 1)
        self.assertEqual(len(list(self.root.glob("*.img"))), 1)

    def test_before_role_section_owner_and_current_scope(self):
        for actor, form in [(fixtures.EXECUTOR, self.form()),
                            (fixtures.MASTER, self.form(section_id=str(uuid4())))]:
            with self.assertRaises(AccessDenied):
                self.upload(form, actor=actor)
        form = self.form()
        created = self.upload(form)
        with self.assertRaises(AccessDenied):
            self.get(created.body["id"], fixtures.OTHER)
        self.query("DELETE FROM employee_sections WHERE employee_id=%s RETURNING employee_id", (fixtures.MASTER,))
        with self.assertRaises(AccessDenied):
            self.get(created.body["id"])
        with self.assertRaises(AccessDenied):
            self.upload(form)

    def test_after_requires_current_executor_section_and_revision(self):
        order_id = self.fixture.start()
        form = self.form(purpose="after", order_id=order_id, assignment_revision="1")
        for actor in (fixtures.MASTER, fixtures.OTHER):
            with self.assertRaises(AccessDenied):
                self.upload(form, actor=actor)
        with self.assertRaises(AccessDenied):
            self.upload({**form, "section_id": fixtures.SECOND_SECTION}, actor=fixtures.EXECUTOR)
        with self.assertRaises(DomainError) as error:
            self.upload({**form, "assignment_revision": "2"}, actor=fixtures.EXECUTOR)
        self.assertEqual(error.exception.code, "STALE_ASSIGNMENT")
        photo = self.upload(form, actor=fixtures.EXECUTOR).body["id"]
        self.fixture.action(order_id, 3, "reassign", fixtures.MASTER,
            {"assignment": {"executor_id": fixtures.OTHER, "brigade_id": None}, "reason": "Synthetic reassignment"})
        for actor in (fixtures.EXECUTOR, fixtures.OTHER, fixtures.MASTER):
            with self.assertRaises(AccessDenied):
                self.get(photo, actor)
        with self.assertRaises(AccessDenied):
            self.upload(form, actor=fixtures.EXECUTOR)

    def test_staged_expiry_blocks_reads_replay_and_attach_no_ttl_refresh(self):
        form = self.form()
        photo = self.upload(form).body["id"]
        self.fixture.real.value += timedelta(hours=24)
        for call in (lambda: self.get(photo), lambda: self.upload(form), lambda: self.fixture.create([photo])):
            with self.assertRaises(DomainError) as error:
                call()
            self.assertEqual(error.exception.code, "PHOTO_EXPIRED")
        self.assertIsNone(self.query("SELECT attached_at FROM photos")[0]["attached_at"])
        # Logical expiry never frees retained bytes from the storage budget.
        row = self.query("SELECT * FROM photos")[0]
        self.store = PrivateFileStore(self.root, max_total_bytes=MAX_BYTES)
        self.service = self.new_service(max_outstanding_stages=1)
        (self.root / ".pending-budget-fixture").write_bytes(b"x" * (MAX_BYTES - row["bytes"]))
        with self.assertRaises(PhotoUnavailable):
            self.upload()
        self.assertEqual(len(self.query("SELECT * FROM photos")), 1)
        self.assertEqual(len(self.query("SELECT * FROM operation_receipts")), 1)
        self.assertEqual(self.query("SELECT * FROM photos")[0], row)

    def test_actual_before_attachment_and_attached_ttl_ignored(self):
        self.service = self.new_service(max_outstanding_stages=1)
        form = self.form()
        photo = self.upload(form).body["id"]
        self.fixture.create([photo])
        # Attached evidence no longer occupies a stage slot, even before expiry.
        self.upload()
        self.fixture.real.value += timedelta(days=2)
        for actor in (fixtures.MASTER, fixtures.EXECUTOR):
            self.assertTrue(self.get(photo, actor)[0])
        self.assertTrue(self.upload(form).replayed)
        with self.assertRaises(AccessDenied):
            self.get(photo, fixtures.OTHER)

    def test_after_real_content_submit_and_close(self):
        order = self.fixture.start()
        form = self.form(purpose="after", order_id=order, assignment_revision="1")
        photo = self.upload(form, actor=fixtures.EXECUTOR).body["id"]
        submitted, _ = self.fixture.submit(order, [photo])
        self.fixture.real.value += timedelta(days=2)
        self.assertTrue(self.get(photo, fixtures.MASTER)[0])
        closed, _ = self.fixture.review(order, submitted.body["submission_id"])
        self.assertEqual(closed.body["order"]["status"], "closed")

    def test_unknown_or_invalid_content_not_served_and_cannot_close(self):
        order = self.fixture.start()
        photo = self.upload(self.form(purpose="after", order_id=order, assignment_revision="1"),
                            actor=fixtures.EXECUTOR).body["id"]
        submitted, _ = self.fixture.submit(order, [photo])
        for validity in (None, False):
            # Deliberate integrity invalidation, never an upload-valid shortcut.
            self.query("UPDATE photos SET file_valid=%s WHERE id=%s RETURNING id", (validity, photo))
            with self.assertRaises(DomainError):
                self.get(photo, fixtures.MASTER)
            with self.assertRaises(DomainError) as error:
                self.fixture.review(order, submitted.body["submission_id"])
            self.assertEqual(error.exception.code, "INCOMPLETE_SUBMISSION")

    def test_missing_or_tampered_blob_never_returns_success_bytes(self):
        photo = self.upload().body["id"]
        row = self.query("SELECT * FROM photos")[0]
        path = self.root / row["storage_key"]
        path.write_bytes(b"corrupted")
        with self.assertRaises(PhotoUnavailable):
            self.get(photo)
        path.unlink()
        with self.assertRaises(PhotoUnavailable):
            self.get(photo)

    def test_invalid_file_creates_no_receipt_or_blob(self):
        with self.assertRaises(DomainError):
            self.upload(raw=b"not an actual image")
        self.assertEqual(self.query("SELECT * FROM photos"), [])
        self.assertEqual(self.query("SELECT * FROM operation_receipts"), [])
        self.assertEqual(list(self.root.glob("*.img")), [])

    def test_file_failure_rolls_back_receipt(self):
        with patch.object(self.store, "put", side_effect=PhotoUnavailable()), self.assertRaises(PhotoUnavailable):
            self.upload()
        self.assertEqual(self.query("SELECT * FROM photos"), [])
        self.assertEqual(self.query("SELECT * FROM operation_receipts"), [])

    def test_database_failure_after_publish_retains_bounded_orphan_and_retry(self):
        form = self.form()
        original = PostgresRepository.finalize_receipt
        def failed(repo, *args):
            original(repo, *args)
            raise RuntimeError("synthetic precommit failure")
        with patch.object(PostgresRepository, "finalize_receipt", failed), self.assertRaises(RuntimeError):
            self.upload(form)
        self.assertEqual(self.query("SELECT * FROM photos"), [])
        self.assertEqual(self.query("SELECT * FROM operation_receipts"), [])
        self.assertEqual(len(list(self.root.glob("*.img"))), 1)
        self.upload(form)
        self.assertEqual(len(self.query("SELECT * FROM photos")), 1)
        self.assertEqual(len(list(self.root.glob("*.img"))), 2)

    def test_lost_commit_response_keeps_content_then_replays(self):
        original_connection = self.service._connection
        target_form = self.form()
        class LostAcknowledgment:
            def __init__(self, db):
                self.db = db
            def __getattr__(self, key):
                return getattr(self.db, key)
            def __enter__(self):
                self.db.__enter__()
                return self
            def __exit__(self, *args):
                return self.db.__exit__(*args)
            @contextmanager
            def transaction(self):
                with self.db.transaction():
                    yield
                # Successful actual commit, then simulate transport ack loss.
                rows = self.db.execute("SELECT resource_id FROM operation_receipts WHERE operation_id=%s",
                                       (target_form["operation_id"],)).fetchall()
                if rows:
                    raise fixtures.PostgresCommandTests.pg.OperationalError("synthetic COMMIT acknowledgment lost")
        with patch.object(self.service, "_connection", side_effect=lambda: LostAcknowledgment(original_connection())):
            with self.assertRaises(fixtures.PostgresCommandTests.pg.OperationalError):
                self.upload(target_form)
        self.assertEqual(len(self.query("SELECT * FROM photos")), 1)
        retry = self.upload(target_form)
        self.assertTrue(retry.replayed)
        self.assertTrue(self.get(retry.body["id"])[0])
        self.assertEqual(len(list(self.root.glob("*.img"))), 1)

    def test_owner_quota_serializes_competing_new_operations(self):
        self.service = self.new_service(max_outstanding_stages=1)
        raster = decode_raster(image_bytes())
        def attempt(form):
            try:
                return self.upload(form)
            except DomainError as error:
                return error.code
        def race(expire_while_waiting=None):
            forms = [self.form(), self.form()]
            barrier = Barrier(2)
            original_connection = self.service._connection
            pids = []
            def connection():
                db = original_connection()
                pids.append(db.info.backend_pid)
                return db
            def checked_decode(*args):
                barrier.wait(timeout=10)
                return raster
            with patch.object(self.service, "_connection", side_effect=connection), \
                 patch("app.photos.service.decode_raster", side_effect=checked_decode), \
                 ThreadPoolExecutor(max_workers=2) as pool:
                # Release the real lock before joining the workers, even when
                # an assertion fails, so the test cannot strand its own uploads.
                with self.fixture.connect() as blocker, blocker.transaction():
                    if expire_while_waiting is not None:
                        quota_key = int.from_bytes(sha256(("photo-quota:" + fixtures.MASTER).encode()).digest()[:8], "big", signed=True)
                        blocker.execute("SELECT pg_advisory_xact_lock(%s)", (quota_key,))
                    futures = [pool.submit(attempt, form) for form in forms]
                    if expire_while_waiting is not None:
                        deadline = time.monotonic() + 8
                        while time.monotonic() < deadline:
                            waiting = self.query("""SELECT count(*) AS n FROM pg_stat_activity
                                WHERE pid=ANY(%s) AND wait_event_type='Lock' AND wait_event='advisory'""", (list(pids),))[0]["n"]
                            if waiting == 2:
                                break
                            time.sleep(0.02)
                        else:
                            self.fail("Both uploads must reach a real PostgreSQL owner-quota lock wait")
                        self.fixture.real.value = expire_while_waiting
                results = [future.result(timeout=20) for future in futures]
            self.assertCountEqual([r if isinstance(r, str) else r.status for r in results], [201, "RATE_LIMITED"])
            winner = next(i for i, result in enumerate(results) if not isinstance(result, str))
            return forms[winner], results[winner]

        form, first = race()
        original = self.query("SELECT * FROM photos")[0]
        receipt = self.query("SELECT * FROM operation_receipts")[0]
        stored = self.store.get(original["storage_key"])
        self.fixture.real.value = original["expires_at"] - timedelta(microseconds=1)
        self.assertEqual(attempt(self.form()), "RATE_LIMITED")
        replay = self.upload(form)
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.body, first.body)

        # Exactly at expiry, old evidence is unusable and releases the slot.
        # A restart plus competing new operations still permits only one stage.
        self.service = self.new_service(max_outstanding_stages=1)
        _, fresh = race(expire_while_waiting=original["expires_at"])
        self.assertNotEqual(fresh.body["id"], first.body["id"])
        self.assertEqual(attempt(self.form()), "RATE_LIMITED")
        self.assertEqual(attempt(form), "PHOTO_EXPIRED")
        self.assertEqual(self.query("SELECT * FROM photos WHERE id=%s", (first.body["id"],))[0], original)
        self.assertEqual(self.query("SELECT * FROM operation_receipts WHERE operation_id=%s", (form["operation_id"],))[0], receipt)
        self.assertEqual(self.store.get(original["storage_key"]), stored)
        self.assertEqual(len(self.query("SELECT * FROM photos")), 2)
        self.assertEqual(len(self.query("SELECT * FROM operation_receipts")), 2)
        self.assertEqual(len(list(self.root.glob("*.img"))), 2)

    def test_expiry_after_storage_wait_rolls_back_and_keeps_blob(self):
        original = self.store.put
        def late(data):
            key = original(data)
            self.fixture.real.value += timedelta(days=6)
            return key
        with patch.object(self.store, "put", side_effect=late), self.assertRaises(AuthenticationRequired):
            self.upload()
        self.assertEqual(self.query("SELECT * FROM photos"), [])
        self.assertEqual(self.query("SELECT * FROM operation_receipts"), [])
        self.assertEqual(len(list(self.root.glob("*.img"))), 1)

    def test_read_expiry_after_storage_wait_refuses_bytes(self):
        photo = self.upload().body["id"]
        original = self.store.get
        def late(key):
            data = original(key)
            self.fixture.real.value += timedelta(days=6)
            return data
        with patch.object(self.store, "get", side_effect=late), self.assertRaises(AuthenticationRequired):
            self.get(photo)

    def test_session_revocation_on_stage_retry_and_retrieval(self):
        form = self.form()
        photo = self.upload(form).body["id"]
        self.query("UPDATE auth_sessions SET revoked_at=%s WHERE employee_id=%s RETURNING id",
                   (fixtures.NOW, fixtures.MASTER))
        for call in (lambda: self.upload(form), lambda: self.get(photo)):
            with self.assertRaises(AuthenticationRequired):
                call()


if __name__ == "__main__":
    unittest.main()
