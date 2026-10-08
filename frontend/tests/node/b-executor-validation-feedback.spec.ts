import { expect, test } from '@playwright/test';
import { createElement } from 'react';
import { sourceModule } from '../support/source';
import { ssrSourceModule } from '../support/ssr-source';
import { deferred } from '../support/synthetic';
import type * as Screen from '../../src/mobile/executor/ExecutorScreen';
import type * as Model from '../../src/mobile/executor/model';
import type { ExecutorDraft, ExecutorIntent, ExecutorOrderViewModel, ExecutorScreenProps } from '../../src/mobile/executor/types';
import type { MutationOutcome, ResourceState } from '../../src/shared/ui/types';

// Synthetic source/handler lifecycle only. Controlled hooks, hosts and promises
// exercise actual component code, not React DOM, a screen reader, an API or Android.
interface Element { type: string | symbol | ((props: Record<string, unknown>) => Element); key: string | null; props: Record<string, unknown> }
interface Effect { dependencies?: readonly unknown[]; cleanup?: () => void }
type Ref = { current: Host | null };
class Host {
  props: Record<string, unknown> = {};
  disabled = false;
  isConnected = true;
  constructor(readonly type: string, readonly focusCalls: Host[], readonly scrollCalls: Host[]) {}
  focus() { this.focusCalls.push(this); }
  scrollIntoView() { this.scrollCalls.push(this); }
}
const model = sourceModule<typeof Model>('src/mobile/executor/model.ts');
const text = (value: unknown): string => Array.isArray(value) ? value.map(text).join('') :
  value && typeof value === 'object' && 'props' in value ? text((value as Element).props.children) :
    typeof value === 'string' || typeof value === 'number' ? String(value) : '';
const ready = <T,>(snapshot: T): ResourceState<T> => ({ snapshot, freshness: 'fresh', loadStatus: 'ready',
  lastConfirmedAt: '2026-10-08T08:00:00Z', error: null, incomplete: false });
const order: ExecutorOrderViewModel = {
  id: 'synthetic-validation-order', number: 'SYNTHETIC-VALIDATION', version: 4, assignmentRevision: 2,
  sectionId: 'synthetic-section', sectionLabel: 'Синтетический участок', equipmentLabel: 'Тестовый насос',
  status: 'in_progress', type: 'planned', priority: 'normal', description: 'Синтетическая работа',
  comment: '', dueAt: '2026-10-08T10:00:00Z', isOverdue: false, beforePhotoIds: ['synthetic-before'],
};
const invalidDraft = (): ExecutorDraft => ({ ...model.emptyExecutorDraft(), workDescription: ' ',
  comment: 'Сохранить комментарий', reason: 'Сохранить причину', afterPhotoIds: ['synthetic-after'],
  materials: [{ rowId: 'remove-me', materialId: '', quantity: '0' },
    { rowId: 'keep-me', materialId: '', quantity: '1e3' }] });

