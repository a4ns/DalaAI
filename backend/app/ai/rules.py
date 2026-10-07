"""Deterministic gates and honest fallback; no state writes, I/O or model calls."""
from datetime import datetime, timezone
from uuid import UUID

from .models import (Assessment, ClosureInput, EvidenceContext, Gate, GateReport,
                     InputValidationError, Material, PhotoEvidence)


def _uuid(value: object, path: str) -> None:
    try:
        if not isinstance(value, str) or str(UUID(value)) != value.lower():
            raise ValueError
    except (ValueError, AttributeError):
        raise InputValidationError(path + ':UUID_REQUIRED') from None


def _revision(value: object, path: str) -> None:
    if type(value) is not int or value < 1:
        raise InputValidationError(path + ':POSITIVE_INTEGER_REQUIRED')


def validate_input(data: ClosureInput, context: EvidenceContext) -> None:
    if not isinstance(data, ClosureInput) or not isinstance(context, EvidenceContext):
        raise InputValidationError('TYPED_INPUT_REQUIRED')
    for name in ('order_id', 'submission_id'):
        _uuid(getattr(data, name), name)
    _uuid(context.current_order_id, 'current_order_id')
    if context.current_submission_id is not None:
        _uuid(context.current_submission_id, 'current_submission_id')
    _revision(data.assignment_revision, 'assignment_revision')
    _revision(context.current_assignment_revision, 'current_assignment_revision')
    if data.order_type not in ('planned', 'unplanned'):
        raise InputValidationError('order_type:INVALID')
    for name in ('problem_description', 'work_description'):
        value = getattr(data, name)
        maximum = 2000 if name == 'problem_description' else 6000
        if not isinstance(value, str) or len(value) > maximum:
            raise InputValidationError(name + ':TEXT_REQUIRED_OR_TOO_LONG')
    if data.work_code_id is not None:
        _uuid(data.work_code_id, 'work_code_id')
    if type(data.materials) is not tuple or len(data.materials) > 40:
        raise InputValidationError('materials:BOUNDED_TUPLE_REQUIRED')
    for material in data.materials:
        if not isinstance(material, Material):
            raise InputValidationError('materials:TYPED_MATERIAL_REQUIRED')
        _uuid(material.material_id, 'materials.material_id')
    if type(data.after_photo_ids) is not tuple or len(data.after_photo_ids) > 5:
        raise InputValidationError('after_photo_ids:BOUNDED_TUPLE_REQUIRED')
    for photo_id in data.after_photo_ids:
        _uuid(photo_id, 'after_photo_ids')
    if context.submission_completeness not in ('complete', 'incomplete', None):
        raise InputValidationError('submission_completeness:INVALID')
    if type(context.missing_evidence) is not tuple or not all(
            isinstance(code, str) for code in context.missing_evidence):
        raise InputValidationError('missing_evidence:STRING_TUPLE_REQUIRED')
    for name in ('work_code_ids', 'material_ids'):
        ids = getattr(context, name)
        if ids is not None:
            if type(ids) is not frozenset:
                raise InputValidationError(name + ':FROZENSET_REQUIRED')
            for evidence_id in ids:
                _uuid(evidence_id, name)
    if type(context.photos) is not tuple:
        raise InputValidationError('photos:TUPLE_REQUIRED')
    for photo in context.photos:
        if not isinstance(photo, PhotoEvidence):
            raise InputValidationError('photos:TYPED_PHOTO_REQUIRED')
        for name in ('id', 'order_id', 'submission_id'):
            _uuid(getattr(photo, name), 'photos.' + name)
        _revision(photo.assignment_revision, 'photos.assignment_revision')
        if photo.purpose not in ('before', 'after') or (photo.file_valid is not None
                and type(photo.file_valid) is not bool):
            raise InputValidationError('photos:INVALID_VALIDATION_EVIDENCE')
    if len({p.id for p in context.photos}) != len(context.photos):
        raise InputValidationError('photos:DUPLICATE_EVIDENCE')


