import { busyPush, PUSH_POLICY, pushMessage } from './model.ts';
import type { PushState } from './types.ts';

export interface PushSettingsProps {
  state: PushState;
  onPrepare: () => void;
  onEnable: () => void;
  onResetExisting: () => void;
  onRetry: () => void;
  onDisable: () => void;
  disabled?: boolean;
}
/** Controlled presentation only. Mounting does not invoke any callback. */
export function PushSettings({ state, onPrepare, onEnable, onResetExisting, onRetry, onDisable, disabled = false }: PushSettingsProps) {
  const busy = busyPush(state);
  const blocked = disabled || busy;
  const canReset = state.browserSubscription === 'present' && state.backendBinding === 'unconfirmed' && ['unconfirmed', 'error'].includes(state.phase);
  const canPrepare = ['idle', 'unsupported', 'disabled', 'denied', 'error', 'off'].includes(state.phase) && !canReset;
  return <section className="card" aria-label="Уведомления на этом устройстве" aria-busy={busy}>
    <h3>Уведомления на этом устройстве</h3>
    <p>Уведомления об обновлениях нарядов. На экране блокировки показывается общий текст без сведений о сотрудниках и нарядах.</p>
    <p role="status" aria-live="polite">{pushMessage(state)}</p>
    <p className="hint">{PUSH_POLICY}</p>
    <p className="hint">Работа с нарядами остаётся доступна без уведомлений. Автоматического подключения и повторных запросов разрешения нет.</p>
    {canPrepare && <button className="secondary" type="button" disabled={blocked} onClick={onPrepare}>{state.phase === 'idle' ? 'Проверить настройки' : 'Проверить снова'}</button>}
    {state.phase === 'ready' && <button type="button" disabled={blocked} onClick={onEnable}>Включить уведомления</button>}
    {canReset && <button className="secondary" type="button" disabled={blocked} onClick={onResetExisting}>Удалить прежнюю подписку на этом устройстве</button>}
    {['unknown', 'remove-unknown', 'local-cleanup'].includes(state.phase) && <button type="button" disabled={blocked} onClick={onRetry}>{state.phase === 'local-cleanup' ? 'Повторить отключение в браузере' : 'Повторить тот же запрос'}</button>}
    {state.phase === 'connected' && <button className="secondary" type="button" disabled={blocked} onClick={onDisable}>Отключить уведомления</button>}
  </section>;
}
