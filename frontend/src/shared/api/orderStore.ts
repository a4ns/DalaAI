import { ApiClient, ApiError, safeErrorMessage, SessionChangedError } from './client';
import type { Order, OrderEvent, Session } from './wire';
import type { ResourceState } from '../ui/types';
import { initialResource } from '../ui/types';

/** Never let an old idempotent receipt replace a newer observed version. */
export function mergeOrderVersion(current: Order | undefined, incoming: Order): Order {
  if (!current || incoming.version > current.version) return incoming;
  if (incoming.version < current.version) return current;
  // Overdue/domain time are computed on reads and can advance without a version bump.
  return Date.parse(incoming.domain_now) > Date.parse(current.domain_now) ? incoming : current;
}
export function mergeOrders(current: readonly Order[], incoming: readonly Order[]): Order[] {
  const byId = new Map(current.map(order => [order.id, order]));
  for (const order of incoming) byId.set(order.id, mergeOrderVersion(byId.get(order.id), order));
  return [...byId.values()].sort((a, b) => b.number.localeCompare(a.number, 'en', { numeric: true }));
}

/** A retained full confirmation is usable for at most one real 15-second window. */
export const ORDER_CONFIRMATION_LIMIT_MS = 15000;
function authority(session: Session | null): string {
  const principal = session?.principal;
  return principal ? JSON.stringify([principal.user_id, principal.role, principal.active, [...new Set(principal.section_ids)].sort()]) : '';
}
function actionIdentity(order: Order): string {
  return JSON.stringify([order.status, order.assignment_revision, order.scheduling_revision, order.type, order.section_id, order.equipment_id, order.assignment.executor_id, order.assignment.brigade_id, order.current_submission_id]);
}
/** Every sweep stages membership privately. Only explicit healthy automatic polls retain readiness. */
export class OrderStore {
  #client: ApiClient; #epoch: number; #state: ResourceState<Order[]> = initialResource();
  #listeners = new Set<() => void>(); #access: 'allowed' | 'forbidden' = 'allowed';
  #confirmation = 0; #run = 0; #pending: Promise<void> | null = null; #unsubscribe: () => void;
  #abort: AbortController | null = null; #watchdog: ReturnType<typeof setTimeout> | null = null;
  #reading = false; #retainedUntil = 0; #disposed = false; #confirmedAuthority = '';
  constructor(client: ApiClient) {
    this.#client = client; this.#epoch = client.epoch;
    this.#unsubscribe = client.subscribe(() => {
      if (this.#epoch !== client.epoch) {
        this.#epoch = client.epoch; this.#access = 'allowed'; this.#confirmation = 0; this.#confirmedAuthority = ''; this.#cancelRead(); this.#set(initialResource());
      }
    });
  }
  get confirmation(): number { return this.#confirmation; }
  get access(): 'allowed' | 'forbidden' { return this.#access; }
  /** Synchronous final gate, including delayed watchdogs, offline and real session expiry. */
  get actionReady(): boolean {
    const confirmed = Date.parse(this.#state.lastConfirmedAt ?? ''); const now = Date.now();
    return !this.#disposed && this.#epoch === this.#client.epoch && this.#access === 'allowed' && this.#client.online && this.#client.activeSession
      && this.#confirmedAuthority === authority(this.#client.session)
      && this.#state.snapshot !== null && this.#state.loadStatus === 'ready' && this.#state.freshness === 'fresh' && !this.#state.incomplete && this.#state.error === null
      && Number.isFinite(confirmed) && now >= confirmed && now - confirmed < ORDER_CONFIRMATION_LIMIT_MS
      && (!this.#reading || now < this.#retainedUntil);
  }
  getSnapshot = (): ResourceState<Order[]> => this.#state;
  subscribe = (listener: () => void): (() => void) => { this.#listeners.add(listener); return () => { this.#listeners.delete(listener); }; };
  dispose(): void { this.#disposed = true; this.#unsubscribe(); this.#cancelRead(); this.#listeners.clear(); }
  #set(state: ResourceState<Order[]>): void { this.#state = state; this.#listeners.forEach(listener => listener()); }
  #finishRead(): void { if (this.#watchdog !== null) clearTimeout(this.#watchdog); this.#watchdog = null; this.#abort = null; this.#reading = false; this.#retainedUntil = 0; }
  #cancelRead(): void { const abort = this.#abort; this.#run++; this.#pending = null; this.#finishRead(); abort?.abort(); }
  #blockLoading(): void { if (this.#retainedUntil === 0 && this.#state.loadStatus === 'loading' && this.#state.freshness !== 'fresh') return; this.#retainedUntil = 0; this.#set({ ...this.#state, loadStatus: 'loading', freshness: this.#state.snapshot ? 'stale' : 'never', error: null }); }
  #expireRead(): void {
    this.#cancelRead();
    if (this.#client.session && !this.#client.activeSession) this.#set({ ...initialResource<Order[]>(), loadStatus: 'error', error: 'Сессия завершена или неактивна. Войдите снова.' });
    else this.#set({ ...this.#state, freshness: this.#state.snapshot ? 'stale' : 'never', loadStatus: 'error', incomplete: true, error: 'Полное обновление не подтверждено за отведённое время. Действия заблокированы до нового снимка.' });
  }
  invalidateOffline = (): void => {
    this.#cancelRead();
    this.#set({ ...this.#state, loadStatus: 'offline', freshness: this.#state.snapshot ? 'stale' : 'never', incomplete: true, error: 'Нет сети. Доступность действий требует нового полного обновления.' });
  };
  record(order: Order, epoch: number): void {
    if (this.#disposed || epoch !== this.#client.epoch) return;
    this.#set({ ...this.#state, snapshot: mergeOrders(this.#state.snapshot ?? [], [order]) });
  }
  refresh(options: { background?: boolean } = {}): Promise<void> {
    if (this.#disposed) return Promise.resolve();
    if (!this.#client.online) { this.invalidateOffline(); return Promise.resolve(); }
    if (this.#pending) {
      // Explicit recovery joins the existing read, but revokes its background allowance now.
      if (!options.background || !this.actionReady) this.#blockLoading();
      return this.#pending;
    }
    const retain = options.background === true && this.actionReady;
    const run = ++this.#run; const epoch = this.#client.epoch; const now = Date.now(); const scope = authority(this.#client.session);
    const start = new Map((this.#state.snapshot ?? []).map(order => [order.id, order]));
    const abort = new AbortController(); this.#abort = abort; this.#reading = true;
    let deadline = now + ORDER_CONFIRMATION_LIMIT_MS;
    if (retain) deadline = Math.min(deadline, Date.parse(this.#state.lastConfirmedAt!) + ORDER_CONFIRMATION_LIMIT_MS);
    if (this.#client.activeSession) deadline = Math.min(deadline, Date.parse(this.#client.session!.expires_at));
    this.#retainedUntil = retain ? deadline : 0;
    const promise = Promise.resolve().then(() => this.#sweep(run, epoch, scope, deadline, start, abort.signal)).finally(() => {
      if (run === this.#run) { this.#pending = null; this.#finishRead(); }
    });
    this.#pending = promise;
    this.#watchdog = setTimeout(() => {
      if (run !== this.#run || !this.#reading) return;
      this.#expireRead();
    }, Math.max(1, deadline - now));
    if (!retain) this.#blockLoading();
    return promise;
  }
  async #sweep(run: number, epoch: number, scope: string, deadline: number, start: Map<string, Order>, signal: AbortSignal): Promise<void> {
    let seen: Order[] = []; let cursor: string | undefined; const cursors = new Set<string>();
    const active = () => !this.#disposed && run === this.#run && epoch === this.#client.epoch;
    try {
      if (!active()) return;
      do {
        if (Date.now() >= deadline) { this.#expireRead(); return; }
        const page = await this.#client.listOrders({}, cursor, signal);
        if (!active()) return;
        if (Date.now() >= deadline) { this.#expireRead(); return; }
        if (scope !== authority(this.#client.session)) { this.#cancelRead(); this.#set({ ...initialResource<Order[]>(), loadStatus: 'error', error: 'Область доступа изменилась. Требуется новый полный снимок.' }); return; }
        if (!this.#client.online) { this.invalidateOffline(); return; }
        const current = new Map((this.#state.snapshot ?? []).map(order => [order.id, order]));
        for (const incoming of page.items) {
          const held = current.get(incoming.id);
          if (!held || incoming.version < held.version) continue; // Never roll back a concurrent receipt.
          if (incoming.version === held.version && actionIdentity(incoming) !== actionIdentity(held)) throw new ApiError('Наряд изменил назначение или состояние без новой версии. Обновление не подтверждено.');
          if (incoming.version > held.version && this.#retainedUntil > 0) this.#blockLoading();
        }
        seen = mergeOrders(seen, page.items); cursor = page.next_cursor ?? undefined;
        if (cursor && cursors.has(cursor)) throw new ApiError('Сервер повторил страницу. Список получен не полностью.');
        if (cursor) cursors.add(cursor);
      } while (cursor);
      if (!active()) return;
      if (Date.now() >= deadline) { this.#expireRead(); return; }
      if (this.#client.session && !this.#client.activeSession) { this.#cancelRead(); this.#set({ ...initialResource<Order[]>(), loadStatus: 'error', error: 'Сессия завершена или неактивна. Войдите снова.' }); return; }
      const latest = this.#state.snapshot ?? []; const ids = new Set(seen.map(order => order.id));
      const concurrent = latest.filter(order => order !== start.get(order.id) && !ids.has(order.id));
      const completed = mergeOrders(seen, latest.filter(order => ids.has(order.id)));
      this.#finishRead(); this.#access = 'allowed'; this.#confirmedAuthority = scope; this.#confirmation++;
      this.#set({ snapshot: mergeOrders(completed, concurrent), freshness: 'fresh', loadStatus: 'ready', error: null, incomplete: false, lastConfirmedAt: new Date().toISOString() });
    } catch (error) {
      if (!active() || error instanceof SessionChangedError) return;
      this.#finishRead();
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
        this.#access = 'forbidden'; this.#set({ ...initialResource<Order[]>(), loadStatus: 'error', error: safeErrorMessage(error) }); return;
      }
      this.#set({ ...this.#state, freshness: this.#state.snapshot ? 'stale' : 'never', loadStatus: this.#client.online ? 'error' : 'offline', error: safeErrorMessage(error), incomplete: true });
    }
  }
}

/** Events and versions differ; drain by server cursor, then callers reconcile an order snapshot. */
export async function readAllOrderEvents(client: ApiClient, orderId: string, signal?: AbortSignal): Promise<OrderEvent[]> {
  const epoch = client.epoch; const byId = new Map<string, OrderEvent>(); let after = 0;
  for (;;) {
    const page = await client.listOrderEvents(orderId, after, signal);
    if (epoch !== client.epoch) throw new SessionChangedError();
    for (const event of page.items) byId.set(event.id, event);
    if (!page.has_more) return [...byId.values()].sort((a, b) => a.sequence - b.sequence);
    if (page.next_after_sequence <= after) throw new ApiError('Не удалось получить полную историю.');
    after = page.next_after_sequence;
  }
}
