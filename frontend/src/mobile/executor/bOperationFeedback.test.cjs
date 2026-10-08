/* B-only synthetic hook/event tests; no browser, layout, scrolling or assistive-technology evidence.
 * Run: node --test src/mobile/executor/bOperationFeedback.test.cjs
 * Isolated checkout: EXECUTOR_DEPENDENCY_ROOT=/path/to/frontend node --test ...
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const dependencyRoot = process.env.EXECUTOR_DEPENDENCY_ROOT || path.resolve(__dirname, '../../..');
const dep = createRequire(path.join(dependencyRoot, 'package.json'));
const ts = dep('typescript');
const React = dep('react');

function loader(react = React) {
  const cache = new Map();
  function load(file) {
    if (cache.has(file)) return cache.get(file).exports;
    const module = { exports: {} };
    cache.set(file, module);
    const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: {
      target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
    } }).outputText;
    const scopedRequire = (name) => {
      if (name === 'react') return react;
      if (name.endsWith('.css')) return {};
      if (name.startsWith('.')) {
        const base = path.resolve(path.dirname(file), name);
        return load(fs.existsSync(`${base}.ts`) ? `${base}.ts` : `${base}.tsx`);
      }
      return dep(name);
    };
    new Function('require', 'module', 'exports', code)(scopedRequire, module, module.exports);
    return module.exports;
  }
  return (name) => load(path.join(__dirname, name));
}
const load = loader();
const model = load('model.ts');
const ready = (snapshot) => ({ snapshot, freshness: 'fresh', loadStatus: 'ready', error: null, lastConfirmedAt: '2026-10-07T19:00:00Z', incomplete: false });
const order = (status = 'issued', other = {}) => ({ id: 'order-1', number: 'Н-001', version: 3, assignmentRevision: 1, sectionId: 'section-1', equipmentLabel: 'Насос Н-1', sectionLabel: 'Участок 1', status, type: 'unplanned', priority: 'normal', description: 'Устранить течь', comment: '', dueAt: '2026-10-08T03:00:00Z', isOverdue: false, ...other });
const dictionaries = { workCodes: [{ id: 'code-1', code: '01', label: 'Замена уплотнения' }], materials: [{ id: 'material-1', code: 'M01', label: 'Прокладка', unit: 'шт.' }] };
function props(overrides = {}) {
  return { sessionKey: 'synthetic-executor-session-1', orders: ready([order()]), dictionaries: ready(dictionaries), selectedOrderId: 'order-1', drafts: {}, mutation: { status: 'idle', error: null }, pendingIntent: null, onSelectOrder() {}, onDraftChange() {}, onRefresh() {}, onResolveConflict() {}, onIntent: async () => ({ kind: 'confirmed' }), onRetry: async () => ({ kind: 'confirmed' }), ...overrides };
}

/** Minimal hook simulator for event-boundary assertions, explicitly not a DOM/browser test. */
function harness(initialProps) {
  const slots = []; const focusEvents = []; let cursor = 0; let pendingEffects = []; let currentProps = initialProps;
  const hookRuntime = {
    useId: () => ':test:',
    useState(initial) { const index = cursor++; if (!(index in slots)) slots[index] = typeof initial === 'function' ? initial() : initial; return [slots[index], (value) => { slots[index] = typeof value === 'function' ? value(slots[index]) : value; }]; },
    useRef(initial) { const index = cursor++; if (!(index in slots)) slots[index] = { current: initial }; return slots[index]; },
    useEffect(effect, dependencies) { const index = cursor++; const previous = slots[index]; if (!previous || dependencies.some((item, offset) => item !== previous.dependencies[offset])) { pendingEffects.push(() => { previous?.cleanup?.(); slots[index] = { dependencies, cleanup: effect() }; }); } },
  };
  hookRuntime.useLayoutEffect = hookRuntime.useEffect;
  const Component = loader(hookRuntime)('ExecutorScreen.tsx').ExecutorScreen;
  let tree;
  function render(next = currentProps) { if (next.sessionKey !== currentProps.sessionKey) { for (const slot of slots) slot?.cleanup?.(); slots.length = 0; } currentProps = next; cursor = 0; pendingEffects = []; const wrapper = Component(currentProps); tree = wrapper.type(wrapper.props); elements(tree).forEach((node) => {
    if (node.props?.ref && typeof node.props.ref === 'object') node.props.ref.current = {
      focus: (options) => focusEvents.push({ kind: 'focus', className: node.props.className, options }),
      scrollIntoView: (options) => focusEvents.push({ kind: 'scroll', className: node.props.className, options }),
    };
  }); pendingEffects.forEach((effect) => effect()); return tree; }
  function elements(node, result = []) { if (node && typeof node === 'object' && typeof node.type === 'function') return elements(node.type(node.props), result); if (!node || typeof node !== 'object') return result; if (Array.isArray(node)) { node.forEach((item) => elements(item, result)); return result; } result.push(node); elements(node.props?.children, result); return result; }
  function text(node) { if (node === null || node === undefined || typeof node === 'boolean') return ''; if (typeof node === 'string' || typeof node === 'number') return String(node); if (Array.isArray(node)) return node.map(text).join(''); return text(node.props?.children); }
  render();
  return { render, focusEvents, element: (predicate) => elements(tree).find(predicate), button: (label) => elements(tree).find((node) => node.type === 'button' && text(node) === label), form: () => elements(tree).find((node) => node.type === 'form'), unmount() { for (const slot of slots) slot?.cleanup?.(); }, text: () => text(tree) };
}
const settle = () => new Promise((resolve) => setImmediate(resolve));
const pending = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const feedbackProps = (overrides = {}) => props({
  operationScopeKey: 'synthetic-order-1-assignment-1', orders: ready([order('in_progress'), order('in_progress', { id: 'order-2', number: 'Н-002' })]),
  drafts: { 'order-1': { ...model.emptyExecutorDraft(), workDescription: 'Синтетический результат' } }, ...overrides,
});
const submit = h => h.form().props.onSubmit({ preventDefault() {} });
const operationScroll = { kind: 'scroll', className: 'executor-operation', options: { block: 'start', inline: 'nearest' } };

