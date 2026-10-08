import { expect, test } from '@playwright/test';
import { ssrSourceModule } from '../support/ssr-source';
import { sourceModule } from '../support/source';
import { deferred } from '../support/synthetic';
import type * as Picker from '../../src/pwa/PhotoPicker';
import type * as Preparation from '../../src/pwa/photoPreparation';
import type { PhotoPickerProps } from '../../src/pwa/PhotoPicker';
import type { PreparedPhoto } from '../../src/pwa/photoPreparation';

// Synthetic hook/host lifecycle only. The real component handlers and effects run
// with controlled promises and focus ports; this is not React DOM, browser,
// screen-reader, camera, upload or physical-device acceptance.
interface Element { type: string | ((props: PhotoPickerProps) => Element); key: string | null; props: Record<string, unknown> }
interface Effect { dependencies?: readonly unknown[]; cleanup?: () => void }
type Ref = { current: Host | null };
class Host {
  isConnected = true;
  disabled = false;
  props: Record<string, unknown> = {};
  focusOptions: FocusOptions | undefined;
  constructor(readonly type: string, readonly ownerDocument: { activeElement: Host | null; body: Host | null }, readonly focused: Host[]) {}
  focus(options?: FocusOptions) {
    if (!this.isConnected || this.disabled) return;
    this.ownerDocument.activeElement = this;
    this.focusOptions = options;
    this.focused.push(this);
  }
}
const preparation = sourceModule<typeof Preparation>('src/pwa/photoPreparation.ts');
const activity = sourceModule<typeof import('../../src/pwa/preparationActivity')>('src/pwa/preparationActivity.ts');
const text = (value: unknown): string => Array.isArray(value) ? value.map(text).join('') :
  value && typeof value === 'object' && 'props' in value ? text((value as Element).props.children) :
    typeof value === 'string' || typeof value === 'number' ? String(value) : '';
const photo = (id: string): PreparedPhoto => ({ id, file: new File(['synthetic'], `${id}.jpg`, { type: 'image/jpeg' }), originalName: `${id}.jpg`, originalBytes: 9, width: 1, height: 1, preparedAt: '2026-10-08T05:00:00Z' });

