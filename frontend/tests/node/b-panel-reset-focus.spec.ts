import { expect, test } from '@playwright/test';
import { sourceModule } from '../support/source';
import { ssrSourceModule } from '../support/ssr-source';
import type * as Screen from '../../src/panel/PanelScreen';
import type * as Model from '../../src/panel/model';
import type * as Labels from '../../src/panel/ru';
import type { PanelOrder, PanelScreenProps } from '../../src/panel/types';
import type { ResourceState } from '../../src/shared/ui/types';

// Source-only hook/host simulation: real component handlers and effects, with
// explicit commit/removal and focus ports. Not React DOM, browser or AT proof.
interface Element { type: string | symbol | ((props: Record<string, unknown>) => Element); key: string | null; props: Record<string, unknown> }
interface Effect { dependencies?: readonly unknown[]; cleanup?: () => void }
type Ref = { current: Host | null };
class Host {
  isConnected = true;
  disabled = false;
  props: Record<string, unknown> = {};
  focusOptions: FocusOptions | undefined;
  focusAttempts = 0;
  constructor(readonly type: string, readonly ownerDocument: { activeElement: Host | null; body: Host | null }, readonly focused: Host[], readonly blockingAncestor: () => 'hidden' | 'inert' | null) {}
  closest(selector: string) {
    if (selector !== '[hidden], [inert]') throw new Error(`Unsupported synthetic selector: ${selector}`);
    return this.blockingAncestor() ? this : null;
  }
  focus(options?: FocusOptions) {
    this.focusAttempts += 1;
    if (!this.isConnected || this.disabled || this.blockingAncestor()) return;
    this.ownerDocument.activeElement = this;
    this.focusOptions = options;
    this.focused.push(this);
  }
}
const text = (value: unknown): string => Array.isArray(value) ? value.map(text).join('') :
  value && typeof value === 'object' && 'props' in value ? text((value as Element).props.children) :
    typeof value === 'string' || typeof value === 'number' ? String(value) : '';
const ready = <T,>(snapshot: T): ResourceState<T> => ({ snapshot, freshness: 'fresh', loadStatus: 'ready', error: null,
  lastConfirmedAt: '2026-10-08T08:00:00Z', incomplete: false });
const order: PanelOrder = { id: 'synthetic-first', number: 'SYNTHETIC-1', title: 'Тестовый наряд', sectionLabel: 'Участок',
  equipmentLabel: 'Насос', executorLabel: 'Тестовый исполнитель', status: 'accepted', priority: 'normal',
  dueAt: '2026-10-08T07:00:00Z', isOverdue: true, version: 1 };

