"""Local non-database unit checks. These do NOT prove PostgreSQL semantics."""
from datetime import datetime, timedelta, timezone
import unittest
from uuid import uuid4

from app.jobs import AssessmentWorker, Claim, WorkerPolicy


class JobsUnitTests(unittest.TestCase):
    def test_policy_caps_real_retry_backoff(self):
        policy = WorkerPolicy()
        self.assertEqual(policy.retry_delay(1),timedelta(seconds=2))
        self.assertEqual(policy.retry_delay(2),timedelta(seconds=4))
        self.assertEqual(policy.retry_delay(100),timedelta(minutes=5))

    def test_policy_rejects_unsafe_ranges_and_bool(self):
        for kwargs in ({'lease':timedelta(0)},{'lease':timedelta(hours=1)},
                       {'retry_base':timedelta(0)},{'retry_cap':timedelta(days=1)},
                       {'max_attempts':True},{'max_attempts':0},{'max_attempts':101}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                WorkerPolicy(**kwargs)

    def test_claim_requires_aware_expiry_and_positive_generation(self):
        args = dict(id=str(uuid4()),submission_id=str(uuid4()),assignment_revision=1,
                    attempts=1,lease_token=str(uuid4()),lease_until=datetime.now(timezone.utc))
        self.assertEqual(Claim(**args).attempts,1)
        with self.assertRaises(ValueError):
            Claim(**dict(args,attempts=0))
        with self.assertRaises(ValueError):
            Claim(**dict(args,lease_until=datetime.now()))

    def test_import_and_constructor_start_no_work(self):
        def forbidden():
            raise AssertionError('Unexpected connection')
        worker = AssessmentWorker(forbidden,domain_clock=None)
        self.assertIsNotNone(worker)
        for limit in (0,1001,True,None):
            with self.subTest(limit=limit),self.assertRaises(ValueError):
                worker.run_batch(limit=limit)

    def test_batch_is_bounded_and_stops_on_idle(self):
        from app.jobs import RunResult
        worker = AssessmentWorker(None,domain_clock=None)
        calls = iter((RunResult('done','one'),RunResult('retry','two'),RunResult('idle')))
        worker.run_once = lambda:next(calls)
        self.assertEqual([r.state for r in worker.run_batch(limit=4)],['done','retry'])

    def test_batch_continues_past_exhausted_job(self):
        from app.jobs import RunResult
        worker = AssessmentWorker(None,domain_clock=None)
        calls = iter((RunResult('exhausted'),RunResult('done','two'),RunResult('idle')))
        worker.run_once = lambda:next(calls)
        self.assertEqual([r.state for r in worker.run_batch(limit=4)],['exhausted','done'])

    def test_generated_event_conforms_to_accepted_proposal(self):
        import json
        from pathlib import Path
        from types import SimpleNamespace
        import yaml
        from jsonschema import Draft202012Validator, FormatChecker
        from app.jobs.models import assessment_event
        from app.persistence.canonical import canonical_json
        order = SimpleNamespace(id=str(uuid4()),version=4,assignment_revision=2,scheduling_revision=3)
        assessment = SimpleNamespace(id=str(uuid4()),submission_id=str(uuid4()))
        now = datetime.now(timezone.utc)
        event = assessment_event(order,assessment,sequence=7,domain_now=now,real_now=now)
        root = Path(__file__).resolve().parents[2]
        spec = yaml.safe_load((root/'coord/proposals/a6-contract-v1/contracts/openapi.yaml').read_text())
        schema = dict(spec, **{'$ref':'#/components/schemas/OrderEvent'})
        Draft202012Validator(schema,format_checker=FormatChecker()).validate(json.loads(canonical_json(event)))
        self.assertEqual(event['kind'],'order.assessment_recorded')
        self.assertEqual(event['order_version'],5)
        self.assertIsNone(event['actor_id']); self.assertIsNone(event['operation_id'])

    def test_default_physical_evidence_downgrades_only_previously_valid_files(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from app.ai.models import PhotoEvidence
        from app.jobs.evidence import UnverifiedPhysicalReferences
        from app.persistence.postgres import PostgresReferences
        order_id,submission_id = str(uuid4()),str(uuid4())
        photos = tuple(PhotoEvidence(str(uuid4()),order_id,submission_id,1,'after',valid)
                       for valid in (True,False,None))
        refs = UnverifiedPhysicalReferences(SimpleNamespace(db=None),None,None,None)
        with patch.object(PostgresReferences,'closure_evidence',return_value=(frozenset(),frozenset(),photos)):
            _,_,actual = refs.closure_evidence(None)
        self.assertEqual([photo.file_valid for photo in actual],[None,False,None])
        self.assertEqual([photo.id for photo in actual],[photo.id for photo in photos])
        self.assertEqual(photos[0].file_valid,True)  # immutable source is unchanged
