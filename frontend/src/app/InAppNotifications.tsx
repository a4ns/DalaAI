import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { ApiClient } from '../shared/api/client';
import type { OrderStore } from '../shared/api/orderStore';
import { InAppNotificationFeed, NOTICE_LIFETIME_MS } from './inAppNotifications';
import type { InAppNotice } from './inAppNotifications';
import './inAppNotifications.css';

function Notice({ notice, dismiss }: { notice: InAppNotice; dismiss: (key: string) => void }) {
  const remaining = useRef(NOTICE_LIFETIME_MS);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const paused = hovered || focused;
  useEffect(() => {
    if (paused) return;
    const started = performance.now();
    const timer = setTimeout(() => dismiss(notice.key), remaining.current);
    return () => { clearTimeout(timer); remaining.current = Math.max(0, remaining.current - (performance.now() - started)); };
  }, [paused, notice.key, dismiss]);
  return <div className="in-app-notice" onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}
    onFocus={() => setFocused(true)} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false); }}>
    <div><strong>{notice.title}</strong><p>{notice.message}</p></div>
    <button type="button" className="in-app-notice-close" aria-label={`Закрыть уведомление: ${notice.message}`} onClick={() => dismiss(notice.key)}><span aria-hidden="true">×</span></button>
  </div>;
}

/** Mounted once inside App's session boundary, outside the hidden tab panels. */
export function InAppNotifications({ client, orders }: { client: ApiClient; orders: OrderStore }) {
  const [feed] = useState(() => new InAppNotificationFeed(client, orders));
  const notices = useSyncExternalStore(feed.subscribe, feed.getSnapshot);
  useEffect(() => feed.attach(), [feed]);
  return <div className="in-app-notifications" role="status" aria-label="Уведомления" aria-live="polite" aria-atomic="false" aria-relevant="additions">
    {notices.map(notice => <Notice key={notice.key} notice={notice} dismiss={feed.dismiss}/>)}
  </div>;
}
