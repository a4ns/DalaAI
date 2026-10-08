import type { CommandResult, CreateOrder, CreatePayload, Dictionaries, EventPage, Login, Order, OrderCommand, OrderPage, Problem, Session, StagedPhoto, Status, Submission } from './wire';
import { assertWire, isWire } from './validation';
import { isPushConfig, isPushConfirmation, validPushEndpoint, validPushRegistration } from './pushProtocol';
import type { PushApiConfig } from './pushProtocol';
import { isAnalyticsFacts, isOrderReport, isShiftReport, validPeriod } from './analyticsProtocol';
import type { AnalyticsFacts, OrderReport, PeriodRequest, ShiftReport } from './analyticsProtocol';
import { readReportFile, REPORT_FILE_MIME } from './reportFiles';
import type { ReportFile, ReportFileFormat, ReportFileKind } from './reportFiles';
import { isDemoClockChange, isDemoClockControl, isDemoClockSnapshot } from './demoClockProtocol';
import type { DemoClockChange, DemoClockControl, DemoClockSnapshot } from './demoClockProtocol';
import { decodeAiReport, isAiReport, validAiReportRequest } from '../../features/aiReports/protocol';
import type { AiReport, AiReportRequest } from '../../features/aiReports/protocol';
import { decodeAssigneeRecommendations, isAssigneeRecommendations } from '../../features/assigneeRecommendations/protocol';
import type { AssigneeRecommendationRequest, AssigneeRecommendations } from '../../features/assigneeRecommendations/protocol';
export interface PreparedDemoClock { readonly intent:Readonly<DemoClockControl> }
type ClockPrepared={epoch:number;body:string;snapshot:DemoClockSnapshot;intent:Readonly<DemoClockControl>;promise?:Promise<DemoClockSnapshot>};
type ApiProblem = Omit<Problem, 'code'> & { code: Problem['code'] | 'SUBSCRIPTION_CONFLICT' | 'PUSH_DISABLED' | 'REPORT_LIMIT_EXCEEDED' };

const BASE = '/api/v1';
type SchemaName = 'Session' | 'Order' | 'Dictionaries' | 'OrderPage' | 'EventPage' | 'Submission' | 'StagedPhoto' | 'CommandResult';
export interface PreparedMutation<T> { readonly operationId: string; readonly __resultType?: T }
type PhotoReceiptContext = Readonly<Pick<StagedPhoto, 'owner_id' | 'section_id' | 'purpose' | 'order_id' | 'assignment_revision'>>;
type Prepared = { epoch: number; path: string; body: string | Blob; contentType: string; schema: SchemaName; successStatus: number; inFlight?: Promise<unknown>; confirmed?: unknown; retryAt?: number; retryError?: ApiError; expectedOrderId?: string; expectedPhoto?: PhotoReceiptContext };
export type StagePhotoInput = { sectionId: string; file: File } & ({ purpose: 'before' } | { purpose: 'after'; orderId: string; assignmentRevision: number });
type WithoutOperation<T> = T extends unknown ? Omit<T, 'operation_id'> : never;
export type OrderCommandIntent = WithoutOperation<OrderCommand>;
export type OrderFilters = { status?: Status; section_id?: string; equipment_id?: string; executor_id?: string };

