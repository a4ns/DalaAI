"""Control-flow/SQL-shape simulations, NOT evidence of real PostgreSQL semantics."""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.ai.model_adapter import EgressApproval, ModelAdapter, prepare_input
from app.ai.model_budget import BudgetPolicy, SqliteBudgetLedger
from app.ai.openai_runtime import openai_demo_settings
from app.jobs.models import Claim, RunResult, WorkerPolicy
from app.jobs.postgres import JobRepository
from app.jobs.provider_worker import (ProviderAssessmentWorker, ProviderAssets, ProviderJobRepository,
    PreparedAssessment, provider_event)
from test_model_adapter import (good,uid,NOW,ASSESS,FakeTransport,response,observation)


class Store:
    def __init__(self):
        self.active=0;self.log=[];self.effects=[];self.valid_lease=True;self.finish_ok=True
        self.data,self.context=good()
        self.order=SimpleNamespace(id=self.data.order_id,version=4,assignment_revision=1,
            scheduling_revision=1,before_photo_ids=(),type='unplanned',description=self.data.problem_description,
            current_submission_id=self.data.submission_id,status='ai_review',section_id=uid(90),updated_at=NOW)
        self.sub=SimpleNamespace(id=self.data.submission_id,order_id=self.data.order_id,assignment_revision=1,
            payload=SimpleNamespace(work_description=self.data.work_description,work_code_id=self.data.work_code_id,
                materials=self.data.materials,after_photo_ids=self.data.after_photo_ids),
            completeness='complete',missing_evidence=())


class FakeDB:
    def __init__(self,store):self.store=store
    def __enter__(self):return self
    def __exit__(self,*args):pass
    @contextmanager
    def transaction(self):
        before=deepcopy(self.store.effects);self.store.active+=1
        try:yield
        except BaseException:
            self.store.effects=before
            raise
        finally:self.store.active-=1
    def execute(self,sql,params=()):
        self.store.log.append(sql)
        if sql.startswith('INSERT') or sql.startswith('UPDATE orders'):
            self.store.effects.append((sql,params))
        return SimpleNamespace(rowcount=1,fetchall=lambda:[],fetchone=lambda:{'n':1})


class FakeRepository:
    def __init__(self,db):self.db=db;self.store=db.store
    def load_submission(self,*args):self.store.log.append('load_submission');return self.store.sub
    def load_order(self,*args,**kwargs):self.store.log.append('lock_order');return self.store.order


class TransactionAwareTransport(FakeTransport):
    def __init__(self,store,**kw):super().__init__(**kw);self.store=store
    async def post_json(self,**kwargs):
        if self.store.active:raise AssertionError('PROVIDER_CALLED_INSIDE_TRANSACTION')
        self.store.log.append('provider_outside_transaction')
        return await super().post_json(**kwargs)


class ProviderWorkerUnitTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store();self.now=NOW
        self.clock=SimpleNamespace(now=lambda:self.now)
        self.claim=Claim(uid(50),self.store.data.submission_id,1,1,uid(51),NOW+timedelta(seconds=30))
        settings=openai_demo_settings(timeout_seconds=.05)
        payload=prepare_input(self.store.data,self.store.context)
        ledger=SqliteBudgetLedger(Path(self.tmp.name)/'budget.sqlite',BudgetPolicy('test',1000,100,60,1))
        self.transport=TransactionAwareTransport(self.store)
        adapter=ModelAdapter(settings=settings,transport=self.transport,ledger=ledger,
            approval=EgressApproval('test',settings.fingerprint,frozenset({payload.payload_hash}),NOW+timedelta(hours=1)))
        def refs(repo,*args):
            self.store.log.append('physical_evidence')
            c=self.store.context
            return SimpleNamespace(closure_evidence=lambda sub:(c.work_code_ids,c.material_ids,c.photos))
        self.worker=ProviderAssessmentWorker(None,adapter=adapter,domain_clock=self.clock,
            real_clock=self.clock,references_factory=refs)
        self.worker._connection=lambda:FakeDB(self.store)
        self.worker.claim_one=lambda:self.claim
        self.worker.record_failure=lambda claim,invalid_input=False:RunResult('failed' if invalid_input else 'retry',claim.id)
        def owns(repo,claim,*,now,lock=False):
            self.store.log.append('job_lock' if lock else 'job_check')
            return self.store.valid_lease and now<claim.lease_until
        def finish(repo,claim,*,now):
            self.store.log.append('finish_fence')
            return self.store.finish_ok and self.store.valid_lease and now<claim.lease_until
        self.patches=[patch('app.jobs.provider_worker.PostgresRepository',FakeRepository),
            patch.object(JobRepository,'owns',owns),patch.object(ProviderJobRepository,'finish',finish),
            patch('app.jobs.provider_worker.jsonb',lambda x:x)]
        for p in self.patches:p.start();self.addCleanup(p.stop)

    async def test_provider_outside_transaction_and_model_mode_persisted_atomically(self):
        r=await self.worker.run_once()
        self.assertEqual(r.state,'done');self.assertFalse(r.stale)
        writes=self.store.effects
        self.assertEqual(len(writes),3)
        sql,p=writes[0]
        self.assertIn('INSERT INTO ai_assessments',sql)
        self.assertEqual(p[3],'model');self.assertIsNotNone(p[4]);self.assertIsNotNone(p[5])
        self.assertIn('NULL',sql)
        event=writes[2][1]
        self.assertEqual(event['details']['mode'],'model')
        self.assertEqual(event['to_status'],'ai_review')
        self.assertIn('provider_provenance',event['details'])
        self.assertNotIn(self.store.data.work_description,json.dumps(event['details']))
        self.assertEqual(self.store.log.count('physical_evidence'),2)
        for index,entry in enumerate(self.store.log):
            if entry=='job_lock':
                self.assertIn('lock_order',self.store.log[:index])
                self.assertIn('physical_evidence',self.store.log[:index])
        self.assertLess(self.store.log.index('job_check'),self.store.log.index('provider_outside_transaction'))
        self.assertEqual(self.store.active,0)

    async def test_unconfigured_adapter_persists_honest_fallback(self):
        self.worker.adapter.approval=None
        r=await self.worker.run_once()
        self.assertEqual(r.state,'done')
        self.assertEqual(self.store.effects[0][1][3],'rules_fallback')
        self.assertIsNone(self.store.effects[0][1][4])
        self.assertEqual(self.transport.calls,[])
        self.assertEqual(self.store.effects[2][1]['details']['mode'],'rules_fallback')

    async def test_current_evidence_rechecked_after_provider(self):
        original=self.transport.post_json
        async def late_change(**kwargs):
            result=await original(**kwargs)
            self.store.context=replace(self.store.context,photos=())
            return result
        self.transport.post_json=late_change
        r=await self.worker.run_once()
        self.assertEqual(r.state,'done')
        self.assertEqual(self.store.effects[0][1][3],'rules_fallback')
        self.assertEqual(self.store.effects[2][1]['details']['mode'],'rules_fallback')

    async def test_reassignment_stale_archives_no_current_version_or_event(self):
        original=self.transport.post_json
        async def late_change(**kwargs):
            result=await original(**kwargs)
            self.store.order.assignment_revision=2;self.store.order.status='issued'
            self.store.order.current_submission_id=None
            return result
        self.transport.post_json=late_change
        r=await self.worker.run_once()
        self.assertEqual(r.state,'done');self.assertTrue(r.stale)
        self.assertEqual(len(self.store.effects),1)
        self.assertEqual(self.store.effects[0][1][3],'rules_fallback')

    async def test_lease_loss_after_provider_writes_nothing(self):
        original=self.transport.post_json
        async def late_change(**kwargs):
            result=await original(**kwargs);self.store.valid_lease=False;return result
        self.transport.post_json=late_change
        r=await self.worker.run_once()
        self.assertEqual(r.state,'lost_lease');self.assertEqual(self.store.effects,[])

    async def test_final_finish_failure_rolls_back_all_provisional_effects(self):
        self.store.finish_ok=False
        r=await self.worker.run_once()
        self.assertEqual(r.state,'lost_lease');self.assertEqual(self.store.effects,[])
        self.assertIn('finish_fence',self.store.log)

    async def test_failure_after_insert_rolls_back_and_is_sanitized(self):
        def fail(*a,**k):raise RuntimeError('PRIVATE_KEY_RAW_PROVIDER_BODY')
        with patch.object(ProviderJobRepository,'publish_finalized',fail):r=await self.worker.run_once()
        self.assertEqual(r.state,'retry');self.assertEqual(self.store.effects,[])
        self.assertNotIn('PRIVATE',repr(r))

    async def test_no_lease_margin_skips_provider(self):
        self.now=self.claim.lease_until-timedelta(seconds=1)
        r=await self.worker.run_once()
        self.assertEqual(r.state,'retry');self.assertEqual(self.transport.calls,[])

    async def test_lost_prepare_lease_skips_provider(self):
        self.store.valid_lease=False
        r=await self.worker.run_once()
        self.assertEqual(r.state,'lost_lease');self.assertEqual(self.transport.calls,[])

    async def test_cancelled_provider_does_not_persist_or_fake_retry(self):
        self.transport.delay=10
        task=asyncio.create_task(self.worker.run_once())
        await asyncio.sleep(.01);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(self.store.effects,[])
        self.assertEqual(self.worker.adapter.ledger.counters()['calls_reserved'],1)

    async def test_invalid_assets_fails_without_egress(self):
        self.worker.assets_factory=lambda *args,**kwargs:{'synthetic':True}
        r=await self.worker.run_once()
        self.assertEqual(r.state,'failed');self.assertEqual(self.transport.calls,[])

    async def test_batch_bound_and_terminal_idle(self):
        for limit in (True,0,1001):
            with self.assertRaises(ValueError):await self.worker.run_batch(limit=limit)
        results=iter([RunResult('done'),RunResult('idle')])
        async def step():return next(results)
        self.worker.run_once=step
        self.assertEqual(len(await self.worker.run_batch()),1)

    async def test_event_matches_existing_schema_with_safe_provenance(self):
        import yaml
        from jsonschema import Draft202012Validator,FormatChecker
        from app.persistence.canonical import canonical_json
        import app
        await self.worker.run_once()
        event=self.store.effects[2][1]
        root=Path(app.__file__).resolve().parents[2]
        spec=yaml.safe_load((root/'coord/proposals/a6-contract-v1/contracts/openapi.yaml').read_text())
        Draft202012Validator(dict(spec,**{'$ref':'#/components/schemas/OrderEvent'}),
            format_checker=FormatChecker()).validate(json.loads(canonical_json(event)))

    def test_constructor_no_implicit_connection_and_timeout_lease_bound(self):
        with self.assertRaisesRegex(ValueError,'LEASE_MARGIN'):
            ProviderAssessmentWorker(None,adapter=self.worker.adapter,domain_clock=self.clock,
                                      policy=WorkerPolicy(lease=timedelta(seconds=2)))
        self.assertEqual(self.transport.calls,[])
        self.assertEqual(self.store.log,[])


