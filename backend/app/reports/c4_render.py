"""Pure Russian report presentation over C3 facts; no I/O or authorization.

The input is the C3 DTO, never a report-specific input dictionary. The caller
must load authorized facts. JSON projections remain unescaped data; only HTML
text nodes are escaped. No report format or transport support is implied.
"""
from datetime import datetime
from html import escape
import json
from zoneinfo import ZoneInfo

from app.analytics.c3_types import AnalyticsFacts
from app.analytics.c3_facts import facts_to_dict


_STATUS_LABELS = {
    'issued': 'Выдан', 'queued': 'В очереди', 'accepted': 'Принят',
    'rejected': 'Отклонён', 'in_progress': 'В работе', 'paused': 'Приостановлен',
    'done': 'Результат отправлен', 'ai_review': 'На проверке',
    'rework': 'На доработке', 'closed': 'Закрыт', 'cancelled': 'Отменён',
}
_MODE_LABELS = {
    'model': 'Модель', 'rules_fallback': 'Правила (резервный режим)',
    'manual': 'Ручной режим',
}
_COVERAGE_LABELS = {
    'consistent_snapshot': 'Согласованный снимок разрешённой области',
    'frozen_complete_export': 'Полный неизменяемый экспорт разрешённой области',
    'partial_keyset': 'Неполная выборка страниц',
    'drained_moving_keyset': 'Прочитанные страницы изменяющегося источника',
}
_METRIC_LABELS = {
    'issued_orders': 'Выдано нарядов',
    'submitted_orders': 'Отправлено нарядов',
    'submission_attempts': 'Отправлено попыток',
    'closed_orders': 'Закрыто нарядов',
    'rework_decisions': 'Решений о доработке',
    'awaiting_review': 'Ожидают проверки на доменное время снимка',
    'overdue_active': 'Просрочено на доменное время снимка',
    'attempt_on_time': 'Отправлено попыток в срок',
    'human_score': 'Оценка мастера среди закрытых',
    'human_score_mean': 'Средняя оценка мастера среди закрытых',
    'closed_on_time': 'В срок среди закрытых',
    'closed_with_rework': 'Закрытые с доработкой',
}
_LIMITATIONS = (
    'Показаны только факты разрешённой области источника; это не итог по предприятию.',
    'Оценка ИИ — рекомендация. Производственное решение принимает мастер.',
    'Фото представлены только идентификаторами; изображения и исправность не проверялись этим отчётом.',
    'История попыток и решений не является полным журналом событий наряда.',
    'Материалы указаны по заявлениям исполнителей, а не как подтверждённые складские списания.',
)
_TOTALS_UNAVAILABLE = (
    'Итоги недоступны: нет полного согласованного снимка и истории разрешённой области. '
    'Наблюдённые строки не являются итогом смены.'
)


def _wire(facts: AnalyticsFacts) -> dict:
    if not isinstance(facts, AnalyticsFacts):
        raise TypeError('C4 requires app.analytics.c3_types.AnalyticsFacts')
    return facts_to_dict(facts)


def _base(data: dict, kind: str) -> dict:
    return {
        'report_kind': kind,
        'fact_schema_version': data['schema_version'],
        'provenance': data['provenance'],
        'period': data['period'],
        'unavailable_reasons': data['unavailable_reasons'],
        'limitations': list(_LIMITATIONS),
    }


def order_report_data(facts: AnalyticsFacts, order_id: str) -> dict:
    """One authorized observed order only, with no scope-wide aggregates."""
    data = _wire(facts)
    selected = [row for row in data['orders'] if row['order']['id'] == order_id]
    if len(selected) != 1:
        raise ValueError('Order is not uniquely present in the supplied authorized facts')
    return {**_base(data, 'order'), 'order': selected[0]}


def shift_report_data(facts: AnalyticsFacts) -> dict:
    """Present C3 facts without recomputing cohort math or inventing totals."""
    data = _wire(facts)
    available = facts.totals_available
    return {
        **_base(data, 'shift'),
        'totals_available': available,
        'metrics': data['metrics'] if available else None,
        'ratings': data['ratings'] if available else None,
        'closed_materials': data['closed_materials'] if available else None,
    }


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)


def _shown(value: object, *, missing: str = 'не указано') -> str:
    if value is None:
        return missing
    if type(value) is bool:
        return 'да' if value else 'нет'
    if isinstance(value, (list, dict)):
        return _json(value)
    return str(value)


def _time(value: str, timezone_name: str) -> str:
    instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError('Report timestamps must include a timezone')
    return instant.astimezone(ZoneInfo(timezone_name)).strftime('%d.%m.%Y %H:%M:%S %z')


def _fields(*pairs: tuple[str, object]) -> str:
    return '\n'.join(f'{label}: {_shown(value)}' for label, value in pairs)


