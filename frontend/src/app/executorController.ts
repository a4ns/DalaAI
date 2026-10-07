import { ApiClient, ApiError, safeErrorMessage, SessionChangedError } from '../shared/api/client';
import type { OrderCommandIntent, PreparedMutation } from '../shared/api/client';
import type { OrderStore } from '../shared/api/orderStore';
import type { CommandResult, Order } from '../shared/api/wire';
import type { MutationOutcome, MutationState } from '../shared/ui/types';
import { emptyExecutorDraft } from '../mobile/executor/model';
import type { ExecutorDraft, ExecutorIntent, ExecutorIntentSummary } from '../mobile/executor/types';
import { canResolveIntent, isIntentUnresolved, mutationFailureState, withNewIntentGuard } from './mutationFailure';
import type { PhotoContext, PhotoStore } from './photoStore';

export const executorScope = (orderId: string, assignmentRevision: number): string => `${orderId}:${assignmentRevision}`;
interface Entry {
  scope: string;
  orderId: string;
  assignmentRevision: number;
  intent: ExecutorIntentSummary;
  token: PreparedMutation<CommandResult>;
  status: MutationState['status'];
  error: string | null;
  unresolved: boolean;
  startedConfirmation: number;
  deniedAt: number | null;
  promise?: Promise<MutationOutcome>;
}
export interface ExecutorView {
  scope: string;
  mutation: MutationState;
  pendingIntent: ExecutorIntentSummary | null;
}
const idleView = (scope: string): ExecutorView => ({ scope, mutation: { status: 'idle', error: null }, pendingIntent: null });
function copyDraft(draft: ExecutorDraft): ExecutorDraft {
  return { ...draft, materials: draft.materials.map(item => ({ ...item })), afterPhotoIds: [...draft.afterPhotoIds] };
}

