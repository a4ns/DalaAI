"""Offline synthetic report example. Not a production renderer or API validator."""
import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html import escape
import hashlib
import json
from pathlib import Path
import re
from uuid import UUID

HERE = Path(__file__).resolve().parent
LIVE = {'issued', 'queued', 'accepted', 'rejected', 'in_progress', 'paused', 'rework'}
STATUSES = LIVE | {'done', 'ai_review', 'closed', 'cancelled'}
MARK = 'СИНТЕТИЧЕСКИЙ АВТОНОМНЫЙ ПРИМЕР'
RFC3339 = re.compile(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)')


def require(condition, code):
    if not condition:
        raise ValueError(code)


def timestamp(value):
    require(isinstance(value, str) and RFC3339.fullmatch(value), 'timestamp.format')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('timestamp.calendar') from None
    require(result.utcoffset() is not None, 'timestamp.zone')
    return result


def ident(value):
    try:
        require(isinstance(value, str) and str(UUID(value)) == value, 'id.canonical_uuid')
    except (ValueError, TypeError, AttributeError):
        raise ValueError('id.canonical_uuid') from None


def text(value, limit, *, blank=False):
    require(isinstance(value, str) and len(value) <= limit and (blank or bool(value.strip())), 'text.invalid')


def number(value):
    require(type(value) in (int, float, Decimal), 'quantity.number')
    try:
        result = Decimal(str(value))
        require(result.is_finite() and 0 < result <= 999999999, 'quantity.range')
        require(result == result.quantize(Decimal('.001')), 'quantity.precision')
    except InvalidOperation:
        raise ValueError('quantity.invalid') from None
    return result


def score(value):
    require(value is None or type(value) is int and 0 <= value <= 100, 'score.null_or_integer')


def unique(rows, code):
    require(isinstance(rows, list), code + '.list')
    found = {}
    for row in rows:
        require(isinstance(row, dict) and 'id' in row, code + '.object')
        ident(row['id'])
        require(row['id'] not in found, code + '.duplicate_id')
        found[row['id']] = row
    return found


