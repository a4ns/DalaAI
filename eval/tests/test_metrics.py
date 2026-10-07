"""Hand-calculated oracles, independent of production rules and fixture labels."""
import unittest
from eval.metrics import classification, nearest_rank, score, GATE_CLASSES, SEMANTIC_CLASSES


def label(i, truth):
    return {'case_id': str(i), 'gate_decision': truth, 'semantic_decision': 'match',
            'critical_gate_block': truth == 'gate_block'}


def prediction(i, decision, fallback=True):
    return {'case_id': str(i), 'gate_decision': decision, 'semantic_decision': 'abstain',
            'fallback': fallback, 'mode': 'rules_fallback', 'latency_ms': float(i)}


class MetricOracleTests(unittest.TestCase):
    def test_eight_episode_hand_calculated_oracle(self):
        # Truth: permit x3, block x5. Prediction counts:
        # permit: TP=1 FP=1 FN=2 -> P=1/2 R=1/3 F1=2/5
        # block:  TP=2 FP=1 FN=3 -> P=2/3 R=2/5 F1=4/8
        # All three non-decisions remain false negatives, not discarded episodes.
        labels = [label(i, 'gate_permit' if i <= 3 else 'gate_block') for i in range(1, 9)]
        predictions = [prediction(1, 'gate_permit'), prediction(2, 'gate_block', False),
                       prediction(3, 'abstain'), prediction(4, 'gate_permit'),
                       prediction(5, 'gate_block'), prediction(6, 'invalid', None),
                       prediction(8, 'gate_block')]
        result = score(labels, predictions)
        gates = result['mandatory_gates']
        self.assertEqual(gates['accuracy_all_episodes'], {'numerator': 3, 'denominator': 8, 'value': 3/8})
        self.assertEqual(gates['accuracy_on_decisions']['value'], 3/5)
        self.assertEqual(gates['decision_coverage']['value'], 5/8)
        self.assertEqual(gates['per_class']['gate_permit']['precision']['value'], 1/2)
        self.assertEqual(gates['per_class']['gate_permit']['recall']['value'], 1/3)
        self.assertEqual(gates['per_class']['gate_permit']['f1']['value'], 2/5)
        self.assertEqual(gates['per_class']['gate_block']['precision']['value'], 2/3)
        self.assertEqual(gates['per_class']['gate_block']['recall']['value'], 2/5)
        self.assertEqual(gates['per_class']['gate_block']['f1']['value'], 1/2)
        self.assertAlmostEqual(gates['macro_f1_supported_classes']['value'], .45)
        for name in ('abstention_rate', 'invalid_output_rate', 'no_output_rate'):
            self.assertEqual(gates[name]['value'], 1/8)
        self.assertEqual(result['critical_false_accept_rate'], {'numerator': 1, 'denominator': 5, 'value': .2})
        self.assertEqual(result['critical_false_accept_case_ids'], ['4'])
        self.assertEqual(result['fallback_rate']['value'], 5/8)
        self.assertEqual(result['fallback_status_unknown_rate']['value'], 2/8)
        self.assertEqual(result['latency_ms']['p50'], 4)
        self.assertEqual(result['latency_ms']['p95'], 8)
        self.assertEqual(result['latency_ms']['observed_episodes'], 7)
        self.assertEqual(result['fixture_gate_expectations'], 'FAIL')

    def test_all_abstentions_have_zero_recall_not_perfect_accuracy(self):
        result = classification(['match', 'mismatch', 'unknown'], ['abstain'] * 3, SEMANTIC_CLASSES)
        self.assertEqual(result['accuracy_all_episodes']['value'], 0)
        self.assertEqual(result['macro_f1_supported_classes']['value'], 0)
        self.assertIsNone(result['accuracy_on_decisions']['value'])
        for row in result['per_class'].values():
            self.assertEqual(row['recall']['value'], 0)
            self.assertEqual(row['f1']['value'], 0)
            self.assertIsNone(row['precision']['value'])

    def test_empty_denominators_are_null_and_cannot_pass(self):
        result = score([], [])
        self.assertIsNone(result['mandatory_gates']['accuracy_all_episodes']['value'])
        self.assertIsNone(result['critical_false_accept_rate']['value'])
        self.assertIsNone(result['fallback_rate']['value'])
        self.assertIsNone(result['latency_ms']['p95'])
        self.assertEqual(result['fixture_gate_expectations'], 'FAIL')

    def test_missing_prediction_is_in_denominator(self):
        result = score([label(1, 'gate_block')], [])
        self.assertEqual(result['mandatory_gates']['no_output_rate']['value'], 1)
        self.assertEqual(result['mandatory_gates']['per_class']['gate_block']['fn'], 1)
        self.assertEqual(result['critical_false_accept_rate']['denominator'], 1)

    def test_malformed_prediction_never_becomes_false_success(self):
        for replacement in ({'gate_decision': 'accepted'}, {'latency_ms': float('nan')},
                            {'latency_ms': -1}, {'fallback': 1}, {'semantic_decision': 'accepted'}):
            with self.subTest(replacement=replacement):
                row = {**prediction(1, 'gate_permit'), **replacement}
                result = score([label(1, 'gate_permit')], [row])
                self.assertEqual(result['mandatory_gates']['invalid_output_rate']['value'], 1)
                self.assertEqual(result['mandatory_gates']['accuracy_all_episodes']['value'], 0)
                self.assertEqual(result['latency_ms']['observed_episodes'], 0)

    def test_invalid_telemetry_cannot_hide_unsafe_permit(self):
        row = {**prediction(1, 'gate_permit'), 'latency_ms': float('nan')}
        result = score([label(1, 'gate_block')], [row])
        self.assertEqual(result['mandatory_gates']['invalid_output_rate']['value'], 1)
        self.assertEqual(result['critical_false_accept_rate']['value'], 1)

    def test_duplicate_foreign_or_contradictory_rows_rejected(self):
        with self.assertRaises(ValueError):
            score([label(1, 'gate_block')], [prediction(1, 'gate_block')] * 2)
        with self.assertRaises(ValueError):
            score([label(1, 'gate_block')], [prediction(2, 'gate_block')])
        with self.assertRaises(ValueError):
            score([label(1, 'gate_block')] * 2, [])
        with self.assertRaises(ValueError):
            score([{**label(1, 'gate_permit'), 'critical_gate_block': True}], [])

    def test_absent_class_not_given_fictitious_f1(self):
        result = classification(['gate_block'], ['gate_block'], GATE_CLASSES)
        self.assertIsNone(result['per_class']['gate_permit']['f1']['value'])
        self.assertEqual(result['macro_f1_supported_classes']['denominator_classes'], 1)
        self.assertEqual(result['macro_f1_supported_classes']['value'], 1)

    def test_quantiles_and_input_validation(self):
        self.assertEqual(nearest_rank(list(range(1, 21)), .95), 19)
        self.assertEqual(nearest_rank([7], .5), 7)
        with self.assertRaises(ValueError):
            nearest_rank([float('inf')], .95)
        with self.assertRaises(ValueError):
            classification(['gate_block'], [], GATE_CLASSES)


if __name__ == '__main__':
    unittest.main()