function harness(patch: Partial<PanelScreenProps> = {}) {
  const document = { activeElement: null as Host | null, body: null as Host | null };
  const focusCalls: Host[] = [];
  document.body = new Host('body', document, focusCalls, () => null);
  document.activeElement = document.body;
  let blockingAncestor: 'hidden' | 'inert' | null = null;
  let alive = true;
  let dirty = true;
  let cursor = 0;
  const slots: unknown[] = [];
  const effects: Effect[] = [];
  let layout: (() => void)[] = [];
  let passive: (() => void)[] = [];
  let hosts = new Map<string, Host>();
  let refs = new Map<Ref, Host>();
  const selections: string[] = [];
  const historyRefreshes: string[] = [];
  let refreshes = 0;
  let props: PanelScreenProps = { orders: ready([order]), selectedOrderId: null,
    onSelectOrder: id => selections.push(id), onRefresh: () => { refreshes += 1; },
    onRefreshHistory: id => historyRefreshes.push(id), ...patch };
  function effect(queue: (() => void)[], callback: () => void | (() => void), dependencies?: readonly unknown[]) {
    const index = cursor++;
    const previous = effects[index];
    if (previous && dependencies && previous.dependencies && dependencies.length === previous.dependencies.length && dependencies.every((value, i) => Object.is(value, previous.dependencies![i]))) return;
    queue.push(() => { previous?.cleanup?.(); effects[index] = { dependencies, cleanup: callback() || undefined }; });
  }
  const hooks = {
    useId: () => 'synthetic-panel',
    useRef: (initial: unknown) => { const index = cursor++; return slots[index] ??= { current: initial }; },
    useState: (initial: unknown) => {
      const index = cursor++;
      if (!(index in slots)) slots[index] = initial;
      return [slots[index], (value: unknown) => { if (alive && !Object.is(slots[index], value)) { slots[index] = value; dirty = true; } }];
    },
    useLayoutEffect: (callback: () => void | (() => void), dependencies?: readonly unknown[]) => effect(layout, callback, dependencies),
    useEffect: (callback: () => void | (() => void), dependencies?: readonly unknown[]) => effect(passive, callback, dependencies),
  };
  const { PanelScreen } = ssrSourceModule<typeof Screen>('src/panel/PanelScreen.tsx', {
    react: hooks, './panel.css': {}, './model': sourceModule<typeof Model>('src/panel/model.ts'), './ru': sourceModule<typeof Labels>('src/panel/ru.ts'),
  });
  const disconnect = (host: Host) => { host.isConnected = false; if (document.activeElement === host) document.activeElement = document.body; };
  function flush() {
    if (!alive) return;
    for (let pass = 0; dirty; pass += 1) {
      if (pass > 20) throw new Error('Synthetic render did not settle');
      dirty = false; cursor = 0; layout = []; passive = [];
      const tree = PanelScreen(props);
      const next = new Map<string, Host>();
      const nextRefs = new Map<Ref, Host>();
      function visit(value: unknown, path: string) {
        if (Array.isArray(value)) { value.forEach((child, index) => visit(child, `${path}/${(child as Element | null)?.key ?? index}`)); return; }
        if (!value || typeof value !== 'object' || !('type' in value)) return;
        const element = value as Element;
        if (typeof element.type === 'function') { visit(element.type(element.props), `${path}/component`); return; }
        if (typeof element.type === 'symbol') { visit(element.props.children, `${path}/fragment`); return; }
        const previous = hosts.get(path);
        const host = previous?.type === element.type ? previous : new Host(element.type, document, focusCalls, () => blockingAncestor);
        if (previous && previous !== host) disconnect(previous);
        host.props = element.props; host.disabled = Boolean(element.props.disabled);
        next.set(path, host);
        const ref = element.props.ref as Ref | undefined;
        if (ref) { ref.current = host; nextRefs.set(ref, host); }
        visit(element.props.children, `${path}/children`);
      }
      visit(tree, 'root');
      for (const [path, host] of hosts) if (!next.has(path)) disconnect(host);
      for (const ref of refs.keys()) if (!nextRefs.has(ref)) ref.current = null;
      hosts = next; refs = nextRefs;
      for (const run of layout) run();
      for (const run of passive) run();
    }
  }
  const find = (predicate: (host: Host) => boolean): Host => { const host = [...hosts.values()].find(predicate); if (!host) throw new Error('Synthetic host not found'); return host; };
  const button = (label: string) => find(host => host.type === 'button' && text(host.props.children) === label);
  flush();
  return {
    document, focusCalls, selections, historyRefreshes, flush, button,
    get refreshes() { return refreshes; },
    get search() { return find(host => host.props.id === 'synthetic-panel-search'); },
    get status() { return find(host => host.props.id === 'synthetic-panel-status'); },
    get overdue() { return find(host => host.props.id === 'synthetic-panel-overdue'); },
    get history() { return find(host => host.props.id === 'synthetic-panel-history'); },
    get reset() { return button('Сбросить фильтры'); },
    get hasReset() { return [...hosts.values()].some(host => host.type === 'button' && text(host.props.children) === 'Сбросить фильтры'); },
    get content() { return [...hosts.values()].filter(host => host.type === 'p' || host.type === 'h3').map(host => text(host.props.children)).join('\n'); },
    update(value: Partial<PanelScreenProps>) { props = { ...props, ...value }; dirty = true; flush(); },
    change(host: Host, value: string | boolean) { (host.props.onChange as (event: unknown) => void)({ target: { value, checked: value } }); flush(); },
    click(host: Host, focus = true, beforeCommit?: () => void) {
      if (host.disabled) return;
      if (focus) host.focus();
      (host.props.onClick as (event: unknown) => void)({ currentTarget: host });
      beforeCommit?.(); flush();
    },
    setBlockingAncestor(value: 'hidden' | 'inert' | null) { blockingAncestor = value; dirty = true; },
    outside() { const host = new Host('input', document, focusCalls, () => null); host.focus(); return host; },
    unmount() { alive = false; for (const effect of effects) effect?.cleanup?.(); for (const host of hosts.values()) disconnect(host); for (const ref of refs.keys()) ref.current = null; hosts.clear(); refs.clear(); },
  };
}

