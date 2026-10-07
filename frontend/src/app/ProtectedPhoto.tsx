import { useEffect, useState } from 'react';
import type { ApiClient } from '../shared/api/client';
import { safeErrorMessage } from '../shared/api/client';

type Props = { client: ApiClient; photoId: string; index: number };
export function ProtectedPhoto(props: Props) {
  const [attempt, setAttempt] = useState(0);
  return <ProtectedPhotoAttempt key={`${props.photoId}:${attempt}`} {...props} onRetry={() => setAttempt(value => value + 1)}/>;
}
function ProtectedPhotoAttempt({ client, photoId, index, onRetry }: Props & { onRetry: () => void }) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true; let objectUrl: string | null = null; const epoch = client.epoch;
    void client.getPhoto(photoId).then(blob => {
      if (!active || epoch !== client.epoch) return;
      objectUrl = URL.createObjectURL(blob); setUrl(objectUrl);
    }).catch(failure => { if (active && epoch === client.epoch) setError(safeErrorMessage(failure)); });
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [client, photoId]);
  return <figure className="protected-photo">{url && !error ? <img src={url} alt={`Фото результата ${index + 1}`} onError={() => setError('Не удалось отобразить изображение.')}/> : <p role={error ? 'alert' : 'status'}>{error ?? 'Загружаем защищённое фото…'}</p>}{error && <button type="button" onClick={onRetry}>Повторить загрузку фото {index + 1}</button>}<figcaption>Фото результата {index + 1}</figcaption></figure>;
}
