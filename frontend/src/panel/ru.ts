/** Panel-local RU catalog. A second language requires reviewed translations. */
export const panelStatuses: Readonly<Record<string, string>> = {
  issued: 'Выдан',
  queued: 'В очереди',
  accepted: 'Принят исполнителем',
  rejected: 'Отклонён исполнителем',
  in_progress: 'В работе',
  paused: 'Приостановлен',
  done: 'Результат отправлен',
  ai_review: 'На проверке мастера',
  closed: 'Закрыт',
  rework: 'На доработке',
  cancelled: 'Отменён',
};

export const panelPriorities: Readonly<Record<string, string>> = {
  normal: 'Обычный',
  high: 'Высокий',
  emergency: 'Аварийный',
};

export const panelEventKinds: Readonly<Record<string, string>> = {
  'order.created': 'Наряд выдан',
  'order.queued': 'Добавлен в очередь',
  'order.accepted': 'Принят исполнителем',
  'order.rejected': 'Отклонён исполнителем',
  'order.started': 'Работа начата',
  'order.paused': 'Работа приостановлена',
  'order.resumed': 'Работа продолжена',
  'order.done': 'Результат отправлен',
  'order.ai_review_requested': 'Результат передан на проверку',
  'order.assessment_recorded': 'Оценка результата записана',
  'order.reviewed': 'Решение мастера записано',
  'order.reassigned': 'Наряд переназначен',
  'order.cancelled': 'Наряд отменён',
  'order.priority_changed': 'Приоритет изменён',
};

export const statusLabel = (status: string): string => Object.hasOwn(panelStatuses, status) ? panelStatuses[status] : 'Неизвестный статус';
export const priorityLabel = (priority: string): string => Object.hasOwn(panelPriorities, priority) ? panelPriorities[priority] : 'Неизвестный приоритет';
export const eventLabel = (kind: string): string => Object.hasOwn(panelEventKinds, kind) ? panelEventKinds[kind] : 'Событие наряда';
