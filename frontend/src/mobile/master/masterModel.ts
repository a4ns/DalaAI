import type { MasterCreateDraft, MasterDictionaries, MasterExecutor, MasterOrderVM, MasterReviewDraft } from './types';
import type { MutationOutcome, ResourceState } from '../../shared/ui/types';

export type DraftErrors = Partial<Record<keyof MasterCreateDraft, string>>;
export const orderStatusLabels = {
  issued: 'Выдан', queued: 'В очереди', accepted: 'Принят исполнителем', rejected: 'Отклонён исполнителем',
  in_progress: 'В работе', paused: 'Приостановлен', done: 'Результат отправлен', ai_review: 'На проверке мастера',
  rework: 'На доработке', closed: 'Закрыт мастером', cancelled: 'Отменён',
} as const;

/** Strict UTC+5 wall time conversion. Never uses the device's local timezone. */
export function dueLocalToIso(value: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) return null;
  const date = new Date(`${value}:00+05:00`);
  if (!Number.isFinite(date.getTime())) return null;
  const roundTrip = new Date(date.getTime() + 5 * 60 * 60 * 1000).toISOString().slice(0, 16);
  return roundTrip === value ? date.toISOString() : null;
}
export function formatMasterTime(iso: string): string {
  const date = new Date(iso);
  if (!Number.isFinite(date.getTime())) return 'Срок не загружен';
  return `${new Intl.DateTimeFormat('ru-RU', {
    timeZone: 'Asia/Almaty', day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  }).format(date)} (UTC+5)`;
}
export function executorLoad(executor: MasterExecutor): string {
  const state = !executor.onShift ? 'Не на смене' : executor.activeOrderId ? 'Занят' : executor.queueCount > 0 ? 'Есть очередь' : 'Занятость не подтверждена';
  return `${state}${executor.queueCount > 0 ? ` · в очереди: ${executor.queueCount}` : ''}`;
}
export function resourceIsCurrent<T>(resource: ResourceState<T>): boolean {
  return resource.loadStatus === 'ready' && resource.freshness === 'fresh' && resource.snapshot !== null && !resource.incomplete;
}
export function validateCreate(draft: MasterCreateDraft, dictionaries: MasterDictionaries | null, domainNow?: string | null): DraftErrors {
  const errors: DraftErrors = {};
  if (!draft.description.trim()) errors.description = 'Опишите задачу или неисправность.';
  else if (draft.description.length > 2000) errors.description = 'Не более 2000 символов.';
  if (!dictionaries?.sections.some(section => section.id === draft.sectionId)) errors.sectionId = 'Выберите доступный участок.';
  if (!dictionaries?.equipment.some(item => item.id === draft.equipmentId && item.sectionId === draft.sectionId)) errors.equipmentId = 'Выберите оборудование этого участка.';
  const executor = dictionaries?.executors.find(item => item.id === draft.executorId && item.sectionIds.includes(draft.sectionId));
  if (!executor) errors.executorId = 'Выберите ответственного исполнителя этого участка.';
  else if (!executor.onShift) errors.executorId = 'Выбранный исполнитель не на смене. Обновите данные или выберите другого.';
  if (draft.brigadeId && (!dictionaries?.brigades.some(item => item.id === draft.brigadeId) || executor?.brigadeId !== draft.brigadeId)) errors.brigadeId = 'Ответственный исполнитель должен входить в выбранную бригаду.';
  const dueIso = dueLocalToIso(draft.dueLocal);
  if (!dueIso) errors.dueLocal = 'Укажите существующую дату и время (UTC+5).';
  else if (domainNow && Number.isFinite(Date.parse(domainNow)) && Date.parse(dueIso) <= Date.parse(domainNow)) errors.dueLocal = 'Срок должен быть позже текущего времени сервера. Срок не изменён автоматически.';
  if (!/^\d+$/.test(draft.normMinutes) || Number(draft.normMinutes) < 1 || Number(draft.normMinutes) > 525600) errors.normMinutes = 'Укажите целое число минут от 1 до 525600.';
  if (draft.comment.length > 2000) errors.comment = 'Не более 2000 символов.';
  if (draft.beforePhotoIds.length > 5 || new Set(draft.beforePhotoIds).size !== draft.beforePhotoIds.length) errors.beforePhotoIds = 'Можно прикрепить до 5 разных фотографий.';
  return errors;
}
export function reviewErrors(draft: MasterReviewDraft): string[] {
  const errors: string[] = [];
  if (!draft.reason.trim()) errors.push('Укажите причину решения мастера.');
  else if (draft.reason.length > 2000) errors.push('Причина должна быть не длиннее 2000 символов.');
  if (draft.finalScore.trim() && (!/^\d+$/.test(draft.finalScore.trim()) || Number(draft.finalScore) > 100)) errors.push('Оценка: целое число от 0 до 100 или пустое поле.');
  return errors;
}
export function closeBlockers(order: MasterOrderVM): string[] {
  const blockers: string[] = [];
  if (order.status !== 'ai_review') blockers.push('Наряд сейчас не находится на проверке мастера.');
  const submission = order.submission;
  if (!submission) return [...blockers, 'Результат исполнителя ещё не загружен.'];
  if (submission.assignmentRevision !== order.assignmentRevision) blockers.push('Результат относится к предыдущему назначению.');
  if (submission.completeness !== 'complete') blockers.push(submission.completeness === 'unknown' ? 'Полнота результата не подтверждена сервером.' : 'Результат отмечен как неполный.');
  if (!submission.workDescription.trim()) blockers.push('Нет описания выполненных работ.');
  if (!submission.workCodeLabel) blockers.push('Не указан шифр работ.');
  if (order.type === 'unplanned' && submission.afterPhotoCount < 1) blockers.push('Для внеплановой работы требуется фото после выполнения.');
  return [...new Set([...blockers, ...submission.missingEvidence])];
}
/** A resolved Promise or thrown transport error is not evidence of a committed command. */
export function normalizeOutcome(value: unknown): MutationOutcome {
  if (value && typeof value === 'object' && 'kind' in value) {
    const outcome = value as { kind: unknown; message?: unknown };
    const message = typeof outcome.message === 'string' ? outcome.message : '';
    if (outcome.kind === 'confirmed') return { kind: 'confirmed', ...(message ? { message } : {}) };
    if (outcome.kind === 'rejected' || outcome.kind === 'conflict' || outcome.kind === 'unknown') return { kind: outcome.kind, message: message || 'Не удалось подтвердить результат операции.' };
  }
  return { kind: 'unknown', message: 'Результат не подтверждён. Не создавайте повторную операцию.' };
}

/** Ignore delayed uploads from another section, earlier form generation or unmounted identity. */
export function canApplyPhotoResult(context: { mounted: boolean; locked: boolean; expectedGeneration: number; currentGeneration: number; expectedSection: string; currentSection: string }): boolean {
  return context.mounted && !context.locked && context.expectedGeneration === context.currentGeneration && context.expectedSection === context.currentSection;
}
