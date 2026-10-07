"""Offline operator-policy tests. All transport replies are synthetic fixtures."""
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from app.ai.demo_policy import (build_demo_policy,load_demo_policy,build_interactive_demo_policy,
    load_interactive_demo_policy,PROCESSING_DISCLOSURE)
from app.ai.model_adapter import (ModelAdapter,EgressApproval,SyntheticDemoContext,DemoProjectContext,
    DemoSubmissionContext,SyntheticImage,prepare_input,finalize_candidate,BeforePhotoEvidence)
from app.ai.model_budget import SqliteBudgetLedger
from app.ai.openai_runtime import openai_demo_settings,openai_demo_budget
from app.ai.image_derivation import derive_model_png
from app.ai.models import InputValidationError
from app.photos.validation import decode_raster
import test_model_adapter as fixture
import test_camera_derivation as camera_fixture
import test_provider_worker_unit as worker_fixture


class DemoPolicyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.d,self.c=fixture.good();self.settings=openai_demo_settings(timeout_seconds=.1)
        self.ledger=SqliteBudgetLedger(self.root/'budget.sqlite',openai_demo_budget())
        self.project=DemoProjectContext('DalaAI','demo-2026-10')
        self.policy=build_interactive_demo_policy(project_id=self.project.project_id,
            instance_id=self.project.instance_id,expires_at=fixture.NOW+timedelta(days=1),settings=self.settings)
        self.grant=load_interactive_demo_policy(self.policy,settings=self.settings,ledger=self.ledger,
                                              project_context=self.project,runtime_mode='demo')
        self.transport=fixture.FakeTransport()
        self.adapter=ModelAdapter(settings=self.settings,transport=self.transport,
                                  approval=self.grant,ledger=self.ledger)

    def request_context(self,data=None):
        d=data or self.d
        return DemoSubmissionContext(self.project.project_id,self.project.instance_id,
            d.order_id,d.submission_id,d.assignment_revision,fixture.uid(500))

    async def test_interactive_edited_text_no_content_rehash_required(self):
        d=replace(self.d,work_description='Отрегулирован зазор; крепление проверено после повторного осмотра')
        r=await self.adapter.assess(d,self.c,now=fixture.NOW,request_context=self.request_context(d))
        self.assertIsNotNone(r.observation);self.assertEqual(len(self.transport.calls),1)
        self.assertEqual(r.source_provenance,'authenticated_demo_submission_content_unverified')
        self.assertNotIn('synthetic',r.source_provenance)

    async def test_new_runtime_ids_continue_under_same_project_policy(self):
        d=replace(self.d,order_id=fixture.uid(101),submission_id=fixture.uid(102))
        c=replace(self.c,current_order_id=d.order_id,current_submission_id=d.submission_id,
                  photos=tuple(replace(p,order_id=d.order_id,submission_id=d.submission_id) for p in self.c.photos))
        r=await self.adapter.assess(d,c,now=fixture.NOW,request_context=self.request_context(d))
        self.assertIsNotNone(r.observation)
        self.assertNotEqual(prepare_input(d,c).snapshot_hash,prepare_input(self.d,self.c).snapshot_hash)

    async def test_recompressed_camera_content_no_manual_allowlist(self):
        # Two different in-memory camera encodings, both actual trusted current
        # source inputs for this test; authorization is project-scoped, not hashes.
        for size in [(320,240),(321,241)]:
            raw=camera_fixture.raster('JPEG',size=size)
            clean=decode_raster(raw)
            png,_=derive_model_png(clean.data,photo_id=fixture.AFTER,source_mime=clean.mime_type,
                                   source_sha256=clean.sha256)
            r=await self.adapter.assess(self.d,self.c,images=(SyntheticImage(fixture.AFTER,'after',png),),
                now=fixture.NOW,request_context=self.request_context())
            self.assertIsNotNone(r.observation)
        self.assertEqual(len(self.transport.calls),2)
        self.assertNotEqual(self.transport.calls[0]['body'],self.transport.calls[1]['body'])

    async def test_no_request_context_never_egresses(self):
        r=await self.adapter.assess(self.d,self.c,now=fixture.NOW)
        self.assertEqual(r.fallback_reason,'provider_not_configured');self.assertEqual(self.transport.calls,[])

    async def test_wrong_project_instance_submission_revision_or_expired_policy_blocks(self):
        ctx=self.request_context()
        for bad in [replace(ctx,project_id='Other'),replace(ctx,instance_id='other'),
                    replace(ctx,submission_id=fixture.uid(900)),replace(ctx,order_id=fixture.uid(901)),
                    replace(ctx,assignment_revision=2)]:
            r=await self.adapter.assess(self.d,self.c,now=fixture.NOW,request_context=bad)
            self.assertIsNone(r.observation)
        self.adapter.approval=replace(self.grant,expires_at=fixture.NOW)
        r=await self.adapter.assess(self.d,self.c,now=fixture.NOW,request_context=ctx)
        self.assertIsNone(r.observation);self.assertEqual(self.transport.calls,[])

    async def test_project_policy_never_overrides_current_required_evidence(self):
        for c in [replace(self.c,current_assignment_revision=2),replace(self.c,photos=()),
                  replace(self.c,current_status='closed')]:
            r=await self.adapter.assess(self.d,c,now=fixture.NOW,request_context=self.request_context())
            self.assertIsNone(r.observation)
        self.assertEqual(self.transport.calls,[])
        self.assertEqual(self.ledger.counters()['calls_reserved'],0)

    async def test_optional_exact_fixture_mode_is_id_independent_and_content_strict(self):
        payload=prepare_input(self.d,self.c)
        context=SyntheticDemoContext('fixture-set','v1')
        grant=EgressApproval(self.ledger.policy.approval_id,self.settings.fingerprint,frozenset(),
            fixture.NOW+timedelta(days=1),False,frozenset({payload.content_hash}),context.dataset_id,context.dataset_version)
        adapter=ModelAdapter(settings=self.settings,transport=self.transport,approval=grant,
                             ledger=self.ledger,demo_context=context)
        d=replace(self.d,order_id=fixture.uid(101),submission_id=fixture.uid(102))
        c=replace(self.c,current_order_id=d.order_id,current_submission_id=d.submission_id,
                  photos=tuple(replace(p,order_id=d.order_id,submission_id=d.submission_id) for p in self.c.photos))
        self.assertEqual(prepare_input(d,c).content_hash,payload.content_hash)
        r=await adapter.assess(d,c,now=fixture.NOW);self.assertIsNotNone(r.observation)
        r=await adapter.assess(replace(d,work_description='unapproved text'),c,now=fixture.NOW)
        self.assertIsNone(r.observation);self.assertEqual(len(self.transport.calls),1)

    def test_policy_loader_refuses_production_other_scope_and_budget_expansion(self):
        for mode in ['health','production','']:
            with self.assertRaises(InputValidationError):
                load_interactive_demo_policy(self.policy,settings=self.settings,ledger=self.ledger,
                                              project_context=self.project,runtime_mode=mode)
        for change in [{'purpose':'arbitrary_prompt'},{'total_microusd':100_000_000},
                       {'authenticated_submissions_only':False},{'project_id':'Other'},
                       {'source_provenance':'synthetic'},{'processing_disclosure':''}]:
            with self.assertRaises(InputValidationError):
                load_interactive_demo_policy(dict(self.policy,**change),settings=self.settings,ledger=self.ledger,
                                              project_context=self.project,runtime_mode='demo')

    def test_one_time_fixture_builder_matches_real_upload_sanitization_and_derivation(self):
        raw=camera_fixture.raster('JPEG')
        (self.root/'approved.jpg').write_bytes(raw)
        manifest={'schema_version':'1','dataset_id':'approved','dataset_version':'v1','cases':[{
            'problem_text':self.d.problem_description,'work_text':self.d.work_description,
            'before':None,'after':{'path':'approved.jpg','sha256':sha256(raw).hexdigest()}}]}
        policy=build_demo_policy(manifest,fixture_root=self.root,expires_at=fixture.NOW+timedelta(days=1),settings=self.settings)
        sanitized=decode_raster(raw)
        png,_=derive_model_png(sanitized.data,photo_id=fixture.AFTER,source_mime=sanitized.mime_type,
                               source_sha256=sanitized.sha256)
        payload=prepare_input(self.d,self.c,images=(SyntheticImage(fixture.AFTER,'after',png),))
        self.assertEqual(policy['content_hashes'],[payload.content_hash])
        grant=load_demo_policy(policy,settings=self.settings,ledger=self.ledger,
                              demo_context=SyntheticDemoContext('approved','v1'))
        self.assertEqual(grant.synthetic_content_hashes,frozenset({payload.content_hash}))
        self.assertNotIn('PRIVATE',str(policy))

    def test_fixture_builder_rejects_path_escape_hash_mismatch_and_unreviewed_shape(self):
        raw=camera_fixture.raster('JPEG');(self.root/'approved.jpg').write_bytes(raw)
        case={'problem_text':self.d.problem_description,'work_text':self.d.work_description,
              'before':None,'after':{'path':'approved.jpg','sha256':'0'*64}}
        manifest={'schema_version':'1','dataset_id':'approved','dataset_version':'v1','cases':[case]}
        with self.assertRaises(InputValidationError):
            build_demo_policy(manifest,fixture_root=self.root,expires_at=fixture.NOW+timedelta(days=1))
        manifest['cases'][0]['after']={'path':'/etc/hosts','sha256':'0'*64}
        with self.assertRaises(InputValidationError):
            build_demo_policy(manifest,fixture_root=self.root,expires_at=fixture.NOW+timedelta(days=1))


