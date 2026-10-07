"""Four independent real-PG race probes, locally NOT_RUN without PostgreSQL.

Uses author fixture setup only. The two attachment races delay actual cursor
consumption to interleave real domain attachment, never fabricate row contents.
The other two require an observed PostgreSQL lock wait before advancing state.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
import time
import unittest
from unittest.mock import patch

import test_photos_postgres as author_suite
import test_persistence_postgres as fixtures

from app.core.auth_boundary import AuthenticationRequired
from app.core.auth_policy import AccessDenied


class PhotoRacePostgresTests(author_suite.PhotoPostgresTests):
    def intercept_first_photo_discovery(self, photo_id):
        original = self.service._connection
        observed = {"attachments": 0, "discoveries": 0}
        owner = self
        class Connection:
            def __init__(self, db):
                self.db = db
            def __getattr__(self, name):
                return getattr(self.db, name)
            def __enter__(self):
                self.db.__enter__()
                return self
            def __exit__(self, *args):
                return self.db.__exit__(*args)
            def execute(self, query, params=()):
                cursor = self.db.execute(query, params)
                if " ".join(query.split()) != "SELECT order_id FROM photos WHERE id=%s":
                    return cursor
                observed["discoveries"] += 1
                class Cursor:
                    def fetchone(self):
                        row = cursor.fetchone()
                        if observed["attachments"] == 0:
                            observed["attachments"] += 1
                            owner.fixture.create([photo_id])
                        return row
                return Cursor()
        return patch.object(self.service, "_connection", side_effect=lambda: Connection(original())), observed

    def wait_for_lock(self, get_pid):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            pid = get_pid()
            if pid is not None:
                rows = self.query("SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s", (pid,))
                if rows and rows[0]["wait_event_type"] == "Lock":
                    return
            time.sleep(0.02)
        self.fail("The intended real PostgreSQL lock wait was not observed")

    def test_get_restarts_after_real_before_attachment_between_discovery_and_lock(self):
        photo = self.upload().body["id"]
        interception, observed = self.intercept_first_photo_discovery(photo)
        with interception, patch.object(self.store, "get", wraps=self.store.get) as storage_read:
            self.assertTrue(self.get(photo)[0])
        self.assertEqual(observed["attachments"], 1)
        self.assertGreaterEqual(observed["discoveries"], 2)
        storage_read.assert_called_once()
        self.assertIsNotNone(self.query("SELECT attached_at FROM photos WHERE id=%s", (photo,))[0]["attached_at"])
        self.assertEqual(len(list(self.root.glob("*.img"))), 1)

    def test_receipt_replay_restarts_attachment_race_without_republishing(self):
        form = self.form()
        original = self.upload(form)
        interception, observed = self.intercept_first_photo_discovery(original.body["id"])
        with interception, patch.object(self.store, "put", wraps=self.store.put) as publish:
            replay = self.upload(form)
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.body, original.body)
        self.assertGreaterEqual(observed["discoveries"], 2)
        publish.assert_not_called()
        self.assertEqual(len(list(self.root.glob("*.img"))), 1)

    def test_get_expired_while_blocked_on_photo_never_reads_blob(self):
        photo = self.upload().body["id"]
        original = self.service._connection
        pids = []
        def connection():
            db = original()
            pids.append(db.info.backend_pid)
            return db
        with self.fixture.connect() as blocker:
            with patch.object(self.service, "_connection", side_effect=connection), \
                 patch.object(self.store, "get", wraps=self.store.get) as storage_read, \
                 ThreadPoolExecutor(max_workers=1) as pool:
                with blocker.transaction():
                    blocker.execute("SELECT id FROM photos WHERE id=%s FOR UPDATE", (photo,))
                    future = pool.submit(self.get, photo)
                    self.wait_for_lock(lambda: pids[-1] if pids else None)
                    self.fixture.real.value += timedelta(days=6)
                with self.assertRaises(AuthenticationRequired):
                    future.result(timeout=10)
                storage_read.assert_not_called()

    def test_after_upload_waiting_on_order_rechecks_committed_assignment(self):
        order = self.fixture.start()
        form = self.form(purpose="after", order_id=order, assignment_revision="1")
        original = self.service._connection
        pids = []
        def connection():
            db = original()
            pids.append(db.info.backend_pid)
            return db
        with self.fixture.connect() as blocker:
            with patch.object(self.service, "_connection", side_effect=connection), \
                 patch.object(self.store, "put", wraps=self.store.put) as publish, \
                 ThreadPoolExecutor(max_workers=1) as pool:
                with blocker.transaction():
                    blocker.execute("SELECT id FROM orders WHERE id=%s FOR UPDATE", (order,))
                    future = pool.submit(self.upload, form, None, fixtures.EXECUTOR)
                    self.wait_for_lock(lambda: pids[-1] if pids else None)
                    # Owner-only fixture mutation models a committed concurrent
                    # assignment change; this is not a lifecycle/history test.
                    blocker.execute("""UPDATE orders SET executor_id=%s,assignment_revision=assignment_revision+1,
                                       version=version+1 WHERE id=%s""", (fixtures.OTHER, order))
                with self.assertRaises(AccessDenied):
                    future.result(timeout=10)
                publish.assert_not_called()
        self.assertEqual(self.query("SELECT * FROM photos"), [])
        self.assertEqual(self.query("SELECT * FROM operation_receipts WHERE operation_id=%s", (form["operation_id"],)), [])


def load_tests(loader, standard_tests, pattern):
    names = sorted(name for name in PhotoRacePostgresTests.__dict__ if name.startswith("test_"))
    return unittest.TestSuite(PhotoRacePostgresTests(name) for name in names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
