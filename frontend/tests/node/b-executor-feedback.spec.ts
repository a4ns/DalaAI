import { expect, test } from '@playwright/test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { sourceModule } from '../support/source';
import { ssrSourceModule } from '../support/ssr-source';
import type * as Screen from '../../src/mobile/executor/ExecutorScreen';
import type * as Model from '../../src/mobile/executor/model';
import type { ExecutorOrderViewModel, ExecutorScreenProps } from '../../src/mobile/executor/types';
import type { ResourceState } from '../../src/shared/ui/types';

// Synthetic static rendering only: no layout, scrolling, screen-reader or API claim.
const model = sourceModule<typeof Model>('src/mobile/executor/model.ts');
const { ExecutorScreen } = ssrSourceModule<typeof Screen>('src/mobile/executor/ExecutorScreen.tsx', {
  './model': model, './executor.css': {},
});
const ready = <T,>(snapshot: T): ResourceState<T> => ({
  snapshot, freshness: 'fresh', loadStatus: 'ready', error: null,
  lastConfirmedAt: '2026-10-08T04:00:00Z', incomplete: false,
});
const orders: ExecutorOrderViewModel[] = Array.from({ length: 30 }, (_, index) => ({
  id: `synthetic-order-${index}`, number: `SYNTHETIC-${index}`, version: 3, assignmentRevision: 1,
  sectionId: 'synthetic-section', sectionLabel: 'Синтетический участок', equipmentLabel: 'Тестовый насос',
  status: 'in_progress', type: 'unplanned', priority: 'normal', description: 'Тестовая работа',
  comment: '', dueAt: '2026-10-08T10:00:00Z', isOverdue: false,
}));
function props(patch: Partial<ExecutorScreenProps> = {}): ExecutorScreenProps {
  return {
    sessionKey: 'synthetic-feedback-session', operationScopeKey: 'synthetic-order-29:1',
    orders: ready(orders), dictionaries: ready({ workCodes: [], materials: [] }),
    selectedOrderId: orders[29].id, drafts: {}, mutation: { status: 'idle', error: null }, pendingIntent: null,
    onSelectOrder() {}, onDraftChange() {}, onRefresh() {}, onResolveConflict() {},
    onIntent: async () => ({ kind: 'confirmed' }), onRetry: async () => ({ kind: 'confirmed' }), ...patch,
  };
}
const render = (patch: Partial<ExecutorScreenProps> = {}) => renderToStaticMarkup(createElement(ExecutorScreen, props(patch)));
const detail = (html: string) => html.match(/<article class="executor-detail"[^>]*>([\s\S]*?)<\/article>/)?.[1] ?? '';
const liveRegions = (html: string) => html.match(/<[^>]+(?:role="(?:status|alert)"|aria-live="(?:polite|assertive)")[^>]*>/g) ?? [];
const emptyStatus = '<p role="status" aria-live="polite" aria-atomic="true"></p>';

