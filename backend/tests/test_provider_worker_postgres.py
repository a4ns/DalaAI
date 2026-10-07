"""REAL PostgreSQL state/atomicity tests, fake model and physical-verifier fixture.

Does not prove real model behavior or actual private-blob integrity. Each test
owns an independent random schema via the existing authorized disposable DSN.
"""
import asyncio
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import test_persistence_postgres as fixture
from test_model_adapter import FakeTransport,response
from app.ai.model_adapter import EgressApproval,ModelAdapter,prepare_input
from app.ai.model_budget import BudgetPolicy,SqliteBudgetLedger
from app.ai.openai_runtime import openai_demo_settings
from app.jobs.provider_worker import ProviderAssessmentWorker,ProviderJobRepository
from app.persistence.postgres import PostgresReferences


class ProviderWorkerPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixture.PostgresCommandTests.setUpClass.__func__(cls)
    for _name in ('connect','drop_schema','query','run_command','create','action','start','stage','submit','review'):
        locals()[_name]=getattr(fixture.PostgresCommandTests,_name)

    def setUp(self):
        fixture.PostgresCommandTests.setUp(self)
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        settings=openai_demo_settings(timeout_seconds=.1)
        self.transport=FakeTransport(response())
        self.ledger=SqliteBudgetLedger(Path(self.tmp.name)/'budget.sqlite',BudgetPolicy('pg-test',1000,100,60,1))
        self.adapter=ModelAdapter(settings=settings,transport=self.transport,ledger=self.ledger)
        # TEST ONLY verifier fixture: DB rows stand in for separately verified
        # synthetic bytes. Production MUST inject actual private-store verifier.
        self.worker=ProviderAssessmentWorker(self.connect,adapter=self.adapter,
            domain_clock=self.domain,real_clock=self.real,references_factory=PostgresReferences)

    def submitted(self):
        order=self.start()
        photo=self.stage(owner=fixture.EXECUTOR,purpose='after',order_id=order,revision=1)
        result,_=self.submit(order,photos=(photo,))
        return order,result.body['submission_id'],photo

    def authorize_claim(self):
        claim=self.worker.claim_one()
        prepared=self.worker.prepare(claim)
        p=prepare_input(prepared.data,prepared.context,images=prepared.assets.images,
                        before_photos=prepared.assets.before_photos)
        self.adapter.approval=EgressApproval('pg-test',self.adapter.settings.fingerprint,
            frozenset({p.payload_hash}),self.real.now()+timedelta(hours=1))
        return claim,prepared

    def compute(self,prepared):
        return asyncio.run(self.adapter.assess(prepared.data,prepared.context,
            images=prepared.assets.images,before_photos=prepared.assets.before_photos,now=self.real.now()))

    def test_model_actual_mode_metadata_provenance_without_state_transition(self):
        order,sub,_=self.submitted();claim,prepared=self.authorize_claim()
        candidate=self.compute(prepared)
        self.domain.value += timedelta(hours=1)  # Business advance while provider candidate was in flight.
        result=self.worker.complete(claim,candidate)
        self.assertEqual(result.state,'done')
        a=self.query('SELECT * FROM ai_assessments')[0]
        self.assertEqual(a['created_at'],self.domain.now())
        self.assertEqual(a['mode'],'model');self.assertIsNone(a['score']);self.assertIsNone(a['fallback_reason'])
        self.assertEqual(a['model_version'],self.adapter.settings.model_version)
        self.assertEqual(self.query('SELECT status,version FROM orders')[0],{'status':'ai_review','version':5})
        self.assertEqual(self.query('SELECT * FROM reviews'),[])
        e=self.query("SELECT * FROM order_events WHERE kind='order.assessment_recorded'")[0]
        self.assertEqual(e['occurred_at'],self.domain.now())
        self.assertEqual(e['recorded_at'],self.real.now())
        self.assertEqual(e['details']['mode'],'model')
        self.assertEqual(e['details']['provider_provenance']['payload_sha256'],candidate.payload_hash)
        self.assertEqual(self.query('SELECT state FROM ai_jobs')[0]['state'],'done')

    def test_default_unverified_physical_refs_never_egress(self):
        self.submitted()
        self.worker=ProviderAssessmentWorker(self.connect,adapter=self.adapter,
            domain_clock=self.domain,real_clock=self.real)
        claim,prepared=self.authorize_claim()
        candidate=self.compute(prepared)
        self.worker.complete(claim,candidate)
        self.assertEqual(self.transport.calls,[])
        self.assertEqual(self.query('SELECT mode FROM ai_assessments')[0]['mode'],'rules_fallback')

    def test_late_physical_evidence_change_discards_model(self):
        _,_,photo=self.submitted();claim,prepared=self.authorize_claim();candidate=self.compute(prepared)
        self.query('UPDATE photos SET file_valid=NULL WHERE id=%s RETURNING id',(photo,))
        self.worker.complete(claim,candidate)
        a=self.query('SELECT * FROM ai_assessments')[0]
        self.assertEqual(a['mode'],'rules_fallback');self.assertIsNone(a['model'])
        self.assertEqual(self.query('SELECT status FROM orders')[0]['status'],'ai_review')

    def test_reassignment_during_provider_archives_only_stale_fallback(self):
        order,_,_=self.submitted();claim,prepared=self.authorize_claim();candidate=self.compute(prepared)
        self.action(order,4,'reassign',fixture.MASTER,{'assignment':{'executor_id':fixture.OTHER,'brigade_id':None},'reason':'Synthetic reassignment'})
        result=self.worker.complete(claim,candidate)
        self.assertTrue(result.stale)
        self.assertEqual(self.query('SELECT mode,stale FROM ai_assessments')[0],{'mode':'rules_fallback','stale':True})
        self.assertEqual(self.query("SELECT * FROM order_events WHERE kind='order.assessment_recorded'"),[])
        self.assertEqual(self.query('SELECT status,version FROM orders')[0],{'status':'issued','version':5})

    def test_lease_expiry_after_provider_persists_nothing(self):
        self.submitted();claim,prepared=self.authorize_claim();candidate=self.compute(prepared)
        self.domain.value += timedelta(days=3)
        self.real.value=claim.lease_until
        self.assertEqual(self.worker.complete(claim,candidate).state,'lost_lease')
        self.assertEqual(self.query('SELECT * FROM ai_assessments'),[])
        self.assertEqual(self.query('SELECT version FROM orders')[0]['version'],4)
        self.assertEqual(self.ledger.counters()['calls_reserved'],1)

    def test_final_lease_failure_rolls_back_assessment_event_and_version(self):
        self.submitted();claim,prepared=self.authorize_claim();candidate=self.compute(prepared)
        def slow_business_read():
            self.real.value=claim.lease_until
            return self.domain.value
        with patch.object(self.domain,'now',side_effect=slow_business_read):
            self.assertEqual(self.worker.complete(claim,candidate).state,'lost_lease')
        self.assertEqual(self.query('SELECT * FROM ai_assessments'),[])
        self.assertEqual(self.query("SELECT * FROM order_events WHERE kind='order.assessment_recorded'"),[])
        self.assertEqual(self.query('SELECT version FROM orders')[0]['version'],4)
        self.assertEqual(self.query('SELECT state FROM ai_jobs')[0]['state'],'running')

    def test_repeat_complete_is_noop_and_cannot_double_publish(self):
        self.submitted();claim,prepared=self.authorize_claim();candidate=self.compute(prepared)
        self.worker.complete(claim,candidate)
        self.assertEqual(self.worker.complete(claim,candidate).state,'lost_lease')
        self.assertEqual(len(self.query('SELECT * FROM ai_assessments')),1)
        self.assertEqual(len(self.query("SELECT * FROM order_events WHERE kind='order.assessment_recorded'")),1)
        self.assertEqual(self.query('SELECT version FROM orders')[0]['version'],5)

    def test_unconfigured_async_run_once_finishes_labeled_fallback(self):
        self.submitted()
        result=asyncio.run(self.worker.run_once())
        self.assertEqual(result.state,'done')
        self.assertEqual(self.transport.calls,[])
        self.assertEqual(self.query('SELECT mode,model,score FROM ai_assessments')[0],
                         {'mode':'rules_fallback','model':None,'score':None})
