"""Source tests use fake/recorded responses only; no live provider/PG/browser."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.ai.demo_policy import build_interactive_demo_policy
from app.ai.model_adapter import DemoProjectContext, InputValidationError, TransportResponse
from app.ai.model_budget import SqliteBudgetLedger
from app.ai.openai_runtime import openai_demo_budget, openai_demo_settings
from app.analytics.c3_facts import build_facts
from app.analytics.c3_repository import RuntimeReportService
from app.core.auth_boundary import AuthenticationRequired, AuthContext, RequestProtection, SESSION_COOKIE_NAME, SessionRecord
from app.core.auth_policy import Principal, Role
from app.orders.models import DomainError, OrderType
from app.reports.ai_summary import (MAX_OUTPUT_BYTES, SCHEMA_VERSION, SELECTION_VERSION, ReportAttemptFence,
    ReportModelAdapter, SummaryRequest, SummaryService, build_request, parse_response, prepare_report,
    render_summary, validate_selection)
from app.reports.ai_summary_routes import create_ai_summary_router
from test_c3_facts import PERIOD, fixture

NOW = datetime(2026, 10, 8, 3, tzinfo=timezone.utc)
ORIGIN = 'https://reports.test'
PRINCIPAL = Principal(str(uuid4()), Role.MASTER, frozenset({str(uuid4())}))

class Clock:
    def __init__(self, value=NOW): self.value = value
    def now(self): return self.value

def request(**overrides):
    value = {'operation_id': str(uuid4()), 'start': PERIOD.start.isoformat(),
             'end': PERIOD.end.isoformat(), 'report_kind': 'shift'}
    value.update(overrides)
    return SummaryRequest.parse(json.dumps(value).encode())

def prepared(kind='shift', rows=None):
    return prepare_report(build_facts(rows or fixture(), PERIOD), None, kind)

def selection():
    return {'schema_version': SELECTION_VERSION, 'highlights': ['m_issued_orders', 'm_closed_orders'], 'recommendations': []}

def envelope(selected=None, **changes):
    value = {'model': openai_demo_settings().model_version, 'choices': [{'finish_reason': 'stop',
        'message': {'role': 'assistant', 'content': json.dumps(selected or selection())}}]}
    value.update(changes)
    return TransportResponse(200, json.dumps(value).encode())

class RecordedTransport:
    def __init__(self, response=None, effect=None):
        self.response, self.effect, self.calls, self.bodies = response or envelope(), effect, 0, []
    async def post_json(self, **kwargs):
        self.calls += 1; self.bodies.append(kwargs['body'])
        if self.effect is not None: self.effect()
        return self.response

class GroundedFactsTests(unittest.TestCase):
    def test_strict_request_and_period_bounds(self):
        self.assertEqual(request().report_kind, 'shift')
        for change in ({'role':'master'}, {'prompt':'invent'}, {'operation_id':'x'},
                {'start':'2026-09-02T00:00:00'}, {'report_kind':'all'}, {'end':'2026-09-05T00:00:00Z'},
                {'end':'2027-09-05T00:00:00Z','report_kind':'history'}):
            with self.subTest(change=change), self.assertRaises(DomainError): request(**change)
        with self.assertRaises(DomainError): SummaryRequest.parse(b'{"start":"a","start":"b"}')

    def test_c111_exact_human_scores_missing_cohorts_sample_and_snapshot_scope(self):
        bundle = prepared(); index = {f['fact_id']:f for f in bundle.model_facts}
        self.assertEqual(index['m_human_score']['value'], '60.000000000000')
        self.assertEqual(index['m_human_score']['missing'], 1)
        self.assertTrue(index['m_human_score']['small_sample'])
        self.assertEqual(index['m_overdue_active']['scope'], 'domain_snapshot')
        self.assertEqual(index['m_closed_orders']['scope'], 'period')
        selected = {'schema_version':SELECTION_VERSION,'highlights':['m_human_score'],
            'recommendations':[{'code':'complete_human_scores','fact_ids':['m_human_score']}]}
        body = render_summary(request(), bundle, selection=selected, generated_at_real=NOW)
        self.assertIn('мастера',body['summary']); self.assertTrue(body['advisory'])
        self.assertEqual(body['highlights'][0]['source_ids'],['r1','r22','r3','r82'])
        self.assertIsNone(body['model']); self.assertEqual(body['mode'],'deterministic_fallback')

    def test_empty_and_partial_are_not_invented(self):
        rows=fixture(); bundle=prepared(rows=replace(rows,orders=(),submissions=(),reviews=()))
        score=next(f for f in bundle.model_facts if f['fact_id']=='m_human_score')
        self.assertIsNone(score['value']); self.assertEqual(score['status'],'no_cohort')
        with self.assertRaises(DomainError):
            prepared(rows=replace(rows,provenance=replace(rows.provenance,coverage='partial_keyset')))
        with self.assertRaises(InputValidationError):
            validate_selection({'schema_version':SELECTION_VERSION,'highlights':['m_overdue_active'],
                'recommendations':[{'code':'review_overdue','fact_ids':['m_overdue_active']}]},bundle)

    def test_history_deduplicates_order_attempts_and_period_scope(self):
        rows=fixture(); rows=replace(rows,orders=tuple(replace(o,type=OrderType.UNPLANNED) for o in rows.orders),
            submissions=tuple(replace(s,payload=replace(s.payload,after_photo_ids=('photo-'+s.id,))) for s in rows.submissions))
        bundle=prepared('history',rows); items={f['fact_id']:f for f in bundle.model_facts}
        self.assertEqual(items['unplanned_equipment_1']['value'],'6')
        self.assertEqual(items['repeated_code_1']['value'],'4')
        ref=next(f for f in bundle.facts if f['fact_id']=='repeated_code_1')
        self.assertEqual(ref['source_ids'],['o2','o3','o4','o8'])
        self.assertIn('repeat_fault_7d:unsupported_inputs',bundle.report['unavailable_reasons'])

    def test_outbound_omits_ids_names_comments_labels_and_photos(self):
        body=build_request(openai_demo_settings(),prepared('history')); wire=json.dumps(body)
        for secret in ('equipment-1','worker-1','current-executor','material-1','<script>','Выполнено',
                       'Смазка','source_ids','source_ref','image_url'):
            self.assertNotIn(secret,wire)
        self.assertIs(body['store'],False); self.assertEqual(body['max_completion_tokens'],400)
        self.assertNotIn('tools',body)

    def test_historical_unavailable_photos_and_synthetic_label_survive(self):
        evidence={'status':'synthetic_historical_evidence_unavailable','physical_evidence_verified':False}
        bundle=prepare_report(build_facts(fixture(),PERIOD),evidence,'history')
        body=render_summary(request(report_kind='history'),bundle,generated_at_real=NOW)
        self.assertEqual(body['provenance']['historical_evidence'],evidence)
        self.assertIn('Синтетические',body['summary']); self.assertIn('фото недоступны',body['summary'])

    def test_forged_numbers_ids_prose_duplicate_highlight_and_wrong_fact_rejected(self):
        good=selection()
        for obj in (dict(good,highlights=['foreign-id']),dict(good,summary='999 repaired'),dict(good,numbers=[99]),
                dict(good,highlights=[]),dict(good,highlights=['m_closed_orders','m_closed_orders']),
                dict(good,recommendations=[{'code':'review_overdue','fact_ids':['m_closed_orders']}]),
                dict(good,recommendations=[{'code':'review_pending','fact_ids':['m_awaiting_review']}])):
            with self.subTest(obj=obj),self.assertRaises(InputValidationError): validate_selection(obj,prepared())

    def test_malformed_wrapper_refusal_tools_duplicate_json_and_unverified_model(self):
        cases=[TransportResponse(200,b'{"model":"a","model":"b"}'),envelope(model='unverified'),
               TransportResponse(200,b'NaN'),TransportResponse(200,b'x'*40000)]
        for field in ('refusal','tool_calls','function_call'):
            obj=json.loads(envelope().body); obj['choices'][0]['message'][field]='forbidden'
            cases.append(TransportResponse(200,json.dumps(obj).encode()))
        obj=json.loads(envelope().body); obj['choices'][0]['finish_reason']='length'
        cases.append(TransportResponse(200,json.dumps(obj).encode()))
        for response in cases:
            with self.subTest(response=response),self.assertRaises(InputValidationError):
                parse_response(response,openai_demo_settings(),prepared())

    def test_recorded_label_response_bound_and_false_live_mode_rejected(self):
        body=render_summary(request(),prepared(),selection=selection(),mode='recorded_fixture',
            fallback_reason=None,model=openai_demo_settings().model,generated_at_real=NOW)
        self.assertIn('не живой OpenAI',body['label']); self.assertLess(len(json.dumps(body).encode()),MAX_OUTPUT_BYTES)
        with self.assertRaises(ValueError): render_summary(request(),prepared(),mode='openai',generated_at_real=NOW)

class AdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=str(Path(self.tmp.name)/'shared.sqlite3')
        self.ledger=SqliteBudgetLedger(self.path,openai_demo_budget())
        self.clock,self.project=Clock(),DemoProjectContext('dalaai','isolated-demo')
        self.settings=openai_demo_settings()
        self.policy=build_interactive_demo_policy(project_id='dalaai',instance_id='isolated-demo',
            expires_at=NOW+timedelta(hours=1),include_grounded_reports=True)
        self.transport=RecordedTransport(); self.rechecks=0
    async def reauthorize(self): self.rechecks+=1
    def adapter(self,**changes):
        args=dict(settings=self.settings,transport=self.transport,policy=self.policy,ledger=self.ledger,
            project_context=self.project,runtime_mode='demo',real_clock=self.clock)
        args.update(changes); return ReportModelAdapter.from_operator_policy(**args)
    async def run_adapter(self,adapter=None,req=None,principal=PRINCIPAL,reauthorize=None):
        return await (adapter or self.adapter()).summarize(req or request(),prepared(),principal,
            reauthorize=reauthorize or self.reauthorize)
    def fences(self):
        with sqlite3.connect(self.path) as db:
            found=db.execute("SELECT name FROM sqlite_master WHERE name='ai_report_attempt_v1'").fetchone()
            return db.execute('SELECT count(*) FROM ai_report_attempt_v1').fetchone()[0] if found else 0

    async def test_recorded_response_same_shared_budget_and_restart_idempotency(self):
        req=request(); result=await self.run_adapter(req=req)
        self.assertEqual(result['mode'],'recorded_fixture'); self.assertIsNone(result['fallback_reason'])
        self.assertEqual(self.transport.calls,1); self.assertGreaterEqual(self.rechecks,2)
        self.assertEqual(self.ledger.counters()['reserved_upper_bound_microusd'],420000)
        restarted=self.adapter(ledger=SqliteBudgetLedger(self.path,openai_demo_budget()))
        self.assertEqual((await self.run_adapter(restarted,req=req))['fallback_reason'],'operation_already_attempted')
        self.assertEqual(self.transport.calls,1); self.assertEqual(self.ledger.counters()['calls_reserved'],1)

    async def test_missing_key_legacy_and_forged_policy_do_not_consume_attempt(self):
        req=request(); legacy=build_interactive_demo_policy(project_id='dalaai',instance_id='isolated-demo')
        for adapter in (ReportModelAdapter(),self.adapter(policy=legacy),
                self.adapter(policy={**self.policy,'total_microusd':100000000}),
                self.adapter(policy={**self.policy,'processing_disclosure':legacy['processing_disclosure']}),
                self.adapter(runtime_mode='production'),self.adapter(transport=None)):
            self.assertIn((await self.run_adapter(adapter,req=req))['fallback_reason'],
                {'provider_not_configured','report_purpose_not_approved','provider_policy_unavailable'})
        self.assertEqual(self.fences(),0); self.assertEqual(self.ledger.counters()['calls_reserved'],0)
        await self.run_adapter(req=req); self.assertEqual(self.transport.calls,1)

    async def test_expired_policy_and_unauthorized_request_do_not_claim(self):
        adapter=self.adapter(); self.clock.value=NOW+timedelta(hours=2)
        self.assertEqual((await self.run_adapter(adapter))['fallback_reason'],'provider_policy_expired')
        self.assertEqual(self.fences(),0); self.clock.value=NOW
        async def denied(): raise AuthenticationRequired()
        with self.assertRaises(AuthenticationRequired): await self.run_adapter(reauthorize=denied)
        self.assertEqual(self.fences(),0); self.assertEqual(self.transport.calls,0)

    async def test_changed_payload_scope_policy_instance_cannot_recharge_operation(self):
        req=request(); await self.run_adapter(req=req)
        for changed in (replace(req,report_kind='history'),replace(req,start='2026-09-01T12:00:00Z')):
            with self.assertRaises(DomainError) as caught: await self.run_adapter(req=changed)
            self.assertEqual(caught.exception.code,'OPERATION_ID_REUSED')
        with self.assertRaises(DomainError):
            await self.run_adapter(req=req,principal=replace(PRINCIPAL,section_ids=frozenset({str(uuid4())})))
        with self.assertRaises(DomainError):
            await self.run_adapter(self.adapter(policy={**self.policy,'expires_at':(NOW+timedelta(minutes=40)).isoformat()}),req=req)
        project=DemoProjectContext('dalaai','other-demo')
        policy=build_interactive_demo_policy(project_id='dalaai',instance_id='other-demo',
            expires_at=NOW+timedelta(hours=1),include_grounded_reports=True)
        with self.assertRaises(DomainError):
            await self.run_adapter(self.adapter(policy=policy,project_context=project),req=req)
        self.assertEqual(self.transport.calls,1)

    async def test_crash_claim_no_reclaim_and_capacity_fail_closed(self):
        h=lambda x:sha256(x.encode()).hexdigest(); fence=ReportAttemptFence(self.ledger)
        self.assertTrue(fence.claim(h('op'),h('body'),now=NOW.timestamp()))
        self.assertFalse(ReportAttemptFence(self.ledger).claim(h('op'),h('body'),now=NOW.timestamp()+999999))
        with patch.object(ReportAttemptFence,'ROW_CAP',1): result=await self.run_adapter()
        self.assertEqual(result['fallback_reason'],'report_attempt_capacity_exhausted')
        self.assertEqual(self.transport.calls,0); self.assertEqual(self.ledger.counters()['calls_reserved'],0)

    async def test_timeout_http_invalid_and_429_never_retry_or_refund(self):
        def timeout(): raise TimeoutError()
        cases=[(RecordedTransport(effect=timeout),'provider_timeout'),
            (RecordedTransport(TransportResponse(500,b'secret')),'provider_unavailable'),
            (RecordedTransport(TransportResponse(429,b'')),'provider_rate_limited'),
            (RecordedTransport(envelope(dict(selection(),highlights=['invented']))),'provider_invalid_response')]
        for transport,reason in cases:
            req=request(); result=await self.run_adapter(self.adapter(transport=transport),req=req)
            self.assertEqual(result['fallback_reason'],reason); self.assertEqual(result['reserved_upper_bound_microusd'],420000)
            self.assertEqual((await self.run_adapter(self.adapter(transport=transport),req=req))['fallback_reason'],'operation_already_attempted')
            self.assertEqual(transport.calls,1)
        self.assertEqual(self.ledger.counters()['calls_reserved'],4)

    async def test_closure_shared_concurrency_and_rate_not_bypassed(self):
        token=self.ledger.reserve(now=NOW.timestamp()); req=request()
        self.assertEqual((await self.run_adapter(req=req))['fallback_reason'],'provider_concurrency_limited')
        self.ledger.finish(token,'valid')
        self.assertEqual((await self.run_adapter(req=req))['fallback_reason'],'operation_already_attempted')
        for _ in range(4):
            token=self.ledger.reserve(now=NOW.timestamp()); self.ledger.finish(token,'valid')
        self.assertEqual((await self.run_adapter())['fallback_reason'],'provider_rate_limited')
        self.assertEqual(self.transport.calls,0)

    async def test_night_and_total_budget_caps(self):
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO model_budget_reservation VALUES(?,?,?,?,?,?)',
                (str(uuid4()),self.ledger.policy.approval_id,self.ledger.policy.period_id,NOW.timestamp()-3600,9800000,'valid'))
        self.assertEqual((await self.run_adapter())['fallback_reason'],'provider_period_budget_exhausted')
        self.clock.value=NOW+timedelta(hours=2); self.policy['expires_at']=(NOW+timedelta(hours=3)).isoformat()
        self.assertEqual((await self.run_adapter())['mode'],'recorded_fixture')
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO model_budget_reservation VALUES(?,?,?,?,?,?)',
                (str(uuid4()),self.ledger.policy.approval_id,self.ledger.policy.period_id,NOW.timestamp()-3500,39500000,'valid'))
        self.assertEqual((await self.run_adapter())['fallback_reason'],'provider_budget_exhausted')

    async def test_policy_expiry_during_call_discards_result(self):
        transport=RecordedTransport(effect=lambda:setattr(self.clock,'value',NOW+timedelta(hours=2)))
        result=await self.run_adapter(self.adapter(transport=transport))
        self.assertEqual(result['fallback_reason'],'provider_policy_expired'); self.assertNotIn('selection',result)

    async def test_auth_expiry_after_reservation_denies_egress(self):
        calls=0
        async def expires():
            nonlocal calls
            calls+=1
            if calls==2: raise AuthenticationRequired()
        req=request()
        with self.assertRaises(AuthenticationRequired): await self.run_adapter(req=req,reauthorize=expires)
        self.assertEqual(self.transport.calls,0); self.assertEqual(self.ledger.counters()['calls_reserved'],1)
        self.assertEqual((await self.run_adapter(req=req))['fallback_reason'],'operation_already_attempted')

    async def test_atomic_fence_race_only_one_claim(self):
        h=lambda x:sha256(x.encode()).hexdigest()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(ReportAttemptFence(self.ledger).claim,h('same'),h('body'),now=NOW.timestamp()) for _ in range(2)]
            self.assertEqual(sorted(f.result() for f in futures),[False,True])

class FakeDB:
    def __init__(self,sessions): self.sessions=sessions
    def __enter__(self): return self
    def __exit__(self,*args): return False
    @contextmanager
    def transaction(self):
        self.sessions.transactions+=1
        try: yield
        finally: self.sessions.transactions-=1
    def execute(self,*args): return None

class FakeSessions:
    def __init__(self):
        self.clock,self.protection,self.principal=Clock(),RequestProtection(ORIGIN),PRINCIPAL
        self.expires,self.transactions=NOW+timedelta(hours=1),0
    def _connection(self): return FakeDB(self)
    def _auth(self,db,handle):
        if handle!='valid' or self.clock.now()>=self.expires: raise AuthenticationRequired()
        return AuthContext(self.principal,SessionRecord(self.principal.user_id,NOW-timedelta(hours=1),self.expires,'csrf'))

class SummaryHTTPTests(unittest.TestCase):
    def setUp(self):
        self.sessions=FakeSessions()
        self.reports=RuntimeReportService(self.sessions,domain_clock=Clock(PERIOD.end),synthetic=True)
        self.service=SummaryService(self.reports)
        def capture(service,query,*,session_handle,project,**kwargs):
            service.sessions._auth(None,session_handle)
            return project(build_facts(fixture(),PERIOD),'json',None)
        self.mock_capture=patch.object(RuntimeReportService,'capture',capture)
        self.mock_capture.start(); self.addCleanup(self.mock_capture.stop)
        app=FastAPI(); app.include_router(create_ai_summary_router(self.service)); self.client=TestClient(app)
        req=request(); self.body={'operation_id':req.operation_id,'start':req.start,'end':req.end,'report_kind':req.report_kind}
        self.headers={'cookie':SESSION_COOKIE_NAME+'=valid','origin':ORIGIN,'x-csrf-token':'csrf'}
    def post(self,**kwargs):
        return self.client.post('/api/v1/reports/ai-summary',json=kwargs.pop('body',self.body),
            headers=kwargs.pop('headers',self.headers),**kwargs)

    def test_keyless_no_store_shape_and_no_get_generation(self):
        response=self.post(); self.assertEqual(response.status_code,200,response.text)
        body=response.json(); self.assertEqual(body['schema_version'],SCHEMA_VERSION)
        self.assertEqual(body['mode'],'deterministic_fallback'); self.assertEqual(body['fallback_reason'],'provider_not_configured')
        self.assertIn('no-store',response.headers['cache-control'])
        self.assertEqual(self.client.get('/api/v1/reports/ai-summary',headers=self.headers).status_code,405)

    def test_auth_csrf_origin_roles_and_forged_scope_body(self):
        for headers,expected in (({},401),({**self.headers,'cookie':SESSION_COOKIE_NAME+'=bad'},401),
                ({**self.headers,'cookie':self.headers['cookie']+'; '+self.headers['cookie']},401),
                ({**self.headers,'origin':'https://foreign.test'},403),({**self.headers,'x-csrf-token':'bad'},403)):
            self.assertEqual(self.post(headers=headers).status_code,expected)
        for role in (Role.EXECUTOR,Role.MANAGER,Role.ADMIN):
            self.sessions.principal=replace(PRINCIPAL,role=role); self.assertEqual(self.post().status_code,403)
        self.sessions.principal=PRINCIPAL
        self.assertEqual(self.post(body={**self.body,'section_id':'foreign'}).status_code,422)
        self.assertEqual(self.post(params={'role':'master'}).status_code,400)
        self.assertEqual(self.post(body={**self.body,'prompt':'x'*3000}).status_code,413)

    def test_bound_capture_refuses_changed_scope(self):
        def changed(service,query,*,session_handle,project,**kwargs):
            self.sessions.principal=replace(PRINCIPAL,section_ids=frozenset({str(uuid4())}))
            service.sessions._auth(None,session_handle)
            raise AssertionError('Bound scope should deny')
        with patch.object(RuntimeReportService,'capture',changed): self.assertEqual(self.post().status_code,403)

    def test_final_recheck_after_serialization_denies_expiry_and_scope_changes(self):
        from app.reports import ai_summary
        original=ai_summary.render_summary
        for change,expected in ((lambda:setattr(self.sessions.clock,'value',self.sessions.expires),401),
                (lambda:setattr(self.sessions,'principal',replace(PRINCIPAL,section_ids=frozenset({str(uuid4())}))),403)):
            self.sessions.clock.value=NOW; self.sessions.principal=PRINCIPAL
            def render(*args,**kwargs):
                result=original(*args,**kwargs); change(); return result
            with patch.object(ai_summary,'render_summary',render): response=self.post()
            self.assertEqual(response.status_code,expected); self.assertNotIn('highlights',response.json())

    def test_recorded_provider_runs_without_auth_transaction_and_final_revocation_hides_result(self):
        with TemporaryDirectory() as directory:
            ledger=SqliteBudgetLedger(Path(directory)/'shared.sqlite3',openai_demo_budget())
            policy=build_interactive_demo_policy(project_id='dalaai',instance_id='http-test',
                expires_at=NOW+timedelta(hours=1),include_grounded_reports=True)
            def during_provider():
                self.assertEqual(self.sessions.transactions,0)
                self.sessions.clock.value=self.sessions.expires
            transport=RecordedTransport(effect=during_provider)
            self.service.adapter=ReportModelAdapter.from_operator_policy(settings=openai_demo_settings(),
                transport=transport,policy=policy,ledger=ledger,project_context=DemoProjectContext('dalaai','http-test'),
                runtime_mode='demo',real_clock=self.sessions.clock)
            response=self.post()
            self.assertEqual(transport.calls,1)
            self.assertEqual(response.status_code,401)
            self.assertNotIn('summary',response.json())
            self.assertEqual(ledger.counters()['calls_reserved'],1)

    def test_response_size_cap_fails_closed(self):
        with patch('app.reports.ai_summary.MAX_OUTPUT_BYTES',10):
            response=self.post()
        self.assertEqual(response.status_code,422)
        self.assertNotIn('summary',response.json())

    def test_stalled_small_body_times_out_before_any_service_attempt(self):
        from starlette.requests import Request
        from unittest.mock import AsyncMock
        async def stalled_receive():
            await asyncio.sleep(1)
            return {'type':'http.request','body':b'{}','more_body':False}
        request=Request({'type':'http','method':'POST','path':'/api/v1/reports/ai-summary',
            'query_string':b'', 'headers':[(b'cookie',(SESSION_COOKIE_NAME+'=valid').encode()),
                                         (b'content-type',b'application/json')]},stalled_receive)
        router=create_ai_summary_router(self.service)
        endpoint=router.routes[0].endpoint
        with patch.object(self.service,'execute',new_callable=AsyncMock) as execute:
            with patch('app.reports.ai_summary_routes.MAX_BODY_READ_SECONDS',0.005):
                response=asyncio.run(endpoint(request))
            execute.assert_not_called()
        self.assertEqual(response.status_code,408)
        self.assertEqual(json.loads(response.body)['code'],'REQUEST_TIMEOUT')
        self.assertNotIn('summary',json.loads(response.body))