def _page(title: str, sections: list[tuple[str, str]]) -> str:
    # Source data are text nodes only. No interpolated attributes or resources.
    body = ''.join(
        '<section><h2>' + escape(label, quote=True) + '</h2><pre>'
        + escape(value, quote=True) + '</pre></section>'
        for label, value in sections
    )
    safe_title = escape(title, quote=True)
    return (
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        'style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">'
        '<title>' + safe_title + '</title><style>'
        'body{max-width:72rem;margin:2rem auto;padding:1rem;font:18px sans-serif;'
        'color:#161616;background:#fff}pre{font:inherit;white-space:pre-wrap;'
        'overflow-wrap:anywhere}section{border-top:1px solid #999}h1{font-size:1.6rem}'
        '</style></head><body><h1>' + safe_title + '</h1>' + body + '</body></html>'
    )


def _provenance(data: dict) -> list[tuple[str, str]]:
    source, period = data['provenance'], data['period']
    zone = period['display_timezone']
    mode = 'СИНТЕТИЧЕСКИЕ ДАННЫЕ' if source['synthetic'] else 'ДАННЫЕ ИСТОЧНИКА: НЕ СИНТЕТИЧЕСКИЕ'
    return [
        ('Происхождение и область', _fields(
            ('Режим', mode), ('Источник', source['source_ref']),
            ('Разрешённая область', source['scope_description']),
            ('Полнота', _COVERAGE_LABELS.get(source['coverage'], source['coverage'])),
            ('История полная по заявлению источника', source['history_complete']),
            ('Доменное время снимка', _time(source['domain_as_of'], zone)),
            ('Реальное время получения', _time(source['captured_at_real'], zone)),
            ('Версия фактов', data['fact_schema_version']))),
        ('Период отчёта [начало, конец)',
         _time(period['start'], zone) + ' — ' + _time(period['end'], zone)
         + '\nЧасовой пояс: ' + zone + '; начало включено, конец исключён'),
    ]


def _limitations(data: dict) -> list[tuple[str, str]]:
    result = [('Ограничения', '\n'.join(data['limitations']))]
    if data['unavailable_reasons']:
        result.append(('Недоступные данные: причины источника', _json(data['unavailable_reasons'])))
    return result


def _assessment(row: dict, *, current: bool, zone: str, review: dict | None) -> str:
    chronology = 'В источнике нет решения мастера для сравнения времени'
    if review is not None:
        after_review = (datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
                        > datetime.fromisoformat(review['created_at'].replace('Z', '+00:00')))
        chronology = ('Записана после решения мастера' if after_review
                      else 'Записана не позже решения мастера; это не подтверждает её просмотр')
    return _fields(
        ('Идентификатор оценки', row['id']), ('Попытка', row['submission_id']),
        ('Ревизия назначения', row['assignment_revision']),
        ('Режим', _MODE_LABELS.get(row['mode'], row['mode'])),
        ('Модель', row['model']), ('Версия модели', row['model_version']),
        ('Рекомендация', {'satisfactory': 'Удовлетворительно',
                         'rework_recommended': 'Рекомендуется доработка',
                         'needs_master_review': 'Требуется проверка мастера'}.get(
                             row['recommendation'], row['recommendation'])),
        ('Версия схемы оценки', row['schema_version']),
        ('Длительность, миллисекунд', row['duration_ms']),
        ('Балл ИИ', _shown(row['score'], missing='не оценено')),
        ('Объяснения', row['reasons']), ('Источники', row['evidence_ids']),
        ('Причина резервного режима', row['fallback_reason']),
        ('Устаревшая оценка', row['stale']),
        ('Рекомендация текущей попытки', current and not row['stale']),
        ('Время оценки', _time(row['created_at'], zone)),
        ('Хронология оценки', chronology),
    )


