import { expect, test } from '@playwright/test';
import { sourceModule } from '../support/source';
import type * as Model from '../../src/mobile/executor/model';
import type { ResourceState } from '../../src/shared/ui/types';

const model = sourceModule<typeof Model>('src/mobile/executor/model.ts');

test('executor: confirmed empty requires all four confirmation conditions', () => {
  const states: ResourceState<unknown[]>['loadStatus'][] = ['idle', 'loading', 'ready', 'error', 'offline', 'unavailable'];
  for (const loadStatus of states) for (const freshness of ['never', 'fresh', 'stale'] as const) for (const incomplete of [false, true]) {
    const state: ResourceState<unknown[]> = { snapshot: [], freshness, loadStatus, incomplete, error: null, lastConfirmedAt: '2026-10-07T19:00:00Z' };
    expect(model.isConfirmedEmpty(state), JSON.stringify(state)).toBe(loadStatus === 'ready' && freshness === 'fresh' && !incomplete);
  }
});

test('executor: mutation payload cannot follow changes to the original draft', () => {
  const draft = { ...model.emptyExecutorDraft(), workDescription: '  Проверено  ', afterPhotoIds: ['confirmed-photo'], materials: [{ rowId: 'r', materialId: 'm', quantity: '2,125' }] };
  const payload = model.toSubmitPayload(draft);
  draft.afterPhotoIds.push('later-photo'); draft.materials[0].quantity = '900'; draft.workDescription = 'Изменено';
  expect(payload).toMatchObject({ workDescription: 'Проверено', afterPhotoIds: ['confirmed-photo'], materials: [{ materialId: 'm', quantity: 2.125 }] });
  expect(payload.materials[0]).not.toHaveProperty('rowId');
});

test('executor: arbitrary format, exponent, invalid bounds and excessive precision are rejected', () => {
  for (const value of ['-0.1', '+1', '1e2', '0x10', 'Infinity', 'NaN', '1.2345', '999999999.001', '0', ' ', '1_000', '1,2.3']) expect(model.parseQuantity(value), value).toBeNull();
  expect(model.parseQuantity('0,001')).toBe(0.001);
});

test('executor: incomplete evidence is reviewable but is never labelled complete', () => {
  const draft = { ...model.emptyExecutorDraft(), workDescription: 'Синтетический корректный результат' };
  expect(model.validateExecutorDraft(draft, { workCodes: [], materials: [] })).toEqual({});
  expect(model.incompleteEvidence({ type: 'unplanned' }, draft)).toEqual(['шифр работ', 'фото после выполнения']);
  expect(model.incompleteEvidence({ type: 'planned' }, draft)).toEqual(['шифр работ']);
});

test('executor: terminal and review states do not advertise write actions', () => {
  for (const status of ['done', 'ai_review', 'closed', 'cancelled', 'rejected'] as const) expect(model.allowedActions(status)).toEqual([]);
  expect(model.allowedActions('paused')).toEqual(['resume']);
  expect(model.allowedActions('rework')).toEqual(['start']);
});

test('executor: duplicate or unconfirmed photo IDs cannot masquerade as submitted evidence', () => {
  for (const afterPhotoIds of [['same', 'same'], [''], [' '], ['1', '2', '3', '4', '5', '6']]) {
    const draft = { ...model.emptyExecutorDraft(), workDescription: 'Проверено', afterPhotoIds };
    expect(model.validateExecutorDraft(draft, { workCodes: [], materials: [] }).photos).toBeTruthy();
  }
});