export class SessionChangedError extends Error {
  constructor() { super('Сессия изменилась. Ответ прежней сессии проигнорирован.'); this.name = 'SessionChangedError'; }
}
export class ApiError extends Error {
  readonly status: number;
  readonly problem: ApiProblem | null;
  readonly outcomeUnknown: boolean;
  readonly retryAfterSeconds: number | null;
  readonly transportInterrupted: boolean;
  constructor(message: string, status = 0, problem: ApiProblem | null = null, outcomeUnknown = false, retryAfterSeconds: number | null = null, transportInterrupted = false) {
    super(message); this.name = 'ApiError'; this.status = status; this.problem = problem; this.outcomeUnknown = outcomeUnknown; this.retryAfterSeconds = retryAfterSeconds; this.transportInterrupted = transportInterrupted;
  }
}
export class LoginError extends ApiError {
  readonly loginOutcome: 'rejected' | 'unknown';
  constructor(source: ApiError) {
    super(source.message, source.status, source.problem, false, source.retryAfterSeconds, source.transportInterrupted);
    this.name = 'LoginError';
    this.loginOutcome = source.transportInterrupted || source.status >= 500 || (source.status >= 200 && source.status < 300) ? 'unknown' : 'rejected';
  }
}
export function safeErrorMessage(error: unknown): string {
  if (error instanceof SessionChangedError) return error.message;
  if (error instanceof LoginError) {
    if (error.loginOutcome === 'unknown') return 'Ответ на запрос входа не подтверждён. Проверьте соединение и повторите вход, введя PIN заново.';
    if (error.status === 401) return 'Не удалось войти. Проверьте табельный код и PIN.';
    if (error.status === 0) return 'Нет соединения. Запрос входа не отправлен.';
  }
  if (!(error instanceof ApiError)) return 'Не удалось выполнить запрос. Повторите попытку.';
  if (error.outcomeUnknown) return 'Результат операции не подтверждён. Повторите тот же запрос.';
  if (error.status === 401) return 'Сессия завершена. Войдите снова.';
  if (error.status === 403) return 'Нет доступа к этому действию или объекту.';
  if (error.status === 409 && error.problem?.code === 'INCOMPLETE_SUBMISSION') return 'Закрытие невозможно: не хватает обязательных доказательств. Проверьте шифр работ и требуемые фото; результат можно вернуть на доработку.';
  if (error.status === 409) return error.problem?.code === 'OPERATION_ID_REUSED' ? 'Идентификатор операции уже использован с другими данными. Автоматический повтор остановлен.' : 'Данные изменились. Загрузите актуальное состояние и проверьте введённые значения.';
  if (error.status === 422) return 'Проверьте заполненные поля и обязательные доказательства.';
  if (error.status === 429) return 'Слишком много запросов. Повторите позже.';
  if (error.status === 413) return 'Файл слишком большой.';
  if (error.status === 415) return 'Формат изображения не поддерживается.';
  return error.message;
}
function retryDelay(value: string | null): number | null {
  if (!value) return null;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) return seconds;
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? Math.max(0, Math.ceil((timestamp - Date.now()) / 1000)) : null;
}
/** Bound successful JSON while streaming; a header is only an early refusal hint. */
async function readBoundedJson(response: Response, maximum: number, signal: AbortSignal, assertCurrent: () => void): Promise<unknown> {
  const declared = response.headers.get('Content-Length');
  if (declared && /^\d+$/.test(declared) && Number(declared) > maximum) { void response.body?.cancel().catch(() => undefined); throw new Error('Response too large'); }
  const reader = response.body?.getReader();
  if (!reader) throw new Error('Response body missing');
  const decoder = new TextDecoder('utf-8', { fatal: true }); let received = 0; let content = ''; let complete = false;
  const cancel = () => { void reader.cancel().catch(() => undefined); };
  signal.addEventListener('abort', cancel, { once: true });
  try {
    while (true) {
      assertCurrent(); signal.throwIfAborted();
      const chunk = await reader.read();
      assertCurrent(); signal.throwIfAborted();
      if (chunk.done) { complete = true; break; }
      received += chunk.value.byteLength;
      if (received > maximum) throw new Error('Response too large');
      content += decoder.decode(chunk.value, { stream: true });
    }
    return JSON.parse(content + decoder.decode()) as unknown;
  } finally {
    signal.removeEventListener('abort', cancel);
    if (!complete) void reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
function authorityKey(session: Session): string {
  const principal = session.principal;
  return JSON.stringify([principal.user_id, principal.role, principal.active, [...new Set(principal.section_ids)].sort()]);
}
function sameUuid(left: string | null, right: string | null): boolean {
  return left === null || right === null ? left === right : left.toLowerCase() === right.toLowerCase();
}
function id(value: string): string {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)) throw new Error('Invalid resource ID');
  return encodeURIComponent(value);
}