function harness(patch: Partial<PhotoPickerProps> = {}) {
  const document = { activeElement: null as Host | null, body: null as Host | null };
  const focusCalls: Host[] = [];
  document.body = new Host('body', document, focusCalls);
  document.activeElement = document.body;
  let hosts = new Map<string, Host>();
  let refs = new Map<Ref, Host>();
  let slots: unknown[] = [];
  let effects: Effect[] = [];
  let cursor = 0;
  let dirty = true;
  let alive = true;
  let key: string | null = null;
  let generation = 0;
  let layout: (() => void)[] = [];
  let passive: (() => void)[] = [];
  let lateStateWrites = 0;
  const busy: boolean[] = [];
  const changes: PreparedPhoto[][] = [];
  const preparations: { file: File; signal: AbortSignal; result: ReturnType<typeof deferred<PreparedPhoto>> }[] = [];
  let props: PhotoPickerProps = { contextKey: 'synthetic-session:order:revision', phase: 'after', value: [],
    onChange: value => { changes.push(value); props = { ...props, value }; dirty = true; },
    onBusyChange: value => busy.push(value), ...patch };
  function effect(queue: (() => void)[], callback: () => void | (() => void), dependencies?: readonly unknown[]) {
    const index = cursor++;
    const previous = effects[index];
    if (previous && dependencies && previous.dependencies && dependencies.length === previous.dependencies.length && dependencies.every((value, i) => Object.is(value, previous.dependencies![i]))) return;
    queue.push(() => { previous?.cleanup?.(); effects[index] = { dependencies, cleanup: callback() || undefined }; });
  }
  const hooks = {
    useId: () => 'synthetic-picker',
    useRef: (initial: unknown) => { const index = cursor++; return slots[index] ??= { current: initial }; },
    useState: (initial: unknown) => {
      const index = cursor++;
      const owner = generation;
      if (!(index in slots)) slots[index] = initial;
      return [slots[index], (value: unknown) => {
        if (!alive || owner !== generation) { lateStateWrites += 1; return; }
        if (!Object.is(slots[index], value)) { slots[index] = value; dirty = true; }
      }];
    },
    useLayoutEffect: (callback: () => void | (() => void), dependencies?: readonly unknown[]) => effect(layout, callback, dependencies),
    useEffect: (callback: () => void | (() => void), dependencies?: readonly unknown[]) => effect(passive, callback, dependencies),
  };
  const { PhotoPicker } = ssrSourceModule<typeof Picker>('src/pwa/PhotoPicker.tsx', {
    react: hooks, './photoPicker.css': {}, './preparationActivity': activity,
    './useConnectivity': { useConnectivity: () => 'online', connectivityMessage: () => 'Синтетическая сеть' },
    './photoPreparation': { ...preparation, preparePhoto: (file: File, signal: AbortSignal) => {
      const result = deferred<PreparedPhoto>(); preparations.push({ file, signal, result }); return result.promise;
    } },
  });
  function disconnect() {
    for (const host of hosts.values()) { host.isConnected = false; if (document.activeElement === host) document.activeElement = document.body; }
    for (const ref of refs.keys()) ref.current = null;
    hosts.clear(); refs.clear();
  }
  function cleanup() { for (const effect of effects) effect?.cleanup?.(); effects = []; disconnect(); }
  function flush() {
    for (let pass = 0; dirty; pass += 1) {
      if (pass > 20) throw new Error('Synthetic render did not settle');
      dirty = false;
      const selection = PhotoPicker(props) as unknown as Element;
      if (selection.key !== key) { cleanup(); slots = []; generation += 1; key = selection.key; }
      cursor = 0; layout = []; passive = [];
      const tree = (selection.type as (props: PhotoPickerProps) => Element)(props);
      const next = new Map<string, Host>();
      const nextRefs = new Map<Ref, Host>();
      function visit(value: unknown, path: string, disabled = false) {
        if (Array.isArray(value)) { value.forEach((child, index) => visit(child, `${path}/${(child as Element | null)?.key ?? index}`, disabled)); return; }
        if (!value || typeof value !== 'object' || !('type' in value)) return;
        const element = value as Element;
        if (typeof element.type !== 'string') return; // Preview image decoding is outside this harness.
        const host = hosts.get(path) ?? new Host(element.type, document, focusCalls);
        host.props = element.props;
        host.disabled = Boolean(element.props.disabled) || disabled;
        next.set(path, host);
        const ref = element.props.ref as Ref | undefined;
        if (ref) { ref.current = host; nextRefs.set(ref, host); }
        visit(element.props.children, `${path}/children`, disabled || element.type === 'fieldset' && Boolean(element.props.disabled));
      }
      visit(tree, 'root');
      for (const [path, host] of hosts) if (!next.has(path)) { host.isConnected = false; if (document.activeElement === host) document.activeElement = document.body; }
      for (const ref of refs.keys()) if (!nextRefs.has(ref)) ref.current = null;
      hosts = next; refs = nextRefs;
      for (const run of layout) run();
      for (const run of passive) run();
    }
  }
  const find = (predicate: (host: Host) => boolean): Host => { const host = [...hosts.values()].find(predicate); if (!host) throw new Error('Synthetic host not found'); return host; };
  flush();
  return {
    busy, changes, preparations, document, focusCalls, flush,
    get lateStateWrites() { return lateStateWrites; },
    get status() { return find(host => host.props.className === 'photo-picker__status'); },
    get chooser() { return find(host => host.type === 'button' && text(host.props.children) === 'Выбрать из файлов'); },
    get fieldset() { return find(host => host.type === 'fieldset'); },
    remove(index = 1) { return find(host => host.type === 'button' && String(host.props['aria-label']).startsWith(`Удалить фото ${index}:`)); },
    update(value: Partial<PhotoPickerProps>) { props = { ...props, ...value }; dirty = true; flush(); },
    select(files: File[]) {
      const input = find(host => host.props['aria-label'] === 'Выбрать фотографии');
      const target = { files, value: 'synthetic-path' };
      (input.props.onChange as (event: unknown) => void)({ currentTarget: target });
      flush(); return target;
    },
    click(host: Host, focus = true, beforeCommit?: () => void) {
      if (focus) host.focus();
      (host.props.onClick as (event: unknown) => void)({ currentTarget: host });
      beforeCommit?.(); flush();
    },
    async settle() { for (let i = 0; i < 5; i += 1) await Promise.resolve(); flush(); },
    unmount() { alive = false; cleanup(); },
    outside() { const outside = new Host('input', document, focusCalls); outside.focus(); return outside; },
  };
}