def validate(data):
    """Only fixture invariants; does not prove authorization or all OpenAPI rules."""
    try:
        require(data['schema_version'] == 'c4-report-facts/1' and data['synthetic'] is True, 'synthetic_only')
        start, end = (timestamp(data['period'][k]) for k in ('start', 'end'))
        as_of = timestamp(data['coverage']['as_of'])
        require(start < end <= as_of, 'period.invalid')
        require(data['period']['display_offset'] == '+05:00', 'display_offset.unsupported')
        require(data['coverage']['kind'] in {'frozen_complete_synthetic', 'partial_keyset', 'drained_moving_keyset'}, 'coverage.unknown')
        scope = data['coverage']['scope_section_ids']
        require(isinstance(scope, list) and scope, 'scope.required')
        for sid in scope:
            ident(sid)
        orders = unique(data['orders'], 'order')
        subs = unique(data['submissions'], 'submission')
        materials = unique(data['materials'], 'material')
        for material in materials.values():
            text(material['code'], 80)
            text(material['label'], 200)
            text(material['unit'], 40)
        seen_attempts, all_reviews, all_assessments = set(), [], []
        for order in orders.values():
            text(order['number'], 80)
            text(order['description'], 2000)
            text(order['comment'], 2000, blank=True)
            require(order['status'] in STATUSES and order['type'] in {'planned', 'unplanned'}, 'order.enum')
            require(order['section_id'] in scope, 'order.outside_scope')
            for key in ('equipment_id', 'created_by'):
                ident(order[key])
            ident(order['assignment']['executor_id'])
            if order['assignment']['brigade_id'] is not None:
                ident(order['assignment']['brigade_id'])
            for key in ('version', 'assignment_revision', 'scheduling_revision', 'norm_minutes'):
                require(type(order[key]) is int and order[key] >= 1, 'order.positive_integer')
            require(timestamp(order['issued_at']) <= timestamp(order['updated_at']) <= as_of, 'order.snapshot_time')
            require(timestamp(order['domain_now']) == as_of, 'order.mixed_snapshot')
            expected_overdue = order['status'] in LIVE and timestamp(order['due_at']) < as_of
            require(type(order['is_overdue']) is bool and order['is_overdue'] == expected_overdue, 'order.overdue_mismatch')
            require(isinstance(order['before_photo_ids'], list), 'order.photos.list')
            for photo in order['before_photo_ids']:
                ident(photo)
        for sub in subs.values():
            require(sub['order_id'] in orders, 'submission.order_join')
            order = orders[sub['order_id']]
            ident(sub['submitted_by'])
            for key in ('assignment_revision', 'attempt_number'):
                require(type(sub[key]) is int and sub[key] >= 1, 'submission.positive_integer')
            key = (sub['order_id'], sub['assignment_revision'], sub['attempt_number'])
            require(key not in seen_attempts, 'submission.duplicate_attempt')
            seen_attempts.add(key)
            require(sub['assignment_revision'] <= order['assignment_revision'], 'submission.future_revision')
            submitted = timestamp(sub['submitted_at'])
            require(timestamp(order['issued_at']) <= submitted <= as_of, 'submission.time')
            require(type(sub['done_late']) is bool and sub['done_late'] == (submitted > timestamp(order['due_at'])), 'submission.done_late')
            payload = sub['payload']
            text(payload['work_description'], 6000)
            text(payload['comment'], 2000, blank=True)
            if payload['work_code_id'] is not None:
                ident(payload['work_code_id'])
            require(isinstance(payload['materials'], list) and len(payload['materials']) <= 40, 'materials.list')
            used = set()
            for use in payload['materials']:
                mid = use['material_id']
                require(mid in materials and mid not in used, 'material.join_or_duplicate')
                number(use['quantity'])
                used.add(mid)
            require(isinstance(payload['after_photo_ids'], list) and len(payload['after_photo_ids']) <= 5, 'photos.list')
            require(len(set(payload['after_photo_ids'])) == len(payload['after_photo_ids']), 'photos.duplicate')
            for photo in payload['after_photo_ids']:
                ident(photo)
            missing = []
            if payload['work_code_id'] is None:
                missing.append('WORK_CODE_REQUIRED')
            if order['type'] == 'unplanned' and not payload['after_photo_ids']:
                missing.append('AFTER_PHOTO_REQUIRED')
            require(sub['missing_evidence'] == missing and sub['completeness'] == ('incomplete' if missing else 'complete'), 'submission.completeness')
            for assessment in unique(sub['assessments'], 'assessment').values():
                require(assessment['submission_id'] == sub['id'] and assessment['assignment_revision'] == sub['assignment_revision'], 'assessment.join')
                require(assessment['mode'] in {'model', 'rules_fallback', 'manual'}, 'assessment.mode')
                require(assessment['recommendation'] in {'satisfactory', 'rework_recommended', 'needs_master_review'}, 'assessment.recommendation')
                require(assessment['schema_version'] == '1' and type(assessment['stale']) is bool, 'assessment.schema')
                require(type(assessment['duration_ms']) is int and assessment['duration_ms'] >= 0, 'assessment.duration')
                score(assessment['score'])
                require(submitted <= timestamp(assessment['created_at']) <= as_of, 'assessment.time')
                for field in ('model', 'model_version', 'fallback_reason'):
                    if assessment[field] is not None:
                        text(assessment[field], 120)
                require(isinstance(assessment['reasons'], list) and isinstance(assessment['evidence_ids'], list), 'assessment.lists')
                for reason in assessment['reasons']:
                    text(reason, 2000)
                for evidence in assessment['evidence_ids']:
                    ident(evidence)
                all_assessments.append(assessment)
            require(isinstance(sub['reviews'], list) and len(sub['reviews']) <= 1, 'submission.multiple_immutable_reviews')
            for review in unique(sub['reviews'], 'review').values():
                require(review['submission_id'] == sub['id'], 'review.join')
                ident(review['reviewer_id'])
                require(review['decision'] in {'close', 'rework'}, 'review.decision')
                require(submitted <= timestamp(review['created_at']) <= as_of, 'review.time')
                require(review['decision'] != 'close' or not missing, 'review.incomplete_close')
                score(review['final_score'])
                text(review['reason'], 2000)
                all_reviews.append(review)
        unique(all_reviews, 'review')
        unique(all_assessments, 'assessment')
        for order in orders.values():
            current = order['current_submission_id']
            if current is not None:
                require(current in subs and subs[current]['order_id'] == order['id'] and subs[current]['assignment_revision'] == order['assignment_revision'], 'order.current_submission_join')
            close = [r for s in subs.values() if s['order_id'] == order['id'] for r in s['reviews'] if r['decision'] == 'close']
            require(len(close) <= 1, 'order.duplicate_close')
            require(bool(close) == (order['status'] == 'closed'), 'order.close_status')
            if close:
                require(close[0]['submission_id'] == current, 'order.close_current')
        return orders, subs, materials
    except (KeyError, TypeError):
        raise ValueError('required_field_or_shape') from None