/** Same-origin cookie/CSRF client. No storage, token URLs, logging or implicit retries. */
export class ApiClient {
  #epoch = 0;
  #session: Session | null = null;
  #listeners = new Set<() => void>();
  #prepared = new WeakMap<object, Prepared>();
  #clockPrepared = new WeakMap<object,ClockPrepared>();
  #fetch: typeof fetch;
  #online: () => boolean;
  #timeout: number;
  #cooldowns = new Map<string, { until: number; status: number }>();
  constructor(options: { fetch?: typeof fetch; online?: () => boolean; timeoutMs?: number } = {}) {
    this.#fetch = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.#online = options.online ?? (() => typeof navigator === 'undefined' || navigator.onLine);
    this.#timeout = options.timeoutMs ?? 15000;
  }
  get epoch(): number { return this.#epoch; }
  get session(): Session | null { return this.#session; }
  subscribe(listener: () => void): () => void { this.#listeners.add(listener); return () => { this.#listeners.delete(listener); }; }
  clearIdentity(): void { this.#epoch += 1; this.#session = null; this.#listeners.forEach(listener => listener()); }
  #assertEpoch(epoch: number): void { if (epoch !== this.#epoch) throw new SessionChangedError(); }
  async #request<T>(path: string, options: { method?: 'GET' | 'POST'; body?: string | Blob; contentType?: string; schema?: SchemaName; successStatus?: number; epoch?: number; auth?: boolean; mutation?: boolean; signal?: AbortSignal; image?: boolean; validate?: (data: unknown) => boolean; push?: boolean; emptyBody?: boolean; analytics?: boolean; maxBytes?: number; streamJson?: boolean; reportFile?: {format:ReportFileFormat;filename:string} } = {}): Promise<T> {
    const epoch = options.epoch ?? this.#epoch;
    this.#assertEpoch(epoch);
    if (!this.#online()) throw new ApiError('Нет сети. Изменения не отправлены.');
    const routeKey = `${options.method ?? 'GET'} ${path.split('?')[0].replace(/[0-9a-f]{8}-[0-9a-f-]{27}/gi, ':id')}`;
    const cooldown = this.#cooldowns.get(routeKey);
    if (cooldown && cooldown.until > Date.now()) throw new ApiError('Повторите запрос после указанной сервером задержки.', cooldown.status, null, false, Math.ceil((cooldown.until - Date.now()) / 1000));
    this.#cooldowns.delete(routeKey);
    const headers = new Headers({ Accept: options.reportFile ? REPORT_FILE_MIME[options.reportFile.format] : options.image ? 'image/jpeg, image/png, image/webp' : 'application/json' });
    if (options.contentType) headers.set('Content-Type', options.contentType);
    if (options.method === 'POST' && options.auth !== false) {
      if (!this.#session) throw new ApiError('Сессия завершена. Войдите снова.', 401);
      headers.set('X-CSRF-Token', this.#session.csrf_token);
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.#timeout);
    const abort = () => controller.abort();
    options.signal?.addEventListener('abort', abort, { once: true });
    if (options.signal?.aborted) controller.abort();
    try {
      const response = await this.#fetch(BASE + path, { method: options.method ?? 'GET', credentials: 'same-origin', mode: 'same-origin', cache: 'no-store', redirect: 'error', headers, body: options.body, signal: controller.signal });
      this.#assertEpoch(epoch);
      if (response.status === 401) {
        this.clearIdentity();
        throw new ApiError('Сессия завершена. Войдите снова.', 401);
      }
      if (!response.ok) {
        let data: unknown = null;
        try { data = await response.json(); } catch { /* A proxy may return non-JSON. Never render its body. */ }
        this.#assertEpoch(epoch);
        let problem: ApiProblem | null = isWire<Problem>('Problem', data) ? data : null;
        if (options.push && data && typeof data === 'object' && 'code' in data && (data.code === 'SUBSCRIPTION_CONFLICT' || data.code === 'PUSH_DISABLED') && isWire<Problem>('Problem', { ...data, code: 'TEMPORARILY_UNAVAILABLE' })) problem = data as ApiProblem;
        if (options.analytics && data && typeof data === 'object' && 'code' in data && data.code === 'REPORT_LIMIT_EXCEEDED' && isWire<Problem>('Problem', { ...data, code: 'VALIDATION_FAILED' })) problem = data as ApiProblem;
        const delay = retryDelay(response.headers.get('Retry-After'));
        if ((response.status === 429 || response.status === 503) && delay !== null) this.#cooldowns.set(routeKey, { until: Date.now() + delay * 1000, status: response.status });
        throw new ApiError('Сервер отклонил запрос. Повторите позже.', response.status, problem, Boolean(options.mutation && response.status >= 500), delay);
      }
      if (response.status !== (options.successStatus ?? 200)) throw new ApiError('Получен неожиданный ответ сервера.', response.status, null, Boolean(options.mutation));
      if (response.status === 204) {
        if (options.emptyBody && (await response.text()) !== '') throw new ApiError('Ответ отключения не соответствует контракту.', response.status, null, Boolean(options.mutation));
        this.#assertEpoch(epoch); return undefined as T;
      }
      if (options.reportFile) {
        try { return await readReportFile(response, options.reportFile.format, options.reportFile.filename, () => { this.#assertEpoch(epoch); controller.signal.throwIfAborted(); }) as T; }
        catch(error) { await response.body?.cancel().catch(()=>undefined); if(error instanceof SessionChangedError) throw error; throw new ApiError('Файл отчёта не прошёл проверку формата или размера. Сохранение не начато.', response.status); }
      }
      if (options.image) {
        if (!['image/jpeg', 'image/png', 'image/webp'].includes(response.headers.get('Content-Type')?.split(';')[0] ?? '')) throw new ApiError('Сервер вернул неподдерживаемое изображение.', response.status);
        const blob = await response.blob(); this.#assertEpoch(epoch); return blob as T;
      }
      let data: unknown;
      try {
        if (options.maxBytes && options.streamJson) data = await readBoundedJson(response, options.maxBytes, controller.signal, () => this.#assertEpoch(epoch));
        else if (options.maxBytes) { const text = await response.text(); if (new TextEncoder().encode(text).length > options.maxBytes) throw new Error('Response too large'); data = JSON.parse(text); }
        else data = await response.json();
      } catch (error) { if (error instanceof SessionChangedError) throw error; throw new ApiError('Сервер вернул неподдерживаемый ответ.', response.status, null, Boolean(options.mutation)); }
      this.#assertEpoch(epoch);
      if (options.validate ? !options.validate(data) : !options.schema || !isWire<T>(options.schema, data)) throw new ApiError('Ответ сервера не соответствует согласованному контракту.', response.status, null, Boolean(options.mutation));
      return data as T;
    } catch (error) {
      if (error instanceof ApiError || error instanceof SessionChangedError) throw error;
      this.#assertEpoch(epoch);
      throw new ApiError(options.mutation ? 'Результат операции не подтверждён.' : 'Не удалось связаться с сервером.', 0, null, Boolean(options.mutation), null, true);
    } finally {
      clearTimeout(timeout); options.signal?.removeEventListener('abort', abort);
    }
  }
  async login(input: Login): Promise<Session> {
    assertWire('Login', input);
    this.clearIdentity();
    const epoch = this.#epoch;
    try {
      const session = await this.#request<Session>('/auth/login', { method: 'POST', body: JSON.stringify(input), contentType: 'application/json', auth: false, schema: 'Session', epoch });
      this.#assertEpoch(epoch); this.#session = session; this.#listeners.forEach(listener => listener()); return session;
    } catch (error) {
      if (error instanceof ApiError) throw new LoginError(error);
      throw error;
    }
  }
  async getMe(): Promise<Session> {
    const epoch = this.#epoch;
    const session = await this.#request<Session>('/me', { schema: 'Session', epoch });
    this.#assertEpoch(epoch);
    if (this.#session && (this.#session.csrf_token !== session.csrf_token || authorityKey(this.#session) !== authorityKey(session))) this.clearIdentity();
    this.#session = session; this.#listeners.forEach(listener => listener()); return session;
  }
  async logout(): Promise<void> {
    const epoch = this.#epoch;
    try { await this.#request<void>('/auth/logout', { method: 'POST', successStatus: 204, mutation: true }); }
    finally { if (this.#epoch === epoch) this.clearIdentity(); }
  }
  #analyticsQuery(period: PeriodRequest): string {
    if (!this.#session?.principal.active || !(Date.parse(this.#session.expires_at) > Date.now())) throw new ApiError('Сессия завершена. Войдите снова.', 401);
    if (this.#session.principal.role !== 'master' || !this.#session.principal.section_ids.length) throw new ApiError('Отчёты доступны мастеру с разрешённым участком.', 403);
    if (!validPeriod(period)) throw new ApiError('Укажите корректный период не более 93 суток.', 422);
    return new URLSearchParams({ start: period.start, end: period.end, format: 'json' }).toString();
  }
  async #report<T extends AnalyticsFacts | ShiftReport | OrderReport>(path: string, period: PeriodRequest, validate: (data: unknown) => boolean, signal?: AbortSignal): Promise<T> {
    const start=period.start, end=period.end;
    const result = await this.#request<T>(`${path}?${this.#analyticsQuery({ start, end })}`, { validate, signal, analytics: true, maxBytes: 8 * 1024 * 1024 });
    if (Date.parse(result.period.start)!==Date.parse(start) || Date.parse(result.period.end)!==Date.parse(end)) throw new ApiError('Ответ относится к другому периоду. Загрузите отчёт снова.');
    return result;
  }
  getShiftAnalytics(period: PeriodRequest, signal?: AbortSignal): Promise<AnalyticsFacts> { return this.#report('/analytics/shift', period, isAnalyticsFacts, signal); }
  getShiftReport(period: PeriodRequest, signal?: AbortSignal): Promise<ShiftReport> { return this.#report('/reports/shift', period, isShiftReport, signal); }
  async getOrderReport(orderId: string, period: PeriodRequest, signal?: AbortSignal): Promise<OrderReport> {
    const result = await this.#report<OrderReport>(`/reports/orders/${id(orderId)}`, period, isOrderReport, signal);
    if (result.order.order.id.toLowerCase() !== orderId.toLowerCase()) throw new ApiError('Ответ содержит отчёт другого наряда.');
    return result;
  }
  async getReportFile(kind:ReportFileKind, format:ReportFileFormat, period:PeriodRequest, signal?:AbortSignal):Promise<ReportFile> {
    if(format!=='pdf'&&format!=='xlsx')throw new ApiError('Формат отчёта не поддерживается.');
    const query=new URLSearchParams(this.#analyticsQuery(period));query.delete('format');
    const suffix=kind==='shift'?'shift':`orders/${id(kind.orderId).toLowerCase()}`;
    const filename=`naryadai-${kind==='shift'?'shift':`order-${kind.orderId.toLowerCase()}`}.${format}`;
    return this.#request(`/reports/${suffix}.${format}?${query}`,{signal,analytics:true,reportFile:{format,filename}});
  }
  #assertAssistanceSession(): void {
    if (!this.#session?.principal.active || !(Date.parse(this.#session.expires_at) > Date.now())) throw new ApiError('Сессия завершена. Войдите снова.', 401);
    if (this.#session.principal.role !== 'master' || !this.#session.principal.section_ids.length) throw new ApiError('Подсказки доступны мастеру с разрешённым участком.', 403);
  }
  async createAiSummary(input: Readonly<AiReportRequest>, signal?: AbortSignal): Promise<AiReport> {
    this.#assertAssistanceSession();
    if (!validAiReportRequest(input)) throw new ApiError('Проверьте период и вид сводки.', 422);
    const epoch = this.#epoch;
    const request = Object.freeze({ operation_id: input.operation_id, start: input.start, end: input.end, report_kind: input.report_kind });
    const value = await this.#request<AiReport>('/reports/ai-summary', { method: 'POST', contentType: 'application/json', body: JSON.stringify(request), epoch, signal, mutation: true, analytics: true, maxBytes: 1024 * 1024, streamJson: true, validate: isAiReport });
    this.#assertEpoch(epoch); this.#assertAssistanceSession();
    try { return decodeAiReport(value, request); }
    catch { throw new ApiError('Ответ сводки не соответствует исходному запросу.', 200, null, true); }
  }
  async getAssigneeRecommendations(input: Readonly<AssigneeRecommendationRequest>, signal?: AbortSignal): Promise<AssigneeRecommendations> {
    this.#assertAssistanceSession();
    const validId = (value: unknown): value is string => typeof value === 'string' && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(value);
    if (!validId(input.section_id) || (input.work_code_id !== null && !validId(input.work_code_id)) || !Number.isSafeInteger(input.limit) || input.limit < 1 || input.limit > 5) throw new ApiError('Проверьте участок и параметры рекомендаций.', 422);
    const request = Object.freeze({ section_id: input.section_id, work_code_id: input.work_code_id, limit: input.limit });
    if (!this.#session!.principal.section_ids.some(section => sameUuid(section, request.section_id))) throw new ApiError('Нет доступа к выбранному участку.', 403);
    const epoch = this.#epoch; const query = new URLSearchParams({ section_id: request.section_id, limit: String(request.limit) });
    if (request.work_code_id !== null) query.set('work_code_id', request.work_code_id);
    const value = await this.#request<AssigneeRecommendations>(`/recommendations/assignees?${query}`, { epoch, signal, maxBytes: 512 * 1024, streamJson: true, validate: isAssigneeRecommendations });
    this.#assertEpoch(epoch); this.#assertAssistanceSession();
    if (!this.#session!.principal.section_ids.some(section => sameUuid(section, request.section_id))) throw new ApiError('Доступ к выбранному участку изменился.', 403);
    try { return decodeAssigneeRecommendations(value, request); }
    catch { throw new ApiError('Рекомендации устарели или относятся к другому участку.', 200); }
  }
  #assertClockSession():void {
    if(!this.#session?.principal.active||!(Date.parse(this.#session.expires_at)>Date.now()))throw new ApiError('Сессия завершена. Войдите снова.',401);
    if(this.#session.principal.role!=='master')throw new ApiError('Демо-время доступно только разрешённому оператору.',403);
  }
  async getDemoClock(signal?:AbortSignal):Promise<DemoClockSnapshot> {
    this.#assertClockSession();return this.#request('/demo/clock',{validate:isDemoClockSnapshot,signal,maxBytes:4096});
  }
  prepareDemoClock(snapshot:DemoClockSnapshot,change:DemoClockChange):PreparedDemoClock {
    this.#assertClockSession();
    if(!isDemoClockChange(change))throw new ApiError('Проверьте допустимое целое значение демо-времени.',422);
    if(!isDemoClockSnapshot(snapshot)||snapshot.version>=2147483647)throw new ApiError('Версия демо-времени недоступна для изменения.');
    const intent=Object.freeze({instance_id:snapshot.instance_id,expected_version:snapshot.version,...change});
    if(!isDemoClockControl(intent))throw new ApiError('Проверьте допустимое целое значение демо-времени.',422);
    const token=Object.freeze({intent});
    this.#clockPrepared.set(token,{epoch:this.#epoch,body:JSON.stringify(intent),snapshot:Object.freeze({...snapshot,limits:Object.freeze({...snapshot.limits})}),intent});return token;
  }
  executeDemoClock(token:PreparedDemoClock):Promise<DemoClockSnapshot> {
    const prepared=this.#clockPrepared.get(token);
    if(!prepared)return Promise.reject(new ApiError('Неизвестное действие демо-времени.'));
    try{this.#assertEpoch(prepared.epoch);this.#assertClockSession();}catch(error){return Promise.reject(error);}
    // A token is sent at most once. A repeated call observes the same settled promise,
    // including an unknown result; it is NOT an idempotent domain receipt or a retry.
    prepared.promise??=Promise.resolve().then(async()=>{
      const result=await this.#request<DemoClockSnapshot>('/demo/clock',{method:'POST',body:prepared.body,contentType:'application/json',epoch:prepared.epoch,validate:isDemoClockSnapshot,mutation:true,maxBytes:4096});
      const old=prepared.snapshot,intent=prepared.intent;
      const minimum=Date.parse(old.domain_now)+(intent.action==='advance'?intent.seconds*1000:0);
      if(result.instance_id!==intent.instance_id||result.version!==intent.expected_version+1||result.scale!==(intent.action==='set_scale'?intent.scale:old.scale)||Date.parse(result.domain_now)<minimum||result.domain_limit!==old.domain_limit||result.real_anchor!==result.real_now||result.domain_anchor!==result.domain_now)throw new ApiError('Ответ изменения демо-времени не соответствует исходному действию.',200,null,true);
      return result;
    });return prepared.promise;
  }
  #assertPushSession(): void {
    if (!this.#session?.principal.active || !(Date.parse(this.#session.expires_at) > Date.now())) throw new ApiError('Сессия завершена. Войдите снова.', 401);
  }
  getPushConfig(): Promise<PushApiConfig> {
    this.#assertPushSession();
    return this.#request('/push/config', { validate: isPushConfig, push: true });
  }
  async registerPushSubscription(body: string): Promise<void> {
    this.#assertPushSession();
    if (!validPushRegistration(body)) throw new ApiError('Некорректная подписка. Запрос не отправлен.');
    await this.#request('/push/subscriptions', { method: 'POST', body, contentType: 'application/json', validate: isPushConfirmation, mutation: true, push: true });
  }
  async removePushSubscription(endpoint: string): Promise<void> {
    this.#assertPushSession();
    const body = JSON.stringify({ endpoint });
    if (!validPushEndpoint(endpoint) || new TextEncoder().encode(body).length > 4096) throw new ApiError('Некорректная подписка. Запрос не отправлен.');
    await this.#request('/push/subscriptions/remove', { method: 'POST', body, contentType: 'application/json', successStatus: 204, emptyBody: true, mutation: true, push: true });
  }
  getDictionaries(signal?: AbortSignal): Promise<Dictionaries> { return this.#request('/dicts', { schema: 'Dictionaries', signal }); }
  getPhoto(photoId: string, signal?: AbortSignal): Promise<Blob> { return this.#request(`/photos/${id(photoId)}`, { image: true, signal }); }
  async getOrder(orderId: string, signal?: AbortSignal): Promise<Order> {
    const order = await this.#request<Order>(`/orders/${id(orderId)}`, { schema: 'Order', signal });
    if (order.id.toLowerCase() !== orderId.toLowerCase()) throw new ApiError('Ответ содержит другой наряд.');
    return order;
  }
  async getSubmission(orderId: string, submissionId: string, signal?: AbortSignal): Promise<Submission> {
    const submission = await this.#request<Submission>(`/orders/${id(orderId)}/submissions/${id(submissionId)}`, { schema: 'Submission', signal });
    if (submission.order_id.toLowerCase() !== orderId.toLowerCase() || submission.id.toLowerCase() !== submissionId.toLowerCase()) throw new ApiError('Ответ содержит результат другого наряда или попытки.');
    return submission;
  }
  listOrders(filters: OrderFilters = {}, cursor?: string, signal?: AbortSignal): Promise<OrderPage> {
    const query = new URLSearchParams({ ...filters, limit: '100' }); if (cursor) query.set('cursor', cursor);
    return this.#request(`/orders?${query}`, { schema: 'OrderPage', signal });
  }
  async listOrderEvents(orderId: string, afterSequence = 0, signal?: AbortSignal): Promise<EventPage> {
    if (!Number.isSafeInteger(afterSequence) || afterSequence < 0) return Promise.reject(new ApiError('Курсор истории не может быть безопасно представлен. Запрос не отправлен.'));
    const page = await this.#request<EventPage>(`/orders/${id(orderId)}/events?after_sequence=${afterSequence}&limit=200`, { schema: 'EventPage', signal });
    if (page.items.some(event => event.order_id.toLowerCase() !== orderId.toLowerCase())) throw new ApiError('История содержит событие другого наряда.');
    return page;
  }
  prepareCreate(payload: CreatePayload): PreparedMutation<CommandResult> {
    const body: CreateOrder = { operation_id: crypto.randomUUID(), expected_version: 0, action: 'create', payload };
    assertWire('CreateOrder', body); return this.#prepare(body.operation_id, '/orders', JSON.stringify(body), 'CommandResult', 201);
  }
  prepareCommand(orderId: string, command: OrderCommandIntent): PreparedMutation<CommandResult> {
    const body = { ...command, operation_id: crypto.randomUUID() };
    assertWire('OrderCommand', body); return this.#prepare(body.operation_id, `/orders/${id(orderId)}/commands`, JSON.stringify(body), 'CommandResult', 200, 'application/json', orderId);
  }
  #prepare<T>(operationId: string, path: string, body: string | Blob, schema: SchemaName, successStatus: number, contentType = 'application/json', expectedOrderId?: string, expectedPhoto?: PhotoReceiptContext): PreparedMutation<T> {
    if (!this.#session) throw new ApiError('Сначала войдите в систему.', 401);
    const token = Object.freeze({ operationId });
    this.#prepared.set(token, { epoch: this.#epoch, path, body, contentType, schema, successStatus, expectedOrderId, expectedPhoto });
    return token;
  }
  async preparePhoto(input: StagePhotoInput): Promise<PreparedMutation<StagedPhoto>> {
    id(input.sectionId);
    if (input.purpose === 'after') {
      id(input.orderId);
      if (!Number.isSafeInteger(input.assignmentRevision) || input.assignmentRevision < 1) throw new ApiError('Некорректная версия назначения. Фото не отправлено.');
    }
    if (!this.#session) throw new ApiError('Сначала войдите в систему.', 401);
    const epoch = this.#epoch;
    // Snapshot primitives before serialization yields: later caller edits must not alter receipt binding.
    const expectedPhoto: PhotoReceiptContext = Object.freeze({
      owner_id: this.#session.principal.user_id, section_id: input.sectionId, purpose: input.purpose,
      order_id: input.purpose === 'after' ? input.orderId : null,
      assignment_revision: input.purpose === 'after' ? input.assignmentRevision : null,
    });
    const operationId = crypto.randomUUID();
    const form = new FormData();
    form.set('section_id', expectedPhoto.section_id); form.set('operation_id', operationId); form.set('expected_version', '0'); form.set('purpose', expectedPhoto.purpose);
    if (expectedPhoto.purpose === 'after') { form.set('order_id', expectedPhoto.order_id!); form.set('assignment_revision', String(expectedPhoto.assignment_revision)); }
    form.set('file', input.file);
    // Capture the encoded body once, including boundary and immutable original file bytes.
    const request = new Request('https://same-origin.invalid/api/v1/photos/stage', { method: 'POST', body: form });
    const body = await request.blob(); this.#assertEpoch(epoch);
    return this.#prepare(operationId, '/photos/stage', body, 'StagedPhoto', 201, request.headers.get('content-type')!, undefined, expectedPhoto);
  }
  execute<T>(token: PreparedMutation<T>): Promise<T> {
    const prepared = this.#prepared.get(token);
    if (!prepared) return Promise.reject(new Error('Unknown prepared intent'));
    try { this.#assertEpoch(prepared.epoch); } catch (error) { return Promise.reject(error); }
    if (prepared.retryAt && prepared.retryAt > Date.now()) return Promise.reject(prepared.retryError);
    if (prepared.confirmed !== undefined) return Promise.resolve(prepared.confirmed as T);
    if (prepared.inFlight) return prepared.inFlight as Promise<T>;
    const promise = this.#request<T>(prepared.path, { ...prepared, method: 'POST', mutation: true }).then(result => {
      if (prepared.expectedOrderId && (result as CommandResult).order.id.toLowerCase() !== prepared.expectedOrderId.toLowerCase()) throw new ApiError('Ответ операции относится к другому наряду. Результат не подтверждён.', 200, null, true);
      if (prepared.expectedPhoto) {
        const photo = result as StagedPhoto; const expected = prepared.expectedPhoto;
        if (!sameUuid(photo.owner_id, expected.owner_id) || !sameUuid(photo.section_id, expected.section_id) || photo.purpose !== expected.purpose || !sameUuid(photo.order_id, expected.order_id) || photo.assignment_revision !== expected.assignment_revision) {
          throw new ApiError('Ответ загрузки относится к другому контексту. Результат не подтверждён.', prepared.successStatus, null, true);
        }
      }
      prepared.confirmed = result; return result;
    }).catch((error: unknown) => {
      if (error instanceof ApiError && error.retryAfterSeconds !== null) { prepared.retryAt = Date.now() + error.retryAfterSeconds * 1000; prepared.retryError = error; }
      throw error;
    }).finally(() => { prepared.inFlight = undefined; });
    prepared.inFlight = promise; return promise;
  }
}