class PrivatePngFactoryTests(unittest.TestCase):
    def setUp(self):
        from test_model_adapter import good,BEFORE,AFTER,png
        self.d,self.c=good();self.before_id,self.after_id=BEFORE,AFTER
        self.order=SimpleNamespace(id=self.d.order_id,section_id=uid(80),before_photo_ids=(BEFORE,))
        self.sub=SimpleNamespace(id=self.d.submission_id,assignment_revision=1,submitted_by=uid(81),
                                payload=SimpleNamespace(after_photo_ids=(AFTER,)))
        self.rows={}
        for purpose,photo_id in [('before',BEFORE),('after',AFTER)]:
            self.rows[photo_id]={'id':photo_id,'order_id':self.d.order_id,'section_id':uid(80),
                'attached_at':NOW,'purpose':purpose,'file_valid':True,'owner_id':uid(81),
                'submission_id':None if purpose=='before' else self.d.submission_id,
                'assignment_revision':None if purpose=='before' else 1}
        self.repo=SimpleNamespace(db=SimpleNamespace(execute=lambda sql,params:
            SimpleNamespace(fetchone=lambda:self.rows.get(params[0]))))
        self.reads=[]
        def read(row):self.reads.append(row['id']);return png()
        from app.jobs.provider_worker import PrivatePngAssetsFactory
        self.factory=PrivatePngAssetsFactory(read,selections={self.sub.id:(BEFORE,AFTER)})

    def test_nullable_before_and_bound_after_private_png_pair(self):
        result=self.factory(self.repo,None,self.order,self.sub,include_images=True)
        self.assertEqual([i.purpose for i in result.images],['before','after'])
        self.assertEqual(result.before_photos[0].id,self.before_id)
        self.assertEqual(len(self.reads),2)
        current=self.factory(self.repo,None,self.order,self.sub,include_images=False)
        self.assertEqual(current.images,())
        self.assertEqual(len(self.reads),4)

    def test_missing_integrity_not_upgraded_and_no_bytes_read(self):
        self.rows[self.before_id]['file_valid']=None
        self.rows[self.after_id]['file_valid']=False
        result=self.factory(self.repo,None,self.order,self.sub,include_images=True)
        self.assertIsNone(result.before_photos[0].file_valid)
        self.assertEqual(result.images,());self.assertEqual(self.reads,[])

    def test_foreign_binding_cannot_be_normalized(self):
        from app.ai.models import InputValidationError
        self.rows[self.after_id]['submission_id']=uid(99)
        with self.assertRaises(InputValidationError):
            self.factory(self.repo,None,self.order,self.sub,include_images=True)

    def test_before_does_not_invent_submission_or_revision(self):
        from app.ai.models import InputValidationError
        self.rows[self.before_id]['assignment_revision']=1
        with self.assertRaises(InputValidationError):
            self.factory(self.repo,None,self.order,self.sub,include_images=True)
