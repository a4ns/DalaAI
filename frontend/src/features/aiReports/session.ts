import type { ApiClient } from '../../shared/api/client';

export type AssistanceSession = Pick<ApiClient, 'epoch' | 'session' | 'subscribe'>;
export interface AssistanceRuntime {
  now: () => number;
  schedule: (callback: () => void, ms: number) => () => void;
  uuid: () => string;
}
export const assistanceRuntime: AssistanceRuntime = {
  now: () => Date.now(),
  schedule: (callback, ms) => { const timer = setTimeout(callback, ms); return () => clearTimeout(timer); },
  uuid: () => crypto.randomUUID(),
};
/** Each controller belongs to one authenticated session, never persistent storage. */
export class MasterSessionFence {
  readonly epoch: number;
  #alive = true;
  #cancelTimer: (() => void) | null = null;
  constructor(readonly client: AssistanceSession, readonly ready: () => boolean, readonly runtime: AssistanceRuntime) {
    this.epoch = client.epoch;
  }
  current = (): boolean => {
    const session = this.client.session;
    return this.#alive && this.client.epoch === this.epoch && this.ready() && Boolean(session?.principal.active && session.principal.role === 'master' && Date.parse(session.expires_at) > this.runtime.now());
  };
  attach(invalidate: () => void): () => void {
    this.#alive = true;
    const check = () => {
      this.#cancelTimer?.(); this.#cancelTimer = null;
      if (!this.current()) invalidate();
      const session = this.client.session;
      const ms = session ? Date.parse(session.expires_at) - this.runtime.now() : 0;
      // Keep the expiry fence armed while auth/UI readiness is temporarily false.
      if (this.#alive && this.client.epoch === this.epoch && ms > 0) this.#cancelTimer = this.runtime.schedule(check, Math.min(ms, 2147483647));
    };
    const off = this.client.subscribe(check); check();
    return () => { off(); this.#alive = false; this.#cancelTimer?.(); this.#cancelTimer = null; invalidate(); };
  }
}
