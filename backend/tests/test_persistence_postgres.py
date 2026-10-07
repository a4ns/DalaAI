"""REAL PostgreSQL integration tests. No SQLite, fake transaction, or fallback.

Opt in with DALA_TEST_DATABASE_URL for an isolated test database. Each test owns
one random schema and drops only that schema. Missing DSN => explicitly skipped;
a configured DSN with missing driver/failed server/migration => ERROR, never skip.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import os
from pathlib import Path
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4

from app.core.auth_boundary import AuthenticationRequired
from app.core.auth_policy import AccessDenied
from app.orders.models import DomainError
from app.persistence.postgres import PostgresRepository, PostgresReferences
from app.persistence.service import CommandService
from test_persistence_canonical import create_command, uid

NOW = datetime(2026,10,7,17,tzinfo=timezone.utc)
SECTION, EQUIPMENT, EXECUTOR, MASTER, OTHER, CODE, MATERIAL = [uid(n) for n in (1,2,3,4,5,6,7)]
SECOND_SECTION, SECOND_EQUIPMENT = uid(8),uid(9)
ORIGIN = "https://naryadai.test"
MIGRATIONS = Path(__file__).resolve().parents[1] / "db" / "migrations"


class Clock:
    def __init__(self,now=NOW):
        self.value = now
    def now(self):
        return self.value


class PostgresCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.environ.get("DALA_TEST_DATABASE_URL")
        if not cls.dsn:
            raise unittest.SkipTest("NOT_RUN: DALA_TEST_DATABASE_URL absent; real PostgreSQL required")
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row
        cls.pg,cls.sql,cls.dict_row = psycopg,sql,staticmethod(dict_row)

    def setUp(self):
        self.schema = "a6_test_" + uuid4().hex
        with self.pg.connect(self.dsn,autocommit=True) as db:
            db.execute(self.sql.SQL("CREATE SCHEMA {}").format(self.sql.Identifier(self.schema)))
        self.addCleanup(self.drop_schema)
        with self.connect() as db:
            for migration in sorted(MIGRATIONS.glob("*.sql")):
                db.execute(migration.read_text())
            db.execute("INSERT INTO sections VALUES (%s,'S1','Synthetic 1'),(%s,'S2','Synthetic 2')",(SECTION,SECOND_SECTION))
            for employee,role,code in ((MASTER,"master","M"),(EXECUTOR,"executor","E"),(OTHER,"executor","E2")):
                db.execute("""INSERT INTO employees(id,employee_code,role,on_shift,pin_hash)
                    VALUES (%s,%s,%s,true,'not-a-login-fixture')""",(employee,code,role))
                db.execute("INSERT INTO employee_sections VALUES (%s,%s)",(employee,SECTION))
                db.execute("""INSERT INTO auth_sessions(id,employee_id,token_hash,csrf_token,created_at,expires_at)
                    VALUES (%s,%s,%s,'synthetic-csrf',%s,%s)""",(str(uuid4()),employee,
                    sha256(employee.encode()).hexdigest(),NOW-timedelta(minutes=1),NOW+timedelta(days=5)))
            db.execute("INSERT INTO employee_sections VALUES (%s,%s)",(MASTER,SECOND_SECTION))
            db.execute("INSERT INTO equipment VALUES (%s,%s,'EQ','Synthetic'),(%s,%s,'EQ2','Synthetic')",
                       (EQUIPMENT,SECTION,SECOND_EQUIPMENT,SECOND_SECTION))
            db.execute("INSERT INTO work_codes VALUES (%s,'W','Synthetic work')",(CODE,))
            db.execute("INSERT INTO materials VALUES (%s,'MAT','Synthetic material','unit')",(MATERIAL,))
        self.real = Clock()
        self.domain = Clock()
        self.service = CommandService(self.connect,allowed_origin=ORIGIN,delivery_channel="synthetic",
                                      domain_clock=self.domain,real_clock=self.real)

    def connect(self):
        return self.pg.connect(self.dsn,autocommit=True,options=f"-c search_path={self.schema}",row_factory=self.dict_row)

    def drop_schema(self):
        with self.pg.connect(self.dsn,autocommit=True) as db:
            db.execute(self.sql.SQL("DROP SCHEMA {} CASCADE").format(self.sql.Identifier(self.schema)))

    def query(self,sql,params=()):
        with self.connect() as db:
            return db.execute(sql,params).fetchall()

    def run_command(self,command,actor=MASTER,order_id=None):
        return self.service.execute(command,session_handle=actor,origin=ORIGIN,
                                    csrf_token="synthetic-csrf",order_id=order_id)

    def create(self,photos=()):
        command = create_command()
        command["operation_id"] = str(uuid4())
        command["payload"]["before_photo_ids"] = list(photos)
        return self.run_command(command),command

    def action(self,order_id,version,action,actor=EXECUTOR,payload=None,operation=None):
        command = {"operation_id":operation or str(uuid4()),"expected_version":version,
                   "action":action,"payload":payload or {}}
        return self.run_command(command,actor,order_id),command

    def start(self):
        created,_ = self.create()
        order_id = created.body["order"]["id"]
        self.action(order_id,1,"accept")
        self.action(order_id,2,"start")
        return order_id

    def stage(self,*,owner=MASTER,section=SECTION,purpose="before",order_id=None,revision=None,
              valid=True,expires=None):
        photo_id = str(uuid4())
        self.query("""INSERT INTO photos(id,owner_id,section_id,purpose,order_id,assignment_revision,
            storage_key,mime_type,bytes,sha256,uploaded_at,expires_at,exif_removed,file_valid)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'image/jpeg',100,%s,%s,%s,true,%s) RETURNING id""",
            (photo_id,owner,section,purpose,order_id,revision,"synthetic/"+photo_id,"a"*64,
             NOW-timedelta(hours=1),expires or NOW+timedelta(hours=24),valid))
        return photo_id

    def submit(self,order_id,photos=(),code=CODE):
        return self.action(order_id,3,"submit",payload={"work_description":"Ремень заменён",
            "work_code_id":code,"materials":[{"material_id":MATERIAL,"quantity":1.25}],
            "after_photo_ids":list(photos),"comment":""})

    def review(self,order_id,submission_id,*,decision="close",version=4):
        return self.action(order_id,version,"review",MASTER,{"submission_id":submission_id,
            "decision":decision,"reason":"Проверено мастером","final_score":None})

    def test_create_replay_returns_original_snapshot_after_later_change(self):
        created,command = self.create()
        order_id = created.body["order"]["id"]
        self.action(order_id,1,"accept")
        replay = self.run_command(command)
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.body,created.body)
        self.assertEqual(replay.status,201)
        self.assertEqual(self.query("SELECT version FROM orders")[0]["version"],2)
        self.assertEqual(len(self.query("SELECT * FROM order_events")),2)

    def test_idempotency_hash_mismatch_is_conflict(self):
        _,command = self.create()
        command["payload"]["description"] = "Different intent"
        with self.assertRaises(DomainError) as error:
            self.run_command(command)
        self.assertEqual(error.exception.code,"OPERATION_ID_REUSED")
        self.assertEqual(len(self.query("SELECT * FROM orders")),1)

    def test_concurrent_identical_operation_waits_then_rereads_receipt(self):
        created,_ = self.create()
        order_id = created.body["order"]["id"]
        command = {"operation_id":str(uuid4()),"expected_version":1,"action":"accept","payload":{}}
        barrier = Barrier(2)
        reserve = PostgresRepository.reserve
        def simultaneous(repo,*args):
            barrier.wait(timeout=10)
            return reserve(repo,*args)
        with patch.object(PostgresRepository,"reserve",simultaneous),ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(self.run_command,deepcopy(command),EXECUTOR,order_id)
            b = pool.submit(self.run_command,deepcopy(command),EXECUTOR,order_id)
            results = [a.result(timeout=20),b.result(timeout=20)]
        self.assertEqual(results[0].body,results[1].body)
        self.assertEqual(sorted(r.replayed for r in results),[False,True])
        self.assertEqual(self.query("SELECT version FROM orders")[0]["version"],2)
        self.assertEqual(len(self.query("SELECT * FROM operation_receipts")),2)
        self.assertEqual(len(self.query("SELECT * FROM order_events")),2)

    def test_two_distinct_operations_same_version_have_one_winner(self):
        created,_ = self.create()
        order_id = created.body["order"]["id"]
        barrier = Barrier(2)
        reserve = PostgresRepository.reserve
        def simultaneous(repo,*args):
            result = reserve(repo,*args)
            barrier.wait(timeout=10)
            return result
        def perform():
            try:
                return self.action(order_id,1,"accept")[0]
            except DomainError as error:
                return error.code
        with patch.object(PostgresRepository,"reserve",simultaneous),ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(perform) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]
        self.assertEqual(sum(result == "VERSION_CONFLICT" for result in results),1)
        self.assertEqual(self.query("SELECT version FROM orders")[0]["version"],2)
        self.assertEqual(len(self.query("SELECT * FROM operation_receipts")),2)

    def test_foreign_executor_and_reassigned_receipt_rejected(self):
        created,_ = self.create()
        order_id = created.body["order"]["id"]
        with self.assertRaises(AccessDenied):
            self.action(order_id,1,"accept",OTHER)
        _,accepted = self.action(order_id,1,"accept")
        self.action(order_id,2,"reassign",MASTER,{"assignment":{"executor_id":OTHER,"brigade_id":None},"reason":"New assignment"})
        with self.assertRaises(AccessDenied):
            self.run_command(accepted,EXECUTOR,order_id)

    def test_receipt_does_not_bypass_revocation_role_or_scope(self):
        _,command = self.create()
        self.query("UPDATE employees SET role='manager' WHERE id=%s RETURNING id",(MASTER,))
        with self.assertRaises(AccessDenied):
            self.run_command(command)
        self.query("UPDATE employees SET role='master' WHERE id=%s RETURNING id",(MASTER,))
        self.query("DELETE FROM employee_sections WHERE employee_id=%s AND section_id=%s RETURNING employee_id",(MASTER,SECTION))
        with self.assertRaises(AccessDenied):
            self.run_command(command)
        self.query("UPDATE auth_sessions SET revoked_at=%s WHERE employee_id=%s RETURNING id",(NOW,MASTER))
        with self.assertRaises(AuthenticationRequired):
            self.run_command(command)

    def test_wrong_origin_or_csrf_has_no_receipt(self):
        for origin,csrf in (("https://evil.test","synthetic-csrf"),(ORIGIN,"wrong")):
            with self.assertRaises(AccessDenied):
                self.service.execute(create_command(),session_handle=MASTER,origin=origin,csrf_token=csrf)
        self.assertEqual(self.query("SELECT * FROM operation_receipts"),[])

    def test_cross_section_and_owner_stages_rejected(self):
        for photo in (self.stage(section=SECOND_SECTION),self.stage(owner=OTHER)):
            with self.assertRaises((AccessDenied,DomainError)):
                self.create([photo])
        self.assertEqual(self.query("SELECT * FROM orders"),[])
        self.assertTrue(all(row["attached_at"] is None for row in self.query("SELECT * FROM photos")))

    def test_expired_authorized_stage_returns_photo_expired(self):
        photo = self.stage(expires=NOW-timedelta(seconds=1))
        with self.assertRaises(DomainError) as error:
            self.create([photo])
        self.assertEqual(error.exception.code,"PHOTO_EXPIRED")
        self.assertEqual(self.query("SELECT * FROM operation_receipts"),[])

    def test_single_use_stage_replay_and_failed_create_does_not_consume(self):
        photo = self.stage()
        original = PostgresRepository.persist_events
        def fail(repo,*args):
            original(repo,*args)
            raise RuntimeError("synthetic fault after events")
        with patch.object(PostgresRepository,"persist_events",fail),self.assertRaises(RuntimeError):
            self.create([photo])
        for table in ("orders","order_events","operation_receipts","delivery_jobs"):
            self.assertEqual(self.query(f"SELECT * FROM {table}"),[])
        self.assertIsNone(self.query("SELECT attached_at FROM photos")[0]["attached_at"])
        created,command = self.create([photo])
        self.assertEqual(self.run_command(command).body,created.body)
        with self.assertRaises((AccessDenied,DomainError)):
            self.create([photo])
        self.assertEqual(len(self.query("SELECT * FROM orders")),1)

    def test_concurrent_different_creates_cannot_consume_same_stage(self):
        photo = self.stage()
        def perform():
            try:
                return self.create([photo])[0]
            except (AccessDenied,DomainError):
                return "denied"
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(perform) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]
        self.assertEqual(sum(result == "denied" for result in results),1)
        self.assertEqual(len(self.query("SELECT * FROM orders")),1)
        self.assertEqual(len(self.query("SELECT * FROM operation_receipts")),1)

    def test_submit_atomic_events_jobs_manifest_and_human_close(self):
        order_id = self.start()
        photo = self.stage(owner=EXECUTOR,purpose="after",order_id=order_id,revision=1)
        submitted,command = self.submit(order_id,[photo])
        sub_id = submitted.body["submission_id"]
        self.assertEqual(submitted.body["order"]["status"],"ai_review")
        events = self.query("SELECT sequence,order_version,to_status FROM order_events ORDER BY sequence")
        self.assertEqual([(r["sequence"],r["order_version"],r["to_status"]) for r in events[-2:]],[(4,4,"done"),(5,4,"ai_review")])
        self.assertEqual(len(self.query("SELECT * FROM ai_jobs")),1)
        self.assertEqual(len(self.query("SELECT * FROM delivery_jobs WHERE kind='submission_ready'")),1)
        self.assertEqual(self.service.get_submission(order_id,sub_id,session_handle=MASTER)["payload"]["after_photo_ids"],[photo])
        replay = self.run_command(command,EXECUTOR,order_id)
        self.assertEqual(replay.body,submitted.body)
        closed,_ = self.review(order_id,sub_id)
        self.assertEqual(closed.body["order"]["status"],"closed")
        self.assertEqual(len(self.query("SELECT * FROM reviews")),1)
        self.assertEqual(len(self.query("SELECT * FROM delivery_jobs WHERE kind='review_result'")),1)

    def test_unknown_or_invalid_current_file_blocks_close_but_allows_rework(self):
        order_id = self.start()
        photo = self.stage(owner=EXECUTOR,purpose="after",order_id=order_id,revision=1)
        submitted,_ = self.submit(order_id,[photo])
        sub_id = submitted.body["submission_id"]
        for validity in (None,False):
            self.query("UPDATE photos SET file_valid=%s WHERE id=%s RETURNING id",(validity,photo))
            with self.assertRaises(DomainError) as error:
                self.review(order_id,sub_id)
            self.assertEqual(error.exception.code,"INCOMPLETE_SUBMISSION")
        self.assertEqual(self.query("SELECT version FROM orders")[0]["version"],4)
        self.assertEqual(self.query("SELECT * FROM reviews"),[])
        rework,_ = self.review(order_id,sub_id,decision="rework")
        self.assertEqual(rework.body["order"]["status"],"rework")

    def test_incomplete_submission_is_reviewable_but_not_closable(self):
        order_id = self.start()
        submitted,_ = self.submit(order_id)
        sub_id = submitted.body["submission_id"]
        self.assertEqual(self.service.get_submission(order_id,sub_id,session_handle=MASTER)["completeness"],"incomplete")
        with self.assertRaises(DomainError) as error:
            self.review(order_id,sub_id)
        self.assertEqual(error.exception.code,"INCOMPLETE_SUBMISSION")
        self.review(order_id,sub_id,decision="rework")

    def test_incomplete_rework_resubmit_close_keeps_both_attempts_and_reviews(self):
        order_id = self.start()
        first,_ = self.submit(order_id)
        first_sub = first.body["submission_id"]
        with self.assertRaises(DomainError):
            self.review(order_id,first_sub)
        self.review(order_id,first_sub,decision="rework")
        self.action(order_id,5,"start")
        photo = self.stage(owner=EXECUTOR,purpose="after",order_id=order_id,revision=1)
        second,_ = self.action(order_id,6,"submit",payload={"work_description":"Доработано",
            "work_code_id":CODE,"materials":[],"after_photo_ids":[photo],"comment":""})
        self.review(order_id,second.body["submission_id"],version=7)
        attempts = self.query("SELECT attempt_number,completeness FROM submissions ORDER BY attempt_number")
        self.assertEqual(attempts,[{"attempt_number":1,"completeness":"incomplete"},
                                   {"attempt_number":2,"completeness":"complete"}])
        self.assertEqual(len(self.query("SELECT * FROM reviews")),2)
        self.assertEqual(self.query("SELECT status,version FROM orders")[0],{"status":"closed","version":8})
        from app.scheduler import ScheduleSnapshot
        snapshot = ScheduleSnapshot(order_id,1,1,"in_progress","normal",EXECUTOR,MASTER,
                                    NOW+timedelta(hours=1),NOW,first_sub)
        self.assertEqual(snapshot.deadline_cycle,"rework:"+first_sub)

    def test_attached_photo_ttl_is_not_reapplied(self):
        order_id = self.start()
        photo = self.stage(owner=EXECUTOR,purpose="after",order_id=order_id,revision=1)
        submitted,_ = self.submit(order_id,[photo])
        self.real.value += timedelta(days=2)
        self.review(order_id,submitted.body["submission_id"])
        self.assertEqual(self.query("SELECT status FROM orders")[0]["status"],"closed")

    def test_stale_revision_stage_rejected_and_not_consumed(self):
        order_id = self.start()
        photo = self.stage(owner=EXECUTOR,purpose="after",order_id=order_id,revision=2)
        with self.assertRaises((AccessDenied,DomainError)):
            self.submit(order_id,[photo])
        self.assertIsNone(self.query("SELECT attached_at FROM photos WHERE id=%s",(photo,))[0]["attached_at"])
        self.assertEqual(self.query("SELECT version FROM orders")[0]["version"],3)

    def test_failure_after_outbox_rolls_back_submission_and_both_events(self):
        order_id = self.start()
        photo = self.stage(owner=EXECUTOR,purpose="after",order_id=order_id,revision=1)
        finalize = PostgresRepository.finalize_receipt
        def fail(repo,*args):
            finalize(repo,*args)
            raise RuntimeError("synthetic lost-before-commit fault")
        with patch.object(PostgresRepository,"finalize_receipt",fail),self.assertRaises(RuntimeError):
            self.submit(order_id,[photo])
        self.assertEqual(self.query("SELECT version,status FROM orders")[0],{"version":3,"status":"in_progress"})
        for table in ("submissions","material_writeoffs","ai_jobs"):
            self.assertEqual(self.query(f"SELECT * FROM {table}"),[])
        self.assertEqual(len(self.query("SELECT * FROM order_events")),3)
        self.assertEqual(len(self.query("SELECT * FROM operation_receipts")),3)
        self.assertIsNone(self.query("SELECT attached_at FROM photos WHERE id=%s",(photo,))[0]["attached_at"])

    def test_stage_ttl_is_refreshed_after_blocking_reference_lookup(self):
        photo = self.stage(expires=NOW+timedelta(seconds=10))
        lookup = PostgresReferences.equipment_in_section
        def waited(refs,*args):
            value = lookup(refs,*args)
            self.real.value = NOW+timedelta(seconds=20)
            return value
        with patch.object(PostgresReferences,"equipment_in_section",waited),self.assertRaises((AccessDenied,DomainError)):
            self.create([photo])
        self.assertEqual(self.query("SELECT * FROM orders"),[])
        self.assertEqual(self.query("SELECT * FROM operation_receipts"),[])
        self.assertIsNone(self.query("SELECT attached_at FROM photos")[0]["attached_at"])

    def test_session_expiry_after_stage_lock_blocks_effects(self):
        photo = self.stage()
        lock = PostgresReferences.lock_stages
        def waited(refs,*args):
            value = lock(refs,*args)
            self.real.value = NOW+timedelta(days=6)
            return value
        with patch.object(PostgresReferences,"lock_stages",waited),self.assertRaises(AuthenticationRequired):
            self.create([photo])
        self.assertEqual(self.query("SELECT * FROM orders"),[])
        self.assertEqual(self.query("SELECT * FROM operation_receipts"),[])

    def test_replay_session_rechecked_after_resource_lock_wait(self):
        created,command = self.create()
        load = PostgresRepository.load_order
        def waited(repo,*args,**kwargs):
            value = load(repo,*args,**kwargs)
            if kwargs.get("share"):
                self.real.value = NOW+timedelta(days=6)
            return value
        with patch.object(PostgresRepository,"load_order",waited),self.assertRaises(AuthenticationRequired):
            self.run_command(command)
        self.assertEqual(len(self.query("SELECT * FROM orders")),1)

    def test_read_session_rechecked_after_resource_lock_wait(self):
        order_id = self.start()
        submitted,_ = self.submit(order_id)
        load = PostgresRepository.load_order
        def waited(repo,*args,**kwargs):
            value = load(repo,*args,**kwargs)
            if kwargs.get("share"):
                self.real.value = NOW+timedelta(days=6)
            return value
        for reader in (lambda:self.service.get_order(order_id,session_handle=MASTER),
                       lambda:self.service.get_submission(order_id,submitted.body["submission_id"],session_handle=MASTER)):
            self.real.value = NOW
            with patch.object(PostgresRepository,"load_order",waited),self.assertRaises(AuthenticationRequired):
                reader()

    def test_deferred_guard_rejects_unfinalized_receipt(self):
        with self.assertRaises(self.pg.Error),self.connect() as db:
            with db.transaction():
                PostgresRepository(db).reserve(MASTER,str(uuid4()),"a"*64,NOW)
        self.assertEqual(self.query("SELECT * FROM operation_receipts"),[])

    def test_attached_binding_and_submission_audit_cannot_be_deleted(self):
        order_id = self.start()
        photo = self.stage(owner=EXECUTOR,purpose="after",order_id=order_id,revision=1)
        submitted,_ = self.submit(order_id,[photo])
        with self.assertRaises(self.pg.Error):
            self.query("DELETE FROM photos WHERE id=%s RETURNING id",(photo,))
        with self.assertRaises(self.pg.Error):
            self.query("UPDATE submissions SET after_photo_ids='{}' WHERE id=%s RETURNING id",(submitted.body["submission_id"],))
        with self.assertRaises(self.pg.Error):
            self.query("UPDATE photos SET owner_id=%s WHERE id=%s RETURNING id",(MASTER,photo))


if __name__ == "__main__":
    unittest.main()