test('B photo feedback: canceled preparation settles to honest copy without changing the selected files or busy contract', async () => {
  const selected = photo('existing');
  const view = harness({ value: [selected] });
  const status = view.status;
  view.select([photo('canceled').file]);
  expect(view.fieldset.props['aria-busy']).toBe(true);
  view.update({ disabled: true });
  expect(view.preparations[0].signal.aborted).toBe(true);
  expect(view.busy).toEqual([true, false]);
  view.preparations[0].result.reject(new DOMException('Synthetic cancel', 'AbortError'));
  await view.settle();
  expect(view.fieldset.props['aria-busy']).toBe(false);
  expect(text(view.status.props.children)).toContain('Подготовка отменена');
  expect(text(view.status.props.children)).not.toMatch(/Подготавливаем|Проверяем|Загрузка.*подтверждена/);
  expect(view.status).toBe(status);
  expect(view.changes).toEqual([]);
  expect(view.busy).toEqual([true, false]);
  expect(view.focusCalls).toEqual([]);
  view.unmount();
});

test('B photo feedback: removing the focused last photo returns focus to the newly enabled file chooser', () => {
  const view = harness({ value: [photo('only')], maxPhotos: 1 });
  const status = view.status;
  const remove = view.remove();
  expect(view.chooser.disabled).toBe(true);
  view.click(remove);
  expect(view.changes).toEqual([[]]);
  expect(remove.isConnected).toBe(false);
  expect(view.document.activeElement).toBe(view.chooser);
  expect(view.chooser.disabled).toBe(false);
  expect(view.chooser.focusOptions).toEqual({ preventScroll: true });
  expect(view.status).toBe(status);
  expect(text(view.status.props.children)).toBe('Фото удалено из локального выбора.');
  view.unmount();
});

test('B photo feedback: canceled late success is discarded and selecting the same file again has fresh status', async () => {
  const view = harness();
  const selected = photo('same-file');
  const target = view.select([selected.file]);
  expect(target.value).toBe('');
  view.update({ disabled: true });
  view.update({ disabled: false });
  view.select([selected.file]);
  expect(view.preparations).toHaveLength(1); // Preserve the current in-flight guard.
  view.preparations[0].result.resolve(selected);
  await view.settle();
  expect(view.changes).toEqual([]);
  expect(text(view.status.props.children)).toContain('Подготовка отменена');
  view.select([selected.file]);
  expect(text(view.status.props.children)).toBe('Проверяем и сжимаем фото…');
  view.preparations[1].result.resolve(selected);
  await view.settle();
  expect(view.changes).toEqual([[selected]]);
  expect(text(view.status.props.children)).toBe('Подготовлено фото: 1. Загрузка на сервер ещё не подтверждена.');
  expect(view.busy).toEqual([true, false, true, false]);
  expect(view.focusCalls).toEqual([]);
  view.unmount();
});

test('B photo feedback: cancellation partway through a batch does not publish already prepared files', async () => {
  const view = harness({ value: [photo('existing')] });
  view.select([photo('first').file, photo('second').file]);
  view.preparations[0].result.resolve(photo('first'));
  await view.settle();
  expect(view.preparations).toHaveLength(2);
  view.update({ disabled: true });
  view.preparations[1].result.reject(new DOMException('Synthetic cancel', 'AbortError'));
  await view.settle();
  expect(view.changes).toEqual([]);
  expect(view.busy).toEqual([true, false]);
  expect(text(view.status.props.children)).toBe('Подготовка отменена. Новые фото не добавлены.');
  expect(view.focusCalls).toEqual([]);
  view.unmount();
});

