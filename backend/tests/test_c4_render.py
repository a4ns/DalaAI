"""Synthetic presentation checks over the declared C3 DTO, never mocked imports.

Behavior expectations independently retain the public offline C4 invariants at
4a5184fd5caa3c1be35fea5ff55d534967c191bf. Missing C3 is a collection/import
error (BLOCKED dependency), not a skipped test or replacement DTO.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html.parser import HTMLParser
import json
import unittest

from app.analytics.c3_types import (
    AnalyticsFacts, AssessmentFact, AttemptFact, ExecutorRating, MaterialFact,
    MetricFact, OrderFact, Period, Provenance,
)
from app.orders.models import (
    Assignment, Completeness, Decision, MaterialUse, Order, OrderType, Priority,
    Review, Status, Submission, SubmitPayload,
)
from app.reports.c4_render import (
    order_report_data, render_order_html, render_shift_html, shift_report_data,
)


NOW = datetime(2026, 10, 7, 7, tzinfo=timezone.utc)
ATTACK = '<script>alert("x")</script><img src="https://example.invalid/x" onerror="x()">'


def uid(number):
    return f'00000000-0000-4000-8000-{number:012d}'


def metric(name='human_score', value=Decimal('0'), **changes):
    values = dict(
        name=name, source_table='reviews', status='ok', numerator=Decimal('0'),
        denominator=1, eligible=2, missing=1, excluded=0, value=value,
        source_ids=(uid(31), uid(32)), missing_source_ids=(uid(32),), excluded_source_ids=(),
        small_sample=True,
    )
    values.update(changes)
    return MetricFact(**values)


def fixture():
    """Declared DTO fixture; not an API/DB/provider/scope authorization test."""
    order = Order(
        id=uid(1), number='Н-001', version=9, assignment_revision=2,
        scheduling_revision=1, status=Status.CLOSED, type=OrderType.UNPLANNED,
        description='Проверить привод ' + ATTACK, section_id=uid(2),
        equipment_id=uid(3), assignment=Assignment(uid(4), None),
        created_by=uid(5), issued_at=NOW - timedelta(hours=2),
        due_at=NOW - timedelta(minutes=30), norm_minutes=60, priority=Priority.HIGH,
        comment='Комментарий мастера', before_photo_ids=(),
        current_submission_id=uid(12), updated_at=NOW,
    )
    payload = SubmitPayload(
        work_description=('Выполнены работы ' + ATTACK).ljust(6000, 'Я'),
        work_code_id=uid(6), materials=(MaterialUse(uid(7), Decimal('1.125')),),
        after_photo_ids=(uid(8),), comment=('Комментарий ' + ATTACK).ljust(2000, 'Я'),
    )
    old = Submission(
        id=uid(11), order_id=uid(1), assignment_revision=1, attempt_number=1,
        submitted_by=uid(9), submitted_at=NOW - timedelta(hours=1),
        done_late=False, payload=payload, completeness=Completeness.COMPLETE,
        missing_evidence=(),
    )
    current = replace(old, id=uid(12), assignment_revision=2,
                      submitted_by=uid(4), submitted_at=NOW - timedelta(minutes=20),
                      done_late=True)
    assessment = AssessmentFact(
        id=uid(21), submission_id=old.id, assignment_revision=old.assignment_revision,
        schema_version='1', mode='rules_fallback', model=None, model_version=None,
        duration_ms=4, recommendation='needs_master_review', score=91,
        reasons=('Требуется решение мастера ' + ATTACK,), evidence_ids=(uid(8),),
        fallback_reason='Модель недоступна', stale=True, created_at=old.submitted_at,
    )
    review = Review(
        id=uid(32), submission_id=current.id, reviewer_id=uid(5),
        decision=Decision.CLOSE, reason='Проверено ' + ATTACK, final_score=None,
        created_at=NOW - timedelta(minutes=5),
    )
    human = metric()
    on_time = metric('closed_on_time', Decimal('0.5'), numerator=Decimal('1'),
                     denominator=2, missing=0, missing_source_ids=())
    rework = metric('closed_with_rework', Decimal('0'), denominator=2,
                    missing=0, missing_source_ids=())
    return AnalyticsFacts(
        schema_version='c3-runtime-facts/1',
        provenance=Provenance(
            synthetic=True, source_ref='declared-fixture ' + ATTACK,
            scope_description='Разрешённый участок ' + uid(2),
            domain_as_of=NOW, captured_at_real=NOW + timedelta(minutes=1),
            coverage='consistent_snapshot', history_complete=True,
        ),
        period=Period(start=NOW - timedelta(days=1), end=NOW, display_timezone='Asia/Almaty'),
        orders=(OrderFact(order=order, is_overdue=False, attempts=(
            AttemptFact(submission=old, review=None, assessments=(assessment,), assessment_status='recorded'),
            AttemptFact(submission=current, review=review, assessments=(), assessment_status='absent'),
        )),),
        metrics=(human, on_time, rework),
        ratings=(ExecutorRating(
            executor_id=uid(4), human_score=human, closed_on_time=on_time,
            closed_with_rework=rework, composite_score=None, composite_status='unsupported_inputs',
        ),),
        closed_materials=(MaterialFact(
            material_id=uid(7), label='Смазка', unit='кг', quantity=Decimal('1.125'),
            order_ids=(uid(1),), submission_ids=(uid(12),), review_ids=(uid(32),),
        ),),
        unavailable_reasons=(),
    )


class TextView(HTMLParser):
    def __init__(self, document):
        super().__init__(convert_charrefs=True)
        self.tags, self.attrs, self.texts = [], [], []
        self.feed(document)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs.extend(attrs)

    def handle_data(self, data):
        self.texts.append(data)


class RuntimeReports(unittest.TestCase):
    def setUp(self):
        self.facts = fixture()

    def test_plain_dict_is_not_a_second_input_contract(self):
        for operation in (shift_report_data, render_shift_html):
            with self.assertRaisesRegex(TypeError, 'AnalyticsFacts'):
                operation({})

    def test_order_projection_is_json_safe_and_preserves_exact_quantities(self):
        data = order_report_data(self.facts, uid(1))
        encoded = json.dumps(data, ensure_ascii=False, allow_nan=False)
        decoded = json.loads(encoded)
        self.assertEqual(decoded, data)
        self.assertEqual(data['fact_schema_version'], 'c3-runtime-facts/1')
        self.assertEqual(data['order']['attempts'][0]['submission']['payload']['materials'][0]['quantity'], '1.125')
        self.assertIsNone(data['order']['attempts'][1]['review']['final_score'])
        self.assertEqual(data['order']['attempts'][0]['assessments'][0]['score'], 91)
        self.assertEqual(data['report_kind'], 'order')

    def test_order_projection_excludes_other_orders_and_all_shift_aggregates(self):
        other = replace(self.facts.orders[0], order=replace(
            self.facts.orders[0].order, id=uid(99), description='OTHER-ORDER-CANARY'))
        facts = replace(self.facts, orders=self.facts.orders + (other,))
        data = order_report_data(facts, uid(1))
        for key in ('metrics', 'ratings', 'closed_materials', 'orders'):
            self.assertNotIn(key, data)
        self.assertNotIn('OTHER-ORDER-CANARY', json.dumps(data))
        self.assertNotIn('OTHER-ORDER-CANARY', render_order_html(facts, uid(1)))

    def test_unknown_and_duplicate_selected_order_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'authorized facts'):
            order_report_data(self.facts, uid(999))
        duplicate = replace(self.facts, orders=self.facts.orders * 2)
        with self.assertRaisesRegex(ValueError, 'uniquely present'):
            order_report_data(duplicate, uid(1))

    def test_html_is_inert_and_untrusted_long_cyrillic_is_preserved(self):
        document = render_order_html(self.facts, uid(1))
        view = TextView(document)
        self.assertTrue(set(view.tags) <= {'html', 'head', 'meta', 'title', 'style', 'body', 'h1', 'section', 'h2', 'pre'})
        self.assertFalse(any(name.lower().startswith('on') for name, _ in view.attrs))
        self.assertFalse(any(name.lower() in {'src', 'href', 'action', 'srcdoc'} for name, _ in view.attrs))
        self.assertIn('&lt;script&gt;', document)
        self.assertIn(ATTACK, ''.join(view.texts))
        self.assertIn(self.facts.orders[0].attempts[0].submission.payload.work_description, ''.join(view.texts))
        self.assertEqual(len(self.facts.orders[0].attempts[0].submission.payload.work_description), 6000)
        self.assertEqual(len(self.facts.orders[0].attempts[0].submission.payload.comment), 2000)
        self.assertIn("default-src 'none'", document)
        self.assertIn('<html lang="ru">', document)

    def test_title_and_all_shift_free_text_are_escaped(self):
        bad_order = replace(self.facts.orders[0], order=replace(self.facts.orders[0].order, number=ATTACK))
        facts = replace(self.facts, orders=(bad_order,),
                        closed_materials=(replace(self.facts.closed_materials[0], label=ATTACK, unit=ATTACK),),
                        unavailable_reasons=(ATTACK,))
        for document in (render_order_html(facts, uid(1)), render_shift_html(facts)):
            view = TextView(document)
            self.assertNotIn('script', view.tags)
            self.assertNotIn('img', view.tags)
            self.assertIn(ATTACK, ''.join(view.texts))

    def test_null_human_score_never_uses_ai_score_and_zero_remains_zero(self):
        document = render_order_html(self.facts, uid(1))
        self.assertIn('Оценка мастера: не оценено', document)
        self.assertIn('Балл ИИ: 91', document)
        current = self.facts.orders[0].attempts[1]
        changed = replace(current, review=replace(current.review, final_score=0))
        facts = replace(self.facts, orders=(replace(
            self.facts.orders[0], attempts=(self.facts.orders[0].attempts[0], changed)),))
        self.assertIn('Оценка мастера: 0', render_order_html(facts, uid(1)))
        self.assertEqual(order_report_data(facts, uid(1))['order']['attempts'][1]['review']['final_score'], 0)

    def test_absent_assessment_is_not_an_invented_job_state(self):
        document = render_order_html(self.facts, uid(1))
        self.assertIn('Оценок в источнике нет; состояние задания ИИ неизвестно', document)
        self.assertNotIn('проверка идёт', document)
        self.assertNotIn('задание завершилось ошибкой', document)
        self.assertIn('Решения мастера в источнике нет', document)

    def test_stale_and_previous_revision_recommendation_are_not_current(self):
        document = render_order_html(self.facts, uid(1))
        self.assertIn('Устаревшая оценка: да', document)
        self.assertIn('Рекомендация текущей попытки: нет', document)
        self.assertIn('Попытка 1, ревизия 1', document)
        self.assertIn('Попытка 1, ревизия 2', document)
        self.assertIn('Текущая попытка: да', document)

    def test_assessment_after_review_is_not_implied_to_inform_decision(self):
        row = self.facts.orders[0]
        current = row.attempts[1]
        assessment = replace(row.attempts[0].assessments[0], submission_id=current.submission.id,
                             assignment_revision=2, stale=False, created_at=NOW)
        updated = replace(current, assessments=(assessment,), assessment_status='recorded')
        facts = replace(self.facts, orders=(replace(row, attempts=(updated,)),))
        document = render_order_html(facts, uid(1))
        self.assertIn('Хронология оценки: Записана после решения мастера', document)
        self.assertIn('Оценка мастера: не оценено', document)

    def test_source_mode_and_both_clocks_are_explicit(self):
        document = render_shift_html(self.facts)
        self.assertIn('СИНТЕТИЧЕСКИЕ ДАННЫЕ', document)
        self.assertIn('07.10.2026 12:00:00 +0500', document)
        self.assertIn('07.10.2026 12:01:00 +0500', document)
        self.assertIn('начало включено, конец исключён', document)
        self.assertIn('Asia/Almaty', document)
        self.assertIn(self.facts.provenance.scope_description, document)
        facts = replace(self.facts, provenance=replace(self.facts.provenance, synthetic=False))
        self.assertIn('НЕ СИНТЕТИЧЕСКИЕ', render_shift_html(facts))

    def test_modes_and_fallback_remain_separate_from_human_decision(self):
        document = render_order_html(self.facts, uid(1))
        self.assertIn('Правила (резервный режим)', document)
        self.assertIn('Причина резервного режима: Модель недоступна', document)
        self.assertIn('ИИ: рекомендация, не решение мастера', document)
        self.assertIn('Мастер: зафиксированное решение', document)

    def test_shift_preserves_numerators_denominators_missing_ids_and_null_rating(self):
        data = shift_report_data(self.facts)
        self.assertTrue(data['totals_available'])
        self.assertEqual(data['metrics'][0]['value'], '0')
        self.assertEqual(data['metrics'][0]['denominator'], 1)
        self.assertEqual(data['metrics'][0]['missing'], 1)
        self.assertEqual(data['metrics'][0]['missing_source_ids'], [uid(32)])
        self.assertEqual(data['metrics'][1]['numerator'], '1')
        self.assertEqual(data['metrics'][1]['denominator'], 2)
        self.assertIsNone(data['ratings'][0]['composite_score'])
        self.assertEqual(data['ratings'][0]['composite_status'], 'unsupported_inputs')
        self.assertEqual(json.loads(json.dumps(data, allow_nan=False)), data)
        document = render_shift_html(self.facts)
        self.assertIn('Сводный рейтинг: недостаточно поддерживаемых данных', document)
        self.assertIn('Малая выборка: да', document)

    def test_partial_and_moving_pages_never_claim_totals_even_with_attached_metrics(self):
        for coverage in ('partial_keyset', 'drained_moving_keyset'):
            with self.subTest(coverage=coverage):
                facts = replace(self.facts, provenance=replace(self.facts.provenance, coverage=coverage))
                data = shift_report_data(facts)
                self.assertFalse(data['totals_available'])
                for key in ('metrics', 'ratings', 'closed_materials'):
                    self.assertIsNone(data[key])
                document = render_shift_html(facts)
                self.assertIn('Наблюдённые строки не являются итогом смены', document)
                self.assertNotIn('Значение: 0', document)
                self.assertIn(uid(1), render_order_html(facts, uid(1)))

    def test_incomplete_history_never_claims_complete_totals(self):
        facts = replace(self.facts, provenance=replace(self.facts.provenance, history_complete=False))
        self.assertFalse(shift_report_data(facts)['totals_available'])
        self.assertIn('Итоги недоступны', render_shift_html(facts))

    def test_empty_source_unknown_mean_is_not_zero(self):
        unknown = metric(value=None, numerator=None, denominator=0, eligible=0,
                         missing=0, source_ids=(), missing_source_ids=(), status='no_cohort')
        facts = replace(self.facts, orders=(), metrics=(unknown,), ratings=(), closed_materials=())
        data = shift_report_data(facts)
        self.assertIsNone(data['metrics'][0]['value'])
        document = render_shift_html(facts)
        self.assertIn('Значение: недостаточно данных', document)
        self.assertIn('Знаменатель: 0', document)
        self.assertNotIn('Значение: 0', document)

    def test_material_totals_keep_exact_units_and_source_ids(self):
        data = shift_report_data(self.facts)
        row = data['closed_materials'][0]
        self.assertEqual((row['quantity'], row['unit']), ('1.125', 'кг'))
        self.assertEqual(row['review_ids'], [uid(32)])
        document = render_shift_html(self.facts)
        self.assertIn('не складское списание', document)
        self.assertIn('Количество: 1.125', document)
        self.assertIn('Единица: кг', document)

    def test_no_dictionary_label_or_unit_is_not_invented(self):
        facts = replace(self.facts, closed_materials=(replace(
            self.facts.closed_materials[0], label=None, unit=None),))
        document = render_shift_html(facts)
        self.assertIn('Материал: не указано', document)
        self.assertIn('Единица: не указано', document)

    def test_no_attempt_no_material_and_photo_limits_are_explicit(self):
        row = self.facts.orders[0]
        sub = replace(row.attempts[0].submission, payload=replace(row.attempts[0].submission.payload, materials=()))
        facts = replace(self.facts, orders=(replace(row, attempts=(replace(row.attempts[0], submission=sub),)),))
        document = render_order_html(facts, uid(1))
        self.assertIn('материалы не заявлены', document)
        self.assertIn('не применимо: фото до работ не указаны', document)
        self.assertIn('изображения и исправность не проверялись', document)
        facts = replace(facts, orders=(replace(row, attempts=()),))
        self.assertIn('В источнике нет попыток выполнения', render_order_html(facts, uid(1)))

    def test_projection_is_detached_and_render_is_deterministic(self):
        before = render_order_html(self.facts, uid(1))
        data = order_report_data(self.facts, uid(1))
        data['order']['order']['description'] = 'mutated projection'
        data['provenance']['source_ref'] = 'mutated source'
        self.assertEqual(before, render_order_html(self.facts, uid(1)))
        self.assertEqual(render_shift_html(self.facts), render_shift_html(self.facts))


if __name__ == '__main__':
    unittest.main()
