/* B-107 notification-only worker. No cache, API access, background mutations or stored identity. */
'use strict';
const TITLE = 'НарядAI';
const BODY = 'Есть обновление наряда. Откройте приложение.';
const TAG = 'naryadai-update';

function acceptedPayload(data) {
  try {
    const raw = data?.text();
    if (typeof raw !== 'string' || raw.length > 4096) return false;
    const payload = JSON.parse(raw);
    return payload !== null && typeof payload === 'object' && !Array.isArray(payload)
      && Object.keys(payload).sort().join(',') === 'body,tag,title,url,v'
      && payload.v === 1 && payload.title === TITLE && payload.body === BODY
      && payload.url === '/' && payload.tag === TAG;
  } catch { return false; }
}

self.addEventListener('push', event => {
  // A0-0036: malformed messages are dropped. Log only a fixed reason marker;
  // never payload bytes, parsed fields, provider endpoints or thrown errors.
  if (!acceptedPayload(event.data)) {
    console.warn('NARYADAI_PUSH_INVALID_PAYLOAD');
    return;
  }
  event.waitUntil(self.registration.showNotification(TITLE, {
    body: BODY,
    tag: TAG,
    lang: 'ru',
    data: { url: '/' },
  }));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil((async () => {
    const target = new URL('/', self.location.origin);
    if (target.protocol !== 'https:' || target.origin !== self.location.origin) return;
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const client of windows) {
      let current;
      try { current = new URL(client.url); } catch { continue; }
      // Only the app root. Focusing leaves memory-only drafts and history intact.
      if (current.origin === target.origin && current.pathname === '/' && !current.username && !current.password) {
        try { await client.focus(); return; } catch { /* Try another valid app window. */ }
      }
    }
    await self.clients.openWindow(target.href);
  })().catch(() => { /* No delivery claim, raw payload logging, or network fallback. */ }));
});
