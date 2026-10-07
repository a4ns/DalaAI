import { useCallback, useLayoutEffect, useRef, useState } from 'react';
import { ApiError, SessionChangedError, safeErrorMessage } from '../shared/api/client';
import type { ApiClient } from '../shared/api/client';
import { initialResource } from '../shared/ui/types';
import type { ResourceState } from '../shared/ui/types';

export function useResource<T>(client: ApiClient, loader: () => Promise<T>) {
  const [state, setState] = useState<ResourceState<T>>(initialResource);
  const currentLoader = useRef(loader);
  useLayoutEffect(() => { currentLoader.current = loader; }, [loader]);
  const lifecycle = useRef({ active: true }); const run = useRef(0);
  useLayoutEffect(() => { const life = { active: true }; lifecycle.current = life; return () => { life.active = false; }; }, []);
  const refresh = useCallback(async () => {
    const id = ++run.current; const epoch = client.epoch; const life = lifecycle.current;
    setState(previous => ({ ...previous, loadStatus: 'loading', freshness: previous.snapshot === null ? 'never' : 'stale', error: null }));
    try {
      const snapshot = await currentLoader.current();
      if (!life.active || run.current !== id || epoch !== client.epoch) return;
      setState({ snapshot, freshness: 'fresh', loadStatus: 'ready', error: null, incomplete: false, lastConfirmedAt: new Date().toISOString() });
    } catch (error) {
      if (!life.active || run.current !== id || epoch !== client.epoch || error instanceof SessionChangedError) return;
      const purge = error instanceof ApiError && [401, 403, 404].includes(error.status);
      setState(previous => ({ ...(purge ? initialResource<T>() : previous), freshness: purge || previous.snapshot === null ? 'never' : 'stale', loadStatus: navigator.onLine ? 'error' : 'offline', error: safeErrorMessage(error), incomplete: true }));
    }
  }, [client]);
  return { state, refresh, setState };
}
