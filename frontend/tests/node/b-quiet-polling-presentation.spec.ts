import { expect, test } from '@playwright/test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { sourceModule } from '../support/source';
import { ssrSourceModule } from '../support/ssr-source';
import { deferred, json, result } from '../support/synthetic';
import type * as Client from '../../src/shared/api/client';
import type * as Store from '../../src/shared/api/orderStore';
import type * as Master from '../../src/mobile/master/MasterScreen';
import type * as MasterModel from '../../src/mobile/master/masterModel';
import type * as MasterTypes from '../../src/mobile/master/types';
import type * as Executor from '../../src/mobile/executor/ExecutorScreen';
import type * as ExecutorModel from '../../src/mobile/executor/model';
import type * as Panel from '../../src/panel/PanelScreen';
import type * as PanelModel from '../../src/panel/model';
import type * as PanelLabels from '../../src/panel/ru';
import type { ExecutorOrderViewModel, ExecutorScreenProps } from '../../src/mobile/executor/types';
import type { PanelOrder, PanelScreenProps } from '../../src/panel/types';
import type { ResourceState } from '../../src/shared/ui/types';

// Synthetic OrderStore + static React markup only. These checks do not measure
// browser bounds, layout shifts, focus, scroll position, real API or Android behavior.
const { ApiClient } = sourceModule<typeof Client>('src/shared/api/client.ts');
const { OrderStore } = sourceModule<typeof Store>('src/shared/api/orderStore.ts');
const masterTypes = sourceModule<typeof MasterTypes>('src/mobile/master/types.ts');
const { MasterScreen } = ssrSourceModule<typeof Master>('src/mobile/master/MasterScreen.tsx', {
  './types': masterTypes, './masterModel': sourceModule<typeof MasterModel>('src/mobile/master/masterModel.ts'), './master.css': {},
});
const { ExecutorScreen } = ssrSourceModule<typeof Executor>('src/mobile/executor/ExecutorScreen.tsx', {
  './model': sourceModule<typeof ExecutorModel>('src/mobile/executor/model.ts'), './executor.css': {},
});
const { PanelScreen } = ssrSourceModule<typeof Panel>('src/panel/PanelScreen.tsx', {
  './model': sourceModule<typeof PanelModel>('src/panel/model.ts'), './ru': sourceModule<typeof PanelLabels>('src/panel/ru.ts'), './panel.css': {},
});
const ready = <T,>(snapshot: T): ResourceState<T> => ({
  snapshot, freshness: 'fresh', loadStatus: 'ready', error: null,
  lastConfirmedAt: '2026-10-08T06:00:00Z', incomplete: false,
});
const polling = <T,>(resource: ResourceState<T>): ResourceState<T> => ({ ...resource, loadStatus: 'loading', freshness: 'stale' });
const executorOrder: ExecutorOrderViewModel = {
  id: 'synthetic-order', number: 'SYNTHETIC-POLL', version: 3, assignmentRevision: 1,
  sectionId: 'synthetic-section', sectionLabel: 'Синтетический участок', equipmentLabel: 'Тестовый насос',
  status: 'in_progress', type: 'planned', priority: 'normal', description: 'Синтетическая работа',
  comment: '', dueAt: '2026-10-08T10:00:00Z', isOverdue: false,
};
const masterOrder: MasterTypes.MasterOrderVM = { ...executorOrder, executorLabel: 'Синтетический исполнитель', submission: null };
const panelOrder: PanelOrder = { ...executorOrder, title: executorOrder.description, executorLabel: 'Синтетический исполнитель' };
const noop = () => {};
const masterProps = (orders: ResourceState<MasterTypes.MasterOrderVM[]>, patch: Partial<MasterTypes.MasterScreenProps> = {}): MasterTypes.MasterScreenProps => ({
  orders, dictionaries: ready({ sections: [], equipment: [], brigades: [], executors: [] }),
  createDraft: { ...masterTypes.emptyMasterCreateDraft(), description: 'Сохранённый черновик мастера' },
  reviewDrafts: {}, online: true, domainNow: '2026-10-08T06:00:00Z',
  onCreateDraftChange: noop, onReviewDraftChange: noop, onReload: async () => {},
  onCreate: async () => ({ kind: 'confirmed' }), onReview: async () => ({ kind: 'confirmed' }), ...patch,
});
const executorProps = (orders: ResourceState<ExecutorOrderViewModel[]>, patch: Partial<ExecutorScreenProps> = {}): ExecutorScreenProps => ({
  orders, sessionKey: 'synthetic-poll-session', operationScopeKey: 'synthetic-order:1',
  dictionaries: ready({ workCodes: [], materials: [] }), selectedOrderId: executorOrder.id,
  drafts: { [executorOrder.id]: { workDescription: 'Сохранённый черновик исполнителя', workCodeId: '', materials: [], afterPhotoIds: [], comment: '', reason: '' } },
  mutation: { status: 'idle', error: null }, pendingIntent: null,
  onSelectOrder: noop, onDraftChange: noop, onRefresh: noop, onResolveConflict: noop,
  onIntent: async () => ({ kind: 'confirmed' }), onRetry: async () => ({ kind: 'confirmed' }), ...patch,
});
const panelProps = (orders: ResourceState<readonly PanelOrder[]>, patch: Partial<PanelScreenProps> = {}): PanelScreenProps => ({
  orders, selectedOrderId: null, onSelectOrder: noop, onRefresh: noop, ...patch,
});
const renderMaster = (orders: ResourceState<MasterTypes.MasterOrderVM[]>, patch: Partial<MasterTypes.MasterScreenProps> = {}) => renderToStaticMarkup(createElement(MasterScreen, masterProps(orders, patch)));
const renderExecutor = (orders: ResourceState<ExecutorOrderViewModel[]>, patch: Partial<ExecutorScreenProps> = {}) => renderToStaticMarkup(createElement(ExecutorScreen, executorProps(orders, patch)));
const renderPanel = (orders: ResourceState<readonly PanelOrder[]>, patch: Partial<PanelScreenProps> = {}) => renderToStaticMarkup(createElement(PanelScreen, panelProps(orders, patch)));
// Loading must still change these safety/accessibility attributes, but not visible structure or copy.
const presentation = (html: string) => html.replace(/ disabled=""| aria-busy="(?:true|false)"/g, '');
const waitCopy = 'Обновляемый статус ещё не получен.';
const actionDisabled = (html: string, label: string) => expect(html).toMatch(new RegExp(`<button[^>]*disabled=""[^>]*>${label}</button>`));

