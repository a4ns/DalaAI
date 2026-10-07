/** Additive A0-0031 contract. The accepted core wire files are unchanged. */
export interface PushConfig {
  enabled: boolean;
  application_server_key: string | null;
  delivery_semantics: 'provider_acceptance_is_not_device_delivery';
  device_policy: 'latest_registration_per_user';
}
export interface PushSubscriptionData {
  endpoint: string;
  keys: { p256dh: string; auth: string };
  expirationTime?: number | null;
}
export interface BrowserSubscription {
  toJSON(): PushSubscriptionJSON;
}
export interface PushBrowserPort {
  supported(): boolean;
  permission(): NotificationPermission;
  prepare(): Promise<BrowserSubscription | null>;
  /** Invoke directly from the enable button, without asynchronous preparation first. */
  subscribe(publicKey: string): Promise<BrowserSubscription>;
  unsubscribe(subscription: BrowserSubscription): Promise<boolean>;
}
export interface PushBackendPort {
  getConfig(): Promise<PushConfig>;
  /** Send these exact captured JSON bytes. No replacement body or operation identifier. */
  register(body: string): Promise<void>;
  remove(endpoint: string): Promise<void>;
}
export type PushPhase = 'idle' | 'unsupported' | 'preparing' | 'disabled' | 'denied' | 'ready' | 'unconfirmed' | 'subscribing' | 'registering' | 'connected' | 'unknown' | 'error' | 'resetting' | 'removing' | 'remove-unknown' | 'local-cleanup' | 'off';
export interface PushState {
  readonly phase: PushPhase;
  readonly permission: NotificationPermission | 'unsupported';
  readonly browserSubscription: 'unchecked' | 'absent' | 'present';
  readonly backendBinding: 'unconfirmed' | 'confirmed' | 'unknown' | 'removed';
  readonly message: string | null;
}
export class PushOperationError extends Error {
  readonly outcomeUnknown: boolean;
  readonly code: string;
  constructor(code: string, outcomeUnknown = false) {
    super('Не удалось подтвердить настройку уведомлений.');
    this.name = 'PushOperationError'; this.code = code; this.outcomeUnknown = outcomeUnknown;
  }
}