def evaluate_gates(data: ClosureInput, context: EvidenceContext) -> GateReport:
    """Unknown evidence cannot pass; independent gates cannot offset each other."""
    from decimal import Decimal, InvalidOperation
    validate_input(data, context)
    gates: list[Gate] = []
    base = (data.order_id, data.submission_id)

    def add(code: str, status: str, ids: tuple[str, ...] = base) -> None:
        gates.append(Gate(code, status, ids))

    current = (data.order_id == context.current_order_id
               and data.submission_id == context.current_submission_id
               and data.assignment_revision == context.current_assignment_revision
               and context.current_status == 'ai_review')
    add('CURRENT_ATTEMPT', 'pass' if current else 'fail')
    completeness = context.submission_completeness
    add('PERSISTED_COMPLETENESS', 'unknown' if completeness is None else
        'pass' if completeness == 'complete' and not context.missing_evidence else 'fail')
    add('WORK_DESCRIPTION', 'pass' if data.work_description.strip() else 'fail')
    code_status = ('fail' if data.work_code_id is None else
                   'unknown' if context.work_code_ids is None else
                   'pass' if data.work_code_id in context.work_code_ids else 'fail')
    add('WORK_CODE', code_status, base + ((data.work_code_id,) if data.work_code_id else ()))
    material_ids = tuple(m.material_id for m in data.materials)
    try:
        valid_quantities = all(isinstance(m.quantity, Decimal) and m.quantity.is_finite()
                               and 0 < m.quantity <= Decimal('999999999')
                               and m.quantity == m.quantity.quantize(Decimal('0.001'))
                               for m in data.materials)
    except InvalidOperation:
        valid_quantities = False
    add('MATERIAL_QUANTITIES', 'pass' if valid_quantities else 'fail', base + material_ids)
    add('MATERIAL_DISTINCT', 'pass' if len(set(material_ids)) == len(material_ids) else 'fail',
        base + material_ids)
    materials_status = ('pass' if not material_ids else
                        'unknown' if context.material_ids is None else
                        'pass' if all(mid in context.material_ids for mid in material_ids) else 'fail')
    add('MATERIAL_CATALOG', materials_status, base + material_ids)
    add('AFTER_PHOTO_REQUIRED', 'fail' if data.order_type == 'unplanned'
        and not data.after_photo_ids else 'pass')
    add('AFTER_PHOTO_DISTINCT', 'pass' if len(set(data.after_photo_ids)) == len(data.after_photo_ids)
        else 'fail', base + data.after_photo_ids)
    photo_map = {photo.id: photo for photo in context.photos}
    for photo_id in data.after_photo_ids:
        photo = photo_map.get(photo_id)
        binding = ('unknown' if photo is None else 'pass' if (
            photo.order_id == data.order_id and photo.submission_id == data.submission_id
            and photo.assignment_revision == data.assignment_revision and photo.purpose == 'after')
            else 'fail')
        add('AFTER_PHOTO_BINDING', binding, base + (photo_id,))
        validity = (None if photo is None else photo.file_valid)
        add('AFTER_PHOTO_FILE', 'unknown' if validity is None else 'pass' if validity else 'fail',
            base + (photo_id,))
    return GateReport(tuple(gates), stale=not current)


GATE_LABELS = {
    'CURRENT_ATTEMPT': 'Текущая попытка и назначение',
    'PERSISTED_COMPLETENESS': 'Сохранённая полнота результата',
    'WORK_DESCRIPTION': 'Описание выполненных работ',
    'WORK_CODE': 'Обязательный шифр работ',
    'MATERIAL_QUANTITIES': 'Допустимое количество материалов',
    'MATERIAL_DISTINCT': 'Уникальность строк материалов',
    'MATERIAL_CATALOG': 'Материалы из справочника',
    'AFTER_PHOTO_REQUIRED': 'Обязательное фото после внеплановых работ',
    'AFTER_PHOTO_DISTINCT': 'Уникальность фото',
    'AFTER_PHOTO_BINDING': 'Принадлежность фото текущей попытке',
    'AFTER_PHOTO_FILE': 'Подтверждённая проверка файла фото',
}
FALLBACK_REASONS = frozenset({'provider_not_configured', 'synthetic_provider', 'provider_timeout',
                             'provider_invalid_response', 'provider_unavailable'})


def assess_rules(data: ClosureInput, context: EvidenceContext, *, assessment_id: str,
                 created_at: datetime, duration_ms: int = 0,
                 fallback_reason: str = 'provider_not_configured') -> tuple[Assessment, GateReport]:
    """Numeric coverage is calculated here; total quality score remains unknown.

    A satisfactory mandatory-gate report still requires human final review and
    does not establish text semantics, material suitability or photo contents.
    """
    _uuid(assessment_id, 'assessment_id')
    if not isinstance(created_at, datetime) or created_at.tzinfo is None or created_at.utcoffset() is None:
        raise InputValidationError('created_at:AWARE_TIME_REQUIRED')
    if type(duration_ms) is not int or duration_ms < 0:
        raise InputValidationError('duration_ms:NONNEGATIVE_INTEGER_REQUIRED')
    if fallback_reason not in FALLBACK_REASONS:
        raise InputValidationError('fallback_reason:UNKNOWN_CODE')
    report = evaluate_gates(data, context)
    counts = report.counts
    reasons = [f"Обязательные проверки: пройдено {counts['pass']} из {len(report.gates)}, "
               f"не пройдено {counts['fail']}, неизвестно {counts['unknown']}."]
    for gate in report.gates:
        if gate.status != 'pass':
            status = 'не пройдено' if gate.status == 'fail' else 'недостаточно данных'
            reasons.append(f'{GATE_LABELS[gate.code]}: {status}.')
    reasons += ['Семантика работ, пригодность материалов и содержание фото не оценены моделью; общий балл неизвестен.',
                'Финальное решение принимает мастер с причиной; правила не закрывают наряд и не возвращают его автоматически.']
    recommendation = ('rework_recommended' if counts['fail'] and not report.stale else
                      'needs_master_review')
    ids = tuple(dict.fromkeys(eid for gate in report.gates for eid in gate.evidence_ids))
    return Assessment(assessment_id, data.submission_id, data.assignment_revision, duration_ms,
                      recommendation, tuple(reasons), ids, fallback_reason, report.stale,
                      created_at.astimezone(timezone.utc)), report