test('B panel reset focus: focused reset removal returns focus to search and clears all filters', () => {
  const view = harness();
  view.change(view.search, 'насос'); view.change(view.status, 'accepted'); view.change(view.overdue, true);
  const search = view.search;
  const reset = view.reset;
  view.click(reset);
  expect(reset.isConnected).toBe(false); expect(view.hasReset).toBe(false);
  expect(view.search).toBe(search);
  expect(view.search.props.value).toBe(''); expect(view.status.props.value).toBe('all'); expect(view.overdue.props.checked).toBe(false);
  expect(view.document.activeElement === view.search, 'removed reset must restore search focus rather than leave the body active').toBe(true);
  expect(view.search.focusOptions).toEqual({ preventScroll: true });
  expect(view.focusCalls).toEqual([reset, search]);
  expect(view.selections).toEqual([]); expect(view.refreshes).toBe(0); expect(view.historyRefreshes).toEqual([]);
  view.unmount();
});

for (const filter of ['query', 'status', 'overdue'] as const) {
  test(`B panel reset focus: repeated ${filter}-only resets restore the same search once per activation`, () => {
    const view = harness();
    const search = view.search;
    for (let cycle = 0; cycle < 3; cycle += 1) {
      if (filter === 'query') view.change(view.search, 'нет совпадений');
      if (filter === 'status') view.change(view.status, 'paused');
      if (filter === 'overdue') view.change(view.overdue, true);
      const reset = view.reset;
      view.click(reset);
      expect(view.document.activeElement).toBe(search); expect(view.hasReset).toBe(false);
      expect(view.focusCalls.slice(-2)).toEqual([reset, search]);
    }
    expect(search.focusAttempts).toBe(3);
    view.unmount();
  });
}

test('B panel reset focus: mount, filter edits and repeated quiet polling never focus the search', () => {
  const view = harness();
  const search = view.search;
  expect(view.focusCalls).toEqual([]);
  view.change(search, 'насос'); view.change(view.status, 'accepted'); view.change(view.overdue, true);
  const status = view.status; status.focus();
  const before = view.content;
  for (let cycle = 0; cycle < 3; cycle += 1) {
    view.update({ orders: { ...ready([order]), loadStatus: 'loading', freshness: 'stale' } });
    expect(view.content).toBe(before); expect(view.button('Обновить данные').disabled).toBe(true);
    view.update({ orders: ready([order]) });
    expect(view.content).toBe(before); expect(view.button('Обновить данные').disabled).toBe(false);
    expect(view.search).toBe(search); expect(view.status).toBe(status); expect(view.document.activeElement).toBe(status);
    expect(view.search.props.value).toBe('насос'); expect(view.status.props.value).toBe('accepted'); expect(view.overdue.props.checked).toBe(true);
  }
  view.change(search, ''); view.change(view.status, 'all'); view.change(view.overdue, false);
  expect(view.hasReset).toBe(false); expect(view.document.activeElement).toBe(status);
  expect(search.focusAttempts).toBe(0); expect(view.focusCalls).toEqual([status]);
  view.unmount();
});

test('B panel reset focus: unfocused activation clears filters without taking focus', () => {
  const view = harness();
  view.change(view.search, 'насос');
  const outside = view.outside();
  view.click(view.reset, false);
  expect(view.hasReset).toBe(false); expect(view.document.activeElement).toBe(outside);
  expect(view.search.focusAttempts).toBe(0); expect(view.focusCalls).toEqual([outside]);
  view.unmount();
});

for (const destination of ['status', 'outside'] as const) {
  test(`B panel reset focus: a newer focus move to ${destination} wins over reset and later polls`, () => {
    const view = harness();
    view.change(view.search, 'насос');
    let target: Host | undefined;
    view.click(view.reset, true, () => {
      if (destination === 'status') { target = view.status; target.focus(); }
      else target = view.outside();
    });
    expect(view.document.activeElement).toBe(target); expect(view.search.focusAttempts).toBe(0);
    view.update({ orders: ready([{ ...order, version: 2 }]) });
    expect(view.document.activeElement).toBe(target); expect(view.search.focusAttempts).toBe(0);
    view.unmount();
  });
}

for (const access of ['forbidden', 'unauthenticated'] as const) {
  test(`B panel reset focus: ${access} during reset discards restoration even after access returns`, () => {
    const view = harness();
    view.change(view.search, 'насос');
    const search = view.search; const reset = view.reset;
    view.click(reset, true, () => view.update({ access }));
    expect(search.isConnected).toBe(false); expect(search.focusAttempts).toBe(0);
    expect(view.content).not.toContain(order.title);
    view.update({ access: 'allowed' });
    expect(view.search.focusAttempts).toBe(0); expect(view.focusCalls).toEqual([reset]);
    expect(view.hasReset).toBe(false);
    view.unmount();
  });
}

