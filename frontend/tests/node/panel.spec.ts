import { expect, test } from '@playwright/test';
import { sourceModule } from '../support/source';
import type * as Model from '../../src/panel/model';
import type { PanelEvent, PanelOrder } from '../../src/panel/types';
const model = sourceModule<typeof Model>('src/panel/model.ts');

test('panel: zero queued orders and no representative active order does not prove free', () => {
  expect(model.employeeActivityLabel({ id: 'synthetic', label: 'Тест', onShift: true, activeOrderId: null, queueCount: 0 })).toBe('Занятость не подтверждена');
  expect(model.employeeActivityLabel({ id: 'synthetic', label: 'Тест', onShift: false, activeOrderId: 'order', queueCount: 5 })).toBe('Вне смены');
});

test('panel: history ordering uses sequence even if timestamps disagree and IDs repeat', () => {
  const event = (id: string, sequence: number, occurredAt: string): PanelEvent => ({ id, sequence, occurredAt, kind: 'order.created', actorLabel: 'Тест', reason: null, fromStatus: null, toStatus: 'issued' });
  const sorted = model.sortedPanelEvents([event('late', 1, '2099-01-01T00:00:00Z'), event('early', 8, '2020-01-01T00:00:00Z'), event('early', 8, '2020-01-01T00:00:00Z')]);
  expect(sorted.map(value => value.id)).toEqual(['early', 'late']);
});

test('panel: current server overdue flag is independent of workflow status', () => {
  const base: PanelOrder = { id: 's', number: 'TEST', title: 'Тест', sectionLabel: 'Участок', equipmentLabel: 'Насос', executorLabel: 'Код', status: 'accepted', priority: 'normal', dueAt: '2026-10-08T04:00:00Z', isOverdue: true, version: 1 };
  expect(model.filterPanelOrders([base, { ...base, id: 'other', status: 'closed', isOverdue: false }], '', 'all', true).map(order => order.id)).toEqual(['s']);
  expect(model.filterPanelOrders([base], 'насос', 'accepted', false)).toHaveLength(1);
});

test('panel: absent or ambiguous timestamps are not rendered as authoritative clock time', () => {
  for (const value of [null, '', '2026-10-08T00:00:00', 'invalid']) expect(model.formatPanelTime(value)).toBe('Время не указано');
  expect(model.formatPanelTime('2026-10-07T19:00:00Z')).toContain('08.10.2026');
  expect(model.formatPanelTime('2026-10-07T19:00:00Z')).toContain('00:00 (UTC+5)');
});
