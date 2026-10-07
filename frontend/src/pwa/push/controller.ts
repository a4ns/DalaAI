import { assertPushConfig, captureSubscription, INITIAL_PUSH_STATE } from './model.ts';
import type { BrowserSubscription, PushBackendPort, PushBrowserPort, PushConfig, PushState } from './types.ts';

function failure(error: unknown, unknownDefault = false): { unknown: boolean; message: string } {
  const details = error && typeof error === 'object' ? error as { outcomeUnknown?: boolean; code?: string; problem?: { code?: string } } : {};
  const code = details.code ?? details.problem?.code;
  if (code === 'SUBSCRIPTION_CONFLICT') return { unknown: false, message: 'Подписка связана с другой учётной записью. Удалите прежнюю подписку браузера и подключите заново.' };
  if (code === 'PUSH_DISABLED') return { unknown: false, message: 'Сервис уведомлений отключён. Подключение не подтверждено.' };
  return { unknown: details.outcomeUnknown ?? unknownDefault, message: 'Не удалось подтвердить настройку. Проверьте соединение и состояние сессии.' };
}

/** Memory-only, user-action controller. Construct once per sessionKey; dispose on identity change. */
export class PushController {
  #browser: PushBrowserPort;
  #backend: PushBackendPort;
  #current: () => boolean;
  #alive = true;
  #pending = false;
  #state: PushState = INITIAL_PUSH_STATE;
  #listeners = new Set<() => void>();
  #config: PushConfig | null = null;
  #subscription: BrowserSubscription | null = null;
  #captured: { body: string; endpoint: string } | null = null;
  constructor(options: { browser: PushBrowserPort; backend: PushBackendPort; isCurrentContext: () => boolean }) {
    this.#browser = options.browser; this.#backend = options.backend; this.#current = options.isCurrentContext;
  }
  get state(): PushState { return this.#state; }
  subscribe = (listener: () => void): (() => void) => { this.#listeners.add(listener); return () => { this.#listeners.delete(listener); }; };
  dispose(): void { this.#alive = false; this.#config = null; this.#subscription = null; this.#captured = null; this.#listeners.clear(); }
  #active(): boolean { return this.#alive && this.#current(); }
  #set(update: Partial<PushState>): void {
    if (!this.#active()) return;
    this.#state = Object.freeze({ ...this.#state, message: null, ...update }); this.#listeners.forEach(listener => listener());
  }
  #run(action: () => Promise<void>): Promise<void> {
    if (this.#pending || !this.#active()) return Promise.resolve();
    this.#pending = true;
    return action().finally(() => { this.#pending = false; });
  }
  prepare = (): Promise<void> => this.#run(async () => {
    if (['unknown', 'remove-unknown', 'local-cleanup', 'connected'].includes(this.#state.phase)) return;
    if (!this.#browser.supported()) { this.#set({ phase: 'unsupported', permission: 'unsupported' }); return; }
    this.#set({ phase: 'preparing', permission: this.#browser.permission() });
    try {
      const config = await this.#backend.getConfig();
      if (!this.#active()) return;
      assertPushConfig(config); this.#config = Object.freeze({ ...config });
      if (!config.enabled) { this.#set({ phase: 'disabled' }); return; }
      if (this.#browser.permission() === 'denied') { this.#set({ phase: 'denied', permission: 'denied' }); return; }
      const subscription = await this.#browser.prepare();
      if (!this.#active()) return;
      this.#subscription = subscription; this.#captured = null;
      this.#set({ phase: subscription ? 'unconfirmed' : 'ready', permission: this.#browser.permission(), browserSubscription: subscription ? 'present' : 'absent', backendBinding: 'unconfirmed' });
    } catch { this.#set({ phase: 'error' }); }
  });
  /** Native subscribe is reached synchronously from this explicit user action. */
  enable = (): Promise<void> => this.#run(async () => {
    if (this.#state.phase !== 'ready' || !this.#config?.enabled || !this.#config.application_server_key || this.#subscription) return;
    const permission = this.#browser.permission();
    if (permission === 'denied') { this.#set({ phase: 'denied', permission }); return; }
    this.#set({ phase: 'subscribing', permission });
    try {
      const subscription = await this.#browser.subscribe(this.#config.application_server_key);
      if (!this.#active()) return;
      this.#subscription = subscription;
      this.#set({ browserSubscription: 'present', permission: this.#browser.permission(), backendBinding: 'unconfirmed' });
      this.#captured = captureSubscription(subscription.toJSON());
    } catch {
      if (!this.#active()) return;
      const after = this.#browser.permission();
      this.#set({ phase: after === 'denied' ? 'denied' : 'error', permission: after, message: after === 'denied' ? null : 'Подписка не подтверждена. Если окно разрешения закрыто, разрешение не выдано. Проверьте настройки снова.' }); return;
    }
    await this.#register();
  });
  async #register(): Promise<void> {
    if (!this.#captured || !this.#active()) return;
    const wasUnknown = this.#state.backendBinding === 'unknown';
    this.#set({ phase: 'registering' });
    try {
      await this.#backend.register(this.#captured.body);
      this.#set({ phase: 'connected', backendBinding: 'confirmed' });
    } catch (error) {
      const result = failure(error, true);
      this.#set({ phase: result.unknown || wasUnknown ? 'unknown' : 'error', backendBinding: result.unknown || wasUnknown ? 'unknown' : 'unconfirmed', message: result.unknown || wasUnknown ? null : result.message });
    }
  }
  retry = (): Promise<void> => this.#run(async () => {
    if (this.#state.phase === 'unknown') await this.#register();
    else if (this.#state.phase === 'remove-unknown') await this.#remove();
    else if (this.#state.phase === 'local-cleanup') await this.#clearLocal(true);
  });
  /** Explicit destructive reset of an unconfirmed browser subscription, never an automatic rebind. */
  resetExisting = (): Promise<void> => this.#run(async () => {
    if (!this.#subscription || this.#state.backendBinding !== 'unconfirmed' || !['unconfirmed', 'error'].includes(this.#state.phase)) return;
    this.#set({ phase: 'resetting' });
    await this.#clearLocal(false);
  });
  async #clearLocal(serverRemoved: boolean): Promise<void> {
    if (!this.#subscription || !this.#active()) return;
    try {
      const removed = await this.#browser.unsubscribe(this.#subscription);
      if (!this.#active()) return;
      if (!removed) throw new Error('Browser subscription remains');
      this.#subscription = null; this.#captured = null;
      this.#set({ phase: serverRemoved ? 'off' : 'ready', browserSubscription: 'absent', backendBinding: serverRemoved ? 'removed' : 'unconfirmed', permission: this.#browser.permission() });
    } catch {
      this.#set({ phase: serverRemoved ? 'local-cleanup' : 'unconfirmed', message: serverRemoved ? null : 'Удаление подписки браузера не подтверждено. Новое подключение не начато.' });
    }
  }
  disable = (): Promise<void> => this.#run(async () => {
    if (this.#state.phase === 'connected') await this.#remove();
  });
  async #remove(): Promise<void> {
    if (!this.#captured || !this.#active()) return;
    const wasUnknown = this.#state.phase === 'remove-unknown';
    this.#set({ phase: 'removing' });
    try { await this.#backend.remove(this.#captured.endpoint); }
    catch (error) {
      const result = failure(error, true);
      this.#set({ phase: result.unknown || wasUnknown ? 'remove-unknown' : 'connected', backendBinding: result.unknown || wasUnknown ? 'unknown' : 'confirmed', message: result.unknown || wasUnknown ? null : 'Сервер отклонил отключение. Подписка браузера сохранена; можно повторить отключение.' }); return;
    }
    if (!this.#active()) return;
    this.#set({ backendBinding: 'removed' });
    await this.#clearLocal(true);
  }
}
