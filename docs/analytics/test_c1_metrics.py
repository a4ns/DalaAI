"""Independent exact totals on pinned C1 bytes; no expected-output regeneration."""
from copy import deepcopy
from hashlib import sha256
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest

from c1_metrics import HISTORY_SHA256, calculate, canonical, load_history


class C1Metrics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.input_path = Path(os.environ.get('C3_HISTORY_PATH', Path(__file__).resolve().parents[2] / 'data/synthetic/generated/v1/history.json'))
        cls.history = load_history(cls.input_path)
        cls.manifest, cls.traces = calculate(cls.history)

    def test_committed_manifest_reproduces(self):
        expected=json.loads(Path(__file__).with_name('c1-metrics-manifest.json').read_text())
        self.assertEqual(self.manifest,expected)

    def test_frozen_quarter_and_month_totals(self):
        # Frozen regression targets; independent direct-fact checks below and C4 review are separate.
        expected=[(540,568,28,41859,486,54,492,540,520,568),
                  (182,192,10,14141,163,19,182,182,192,192),
                  (182,191,9,14138,164,18,182,182,191,191),
                  (176,185,9,13580,159,17,128,176,137,185)]
        for period,want in zip(self.manifest['periods'],expected):
            m=period['metrics']; q=m['human_score']; t=m['closed_on_time']; a=m['attempt_on_time']
            got=(m['closed_orders']['count'],m['submission_attempts']['count'],m['rework_decisions']['count'],
                 q['numerator'],q['denominator'],q['missing'],t['numerator'],t['denominator'],a['numerator'],a['denominator'])
            self.assertEqual(got,want)
            self.assertEqual(q['status'],'partial')

    def test_independent_direct_facts_and_trace_membership(self):
        h=self.history
        subs={s['id']:s for s in h['submissions']}
        close=[r for r in h['reviews'] if r['decision']=='close']
        self.assertEqual(sum(r['final_score'] for r in close if r['final_score'] is not None),41859)
        self.assertEqual(sum(r['final_score'] is None for r in close),54)
        self.assertEqual(sum(not subs[r['submission_id']]['done_late'] for r in close),492)
        tables={name:{r['id'] for r in h[name]} for name in ('orders','submissions','reviews')}
        for p in self.manifest['periods']:
            for metric in p['metrics'].values():
                ids=self.traces[metric['trace_id']]
                self.assertEqual(ids,sorted(set(ids)))
                self.assertTrue(set(ids)<=tables[metric['source_table']])
                self.assertEqual(sha256(canonical(ids)).hexdigest(),metric['source_ids_sha256'])
                self.assertEqual(len(ids),metric['eligible'])
        self.assertEqual(sha256(canonical(self.traces)).hexdigest(),self.manifest['trace']['full_trace_sha256'])

    def test_period_partition_and_actual_asof_only(self):
        for name in ('issued_orders','submission_attempts','closed_orders','rework_decisions'):
            quarter=set(self.traces['full/'+name]); monthly=[set(self.traces[p+'/'+name]) for p in ('2026-07','2026-08','2026-09')]
            self.assertEqual(set.union(*monthly),quarter)
            self.assertEqual(sum(map(len,monthly)),len(quarter))
        self.assertEqual(self.manifest['snapshot']['domain_as_of'],'2026-09-30T19:00:00Z')
        for p in self.manifest['periods']:
            self.assertNotIn('overdue_active',p['metrics'])
        self.assertEqual(self.manifest['snapshot']['metrics']['overdue_active']['count'],0)

    def test_nulls_and_no_assessment_not_false_zero(self):
        for row in self.manifest['unsupported'].values():
            self.assertIsNone(row['value'])
        self.assertEqual(self.manifest['unsupported']['ai_quality']['status'],'no_assessment')
        self.assertEqual(self.manifest['counts']['ai_assessments'],0)

    def test_input_order_has_no_effect(self):
        h=deepcopy(self.history)
        for key in ('orders','submissions','reviews','sections'):
            h[key].reverse()
        self.assertEqual(calculate(h),(self.manifest,self.traces))

    def test_source_only_directory_no_git_default_and_explicit_input(self):
        # Only calculator files and canonical bytes; .git and old Git objects absent.
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); scripts=root/'docs/analytics'; scripts.mkdir(parents=True)
            for name in ('c1_metrics.py','check_examples.py','c1-metrics-manifest.json'):
                shutil.copyfile(Path(__file__).with_name(name),scripts/name)
            generated=root/'data/synthetic/generated/v1/history.json'
            generated.parent.mkdir(parents=True)
            shutil.copyfile(self.input_path,generated)
            self.assertFalse((root/'.git').exists())
            env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
            # Empty PATH also proves the calculator cannot silently execute Git.
            env['PATH']=''
            for flags in ([],['--history',str(generated)]):
                result=subprocess.run([sys.executable,str(scripts/'c1_metrics.py'),*flags,'--check'],
                                      cwd=root,env=env,text=True,capture_output=True)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertIn('PASS',result.stdout)
            absent=subprocess.run([sys.executable,str(scripts/'c1_metrics.py'),'--history',str(root/'absent.json'),'--check'],
                                  cwd=root,env=env,text=True,capture_output=True)
            self.assertNotEqual(absent.returncode,0)
            self.assertIn('canonical history missing',absent.stderr)

    def test_modified_generated_history_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'history.json'
            path.write_text('{}\n')
            with self.assertRaisesRegex(ValueError,'hash mismatch'):
                load_history(path)


if __name__=='__main__':
    unittest.main(verbosity=2)
