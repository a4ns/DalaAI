import { expect, test } from '@playwright/test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { ssrSourceModule } from '../support/ssr-source';
import { clock } from '../support/demo-clock';
import type * as View from '../../src/features/demoClock/DemoClockView';
import type * as Screen from '../../src/features/demoClock/DemoClockScreen';
import type { DemoClockState } from '../../src/features/demoClock/controller';
const view = ssrSourceModule<typeof View>('src/features/demoClock/DemoClockView.tsx');
const { parseClockInteger } = ssrSourceModule<typeof Screen>('src/features/demoClock/DemoClockScreen.tsx', { './DemoClockView': view, './demoClock.css': {} });
function state(patch: Partial<DemoClockState> = {}): DemoClockState { return { snapshot: null, readStatus: 'idle', readError: null, operation: 'idle', operationError: null, canResolveConflict: false, ...patch }; }
function render(value: DemoClockState): string {
  const props: View.DemoClockViewProps = { state: value, scale: '1', seconds: '60', onScale() {}, onSeconds() {}, onRefresh() {}, onPause() {}, onResume() {}, onSetScale() {}, onAdvance() {}, onResolve() {}, inputError: null };
  return renderToStaticMarkup(createElement(view.DemoClockView, props));
}

test('unconfirmed or unavailable clock capability renders no invented time or mutation controls', () => {
  for (const data of [state(), state({ readStatus: 'unavailable', readError: 'Synthetic access denial' })]) {
    const html = render(data);
    expect(html).not.toContain('Бизнес-время снимка:');
    expect(html).not.toContain('Пауза (0×)'); expect(html).not.toContain('Изменить скорость');
    expect(html).not.toContain('<input');
  }
  expect(render(state())).toContain('Возможность управления пока не подтверждена сервером');
});

test('business snapshot and real response time are distinct and never advance from the device clock', () => {
  const snapshot = state({ snapshot: clock(), readStatus: 'ready' }); const before = render(snapshot);
  const originalNow = Date.now;
  try { Date.now = () => originalNow() + 3600000; expect(render(snapshot)).toBe(before); } finally { Date.now = originalNow; }
  expect(before).toContain('Бизнес-время снимка: 2026-10-09 05:00:00 UTC+5');
  expect(before).toContain('Реальное время этого ответа: 2026-10-08 05:00:00 UTC+5');
  expect(before).toContain('Реальное время авторизации, сессий, хранения фото, таймаутов и бюджетов провайдера не меняется');
  expect(before).toContain('Часы в интерфейсе не продвигаются по времени устройства');
  expect(before).not.toMatch(/<button[^>]*>[^<]*(Сброс|Удалить|Вернуть время)/);
});

test('unknown outcome keeps mutation controls disabled while a fresh GET remains an explicit option', () => {
  const html = render(state({ snapshot: clock({ version: 9, scale: 60 }), readStatus: 'ready', operation: 'unknown', operationError: 'Исход отправленного действия неизвестен.' }));
  const buttons = [...html.matchAll(/<button\b([^>]*)>([^<]*)<\/button>/g)];
  expect(buttons.find(button => button[2] === 'Обновить показание сервера')?.[1]).not.toContain('disabled');
  for (const name of ['Пауза (0×)', 'Продолжить (1×)', 'Изменить скорость', 'Продвинуть бизнес-время вперёд']) expect(buttons.find(button => button[2] === name)?.[1]).toContain('disabled');
  expect(html).toContain('не докажет исход прежнего действия');
  expect(html).not.toContain('Ответ на исходное действие подтверждён');
  expect(html).not.toContain('Проверил обновлённое состояние — разрешить новое действие');
});

test('numeric fields reject empty, fractional, negative and out-of-bound values; pause is an explicit separate action', () => {
  for (const value of ['', ' ', '-1', '0.5', '1e1', '61']) expect(() => parseClockInteger(value, 1, 60)).toThrow();
  expect(parseClockInteger('1', 1, 60)).toBe(1); expect(parseClockInteger('60', 1, 60)).toBe(60);
  expect(parseClockInteger('3600', 1, 3600)).toBe(3600); expect(() => parseClockInteger('3601', 1, 3600)).toThrow();
  const paused = render(state({ snapshot: clock({ scale: 0 }), readStatus: 'ready' }));
  expect(paused).toContain('Продолжить (1×)'); expect(paused).toContain('(пауза)');
});