function harness(patch: Partial<ExecutorScreenProps> = {}) {
  let props: ExecutorScreenProps = {
    sessionKey: 'synthetic-validation-session', operationScopeKey: `${order.id}:2`,
    orders: ready([order]), selectedOrderId: order.id,
    dictionaries: ready({ workCodes: [{ id: 'code', code: 'SYNTHETIC', label: 'Тестовая работа' }],
      materials: [{ id: 'material', code: 'SYNTHETIC', label: 'Тестовый материал', unit: 'шт' }] }),
    drafts: { [order.id]: invalidDraft() }, mutation: { status: 'idle', error: null }, pendingIntent: null,
    onSelectOrder() {}, onRefresh() {}, onResolveConflict() {}, onRetry: async () => ({ kind: 'confirmed' }),
    onDraftChange(orderId, draft, assignmentRevision) {
      changes.push({ orderId, draft, assignmentRevision });
      props = { ...props, drafts: { ...props.drafts, [orderId]: draft } }; dirty = true;
    },
    onIntent(intent) { intents.push(intent); const result = deferred<MutationOutcome>(); outcomes.push(result); return result.promise; },
    ...patch,
  };
  const changes: { orderId: string; draft: ExecutorDraft; assignmentRevision: number }[] = [];
  const intents: ExecutorIntent[] = [];
  const outcomes: ReturnType<typeof deferred<MutationOutcome>>[] = [];
  const focusCalls: Host[] = []; const scrollCalls: Host[] = [];
  let hosts = new Map<string, Host>(); let refs = new Map<Ref, Host>();
  let slots: unknown[] = []; let effects: Effect[] = []; let cursor = 0;
  let dirty = true; let alive = true; let generation = 0; let key: string | null = null;
  let layout: (() => void)[] = []; let passive: (() => void)[] = [];
  let lateStateWrites = 0;
  function effect(queue: (() => void)[], callback: () => void | (() => void), dependencies?: readonly unknown[]) {
    const index = cursor++; const previous = effects[index];
    if (previous && dependencies && previous.dependencies && dependencies.length === previous.dependencies.length &&
      dependencies.every((value, i) => Object.is(value, previous.dependencies![i]))) return;
    queue.push(() => { previous?.cleanup?.(); effects[index] = { dependencies, cleanup: callback() || undefined }; });
  }
  const hooks = {
    useId: () => `synthetic-validation-${generation}`,
    useRef: (initial: unknown) => { const index = cursor++; return slots[index] ??= { current: initial }; },
    useState: (initial: unknown) => {
      const index = cursor++; const owner = generation;
      if (!(index in slots)) slots[index] = typeof initial === 'function' ? (initial as () => unknown)() : initial;
      return [slots[index], (next: unknown) => {
        if (!alive || owner !== generation) { lateStateWrites++; return; }
        const value = typeof next === 'function' ? (next as (previous: unknown) => unknown)(slots[index]) : next;
        if (!Object.is(slots[index], value)) { slots[index] = value; dirty = true; }
      }];
    },
    useLayoutEffect: (callback: () => void | (() => void), dependencies?: readonly unknown[]) => effect(layout, callback, dependencies),
    useEffect: (callback: () => void | (() => void), dependencies?: readonly unknown[]) => effect(passive, callback, dependencies),
  };
  const { ExecutorScreen } = ssrSourceModule<typeof Screen>('src/mobile/executor/ExecutorScreen.tsx', {
    react: hooks, './model': model, './executor.css': {},
  });
  function cleanup() {
    for (const effect of effects) effect?.cleanup?.();
    effects = [];
    for (const host of hosts.values()) host.isConnected = false;
    for (const ref of refs.keys()) ref.current = null;
    hosts.clear(); refs.clear();
  }
  function flush() {
    for (let pass = 0; dirty; pass++) {
      if (pass > 20) throw new Error('Synthetic executor did not settle');
      dirty = false;
      const selection = ExecutorScreen(props) as unknown as Element;
      if (selection.key !== key) { cleanup(); slots = []; generation++; key = selection.key; }
      cursor = 0; layout = []; passive = [];
      const tree = (selection.type as unknown as (props: ExecutorScreenProps) => Element)(props);
      if (dirty) continue; // Render-phase adjustment settles before the synthetic commit.
      const next = new Map<string, Host>(); const nextRefs = new Map<Ref, Host>();
      function visit(value: unknown, path: string, disabled = false) {
        if (Array.isArray(value)) { value.forEach((child, index) => visit(child, `${path}/${(child as Element | null)?.key ?? index}`, disabled)); return; }
        if (!value || typeof value !== 'object' || !('type' in value)) return;
        const element = value as Element;
        if (typeof element.type === 'function') { visit(element.type(element.props), `${path}/component`, disabled); return; }
        if (typeof element.type === 'symbol') { visit(element.props.children, `${path}/fragment`, disabled); return; }
        const host = hosts.get(path)?.type === element.type ? hosts.get(path)! : new Host(element.type, focusCalls, scrollCalls);
        host.props = element.props; host.disabled = disabled || Boolean(element.props.disabled); next.set(path, host);
        const ref = element.props.ref as Ref | undefined;
        if (ref) { ref.current = host; nextRefs.set(ref, host); }
        visit(element.props.children, `${path}/children`, disabled || element.type === 'fieldset' && Boolean(element.props.disabled));
      }
      visit(tree, 'root');
      for (const [path, host] of hosts) if (next.get(path) !== host) host.isConnected = false;
      for (const ref of refs.keys()) if (!nextRefs.has(ref)) ref.current = null;
      hosts = next; refs = nextRefs;
      for (const run of layout) run();
      for (const run of passive) run();
    }
  }
  const findAll = (predicate: (host: Host) => boolean) => [...hosts.values()].filter(predicate);
  const find = (predicate: (host: Host) => boolean) => {
    const matches = findAll(predicate); if (matches.length !== 1) throw new Error(`Expected one synthetic host, found ${matches.length}`); return matches[0];
  };
  flush();
  return {
    changes, intents, outcomes, focusCalls, scrollCalls, flush, findAll,
    get props() { return props; }, get lateStateWrites() { return lateStateWrites; },
    get form() { return find(host => host.type === 'form'); },
    get alerts() { return findAll(host => host.props.role === 'alert'); },
    get reason() { return find(host => host.type === 'textarea' && String(host.props.id).endsWith('-reason')); },
    get reasonRegion() { return findAll(host => String(host.props.id).endsWith('-reason-error'))[0]; },
    field(suffix: string) { return find(host => ['input', 'textarea', 'select'].includes(host.type) && String(host.props.id).endsWith(suffix)); },
    button(label: string) { return find(host => host.type === 'button' && (host.props['aria-label'] ?? text(host.props.children)) === label); },
    update(value: Partial<ExecutorScreenProps>) { props = { ...props, ...value }; dirty = true; flush(); },
    change(host: Host, value: string) { (host.props.onChange as (event: unknown) => void)({ target: { value } }); flush(); },
    click(host: Host) { (host.props.onClick as () => void)(); flush(); },
    invoke(callback: () => void) { callback(); flush(); },
    submit(host: Host, count = 1) { for (let i = 0; i < count; i++) (host.props.onSubmit as (event: unknown) => void)({ preventDefault() {} }); flush(); },
    async settle() { for (let i = 0; i < 5; i++) await Promise.resolve(); flush(); },
    unmount() { alive = false; cleanup(); },
  };
}

