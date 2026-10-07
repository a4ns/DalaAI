// Synthetic view-model tests. No backend, HTTP, browser or physical device is exercised.
import test from 'node:test';
import assert from 'node:assert/strict';
import { canApplyPhotoResult, closeBlockers, dueLocalToIso, executorLoad, normalizeOutcome, resourceIsCurrent, reviewErrors, validateCreate } from './masterModel.ts';
const dictionaries = {
  sections: [{ id: 's1', label: 'Участок 1' }], equipment: [{ id: 'eq1', label: 'Насос', sectionId: 's1' }],
  brigades: [{ id: 'b1', label: 'Бригада 1' }],
  executors: [{ id: 'e1', label: 'Исполнитель 1', sectionIds: ['s1'], brigadeId: 'b1', onShift: true, activeOrderId: null, queueCount: 0 }],
};
const draft = { type: 'unplanned', description: 'Осмотреть насос', sectionId: 's1', equipmentId: 'eq1', executorId: 'e1', brigadeId: '', dueLocal: '2026-10-08T02:00', normMinutes: '60', priority: 'normal', comment: '', beforePhotoIds: [] };
const order = { id: 'o1', number: 'TEST-1', version: 4, assignmentRevision: 1, status: 'ai_review', type: 'unplanned', description: 'Насос', equipmentLabel: 'Насос 1', executorLabel: 'Исполнитель 1', dueAt: '2026-10-07T21:00:00Z', isOverdue: false, submission: { id: 'sub1', assignmentRevision: 1, attemptNumber: 1, workDescription: 'Замена уплотнения', workCodeLabel: 'Р-01', materials: [], afterPhotoCount: 1, comment: '', completeness: 'complete', missingEvidence: [], assessment: null } };
const resource = { snapshot: [], freshness: 'fresh', loadStatus: 'ready', error: null, lastConfirmedAt: '2026-10-07T19:00:00Z', incomplete: false };
test('UTC+5 date conversion is independent of device timezone', () => assert.equal(dueLocalToIso('2026-10-08T02:00'), '2026-10-07T21:00:00.000Z'));
for (const value of ['2026-02-30T01:00', '2026-13-01T01:00', '2026-10-08T25:00', '2026-10-08', 'invalid', '']) test(`invalid wall time rejected: ${value}`, () => assert.equal(dueLocalToIso(value), null));
test('valid synthetic draft accepted without photo before', () => assert.deepEqual(validateCreate(draft, dictionaries, '2026-10-07T20:00:00Z'), {}));
test('deadline equal to domain now rejected; draft unchanged', () => { const before = structuredClone(draft); assert.ok(validateCreate(draft, dictionaries, '2026-10-07T21:00:00Z').dueLocal); assert.deepEqual(draft, before); });
test('unknown server domain time is not substituted by client now', () => assert.equal(validateCreate(draft, dictionaries).dueLocal, undefined));
test('blank description rejected', () => assert.ok(validateCreate({ ...draft, description: '  ' }, dictionaries).description));
test('foreign equipment rejected', () => assert.ok(validateCreate({ ...draft, equipmentId: 'eq-other' }, dictionaries).equipmentId));
test('brigade requires responsible member', () => assert.ok(validateCreate({ ...draft, brigadeId: 'b-other' }, dictionaries).brigadeId));
test('off-shift assignment rejected', () => assert.ok(validateCreate(draft, { ...dictionaries, executors: [{ ...dictionaries.executors[0], onShift: false }] }).executorId));
for (const normMinutes of ['0', '-1', '1.5', '525601', '', 'NaN']) test(`invalid norm rejected: ${normMinutes}`, () => assert.ok(validateCreate({ ...draft, normMinutes }, dictionaries).normMinutes));
test('duplicate before-photo IDs rejected', () => assert.ok(validateCreate({ ...draft, beforePhotoIds: ['p1', 'p1'] }, dictionaries).beforePhotoIds));
test('null AI does not block complete manual review', () => assert.deepEqual(closeBlockers(order), []));
test('high AI score does not bypass required after-photo', () => assert.ok(closeBlockers({ ...order, submission: { ...order.submission, afterPhotoCount: 0, assessment: { score: 100 } } }).length));
test('incomplete server result blocks closing despite locally present evidence', () => assert.ok(closeBlockers({ ...order, submission: { ...order.submission, completeness: 'incomplete' } }).length));
test('unknown evidence completeness blocks closing', () => assert.ok(closeBlockers({ ...order, submission: { ...order.submission, completeness: 'unknown' } }).length));
test('missing work code blocks planned closing too', () => assert.ok(closeBlockers({ ...order, type: 'planned', submission: { ...order.submission, workCodeLabel: null } }).length));
test('planned work does not require an after-photo', () => assert.deepEqual(closeBlockers({ ...order, type: 'planned', submission: { ...order.submission, afterPhotoCount: 0 } }), []));
test('old assignment result cannot be closed', () => assert.ok(closeBlockers({ ...order, assignmentRevision: 2 }).length));
test('missing details is unknown rather than complete', () => assert.ok(closeBlockers({ ...order, submission: null }).length));
test('mandatory reason applies even with score 100', () => assert.ok(reviewErrors({ reason: ' ', finalScore: '100' }).length));
test('empty score allowed and never changed to zero', () => assert.deepEqual(reviewErrors({ reason: 'Проверено мастером', finalScore: '' }), []));
for (const finalScore of ['-1', '101', '2.5', 'NaN']) test(`invalid score rejected: ${finalScore}`, () => assert.ok(reviewErrors({ reason: 'Проверено', finalScore }).length));
test('resolved undefined callback never means success', () => assert.equal(normalizeOutcome(undefined).kind, 'unknown'));
test('explicit confirmed result only enables success', () => assert.equal(normalizeOutcome({ kind: 'confirmed' }).kind, 'confirmed'));
for (const kind of ['rejected', 'conflict', 'unknown']) test(`${kind} callback result preserved`, () => assert.equal(normalizeOutcome({ kind, message: 'Синтетический исход' }).kind, kind));
test('fresh empty snapshot distinguishable from not-loaded', () => { assert.equal(resourceIsCurrent(resource), true); assert.equal(resourceIsCurrent({ ...resource, snapshot: null }), false); });
for (const patch of [{ freshness: 'stale' }, { incomplete: true }, { loadStatus: 'loading' }, { loadStatus: 'error' }, { loadStatus: 'offline' }]) test(`noncurrent resource blocks writes: ${JSON.stringify(patch)}`, () => assert.equal(resourceIsCurrent({ ...resource, ...patch }), false));
test('empty representative workload never declares executor free', () => assert.equal(executorLoad(dictionaries.executors[0]), 'Занятость не подтверждена'));
test('workload off-shift has priority and queue is retained', () => assert.equal(executorLoad({ ...dictionaries.executors[0], onShift: false, activeOrderId: 'other', queueCount: 2 }), 'Не на смене · в очереди: 2'));

const photoContext = { mounted: true, locked: false, expectedGeneration: 1, currentGeneration: 1, expectedSection: 's1', currentSection: 's1' };
test('current photo callback may update latest draft', () => assert.equal(canApplyPhotoResult(photoContext), true));
for (const patch of [{ mounted: false }, { locked: true }, { currentGeneration: 2 }, { currentSection: 's2' }]) test(`late photo callback ignored: ${JSON.stringify(patch)}`, () => assert.equal(canApplyPhotoResult({ ...photoContext, ...patch }), false));
