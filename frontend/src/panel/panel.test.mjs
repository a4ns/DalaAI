/** Synthetic local unit/SSR checks. No HTTP, database or browser/device claim. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const directory = dirname(fileURLToPath(import.meta.url));
const dependencyRoot = resolve(process.argv[2] ?? join(directory, '../..'));
const requireDependency = createRequire(join(dependencyRoot, 'package.json'));
const ts = requireDependency('typescript');
const React = requireDependency('react');
const { renderToStaticMarkup } = requireDependency('react-dom/server');
const modules = new Map();

// Transpile this package only; runtime dependencies are read from B4's install.
function moduleUrl(file) {
  if (modules.has(file)) return modules.get(file);
  const result = ts.transpileModule(readFileSync(file, 'utf8'), {
    fileName: file,
    compilerOptions: { target: ts.ScriptTarget.ES2023, module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX },
  });
  const code = result.outputText.replace(/^import ['"]\.\/panel\.css['"];?\s*$/gm, '')
    .replace(/from ['"]([^'"]+)['"]/g, (_match, specifier) => {
      const destination = specifier.startsWith('.')
        ? moduleUrl(resolve(dirname(file), `${specifier}.ts`))
        : pathToFileURL(requireDependency.resolve(specifier)).href;
      return `from '${destination}'`;
    });
  const url = `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`;
  modules.set(file, url);
  return url;
}

const model = await import(moduleUrl(join(directory, 'model.ts')));
const labels = await import(moduleUrl(join(directory, 'ru.ts')));
const { PanelScreen } = await import(moduleUrl(join(directory, 'PanelScreen.tsx')));
const fresh = (snapshot) => ({ snapshot, freshness: 'fresh', loadStatus: 'ready', error: null,
  lastConfirmedAt: '2026-10-07T19:00:00Z', incomplete: false });
const never = () => ({ snapshot: null, freshness: 'never', loadStatus: 'loading', error: null,
  lastConfirmedAt: null, incomplete: false });
const order = { id: 'synthetic-order-a', number: '42', title: 'Синтетическая замена фильтра',
  sectionLabel: 'Учебный участок', equipmentLabel: 'Учебный насос', executorLabel: 'ДЕМО-01',
  status: 'in_progress', priority: 'emergency', dueAt: '2026-10-07T19:10:00Z', isOverdue: true, version: 3 };
const event = { id: 'synthetic-event-a', sequence: 2, occurredAt: '2026-10-07T19:00:00Z',
  kind: 'order.started', actorLabel: 'ДЕМО-01', reason: null, fromStatus: 'accepted', toStatus: 'in_progress' };
const base = { orders: fresh([order]), selectedOrderId: null, onSelectOrder: () => {} };
const render = (props = {}) => renderToStaticMarkup(React.createElement(PanelScreen, { ...base, ...props }));
let count = 0;
function check(label, run) { run(); count += 1; console.log(`PASS ${label}`); }

check('initial load is not a confirmed empty list', () => {
  const html = render({ orders: never() });
  assert.match(html, /загружаем данные/);
  assert.doesNotMatch(html, /Доступных нарядов нет/);
});
check('first request failure is not a confirmed empty list', () => {
  const html = render({ orders: { ...never(), loadStatus: 'error', error: 'Сбой загрузки' } });
  assert.match(html, /не удалось завершить загрузку/);
  assert.doesNotMatch(html, /Доступных нарядов нет/);
});
check('empty is shown only after a fresh complete successful sweep', () => {
  assert.match(render({ orders: fresh([]) }), /Доступных нарядов нет/);
  for (const change of [{ incomplete: true }, { freshness: 'stale' }, { loadStatus: 'loading' }, { loadStatus: 'offline' }]) {
    assert.doesNotMatch(render({ orders: { ...fresh([]), ...change } }), /Доступных нарядов нет/);
  }
});
check('partial sweep failures retain old snapshot and disclose incompleteness', () => {
  const html = render({ orders: { ...fresh([order]), freshness: 'stale', loadStatus: 'error', incomplete: true } });
  assert.match(html, /Синтетическая замена фильтра/);
  assert.match(html, /Полнота списка не подтверждена/);
  assert.doesNotMatch(html, /Всего нарядов|В реальном времени/);
});
check('authorization loss suppresses every old resource', () => {
  for (const access of ['unauthenticated', 'forbidden']) {
    const html = render({ access, selectedOrderId: order.id,
      employees: fresh([{ id: 'e', label: 'SECRET EMPLOYEE', onShift: true, activeOrderId: order.id, queueCount: 1 }]),
      history: fresh({ orderId: order.id, events: [{ ...event, reason: 'SECRET AUDIT' }] }) });
    assert.doesNotMatch(html, /Синтетическая замена фильтра|SECRET/);
    assert.match(html, /role="alert"/);
  }
});
check('a previous order history cannot leak into a newer selection', () => {
  const html = render({ selectedOrderId: order.id, history: fresh({ orderId: 'another-order',
    events: [{ ...event, reason: 'PREVIOUS ORDER SECRET' }] }) });
  assert.doesNotMatch(html, /PREVIOUS ORDER SECRET/);
  assert.match(html, /История выбранного наряда ещё не загружена/);
});
check('an order removed from an authorized sweep cannot retain visible history', () => {
  const html = render({ orders: fresh([]), selectedOrderId: order.id,
    history: fresh({ orderId: order.id, events: [{ ...event, reason: 'REMOVED SECRET' }] }) });
  assert.doesNotMatch(html, /REMOVED SECRET|Синтетическая замена фильтра/);
});
check('history uses sequence, deduplicates ID and escapes unsafe free text', () => {
  assert.deepEqual(model.sortedPanelEvents([{ ...event, sequence: 1, id: 'b' }, event, event]).map((row) => row.sequence), [2, 1]);
  const html = render({ selectedOrderId: order.id,
    history: fresh({ orderId: order.id, events: [{ ...event, reason: '<script>alert(1)</script>' }] }) });
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);
});
check('overdue flag remains separate from status and is not calculated from device time', () => {
  assert.match(render(), /В работе/);
  assert.match(render(), /Срок истёк/);
  assert.doesNotMatch(render({ orders: fresh([{ ...order, dueAt: '2000-01-01T00:00:00Z', isOverdue: false }]) }), /Срок истёк/);
});
check('unknown status is neutral and missing assessment has no verdict', () => {
  assert.equal(labels.statusLabel('toString'), 'Неизвестный статус');
  assert.equal(labels.priorityLabel('__proto__'), 'Неизвестный приоритет');
  assert.equal(labels.eventLabel('constructor'), 'Событие наряда');
  const html = render({ orders: fresh([{ ...order, status: 'future_status' }]), selectedOrderId: order.id });
  assert.match(html, /Неизвестный статус/);
  assert.match(html, /Оценка результата в этой панели не загружена/);
  assert.doesNotMatch(html, /ИИ одобрил|ИИ отклонил|0 из 100/);
});
check('queue zero does not mean free and active order is representative only', () => {
  const employee = { id: 'e', label: 'ДЕМО-02', onShift: true, activeOrderId: null, queueCount: 0 };
  assert.equal(model.employeeActivityLabel(employee), 'Занятость не подтверждена');
  assert.equal(model.employeeActivityLabel({ ...employee, activeOrderId: 'a', queueCount: 2 }), 'Есть активный наряд');
  assert.equal(model.employeeActivityLabel({ ...employee, onShift: false, activeOrderId: 'a' }), 'Вне смены');
  const html = render({ employees: fresh([{ ...employee, activeOrderId: order.id, queueCount: 2 }]) });
  assert.match(html, /В очереди: 2/);
  assert.match(html, /может быть одним из нескольких/);
  assert.doesNotMatch(html, /Свободен/);
});
check('fixed UTC+5 dates cross day boundaries and reject missing timezones', () => {
  assert.equal(model.formatPanelTime('2026-10-07T23:15:00Z'), '08.10.2026, 04:15 (UTC+5)');
  assert.equal(model.formatPanelTime('2026-10-08T04:15:00+05:00'), '08.10.2026, 04:15 (UTC+5)');
  assert.equal(model.formatPanelTime('2026-10-07T23:15:00'), 'Время не указано');
  assert.equal(model.formatPanelTime('bad date'), 'Время не указано');
});
check('filters combine without mutating server order or treating overdue as status', () => {
  const second = { ...order, id: 'b', number: '41', isOverdue: false };
  const rows = Object.freeze([second, order]);
  assert.deepEqual(model.filterPanelOrders(rows, '', 'all', false).map((item) => item.number), ['41', '42']);
  assert.deepEqual(model.filterPanelOrders(rows, '  НАСОС ', 'in_progress', true), [order]);
  assert.deepEqual(model.filterPanelOrders(rows, '', 'closed', true), []);
});
check('synthetic watermark is explicit and unsupported features remain unavailable', () => {
  const html = render({ dataOrigin: 'synthetic' });
  assert.match(html, /Синтетические данные/);
  assert.match(html, /Отчёт смены, экспорт, рейтинг и аналитика пока недоступны/);
  assert.doesNotMatch(render(), /демонстрационный набор/);
});
check('form labels, status live regions and order-specific history controls exist', () => {
  const html = render();
  assert.match(html, /role="search"/);
  assert.match(html, /aria-live="polite"/);
  assert.match(html, /aria-label="Показать историю наряда № 42"/);
  assert.match(html, /aria-pressed="false"/);
  assert.match(html, /<label for="[^"]+-search"/);
});

// Strict, no-emit typecheck with read-only dependency/shared resolution.
const options = { target: ts.ScriptTarget.ES2023, module: ts.ModuleKind.ESNext,
  moduleResolution: ts.ModuleResolutionKind.Bundler, jsx: ts.JsxEmit.ReactJSX,
  noEmit: true, strict: true, skipLibCheck: true, noUnusedLocals: true, noUnusedParameters: true,
  noUncheckedSideEffectImports: false, types: [], lib: ['lib.es2023.d.ts', 'lib.dom.d.ts', 'lib.dom.iterable.d.ts'] };
const host = ts.createCompilerHost(options);
host.resolveModuleNames = (names, file) => names.map((name) => {
  if (name === '../shared/ui/types') return { resolvedFileName: join(dependencyRoot, 'src/shared/ui/types.ts'), extension: ts.Extension.Ts };
  return ts.resolveModuleName(name, file, options, host).resolvedModule
    ?? ts.resolveModuleName(name, join(dependencyRoot, 'src/__panel_check__.tsx'), options, host).resolvedModule;
});
const program = ts.createProgram(['PanelScreen.tsx', 'model.ts', 'ru.ts', 'types.ts'].map((file) => join(directory, file)), options, host);
const diagnostics = ts.getPreEmitDiagnostics(program);
if (diagnostics.length) {
  console.error(ts.formatDiagnosticsWithColorAndContext(diagnostics, {
    getCanonicalFileName: (file) => file, getCurrentDirectory: () => directory, getNewLine: () => '\n',
  }));
  process.exitCode = 1;
} else {
  console.log(`PASS strict panel typecheck; ${count} synthetic local unit/SSR checks passed.`);
}