def render_order_html(facts: AnalyticsFacts, order_id: str) -> str:
    """Return inert HTML for one observed order; missing IDs fail closed."""
    data = order_report_data(facts, order_id)
    fact, zone = data['order'], data['period']['display_timezone']
    order = fact['order']
    sections = _provenance(data)
    sections.extend([
        ('Наряд', _fields(
            ('Идентификатор', order['id']), ('Номер', order['number']),
            ('Состояние', _STATUS_LABELS.get(order['status'], order['status'])),
            ('Тип', {'planned': 'Плановый', 'unplanned': 'Внеплановый'}.get(order['type'], order['type'])),
            ('Участок', order['section_id']), ('Оборудование', order['equipment_id']),
            ('Исполнитель', order['assignment']['executor_id']),
            ('Бригада', order['assignment']['brigade_id']), ('Выдал', order['created_by']),
            ('Версия', order['version']), ('Ревизия назначения', order['assignment_revision']),
            ('Ревизия срока', order['scheduling_revision']),
            ('Выдан', _time(order['issued_at'], zone)), ('Срок', _time(order['due_at'], zone)),
            ('Обновлён', _time(order['updated_at'], zone)),
            ('Просрочен на доменное время снимка', fact['is_overdue']),
            ('Норма, минут', order['norm_minutes']),
            ('Приоритет', {'normal': 'Обычный', 'high': 'Высокий', 'emergency': 'Аварийный'}.get(
                order['priority'], order['priority'])))),
        ('Задание', order['description']), ('Комментарий мастера', order['comment']),
        ('Фото до работ', _shown(order['before_photo_ids'])),
        ('Сравнение до/после', 'не применимо: фото до работ не указаны'
         if not order['before_photo_ids'] else 'не выполнялось этим отчётом'),
    ])
    if not fact['attempts']:
        sections.append(('Попытки', 'В источнике нет попыток выполнения'))
    for attempt in fact['attempts']:
        sub, review = attempt['submission'], attempt['review']
        current = (sub['id'] == order['current_submission_id']
                   and sub['assignment_revision'] == order['assignment_revision'])
        sections.extend([
            (f"Попытка {sub['attempt_number']}, ревизия {sub['assignment_revision']}", _fields(
                ('Идентификатор попытки', sub['id']), ('Наряд', sub['order_id']),
                ('Отправил', sub['submitted_by']), ('Отправлено', _time(sub['submitted_at'], zone)),
                ('Текущая попытка', current), ('Отправлено после срока', sub['done_late']),
                ('Полнота', {'complete': 'Полный результат', 'incomplete': 'Неполный результат'}.get(
                    sub['completeness'], sub['completeness'])),
                ('Недостающие доказательства', sub['missing_evidence']))),
            ('Выполненные работы', sub['payload']['work_description']),
            ('Комментарий исполнителя', sub['payload']['comment']),
            ('Шифр работы', _shown(sub['payload']['work_code_id'])),
            ('Фото после работ: только идентификаторы', _shown(sub['payload']['after_photo_ids'])),
            ('Заявленные материалы попытки; не складское списание',
             _json(sub['payload']['materials']) if sub['payload']['materials']
             else 'Явный пустой список: материалы не заявлены'),
        ])
        if not attempt['assessments']:
            sections.append(('ИИ', 'Оценок в источнике нет; состояние задания ИИ неизвестно'))
        for assessment in attempt['assessments']:
            sections.append(('ИИ: рекомендация, не решение мастера',
                             _assessment(assessment, current=current, zone=zone, review=review)))
        if review is None:
            sections.append(('Решение мастера', 'Решения мастера в источнике нет'))
        else:
            sections.append(('Мастер: зафиксированное решение', _fields(
                ('Идентификатор решения', review['id']), ('Попытка', review['submission_id']),
                ('Мастер', review['reviewer_id']),
                ('Решение', {'close': 'Закрыть', 'rework': 'Вернуть на доработку'}.get(review['decision'], review['decision'])),
                ('Причина', review['reason']),
                ('Оценка мастера', _shown(review['final_score'], missing='не оценено')),
                ('Время решения', _time(review['created_at'], zone)))))
    return _page('Наряд ' + str(order['number']), sections + _limitations(data))


def _metric(row: dict) -> str:
    return _fields(
        ('Состояние показателя', {'ok': 'Данные доступны', 'no_cohort': 'Нет подходящих записей',
                                 'missing': 'Данные отсутствуют', 'partial': 'Частичные данные'}.get(
                                     row['status'], row['status'])),
        ('Значение', _shown(row['value'], missing='недостаточно данных')),
        ('Числитель', row['numerator']), ('Знаменатель', row['denominator']),
        ('Подходящих записей', row['eligible']), ('Без данных', row['missing']),
        ('Исключено', row['excluded']), ('Малая выборка', row['small_sample']),
        ('Таблица источника', row['source_table']), ('Все источники когорты, включая отсутствующие значения', row['source_ids']),
        ('Источники без данных', row['missing_source_ids']),
        ('Исключённые источники', row['excluded_source_ids']),
    )


def render_shift_html(facts: AnalyticsFacts) -> str:
    """Return inert HTML; unavailable totals remain unavailable, not zero."""
    data = shift_report_data(facts)
    sections = _provenance(data)
    if not data['totals_available']:
        sections.append(('Итоги смены', _TOTALS_UNAVAILABLE))
    else:
        for metric in data['metrics']:
            sections.append((_METRIC_LABELS.get(metric['name'], metric['name']), _metric(metric)))
        for rating in data['ratings']:
            sections.append(('Показатели исполнителя', _fields(
                ('Исполнитель', rating['executor_id']),
                ('Сводный рейтинг', _shown(rating['composite_score'], missing='недостаточно поддерживаемых данных')),
                ('Состояние сводного рейтинга', {'unsupported_inputs': 'Нет необходимых исходных показателей'}.get(
                    rating['composite_status'], rating['composite_status'])))))
            for name in ('human_score', 'closed_on_time', 'closed_with_rework'):
                sections.append((_METRIC_LABELS[name], _metric(rating[name])))
        if not data['closed_materials']:
            sections.append(('Заявленные материалы закрытых попыток', 'В выбранной когорте материалы не заявлены'))
        for material in data['closed_materials']:
            sections.append(('Заявленные материалы закрытых попыток; не складское списание', _fields(
                ('Материал', material['label']), ('Идентификатор', material['material_id']),
                ('Количество', material['quantity']), ('Единица', material['unit']),
                ('Наряды', material['order_ids']), ('Попытки', material['submission_ids']),
                ('Решения о закрытии', material['review_ids']))))
    return _page('Отчёт смены', sections + _limitations(data))
