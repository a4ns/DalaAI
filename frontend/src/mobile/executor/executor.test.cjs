/* Synthetic model, server-render and hook tests. These do not claim browser/API/device evidence.
 * Integrated checkout: node --test src/mobile/executor/executor.test.cjs
 * Isolated lane: EXECUTOR_DEPENDENCY_ROOT=/path/to/frontend node --test ...
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
const { renderToStaticMarkup } = dep('react-dom/server');

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
const { ExecutorScreen } = load('ExecutorScreen.tsx');
const ready = (snapshot) => ({ snapshot, freshness: 'fresh', loadStatus: 'ready', error: null, lastConfirmedAt: '2026-10-07T19:00:00Z', incomplete: false });
const order = (status = 'issued', other = {}) => ({ id: 'order-1', number: 'Н-001', version: 3, assignmentRevision: 1, sectionId: 'section-1', equipmentLabel: 'Насос Н-1', sectionLabel: 'Участок 1', status, type: 'unplanned', priority: 'normal', description: 'Устранить течь', comment: '', dueAt: '2026-10-08T03:00:00Z', isOverdue: false, ...other });
const dictionaries = { workCodes: [{ id: 'code-1', code: '01', label: 'Замена уплотнения' }], materials: [{ id: 'material-1', code: 'M01', label: 'Прокладка', unit: 'шт.' }] };
function props(overrides = {}) {
  return { sessionKey: 'synthetic-executor-session-1', orders: ready([order()]), dictionaries: ready(dictionaries), selectedOrderId: 'order-1', drafts: {}, mutation: { status: 'idle', error: null }, pendingIntent: null, onSelectOrder() {}, onDraftChange() {}, onRefresh() {}, onResolveConflict() {}, onIntent: async () => ({ kind: 'confirmed' }), onRetry: async () => ({ kind: 'confirmed' }), ...overrides };
}
const markup = (overrides = {}) => renderToStaticMarkup(React.createElement(ExecutorScreen, props(overrides)));

test('state transitions exactly match accepted executor command sources', () => {
  assert.deepEqual(model.allowedActions('issued'), ['accept', 'queue', 'reject']);
  assert.deepEqual(model.allowedActions('queued'), ['accept']);
  assert.deepEqual(model.allowedActions('accepted'), ['start']);
  assert.deepEqual(model.allowedActions('in_progress'), ['submit', 'pause']);
  assert.deepEqual(model.allowedActions('paused'), ['resume']);
  assert.deepEqual(model.allowedActions('rework'), ['start']);
  for (const status of ['done', 'ai_review', 'closed', 'cancelled', 'rejected']) assert.deepEqual(model.allowedActions(status), []);
});
test('quantity parser rejects empty, zero, negatives, exponents and excess precision', () => {
  for (const value of ['', ' ', '0', '0.000', '-1', '1e2', 'Infinity', 'NaN', '1.0001', '1000000000', '1,2,3', '.5']) assert.equal(model.parseQuantity(value), null, value);
  for (const [value, expected] of [['1,5', 1.5], ['0.001', .001], ['999999999', 999999999], [' 2.000 ', 2]]) assert.equal(model.parseQuantity(value), expected);
});
test('empty work and unknown/duplicate/invalid material quantities cannot submit', () => {
  const draft = { ...model.emptyExecutorDraft(), workDescription: '   ', workCodeId: 'unknown', materials: [{ rowId: '1', materialId: 'material-1', quantity: '2' }, { rowId: '2', materialId: 'material-1', quantity: '-1' }, { rowId: '3', materialId: 'unknown', quantity: '1' }] };
  const errors = model.validateExecutorDraft(draft, dictionaries);
  for (const field of ['workDescription', 'workCodeId', 'material:2', 'quantity:2', 'material:3']) assert.ok(errors[field], field);
  assert.throws(() => model.toSubmitPayload(draft));
});
test('incomplete evidence is explicitly allowed for review with valid work', () => {
  const draft = { ...model.emptyExecutorDraft(), workDescription: 'Заменена прокладка' };
  assert.deepEqual(model.validateExecutorDraft(draft, dictionaries), {});
  assert.deepEqual(model.incompleteEvidence(order(), draft), ['шифр работ', 'фото после выполнения']);
  assert.deepEqual(model.incompleteEvidence(order('in_progress', { type: 'planned' }), { ...draft, workCodeId: 'code-1' }), []);
  assert.deepEqual(model.toSubmitPayload(draft), { workDescription: 'Заменена прокладка', workCodeId: null, materials: [], afterPhotoIds: [], comment: '' });
});
test('payload is detached from controlled draft and retains quantity semantics', () => {
  const draft = { ...model.emptyExecutorDraft(), workDescription: '  Заменена прокладка  ', materials: [{ rowId: '1', materialId: 'material-1', quantity: '1,5' }], afterPhotoIds: ['photo-1'] };
  const payload = model.toSubmitPayload(draft);
  assert.equal(payload.materials[0].quantity, 1.5);
  assert.equal(payload.workDescription, 'Заменена прокладка');
  draft.materials[0].quantity = '4'; draft.afterPhotoIds.push('photo-2');
  assert.equal(payload.materials[0].quantity, 1.5);
  assert.deepEqual(payload.afterPhotoIds, ['photo-1']);
});
test('empty copy appears only after fresh complete successful snapshot', () => {
  assert.match(markup({ orders: ready([]), selectedOrderId: null }), /Назначенных нарядов нет/);
  for (const state of [
    { ...ready([]), freshness: 'never', loadStatus: 'idle', snapshot: null },
    { ...ready([]), loadStatus: 'loading' }, { ...ready([]), loadStatus: 'error', error: 'Ошибка загрузки' },
    { ...ready([]), loadStatus: 'offline' }, { ...ready([]), freshness: 'stale' }, { ...ready([]), incomplete: true },
  ]) assert.doesNotMatch(markup({ orders: state }), /Назначенных нарядов нет/);
});
test('UTC+5 time is explicit and invalid input does not invent a time', () => {
  assert.match(model.formatExecutorTime('2026-10-07T19:00:00Z'), /08\.10/);
  assert.match(model.formatExecutorTime('2026-10-07T19:00:00Z'), /00:00 \(UTC\+5\)/);
  assert.equal(model.formatExecutorTime('not a date'), 'Время не получено');
});
test('unknown outcome freezes data and exposes exact-intent replay, no fake success', () => {
  const html = markup({ orders: ready([order('in_progress')]), mutation: { status: 'unknown_result', error: 'Ответ потерян' }, drafts: { 'order-1': { ...model.emptyExecutorDraft(), workDescription: 'Сохранённый текст' } } });
  assert.match(html, /Результат не подтверждён/); assert.match(html, /Повторить исходное действие/);
  assert.match(html, /disabled=""[^>]*>Сохранённый текст/);
  assert.doesNotMatch(html, /Действие подтверждено сервером/);
});
test('server review status does not invent model progress or automatic acceptance', () => {
  const html = markup({ orders: ready([order('ai_review')]) });
  assert.match(html, /Окончательное решение принимает мастер/);
  assert.match(html, /Статус работы ИИ здесь не подтверждён/);
  assert.doesNotMatch(html, /ИИ анализирует|Работа принята|ИИ одобрил/);
});

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
  function render(next = currentProps) { currentProps = next; cursor = 0; pendingEffects = []; const wrapper = Component(currentProps); tree = wrapper.type(wrapper.props); elements(tree).forEach((node) => {
    if (node.props?.ref && typeof node.props.ref === 'object') node.props.ref.current = {
      focus: (options) => focusEvents.push({ kind: 'focus', id: node.props.id, options }),
      scrollIntoView: (options) => focusEvents.push({ kind: 'scroll', id: node.props.id, options }),
    };
  }); pendingEffects.forEach((effect) => effect()); return tree; }
  function elements(node, result = []) { if (node && typeof node === 'object' && typeof node.type === 'function') return elements(node.type(node.props), result); if (!node || typeof node !== 'object') return result; if (Array.isArray(node)) { node.forEach((item) => elements(item, result)); return result; } result.push(node); elements(node.props?.children, result); return result; }
  function text(node) { if (node === null || node === undefined || typeof node === 'boolean') return ''; if (typeof node === 'string' || typeof node === 'number') return String(node); if (Array.isArray(node)) return node.map(text).join(''); return text(node.props?.children); }
  render();
  return { render, focusEvents, element: (predicate) => elements(tree).find(predicate), button: (label) => elements(tree).find((node) => node.type === 'button' && text(node) === label), form: () => elements(tree).find((node) => node.type === 'form'), unmount() { for (const slot of slots) slot?.cleanup?.(); }, text: () => text(tree) };
}
const settle = () => new Promise((resolve) => setImmediate(resolve));
test('synchronous double click reserves only one intent; unknown retry uses separate callback', async () => {
  let resolve; const first = new Promise((done) => { resolve = done; });
  const intents = []; let retries = 0;
  const h = harness(props({ onIntent: (intent) => { intents.push(intent); return first; }, onRetry: async () => { retries++; return { kind: 'confirmed' }; } }));
  const click = h.button('Принять').props.onClick;
  click(); click(); assert.equal(intents.length, 1);
  assert.deepEqual(intents[0], { orderId: 'order-1', expectedVersion: 3, expectedAssignmentRevision: 1, action: 'accept', payload: {} });
  resolve({ kind: 'unknown', message: 'Ответ потерян' }); await settle(); h.render();
  assert.equal(h.button('Принять').props.disabled, true);
  h.button('Повторить исходное действие').props.onClick(); await settle(); h.render();
  assert.equal(retries, 1); assert.equal(intents.length, 1);
});
test('invalid form does not invoke transport, valid incomplete form does', async () => {
  const intents = []; const base = props({ orders: ready([order('in_progress')]), onIntent: async (intent) => { intents.push(intent); return { kind: 'rejected', message: 'Тестовый отказ' }; } });
  const h = harness(base); h.form().props.onSubmit({ preventDefault() {} }); assert.equal(intents.length, 0);
  h.render({ ...base, drafts: { 'order-1': { ...model.emptyExecutorDraft(), workDescription: 'Заменена прокладка' } } });
  h.form().props.onSubmit({ preventDefault() {} }); await settle();
  assert.equal(intents.length, 1); assert.equal(intents[0].action, 'submit'); assert.equal(intents[0].payload.workCodeId, null); assert.deepEqual(intents[0].payload.afterPhotoIds, []);
});
test('409 requires a new confirmed snapshot and explicit resolution, preserving controlled draft', async () => {
  let resolved = 0; const draft = { ...model.emptyExecutorDraft(), workDescription: 'Не терять' };
  const base = props({ orders: ready([order('in_progress')]), drafts: { 'order-1': draft }, onIntent: async () => ({ kind: 'conflict', message: 'Версия изменилась' }), onResolveConflict: () => { resolved++; } });
  const h = harness(base); h.form().props.onSubmit({ preventDefault() {} }); await settle(); h.render();
  assert.equal(h.button('Состояние проверено, продолжить').props.disabled, true);
  assert.equal(base.drafts['order-1'], draft);
  h.button('Загрузить актуальное состояние').props.onClick();
  h.render({ ...base, orders: { ...ready([order('in_progress', { version: 4 })]), lastConfirmedAt: '2026-10-07T19:01:00Z' } });
  assert.equal(h.button('Состояние проверено, продолжить').props.disabled, false);
  h.button('Состояние проверено, продолжить').props.onClick(); assert.equal(resolved, 1);
});
test('selecting another order cannot release confirmed action awaiting original snapshot', async () => {
  const base = props({ orders: ready([order(), order('issued', { id: 'order-2', number: 'Н-002' })]) });
  const h = harness(base); h.button('Принять').props.onClick(); await settle(); h.render({ ...base, selectedOrderId: 'order-2' });
  assert.equal(h.button('Принять').props.disabled, true);
});
test('late response after unmount has no local state effect', async () => {
  let resolve; const deferred = new Promise((done) => { resolve = done; });
  const h = harness(props({ onIntent: () => deferred })); h.button('Принять').props.onClick(); h.render(); h.unmount();
  resolve({ kind: 'confirmed' }); await settle(); h.render();
  assert.doesNotMatch(h.text(), /Действие подтверждено сервером/);
});


test('late confirmed-photo callback preserves current text and targets its original order', () => {
  const contexts = []; const changes = [];
  const firstDraft = { ...model.emptyExecutorDraft(), workDescription: 'Старый текст' };
  const base = props({ orders: ready([order('in_progress'), order('in_progress', { id: 'order-2', number: 'Н-002' })]), drafts: { 'order-1': firstDraft }, renderPhotoPicker: (context) => { contexts.push(context); return null; }, onDraftChange: (orderId, draft) => changes.push({ orderId, draft }) });
  const h = harness(base); const oldCallback = contexts[0].onConfirmedPhotoIdsChange;
  const updated = { ...firstDraft, workDescription: 'Новый текст', comment: 'Не потерять', materials: [{ rowId: '1', materialId: 'material-1', quantity: '2' }] };
  h.render({ ...base, selectedOrderId: 'order-2', drafts: { 'order-1': updated, 'order-2': model.emptyExecutorDraft() } });
  oldCallback(['photo-1']);
  assert.equal(changes.length, 1); assert.equal(changes[0].orderId, 'order-1');
  assert.deepEqual(changes[0].draft, { ...updated, afterPhotoIds: ['photo-1'] });
});
test('late photo callbacks cannot edit unknown-result or unmounted drafts', () => {
  const contexts = []; const changes = [];
  const base = props({ orders: ready([order('in_progress')]), renderPhotoPicker: (context) => { contexts.push(context); return null; }, onDraftChange: (...change) => changes.push(change) });
  const h = harness(base); const oldCallback = contexts[0].onConfirmedPhotoIdsChange;
  h.render({ ...base, mutation: { status: 'unknown_result', error: 'Ответ потерян' } });
  oldCallback(['photo-1']); assert.equal(changes.length, 0);
  h.render(base); h.unmount(); oldCallback(['photo-2']); assert.equal(changes.length, 0);
});
test('late photo from prior assignment cannot attach to a new assignment', () => {
  const contexts = []; const changes = [];
  const base = props({ orders: ready([order('in_progress')]), renderPhotoPicker: (context) => { contexts.push(context); return null; }, onDraftChange: (...change) => changes.push(change) });
  const h = harness(base); const oldCallback = contexts[0].onConfirmedPhotoIdsChange;
  h.render({ ...base, orders: ready([order('in_progress', { assignmentRevision: 2 })]) });
  oldCallback(['photo-old']); assert.equal(changes.length, 0);
  h.render({ ...base, orders: ready([order('in_progress', { sectionId: 'section-2' })]) });
  oldCallback(['photo-old']); assert.equal(changes.length, 0);
});


test('deliberate card selection focuses its detail heading after controlled selection commits', () => {
  const selections = []; let intents = 0;
  const base = props({ orders: ready([order(), order('issued', { id: 'order-2', number: 'Н-002' })]), onSelectOrder: (id) => selections.push(id), onIntent: async () => { intents++; return { kind: 'confirmed' }; } });
  const h = harness(base);
  assert.equal(h.focusEvents.length, 0, 'initial selection must not steal focus');
  const card = h.element((node) => node.type === 'button' && node.props.className?.includes('executor-order-card') && node.props['aria-pressed'] === false);
  assert.equal(card.props.type, 'button', 'selection never submits a surrounding form');
  card.props.onClick();
  assert.deepEqual(selections, ['order-2']); assert.equal(h.focusEvents.length, 0, 'do not focus old details before controlled update');
  h.render({ ...base, selectedOrderId: 'order-2' });
  assert.deepEqual(h.focusEvents.map((event) => event.kind), ['focus', 'scroll']);
  assert.deepEqual(h.focusEvents[0].options, { preventScroll: true });
  assert.equal(h.element((node) => node.type === 'h2' && node.props.id === ':test:-order-title').props.tabIndex, -1);
  assert.equal(intents, 0);
});
test('background refresh and unrelated draft changes never steal detail focus', () => {
  const base = props(); const h = harness(base);
  h.render({ ...base, orders: { ...ready([order('accepted', { version: 4 })]), lastConfirmedAt: '2026-10-07T19:02:00Z' } });
  h.render({ ...base, drafts: { 'order-1': { ...model.emptyExecutorDraft(), reason: 'Черновик' } } });
  assert.deepEqual(h.focusEvents, []);
});
test('reselecting the same card brings existing detail into view without a mutation', () => {
  let selections = 0; const h = harness(props({ onSelectOrder: () => { selections++; } }));
  const card = h.element((node) => node.type === 'button' && node.props.className?.includes('executor-order-card'));
  card.props.onClick();
  assert.equal(selections, 0); assert.deepEqual(h.focusEvents.map((event) => event.kind), ['focus', 'scroll']);
});


test('unresolved photo work disables submit and cannot create a command through form handler', () => {
  let intents = 0; const reason = 'Загрузка фото не подтверждена: проверьте исходную попытку.';
  const h = harness(props({ orders: ready([order('in_progress')]), drafts: { 'order-1': { ...model.emptyExecutorDraft(), workDescription: 'Заменена прокладка' } }, photoBusy: true, photoBusyReason: reason, onIntent: async () => { intents++; return { kind: 'confirmed' }; } }));
  assert.equal(h.button('Отправить неполный результат на проверку').props.disabled, true);
  assert.match(h.text(), /Загрузка фото не подтверждена/);
  h.form().props.onSubmit({ preventDefault() {} }); assert.equal(intents, 0);
  h.render(); assert.match(h.text(), /Загрузка фото не подтверждена/);
  assert.doesNotMatch(h.text(), /Отправляем действие|Действие подтверждено сервером/);
});
test('settled photo activity re-enables a valid result but never clears unknown command lock', () => {
  const base = props({ orders: ready([order('in_progress')]), drafts: { 'order-1': { ...model.emptyExecutorDraft(), workDescription: 'Заменена прокладка' } }, photoBusy: true });
  const h = harness(base);
  h.render({ ...base, photoBusy: false });
  assert.equal(h.button('Отправить неполный результат на проверку').props.disabled, false);
  h.render({ ...base, photoBusy: false, mutation: { status: 'unknown_result', error: 'Ответ команды потерян' } });
  assert.equal(h.button('Отправить неполный результат на проверку').props.disabled, true);
  assert.equal(h.button('Повторить исходное действие').props.disabled, false);
});

test('superseded local feedback never resurfaces after parent mutation state cycles', async () => {
  const base = props({ onIntent: async () => ({ kind: 'unknown', message: 'Старый неизвестный результат' }) });
  const h = harness(base); h.button('Принять').props.onClick(); await settle(); h.render();
  assert.match(h.text(), /Старый неизвестный результат/);
  h.render({ ...base, mutation: { status: 'confirmed', error: null }, orders: ready([order('accepted', { version: 4 })]) });
  assert.doesNotMatch(h.text(), /Старый неизвестный результат/);
  h.render(base); h.render(base);
  assert.doesNotMatch(h.text(), /Старый неизвестный результат/);
});
test('background polling cannot satisfy a conflict review without explicit refresh request', () => {
  const base = props({ mutation: { status: 'conflict', error: '409' } });
  const h = harness(base);
  const refreshed = { ...base, orders: { ...ready([order('issued', { version: 4 })]), lastConfirmedAt: '2026-10-07T19:01:00Z' } };
  h.render(refreshed);
  assert.equal(h.button('Состояние проверено, продолжить').props.disabled, true);
  h.button('Загрузить актуальное состояние').props.onClick();
  h.render({ ...refreshed, orders: { ...refreshed.orders, lastConfirmedAt: '2026-10-07T19:02:00Z' } });
  assert.equal(h.button('Состояние проверено, продолжить').props.disabled, false);
});

test('unknown response keeps old DOM callbacks locked before the next render commits', async () => {
  let resolve; const response = new Promise((done) => { resolve = done; }); let intents = 0;
  const h = harness(props({ onIntent: () => { intents++; return response; } }));
  const oldClick = h.button('Принять').props.onClick;
  oldClick(); assert.equal(intents, 1);
  resolve({ kind: 'unknown', message: 'Ответ не подтверждён' }); await settle();
  // Deliberately invoke the previously rendered callback before simulating React's next commit.
  oldClick(); assert.equal(intents, 1);
  h.render(); assert.equal(h.button('Принять').props.disabled, true);
});

test('scoped unknown A stays frozen while selecting authorized B remains available', () => {
  const selections = []; const edits = [];
  const aDraft = { ...model.emptyExecutorDraft(), workDescription: 'Сохранённый результат A' };
  const base = props({ operationScopeKey: 'order-1:1', orders: ready([order('in_progress'), order('issued', { id: 'order-2', number: 'Н-002' })]), drafts: { 'order-1': aDraft }, mutation: { status: 'unknown_result', error: 'Ответ A не подтверждён' }, pendingIntent: { orderId: 'order-1', expectedVersion: 3, action: 'submit' }, onSelectOrder: (id) => selections.push(id), onDraftChange: (...args) => edits.push(args) });
  const h = harness(base);
  assert.equal(h.button('Отправить неполный результат на проверку').props.disabled, true);
  h.element((node) => node.type === 'textarea' && node.props.id === ':test:-work').props.onChange({ target: { value: 'Не менять A' } });
  assert.deepEqual(edits, []);
  const bCard = h.element((node) => node.type === 'button' && node.props.className?.includes('executor-order-card') && node.props['aria-pressed'] === false);
  assert.equal(bCard.props.disabled, false); bCard.props.onClick(); assert.deepEqual(selections, ['order-2']);
  h.render({ ...base, selectedOrderId: 'order-2', operationScopeKey: 'order-2:1', mutation: { status: 'idle', error: null }, pendingIntent: null });
  assert.equal(h.button('Принять').props.disabled, false);
  assert.equal(base.drafts['order-1'], aDraft, 'original controlled draft is retained, not cleared');
});

test('lost A then reassignment and late retry403 cannot overwrite B feedback or release its pending latch', async () => {
  let finishRetryA; let finishB; const retryA = new Promise((resolve) => { finishRetryA = resolve; }); const responseB = new Promise((resolve) => { finishB = resolve; });
  const calls = []; let retries = 0;
  const unknownA = { kind: 'unknown', message: 'A: исходный результат неизвестен' };
  const aDraft = { ...model.emptyExecutorDraft(), reason: 'Сохранённый черновик A' };
  const base = props({ operationScopeKey: 'order-1:1', orders: ready([order(), order('issued', { id: 'order-2', number: 'Н-002' })]), drafts: { 'order-1': aDraft }, onIntent: (intent) => { calls.push(intent); return intent.orderId === 'order-1' ? Promise.resolve(unknownA) : responseB; }, onRetry: () => { retries++; return retryA; } });
  const h = harness(base); h.button('Принять').props.onClick(); await settle(); h.render();
  assert.equal(calls.length, 1); assert.match(h.text(), /исходный результат неизвестен/);
  h.button('Повторить исходное действие').props.onClick(); h.render(); assert.equal(retries, 1);
  const bProps = { ...base, selectedOrderId: 'order-2', operationScopeKey: 'order-2:1', orders: ready([order('issued', { id: 'order-2', number: 'Н-002' })]), drafts: {}, mutation: { status: 'idle', error: null }, pendingIntent: null, quarantinedIntentCount: 1, onRetry: async () => { throw new Error('B has no retry'); } };
  h.render(bProps); assert.equal(h.button('Принять').props.disabled, false);
  const bClick = h.button('Принять').props.onClick; bClick(); assert.equal(calls.length, 2);
  finishRetryA({ kind: 'unknown', message: '403: доступ A изменился, исходный результат всё ещё неизвестен' }); await settle();
  bClick(); assert.equal(calls.length, 2, 'late A finally must not clear B in-flight latch');
  h.render(bProps); assert.match(h.text(), /Отправляем действие/); assert.doesNotMatch(h.text(), /403: доступ A/);
  assert.equal(h.button('Принять').props.disabled, true);
  finishB({ kind: 'confirmed' }); await settle();
  h.render({ ...bProps, orders: ready([order('accepted', { id: 'order-2', number: 'Н-002', version: 4 })]) });
  assert.match(h.text(), /Действие подтверждено сервером/); assert.equal(h.button('Начать работу').props.disabled, false);
  assert.deepEqual(calls.map((intent) => intent.orderId), ['order-1', 'order-2']);
  assert.equal(base.drafts['order-1'], aDraft); assert.equal(retries, 1);
});

test('quarantined missing A renders only a generic notice, never its old draft or error details', () => {
  const html = markup({ operationScopeKey: 'none', quarantinedIntentCount: 1, selectedOrderId: 'order-1', orders: ready([order('issued', { id: 'order-2', number: 'Н-002' })]), drafts: { 'order-1': { ...model.emptyExecutorDraft(), workDescription: 'PRIVATE_OLD_WORK' } }, mutation: { status: 'unknown_result', error: 'PRIVATE_OLD_ERROR' }, pendingIntent: { orderId: 'order-1', expectedVersion: 3, action: 'submit' } });
  assert.match(html, /Исходная попытка сохранена отдельно/);
  assert.doesNotMatch(html, /PRIVATE_OLD_WORK|PRIVATE_OLD_ERROR/);
  assert.match(html, /Н-002/);
  assert.doesNotMatch(html, /Повторить исходное действие/);
});

test('stale A form and photo callbacks cannot act on B after a scoped selection change', () => {
  const edits = []; const intents = []; const photoContexts = [];
  const base = props({ operationScopeKey: 'order-1:1', orders: ready([order('in_progress')]), drafts: { 'order-1': { ...model.emptyExecutorDraft(), workDescription: 'Готовая работа A' } }, onDraftChange: (...args) => edits.push(args), onIntent: async (intent) => { intents.push(intent); return { kind: 'confirmed' }; }, renderPhotoPicker: (context) => { photoContexts.push(context); return null; } });
  const h = harness(base); const oldForm = h.form(); const oldInput = h.element((node) => node.type === 'textarea' && node.props.id === ':test:-work'); const oldPhoto = photoContexts[0];
  h.render({ ...base, selectedOrderId: 'order-2', operationScopeKey: 'order-2:4', orders: ready([order('in_progress', { id: 'order-2', number: 'Н-002', assignmentRevision: 4 })]), drafts: { 'order-2': { ...model.emptyExecutorDraft(), workDescription: 'Работа B' } } });
  oldInput.props.onChange({ target: { value: 'Устаревшее изменение A' } }); oldPhoto.onConfirmedPhotoIdsChange(['photo-A']); oldForm.props.onSubmit({ preventDefault() {} });
  assert.deepEqual(edits, []); assert.deepEqual(intents, []); assert.doesNotMatch(h.text(), /Устаревшее изменение A/);
});

test('draft edits and emitted intents carry the selected assignment revision', async () => {
  const edits = []; const intents = [];
  const h = harness(props({ operationScopeKey: 'order-1:7', orders: ready([order('in_progress', { assignmentRevision: 7 })]), drafts: { 'order-1': { ...model.emptyExecutorDraft(), workDescription: 'Работа' } }, onDraftChange: (...args) => edits.push(args), onIntent: async (intent) => { intents.push(intent); return { kind: 'rejected', message: 'Synthetic result' }; } }));
  h.element((node) => node.type === 'textarea' && node.props.id === ':test:-work').props.onChange({ target: { value: 'Уточнение' } });
  assert.equal(edits[0][0], 'order-1'); assert.equal(edits[0][2], 7);
  h.form().props.onSubmit({ preventDefault() {} }); await settle();
  assert.equal(intents[0].expectedAssignmentRevision, 7); assert.equal(intents[0].expectedVersion, 3);
});

test('retained A submit cannot clear B validation feedback before scope rejection', () => {
  const intents = [];
  const base = props({ operationScopeKey: 'order-1:1', orders: ready([order('in_progress')]), drafts: { 'order-1': { ...model.emptyExecutorDraft(), workDescription: 'Валидный результат A' } }, onIntent: async (intent) => { intents.push(intent); return { kind: 'confirmed' }; } });
  const h = harness(base); const oldFormA = h.form();
  const bProps = { ...base, operationScopeKey: 'order-2:1', selectedOrderId: 'order-2', orders: ready([order('in_progress', { id: 'order-2', number: 'Н-002' })]), drafts: { 'order-2': model.emptyExecutorDraft() } };
  h.render(bProps); h.form().props.onSubmit({ preventDefault() {} }); h.render(bProps);
  assert.match(h.text(), /Опишите выполненные работы/);
  oldFormA.props.onSubmit({ preventDefault() {} }); h.render(bProps);
  assert.match(h.text(), /Опишите выполненные работы/);
  assert.deepEqual(intents, []);
});

test('retained A mode refresh selection filter and add-row callbacks leave B feedback unchanged', () => {
  const selections = []; const edits = []; let refreshes = 0;
  const other = order('in_progress', { id: 'order-2', number: 'Н-002' });
  const closed = order('closed', { id: 'order-3', number: 'PRIVATE_CLOSED_NUMBER' });
  const base = props({ operationScopeKey: 'order-1:1', orders: ready([order('in_progress'), other, closed]), drafts: { 'order-1': { ...model.emptyExecutorDraft(), workDescription: 'Работа A' } }, onSelectOrder: (id) => selections.push(id), onDraftChange: (...args) => edits.push(args), onRefresh: () => { refreshes++; } });
  const h = harness(base);
  const stale = [h.button('Приостановить').props.onClick, h.button('Обновить').props.onClick, h.button('Все').props.onClick, h.button('Добавить материал').props.onClick, h.element((node) => node.type === 'button' && node.props.className?.includes('executor-order-card') && node.props['aria-pressed'] === true).props.onClick];
  const bProps = { ...base, operationScopeKey: 'order-2:1', selectedOrderId: 'order-2', orders: ready([other, closed]), drafts: { 'order-2': model.emptyExecutorDraft() } };
  h.render(bProps); h.form().props.onSubmit({ preventDefault() {} }); h.render(bProps);
  const before = h.text();
  for (const callback of stale) callback();
  h.render(bProps);
  assert.equal(h.text(), before); assert.match(h.text(), /Опишите выполненные работы/); assert.doesNotMatch(h.text(), /PRIVATE_CLOSED_NUMBER/);
  assert.equal(refreshes, 0); assert.deepEqual(selections, []); assert.deepEqual(edits, []);
});

const { ResultAnalysisDisclosure, resultAssessmentMessage } = load('ResultAnalysisDisclosure.tsx');
const disclosure = (state) => renderToStaticMarkup(React.createElement(ResultAnalysisDisclosure, { state }));
test('isolated disclosure defaults to unknown and states conditional transfer plus master decision', () => {
  const html = disclosure();
  assert.match(html, /Когда оператор включает OpenAI/);
  assert.match(html, /описание выполненной работы и фотографии до и после выполнения передаются OpenAI/);
  assert.match(html, /Настроенный режим:<\/strong> не подтверждён/);
  assert.match(html, /Статус проверки результата не подтверждён/);
  assert.match(html, /Окончательное решение принимает мастер/);
  assert.doesNotMatch(html, /Проверка по правилам завершена|Результат анализа OpenAI получен|<button|<input/);
});
test('configured OpenAI never implies that this result was analyzed', () => {
  const html = disclosure({ configuredMode: 'openai', assessment: { status: 'unknown', method: 'unknown' } });
  assert.match(html, /Настроенный режим:<\/strong> OpenAI/);
  assert.match(html, /Статус проверки результата не подтверждён/);
  assert.doesNotMatch(html, /Результат анализа OpenAI получен|Проверка по правилам завершена/);
});
test('configured rules with missing assessment remains unknown instead of invented fallback completion', () => {
  const html = disclosure({ configuredMode: 'rules_fallback', assessment: { status: 'unknown', method: 'unknown' } });
  assert.match(html, /Настроенный режим:<\/strong> проверка по правилам/);
  assert.match(html, /Статус проверки результата не подтверждён/);
  assert.doesNotMatch(html, /Проверка по правилам завершена|Результат анализа OpenAI получен/);
});
test('actual rules fallback stays distinct from configured OpenAI and does not verify photo contents', () => {
  const html = disclosure({ configuredMode: 'openai', assessment: { status: 'completed', method: 'rules_fallback' } });
  assert.match(html, /Настроенный режим:<\/strong> OpenAI/);
  assert.match(html, /Проверка по правилам завершена\. Это не подтверждает анализ содержимого фото моделью/);
  assert.doesNotMatch(html, /Результат анализа OpenAI получен|Фото проверены|Работа безопасна|Фото не отправлялись/);
});
test('pending and failed OpenAI attempts never claim an analysis result was received', () => {
  for (const status of ['pending', 'failed']) {
    const html = disclosure({ configuredMode: 'openai', assessment: { status, method: 'openai' } });
    assert.doesNotMatch(html, /Результат анализа OpenAI получен|Проверка по правилам завершена|Работа безопасна|Работа выполнена правильно/);
  }
  assert.equal(resultAssessmentMessage({ status: 'pending', method: 'openai' }), 'Проверка результата ещё не завершена.');
  assert.equal(resultAssessmentMessage({ status: 'failed', method: 'openai' }), 'Проверку результата не удалось завершить. Подтверждённого результата анализа нет.');
});
test('completed outcome uses its verified method rather than the current configured mode', () => {
  const html = disclosure({ configuredMode: 'rules_fallback', assessment: { status: 'completed', method: 'openai' } });
  assert.match(html, /Настроенный режим:<\/strong> проверка по правилам/);
  assert.match(html, /Результат анализа OpenAI получен/);
  assert.equal(resultAssessmentMessage({ status: 'completed', method: 'unknown' }), 'Проверка завершена. Способ проверки не подтверждён.');
  assert.equal(resultAssessmentMessage({ status: 'unknown', method: 'rules_fallback' }), 'Статус проверки результата не подтверждён.');
  assert.equal(resultAssessmentMessage(undefined), 'Статус проверки результата не подтверждён.');
});

const disclosureMarker = React.createElement('aside', { 'data-testid': 'analysis-disclosure-slot' }, 'DISCLOSURE_SLOT_MARKER');
test('optional disclosure mounts once inside selected result detail and outside forms or photo fieldsets', () => {
  for (const status of ['in_progress', 'done', 'ai_review', 'rework', 'closed']) {
    const html = markup({ orders: ready([order(status)]), resultAnalysisDisclosure: disclosureMarker });
    assert.equal((html.match(/DISCLOSURE_SLOT_MARKER/g) ?? []).length, 1, status);
    assert.match(html.match(/<article\b[\s\S]*?<\/article>/)?.[0] ?? '', /DISCLOSURE_SLOT_MARKER/, status);
    for (const fieldset of html.match(/<fieldset\b[\s\S]*?<\/fieldset>/g) ?? []) assert.doesNotMatch(fieldset, /DISCLOSURE_SLOT_MARKER/);
    if (status === 'in_progress') {
      assert.ok(html.indexOf('DISCLOSURE_SLOT_MARKER') < html.indexOf('<form'), 'disclosure precedes result form');
      const withoutSlot = html.replace('<aside data-testid="analysis-disclosure-slot">DISCLOSURE_SLOT_MARKER</aside>', '');
      assert.equal(withoutSlot, markup({ orders: ready([order(status)]) }), 'slot does not change command controls or inputs');
    }
  }
});
test('optional disclosure stays absent outside result states and while pause or reject form is open', () => {
  for (const status of ['issued', 'queued', 'accepted', 'rejected', 'paused', 'cancelled']) assert.doesNotMatch(markup({ orders: ready([order(status)]), resultAnalysisDisclosure: disclosureMarker }), /DISCLOSURE_SLOT_MARKER/);
  const base = props({ orders: ready([order('in_progress')]), resultAnalysisDisclosure: disclosureMarker });
  const h = harness(base); assert.match(h.text(), /DISCLOSURE_SLOT_MARKER/);
  h.button('Приостановить').props.onClick(); h.render(base); assert.doesNotMatch(h.text(), /DISCLOSURE_SLOT_MARKER/);
  h.button('Вернуться без отправки').props.onClick(); h.render(base); assert.equal((h.text().match(/DISCLOSURE_SLOT_MARKER/g) ?? []).length, 1);
  const reject = harness(props({ resultAnalysisDisclosure: disclosureMarker })); reject.button('Отклонить').props.onClick(); reject.render(); assert.doesNotMatch(reject.text(), /DISCLOSURE_SLOT_MARKER/);
});
test('missing or quarantined selected order cannot render disclosure-associated private content', () => {
  const privateDisclosure = React.createElement('aside', null, 'PRIVATE_OLD_RESULT_DISCLOSURE');
  for (const selectedOrderId of [null, 'order-1']) {
    const html = markup({ operationScopeKey: 'none', quarantinedIntentCount: 1, selectedOrderId, orders: ready([order('in_progress', { id: 'order-2', number: 'Н-002' })]), resultAnalysisDisclosure: privateDisclosure });
    assert.doesNotMatch(html, /PRIVATE_OLD_RESULT_DISCLOSURE/);
  }
  assert.doesNotMatch(markup({ orders: ready([]), selectedOrderId: null, resultAnalysisDisclosure: privateDisclosure }), /PRIVATE_OLD_RESULT_DISCLOSURE/);
});
test('default unknown disclosure slot adds no configured-provider or completed-assessment claim', () => {
  const html = markup({ orders: ready([order('in_progress')]), resultAnalysisDisclosure: React.createElement(ResultAnalysisDisclosure) });
  assert.equal((html.match(/Когда оператор включает OpenAI/g) ?? []).length, 1);
  assert.match(html, /Настроенный режим:<\/strong> не подтверждён/);
  assert.match(html, /Статус проверки результата не подтверждён/);
  assert.doesNotMatch(html, /Результат анализа OpenAI получен|Проверка по правилам завершена/);
});