test('B photo feedback: disabling after the parent accepts prepared files does not relabel that selection as canceled', async () => {
  const accepted: PreparedPhoto[][] = [];
  const view = harness({ onChange: value => { accepted.push(value); view.update({ value, disabled: true }); } });
  const selected = photo('accepted');
  view.select([selected.file]);
  view.preparations[0].result.resolve(selected);
  await view.settle();
  expect(accepted).toEqual([[selected]]);
  expect(view.busy).toEqual([true, false]);
  expect(text(view.status.props.children)).toBe('Подготовлено фото: 1. Загрузка на сервер ещё не подтверждена.');
  expect(view.focusCalls).toEqual([]);
  view.unmount();
});

for (const context of [{ contextKey: 'synthetic-new-account' }, { contextKey: 'synthetic-new-order-revision' }, { phase: 'before' as const }]) {
  test(`B photo feedback: ${JSON.stringify(context)} remount isolates old status and late completion from a new batch`, async () => {
    const view = harness();
    view.select([photo('old').file]);
    const old = view.preparations[0];
    view.update(context);
    expect(old.signal.aborted).toBe(true);
    expect(text(view.status.props.children)).toBe('Выбрано: 0 из 5.');
    view.select([photo('new').file]);
    old.result.resolve(photo('old'));
    await view.settle();
    expect(view.fieldset.props['aria-busy']).toBe(true);
    expect(text(view.status.props.children)).toBe('Проверяем и сжимаем фото…');
    expect(view.busy).toEqual([true, false, true]);
    expect(view.changes).toEqual([]);
    view.preparations[1].result.resolve(photo('new'));
    await view.settle();
    expect(view.changes[0].map(item => item.id)).toEqual(['new']);
    expect(view.busy).toEqual([true, false, true, false]);
    expect(view.lateStateWrites).toBe(0);
    expect(view.focusCalls).toEqual([]);
    view.unmount();
  });
}

test('B photo feedback: unmount cancels once and later completion cannot update state, publish or focus', async () => {
  const view = harness();
  view.select([photo('old').file]);
  view.unmount();
  expect(view.preparations[0].signal.aborted).toBe(true);
  expect(view.busy).toEqual([true, false]);
  view.preparations[0].result.resolve(photo('old'));
  await view.settle();
  expect(view.busy).toEqual([true, false]);
  expect(view.changes).toEqual([]);
  expect(view.lateStateWrites).toBe(0);
  expect(view.focusCalls).toEqual([]);
});

test('B photo feedback: external selection reset keeps the stale-selection explanation without focus restoration', async () => {
  const view = harness({ value: [photo('previous')] });
  view.select([photo('new').file]);
  const outside = view.outside();
  view.update({ value: [] });
  view.preparations[0].result.resolve(photo('new'));
  await view.settle();
  expect(text(view.status.props.children)).toBe('Выбор изменился. Добавьте фото ещё раз.');
  expect(view.changes).toEqual([]);
  expect(view.document.activeElement).toBe(outside);
  expect(view.focusCalls).toEqual([outside]);
  view.unmount();
});

test('B photo feedback: failed decoding keeps the error, clears busy and permits a fresh selection without focusing', async () => {
  const view = harness();
  const file = photo('decode-fails').file;
  view.select([file]);
  view.preparations[0].result.reject(new preparation.PhotoPreparationError('decode'));
  await view.settle();
  expect(text(view.status.props.children)).toBe('Новые фото не добавлены.');
  expect(view.fieldset.props['aria-busy']).toBe(false);
  expect(view.changes).toEqual([]);
  expect(view.select([file]).value).toBe('');
  expect(view.preparations).toHaveLength(2);
  view.preparations[1].result.resolve(photo('decoded'));
  await view.settle();
  expect(view.changes[0].map(item => item.id)).toEqual(['decoded']);
  expect(view.focusCalls).toEqual([]);
  view.unmount();
});

