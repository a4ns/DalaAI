import { useEffect, useLayoutEffect, useState, useSyncExternalStore } from 'react';
import type { ApiClient } from '../../shared/api/client';
import type { OrderStore } from '../../shared/api/orderStore';
import { BeforePhotosController, beforePhotoScopeKey } from './beforePhotos';
import type { BeforePhotoScope } from './beforePhotos';

type Props = { client: ApiClient; orders: OrderStore; sessionKey: string; scope: BeforePhotoScope; enabled: boolean; isAuthReady: () => boolean };
/** A changed selection is a new lifetime, including when returning to an earlier order. */
export function ExecutorBeforePhotos(props: Props) {
  return props.enabled ? <BeforePhotos key={JSON.stringify([props.sessionKey, beforePhotoScopeKey(props.scope)])} {...props}/> : null;
}
function BeforePhotos({ client, orders, scope, isAuthReady }: Props) {
  const [controller] = useState(() => new BeforePhotosController(client, orders, scope, isAuthReady));
  useLayoutEffect(() => { controller.setCurrent(isAuthReady); }, [controller, isAuthReady]);
  const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot);
  useLayoutEffect(() => controller.attach(), [controller]);
  useEffect(() => { void controller.load(); }, [controller]);
  return <section aria-label="Фото до выполнения">
    <h3>Фото до выполнения</h3>
    {state.status === 'blocked' ? <><p role="status">Доступ к фото до выполнения не подтверждён. Обновите список нарядов перед повторной загрузкой.</p><button type="button" className="executor-button executor-button--secondary" disabled={!state.canRetry} onClick={() => void controller.load()}>Повторить загрузку фото до выполнения</button></> : <>
      {scope.photoIds.length === 0 && <p className="executor-caption">Фото до выполнения не приложены.</p>}
      {scope.photoIds.length > 5 && <p className="executor-caption">Показаны первые 5 фото до выполнения.</p>}
      {state.photos.map((photo, index) => <figure className="protected-photo" key={photo.id}>
        <div style={{ height: 220, display: 'grid', placeItems: 'center', overflow: 'hidden' }}>
          {photo.url ? <img src={photo.url} alt={`Фото до выполнения ${index + 1}`} style={{ maxHeight: 220 }} onError={() => controller.imageFailed(photo.id)}/> :
            <p role={photo.status === 'failed' || photo.status === 'missing' ? 'alert' : 'status'}>{photo.status === 'missing' ? 'Фото до выполнения недоступно: файл не найден.' : photo.status === 'failed' ? 'Не удалось загрузить фото до выполнения.' : 'Загружаем фото до выполнения…'}</p>}
        </div>
        <figcaption>Фото до выполнения {index + 1}</figcaption>
      </figure>)}
      {state.status === 'ready' && state.photos.some(photo => photo.status === 'failed') && <button type="button" className="executor-button executor-button--secondary" onClick={() => void controller.load()}>Повторить загрузку фото до выполнения</button>}
    </>}
  </section>;
}
