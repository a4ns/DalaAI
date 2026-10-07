"""REAL PostgreSQL proofs, only with an explicitly disposable operator test DSN.

Two independent spawned processes exercise one state row. DSN absence is NOT_RUN.
No accounts/credentials or app data are created; only a unique synthetic schema.
"""
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
import multiprocessing
import os
from pathlib import Path
import unittest
from uuid import uuid4

from app.demo_clock.clock import DemoClockSettings
from app.demo_clock.postgres import PostgresDemoBusinessClock
from app.orders.models import DomainError

FLAGS = DemoClockSettings(enabled=True, mode="demo", isolated_demo=True)
ACTOR = "00000000-0000-0000-0000-000000000001"


def connect_for(dsn, schema, *, read_only=False):
    import psycopg
    return psycopg.connect(dsn, autocommit=True,
        options=f"-c search_path={schema} -c default_transaction_read_only={'on' if read_only else 'off'}")


def run_process(dsn, schema, instance_id, command=None):
    clock = PostgresDemoBusinessClock(lambda: connect_for(dsn, schema), settings=FLAGS, instance_id=instance_id)
    try:
        snap = clock.capture() if command is None else clock.apply(command, authorize=lambda: ACTOR)
        return {"result": "OK", **snap.wire()}
    except DomainError as error:
        return {"result": error.code}


class PostgresClockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.environ.get("DALA_TEST_DATABASE_URL")
        if not cls.dsn or os.environ.get("DALA_DEMO_CLOCK_TEST_DISPOSABLE") != "true":
            raise unittest.SkipTest("NOT_RUN: explicit disposable PostgreSQL DSN + DALA_DEMO_CLOCK_TEST_DISPOSABLE=true required")
        import psycopg
        from psycopg import sql
        cls.pg, cls.sql = psycopg, sql

    def setUp(self):
        self.schema = "demo_clock_test_" + uuid4().hex
        self.instance_id = str(uuid4())
        with self.pg.connect(self.dsn, autocommit=True) as db:
            db.execute(self.sql.SQL("CREATE SCHEMA {}").format(self.sql.Identifier(self.schema)))
        self.addCleanup(self.drop_schema)
        with self.connect() as db:
            db.execute((Path(__file__).resolve().parents[1] / "db/proposals/013_demo_business_clock.sql").read_text())
            db.execute("""INSERT INTO demo_clock_state
                (instance_id,real_anchor,domain_anchor,domain_start,domain_limit,scale)
                SELECT %s,t,t,t,t+interval '168 hours',0 FROM (SELECT clock_timestamp() AS t) q""", (self.instance_id,))
        self.clock = self.new_clock()

    def connect(self):
        return connect_for(self.dsn, self.schema)

    def new_clock(self):
        return PostgresDemoBusinessClock(self.connect, settings=FLAGS, instance_id=self.instance_id)

    def drop_schema(self):
        # This uniquely named schema was created by this test; never an app reset.
        with self.pg.connect(self.dsn, autocommit=True) as db:
            db.execute(self.sql.SQL("DROP SCHEMA {} CASCADE").format(self.sql.Identifier(self.schema)))

    def command(self, *, action="advance", value=60):
        snapshot = self.clock.capture()
        return {"instance_id": self.instance_id, "expected_version": snapshot.revision,
                "action": action, "seconds" if action == "advance" else "scale": value}

    def test_restart_preserves_mapping_and_replay_fence(self):
        command = self.command()
        applied = self.clock.apply(command, authorize=lambda: ACTOR)
        restarted = self.new_clock().capture()
        self.assertEqual((restarted.instance_id, restarted.revision, restarted.real_anchor, restarted.business_anchor, restarted.business_now),
                         (applied.instance_id, applied.revision, applied.real_anchor, applied.business_anchor, applied.business_now))
        with self.assertRaises(DomainError) as caught:
            self.new_clock().apply(command, authorize=lambda: ACTOR)
        self.assertEqual(caught.exception.code, "VERSION_CONFLICT")

    def test_two_processes_share_state_with_one_cas_winner(self):
        initial, command = self.clock.capture(), self.command()
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(2, mp_context=context) as pool:
            pending = [pool.submit(run_process, self.dsn, self.schema, self.instance_id, command) for _ in range(2)]
            results = [future.result(timeout=20) for future in pending]
            reads = [pool.submit(run_process, self.dsn, self.schema, self.instance_id) for _ in range(2)]
            reads = [future.result(timeout=20) for future in reads]
        self.assertEqual(sorted(result["result"] for result in results), ["OK", "VERSION_CONFLICT"])
        self.assertEqual([row["version"] for row in reads], [1, 1])
        self.assertEqual(reads[0]["domain_now"], reads[1]["domain_now"])
        self.assertEqual(self.clock.now(), initial.business_now + timedelta(seconds=60))

    def test_worker_snapshot_is_read_only(self):
        clock = PostgresDemoBusinessClock(lambda: connect_for(self.dsn, self.schema, read_only=True),
            settings=FLAGS, instance_id=self.instance_id)
        self.assertEqual(clock.capture().storage, "postgres_shared")

    def test_audit_failure_rolls_back_state(self):
        old = self.clock.capture()
        original = self.clock._transaction
        class FailAudit:
            def __init__(self, db): self.db = db
            def execute(self, query, *args):
                if "INSERT INTO demo_clock_controls" in query:
                    raise RuntimeError("synthetic audit failure")
                return self.db.execute(query, *args)
        @contextmanager
        def failed_transaction():
            with original() as db:
                yield FailAudit(db)
        self.clock._transaction = failed_transaction
        with self.assertRaises(RuntimeError):
            self.clock.apply(self.command(), authorize=lambda: ACTOR)
        self.assertEqual(self.new_clock().capture().revision, old.revision)
        self.assertEqual(self.new_clock().now(), old.business_now)

    def test_database_rejects_no_audit_rewind_and_audit_mutation(self):
        with self.assertRaises(self.pg.Error):
            with self.connect() as db, db.transaction():
                db.execute("UPDATE demo_clock_state SET version=version+1 WHERE instance_id=%s", (self.instance_id,))
        self.assertEqual(self.clock.capture().revision, 0)
        with self.assertRaises(self.pg.Error):
            with self.connect() as db:
                db.execute("UPDATE demo_clock_state SET version=version+1,domain_anchor=domain_anchor-interval '1 second' WHERE instance_id=%s", (self.instance_id,))
        self.clock.apply(self.command(), authorize=lambda: ACTOR)
        with self.assertRaises(self.pg.Error):
            with self.connect() as db:
                db.execute("UPDATE demo_clock_controls SET actor_id=%s", (str(uuid4()),))

    def test_auth_is_rechecked_after_state_lock_wait(self):
        # The callback itself is the seam; full current-session DB proof belongs
        # to mounted integration. No effect may precede callback success.
        before = self.clock.capture()
        def denied():
            from app.core.auth_boundary import AuthenticationRequired
            raise AuthenticationRequired()
        from app.core.auth_boundary import AuthenticationRequired
        with self.assertRaises(AuthenticationRequired):
            self.clock.apply(self.command(), authorize=denied)
        self.assertEqual(self.clock.capture().revision, before.revision)


if __name__ == "__main__":
    unittest.main()