test('B photo feedback: removing a middle item preserves the remaining files and focuses only for that explicit action', () => {
  const selected = [photo('first'), photo('middle'), photo('last')];
  const view = harness({ value: selected });
  view.click(view.remove(2));
  expect(view.changes).toEqual([[selected[0], selected[2]]]);
  expect(view.document.activeElement).toBe(view.chooser);
  const outside = view.outside();
  view.update({ value: [...view.changes[0]] });
  view.update({ disabled: true });
  view.update({ disabled: false });
  expect(view.document.activeElement).toBe(outside);
  expect(view.focusCalls).toHaveLength(3); // Delete button, chooser, user's other field.
  view.unmount();
});

test('B photo feedback: a still-full selection uses the persistent programmatically focusable status', () => {
  const view = harness({ value: [photo('first'), photo('second'), photo('third')], maxPhotos: 1 });
  const status = view.status;
  view.click(view.remove());
  expect(view.chooser.disabled).toBe(true);
  expect(view.document.activeElement).toBe(status);
  expect(status.props.tabIndex).toBe(-1);
  expect(status.props.role).toBe('status');
  expect(status.focusOptions).toEqual({ preventScroll: true });
  view.unmount();
});

test('B photo feedback: deleting a nonfocused item cannot steal focus from another field', () => {
  const view = harness({ value: [photo('selected')] });
  const outside = view.outside();
  view.click(view.remove(), false);
  expect(view.changes).toEqual([[]]);
  expect(view.document.activeElement).toBe(outside);
  expect(view.focusCalls).toEqual([outside]);
  view.unmount();
});

test('B photo feedback: focus moved before the deletion commit is respected', () => {
  const view = harness({ value: [photo('selected')] });
  let outside: Host | undefined;
  view.click(view.remove(), true, () => { outside = view.outside(); });
  expect(view.document.activeElement).toBe(outside);
  expect(view.focusCalls).toHaveLength(2);
  view.update({ value: [] });
  expect(view.document.activeElement).toBe(outside);
  view.unmount();
});

test('B photo feedback: disabled deletion and selection handlers do nothing; disabling the deletion commit does not focus on later unlock', () => {
  const selected = photo('selected');
  const view = harness({ value: [selected], disabled: true });
  view.click(view.remove());
  view.select([photo('blocked').file]);
  expect(view.changes).toEqual([]);
  expect(view.preparations).toEqual([]);
  expect(view.focusCalls).toEqual([]);
  view.update({ disabled: false });
  view.click(view.remove(), true, () => view.update({ disabled: true }));
  expect(view.changes).toEqual([[]]);
  expect(view.focusCalls).toHaveLength(1);
  view.update({ disabled: false });
  expect(view.focusCalls).toHaveLength(1);
  view.unmount();
});

test('B photo feedback: a parent that retains or defers removal consumes the focus request before any later update', () => {
  const view = harness({ value: [photo('retained')], onChange() {} });
  const button = view.remove();
  view.click(button);
  expect(button.isConnected).toBe(true);
  expect(view.document.activeElement).toBe(button);
  expect(view.focusCalls).toEqual([button]);
  view.update({ value: [] }); // A later parent response/poll is not an explicit activation.
  expect(view.document.activeElement).toBe(view.document.body);
  expect(view.focusCalls).toEqual([button]);
  view.unmount();
});

test('B photo feedback: busy preparation blocks deletion and duplicate selection without changing focus on completion', async () => {
  const view = harness({ value: [photo('existing')] });
  view.select([photo('new').file]);
  view.click(view.remove());
  view.select([photo('duplicate').file]);
  expect(view.preparations).toHaveLength(1);
  expect(view.changes).toEqual([]);
  view.preparations[0].result.resolve(photo('new'));
  await view.settle();
  expect(view.changes[0].map(item => item.id)).toEqual(['existing', 'new']);
  expect(view.focusCalls).toEqual([]);
  view.unmount();
});

test('B photo feedback: a session change during deletion discards its focus request', () => {
  const view = harness({ value: [photo('old-session')] });
  view.click(view.remove(), true, () => view.update({ contextKey: 'synthetic-new-session', value: [] }));
  expect(view.focusCalls).toHaveLength(1);
  expect(text(view.status.props.children)).toBe('Выбрано: 0 из 5.');
  view.update({ value: [] });
  expect(view.focusCalls).toHaveLength(1);
  view.unmount();
});
