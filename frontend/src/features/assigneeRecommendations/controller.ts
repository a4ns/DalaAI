import { ApiError, SessionChangedError } from '../../shared/api/client';
import { assistanceRuntime, MasterSessionFence } from '../aiReports/session';
import type { AssistanceRuntime, AssistanceSession } from '../aiReports/session';
import { sameId, uuid } from '../aiReports/validation';
import { decodeAssigneeRecommendations } from './protocol';
import type { AssigneeRecommendations, AssigneeRecommendationRequest } from './protocol';

/** draftKey is a local fence only. Never send draft text as recommendation context. */
export interface AssigneeContext { sectionId: string; workCodeId: string | null; brigadeId: string; draftKey: string; dictionaryKey: string }
export interface EligibleExecutor { id: string; label: string; sectionIds: readonly string[]; brigadeId: string | null; onShift: boolean }
export type AssigneeTransport = (request: Readonly<AssigneeRecommendationRequest>, signal: AbortSignal) => Promise<unknown>;
export interface AssigneeState { status: 'idle' | 'loading' | 'ready' | 'expired' | 'error'; contextKey: string; data: AssigneeRecommendations | null; error: string | null }
export const assigneeContextKey = (context: AssigneeContext | null): string => context ? JSON.stringify([context.sectionId.toLowerCase(), context.workCodeId?.toLowerCase() ?? null, context.brigadeId.toLowerCase(), context.draftKey, context.dictionaryKey]) : '';
const initial = (contextKey = ''): AssigneeState => ({ status: 'idle', contextKey, data: null, error: null });
export function eligibleExecutor(executor: EligibleExecutor, context: AssigneeContext): boolean {
  return executor.onShift && executor.sectionIds.some(id => sameId(id, context.sectionId)) && (!context.brigadeId || sameId(executor.brigadeId, context.brigadeId));
}
/** Read-only ranking; choose() only returns a verified ID for an explicit draft edit. */
export class AssigneeRecommendationsController {
  #state = initial(); #listeners = new Set<() => void>(); #fence: MasterSessionFence;
  #key = ''; #run = 0; #readyUntil = 0; #abort: AbortController | null = null; #cancelExpiry: (() => void) | null = null;
  constructor(client: AssistanceSession, public transport: AssigneeTransport, public readContext: () => AssigneeContext | null, public readExecutors: () => readonly EligibleExecutor[], public isCurrent: () => boolean, public onAccessLost: (error: ApiError) => void = () => {}, readonly runtime: AssistanceRuntime = assistanceRuntime) {
    this.#fence = new MasterSessionFence(client, () => this.isCurrent(), runtime);
  }
  updatePorts(transport: AssigneeTransport, readContext: () => AssigneeContext | null, readExecutors: () => readonly EligibleExecutor[], isCurrent: () => boolean, onAccessLost: (error: ApiError) => void): void { this.transport = transport; this.readContext = readContext; this.readExecutors = readExecutors; this.isCurrent = isCurrent; this.onAccessLost = onAccessLost; }
  getSnapshot = (): AssigneeState => this.#state;
  subscribe = (listener: () => void): (() => void) => { this.#listeners.add(listener); return () => { this.#listeners.delete(listener); }; };
  #set(state: AssigneeState): void { this.#state = state; this.#listeners.forEach(l => l()); }
  #invalidate(): void { this.#run++; this.#abort?.abort(); this.#abort = null; this.#cancelExpiry?.(); this.#cancelExpiry = null; this.#readyUntil = 0; }
  clear = (): void => { this.#invalidate(); this.#set(initial(this.#key)); };
  attach = (): (() => void) => this.#fence.attach(this.clear);
  #current(key = this.#key): boolean { const context = this.readContext(); return this.#fence.current() && Boolean(context && this.#fence.client.session?.principal.section_ids.some(id => sameId(id, context.sectionId))) && assigneeContextKey(context) === key; }
  current = (): boolean => this.#current();
  synchronize = (): void => {
    const key = assigneeContextKey(this.readContext());
    if (key !== this.#key) { this.#key = key; this.clear(); }
    else if (!this.#current()) this.clear();
  };
  async load(): Promise<void> {
    this.synchronize(); if (!this.#current() || this.#state.status === 'loading') return;
    const context = { ...this.readContext()! };
    if (!uuid(context.sectionId) || (context.workCodeId !== null && !uuid(context.workCodeId))) return;
    this.#invalidate(); const run = this.#run; const key = this.#key;
    const request = Object.freeze({ section_id: context.sectionId, work_code_id: context.workCodeId, limit: 3 });
    this.#abort = new AbortController(); this.#set({ status: 'loading', contextKey: key, data: null, error: null });
    try {
      const response = await this.transport(request, this.#abort.signal);
      if (!this.#current(key) || run !== this.#run) return;
      const data = decodeAssigneeRecommendations(response, request, this.runtime.now());
      // Recheck against the current authorized dictionary, never just the old response.
      if (!data.candidates.every(candidate => this.readExecutors().some(executor => sameId(executor.id, candidate.executor_id) && eligibleExecutor(executor, { ...context, brigadeId: '' })))) throw new Error('Dictionary eligibility changed');
      const expiresIn = Math.min(30000, Date.parse(data.expires_at) - this.runtime.now());
      this.#readyUntil = this.runtime.now() + expiresIn;
      this.#cancelExpiry = this.runtime.schedule(() => {
        if (run !== this.#run) return;
        this.#invalidate(); this.#set({ status: 'expired', contextKey: key, data: null, error: null });
      }, expiresIn);
      this.#set({ status: 'ready', contextKey: key, data, error: null });
    } catch (error) {
      if (!this.#current(key) || run !== this.#run || error instanceof SessionChangedError) return;
      this.#set({ status: 'error', contextKey: key, data: null, error: error instanceof ApiError && error.status === 429 ? 'Слишком много запросов. Подождите указанную сервером задержку.' : 'Рекомендации не подтверждены. Проверьте доступ и актуальность справочников; повторите запрос.' });
      if (error instanceof ApiError && [401, 403, 404].includes(error.status)) this.onAccessLost(error);
    }
  }
  choose(executorId: string): string | null {
    const data = this.#state.data;
    if (!this.#current() || this.#state.status !== 'ready' || !data) { this.clear(); return null; }
    if (this.#readyUntil <= this.runtime.now() || Date.parse(data.expires_at) <= this.runtime.now()) { this.#invalidate(); this.#set({ status: 'expired', contextKey: this.#key, data: null, error: null }); return null; }
    const context = this.readContext()!;
    const candidate = data.candidates.find(row => sameId(row.executor_id, executorId));
    const executor = this.readExecutors().find(row => sameId(row.id, executorId) && eligibleExecutor(row, context));
    if (!candidate || !executor) { this.clear(); return null; }
    return executor.id;
  }
}
