import { useEffect, useState } from 'react';

/** Browser network hint only. Online never means that our API is reachable. */
export type ConnectivityHint = 'online' | 'offline' | 'unknown';
function readHint(): ConnectivityHint {
  if (typeof navigator === 'undefined' || typeof navigator.onLine !== 'boolean') return 'unknown';
  return navigator.onLine ? 'online' : 'offline';
}
export function useConnectivity(): ConnectivityHint {
  const [hint, setHint] = useState<ConnectivityHint>(readHint);
  useEffect(() => {
    const update = (): void => setHint(readHint());
    window.addEventListener('online', update);
    window.addEventListener('offline', update);
    update();
    return () => { window.removeEventListener('online', update); window.removeEventListener('offline', update); };
  }, []);
  return hint;
}
export function connectivityMessage(hint: ConnectivityHint): string {
  if (hint === 'offline') return 'Браузер сообщает об отсутствии сети. Фото можно подготовить, но загрузка требует соединения. Автоматической отправки нет.';
  if (hint === 'online') return 'Браузер видит сеть. Доступность сервера и загрузка фото подтверждаются отдельно.';
  return 'Состояние сети неизвестно. Загрузка фото подтверждается только ответом сервера.';
}
