"""Local adapter/dispatcher shape checks, not PostgreSQL or live delivery proof."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from uuid import uuid4

from app.notify.models import DeliveryEnvelope, DeliveryOutcome, DispatchResult
from app.notify.worker import DeliveryWorker
from app.jobs import WorkerPolicy


class DeliveryUnitTests(unittest.TestCase):
    def test_envelope_is_bounded_internal_metadata(self):
        values = dict(job_id=str(uuid4()),order_id=str(uuid4()),recipient_id=str(uuid4()),kind='new_order')
        self.assertEqual(DeliveryEnvelope(**values).channel,'telegram')
        for kwargs in ({'channel':'email'},{'kind':'arbitrary'},{'assignment_revision':True},{'bucket':''},
                       {'due_at':datetime.now()}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                DeliveryEnvelope(**dict(values,**kwargs))

    def test_outcome_cannot_invent_acceptance_or_persist_raw_error(self):
        for args in (('accepted','OK',None),('unknown','OK',None),('failed','raw user text',None),
                     ('ambiguous','ERROR','a secret with spaces')):
            with self.subTest(args=args),self.assertRaises(ValueError):DeliveryOutcome(*args)
        self.assertEqual(DeliveryOutcome('accepted','TELEGRAM_API_ACCEPTED','telegram:101').receipt,'telegram:101')

    def test_retry_delay_requires_nonnegative_real_integer_seconds(self):
        for delay in (True,-1,1.5,366*86400+1):
            with self.subTest(delay=delay),self.assertRaises(ValueError):
                DeliveryOutcome('retryable','RATE_LIMIT',retry_after_seconds=delay)
        with self.assertRaises(ValueError):
            DeliveryOutcome('accepted','OK','telegram:123',retry_after_seconds=10)

    def test_constructor_enforces_total_provider_timeout_with_lease_margin(self):
        for bound in (None,True,0,float('nan'),25,100):
            with self.subTest(bound=bound),self.assertRaises(ValueError):
                DeliveryWorker(None,adapter=SimpleNamespace(max_call_seconds=bound),channel='telegram',domain_clock=None)
        worker=DeliveryWorker(None,adapter=SimpleNamespace(max_call_seconds=10),channel='telegram',domain_clock=None)
        self.assertIsNotNone(worker)

    def test_constructor_and_import_start_nothing(self):
        def forbidden():raise AssertionError('Unexpected connection')
        DeliveryWorker(forbidden,adapter=SimpleNamespace(max_call_seconds=1),channel='telegram',domain_clock=None)

    def test_batch_stops_on_idle_without_unbounded_background_work(self):
        worker=DeliveryWorker(None,adapter=SimpleNamespace(max_call_seconds=1),channel='telegram',domain_clock=None)
        calls=iter((DispatchResult('retry'),DispatchResult('provider_accepted'),DispatchResult('idle')))
        worker.run_once=lambda:next(calls)
        self.assertEqual([r.state for r in worker.run_batch()],['retry','provider_accepted'])
        for limit in (0,1001,True):
            with self.assertRaises(ValueError):worker.run_batch(limit=limit)

    def test_paused_after_dispatch_commit_cannot_call_provider_with_insufficient_lease(self):
        from app.notify.models import DeliveryClaim
        now=datetime.now(timezone.utc)
        envelope=DeliveryEnvelope(str(uuid4()),str(uuid4()),str(uuid4()),'new_order')
        for seconds in (-1,0,10,15):
            calls=[]
            adapter=SimpleNamespace(max_call_seconds=10,send=lambda value:calls.append(value))
            worker=DeliveryWorker(None,adapter=adapter,channel='telegram',domain_clock=None,
                                  real_clock=SimpleNamespace(now=lambda:now))
            claim=DeliveryClaim(envelope,1,str(uuid4()),now+timedelta(seconds=seconds))
            worker.claim_one=lambda:claim
            worker.prepare=lambda value:value
            outcomes=[]
            worker.finish=lambda value,outcome:outcomes.append(outcome) or DispatchResult('failed')
            self.assertEqual(worker.run_once().state,'failed')
            self.assertEqual(calls,[])
            self.assertEqual(outcomes[0].code,'DELIVERY_NOT_SENT_LEASE_BUDGET')

    def test_web_push_uses_same_minimal_envelope_and_explicit_lane(self):
        envelope=DeliveryEnvelope(str(uuid4()),str(uuid4()),str(uuid4()),'new_order',channel='web_push')
        worker=DeliveryWorker(None,adapter=SimpleNamespace(max_call_seconds=10),channel='web_push',domain_clock=None)
        self.assertEqual((envelope.channel,worker.channel),('web_push','web_push'))
