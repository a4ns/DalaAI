import { ApiClient, ApiError, safeErrorMessage, SessionChangedError } from './client';
import type { Order, OrderEvent } from './wire';
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

/** Every refresh starts a fresh authorized keyset sweep; membership changes only on completion. */
export class OrderStore {
  #client: ApiClient;
  #epoch: number;
  #state: ResourceState<Order[]> = initialResource();
  #listeners = new Set<() => void>();
  #access: 'allowed' | 'forbidden' = 'allowed';
  #run = 0;
  #pending: Promise<void> | null = null;
  #unsubscribe: () => void;
  constructor(client: ApiClient) {
    this.#client = client; this.#epoch = client.epoch;
    this.#unsubscribe = client.subscribe(() => {
      if (this.#epoch !== client.epoch) {
        this.#epoch = client.epoch; this.#access = 'allowed'; this.#run++; this.#pending = null; this.#set(initialResource());
      }
    });
  }
  get access(): 'allowed' | 'forbidden' { return this.#access; }
  getSnapshot = (): ResourceState<Order[]> => this.#state;
  subscribe = (listener: () => void): (() => void) => { this.#listeners.add(listener); return () => { this.#listeners.delete(listener); }; };
  dispose(): void { this.#unsubscribe(); this.#run++; this.#listeners.clear(); }
  #set(state: ResourceState<Order[]>): void { this.#state = state; this.#listeners.forEach(listener => listener()); }
  record(order: Order, epoch: number): void {
    if (epoch !== this.#client.epoch) return;
    this.#set({ ...this.#state, snapshot: mergeOrders(this.#state.snapshot ?? [], [order]) });
  }
  refresh(): Promise<void> {
    if (this.#pending) return this.#pending;
    const run = ++this.#run; const epoch = this.#client.epoch;
    const promise = this.#sweep(run, epoch).finally(() => { if (run === this.#run) this.#pending = null; });
    this.#pending = promise; return promise;
  }
  async #sweep(run: number, epoch: number): Promise<void> {
    const start = new Map((this.#state.snapshot ?? []).map(order => [order.id, order]));
    this.#set({ ...this.#state, loadStatus: 'loading', freshness: this.#state.snapshot ? 'stale' : 'never', error: null });
    let seen: Order[] = []; let cursor: string | undefined;
    const cursors = new Set<string>();
    const active = () => run === this.#run && epoch === this.#client.epoch;
    try {
      do {
        const page = await this.#client.listOrders({}, cursor);
        if (!active()) return;
        seen = mergeOrders(seen, page.items);
        cursor = page.next_cursor ?? undefined;
        if (cursor && cursors.has(cursor)) throw new ApiError('Сервер повторил страницу. Список получен не полностью.');
        if (cursor) cursors.add(cursor);
      } while (cursor);
      if (!active()) return;
      const latest = this.#state.snapshot ?? [];
      const ids = new Set(seen.map(order => order.id));
      // Preserve concurrent, newly confirmed receipts; do not keep stale list membership.
      const concurrent = latest.filter(order => order !== start.get(order.id) && !ids.has(order.id));
      const completed = mergeOrders(seen, latest.filter(order => ids.has(order.id)));
      this.#access = 'allowed';
      this.#set({ snapshot: mergeOrders(completed, concurrent), freshness: 'fresh', loadStatus: 'ready', error: null, incomplete: false, lastConfirmedAt: new Date().toISOString() });
    } catch (error) {
      if (!active() || error instanceof SessionChangedError) return;
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
        this.#access = 'forbidden';
        this.#set({ ...initialResource<Order[]>(), loadStatus: 'error', error: safeErrorMessage(error) }); return;
      }
      const snapshot = seen.length ? mergeOrders(this.#state.snapshot ?? [], seen) : this.#state.snapshot;
      this.#set({ ...this.#state, snapshot, freshness: snapshot ? 'stale' : 'never', loadStatus: typeof navigator !== 'undefined' && !navigator.onLine ? 'offline' : 'error', error: safeErrorMessage(error), incomplete: true });
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
