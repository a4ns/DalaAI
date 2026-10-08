import type { ApiClient } from '../shared/api/client';
import type { OrderStore } from '../shared/api/orderStore';
import type { Order, Principal } from '../shared/api/wire';

export const NOTICE_LIFETIME_MS = 8000;
export const MAX_VISIBLE_NOTICES = 3;
export interface InAppNotice { key: string; title: string; message: string }

function noticeFor(order: Order, principal: Principal): InAppNotice | null {
  if (!principal.section_ids.includes(order.section_id)) return null;
  if (principal.role === 'executor' && order.assignment.executor_id === principal.user_id) {
    return { key: JSON.stringify(['assignment', order.id, order.assignment_revision]), title: 'Новый наряд', message: `Вам назначен наряд № ${order.number}.` };
  }
  if (principal.role === 'master' && order.status === 'ai_review' && order.current_submission_id) {
    return { key: JSON.stringify(['review', order.id, order.assignment_revision, order.current_submission_id]), title: 'Результат на проверке', message: `Наряд № ${order.number} ожидает решения мастера.` };
  }
  return null;
}

/** Read-only observer. Only a completed OrderStore confirmation can discover events.
 * Memory belongs to this session; no requests, storage, commands or OS permissions.
 */
export class InAppNotificationFeed {
  #client: ApiClient;
  #orders: OrderStore;
  #scope = '';
  #confirmation = 0;
  #baseline = false;
  #versions = new Map<string, { version: number; revision: number }>();
  #seen = new Set<string>();
  #state: readonly InAppNotice[] = [];
  #listeners = new Set<() => void>();
  constructor(client: ApiClient, orders: OrderStore) { this.#client = client; this.#orders = orders; }
  getSnapshot = (): readonly InAppNotice[] => this.#state;
  subscribe = (listener: () => void): (() => void) => { this.#listeners.add(listener); return () => { this.#listeners.delete(listener); }; };
  #set(notices: readonly InAppNotice[]): void {
    if (!notices.length && !this.#state.length) return;
    this.#state = notices; this.#listeners.forEach(listener => listener());
  }
  #reset(): void {
    this.#scope = ''; this.#confirmation = 0; this.#baseline = false;
    this.#versions.clear(); this.#seen.clear(); this.#set([]);
  }
  dismiss = (key: string): void => { this.#set(this.#state.filter(notice => notice.key !== key)); };
  #observe = (): void => {
    const principal = this.#client.session?.principal;
    if (!principal || !this.#client.activeSession || this.#orders.access === 'forbidden'
      || (principal.role !== 'master' && principal.role !== 'executor')) { this.#reset(); return; }
    const scope = JSON.stringify([this.#client.epoch, principal.user_id, principal.role, [...new Set(principal.section_ids)].sort()]);
    if (scope !== this.#scope) { this.#reset(); this.#scope = scope; }
    const state = this.#orders.getSnapshot(); const confirmation = this.#orders.confirmation;
    if (confirmation <= this.#confirmation || state.snapshot === null || state.loadStatus !== 'ready'
      || state.freshness !== 'fresh' || state.incomplete || state.error !== null) return;
    this.#confirmation = confirmation;
    const discovered: InAppNotice[] = [];
    // Retain high-water marks even after disappearance; timestamps alone are not events.
    for (const order of state.snapshot) {
      const previous = this.#versions.get(order.id);
      if (previous && order.version <= previous.version) continue;
      this.#versions.set(order.id, { version: order.version, revision: Math.max(previous?.revision ?? 0, order.assignment_revision) });
      if (previous && order.assignment_revision < previous.revision) continue;
      const notice = noticeFor(order, principal);
      if (!notice || this.#seen.has(notice.key)) continue;
      this.#seen.add(notice.key);
      if (this.#baseline) discovered.push(notice);
    }
    // A successful empty list is a baseline too. Failed/partial reads never reach here.
    this.#baseline = true;
    // Keep mounted notices (and their hover/focus) stable. Excess new keys are consumed, not queued.
    if (discovered.length) this.#set([...this.#state, ...discovered].slice(0, MAX_VISIBLE_NOTICES));
  };
  /** Effect cleanup is safe under StrictMode replay and drops all session-local data. */
  attach = (): (() => void) => {
    let expiry: ReturnType<typeof setTimeout> | undefined;
    const observeIdentity = () => {
      clearTimeout(expiry); this.#observe();
      const remaining = Date.parse(this.#client.session?.expires_at ?? '') - Date.now();
      if (remaining > 0) expiry = setTimeout(observeIdentity, Math.min(remaining, 2_147_483_647));
    };
    const unsubscribeOrders = this.#orders.subscribe(this.#observe);
    const unsubscribeClient = this.#client.subscribe(observeIdentity);
    observeIdentity();
    return () => { clearTimeout(expiry); unsubscribeOrders(); unsubscribeClient(); this.#reset(); };
  };
}
