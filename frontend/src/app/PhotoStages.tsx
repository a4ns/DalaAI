import { useSyncExternalStore } from 'react';
import { PhotoPicker } from '../pwa/PhotoPicker';
import type { PhotoContext, PhotoStore } from './photoStore';

export function PhotoStages({ store, context, disabled, required = false }: { store: PhotoStore; context: PhotoContext; disabled: boolean; required?: boolean }) {
  useSyncExternalStore(store.subscribe, store.getSnapshot);
  const bag = store.get(context);
  return <div>
    <PhotoPicker contextKey={context.key} phase={context.phase} value={bag.files} disabled={disabled || store.transportLocked(context)} required={required} onChange={files => store.select(context, files)} onBusyChange={busy => store.processing(context, busy)}/>
    {bag.files.length > 0 && <ul className="photo-stage-status" aria-label="Загрузка фото на сервер">{bag.files.map((file, index) => {
      const job = bag.jobs[file.id]; const expired = job?.photo && store.isExpired(job.photo);
      return <li key={file.id}><strong>Фото {index + 1}: </strong>{job?.status === 'confirmed' && !expired ? 'Загрузка подтверждена сервером' : job?.status === 'pending' ? 'Загружаем…' : job?.status === 'unknown' ? 'Результат загрузки не подтверждён' : expired ? 'Срок хранения истёк. Выберите фото заново.' : 'Загрузка не выполнена'}{job?.error && <p role="alert">{job.error}</p>}{(job?.status === 'unknown' || job?.status === 'failed') && <button type="button" disabled={disabled} onClick={() => store.retry(context, file)}>Повторить исходную загрузку фото {index + 1}</button>}</li>;
    })}</ul>}
    <p className="hint">Подтверждённых фото: {store.confirmedIds(context).length}. До подтверждения всех выбранных фото выдача или отправка результата недоступна. Неудачный выбор можно удалить.</p>
  </div>;
}
