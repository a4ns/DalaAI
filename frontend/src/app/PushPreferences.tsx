import { useEffect, useState, useSyncExternalStore } from 'react';
import { PushSettings } from '../pwa/push/PushSettings';
import type { ApiClient } from '../shared/api/client';
import { PushSession } from './pushSession';

/** Inert on mount: permission, config, registration and retries require their explicit buttons. */
export function PushPreferences({ client, isAuthReady, disabled }: { client: ApiClient; isAuthReady: () => boolean; disabled: boolean }) {
  const [binding] = useState(() => new PushSession(client, isAuthReady));
  const state = useSyncExternalStore(binding.subscribe, binding.getSnapshot);
  useEffect(() => binding.attach(), [binding]);
  return <PushSettings state={state} onPrepare={binding.prepare} onEnable={binding.enable} onResetExisting={binding.resetExisting} onRetry={binding.retry} onDisable={binding.disable} disabled={disabled}/>;
}
