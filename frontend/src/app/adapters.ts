import type { Dictionaries, Order, OrderEvent, Submission } from '../shared/api/wire';
import type { ResourceState } from '../shared/ui/types';
import type { MasterDictionaries, MasterOrderVM, MasterSubmissionVM } from '../mobile/master/types';
import type { ExecutorDictionaries, ExecutorOrderViewModel } from '../mobile/executor/types';
import type { PanelEmployee, PanelEvent, PanelOrder } from '../panel/types';

export function mapResource<A, B>(state: ResourceState<A>, transform: (value: A) => B): ResourceState<B> {
  return { ...state, snapshot: state.snapshot === null ? null : transform(state.snapshot) };
}
const label = (items: readonly { id: string; label: string }[] | undefined, id: string, fallback: string): string => items?.find(item => item.id === id)?.label ?? `${fallback} · ${id}`;
const executorLabel = (dicts: Dictionaries | null, id: string): string => dicts?.executors.find(item => item.id === id)?.employee_code ?? `Исполнитель · ${id}`;
export function masterDictionaries(dicts: Dictionaries): MasterDictionaries {
  return {
    sections: dicts.sections, equipment: dicts.equipment.map(item => ({ ...item, sectionId: item.section_id })), brigades: dicts.brigades,
    executors: dicts.executors.map(item => ({ id: item.id, label: item.employee_code, sectionIds: item.section_ids, brigadeId: item.brigade_id, onShift: item.on_shift, activeOrderId: item.active_order_id, queueCount: item.queue_count })),
  };
}
export function executorDictionaries(dicts: Dictionaries): ExecutorDictionaries { return { workCodes: dicts.work_codes, materials: dicts.materials }; }
export function masterSubmission(submission: Submission, dicts: Dictionaries | null): MasterSubmissionVM {
  const assessments = [...submission.assessments].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
  const assessment = assessments.find(item => !item.stale && item.assignment_revision === submission.assignment_revision && item.submission_id === submission.id) ?? assessments[0];
  return {
    id: submission.id, assignmentRevision: submission.assignment_revision, attemptNumber: submission.attempt_number,
    workDescription: submission.payload.work_description,
    workCodeLabel: submission.payload.work_code_id ? label(dicts?.work_codes, submission.payload.work_code_id, 'Шифр') : null,
    materials: submission.payload.materials.map(item => ({ label: label(dicts?.materials, item.material_id, 'Материал'), quantity: String(item.quantity), unit: dicts?.materials.find(material => material.id === item.material_id)?.unit ?? 'единица не указана' })),
    afterPhotoCount: submission.payload.after_photo_ids.length, comment: submission.payload.comment,
    completeness: submission.completeness, missingEvidence: submission.missing_evidence.map(code => code === 'WORK_CODE_REQUIRED' ? 'Не указан шифр работ' : code === 'AFTER_PHOTO_REQUIRED' ? 'Нет обязательного фото после выполнения' : 'Неизвестное обязательное доказательство'),
    assessment: assessment ? { mode: assessment.mode, recommendation: assessment.recommendation, score: assessment.score, reasons: assessment.reasons, stale: assessment.stale || assessment.assignment_revision !== submission.assignment_revision || assessment.submission_id !== submission.id, fallbackReason: assessment.fallback_reason } : null,
  };
}
export function masterOrder(order: Order, dicts: Dictionaries | null, submission: Submission | null): MasterOrderVM {
  return { id: order.id, number: order.number, version: order.version, assignmentRevision: order.assignment_revision, status: order.status, type: order.type, description: order.description, equipmentLabel: label(dicts?.equipment, order.equipment_id, 'Оборудование'), executorLabel: executorLabel(dicts, order.assignment.executor_id), dueAt: order.due_at, isOverdue: order.is_overdue, submission: submission && submission.order_id === order.id && submission.id === order.current_submission_id && submission.assignment_revision === order.assignment_revision ? masterSubmission(submission, dicts) : null };
}
export function executorOrder(order: Order, dicts: Dictionaries | null): ExecutorOrderViewModel {
  return { id: order.id, number: order.number, version: order.version, assignmentRevision: order.assignment_revision, sectionId: order.section_id, equipmentLabel: label(dicts?.equipment, order.equipment_id, 'Оборудование'), sectionLabel: label(dicts?.sections, order.section_id, 'Участок'), status: order.status, type: order.type, priority: order.priority, description: order.description, comment: order.comment, dueAt: order.due_at, isOverdue: order.is_overdue };
}
export function panelOrder(order: Order, dicts: Dictionaries | null): PanelOrder {
  return { id: order.id, number: order.number, title: order.description, sectionLabel: label(dicts?.sections, order.section_id, 'Участок'), equipmentLabel: label(dicts?.equipment, order.equipment_id, 'Оборудование'), executorLabel: executorLabel(dicts, order.assignment.executor_id), status: order.status, priority: order.priority, dueAt: order.due_at, isOverdue: order.is_overdue, version: order.version };
}
export function panelEmployees(dicts: Dictionaries): PanelEmployee[] { return dicts.executors.map(item => ({ id: item.id, label: item.employee_code, onShift: item.on_shift, activeOrderId: item.active_order_id, queueCount: item.queue_count })); }
export function panelEvent(event: OrderEvent, dicts: Dictionaries | null, self: { user_id: string; employee_code: string }): PanelEvent {
  return { id: event.id, sequence: event.sequence, occurredAt: event.occurred_at, kind: event.kind, actorLabel: event.actor_id === null ? 'Система' : event.actor_id === self.user_id ? self.employee_code : executorLabel(dicts, event.actor_id).replace('Исполнитель ·', 'Участник ·'), reason: event.reason, fromStatus: event.from_status, toStatus: event.to_status };
}
