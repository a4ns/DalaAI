"""Independent expectations for offline fixture math and escaped HTML text."""
import copy
from decimal import Decimal
from html.parser import HTMLParser
import json
import unittest

import c4_report_examples as report


class TextView(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.tags, self.attrs, self.texts = [], [], []
        self.feed(html)
    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs.extend(attrs)
    def handle_data(self, data):
        self.texts.append(data)


class ReportExamples(unittest.TestCase):
    def setUp(self):
        self.data=report.load_case()

    def invalid(self, mutate):
        mutate(self.data)
        with self.assertRaises(ValueError):
            report.summary(self.data)

    def test_independent_expected_values_and_source_ids(self):
        expected=json.loads((report.HERE/'c4-report-expected.json').read_text())
        self.assertEqual(report.summary(self.data),expected)

    def test_partial_and_drained_moving_pages_do_not_get_totals(self):
        for kind in ('partial_keyset','drained_moving_keyset'):
            self.data['coverage']['kind']=kind
            result=report.summary(self.data)
            self.assertEqual(set(result),{'totals','reason'})
            self.assertIsNone(result['totals'])
            self.assertNotIn('Выдано:',report.render_shift(self.data))

    def test_empty_cohort_known_zero_counts_unknown_mean(self):
        self.data['period']['start']='2026-10-07T06:30:00Z'
        result=report.summary(self.data)
        self.assertEqual(result['issued_order_ids'],[])
        self.assertEqual(result['human_scores']['cohort_count'],0)
        self.assertIsNone(result['human_scores']['mean'])
        self.assertEqual(result['timeliness']['denominator'],0)
        self.assertIn('недостаточно данных; n=0',report.render_shift(self.data))

    def test_close_end_boundary_excluded(self):
        self.data['submissions'][2]['reviews'][0]['created_at']=self.data['period']['end']
        result=report.summary(self.data)
        self.assertEqual(result['closed_order_ids'],[self.data['orders'][1]['id']])
        self.assertEqual(result['human_scores']['unscored_count'],0)
        self.assertEqual(result['closed_materials'][0]['quantity'],'1')

    def test_html_escapes_and_preserves_long_cyrillic_text(self):
        doc=report.render_order(self.data,self.data['orders'][0]['id'])
        view=TextView(doc)
        self.assertNotIn('script',view.tags)
        self.assertNotIn('img',view.tags)
        self.assertNotIn('em',view.tags)
        self.assertFalse(any(k.startswith('on') for k,v in view.attrs))
        self.assertIn('&lt;script&gt;',doc)
        self.assertIn(self.data['submissions'][2]['payload']['work_description'],''.join(view.texts))
        self.assertIn(self.data['submissions'][2]['payload']['comment'],''.join(view.texts))
        self.assertEqual(len(self.data['submissions'][2]['payload']['work_description']),6000)
        self.assertEqual(len(self.data['submissions'][2]['payload']['comment']),2000)
        self.assertIn('1,125 кг',doc)
        self.assertIn('2,25 кг',doc)
        self.assertIn('final_score: не оценено',doc)
        self.assertIn('current_recommendation=False',doc)
        self.assertIn('07.10.2026 10:00:00 UTC+5',doc)
        self.assertIn(report.MARK,doc)
        self.assertIn(report.MARK,report.render_shift(self.data))

    def test_absent_assessment_not_pending_and_empty_materials_not_zero(self):
        doc=report.render_order(self.data,self.data['orders'][2]['id'])
        self.assertIn('состояние задания AI неизвестно',doc)
        self.assertIn('решения мастера нет',doc)
        self.assertIn('материалы не заявлены',doc)
        self.assertNotIn('проверка идёт',doc)

    def test_all_case_objects_validate(self):
        for order in self.data['orders']:
            self.assertIn(order['id'],report.render_order(self.data,order['id']))

    def test_duplicate_order_rejected(self):
        self.invalid(lambda d:d['orders'].append(copy.deepcopy(d['orders'][0])))

    def test_distinct_review_ids_on_same_submission_rejected(self):
        other=copy.deepcopy(self.data['submissions'][1]['reviews'][0])
        other['id']='00000003-0000-4000-8000-000000000099'
        self.invalid(lambda d:d['submissions'][1]['reviews'].append(other))

    def test_duplicate_attempt_rejected(self):
        self.invalid(lambda d:d['submissions'][2].update(attempt_number=1))

    def test_cross_order_current_submission_rejected(self):
        self.invalid(lambda d:d['orders'][0].update(current_submission_id=d['submissions'][3]['id']))

    def test_assessment_wrong_revision_rejected(self):
        self.invalid(lambda d:d['submissions'][0]['assessments'][0].update(assignment_revision=2))

    def test_missing_nullable_score_is_not_null(self):
        self.invalid(lambda d:d['submissions'][2]['reviews'][0].pop('final_score'))

    def test_missing_materials_is_not_empty_list(self):
        self.invalid(lambda d:d['submissions'][4]['payload'].pop('materials'))

    def test_invalid_quantities(self):
        original=copy.deepcopy(self.data)
        for bad in (0,-1,True,'1',Decimal('NaN'),Decimal('Infinity'),Decimal('1.1234'),Decimal('1000000000')):
            with self.subTest(value=str(bad)):
                self.data=copy.deepcopy(original)
                self.invalid(lambda d:d['submissions'][0]['payload']['materials'][0].update(quantity=bad))

    def test_unknown_material_and_missing_unit(self):
        self.invalid(lambda d:d['materials'][0].pop('unit'))
        self.data=report.load_case()
        self.invalid(lambda d:d['materials'][0].update(unit='  '))
        self.data=report.load_case()
        self.invalid(lambda d:d['materials'].pop(0))

    def test_noninteger_scores_rejected(self):
        self.invalid(lambda d:d['submissions'][2]['reviews'][0].update(final_score=True))

    def test_incomplete_close_rejected(self):
        self.data['submissions'][4]['reviews']=[copy.deepcopy(self.data['submissions'][2]['reviews'][0])]
        self.data['submissions'][4]['reviews'][0]['submission_id']=self.data['submissions'][4]['id']
        with self.assertRaises(ValueError):
            report.summary(self.data)

    def test_bad_window_timestamp_mixed_snapshot_and_scope(self):
        original=copy.deepcopy(self.data)
        mutations=[lambda d:d['period'].update(start=d['period']['end']),
                   lambda d:d['period'].update(start='2026-10-07T00:00:00'),
                   lambda d:d['period'].update(start='2026-02-30T00:00:00Z'),
                   lambda d:d['orders'][0].update(domain_now='2026-10-07T08:00:00Z'),
                   lambda d:d['coverage'].update(scope_section_ids=[])]
        for mutate in mutations:
            self.data=copy.deepcopy(original)
            self.invalid(mutate)


if __name__ == '__main__':
    unittest.main()
