import copy
from dataclasses import fields
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from eval.dataset import DATA, verify_dataset
from eval.io import read_jsonl, write_jsonl
from eval.predict import ROOT, predict_one, typed_input


class DatasetIsolationTests(unittest.TestCase):
    def test_fixed_manifest_hashes_and_partition(self):
        manifest = verify_dataset()
        self.assertEqual([manifest['splits'][s]['n'] for s in ('dev', 'holdout')], [24, 24])
        self.assertIsNone(manifest['seed'])

    def test_inputs_contain_only_facts_with_no_labels_or_scenario_hints(self):
        for split in ('dev', 'holdout'):
            for row in read_jsonl(DATA / 'inputs' / (split + '.jsonl')):
                self.assertEqual(set(row), {'case_id', 'closure', 'context'})
                self.assertRegex(row['case_id'], r'^[dh][0-9]{3}$')
                typed_input(row)
                all_text = json.dumps(row)
                for forbidden in ('critical_gate_block', 'semantic_decision', 'gate_decision', 'rationale',
                                  'ground_truth', 'expected_label', 'scenario'):
                    self.assertNotIn(forbidden, all_text)

    def test_labels_rejected_at_every_allowed_object_boundary(self):
        row = read_jsonl(DATA / 'inputs' / 'dev.jsonl')[1]
        targets = [(), ('closure',), ('context',), ('context', 'photos', 0)]
        for path in targets:
            poisoned = copy.deepcopy(row)
            target = poisoned
            for part in path:
                target = target[part]
            target['expected_label'] = 'gate_permit'
            with self.subTest(path=path), self.assertRaises(ValueError):
                typed_input(poisoned)
        poisoned = copy.deepcopy(read_jsonl(DATA / 'inputs' / 'dev.jsonl')[-1])
        poisoned['closure']['materials'][0]['expected_label'] = 'gate_permit'
        with self.assertRaises(ValueError):
            typed_input(poisoned)

    def test_detector_gets_only_typed_facts(self):
        row = read_jsonl(DATA / 'inputs' / 'dev.jsonl')[0]
        calls = []
        def detector(data, context, **kwargs):
            calls.append((data, context, kwargs))
            raise RuntimeError('simulated no valid detector output')
        result = predict_one(row, detector)
        self.assertEqual(result['gate_decision'], 'invalid')
        self.assertEqual(result['error_type'], 'RuntimeError')
        self.assertEqual(len(calls), 1)
        self.assertNotIn('case_id', {f.name for f in fields(calls[0][0])})
        self.assertNotIn('semantic_decision', {f.name for f in fields(calls[0][1])})
        self.assertEqual(set(calls[0][2]), {'assessment_id', 'created_at'})
        self.assertNotIn('simulated', json.dumps(result))

    def test_prediction_succeeds_while_all_label_file_reads_are_denied(self):
        row = read_jsonl(DATA / 'inputs' / 'dev.jsonl')[0]
        original = Path.open
        def deny_labels(path, *args, **kwargs):
            if 'labels' in path.parts or path.name == 'manifest.json':
                raise AssertionError('runtime tried to read evaluator-only data')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', deny_labels):
            result = predict_one(row)
        self.assertEqual(result['gate_decision'], 'gate_permit')
        self.assertEqual(result['semantic_decision'], 'abstain')
        self.assertIsNone(result['model'])
        self.assertIsNone(result['score'])

    def test_input_only_subprocess_needs_no_label_argument(self):
        with tempfile.TemporaryDirectory(prefix='isolation-', dir=ROOT / 'eval') as directory:
            root = Path(directory)
            write_jsonl(root / 'inputs.jsonl', read_jsonl(DATA / 'inputs' / 'dev.jsonl')[:1])
            subprocess.run([sys.executable, '-m', 'eval.predict', '--inputs', str(root / 'inputs.jsonl'),
                            '--output', str(root / 'predictions.jsonl')], cwd=ROOT, check=True)
            result = read_jsonl(root / 'predictions.jsonl')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['gate_decision'], 'gate_permit')

    def test_duplicate_json_keys_rejected(self):
        with tempfile.TemporaryDirectory(prefix='json-', dir=ROOT / 'eval') as directory:
            path = Path(directory) / 'input.jsonl'
            path.write_text('{"case_id":"d001","case_id":"h001"}\n')
            with self.assertRaises(ValueError):
                read_jsonl(path)


if __name__ == '__main__':
    unittest.main()