def dec(value):
    return format(Decimal(value), 'f').rstrip('0').rstrip('.') if '.' in format(Decimal(value), 'f') else format(Decimal(value), 'f')


def summary(data):
    orders, subs, materials = validate(data)
    if data['coverage']['kind'] != 'frozen_complete_synthetic':
        return {'totals': None, 'reason': 'Нет согласованного полного snapshot; число наблюдённых строк не является итогом смены'}
    start, end = (timestamp(data['period'][k]) for k in ('start', 'end'))
    inside = lambda value: start <= timestamp(value) < end
    submitted = [s for s in subs.values() if inside(s['submitted_at'])]
    closes = [(s, r) for s in subs.values() for r in s['reviews'] if r['decision'] == 'close' and inside(r['created_at'])]
    scored = [(s, r) for s, r in closes if r['final_score'] is not None]
    unscored = [(s, r) for s, r in closes if r['final_score'] is None]
    groups = defaultdict(lambda: {'quantity': Decimal(0), 'submission_ids': set(), 'review_ids': set(), 'order_ids': set()})
    for sub, review in closes:
        for use in sub['payload']['materials']:
            row = groups[(use['material_id'], materials[use['material_id']]['unit'])]
            row['quantity'] += number(use['quantity'])
            row['submission_ids'].add(sub['id'])
            row['review_ids'].add(review['id'])
            row['order_ids'].add(sub['order_id'])
    return dict(issued_order_ids=sorted(o['id'] for o in orders.values() if inside(o['issued_at'])),
        submitted_order_ids=sorted({s['order_id'] for s in submitted}), submitted_submission_ids=sorted(s['id'] for s in submitted),
        closed_order_ids=sorted(s['order_id'] for s, r in closes), close_review_ids=sorted(r['id'] for s, r in closes),
        rework_review_ids=sorted(r['id'] for s in subs.values() for r in s['reviews'] if r['decision'] == 'rework' and inside(r['created_at'])),
        overdue_order_ids=sorted(o['id'] for o in orders.values() if o['is_overdue']),
        human_scores=dict(cohort_count=len(closes), scored_count=len(scored), unscored_count=len(unscored), mean=dec(sum(Decimal(r['final_score']) for s, r in scored)/len(scored)) if scored else None, scored_review_ids=sorted(r['id'] for s, r in scored), unscored_review_ids=sorted(r['id'] for s, r in unscored)),
        timeliness=dict(numerator=sum(not s['done_late'] for s, r in closes), denominator=len(closes), on_time_submission_ids=sorted(s['id'] for s, r in closes if not s['done_late']), late_submission_ids=sorted(s['id'] for s, r in closes if s['done_late'])),
        closed_materials=[dict(material_id=mid, unit=unit, quantity=dec(row['quantity']), **{k: sorted(row[k]) for k in ('submission_ids','review_ids','order_ids')}) for (mid,unit),row in sorted(groups.items())])


def local_time(value):
    return timestamp(value).astimezone(timezone(timedelta(hours=5))).strftime('%d.%m.%Y %H:%M:%S UTC+5')


def shown_score(value):
    return 'не оценено' if value is None else str(value)


def page(title, rows):
    # All data are text nodes. No links, scripts, images, external resources or raw HTML input.
    body = ''.join('<section><h2>'+escape(str(label))+'</h2><pre>'+escape(str(value))+'</pre></section>' for label,value in rows)
    return '<!doctype html><html lang="ru"><meta charset="utf-8"><title>'+escape(title)+'</title><style>body{max-width:72rem;margin:2rem auto;font:18px sans-serif;padding:1rem}pre{font:inherit;white-space:pre-wrap;overflow-wrap:anywhere}section{border-top:1px solid #999}h1{font-size:1.5rem}</style><h1>'+escape(title)+'</h1><p>'+MARK+'</p><p>Не получено из БД; реальная модель не вызывалась; фото не проверялись</p>'+body+'</html>'


def provenance(data):
    normalized=json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str).encode('utf-8')
    return [('Происхождение автономного примера',
             'source_base_sha='+data['source_base_sha']+'\ncontract_sha256='+data['contract_sha256']+
             '\nnormalized_input_sha256='+hashlib.sha256(normalized).hexdigest()+
             '\nNormalization: sorted compact UTF-8 JSON; Decimal values encoded as strings'+
             '\ngenerated_at_real_utc='+datetime.now(timezone.utc).isoformat())]