class InteractiveWorkerTests(unittest.IsolatedAsyncioTestCase):
    setUp=worker_fixture.ProviderWorkerUnitTests.setUp

    async def test_worker_derives_authenticated_context_from_server_submission(self):
        project=DemoProjectContext('DalaAI','isolated-demo')
        self.worker.demo_project=project
        self.store.sub.submitted_by=fixture.uid(77)
        self.worker.adapter.approval=EgressApproval('test',self.worker.adapter.settings.fingerprint,
            frozenset(),fixture.NOW+timedelta(days=1),True,interactive_project_id=project.project_id,
            interactive_instance_id=project.instance_id,allow_authenticated_demo_submissions=True)
        # Simulates ordinary new work text already accepted by the real command
        # service; no new content hash or per-order policy update is made.
        self.store.sub.payload.work_description='Edited interactive demo work'
        r=await self.worker.run_once()
        self.assertEqual(r.state,'done');self.assertEqual(self.store.effects[0][1][3],'model')
        provenance=self.store.effects[2][1]['details']['provider_provenance']
        self.assertEqual(provenance['demo_project_id'],'DalaAI')
        self.assertEqual(provenance['source_provenance'],'authenticated_demo_submission_content_unverified')
        self.assertNotIn(fixture.uid(77),str(self.transport.calls))

    async def test_missing_server_identity_cannot_enable_project_egress(self):
        self.worker.demo_project=DemoProjectContext('DalaAI','isolated-demo')
        self.store.sub.submitted_by=None
        r=await self.worker.run_once()
        self.assertEqual(r.state,'failed');self.assertEqual(self.transport.calls,[])


