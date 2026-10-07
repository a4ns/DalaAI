export interface PhotoPreparationActivity {
  readonly signal: AbortSignal;
  /** Releases exactly this batch once; late completion cannot clear a newer batch. */
  finish: () => void;
  /** Canceled work may still settle, but must never publish selected files. */
  cancel: () => void;
}

export function beginPhotoPreparation(onBusyChange?: (busy: boolean) => void): PhotoPreparationActivity {
  const controller = new AbortController();
  let finished = false;
  const finish = (): void => {
    if (finished) return;
    finished = true;
    onBusyChange?.(false);
  };
  onBusyChange?.(true);
  return { signal: controller.signal, finish, cancel: () => { controller.abort(); finish(); } };
}
