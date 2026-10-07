import { validPublicKey } from './model.ts';
import type { BrowserSubscription, PushBrowserPort } from './types.ts';

// A pending browser operation outlives a disposed controller. A newer account must
// wait and inspect the resulting subscription rather than racing its creation.
const pending = new WeakMap<ServiceWorkerContainer, object>();
function exclusive<T>(container: ServiceWorkerContainer, action: () => Promise<T>): Promise<T> {
  if (pending.has(container)) return Promise.reject(new Error('Browser operation still pending'));
  const token = {}; pending.set(container, token);
  try { return action().finally(() => { if (pending.get(container) === token) pending.delete(container); }); }
  catch (error) { pending.delete(container); return Promise.reject(error); }
}
function activeWorker(registration: ServiceWorkerRegistration, timeoutMs: number): Promise<void> {
  if (registration.active?.state === 'activated') return Promise.resolve();
  return new Promise((resolve, reject) => {
    const worker = registration.installing ?? registration.waiting ?? registration.active;
    if (!worker) { reject(new Error('Missing service worker')); return; }
    const cleanup = () => { clearTimeout(timer); worker.removeEventListener('statechange', changed); };
    const changed = () => {
      if (worker.state === 'activated') { cleanup(); resolve(); }
      else if (worker.state === 'redundant') { cleanup(); reject(new Error('Service worker became redundant')); }
    };
    const timer = setTimeout(() => { cleanup(); reject(new Error('Service worker activation timed out')); }, timeoutMs);
    worker.addEventListener('statechange', changed); changed();
  });
}
/** Only explicit controller actions call this port. No storage, network adapter or automatic permission prompt. */
export function createPushBrowserPort(): PushBrowserPort {
  let registration: ServiceWorkerRegistration | null = null;
  const known = new WeakSet<object>();
  const supported = () => typeof window !== 'undefined' && window.isSecureContext && window.location.protocol === 'https:' && 'serviceWorker' in navigator && typeof Notification !== 'undefined' && typeof PushManager !== 'undefined' && typeof ServiceWorkerRegistration !== 'undefined' && 'showNotification' in ServiceWorkerRegistration.prototype;
  const permission = (): NotificationPermission => supported() ? Notification.permission : 'default';
  return {
    supported, permission,
    prepare() {
      if (!supported()) return Promise.reject(new Error('Push unsupported'));
      return exclusive(navigator.serviceWorker, async () => {
        const scriptURL = new URL('/sw.js', window.location.origin).href;
        const previous = await navigator.serviceWorker.getRegistration('/');
        if (previous && [previous.active, previous.waiting, previous.installing].some(worker => worker && worker.scriptURL !== scriptURL)) throw new Error('Another service worker owns the application scope');
        const candidate = previous ?? await navigator.serviceWorker.register('/sw.js', { scope: '/', updateViaCache: 'none' });
        if (candidate.scope !== new URL('/', window.location.origin).href) throw new Error('Unexpected service worker scope');
        await activeWorker(candidate, 10000);
        registration = candidate;
        const subscription = await candidate.pushManager.getSubscription();
        if (subscription) known.add(subscription);
        return subscription;
      });
    },
    subscribe(publicKey: string) {
      if (!supported() || !registration || registration.active?.state !== 'activated' || !validPublicKey(publicKey) || permission() === 'denied') return Promise.reject(new Error('Push is not ready'));
      const active = registration;
      return exclusive(navigator.serviceWorker, () => {
        // This native call is synchronous with the user's enable click.
        const key = Uint8Array.from(atob(publicKey.replace(/-/g, '+').replace(/_/g, '/') + '='), char => char.charCodeAt(0));
        return active.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key }).then(subscription => { known.add(subscription); return subscription; });
      });
    },
    unsubscribe(subscription: BrowserSubscription) {
      if (!supported() || !registration || !known.has(subscription)) return Promise.reject(new Error('Unknown browser subscription'));
      const active = registration;
      return exclusive(navigator.serviceWorker, async () => {
        await (subscription as PushSubscription).unsubscribe();
        return await active.pushManager.getSubscription() === null;
      });
    },
  };
}
