export const ru = {
  product: 'НарядAI',
  loadingOrders: 'Загружаем наряды…',
  emptyOrders: 'Нарядов пока нет',
  readError: 'Не удалось загрузить наряды. Повторить',
  offline: 'Нет сети. Изменения не отправлены',
  unknownResult: 'Результат операции не подтверждён',
  stale: 'Показаны ранее полученные данные. Они могут быть неактуальны.',
  incomplete: 'Получена только часть данных.',
  noAssessment: 'Оценка пока отсутствует',
  memoryDraft: 'Черновик хранится только на этой странице. При обновлении или выходе он будет потерян.',
} as const;

export const statusLabels: Record<string, string> = {
  issued: 'Выдан', queued: 'В очереди', accepted: 'Принят', rejected: 'Отклонён',
  in_progress: 'В работе', paused: 'Приостановлен', done: 'Результат отправлен',
  ai_review: 'На проверке мастера', rework: 'На доработке', closed: 'Закрыт', cancelled: 'Отменён',
};
