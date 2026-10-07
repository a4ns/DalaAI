import type { ResourceState } from '../../shared/ui/types';
import type { ExecutorAction, ExecutorDictionaries, ExecutorDraft, ExecutorOrderStatus, ExecutorOrderViewModel, ExecutorSubmitPayload } from './types';

export const STATUS_LABELS: Record<ExecutorOrderStatus, string> = {
  issued: 'Выдан', queued: 'В очереди', accepted: 'Принят', rejected: 'Отклонён',
  in_progress: 'В работе', paused: 'На паузе', done: 'Результат отправлен',
  ai_review: 'На проверке', rework: 'На доработку', closed: 'Закрыт', cancelled: 'Отменён',
};
export const ACTION_LABELS: Record<ExecutorAction, string> = {
  queue: 'В очередь', accept: 'Принять', reject: 'Отклонить', start: 'Начать работу',
  pause: 'Приостановить', resume: 'Продолжить работу', submit: 'Отправить на проверку',
};
const ALLOWED_ACTIONS: Record<ExecutorOrderStatus, readonly ExecutorAction[]> = {
  issued: ['accept', 'queue', 'reject'], queued: ['accept'], accepted: ['start'],
  rejected: [], in_progress: ['submit', 'pause'], paused: ['resume'], done: [],
  ai_review: [], rework: ['start'], closed: [], cancelled: [],
};
export function allowedActions(status: ExecutorOrderStatus): readonly ExecutorAction[] {
  return ALLOWED_ACTIONS[status] ?? [];
}
export function emptyExecutorDraft(): ExecutorDraft {
  return { workDescription: '', workCodeId: '', materials: [], afterPhotoIds: [], comment: '', reason: '' };
}
export function isFreshResource<T>(resource: ResourceState<T>): boolean {
  return resource.snapshot !== null && resource.freshness === 'fresh' && resource.loadStatus === 'ready' && !resource.incomplete;
}
export function isConfirmedEmpty<T>(resource: ResourceState<T[]>): boolean {
  return isFreshResource(resource) && resource.snapshot?.length === 0;
}
export function formatExecutorTime(iso: string): string {
  const date = new Date(iso);
  if (!Number.isFinite(date.getTime())) return 'Время не получено';
  return new Intl.DateTimeFormat('ru-RU', {
    timeZone: 'Asia/Almaty', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date) + ' (UTC+5)';
}
export type DraftErrors = Record<string, string>;
/** Decimal text is validated before coercion: no exponent, Infinity, zero, negative or excess precision. */
export function parseQuantity(text: string): number | null {
  const normalized = text.trim().replace(',', '.');
  if (!/^\d+(?:\.\d{1,3})?$/.test(normalized)) return null;
  const value = Number(normalized);
  return Number.isFinite(value) && value > 0 && value <= 999999999 ? value : null;
}
export function validateExecutorDraft(draft: ExecutorDraft, dictionaries: ExecutorDictionaries | null): DraftErrors {
  const errors: DraftErrors = {};
  if (!draft.workDescription.trim()) errors.workDescription = 'Опишите выполненные работы.';
  else if (draft.workDescription.trim().length > 6000) errors.workDescription = 'Описание должно быть не длиннее 6000 символов.';
  if (draft.comment.length > 2000) errors.comment = 'Комментарий должен быть не длиннее 2000 символов.';
  if (draft.workCodeId && !dictionaries?.workCodes.some((item) => item.id === draft.workCodeId)) {
    errors.workCodeId = 'Выбранный шифр отсутствует в актуальном справочнике.';
  }
  const seen = new Set<string>();
  if (draft.materials.length > 40) errors.materials = 'Допускается не более 40 материалов.';
  for (const row of draft.materials) {
    if (!dictionaries?.materials.some((item) => item.id === row.materialId)) {
      errors[`material:${row.rowId}`] = 'Выберите материал из справочника.';
    } else if (seen.has(row.materialId)) {
      errors[`material:${row.rowId}`] = 'Материал уже добавлен. Укажите общий расход в одной строке.';
    }
    seen.add(row.materialId);
    if (parseQuantity(row.quantity) === null) errors[`quantity:${row.rowId}`] = 'Введите количество больше 0, до 999999999, не более трёх знаков после запятой.';
  }
  if (draft.afterPhotoIds.length > 5 || new Set(draft.afterPhotoIds).size !== draft.afterPhotoIds.length || draft.afterPhotoIds.some((id) => !id.trim())) {
    errors.photos = 'Допускается до 5 разных подтверждённых фото.';
  }
  return errors;
}
export function incompleteEvidence(order: Pick<ExecutorOrderViewModel, 'type'>, draft: ExecutorDraft): string[] {
  const missing = [];
  if (!draft.workCodeId) missing.push('шифр работ');
  if (order.type === 'unplanned' && draft.afterPhotoIds.length === 0) missing.push('фото после выполнения');
  return missing;
}
export function toSubmitPayload(draft: ExecutorDraft): ExecutorSubmitPayload {
  return {
    workDescription: draft.workDescription.trim(), workCodeId: draft.workCodeId || null,
    materials: draft.materials.map((row) => {
      const quantity = parseQuantity(row.quantity);
      if (quantity === null) throw new Error('Недопустимое количество материала');
      return { materialId: row.materialId, quantity };
    }),
    afterPhotoIds: [...draft.afterPhotoIds], comment: draft.comment.trim(),
  };
}