for (const action of ['pause', 'reject'] as const) {
  for (const reason of ['', '  \n\t  ']) {
    test(`B executor validation: ${action} ${reason ? 'whitespace' : 'empty'} reason has one stable described alert and sends no intent`, () => {
      const view = harness({ orders: ready([{ ...order, status: action === 'pause' ? 'in_progress' : 'issued' }]),
        drafts: { [order.id]: { ...model.emptyExecutorDraft(), reason } } });
      view.click(view.button(action === 'pause' ? 'Приостановить' : 'Отклонить'));
      const region = view.reasonRegion;
      view.submit(view.form, 2);
      expect(view.intents).toEqual([]); expect(view.changes).toEqual([]);
      expect(view.reason.props['aria-invalid']).toBe(true);
      expect(view.reason.props['aria-describedby']).toBe(view.reasonRegion?.props.id);
      expect(text(view.reasonRegion?.props.children)).toBe('Укажите причину: от 1 до 2000 символов.');
      expect(view.reasonRegion?.props.role).toBe('alert');
      expect(view.reasonRegion?.props['aria-atomic']).toBe('true');
      expect(view.reasonRegion).toBe(region);
      expect(view.alerts).toEqual([region]);
      expect(view.focusCalls).toEqual([]); expect(view.scrollCalls).toEqual([]);
      view.update({ orders: { ...view.props.orders, loadStatus: 'loading', freshness: 'stale' } });
      expect(view.reasonRegion).toBe(region); expect(view.alerts).toEqual([region]);
      expect(view.focusCalls).toEqual([]); expect(view.scrollCalls).toEqual([]);
      view.unmount();
    });
  }
  test(`B executor validation: corrected ${action} reason sends once with original scope/version and clears its alert`, async () => {
    const view = harness({ orders: ready([{ ...order, status: action === 'pause' ? 'in_progress' : 'issued' }]),
      drafts: { [order.id]: model.emptyExecutorDraft() } });
    view.click(view.button(action === 'pause' ? 'Приостановить' : 'Отклонить'));
    view.submit(view.form); const region = view.reasonRegion;
    view.change(view.reason, '  Синтетическая причина  ');
    view.submit(view.form, 2);
    expect(view.intents).toEqual([{ orderId: order.id, expectedVersion: 4, expectedAssignmentRevision: 2,
      action, payload: { reason: 'Синтетическая причина' } }]);
    expect(view.reason.props['aria-invalid']).toBe(false);
    expect(view.reason.props['aria-describedby']).toBeUndefined();
    expect(view.reasonRegion).toBe(region); expect(text(region?.props.children)).toBe('');
    expect(view.reason.disabled).toBe(true);
    view.outcomes[0].resolve({ kind: 'confirmed' }); await view.settle();
    expect(view.intents).toHaveLength(1);
    expect(view.findAll(host => host.props.role === 'status').map(host => text(host.props.children)).join(' ')).toContain('Действие подтверждено сервером.');
    view.unmount();
  });
}

test('B executor validation: reason error is cleared on cancel and never duplicated in result-form alerts', () => {
  const view = harness(); view.click(view.button('Приостановить')); view.change(view.reason, ''); view.submit(view.form);
  expect(view.alerts).toHaveLength(1);
  view.click(view.button('Вернуться без отправки'));
  expect(view.reasonRegion).toBeUndefined(); expect(view.alerts).toEqual([]);
  view.submit(view.form);
  expect(view.alerts).toHaveLength(1); expect(text(view.alerts[0].props.children)).not.toContain('Укажите причину:');
  expect(view.intents).toEqual([]); view.unmount();
});

