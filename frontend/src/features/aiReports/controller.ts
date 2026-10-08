import { ApiError, SessionChangedError } from '../../shared/api/client';
import { validPeriod } from '../../shared/api/analyticsProtocol';
import { aiReportSelectionKey, decodeAiReport, validAiReportRequest } from './protocol';
import type { AiReport, AiReportKind, AiReportRequest, AiReportSelection } from './protocol';
import { assistanceRuntime, MasterSessionFence } from './session';
import type { AssistanceRuntime, AssistanceSession } from './session';

export type AiReportTransport = (request: Readonly<AiReportRequest>, signal: AbortSignal) => Promise<unknown>;
export interface AiReportState {
  status: 'idle' | 'loading' | 'ready' | 'error' | 'unknown_result';
  selectionKey: string; data: AiReport | null; error: string | null;
}
const initial = (selectionKey = ''): AiReportState => ({ status: 'idle', selectionKey, data: null, error: null });
/** Explicit requests only. Unknown retries retain the exact operation and body. */
export class AiReportController {
  #state = initial(); #listeners = new Set<() => void>(); #fence: MasterSessionFence;
  #selection: AiReportSelection | null = null; #request: Readonly<AiReportRequest> | null = null;
  #run = 0; #abort: AbortController | null = null;
  constructor(client: AssistanceSession, public transport: AiReportTransport, public isCurrent: () => boolean, public onAccessLost: (error: ApiError) => void = () => {}, readonly runtime: AssistanceRuntime = assistanceRuntime) {
    this.#fence = new MasterSessionFence(client, () => this.isCurrent(), runtime);
  }
  updatePorts(transport: AiReportTransport, isCurrent: () => boolean, onAccessLost: (error: ApiError) => void): void { this.transport = transport; this.isCurrent = isCurrent; this.onAccessLost = onAccessLost; }
  getSnapshot = (): AiReportState => this.#state;
  subscribe = (listener: () => void): (() => void) => { this.#listeners.add(listener); return () => { this.#listeners.delete(listener); }; };
  #set(state: AiReportState): void { this.#state = state; this.#listeners.forEach(l => l()); }
  #invalidate(): void { this.#run++; this.#abort?.abort(); this.#abort = null; }
  clear = (): void => { this.#invalidate(); this.#request = null; this.#set(initial(aiReportSelectionKey(this.#selection))); };
  attach = (): (() => void) => this.#fence.attach(this.clear);
  current = (): boolean => this.#fence.current();
  setSelection(selection: AiReportSelection | null): void {
    if (aiReportSelectionKey(selection) === aiReportSelectionKey(this.#selection)) return;
    this.#selection = selection ? Object.freeze({ ...selection }) : null; this.clear();
  }
  async generate(kind: AiReportKind): Promise<void> {
    if (!this.#fence.current()) { this.clear(); return; }
    if (this.#state.status === 'loading' || this.#state.status === 'unknown_result' || !this.#selection) return;
    const selection = this.#selection;
    if (!validPeriod(selection) || (kind === 'shift' && Date.parse(selection.end) - Date.parse(selection.start) > 86400000)) {
      this.#set({ ...initial(aiReportSelectionKey(selection)), status: 'error', error: 'Для смены выберите период до 24 часов; для истории — до 93 суток.' }); return;
    }
    const request = Object.freeze({ operation_id: this.runtime.uuid(), start: selection.start, end: selection.end, report_kind: kind });
    if (!validAiReportRequest(request)) { this.#set({ ...initial(aiReportSelectionKey(selection)), status: 'error', error: 'Не удалось подготовить запрос сводки.' }); return; }
    this.#request = request; await this.#send(false);
  }
  async retry(): Promise<void> {
    if (this.#state.status !== 'unknown_result' || !this.#request) return;
    await this.#send(true);
  }
  async #send(unresolved: boolean): Promise<void> {
    if (!this.#fence.current()) { this.clear(); return; }
    const request = this.#request; if (!request) return;
    this.#invalidate(); const run = this.#run; const key = aiReportSelectionKey(this.#selection);
    this.#abort = new AbortController(); this.#set({ status: 'loading', selectionKey: key, data: null, error: null });
    try {
      const response = await this.transport(request, this.#abort.signal);
      if (!this.#fence.current() || run !== this.#run) return;
      const data = decodeAiReport(response, request);
      this.#set({ status: 'ready', selectionKey: key, data, error: null }); this.#request = null;
    } catch (error) {
      if (!this.#fence.current() || run !== this.#run || error instanceof SessionChangedError) return;
      const denied = error instanceof ApiError && [401, 403, 404].includes(error.status);
      const uncertain = unresolved || !(error instanceof ApiError) || error.outcomeUnknown || error.transportInterrupted || error.status >= 500 || (error.status >= 200 && error.status < 300);
      const status = uncertain ? 'unknown_result' : 'error';
      let message = uncertain ? 'Результат запроса не подтверждён. Повтор использует тот же запрос; сервер может вернуть фактический резервный отчёт вместо прежнего ответа модели.' : 'Сводка недоступна. Проверьте период и доступ; повторите позже.';
      if (denied) message = 'Доступ к сводке утрачен. Прежние данные скрыты. Проверьте текущую сессию.';
      if (error instanceof ApiError && error.status === 429) message = uncertain ? 'Результат прежнего запроса остаётся неизвестным. Подождите указанную сервером задержку перед повтором.' : 'Слишком много запросов. Подождите указанную сервером задержку.';
      this.#set({ status, selectionKey: key, data: null, error: message });
      if (!uncertain) this.#request = null;
      if (denied) this.onAccessLost(error as ApiError);
    }
  }
}
