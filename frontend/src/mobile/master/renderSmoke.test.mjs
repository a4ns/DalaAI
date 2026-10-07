// Synthetic React server rendering, with CSS ignored. NOT a browser/device or interaction test.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, extname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const lane = dirname(fileURLToPath(import.meta.url));
const frontend = process.env.MASTER_SHARED_FRONTEND || resolve(lane, '../../..');
const requireDependency = createRequire(resolve(frontend, 'package.json'));
const ts = requireDependency('typescript');
const React = requireDependency('react');
const { renderToStaticMarkup } = requireDependency('react-dom/server');
const cache = new Map();
function loadSource(path) {
  if (cache.has(path)) return cache.get(path).exports;
  const module = { exports: {} };
  cache.set(path, module);
  const output = ts.transpileModule(readFileSync(path, 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const localRequire = request => {
    if (request.endsWith('.css')) return {};
    if (request.startsWith('.')) return loadSource(resolve(dirname(path), `${request}${extname(request) ? '' : '.ts'}`));
    return requireDependency(request);
  };
  // Execute only this checkout's trusted TypeScript output; no fetched scripts or eval inputs.
  new Function('require', 'module', 'exports', output)(localRequire, module, module.exports);
  return module.exports;
}
const { MasterScreen } = loadSource(resolve(lane, 'MasterScreen.tsx'));
const ready = snapshot => ({ snapshot, freshness: 'fresh', loadStatus: 'ready', error: null, lastConfirmedAt: '2026-10-07T19:00:00Z', incomplete: false });
const order = { id: 'o1', number: 'SYNTHETIC-1', version: 4, assignmentRevision: 1, status: 'ai_review', type: 'unplanned', description: 'Синтетическая работа', equipmentLabel: 'Насос 1', executorLabel: 'Исполнитель 1', dueAt: '2026-10-07T22:00:00Z', isOverdue: false, submission: { id: 'sub1', assignmentRevision: 1, attemptNumber: 1, workDescription: 'Проверка насоса', workCodeLabel: 'Р-01', materials: [], afterPhotoCount: 1, comment: '', completeness: 'complete', missingEvidence: [], assessment: null } };
const props = {
  dictionaries: ready({ sections: [], equipment: [], brigades: [], executors: [] }), orders: ready([]),
  createDraft: { type: 'unplanned', description: '', sectionId: '', equipmentId: '', executorId: '', brigadeId: '', dueLocal: '', normMinutes: '', priority: 'normal', comment: '', beforePhotoIds: [] },
  onCreateDraftChange() {}, reviewDrafts: {}, onReviewDraftChange() {}, online: true,
  async onCreate() { throw new Error('Static render must not submit'); }, async onReview() { throw new Error('Static render must not submit'); }, async onReload() {},
};
const render = overrides => renderToStaticMarkup(React.createElement(MasterScreen, { ...props, ...overrides }));
const closeButton = html => html.match(/<button[^>]*>Принять и закрыть<\/button>/)?.[0];
test('confirmed empty list says there are no reviews', () => assert.match(render({}), /Сейчас нет результатов на проверке/));
test('loading initial resource never masquerades as empty', () => { const html = render({ orders: { ...ready(null), freshness: 'never', loadStatus: 'loading' } }); assert.match(html, /Загружаем/); assert.doesNotMatch(html, /Сейчас нет результатов на проверке/); });
test('offline snapshot never claims current empty list', () => { const html = render({ online: false }); assert.match(html, /Нет сети/); assert.doesNotMatch(html, /Сейчас нет результатов на проверке/); });
test('initial render never shows mutation success', () => assert.doesNotMatch(render({}), /подтверждена сервером|подтверждено сервером/));
test('null AI remains neutral and complete manual close remains available', () => { const html = render({ orders: ready([order]) }); assert.match(html, /Оценка ИИ пока отсутствует/); assert.match(html, /не подтверждение качества/); assert.ok(closeButton(html)); assert.doesNotMatch(closeButton(html), /disabled/); });
test('missing required after-photo disables close and leaves rework available', () => { const html = render({ orders: ready([{ ...order, submission: { ...order.submission, afterPhotoCount: 0 } }]) }); assert.match(closeButton(html), /disabled/); const rework = html.match(/<button[^>]*>Вернуть на доработку<\/button>/)?.[0]; assert.ok(rework); assert.doesNotMatch(rework, /disabled/); });
test('stale snapshot disables review mutations', () => { const html = render({ orders: { ...ready([order]), freshness: 'stale' } }); assert.match(closeButton(html), /disabled/); assert.match(html, /Данные устарели/); });
test('feature does not introduce a nested main landmark', () => { const html = render({}); assert.doesNotMatch(html, /<main/); assert.match(html, /<section[^>]*aria-labelledby=/); });
test('upload in progress disables create', () => { const html = render({ beforePhotosBusy: true }); assert.match(html, /Дождитесь завершения загрузки/); assert.match(html.match(/<button[^>]*>Выдать наряд<\/button>/)?.[0] || '', /disabled/); });