test('B executor validation: removing an invalid row prunes only that row errors and preserves other errors and draft values', () => {
  const view = harness(); view.submit(view.form);
  expect(view.intents).toEqual([]); expect(view.alerts).toHaveLength(1);
  expect(view.findAll(host => host.type === 'li')).toHaveLength(5);
  const before = structuredClone(view.props.drafts[order.id]);
  view.click(view.button('Убрать материал 1'));
  expect(view.changes).toHaveLength(1);
  expect(view.changes[0]).toEqual({ orderId: order.id, assignmentRevision: 2,
    draft: { ...before, materials: [before.materials[1]] } });
  expect(view.findAll(host => host.type === 'li').map(host => text(host.props.children))).toEqual([
    'Опишите выполненные работы.', 'Выберите материал из справочника.',
    'Введите количество больше 0, до 999999999, не более трёх знаков после запятой.',
  ]);
  expect(view.field('-work').props['aria-invalid']).toBe(true);
  expect(view.field('-keep-me-material').props['aria-invalid']).toBe(true);
  expect(view.field('-keep-me-quantity').props.value).toBe('1e3');
  expect(view.field('-comment').props.value).toBe(before.comment);
  expect(view.intents).toEqual([]); expect(view.scrollCalls).toEqual([]); view.unmount();
});

test('B executor validation: removing the only invalid row empties the result alert without submitting', () => {
  const draft = { ...invalidDraft(), workDescription: 'Синтетически выполнено', materials: invalidDraft().materials.slice(0, 1) };
  const view = harness({ drafts: { [order.id]: draft } }); view.submit(view.form);
  expect(view.alerts).toHaveLength(1); view.click(view.button('Убрать материал 1'));
  expect(view.alerts).toEqual([]); expect(view.props.drafts[order.id]).toEqual({ ...draft, materials: [] });
  expect(view.intents).toEqual([]); expect(view.scrollCalls).toEqual([]); view.unmount();
});

test('B executor validation: saved row removal uses the latest draft and repeated removal is inert', () => {
  const view = harness(); view.submit(view.form);
  const remove = view.button('Убрать материал 1').props.onClick as () => void;
  view.change(view.field('-keep-me-quantity'), '2,5');
  view.invoke(remove);
  expect(view.props.drafts[order.id].materials).toEqual([{ rowId: 'keep-me', materialId: '', quantity: '2,5' }]);
  const after = structuredClone(view.props.drafts[order.id]); const changes = view.changes.length;
  view.invoke(remove);
  expect(view.changes).toHaveLength(changes); expect(view.props.drafts[order.id]).toEqual(after);
  expect(view.intents).toEqual([]); view.unmount();
});

for (const status of ['pending', 'unknown_result', 'conflict'] as const) {
  test(`B executor validation: ${status} refuses saved removal without pruning errors or changing values`, () => {
    const view = harness(); view.submit(view.form); const remove = view.button('Убрать материал 1').props.onClick as () => void;
    const before = structuredClone(view.props.drafts); const messages = view.findAll(host => host.type === 'li').map(host => text(host.props.children));
    view.update({ mutation: { status, error: null } }); view.invoke(remove);
    expect(view.changes).toEqual([]); expect(view.props.drafts).toEqual(before);
    expect(view.findAll(host => host.type === 'li').map(host => text(host.props.children))).toEqual(messages);
    expect(view.intents).toEqual([]); view.unmount();
  });
}

test('B executor validation: a synchronous command latch rejects old removal before the pending commit', () => {
  const view = harness(); view.submit(view.form); const remove = view.button('Убрать материал 1').props.onClick as () => void;
  view.click(view.button('Приостановить'));
  // The retained draft already has a valid reason. Replay the old callback before render.
  const form = view.form; (form.props.onSubmit as (event: unknown) => void)({ preventDefault() {} });
  view.invoke(remove);
  expect(view.intents).toHaveLength(1); expect(view.changes).toEqual([]);
  expect(view.props.drafts[order.id].materials).toHaveLength(2); view.unmount();
});