for (const ancestor of ['hidden', 'inert'] as const) {
  test(`B panel reset focus: ${ancestor} navigation consumes the request without later refocusing`, () => {
    const view = harness();
    view.change(view.search, 'насос');
    const search = view.search; const reset = view.reset;
    view.click(reset, true, () => view.setBlockingAncestor(ancestor));
    expect(search.focusAttempts).toBe(0); expect(view.focusCalls).toEqual([reset]);
    view.setBlockingAncestor(null); view.flush();
    expect(search.focusAttempts).toBe(0); expect(view.document.activeElement).toBe(view.document.body);
    view.unmount();
  });
}

test('B panel reset focus: a completed reset cannot replay restoration during later polling', () => {
  const view = harness();
  view.change(view.search, 'насос'); view.click(view.reset);
  const search = view.search;
  expect(search.focusAttempts).toBe(1);
  view.outside(); view.document.activeElement = view.document.body;
  view.update({ orders: { ...ready([order]), loadStatus: 'loading', freshness: 'stale' } });
  view.update({ orders: ready([order]) });
  expect(search.focusAttempts).toBe(1); expect(view.document.activeElement).toBe(view.document.body);
  view.unmount();
});

test('B panel reset focus: unmount before the reset commit has no deferred focus work', () => {
  const view = harness();
  view.change(view.search, 'насос');
  const search = view.search; const reset = view.reset;
  view.click(reset, true, () => view.unmount());
  view.flush();
  expect(search.isConnected).toBe(false); expect(search.focusAttempts).toBe(0); expect(view.focusCalls).toEqual([reset]);
});

test('B panel reset focus: a newer filter keeps reset mounted and consumes the old request', () => {
  const view = harness();
  view.change(view.search, 'насос');
  const reset = view.reset;
  view.click(reset, true, () => view.change(view.status, 'paused'));
  expect(reset.isConnected).toBe(true); expect(view.document.activeElement).toBe(reset);
  expect(view.search.focusAttempts).toBe(0);
  view.change(view.status, 'all'); view.update({ orders: ready([order]) });
  expect(view.hasReset).toBe(false); expect(view.search.focusAttempts).toBe(0);
  view.unmount();
});

test('B panel reset focus: history navigation takes priority over a pending reset', () => {
  const view = harness();
  view.change(view.search, 'насос');
  const reset = view.reset;
  view.click(reset, true, () => view.update({ selectedOrderId: order.id }));
  expect(view.document.activeElement).toBe(view.history); expect(view.search.focusAttempts).toBe(0);
  expect(view.focusCalls).toEqual([reset, view.history]);
  const history = view.history;
  view.update({ orders: { ...ready([order]), loadStatus: 'loading', freshness: 'stale' } });
  expect(view.history).toBe(history); expect(view.focusCalls).toEqual([reset, history]);
  view.unmount();
});

test('B panel reset focus: resetting with unchanged history selection preserves existing history handlers', () => {
  const view = harness({ selectedOrderId: order.id, history: ready({ orderId: order.id, events: [] }) });
  expect(view.focusCalls).toEqual([]);
  view.change(view.search, 'насос'); view.click(view.reset);
  expect(view.document.activeElement).toBe(view.search);
  view.click(view.button('История наряда'));
  expect(view.document.activeElement).toBe(view.history); expect(view.selections).toEqual([order.id]);
  view.click(view.button('Обновить историю')); expect(view.historyRefreshes).toEqual([order.id]);
  view.click(view.button('Обновить данные')); expect(view.refreshes).toBe(1);
  view.update({ history: { ...ready({ orderId: order.id, events: [] }), loadStatus: 'loading', freshness: 'stale' } });
  expect(view.button('Обновить историю').disabled).toBe(true);
  expect(view.content).toContain('В загруженной истории событий нет.');
  view.unmount();
});

test('B panel reset focus: current list props and newest callbacks remain observable after reset', () => {
  const view = harness();
  view.change(view.search, 'несуществующий наряд');
  const changed = { ...order, id: 'synthetic-new', number: 'SYNTHETIC-2', title: 'Новая работа', status: 'paused', version: 2, isOverdue: false };
  const selected: string[] = [];
  let refreshed = 0;
  view.update({ orders: ready([changed]), onSelectOrder: id => selected.push(id), onRefresh: () => { refreshed += 1; } });
  expect(view.content).not.toContain(changed.title);
  view.click(view.reset);
  expect(view.content).toContain(changed.title); expect(view.content).not.toContain(order.title);
  view.click(view.button('История наряда')); expect(selected).toEqual([changed.id]); expect(view.selections).toEqual([]);
  view.click(view.button('Обновить данные')); expect(refreshed).toBe(1); expect(view.refreshes).toBe(0);
  view.unmount();
});
