import type { PushConfig, PushState, PushSubscriptionData } from './types.ts';

export const INITIAL_PUSH_STATE: PushState = Object.freeze({ phase: 'idle', permission: 'default', browserSubscription: 'unchecked', backendBinding: 'unconfirmed', message: null });
export const PUSH_POLICY = 'На текущий вход подключается одно устройство. Новое подключение заменит прежнее. После выхода или окончания сессии доставка отключается. Подключение не подтверждает получение уведомлений телефоном.';
export function busyPush(state: PushState): boolean {
  return ['preparing', 'subscribing', 'registering', 'resetting', 'removing'].includes(state.phase);
}
export function assertPushConfig(value: unknown): asserts value is PushConfig {
  if (!value || typeof value !== 'object') throw new Error('Invalid push configuration');
  const config = value as Partial<PushConfig>;
  if (typeof config.enabled !== 'boolean' || config.delivery_semantics !== 'provider_acceptance_is_not_device_delivery' || config.device_policy !== 'latest_registration_per_user' || (config.enabled ? typeof config.application_server_key !== 'string' || !validPublicKey(config.application_server_key) : config.application_server_key !== null)) throw new Error('Invalid push configuration');
}
export function validPublicKey(value: string): boolean {
  if (!/^[A-Za-z0-9_-]{87}$/.test(value)) return false;
  try { const key = atob(value.replace(/-/g, '+').replace(/_/g, '/') + '='); return key.length === 65 && key.charCodeAt(0) === 4; } catch { return false; }
}
export function captureSubscription(value: PushSubscriptionJSON): { body: string; endpoint: string } {
  const { endpoint, keys, expirationTime } = value;
  if (typeof endpoint !== 'string' || typeof keys?.p256dh !== 'string' || typeof keys.auth !== 'string' || !/^[A-Za-z0-9_-]+$/.test(keys.p256dh) || !/^[A-Za-z0-9_-]+$/.test(keys.auth)) throw new Error('Invalid subscription');
  const url = new URL(endpoint);
  if (url.protocol !== 'https:' || url.username || url.password || url.hash || (expirationTime !== undefined && expirationTime !== null && (!Number.isSafeInteger(expirationTime) || expirationTime < 0))) throw new Error('Invalid subscription');
  const data: PushSubscriptionData = { endpoint, keys: { p256dh: keys.p256dh, auth: keys.auth } };
  if (expirationTime !== undefined) data.expirationTime = expirationTime;
  const body = JSON.stringify(data);
  if (new TextEncoder().encode(body).length > 4096) throw new Error('Subscription too large');
  return { body, endpoint };
}
export function pushMessage(state: PushState): string {
  if (state.message) return state.message;
  switch (state.phase) {
    case 'idle': return 'Уведомления на этом устройстве ещё не проверены.';
    case 'unsupported': return 'Уведомления недоступны в этом браузере или подключении. Нужен поддерживаемый браузер и HTTPS.';
    case 'preparing': return 'Проверяем настройки уведомлений…';
    case 'disabled': return 'Сервис уведомлений пока не настроен.';
    case 'denied': return 'Уведомления заблокированы. Измените разрешение в настройках сайта, затем проверьте снова.';
    case 'ready': return 'Можно подключить уведомления. Браузер может запросить разрешение после нажатия кнопки.';
    case 'unconfirmed': return 'В браузере есть подписка. Её подключение к текущему входу не подтверждено. Для нового подключения сначала удалите прежнюю подписку на этом устройстве.';
    case 'subscribing': return 'Ожидаем разрешение и подписку браузера…';
    case 'registering': return 'Подключаем уведомления к текущему входу…';
    case 'connected': return 'Подключено к текущему входу на этом устройстве. Получение уведомлений телефоном не проверено.';
    case 'unknown': return 'Результат подключения не подтверждён. Можно повторить тот же запрос без новой подписки.';
    case 'resetting': return 'Удаляем прежнюю подписку браузера…';
    case 'removing': return 'Отключаем уведомления для текущего входа…';
    case 'remove-unknown': return 'Отключение на сервере не подтверждено. Повторите тот же запрос.';
    case 'local-cleanup': return 'Серверное подключение удалено. Отключение подписки браузера пока не подтверждено.';
    case 'off': return 'Подключение удалено на сервере, подписка браузера отключена. Разрешение браузера при этом сохраняется.';
    case 'error': return 'Не удалось проверить или изменить настройки уведомлений. Проверьте снова.';
  }
}