test('B quiet polling: repeated real store refreshes preserve markup while commands remain disabled', async () => {
  let response = deferred<Response>();
  const client = new ApiClient({ online: () => true, fetch: async () => response.promise });
  const store = new OrderStore(client);
  const wireOrder = { ...result().order, version: 3, status: 'in_progress' as const };
  const first = store.refresh(); response.resolve(json({ items: [wireOrder], next_cursor: null })); await first;
  expect(store.getSnapshot()).toMatchObject({ loadStatus: 'ready', freshness: 'fresh', incomplete: false });
  const render = () => {
    const state = store.getSnapshot();
    return {
      master: renderMaster({ ...state, snapshot: state.snapshot?.map(() => masterOrder) ?? null }),
      executor: renderExecutor({ ...state, snapshot: state.snapshot?.map(() => executorOrder) ?? null }),
      panel: renderPanel({ ...state, snapshot: state.snapshot?.map(() => panelOrder) ?? null }),
    };
  };
  try {
    for (let cycle = 0; cycle < 3; cycle++) {
      const before = render(); response = deferred<Response>(); const refresh = store.refresh();
      expect(store.getSnapshot()).toMatchObject({ loadStatus: 'loading', freshness: 'stale', incomplete: false });
      const during = render();
      for (const screen of ['master', 'executor', 'panel'] as const) expect(presentation(during[screen])).toBe(presentation(before[screen]));
      actionDisabled(during.executor, 'Приостановить');
      expect(during.executor).toContain('Сохранённый черновик исполнителя');
      expect(during.master).toContain('Сохранённый черновик мастера');
      response.resolve(json({ items: [wireOrder], next_cursor: null })); await refresh;
      expect(store.getSnapshot()).toMatchObject({ loadStatus: 'ready', freshness: 'fresh' });
      expect(render().executor).toMatch(/<button(?![^>]*disabled)[^>]*>Приостановить<\/button>/);
    }
  } finally { store.dispose(); }
});

test('B quiet polling: confirmed empty master, executor and panel lists stay visible', () => {
  for (const [render, emptyText] of [
    [renderMaster, 'Сейчас нет результатов на проверке.'],
    [renderExecutor, 'Назначенных нарядов нет'],
    [renderPanel, 'Доступных нарядов нет'],
  ] as const) {
    const current = ready([]); const before = render(current); const during = render(polling(current));
    expect(during).toContain(emptyText); expect(presentation(during)).toBe(presentation(before));
  }
});

