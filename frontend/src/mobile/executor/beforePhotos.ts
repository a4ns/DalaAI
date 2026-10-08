import { ApiError } from '../../shared/api/client';
import type { ApiClient } from '../../shared/api/client';
import type { OrderStore } from '../../shared/api/orderStore';

export interface BeforePhotoScope {
  orderId: string;
  sectionId: string;
  assignmentRevision: number;
  photoIds: readonly string[];
}
export interface BeforePhotoEntry {
  id: string;
  url: string | null;
  status: 'loading' | 'ready' | 'missing' | 'failed';
}
export interface BeforePhotoState {
  status: 'idle' | 'loading' | 'ready' | 'blocked';
  photos: readonly BeforePhotoEntry[];
  canRetry?: boolean;
}
const LIMIT = 5;
const CONCURRENCY = 2;
const same = (a: string, b: string): boolean => a.toLowerCase() === b.toLowerCase();
const idsKey = (ids: readonly string[]): string => JSON.stringify(ids.map(id => id.toLowerCase()));
export const beforePhotoScopeKey = (scope: BeforePhotoScope): string => JSON.stringify([scope.orderId, scope.sectionId, scope.assignmentRevision, idsKey(scope.photoIds)]);

/** Read-only, per-selection lifetime. Never caches protected bytes outside this controller. */
export class BeforePhotosController {
  #client: ApiClient;
  #orders: OrderStore;
  #scope: BeforePhotoScope;
  #isCurrent: () => boolean;
  #epoch: number;
  #active = false;
  #run = 0;
  #pending = false;
  #deniedAt: number | null = null;
  #abort: AbortController | null = null;
  #urls = new Set<string>();
  #listeners = new Set<() => void>();
  #state: BeforePhotoState = { status: 'idle', photos: [] };
  #url: Pick<typeof URL, 'createObjectURL' | 'revokeObjectURL'>;
  constructor(client: ApiClient, orders: OrderStore, scope: BeforePhotoScope, isCurrent: () => boolean,
    url: Pick<typeof URL, 'createObjectURL' | 'revokeObjectURL'> = URL) {
    this.#client = client; this.#orders = orders; this.#scope = { ...scope, photoIds: [...scope.photoIds] };
    this.#isCurrent = isCurrent; this.#epoch = client.epoch; this.#url = url;
  }
  setCurrent(isCurrent: () => boolean): void { this.#isCurrent = isCurrent; if (this.#active && !this.#allowed()) this.#block(); }
  getSnapshot = (): BeforePhotoState => this.#state;
  subscribe = (listener: () => void): (() => void) => { this.#listeners.add(listener); return () => { this.#listeners.delete(listener); }; };
  #set(state: BeforePhotoState): void { this.#state = state; this.#listeners.forEach(listener => listener()); }
  #allowed(): boolean {
    const session = this.#client.session; const principal = session?.principal;
    const state = this.#orders.getSnapshot();
    const order = state.snapshot?.find(row => same(row.id, this.#scope.orderId));
    // A quiet in-progress poll keeps its last complete authorized membership. Failed/partial
    // reads do not. Neither version nor confirmation time identifies these attached bytes.
    const confirmed = state.snapshot !== null && state.lastConfirmedAt !== null && !state.incomplete && !state.error &&
      (state.loadStatus === 'ready' && state.freshness === 'fresh' || state.loadStatus === 'loading' && state.freshness !== 'never');
    return this.#active && this.#isCurrent() && this.#epoch === this.#client.epoch &&
      this.#orders.access === 'allowed' && confirmed && Boolean(session && Date.parse(session.expires_at) > Date.now() &&
      principal?.active && principal.role === 'executor' && order && same(principal.user_id, order.assignment.executor_id) &&
      principal.section_ids.some(id => same(id, order.section_id)) && same(order.section_id, this.#scope.sectionId) &&
      order.assignment_revision === this.#scope.assignmentRevision && idsKey(order.before_photo_ids) === idsKey(this.#scope.photoIds));
  }
  #clear(): void {
    this.#run++; this.#pending = false; this.#abort?.abort(); this.#abort = null;
    for (const url of this.#urls) this.#url.revokeObjectURL(url);
    this.#urls.clear();
  }
  #canLoad(): boolean { return this.#allowed() && (this.#deniedAt === null || this.#orders.confirmation > this.#deniedAt); }
  #block(): void { this.#clear(); this.#set({ status: 'blocked', photos: [], canRetry: this.#canLoad() }); }
  attach(): () => void {
    this.#active = true;
    const synchronize = () => {
      if (!this.#allowed()) this.#block();
      else if (this.#state.status === 'blocked' && this.#state.canRetry !== this.#canLoad()) this.#set({ ...this.#state, canRetry: this.#canLoad() });
    };
    const stopClient = this.#client.subscribe(synchronize); const stopOrders = this.#orders.subscribe(synchronize);
    // Real-time expiry also clears an already displayed image when there is no network activity.
    const timer = setInterval(synchronize, 1000);
    synchronize();
    return () => { this.#active = false; stopClient(); stopOrders(); clearInterval(timer); this.#block(); };
  }
  async load(): Promise<void> {
    if (this.#pending) return;
    if (!this.#canLoad()) { this.#block(); return; }
    this.#clear();
    const photoIds = [...new Set(this.#scope.photoIds.map(id => id.toLowerCase()))].slice(0, LIMIT);
    const run = this.#run; const abort = new AbortController(); this.#abort = abort; this.#pending = true;
    this.#set({ status: photoIds.length ? 'loading' : 'ready', photos: photoIds.map(id => ({ id, url: null, status: 'loading' })) });
    const current = () => this.#run === run && !abort.signal.aborted && this.#allowed();
    let cursor = 0;
    const update = (id: string, entry: BeforePhotoEntry) => {
      if (current()) this.#set({ ...this.#state, photos: this.#state.photos.map(photo => photo.id === id ? entry : photo) });
    };
    const worker = async () => {
      while (current() && cursor < photoIds.length) {
        const id = photoIds[cursor++];
        try {
          const blob = await this.#client.getPhoto(id, abort.signal);
          if (!current()) return;
          if (!['image/jpeg', 'image/png', 'image/webp'].includes(blob.type.toLowerCase()) || blob.size === 0 || blob.size > 8 * 1024 * 1024) {
            update(id, { id, url: null, status: 'failed' }); continue;
          }
          const url = this.#url.createObjectURL(blob); this.#urls.add(url);
          if (!current()) { this.#url.revokeObjectURL(url); this.#urls.delete(url); return; }
          update(id, { id, url, status: 'ready' });
        } catch (error) {
          if (!current()) return;
          if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
            this.#deniedAt = this.#orders.confirmation; this.#block(); return;
          }
          update(id, { id, url: null, status: error instanceof ApiError && error.status === 404 ? 'missing' : 'failed' });
        }
      }
    };
    await Promise.all(Array.from({ length: Math.min(CONCURRENCY, photoIds.length) }, worker));
    if (current()) { this.#pending = false; this.#abort = null; this.#set({ ...this.#state, status: 'ready' }); }
    else if (this.#run === run) this.#block();
  }
  imageFailed(id: string): void {
    if (!this.#allowed()) { this.#block(); return; }
    const photo = this.#state.photos.find(entry => entry.id === id);
    if (!photo?.url) return;
    this.#url.revokeObjectURL(photo.url); this.#urls.delete(photo.url);
    this.#set({ ...this.#state, photos: this.#state.photos.map(entry => entry.id === id ? { ...entry, url: null, status: 'failed' } : entry) });
  }
}
