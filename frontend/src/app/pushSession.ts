import { ApiClient, SessionChangedError } from '../shared/api/client';
import { PushController } from '../pwa/push/controller';
import { createPushBrowserPort } from '../pwa/push/browser';
import { INITIAL_PUSH_STATE } from '../pwa/push/model';
import type { PushBackendPort, PushBrowserPort, PushState } from '../pwa/push/types';

/** The auth-ready callback reads the synchronous logout latch, not a rendered busy snapshot. */
export function isCurrentPushContext(client: ApiClient, epoch: number, userId: string, isAuthReady: () => boolean): boolean {
  const session = client.session;
  return isAuthReady() && client.epoch === epoch && Boolean(session?.principal.active && session.principal.user_id === userId && Date.parse(session.expires_at) > Date.now());
}
export function createPushBackend(client: ApiClient, isCurrent: () => boolean): PushBackendPort {
  const assertCurrent = () => { if (!isCurrent()) throw new SessionChangedError(); };
  return {
    async getConfig() { assertCurrent(); const result = await client.getPushConfig(); assertCurrent(); return result; },
    async register(body) { assertCurrent(); await client.registerPushSubscription(body); assertCurrent(); },
    async remove(endpoint) { assertCurrent(); await client.removePushSubscription(endpoint); assertCurrent(); },
  };
}

/** Side-effect-free construction; attach/dispose tolerates React StrictMode's effect replay. */
export class PushSession {
  #client: ApiClient;
  #epoch: number;
  #userId: string;
  #isAuthReady: () => boolean;
  #browser: () => PushBrowserPort;
  #controller: PushController | null = null;
  #state: PushState = INITIAL_PUSH_STATE;
  #listeners = new Set<() => void>();
  constructor(client: ApiClient, isAuthReady: () => boolean, browser: () => PushBrowserPort = createPushBrowserPort) {
    this.#client = client; this.#epoch = client.epoch; this.#userId = client.session?.principal.user_id ?? '';
    this.#isAuthReady = isAuthReady; this.#browser = browser;
  }
  getSnapshot = (): PushState => this.#state;
  subscribe = (listener: () => void): (() => void) => { this.#listeners.add(listener); return () => { this.#listeners.delete(listener); }; };
  attach = (): (() => void) => {
    const controller: PushController = new PushController({ browser: this.#browser(), backend: createPushBackend(this.#client, () => this.#current(controller)), isCurrentContext: () => this.#current(controller) });
    this.#controller = controller; this.#state = controller.state;
    const unsubscribe = controller.subscribe(() => { this.#state = controller.state; this.#listeners.forEach(listener => listener()); });
    this.#listeners.forEach(listener => listener());
    return () => { if (this.#controller === controller) this.#controller = null; unsubscribe(); controller.dispose(); };
  };
  #current(controller: PushController): boolean { return this.#controller === controller && isCurrentPushContext(this.#client, this.#epoch, this.#userId, this.#isAuthReady); }
  prepare = (): void => { void this.#controller?.prepare(); };
  enable = (): void => { void this.#controller?.enable(); };
  resetExisting = (): void => { void this.#controller?.resetExisting(); };
  retry = (): void => { void this.#controller?.retry(); };
  disable = (): void => { void this.#controller?.disable(); };
}