test('B quiet polling: dictionary and history empty states retain their confirmed presentation', () => {
  const dictionaries = ready({ sections: [], equipment: [], brigades: [], executors: [] });
  const master = renderMaster(ready([]), { dictionaries: polling(dictionaries) });
  expect(presentation(master)).toBe(presentation(renderMaster(ready([]), { dictionaries })));
  actionDisabled(master, 'Выдать наряд');
  const executorDictionaries = ready({ workCodes: [], materials: [] });
  const executor = renderExecutor(ready([executorOrder]), { dictionaries: polling(executorDictionaries) });
  expect(presentation(executor)).toBe(presentation(renderExecutor(ready([executorOrder]), { dictionaries: executorDictionaries })));
  actionDisabled(executor, 'Отправить неполный результат на проверку');
  const employees = ready([]); const history = ready({ orderId: panelOrder.id, events: [] });
  const props = { selectedOrderId: panelOrder.id, employees, history, onRefreshHistory: noop };
  const panel = renderPanel(ready([panelOrder]), { ...props, employees: polling(employees), history: polling(history) });
  expect(presentation(panel)).toBe(presentation(renderPanel(ready([panelOrder]), props)));
  expect(panel).toContain('В загруженной истории событий нет.');
  expect(panel).toContain('В загруженном справочнике нет доступных исполнителей.');
  actionDisabled(panel, 'Обновить историю');
});

for (const [name, patch] of [
  ['initial null snapshot', { snapshot: null, lastConfirmedAt: null, freshness: 'never' }],
  ['snapshot without confirmation', { lastConfirmedAt: null }],
  ['never-confirmed freshness', { freshness: 'never' }],
  ['incomplete recovery', { incomplete: true }],
  ['retained error', { error: 'Синтетическая ошибка' }],
] as const) {
  test(`B quiet polling: ${name} is never quiet or confirmed empty`, () => {
    const resource: ResourceState<never[]> = { ...polling(ready([])), ...patch };
    const master = renderMaster(resource); const executor = renderExecutor(resource); const panel = renderPanel(resource);
    expect(master).toMatch(/(?:Обновляем|Загружаем) Наряды/);
    expect(executor).toContain('Наряды: загрузка'); expect(panel).toMatch(/Наряды: (?:обновляем|загружаем) данные/);
    expect(master).not.toContain('Сейчас нет результатов на проверке.');
    expect(executor).not.toContain('Назначенных нарядов нет'); expect(panel).not.toContain('Доступных нарядов нет');
    expect(executor).toContain('Список требует подтверждения');
    if (resource.incomplete || resource.freshness === 'stale') expect(panel).toContain('panel-notice--caution');
  });
}

for (const loadStatus of ['idle', 'error', 'offline', 'unavailable', 'ready'] as const) {
  test(`B quiet polling: ${loadStatus} stale snapshots retain warnings and command guards`, () => {
    const resource = { ...ready([executorOrder]), loadStatus, freshness: 'stale' as const };
    const executor = renderExecutor(resource);
    expect(executor).toContain('Список требует подтверждения');
    expect(executor).toContain('Действия станут доступны после получения актуального полного списка.');
    actionDisabled(executor, 'Приостановить');
    const master = renderMaster({ ...resource, snapshot: [masterOrder] });
    expect(master).not.toContain('Сейчас нет результатов на проверке.');
    const panel = renderPanel({ ...resource, snapshot: [panelOrder] });
    expect(panel).toContain('panel-notice--caution');
  });
}

test('B quiet polling: master offline and incomplete review details remain visible and disabled', () => {
  const retained = polling(ready([masterOrder]));
  const offline = renderMaster(retained, { online: false });
  expect(offline).toContain('Нет сети.'); expect(offline).toContain('Обновляем Наряды');
  expect(offline).not.toContain('Сейчас нет результатов на проверке.');
  actionDisabled(offline, 'Выдать наряд');
  const incomplete = renderMaster({ ...retained, snapshot: [{ ...masterOrder, status: 'ai_review' }], incomplete: true });
  expect(incomplete).toContain('Обновляем Наряды');
  expect(incomplete).toContain('Детали результата ещё не загружены. Решение недоступно.');
  actionDisabled(incomplete, 'Принять и закрыть'); actionDisabled(incomplete, 'Вернуть на доработку');
});

