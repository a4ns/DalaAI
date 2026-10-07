import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import { PHOTO_LIMITS, photoErrorMessage, preparePhoto } from './photoPreparation';
import type { PhotoPhase, PreparedPhoto } from './photoPreparation';
import { connectivityMessage, useConnectivity } from './useConnectivity';
import { beginPhotoPreparation } from './preparationActivity';
import type { PhotoPreparationActivity } from './preparationActivity';
import './photoPicker.css';

export interface PhotoPickerProps {
  /** Change on account, order, draft or assignment-revision change. */
  contextKey: string;
  phase: PhotoPhase;
  value: readonly PreparedPhoto[];
  onChange: (photos: PreparedPhoto[]) => void;
  /** Include this in form busy state so submission waits for local preparation. */
  onBusyChange?: (busy: boolean) => void;
  disabled?: boolean;
  maxPhotos?: number;
  /** Informational only: server/workflow decides when missing photos block completion. */
  required?: boolean;
}
export function formatPhotoBytes(bytes: number): string {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} КиБ` : `${(bytes / (1024 * 1024)).toFixed(1)} МиБ`;
}
function Preview({ photo }: { photo: PreparedPhoto }) {
  const image = useRef<HTMLImageElement>(null);
  useEffect(() => {
    const next = URL.createObjectURL(photo.file);
    const element = image.current;
    if (element) element.src = next;
    return () => { element?.removeAttribute('src'); URL.revokeObjectURL(next); };
  }, [photo.file]);
  return <img ref={image} className="photo-picker__preview" alt={`Выбранное фото: ${photo.originalName}`} />;
}

export function PhotoPicker(props: PhotoPickerProps) {
  // Remount the selection state when an account, assignment, draft or phase changes.
  return <PhotoPickerSelection key={JSON.stringify([props.contextKey, props.phase])} {...props} />;
}
function PhotoPickerSelection({ contextKey, phase, value, onChange, onBusyChange, disabled = false, maxPhotos = PHOTO_LIMITS.maxPhotos, required = false }: PhotoPickerProps) {
  const id = useId();
  const camera = useRef<HTMLInputElement>(null);
  const files = useRef<HTMLInputElement>(null);
  const active = useRef<PhotoPreparationActivity | null>(null);
  const mounted = useRef(false);
  const current = useRef({ contextKey, phase, value, onChange, onBusyChange, disabled });
  useLayoutEffect(() => { current.current = { contextKey, phase, value, onChange, onBusyChange, disabled }; }, [contextKey, phase, value, onChange, onBusyChange, disabled]);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [status, setStatus] = useState('');
  const connectivity = useConnectivity();
  const limit = Math.max(1, Math.min(PHOTO_LIMITS.maxPhotos, Number.isFinite(maxPhotos) ? Math.floor(maxPhotos) : PHOTO_LIMITS.maxPhotos));
  const locked = disabled || busy;
  const full = value.length >= limit;

  useLayoutEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; active.current?.cancel(); active.current = null; };
  }, []);
  useEffect(() => { if (disabled) active.current?.cancel(); }, [disabled]);

  const select = async (event: ChangeEvent<HTMLInputElement>): Promise<void> => {
    const selected = Array.from(event.currentTarget.files ?? []);
    event.currentTarget.value = ''; // Re-selecting the same file after a decode failure works.
    if (selected.length === 0 || current.current.disabled || active.current) return;
    const initial = current.current;
    const remaining = Math.max(0, limit - initial.value.length);
    const batch = selected.slice(0, remaining);
    const issues: string[] = selected.length > remaining ? [`Можно выбрать не больше ${limit} фото на этот этап. Лишние файлы не добавлены.`] : [];
    if (batch.length === 0) { setErrors(issues); return; }
    const controller = beginPhotoPreparation(initial.onBusyChange);
    active.current = controller;
    setBusy(true); setErrors([]); setStatus('Подготавливаем фото на устройстве…');
    const prepared: PreparedPhoto[] = [];
    try {
      for (const file of batch) {
        try { prepared.push(await preparePhoto(file, controller.signal)); }
        catch (error) {
          if (controller.signal.aborted) return;
          issues.push(`${file.name || 'Фото'}: ${photoErrorMessage(error)}`);
        }
      }
      const latest = current.current;
      if (!mounted.current || controller.signal.aborted || latest.contextKey !== initial.contextKey || latest.phase !== initial.phase || latest.disabled) return;
      // An external reset/removal during preparation must not restore stale selections.
      const unchanged = latest.value.length === initial.value.length && latest.value.every((photo, i) => photo === initial.value[i]);
      if (!unchanged) { setStatus('Выбор изменился. Добавьте фото ещё раз.'); return; }
      if (prepared.length > 0) latest.onChange([...latest.value, ...prepared]);
      setErrors(issues);
      setStatus(prepared.length > 0 ? `Подготовлено фото: ${prepared.length}. Загрузка на сервер ещё не подтверждена.` : 'Новые фото не добавлены.');
    } finally {
      if (active.current === controller) {
        active.current = null;
        controller.finish();
        if (mounted.current) setBusy(false);
      }
    }
  };

  return <fieldset className="photo-picker" disabled={disabled} aria-describedby={`${id}-help ${id}-network`} aria-busy={busy}>
    <legend>Фото {phase === 'before' ? 'до работы' : 'после работы'}{required ? ' · требуется для завершения' : ''}</legend>
    <p id={`${id}-help`} className="photo-picker__help">JPEG, PNG или WebP, до 8 МиБ и 20 мегапикселей. До {limit} фото на этап. Фото уменьшаются до 1920 пикселей по длинной стороне.</p>
    <p className="photo-picker__notice">Выбор и подготовка фото не означают загрузку на сервер. Файлы хранятся только в текущей вкладке и могут потеряться при её закрытии или обновлении.</p>
    <p id={`${id}-network`} className="photo-picker__network" role="status">{connectivityMessage(connectivity)}</p>
    <div className="photo-picker__actions">
      <button type="button" disabled={locked || full} onClick={() => camera.current?.click()}>Сделать фото</button>
      <button type="button" disabled={locked || full} onClick={() => files.current?.click()}>Выбрать из файлов</button>
    </div>
    <input ref={camera} type="file" accept="image/jpeg,image/png,image/webp" capture="environment" hidden disabled={locked || full} aria-label="Снять фото камерой" onChange={event => { void select(event); }} />
    <input ref={files} type="file" accept="image/jpeg,image/png,image/webp" multiple hidden disabled={locked || full} aria-label="Выбрать фотографии" onChange={event => { void select(event); }} />
    <p className="photo-picker__help">Если камера не открылась или доступ запрещён, выберите готовый файл. Разрешение камеры зависит от устройства и браузера.</p>
    <p role="status" className="photo-picker__status">{busy ? 'Проверяем и сжимаем фото…' : status || `Выбрано: ${value.length} из ${limit}.`}</p>
    {full && <p className="photo-picker__help">Достигнут лимит. Удалите фото, чтобы выбрать другое.</p>}
    {errors.length > 0 && <div className="photo-picker__errors" role="alert"><p>Не все фото удалось добавить:</p><ul>{errors.map((error, index) => <li key={`${index}-${error}`}>{error}</li>)}</ul></div>}
    {value.length > 0 && <ul className="photo-picker__list">{value.map((photo, index) => <li className="photo-picker__item" key={photo.id}>
      <Preview photo={photo} />
      <div className="photo-picker__details"><strong>Фото {index + 1}</strong><span className="photo-picker__filename">{photo.originalName}</span><span>{photo.width} × {photo.height} · {formatPhotoBytes(photo.file.size)}</span><span>Подготовлено на устройстве</span></div>
      <button type="button" disabled={locked} aria-label={`Удалить фото ${index + 1}: ${photo.originalName}`} onClick={() => { onChange(value.filter(item => item.id !== photo.id)); setErrors([]); setStatus('Фото удалено из локального выбора.'); }}>Удалить</button>
    </li>)}</ul>}
  </fieldset>;
}
