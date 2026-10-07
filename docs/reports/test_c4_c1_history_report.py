"""C1 adapter checks with independent source arithmetic and immutable bytes."""
import copy
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import c4_c1_history_report as adapter
import c4_report_examples as report


class C1HistoryReports(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.history,cls.manifest=adapter.load_history()
        cls.facts=adapter.adapt(cls.history,cls.manifest)

    def test_pinned_history_and_no_truth_or_runtime_input(self):
        self.assertEqual(hashlib.sha256(adapter.history_file().read_bytes()).hexdigest(),adapter.SOURCE_HASH)
        self.assertEqual(len(self.facts['orders']),540)
        self.assertEqual(len(self.facts['submissions']),568)
        self.assertEqual(self.facts['coverage']['as_of'],adapter.END)
        self.assertEqual(len(self.facts['coverage']['scope_section_ids']),4)

    def test_tampered_bytes_fail_before_projection(self):
        with self.assertRaisesRegex(ValueError,'history_hash_mismatch'):
            adapter.decode_history(adapter.history_file().read_bytes()+b' ')

    def test_incomplete_capture_and_orphan_review_rejected(self):
        h=copy.deepcopy(self.history);h['orders'].pop()
        with self.assertRaisesRegex(ValueError,'count_mismatch'):
            adapter.adapt(h,self.manifest)
        h=copy.deepcopy(self.history);h['reviews'][0]['submission_id']='missing'
        with self.assertRaisesRegex(ValueError,'orphan_review'):
            adapter.adapt(h,self.manifest)

    def test_period_outside_history_rejected(self):
        with self.assertRaisesRegex(ValueError,'outside_source'):
            adapter.adapt(self.history,self.manifest,start='2026-06-01T00:00:00Z')

    def test_explicit_mapping_preserves_source_facts(self):
        source_orders={o['id']:o for o in self.history['orders']}
        source_subs={s['id']:s for s in self.history['submissions']}
        for o in self.facts['orders']:
            self.assertEqual({k:v for k,v in o.items() if k not in ('domain_now','is_overdue')},source_orders[o['id']])
            self.assertFalse(o['is_overdue'])
        for s in self.facts['submissions']:
            self.assertEqual({k:v for k,v in s.items() if k not in ('reviews','assessments')},source_subs[s['id']])
            self.assertEqual(s['assessments'],[])
            self.assertEqual(s['reviews'],[r for r in self.history['reviews'] if r['submission_id']==s['id']])
        self.assertEqual(self.facts['materials'],self.history['materials'])

    def test_selected_order_null_score_rework_and_absent_ai(self):
        order=next(o for o in self.facts['orders'] if o['id']==adapter.DEMO_ORDER)
        self.assertEqual(order['number'],'521')
        subs=[s for s in self.facts['submissions'] if s['order_id']==adapter.DEMO_ORDER]
        self.assertEqual([(s['assignment_revision'],s['attempt_number']) for s in subs],[(1,1),(1,2)])
        self.assertEqual([s['reviews'][0]['decision'] for s in subs],['rework','close'])
        self.assertIsNone(subs[-1]['reviews'][0]['final_score'])
        html=report.render_order(self.facts,adapter.DEMO_ORDER)
        self.assertIn('final_score: не оценено',html)
        self.assertIn('состояние задания AI неизвестно',html)
        self.assertNotIn('synthetic-model-label',html)

    def test_sample_independent_arithmetic_and_full_source_ids(self):
        result=report.summary(self.facts)
        # Independent raw-source selection; do not use adapter's compact totals.
        subs={s['id']:s for s in self.history['submissions']}
        closes=[r for r in self.history['reviews'] if r['decision']=='close' and adapter.DEMO_START<=r['created_at']<adapter.END]
        self.assertEqual(len(closes),23)
        self.assertEqual(result['close_review_ids'],sorted(r['id'] for r in closes))
        scores=[r['final_score'] for r in closes if r['final_score'] is not None]
        self.assertEqual((sum(scores),len(scores)),(1829,21))
        self.assertEqual(result['human_scores']['unscored_count'],2)
        self.assertEqual(result['human_scores']['mean'],report.dec(Decimal(1829)/21))
        self.assertEqual(result['timeliness']['numerator'],19)
        self.assertEqual(result['timeliness']['denominator'],23)
        self.assertEqual(len(result['submitted_submission_ids']),25)
        self.assertEqual(len(result['rework_review_ids']),2)
        expected={}
        for r in closes:
            for m in subs[r['submission_id']]['payload']['materials']:
                expected[m['material_id']]=expected.get(m['material_id'],Decimal(0))+Decimal(str(m['quantity']))
        self.assertEqual({r['material_id']:Decimal(r['quantity']) for r in result['closed_materials']},expected)
        self.assertEqual(expected['1508a500-0aad-54d3-b4aa-e30d00eaa305'],48)

    def test_full_quarter_independent_numeric_checkpoint(self):
        result=report.summary(adapter.adapt(self.history,self.manifest,start=adapter.FULL_START))
        self.assertEqual([len(result[k]) for k in ('issued_order_ids','submitted_order_ids','submitted_submission_ids','closed_order_ids','rework_review_ids','overdue_order_ids')],[540,540,568,540,28,0])
        self.assertEqual(result['human_scores']['scored_count'],486)
        self.assertEqual(result['human_scores']['unscored_count'],54)
        self.assertEqual(result['human_scores']['mean'],report.dec(Decimal(41859)/486))
        self.assertEqual((result['timeliness']['numerator'],result['timeliness']['denominator']),(492,540))

    def test_explicit_input_path_without_git_or_adjacent_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'explicit.json'
            path.write_bytes(adapter.history_file().read_bytes())
            history,manifest=adapter.load_history(path)
            self.assertEqual(len(history['orders']),540)
            self.assertEqual(manifest['history_sha256'],adapter.SOURCE_HASH)
            path.write_bytes(path.read_bytes()+b' ')
            with self.assertRaisesRegex(ValueError,'hash_mismatch'):
                adapter.load_history(path)

    def test_source_only_cli_default_path_needs_no_git(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            sources=root/'docs'/'reports';sources.mkdir(parents=True)
            for filename in ('c4_c1_history_report.py','c4_report_examples.py'):
                shutil.copy(Path(adapter.__file__).with_name(filename),sources/filename)
            history=root/adapter.SOURCE_PATH;history.parent.mkdir(parents=True)
            history.write_bytes(adapter.history_file().read_bytes())
            env=dict(os.environ);env.pop('C4_HISTORY',None);env['PYTHONDONTWRITEBYTECODE']='1';env['PATH']=''
            result=subprocess.run([sys.executable,str(sources/'c4_c1_history_report.py'),'--output-dir',str(root/'out')],cwd=root,env=env,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            manifest=json.loads((root/'out'/'manifest.json').read_text())
            self.assertEqual(manifest['source_commit'],adapter.SOURCE_COMMIT)
            self.assertIsNone(manifest['report_code_sha'])
            self.assertEqual(len(manifest['report_source_sha256']),2)
            self.assertEqual(manifest['full_period_totals']['closed_order_count'],540)
            self.assertFalse((root/'.git').exists())

    def test_no_mutation_of_source(self):
        original=copy.deepcopy(self.history)
        adapter.adapt(self.history,self.manifest)
        self.assertEqual(self.history,original)


if __name__=='__main__':
    unittest.main()