for (const change of ['order', 'assignment', 'session', 'unmount'] as const) {
  test(`B executor validation: ${change} change fences retained row callbacks and validation feedback`, () => {
    const view = harness(); view.submit(view.form); const remove = view.button('Убрать материал 1').props.onClick as () => void;
    if (change === 'order') view.update({ selectedOrderId: 'synthetic-other', operationScopeKey: 'synthetic-other:2',
      orders: ready([{ ...order, id: 'synthetic-other' }]), drafts: { 'synthetic-other': invalidDraft() } });
    if (change === 'assignment') view.update({ operationScopeKey: `${order.id}:3`, orders: ready([{ ...order, assignmentRevision: 3 }]) });
    if (change === 'session') view.update({ sessionKey: 'synthetic-new-session' });
    if (change === 'unmount') view.unmount();
    if (change !== 'unmount') view.submit(view.form);
    const before = structuredClone(view.props.drafts); const errors = view.findAll(host => host.type === 'li').map(host => text(host.props.children));
    view.invoke(remove);
    expect(view.changes).toEqual([]); expect(view.props.drafts).toEqual(before);
    expect(view.findAll(host => host.type === 'li').map(host => text(host.props.children))).toEqual(errors);
    expect(view.intents).toEqual([]); expect(view.lateStateWrites).toBe(0); view.unmount();
  });
}

test('B executor validation: before-photo rendering and quiet polling preserve visible validation without scrolling', () => {
  const rendered: ExecutorOrderViewModel[] = [];
  const view = harness({ renderBeforePhotos: selected => { rendered.push(selected); return createElement('p', { id: 'synthetic-before-slot' }, 'Синтетическое фото до'); } });
  view.submit(view.form); const messages = view.findAll(host => host.type === 'li').map(host => text(host.props.children));
  view.update({ orders: { ...view.props.orders, loadStatus: 'loading', freshness: 'stale' } });
  expect(view.findAll(host => host.props.id === 'synthetic-before-slot')).toHaveLength(1);
  expect(rendered.every(selected => selected.id === order.id && selected.assignmentRevision === 2)).toBe(true);
  expect(view.findAll(host => host.type === 'li').map(host => text(host.props.children))).toEqual(messages);
  expect(view.button('Приостановить').disabled).toBe(true);
  expect(view.focusCalls).toEqual([]); expect(view.scrollCalls).toEqual([]); expect(view.intents).toEqual([]); view.unmount();
});

test('B executor validation: a parent that declines removal keeps that row invalid and its errors visible', () => {
  const requested: ExecutorDraft[] = [];
  const view = harness({ onDraftChange(_orderId, draft) { requested.push(draft); } });
  view.submit(view.form); const before = structuredClone(view.props.drafts);
  view.click(view.button('Убрать материал 1'));
  expect(requested).toHaveLength(1); expect(requested[0].materials.map(row => row.rowId)).toEqual(['keep-me']);
  expect(view.props.drafts).toEqual(before);
  expect(view.findAll(host => host.type === 'li')).toHaveLength(5);
  expect(view.field('-remove-me-material').props['aria-invalid']).toBe(true);
  expect(view.field('-remove-me-quantity').props['aria-invalid']).toBe(true);
  // An unrelated controlled update is not confirmation that the row was removed.
  view.update({ drafts: { [order.id]: { ...before[order.id], comment: 'Синтетическое обновление комментария' } } });
  expect(view.findAll(host => host.type === 'li')).toHaveLength(5);
  expect(view.field('-remove-me-material').props['aria-describedby']).toBeDefined();
  expect(view.intents).toEqual([]); expect(view.scrollCalls).toEqual([]); view.unmount();
});

test('B executor validation: deferred parent removal prunes only after the controlled draft confirms that row absent', () => {
  const requested: ExecutorDraft[] = [];
  const view = harness({ onDraftChange(_orderId, draft) { requested.push(draft); } });
  view.submit(view.form); view.click(view.button('Убрать материал 1'));
  expect(view.findAll(host => host.type === 'li')).toHaveLength(5);
  expect(view.field('-remove-me-quantity').props['aria-invalid']).toBe(true);
  view.submit(view.form); // A second invalid submit must not lose the pending controlled confirmation.
  expect(view.findAll(host => host.type === 'li')).toHaveLength(5);
  view.update({ drafts: { [order.id]: requested[0] } });
  expect(view.findAll(host => host.type === 'li').map(host => text(host.props.children))).toEqual([
    'Опишите выполненные работы.', 'Выберите материал из справочника.',
    'Введите количество больше 0, до 999999999, не более трёх знаков после запятой.',
  ]);
  expect(view.field('-keep-me-material').props['aria-invalid']).toBe(true);
  expect(view.props.drafts[order.id]).toEqual(requested[0]);
  expect(view.intents).toEqual([]); expect(view.scrollCalls).toEqual([]); view.unmount();
});
