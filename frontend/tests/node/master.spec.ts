import { expect, test } from '@playwright/test';
import { sourceModule } from '../support/source';
import type * as Model from '../../src/mobile/master/masterModel';
import type * as Types from '../../src/mobile/master/types';
const model = sourceModule<typeof Model>('src/mobile/master/masterModel.ts');

test('master: UTC+5 deadlines reject impossible calendar dates instead of normalizing them', () => {
  expect(model.dueLocalToIso('2026-10-08T00:00')).toBe('2026-10-07T19:00:00.000Z');
  for (const value of ['2026-02-30T12:00', '2026-13-01T12:00', '2026-10-08T24:00', '2026-10-08T00:00Z', '']) expect(model.dueLocalToIso(value), value).toBeNull();
});

test('master: missing evidence or old assignment blocks close despite high assessment score', () => {
  const order: Types.MasterOrderVM = { id: 'test', number: 'TEST', version: 2, assignmentRevision: 2, status: 'ai_review', type: 'unplanned', description: 'Тест', equipmentLabel: 'Тест', executorLabel: 'Тест', dueAt: '2026-10-08T04:00:00Z', isOverdue: false, submission: {
    id: 'submission', assignmentRevision: 1, attemptNumber: 1, workDescription: 'Работа выполнена', workCodeLabel: 'TEST', materials: [], afterPhotoCount: 0, comment: '', completeness: 'incomplete', missingEvidence: [], assessment: { mode: 'rules_fallback', recommendation: 'satisfactory', score: 100, reasons: [], stale: false, fallbackReason: 'Synthetic' },
  } };
  const blockers = model.closeBlockers(order);
  expect(blockers.some(text => text.includes('предыдущему назначению'))).toBe(true);
  expect(blockers.some(text => text.includes('неполный'))).toBe(true);
  expect(blockers.some(text => text.includes('фото'))).toBe(true);
});

test('master: undefined, malformed and arbitrary adapter outcomes cannot become confirmation', () => {
  for (const outcome of [undefined, null, true, {}, { ok: true }, { kind: 'success' }]) expect(model.normalizeOutcome(outcome).kind).toBe('unknown');
  expect(model.normalizeOutcome({ kind: 'confirmed' }).kind).toBe('confirmed');
});

test('master: incomplete workload information must not label an executor free', () => {
  expect(model.executorLoad({ id: 'test', label: 'Тест', sectionIds: ['section'], brigadeId: null, onShift: true, activeOrderId: null, queueCount: 0 })).not.toContain('Свободен');
});