/** Per-order effects and per-assignment drafts, confined to one authenticated client epoch. */
export class ExecutorController {
  #client: ApiClient;
  #orders: OrderStore;
  #photos: PhotoStore;
  #sessionKey: string;
  #epoch: number;
  #entries = new Map<string, Entry>();
  #drafts = new Map<string, ExecutorDraft>();
  #photoGenerations = new Map<string, number>();
  #listeners = new Set<() => void>();
  #revision = 0;
  constructor(client: ApiClient, orders: OrderStore, photos: PhotoStore, sessionKey: string) {
    this.#client = client; this.#orders = orders; this.#photos = photos; this.#sessionKey = sessionKey; this.#epoch = client.epoch;
  }
  subscribe = (listener: () => void): (() => void) => { this.#listeners.add(listener); return () => { this.#listeners.delete(listener); }; };
  getSnapshot = (): number => this.#revision;
  #emit(): void { if (this.#epoch !== this.#client.epoch) return; this.#revision++; this.#listeners.forEach(listener => listener()); }
  #currentSession(): boolean { return this.#epoch === this.#client.epoch; }
  #assignedToCurrentUser(order: Order): boolean {
    const principal = this.#client.session?.principal;
    return this.#currentSession() && this.#orders.access === 'allowed' && Boolean(principal?.active && principal.role === 'executor' && principal.user_id === order.assignment.executor_id && principal.section_ids.includes(order.section_id));
  }
  #denied(orderId: string): boolean {
    return [...this.#entries.values()].some(entry => entry.orderId === orderId && entry.deniedAt !== null && this.#orders.confirmation <= entry.deniedAt);
  }
  visibleOrders(): Order[] {
    return (this.#orders.getSnapshot().snapshot ?? []).filter(order => this.#assignedToCurrentUser(order) && !this.#denied(order.id));
  }
  #unresolvedOrder(orderId: string): Entry | undefined {
    return [...this.#entries.values()].find(entry => entry.orderId === orderId && isIntentUnresolved(entry));
  }
  get hasDrafts(): boolean { return [...this.#drafts.values()].some(draft => draft.workDescription || draft.workCodeId || draft.materials.length || draft.comment || draft.reason); }
  photoContext(order: Pick<Order, 'id' | 'assignment_revision' | 'section_id'>): PhotoContext {
    const scope = executorScope(order.id, order.assignment_revision);
    return { key: `${this.#sessionKey}:${scope}:${order.section_id}:${this.#photoGenerations.get(scope) ?? 0}:after`, phase: 'after', sectionId: order.section_id, orderId: order.id, assignmentRevision: order.assignment_revision };
  }
  canEdit(orderId: string, assignmentRevision: number): boolean {
    return this.#currentSession() && !this.#unresolvedOrder(orderId) && this.visibleOrders().some(order => order.id === orderId && order.assignment_revision === assignmentRevision);
  }
  setDraft(orderId: string, assignmentRevision: number, draft: ExecutorDraft): void {
    if (!this.canEdit(orderId, assignmentRevision)) return;
    this.#drafts.set(executorScope(orderId, assignmentRevision), copyDraft(draft)); this.#emit();
  }
  draft(order: Order): ExecutorDraft {
    if (!this.visibleOrders().some(item => item.id === order.id && item.assignment_revision === order.assignment_revision)) return emptyExecutorDraft();
    const saved = this.#drafts.get(executorScope(order.id, order.assignment_revision)) ?? emptyExecutorDraft();
    return { ...copyDraft(saved), afterPhotoIds: this.#photos.confirmedIds(this.photoContext(order)) };
  }
  view(order: Order | undefined): ExecutorView {
    if (!order || !this.visibleOrders().some(item => item.id === order.id && item.assignment_revision === order.assignment_revision)) return idleView(`${this.#sessionKey}:none`);
    // An older unknown effect for A still blocks a new assignment of A, never unrelated B.
    const entry = this.#unresolvedOrder(order.id) ?? this.#entries.get(executorScope(order.id, order.assignment_revision));
    if (!entry) return idleView(executorScope(order.id, order.assignment_revision));
    return { scope: entry.scope, mutation: { status: entry.status, error: entry.error }, pendingIntent: { ...entry.intent } };
  }
  quarantinedScopes(): string[] {
    const visible = this.visibleOrders();
    return [...this.#entries.values()].filter(entry => isIntentUnresolved(entry) && !visible.some(order => order.id === entry.orderId && order.assignment_revision === entry.assignmentRevision)).map(entry => entry.scope);
  }
  act(intent: ExecutorIntent): Promise<MutationOutcome> {
    if (!this.#currentSession()) return Promise.resolve({ kind: 'rejected', message: 'Сессия изменилась.' });
    return withNewIntentGuard(this.#unresolvedOrder(intent.orderId), () => {
      const source = this.#orders.getSnapshot();
      if (source.freshness !== 'fresh' || source.loadStatus !== 'ready' || source.incomplete) return Promise.resolve({ kind: 'rejected', message: 'Сначала загрузите актуальные доступные наряды.' });
      const order = this.visibleOrders().find(item => item.id === intent.orderId);
      if (!order || order.version !== intent.expectedVersion || order.assignment_revision !== intent.expectedAssignmentRevision) return Promise.resolve({ kind: 'conflict', message: 'Наряд или назначение изменились. Обновите данные.' });
      const photoContext = this.photoContext(order);
      if (intent.action === 'submit' && this.#photos.blocked(photoContext)) return Promise.resolve({ kind: 'rejected', message: 'Подтвердите загрузку выбранных фото или удалите неудачный выбор.' });
      let command: OrderCommandIntent;
      if (intent.action === 'submit') command = { action: 'submit', expected_version: intent.expectedVersion, payload: { work_description: intent.payload.workDescription, work_code_id: intent.payload.workCodeId, materials: intent.payload.materials.map(item => ({ material_id: item.materialId, quantity: item.quantity })), after_photo_ids: this.#photos.confirmedIds(photoContext), comment: intent.payload.comment } };
      else if (intent.action === 'pause' || intent.action === 'reject') command = { action: intent.action, expected_version: intent.expectedVersion, payload: { reason: intent.payload.reason } };
      else command = { action: intent.action, expected_version: intent.expectedVersion, payload: {} };
      const scope = executorScope(order.id, order.assignment_revision);
      let token: PreparedMutation<CommandResult>;
      try { token = this.#client.prepareCommand(order.id, command); }
      catch (error) { return Promise.resolve({ kind: 'rejected', message: safeErrorMessage(error) }); }
      const entry: Entry = { scope, orderId: order.id, assignmentRevision: order.assignment_revision, intent: { orderId: order.id, expectedVersion: intent.expectedVersion, action: intent.action }, token, status: 'pending', error: null, unresolved: false, startedConfirmation: this.#orders.confirmation, deniedAt: null };
      this.#entries.set(scope, entry);
      return this.#execute(entry);
    });
  }
  retry(scope: string): Promise<MutationOutcome> {
    const entry = this.#entries.get(scope);
    if (!this.#currentSession() || !entry) return Promise.resolve({ kind: 'rejected', message: 'Исходная операция недоступна в этой сессии.' });
    if (entry.status === 'confirmed') return Promise.resolve({ kind: 'confirmed' });
    return this.#execute(entry);
  }
  resolveConflict(scope: string): void {
    const entry = this.#entries.get(scope);
    if (!this.#currentSession() || !canResolveIntent(entry, this.#orders.getSnapshot()) || (entry && this.#unresolvedOrder(entry.orderId))) return;
    this.#entries.delete(scope); this.#emit();
  }
  #execute(entry: Entry): Promise<MutationOutcome> {
    if (entry.promise) return entry.promise;
    entry.status = 'pending'; entry.error = null; this.#emit();
    const task = (async (): Promise<MutationOutcome> => {
      try {
        const result = await this.#client.execute(entry.token);
        if (!this.#currentSession()) return { kind: 'rejected', message: 'Сессия изменилась.' };
        const current = this.#orders.getSnapshot().snapshot?.find(order => order.id === entry.orderId);
        const removedByNewerRead = this.#orders.confirmation > entry.startedConfirmation && !current;
        // Resolve the original effect without resurrecting an inaccessible old snapshot.
        if (this.#orders.access === 'allowed' && !removedByNewerRead && !this.#denied(entry.orderId)) this.#orders.record(result.order, this.#epoch);
        entry.status = 'confirmed'; entry.unresolved = false; entry.error = null;
        if (entry.intent.action === 'submit') { this.#drafts.delete(entry.scope); this.#photoGenerations.set(entry.scope, (this.#photoGenerations.get(entry.scope) ?? 0) + 1); }
        this.#emit();
        return { kind: 'confirmed' };
      } catch (error) {
        if (!this.#currentSession() || error instanceof SessionChangedError) return { kind: 'rejected', message: 'Сессия изменилась.' };
        entry.status = mutationFailureState(error, entry.unresolved); entry.unresolved = entry.status === 'unknown_result';
        if (error instanceof ApiError && (error.status === 403 || error.status === 404)) entry.deniedAt = this.#orders.confirmation;
        entry.error = entry.unresolved ? `Исход прежнего действия всё ещё не подтверждён. Последняя попытка: ${safeErrorMessage(error)}` : safeErrorMessage(error);
        this.#emit();
        return { kind: entry.unresolved ? 'unknown' : entry.status === 'conflict' ? 'conflict' : 'rejected', message: entry.error };
      } finally { entry.promise = undefined; }
    })();
    entry.promise = task; return task;
  }
}