class NightBudgetBoundaryTests(unittest.TestCase):
    def test_reservation_start_selects_night_bucket_and_global_never_resets(self):
        from app.ai.model_budget import BudgetPolicy,BudgetBlocked
        with TemporaryDirectory() as directory:
            path=Path(directory)/'budget.sqlite'
            p=BudgetPolicy('boundary',500,100,60,1,'night',200,period_ends_at=1000)
            ledger=SqliteBudgetLedger(path,p)
            for now in [998,999]:
                token=ledger.reserve(now=now);ledger.finish(token,'valid')
            with self.assertRaises(BudgetBlocked):ledger.reserve(now=999.9)
            # A retry/new request at exactly 09:00 local is day-charged, while
            # the first two full reservations remain in the global total.
            for now in [1000,1001,1002]:
                ledger=SqliteBudgetLedger(path,p)
                token=ledger.reserve(now=now);ledger.finish(token,'valid')
            with self.assertRaises(BudgetBlocked):ledger.reserve(now=1003)
            self.assertEqual(ledger.counters()['reserved_upper_bound_microusd'],500)
            self.assertEqual(ledger.counters()['period_reserved_upper_bound_microusd'],200)

    def test_night_cap_is_shared_across_period_labels_and_report_callers(self):
        from app.ai.model_budget import BudgetPolicy,BudgetBlocked
        with TemporaryDirectory() as directory:
            path=Path(directory)/'budget.sqlite'
            p=BudgetPolicy('shared-project',1000,100,60,1,'closure-label',100,period_ends_at=1000)
            ledger=SqliteBudgetLedger(path,p)
            token=ledger.reserve(now=999);ledger.finish(token,'valid')
            reports=SqliteBudgetLedger(path,replace(p,period_id='report-label'))
            with self.assertRaises(BudgetBlocked):reports.reserve(now=999.5)
            self.assertEqual(reports.counters()['period_reserved_upper_bound_microusd'],100)
            token=reports.reserve(now=1000);reports.finish(token,'valid')
            self.assertEqual(reports.counters()['reserved_upper_bound_microusd'],200)

    def test_morning_key_time_and_project_day_default_policy_remain_valid(self):
        from datetime import datetime,timezone
        from app.ai.openai_runtime import NIGHT_ENDS_AT,DEFAULT_DEMO_POLICY_EXPIRES_AT
        self.assertEqual(NIGHT_ENDS_AT,datetime(2026,10,8,4,0,tzinfo=timezone.utc))
        self.assertEqual(DEFAULT_DEMO_POLICY_EXPIRES_AT,datetime(2026,10,8,18,59,tzinfo=timezone.utc))
        for hour in [3,4,12,18]:
            self.assertGreater(DEFAULT_DEMO_POLICY_EXPIRES_AT,datetime(2026,10,8,hour,0,tzinfo=timezone.utc))


class AutomaticCameraSelectionTests(unittest.TestCase):
    setUp=camera_fixture.PrivateCameraFactoryTests.setUp

    def test_current_bound_pair_needs_no_per_submission_selection_manifest(self):
        from app.jobs.provider_worker import CameraAssetsFactory
        factory=CameraAssetsFactory(self.verifier.read)
        self.assertEqual(factory.selections,{})
        result=factory(self.repo,None,self.order,self.sub,include_images=True)
        self.assertFalse(result.derivation_failed);self.assertEqual(len(result.images),2)
        self.sub.id=fixture.uid(801)
        self.rows[fixture.AFTER]['submission_id']=self.sub.id
        again=factory(self.repo,None,self.order,self.sub,include_images=True)
        self.assertFalse(again.derivation_failed);self.assertEqual(len(again.images),2)
        self.assertEqual(factory.selections,{})