for (const [status, message] of [
  ['pending', 'Отправляем действие.'], ['unknown_result', 'Результат не подтверждён'],
  ['conflict', 'Наряд изменился'], ['failed', 'Действие отклонено.'],
  ['confirmed', 'Действие подтверждено сервером.'],
] as const) {
  test(`B executor feedback: ${status} appears once inside the selected detail after a long list`, () => {
    const html = render({ mutation: { status, error: null },
      pendingIntent: { orderId: orders[29].id, expectedVersion: 3, action: 'submit' } });
    const selected = detail(html);
    expect(html.match(/class="executor-order-card/g)).toHaveLength(30);
    expect(selected).toContain(message);
    expect(html.split(message)).toHaveLength(2);
    expect(html.match(/class="executor-operation"/g)).toHaveLength(1);
    expect(selected.indexOf('executor-operation')).toBeGreaterThan(selected.indexOf('</header>'));
    expect(selected.indexOf('executor-operation')).toBeLessThan(selected.indexOf('class="executor-actions"'));
    expect(liveRegions(html)).toHaveLength(status === 'pending' || status === 'confirmed' ? 1 : 2);
    if (status !== 'pending' && status !== 'confirmed') expect(selected).toContain(emptyStatus);
  });
}

test('B executor feedback: legacy unknown result remains globally available without a selected detail', () => {
  for (const selectedOrderId of [null, 'synthetic-missing-order']) {
    const html = render({ operationScopeKey: undefined, selectedOrderId, mutation: { status: 'unknown_result', error: 'Ответ потерян' } });
    expect(detail(html)).toBe('');
    expect(html).toContain('Повторить исходное действие');
    expect(html.match(/class="executor-operation"/g)).toHaveLength(1);
    expect(html.indexOf('executor-operation')).toBeLessThan(html.indexOf('executor-order-list'));
    expect(liveRegions(html)).toHaveLength(2);
    expect(html).toContain(emptyStatus);
  }
});

test('B executor feedback: inaccessible scoped operation reveals only the generic global quarantine notice', () => {
  for (const selectedOrderId of [null, 'synthetic-missing-order']) {
    const html = render({ selectedOrderId, quarantinedIntentCount: 1,
      mutation: { status: 'unknown_result', error: 'PRIVATE_SYNTHETIC_ERROR' },
      pendingIntent: { orderId: 'synthetic-missing-order', expectedVersion: 3, action: 'submit' } });
    expect(html).toContain('Исходная попытка сохранена отдельно');
    expect(html).not.toContain('PRIVATE_SYNTHETIC_ERROR');
    expect(html).not.toContain('executor-operation');
    expect(html).not.toContain('Повторить исходное действие');
    expect(liveRegions(html)).toHaveLength(1);
  }
});

test('B executor feedback: an intent for a different or removed order is never placed inside the new selection', () => {
  for (const operationScopeKey of [undefined, 'synthetic-original-scope']) {
    for (const orderId of [orders[0].id, 'synthetic-missing-order']) {
      const html = render({ operationScopeKey, mutation: { status: 'pending', error: null },
        pendingIntent: { orderId, expectedVersion: 3, action: 'submit' } });
      expect(detail(html)).not.toContain('executor-operation');
      expect(html).toContain('Отправляем действие.');
      expect(html.match(/class="executor-operation"/g)).toHaveLength(1);
      expect(html.indexOf('executor-operation')).toBeLessThan(html.indexOf('executor-order-list'));
      expect(liveRegions(html)).toHaveLength(1);
    }
  }
});

test('B executor feedback: local retry keeps the offline guard and conflict keeps explicit review controls', () => {
  const offline = detail(render({ orders: { ...ready(orders), loadStatus: 'offline', freshness: 'stale' },
    mutation: { status: 'unknown_result', error: 'Ответ потерян' } }));
  expect(offline).toMatch(/<button[^>]*disabled=""[^>]*>Повторить исходное действие<\/button>/);
  const conflict = detail(render({ mutation: { status: 'conflict', error: 'Тестовый конфликт' } }));
  expect(conflict).toContain('Загрузить актуальное состояние');
  expect(conflict).toMatch(/<button[^>]*disabled=""[^>]*>Состояние проверено, продолжить<\/button>/);
});

test('B executor feedback: idle keeps an empty persistent status region without a retry action', () => {
  const html = render();
  expect(liveRegions(html)).toHaveLength(1);
  expect(detail(html)).toContain(emptyStatus);
  expect(html).not.toContain('Повторить исходное действие');
});

test('B executor feedback: existing unqualified alert selectors remain unique for unknown outcome and stale-list failure', () => {
  const unknown = render({ mutation: { status: 'unknown_result', error: 'Ответ потерян' } });
  expect(unknown.match(/role="alert"/g)).toHaveLength(1);
  expect(unknown).toContain('Результат не подтверждён');
  const stale = render({ orders: { ...ready(orders), freshness: 'stale', loadStatus: 'error', error: 'Синтетический отказ загрузки' } });
  expect(stale.match(/role="alert"/g)).toHaveLength(1);
  expect(stale).toContain('Синтетический отказ загрузки');
  expect(detail(stale)).toContain(emptyStatus);
});
