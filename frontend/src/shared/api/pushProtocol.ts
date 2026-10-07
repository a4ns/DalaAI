/** A0-0031 additive protocol. Core generated proposal.2 files are unchanged. */
export interface PushApiConfig {
  enabled: boolean;
  application_server_key: string | null;
  delivery_semantics: 'provider_acceptance_is_not_device_delivery';
  device_policy: 'latest_registration_per_user';
}
const object = (value: unknown): value is Record<string, unknown> => Boolean(value && typeof value === 'object' && !Array.isArray(value));
const exact = (value: Record<string, unknown>, keys: string[]): boolean => Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
export function isPushConfig(value: unknown): value is PushApiConfig {
  if (!object(value) || !exact(value, ['enabled', 'application_server_key', 'delivery_semantics', 'device_policy']) || typeof value.enabled !== 'boolean' || value.delivery_semantics !== 'provider_acceptance_is_not_device_delivery' || value.device_policy !== 'latest_registration_per_user') return false;
  if (!value.enabled) return value.application_server_key === null;
  const key = value.application_server_key;
  if (typeof key !== 'string' || !/^[A-Za-z0-9_-]{87}$/.test(key)) return false;
  try { const decoded = atob(key.replace(/-/g, '+').replace(/_/g, '/') + '='); return decoded.length === 65 && decoded.charCodeAt(0) === 4; } catch { return false; }
}
export function isPushConfirmation(value: unknown): boolean { return object(value) && exact(value, ['enabled']) && value.enabled === true; }
export function validPushEndpoint(value: unknown): value is string {
  if (typeof value !== 'string') return false;
  try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password && !url.hash; } catch { return false; }
}
export function validPushRegistration(body: string): boolean {
  if (new TextEncoder().encode(body).length > 4096) return false;
  try {
    const value: unknown = JSON.parse(body);
    if (!object(value) || !exact(value, Object.hasOwn(value, 'expirationTime') ? ['endpoint', 'keys', 'expirationTime'] : ['endpoint', 'keys']) || !validPushEndpoint(value.endpoint) || !object(value.keys) || !exact(value.keys, ['p256dh', 'auth'])) return false;
    if (typeof value.keys.p256dh !== 'string' || typeof value.keys.auth !== 'string' || !/^[A-Za-z0-9_-]+$/.test(value.keys.p256dh) || !/^[A-Za-z0-9_-]+$/.test(value.keys.auth)) return false;
    return value.expirationTime === undefined || value.expirationTime === null || (Number.isSafeInteger(value.expirationTime) && (value.expirationTime as number) >= 0);
  } catch { return false; }
}