test('B feedback: explicit valid submit and exact-intent retry each scroll once without taking focus', async () => {
  const response = pending(); const intents = []; let retries = 0;
  const base = feedbackProps({ onIntent: intent => { intents.push(intent); return response.promise; }, onRetry: async () => { retries++; return { kind: 'confirmed' }; } });
  const h = harness(base); submit(h); submit(h);
  assert.equal(intents.length, 1); assert.deepEqual(h.focusEvents, []);
  h.render(); assert.deepEqual(h.focusEvents, [operationScroll]);
  response.resolve({ kind: 'unknown', message: 'Ответ потерян' }); await settle(); h.render();
  assert.deepEqual(h.focusEvents, [operationScroll], 'asynchronous outcome never steals scroll or focus');
  assert.equal(h.element(node => node.type === 'textarea' && node.props.value === 'Синтетический результат').props.disabled, true);
  const retry = h.button('Повторить исходное действие').props.onClick; retry(); retry();
  await settle(); h.render();
  assert.equal(retries, 1); assert.equal(intents.length, 1);
  assert.deepEqual(h.focusEvents, [operationScroll, operationScroll]);
  assert.equal(base.drafts['order-1'].workDescription, 'Синтетический результат');
});

test('B feedback: initial render, polls, parent-only mutation changes and ordinary draft edits never scroll', () => {
  const base = feedbackProps(); const h = harness(base);
  for (const status of ['pending', 'confirmed', 'unknown_result', 'conflict', 'failed', 'idle']) {
    h.render({ ...base, mutation: { status, error: null } });
  }
  h.render({ ...base, orders: { ...base.orders, lastConfirmedAt: '2026-10-08T05:00:00Z' } });
  h.render({ ...base, drafts: { 'order-1': { ...base.drafts['order-1'], comment: 'Обычная правка' } } });
  assert.deepEqual(h.focusEvents, []);
});

test('B feedback: invalid result validation does not request operation scrolling', () => {
  let calls = 0; const h = harness(feedbackProps({ drafts: {}, onIntent: async () => { calls++; return { kind: 'confirmed' }; } }));
  submit(h); h.render();
  assert.equal(calls, 0); assert.deepEqual(h.focusEvents, []);
  assert.match(h.text(), /Проверьте форму/);
});

test('B feedback: changed selection consumes the request and an A to B to A round trip cannot revive it', async () => {
  for (const scoped of [true, false]) {
    const response = pending();
    const base = feedbackProps({ operationScopeKey: scoped ? 'scope-A' : undefined, onIntent: () => response.promise });
    const h = harness(base); submit(h);
    h.render({ ...base, selectedOrderId: 'order-2', operationScopeKey: scoped ? 'scope-B' : undefined });
    h.render(base);
    response.resolve({ kind: 'unknown', message: 'Поздний ответ A' }); await settle(); h.render();
    assert.deepEqual(h.focusEvents, []);
  }
});

test('B feedback: changed assignment, scope, missing selection or mismatched intent cancels the pending scroll', async () => {
  for (const change of ['assignment', 'scope', 'missing', 'intent']) {
    const response = pending(); const base = feedbackProps({ onIntent: () => response.promise });
    const h = harness(base); submit(h);
    const changed = { ...base };
    if (change === 'assignment') changed.orders = ready([order('in_progress', { assignmentRevision: 2 })]);
    if (change === 'scope') changed.operationScopeKey = 'scope-new';
    if (change === 'missing') changed.orders = ready([]);
    if (change === 'intent') changed.pendingIntent = { orderId: 'order-2', expectedVersion: 3, action: 'submit' };
    h.render(changed); h.render(base);
    response.resolve({ kind: 'unknown', message: 'Поздний ответ' }); await settle(); h.render();
    assert.deepEqual(h.focusEvents, [], change);
  }
});

test('B feedback: once consumed, a late result after newer selection never scrolls even after returning to A', async () => {
  const response = pending(); const base = feedbackProps({ onIntent: () => response.promise });
  const h = harness(base); submit(h); h.render();
  assert.deepEqual(h.focusEvents, [operationScroll]);
  h.render({ ...base, selectedOrderId: 'order-2', operationScopeKey: 'scope-B' }); h.render(base);
  response.resolve({ kind: 'unknown', message: 'Поздний ответ A' }); await settle(); h.render();
  assert.deepEqual(h.focusEvents, [operationScroll]);
});

test('B feedback: replaced session or unmount cannot scroll a late old outcome', async () => {
  const response = pending(); const base = feedbackProps({ onIntent: () => response.promise });
  const h = harness(base); submit(h);
  const replacement = { ...base, sessionKey: 'synthetic-replacement-session' };
  h.render(replacement);
  response.resolve({ kind: 'unknown', message: 'PRIVATE_OLD_OUTCOME' }); await settle(); h.render();
  assert.deepEqual(h.focusEvents, []); assert.doesNotMatch(h.text(), /PRIVATE_OLD_OUTCOME/);
  const other = pending(); const unmounted = harness(feedbackProps({ onIntent: () => other.promise }));
  submit(unmounted); unmounted.unmount(); other.resolve({ kind: 'unknown', message: 'Поздний ответ' }); await settle();
  assert.deepEqual(unmounted.focusEvents, []);
});