def render_order(data, order_id):
    orders, subs, materials = validate(data)
    require(order_id in orders, 'order.not_in_capture')
    order = orders[order_id]
    rows = provenance(data)+[('Источник наряда / snapshot', json.dumps(order,ensure_ascii=False,indent=2)),
            ('Срок / доменное время снимка', local_time(order['due_at'])+' / '+local_time(order['domain_now'])),
            ('Ограничение хронологии', 'Показаны попытки и решения. Полного OrderEvent журнала в этом fixture нет'),
            ('Сравнение до/после', 'не применимо' if not order['before_photo_ids'] else 'фото не проверены')]
    for sub in sorted((s for s in subs.values() if s['order_id']==order_id),key=lambda s:(s['assignment_revision'],s['attempt_number'])):
        current = sub['id']==order['current_submission_id'] and sub['assignment_revision']==order['assignment_revision']
        rows.append((f"Попытка {sub['attempt_number']}, revision {sub['assignment_revision']}",f"order_id={order_id}\nsubmission_id={sub['id']}\nsubmitted_by={sub['submitted_by']}\n{local_time(sub['submitted_at'])}\ncurrent={current}; completeness={sub['completeness']}; missing_evidence={sub['missing_evidence']}; done_late={sub['done_late']}"))
        rows.append(('Выполненные работы',sub['payload']['work_description']))
        rows.append(('Комментарий исполнителя',sub['payload']['comment']))
        rows.append(('Шифр / after photo IDs',str(sub['payload']['work_code_id'])+' / '+str(sub['payload']['after_photo_ids'])))
        for use in sub['payload']['materials']:
            material = materials[use['material_id']]
            rows.append(('Заявлено в этой попытке; не складское списание',f"{material['id']} | {material['label']} | {dec(number(use['quantity'])).replace('.',',')} {material['unit']} | submission_id={sub['id']}"))
        if not sub['payload']['materials']:
            rows.append(('Материалы', 'явный пустой список; материалы не заявлены'))
        if not sub['assessments']:
            rows.append(('AI', 'оценок в источнике нет; состояние задания AI неизвестно'))
        for a in sub['assessments']:
            rows.append(('AI: рекомендация, не решение мастера', json.dumps(a,ensure_ascii=False,indent=2)+'\nscore: '+shown_score(a['score'])+'\ncurrent_recommendation='+str(current and not a['stale'])))
        if not sub['reviews']:
            rows.append(('Мастер', 'решения мастера нет'))
        for r in sub['reviews']:
            rows.append(('Мастер: зафиксированное решение',json.dumps(r,ensure_ascii=False,indent=2)+'\nfinal_score: '+shown_score(r['final_score'])))
    return page('Наряд '+order['number'],rows)


def render_shift(data):
    result = summary(data)
    rows = provenance(data)+[('Период [start, end)',local_time(data['period']['start'])+' — '+local_time(data['period']['end'])),
            ('Доменное as_of', local_time(data['coverage']['as_of'])),
            ('Полнота и scope',json.dumps(data['coverage'],ensure_ascii=False,indent=2)),
            ('Источники и значения',json.dumps(result,ensure_ascii=False,indent=2))]
    if result.get('totals', 'complete') is not None:
        rows += [('Количество',f"Выдано: {len(result['issued_order_ids'])}; отправлено нарядов: {len(result['submitted_order_ids'])}; попыток: {len(result['submitted_submission_ids'])}; закрыто: {len(result['closed_order_ids'])}; возвратов: {len(result['rework_review_ids'])}; просрочено: {len(result['overdue_order_ids'])}"),
                 ('Оценка закрытых, не рейтинг',f"Среднее: {shown_score(result['human_scores']['mean'])}; scored n={result['human_scores']['scored_count']}; unscored n={result['human_scores']['unscored_count']}; малая выборка при n<5"),
                 ('В срок среди закрытых',f"{result['timeliness']['numerator']}/{result['timeliness']['denominator']}" if result['timeliness']['denominator'] else 'недостаточно данных; n=0')]
        for row in result['closed_materials']:
            rows.append(('Материалы закрытых попыток; не фактический расход',f"{row['material_id']}: {row['quantity'].replace('.',',')} {row['unit']}"))
    return page('Отчёт смены',rows)


def load_case():
    return json.loads((HERE/'c4-report-cases.json').read_text(),parse_float=Decimal)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    data=load_case()
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/'order.html').write_text(render_order(data,data['orders'][0]['id']),encoding='utf-8')
    (args.output_dir/'shift.html').write_text(render_shift(data),encoding='utf-8')
    (args.output_dir/'summary.json').write_text(json.dumps(summary(data),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('PASS synthetic offline data/render generation; DB/API/model/device/visual NOT_RUN')


if __name__ == '__main__':
    main()
