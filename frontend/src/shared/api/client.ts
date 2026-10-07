import type { CommandResult, CreateOrder, CreatePayload, Dictionaries, EventPage, Login, Order, OrderCommand, OrderPage, Problem, Session, StagedPhoto, Status, Submission } from './wire';
import { assertWire, isWire } from './validation';

const BASE = '/api/v1';
type SchemaName = 'Session' | 'Order' | 'Dictionaries' | 'OrderPage' | 'EventPage' | 'Submission' | 'StagedPhoto' | 'CommandResult';
export interface PreparedMutation<T> { readonly operationId: string; readonly __resultType?: T }
type Prepared = { epoch: number; path: string; body: string | Blob; contentType: string; schema: SchemaName; successStatus: number; inFlight?: Promise<unknown>; confirmed?: unknown; retryAt?: number; retryError?: ApiError };
export type StagePhotoInput = { sectionId: string; file: File } & ({ purpose: 'before' } | { purpose: 'after'; orderId: string; assignmentRevision: number });
type WithoutOperation<T> = T extends unknown ? Omit<T, 'operation_id'> : never;
export type OrderCommandIntent = WithoutOperation<OrderCommand>;
export type OrderFilters = { status?: Status; section_id?: string; equipment_id?: string; executor_id?: string };

export class SessionChangedError extends Error {
  constructor() { super('Сессия изменилась. Ответ прежней сессии проигнорирован.'); this.name = 'SessionChangedError'; }
}
export class ApiError extends Error {
  readonly status: number;
  readonly problem: Problem | null;
  readonly outcomeUnknown: boolean;
  readonly retryAfterSeconds: number | null;
  constructor(message: string, status = 0, problem: Problem | null = null, outcomeUnknown = false, retryAfterSeconds: number | null = null) {
    super(message); this.name = 'ApiError'; this.status = status; this.problem = problem; this.outcomeUnknown = outcomeUnknown; this.retryAfterSeconds = retryAfterSeconds;
  }
}
export function safeErrorMessage(error: unknown): string {
  if (error instanceof SessionChangedError) return error.message;
  if (!(error instanceof ApiError)) return 'Не удалось выполнить запрос. Повторите попытку.';
  if (error.outcomeUnknown) return 'Результат операции не подтверждён. Повторите тот же запрос.';
  if (error.status === 401) return 'Сессия завершена. Войдите снова.';
  if (error.status === 403) return 'Нет доступа к этому действию или объекту.';
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
  async #request<T>(path: string, options: { method?: 'GET' | 'POST'; body?: string | Blob; contentType?: string; schema?: SchemaName; successStatus?: number; epoch?: number; auth?: boolean; mutation?: boolean; signal?: AbortSignal; image?: boolean } = {}): Promise<T> {
    const epoch = options.epoch ?? this.#epoch;
    this.#assertEpoch(epoch);
    if (!this.#online()) throw new ApiError('Нет сети. Изменения не отправлены.');
    const routeKey = `${options.method ?? 'GET'} ${path.split('?')[0].replace(/[0-9a-f]{8}-[0-9a-f-]{27}/gi, ':id')}`;
    const cooldown = this.#cooldowns.get(routeKey);
    if (cooldown && cooldown.until > Date.now()) throw new ApiError('Повторите запрос после указанной сервером задержки.', cooldown.status, null, false, Math.ceil((cooldown.until - Date.now()) / 1000));
    this.#cooldowns.delete(routeKey);
    const headers = new Headers({ Accept: options.image ? 'image/jpeg, image/png, image/webp' : 'application/json' });
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
        const problem = isWire<Problem>('Problem', data) ? data : null;
        const delay = retryDelay(response.headers.get('Retry-After'));
        if ((response.status === 429 || response.status === 503) && delay !== null) this.#cooldowns.set(routeKey, { until: Date.now() + delay * 1000, status: response.status });
        throw new ApiError('Сервер отклонил запрос. Повторите позже.', response.status, problem, Boolean(options.mutation && response.status >= 500), delay);
      }
      if (response.status !== (options.successStatus ?? 200)) throw new ApiError('Получен неожиданный ответ сервера.', response.status, null, Boolean(options.mutation));
      if (response.status === 204) return undefined as T;
      if (options.image) {
        if (!['image/jpeg', 'image/png', 'image/webp'].includes(response.headers.get('Content-Type')?.split(';')[0] ?? '')) throw new ApiError('Сервер вернул неподдерживаемое изображение.', response.status);
        const blob = await response.blob(); this.#assertEpoch(epoch); return blob as T;
      }
      let data: unknown;
      try { data = await response.json(); } catch { throw new ApiError('Сервер вернул неподдерживаемый ответ.', response.status, null, Boolean(options.mutation)); }
      this.#assertEpoch(epoch);
      if (!options.schema || !isWire<T>(options.schema, data)) throw new ApiError('Ответ сервера не соответствует согласованному контракту.', response.status, null, Boolean(options.mutation));
      return data;
    } catch (error) {
      if (error instanceof ApiError || error instanceof SessionChangedError) throw error;
      this.#assertEpoch(epoch);
      throw new ApiError(options.mutation ? 'Результат операции не подтверждён.' : 'Не удалось связаться с сервером.', 0, null, Boolean(options.mutation));
    } finally {
      clearTimeout(timeout); options.signal?.removeEventListener('abort', abort);
    }
  }
  async login(input: Login): Promise<Session> {
    assertWire('Login', input);
    this.clearIdentity();
    const epoch = this.#epoch;
    const session = await this.#request<Session>('/auth/login', { method: 'POST', body: JSON.stringify(input), contentType: 'application/json', auth: false, schema: 'Session', epoch });
    this.#assertEpoch(epoch); this.#session = session; this.#listeners.forEach(listener => listener()); return session;
  }
  async getMe(): Promise<Session> {
    const epoch = this.#epoch;
    const session = await this.#request<Session>('/me', { schema: 'Session', epoch });
    this.#assertEpoch(epoch);
    if (this.#session && this.#session.principal.user_id !== session.principal.user_id) this.clearIdentity();
    this.#session = session; this.#listeners.forEach(listener => listener()); return session;
  }
  async logout(): Promise<void> {
    const epoch = this.#epoch;
    try { await this.#request<void>('/auth/logout', { method: 'POST', successStatus: 204, mutation: true }); }
    finally { if (this.#epoch === epoch) this.clearIdentity(); }
  }
  getDictionaries(signal?: AbortSignal): Promise<Dictionaries> { return this.#request('/dicts', { schema: 'Dictionaries', signal }); }
  getPhoto(photoId: string, signal?: AbortSignal): Promise<Blob> { return this.#request(`/photos/${id(photoId)}`, { image: true, signal }); }
  getOrder(orderId: string, signal?: AbortSignal): Promise<Order> { return this.#request(`/orders/${id(orderId)}`, { schema: 'Order', signal }); }
  getSubmission(orderId: string, submissionId: string, signal?: AbortSignal): Promise<Submission> { return this.#request(`/orders/${id(orderId)}/submissions/${id(submissionId)}`, { schema: 'Submission', signal }); }
  listOrders(filters: OrderFilters = {}, cursor?: string, signal?: AbortSignal): Promise<OrderPage> {
    const query = new URLSearchParams({ ...filters, limit: '100' }); if (cursor) query.set('cursor', cursor);
    return this.#request(`/orders?${query}`, { schema: 'OrderPage', signal });
  }
  listOrderEvents(orderId: string, afterSequence = 0, signal?: AbortSignal): Promise<EventPage> {
    if (!Number.isSafeInteger(afterSequence) || afterSequence < 0) return Promise.reject(new ApiError('Курсор истории не может быть безопасно представлен. Запрос не отправлен.'));
    return this.#request(`/orders/${id(orderId)}/events?after_sequence=${afterSequence}&limit=200`, { schema: 'EventPage', signal });
  }
  prepareCreate(payload: CreatePayload): PreparedMutation<CommandResult> {
    const body: CreateOrder = { operation_id: crypto.randomUUID(), expected_version: 0, action: 'create', payload };
    assertWire('CreateOrder', body); return this.#prepare(body.operation_id, '/orders', JSON.stringify(body), 'CommandResult', 201);
  }
  prepareCommand(orderId: string, command: OrderCommandIntent): PreparedMutation<CommandResult> {
    const body = { ...command, operation_id: crypto.randomUUID() };
    assertWire('OrderCommand', body); return this.#prepare(body.operation_id, `/orders/${id(orderId)}/commands`, JSON.stringify(body), 'CommandResult', 200);
  }
  #prepare<T>(operationId: string, path: string, body: string | Blob, schema: SchemaName, successStatus: number, contentType = 'application/json'): PreparedMutation<T> {
    if (!this.#session) throw new ApiError('Сначала войдите в систему.', 401);
    const token = Object.freeze({ operationId });
    this.#prepared.set(token, { epoch: this.#epoch, path, body, contentType, schema, successStatus });
    return token;
  }
  async preparePhoto(input: StagePhotoInput): Promise<PreparedMutation<StagedPhoto>> {
    id(input.sectionId);
    if (input.purpose === 'after') {
      id(input.orderId);
      if (!Number.isSafeInteger(input.assignmentRevision) || input.assignmentRevision < 1) throw new ApiError('Некорректная версия назначения. Фото не отправлено.');
    }
    const epoch = this.#epoch;
    const operationId = crypto.randomUUID();
    const form = new FormData();
    form.set('section_id', input.sectionId); form.set('operation_id', operationId); form.set('expected_version', '0'); form.set('purpose', input.purpose);
    if (input.purpose === 'after') { form.set('order_id', input.orderId); form.set('assignment_revision', String(input.assignmentRevision)); }
    form.set('file', input.file);
    // Capture the encoded body once, including boundary and immutable original file bytes.
    const request = new Request('https://same-origin.invalid/api/v1/photos/stage', { method: 'POST', body: form });
    const body = await request.blob(); this.#assertEpoch(epoch);
    return this.#prepare(operationId, '/photos/stage', body, 'StagedPhoto', 201, request.headers.get('content-type')!);
  }
  execute<T>(token: PreparedMutation<T>): Promise<T> {
    const prepared = this.#prepared.get(token);
    if (!prepared) return Promise.reject(new Error('Unknown prepared intent'));
    try { this.#assertEpoch(prepared.epoch); } catch (error) { return Promise.reject(error); }
    if (prepared.retryAt && prepared.retryAt > Date.now()) return Promise.reject(prepared.retryError);
    if (prepared.confirmed !== undefined) return Promise.resolve(prepared.confirmed as T);
    if (prepared.inFlight) return prepared.inFlight as Promise<T>;
    const promise = this.#request<T>(prepared.path, { ...prepared, method: 'POST', mutation: true }).then(result => { prepared.confirmed = result; return result; }).catch((error: unknown) => {
      if (error instanceof ApiError && error.retryAfterSeconds !== null) { prepared.retryAt = Date.now() + error.retryAfterSeconds * 1000; prepared.retryError = error; }
      throw error;
    }).finally(() => { prepared.inFlight = undefined; });
    prepared.inFlight = promise; return promise;
  }
}
