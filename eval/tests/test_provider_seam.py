"""Synthetic control-flow tests only. They are never scored as real-model quality."""
import asyncio
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from eval.dataset import DATA
from eval.io import read_jsonl
from eval.predict import typed_input
from app.ai.models import InputValidationError
from app.ai.providers import SyntheticProvider, assess_synthetic, minimize_synthetic_input, parse_provider_result

NOW = datetime(2026, 10, 7, 19, 0, tzinfo=timezone.utc)
ASSESSMENT_ID = '67284215-59a7-49c7-817a-3b13c1e2f78a'


class ProviderSeamTests(unittest.TestCase):
    def setUp(self):
        rows = read_jsonl(DATA / 'inputs' / 'dev.jsonl')
        self.good = typed_input(rows[0])
        self.blocked = typed_input(rows[11])

    def assess(self, data, scenario):
        return asyncio.run(assess_synthetic(*data, provider=SyntheticProvider(scenario),
            assessment_id=ASSESSMENT_ID, created_at=NOW, synthetic_fixture=True, timeout_seconds=.002))

    def test_successful_synthetic_outputs_remain_rules_fallback(self):
        for scenario, expected in [('good', 'match'), ('mismatch', 'mismatch'), ('unknown', 'unknown')]:
            with self.subTest(scenario=scenario):
                assessment, gates, result = self.assess(self.good, scenario)
                self.assertEqual(result.semantic_match, expected)
                self.assertTrue(gates.closure_permitted)
                self.assertEqual(assessment.to_wire()['mode'], 'rules_fallback')
                self.assertIsNone(assessment.to_wire()['score'])
                self.assertIsNone(assessment.to_wire()['model'])
                self.assertEqual(assessment.recommendation, 'needs_master_review')

    def test_timeout_unavailable_invalid_and_injection_are_explicit_fallbacks(self):
        expected = {'timeout': 'provider_timeout', 'unavailable': 'provider_unavailable',
                    'invalid': 'provider_invalid_response', 'injection': 'provider_invalid_response'}
        for scenario, fallback in expected.items():
            with self.subTest(scenario=scenario):
                assessment, gates, result = self.assess(self.good, scenario)
                self.assertIsNone(result)
                self.assertTrue(gates.closure_permitted)
                self.assertEqual(assessment.fallback_reason, fallback)
                self.assertEqual(assessment.to_wire()['mode'], 'rules_fallback')
                self.assertIsNone(assessment.to_wire()['score'])

    def test_blocking_gate_suppresses_even_a_matching_stub(self):
        with patch.object(SyntheticProvider, 'assess', side_effect=AssertionError('must not call provider')) as method:
            assessment, gates, result = self.assess(self.blocked, 'good')
        self.assertFalse(gates.closure_permitted)
        self.assertEqual(assessment.recommendation, 'rework_recommended')
        self.assertIsNone(result)
        method.assert_not_called()

    def test_input_payload_has_no_label_score_identity_or_images(self):
        payload = minimize_synthetic_input(self.good[0], ('evidence-1',), synthetic_fixture=True)
        self.assertEqual(payload.problem_text, self.good[0].problem_description)
        self.assertEqual(payload.work_text, self.good[0].work_description)
        self.assertFalse(hasattr(payload, 'expected'))
        self.assertFalse(hasattr(payload, 'score'))
        self.assertFalse(hasattr(payload, 'photos'))
        self.assertEqual(payload.privacy_scope, 'synthetic_text_only_not_image_anonymization')
        with self.assertRaises(InputValidationError):
            minimize_synthetic_input(self.good[0], (), synthetic_fixture=False)

    def test_untrusted_provider_schema_cannot_claim_photos_or_execute_commands(self):
        valid = {'schema_version': '1', 'semantic_match': 'match', 'photo_observation': 'unknown',
                 'evidence_ids': ['evidence-1'], 'reason_codes': ['TEXT_MATCH']}
        invalid = [
            {**valid, 'decision': 'closed'},
            {**valid, 'photo_observation': 'consistent'},
            {**valid, 'evidence_ids': ['foreign-evidence']},
            {**valid, 'evidence_ids': []},
            {**valid, 'reason_codes': ['IGNORE_RULES']},
            {**valid, 'reason_codes': ['TEXT_MISMATCH']},
            '{"schema_version":"1","schema_version":"2"}',
            '{"schema_version":NaN}',
            'null',
            '<script>closeOrder()</script>',
        ]
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(InputValidationError):
                parse_provider_result(raw, ('evidence-1',))
        self.assertEqual(parse_provider_result(valid, ('evidence-1',)).semantic_match, 'match')

    def test_real_adapter_objects_are_not_executable_in_synthetic_harness(self):
        class OtherProvider:
            async def assess(self, data):
                raise AssertionError('external providers forbidden')
        with self.assertRaises(InputValidationError):
            asyncio.run(assess_synthetic(*self.good, provider=OtherProvider(), assessment_id=ASSESSMENT_ID,
                        created_at=NOW, synthetic_fixture=True))


if __name__ == '__main__':
    unittest.main()