test('B quiet polling: valid review actions remain disabled and recommendation slot is preserved', () => {
  const review: MasterTypes.MasterOrderVM = { ...masterOrder, status: 'ai_review', submission: {
    id: 'synthetic-submission', assignmentRevision: 1, attemptNumber: 1, workDescription: 'Проверено',
    workCodeLabel: 'SYNTHETIC-CODE', materials: [], afterPhotoCount: 0, comment: '',
    completeness: 'complete', missingEvidence: [], assessment: null,
  } };
  const renderAssigneeRecommendations: MasterTypes.MasterScreenProps['renderAssigneeRecommendations'] = ({ draft, disabled }) =>
    createElement('button', { type: 'button', disabled }, `Синтетическая рекомендация: ${draft.description}`);
  const props = { renderAssigneeRecommendations, reviewDrafts: { [review.id]: { reason: 'Проверил результат', finalScore: '80' } } };
  const before = renderMaster(ready([review]), props); const during = renderMaster(polling(ready([review])), props);
  expect(presentation(during)).toBe(presentation(before));
  expect(during).toContain('Синтетическая рекомендация: Сохранённый черновик мастера');
  expect(during).toContain('Проверил результат');
  expect(before).toMatch(/<button(?![^>]*disabled)[^>]*>Принять и закрыть<\/button>/);
  actionDisabled(during, 'Принять и закрыть'); actionDisabled(during, 'Вернуть на доработку');
});

test('B quiet polling: observed newer command version keeps receipt copy stable but actions disabled', () => {
  const props: Partial<ExecutorScreenProps> = { mutation: { status: 'confirmed', error: null },
    pendingIntent: { orderId: executorOrder.id, expectedVersion: 2, action: 'start' } };
  const before = renderExecutor(ready([executorOrder]), props); const during = renderExecutor(polling(ready([executorOrder])), props);
  expect(during).toContain('Действие подтверждено сервером.'); expect(during).not.toContain(waitCopy);
  expect(presentation(during)).toBe(presentation(before)); actionDisabled(during, 'Приостановить');
});

test('B quiet polling: equal, older and missing post-command versions keep the wait notice', () => {
  const props: Partial<ExecutorScreenProps> = { mutation: { status: 'confirmed', error: null },
    pendingIntent: { orderId: executorOrder.id, expectedVersion: 3, action: 'start' } };
  for (const version of [2, 3]) {
    const resource = ready([{ ...executorOrder, version }]);
    for (const state of [resource, polling(resource)]) {
      const html = renderExecutor(state, props); expect(html).toContain(waitCopy); actionDisabled(html, 'Приостановить');
    }
  }
  const missing = renderExecutor(polling(ready([{ ...executorOrder, id: 'synthetic-other' }])), { ...props, selectedOrderId: 'synthetic-other' });
  expect(missing).toContain(waitCopy);
  const recovered = renderExecutor(ready([{ ...executorOrder, version: 4 }]), props);
  expect(recovered).not.toContain(waitCopy);
});

test('B quiet polling: errors and incomplete recovery cannot hide command version uncertainty', () => {
  const props: Partial<ExecutorScreenProps> = { mutation: { status: 'confirmed', error: null },
    pendingIntent: { orderId: executorOrder.id, expectedVersion: 2, action: 'start' } };
  for (const patch of [{ incomplete: true }, { error: 'Синтетическая ошибка' }, { loadStatus: 'offline' as const }, { lastConfirmedAt: null }]) {
    const html = renderExecutor({ ...polling(ready([executorOrder])), ...patch }, props);
    expect(html).toContain(waitCopy); actionDisabled(html, 'Приостановить');
  }
});

test('B quiet polling: changed statuses, overdue flags, list membership and history remain observable', () => {
  const changed = { ...executorOrder, version: 4, status: 'paused' as const, isOverdue: true };
  const html = renderExecutor(ready([changed]));
  expect(html).toContain('На паузе'); expect(html).toContain('Просрочен'); expect(html).not.toContain('Приостановить');
  expect(html).toContain('Продолжить работу');
  expect(renderMaster(ready([{ ...masterOrder, status: 'ai_review' }]))).not.toContain('Сейчас нет результатов на проверке.');
  const panel = renderPanel(ready([panelOrder]), { selectedOrderId: panelOrder.id, history: ready({ orderId: panelOrder.id, events: [{
    id: 'synthetic-event', sequence: 1, occurredAt: '2026-10-08T06:01:00Z', kind: 'order.created',
    actorLabel: 'Синтетический мастер', reason: null, fromStatus: null, toStatus: 'issued',
  }] }) });
  expect(panel).not.toContain('Доступных нарядов нет'); expect(panel).not.toContain('В загруженной истории событий нет.');
  expect(panel).toContain('Событие 1');
});
