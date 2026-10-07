import { useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ExecutorScreen } from '../../src/mobile/executor/ExecutorScreen';
import { emptyExecutorDraft } from '../../src/mobile/executor/model';
import type { ExecutorDraft, ExecutorIntent, ExecutorOrderViewModel } from '../../src/mobile/executor/types';
import type { MutationOutcome, ResourceState } from '../../src/shared/ui/types';
import '../../src/shared/styles.css';

const order: ExecutorOrderViewModel = {
  id: 'synthetic-order', number: 'UI-001', version: 1, assignmentRevision: 1, sectionId: 'synthetic-section',
  equipmentLabel: 'Синтетическое оборудование', sectionLabel: 'Тестовый участок', status: 'in_progress',
  type: 'unplanned', priority: 'normal', description: 'Проверка интерфейса без API и БД', comment: '',
  dueAt: '2026-10-08T04:00:00Z', isOverdue: false,
};
function resource<T>(snapshot: T): ResourceState<T> {
  return { snapshot, freshness: 'fresh', loadStatus: 'ready', error: null, lastConfirmedAt: '2026-10-07T19:00:00Z', incomplete: false };
}
function Fixture() {
  const [epoch, setEpoch] = useState(1);
  const [drafts, setDrafts] = useState<Record<string, ExecutorDraft>>({ [order.id]: emptyExecutorDraft() });
  const [orders, setOrders] = useState(resource([order]));
  const [outcome, setOutcome] = useState('unknown');
  const [calls, setCalls] = useState(0);
  const [retries, setRetries] = useState(0);
  const [intent, setIntent] = useState<ExecutorIntent | null>(null);
  const pending = useRef<((outcome: MutationOutcome) => void) | null>(null);
  function onIntent(next: ExecutorIntent): Promise<MutationOutcome> {
    setCalls(value => value + 1); setIntent(next);
    if (outcome === 'pending') return new Promise(resolve => { pending.current = resolve; });
    return Promise.resolve({ kind: outcome as 'unknown' | 'conflict', message: 'Синтетический ответ для проверки UI' });
  }
  return <>
    <aside aria-label="Синтетический тест" style={{ background: '#ffe9ab', padding: 16 }}>
      <strong>СИНТЕТИЧЕСКИЙ UI-ТЕСТ. Без настоящего API, БД, AI и устройства.</strong>
      <label>Тестовый исход<select data-testid="outcome" value={outcome} onChange={event => setOutcome(event.target.value)}><option value="unknown">Потерян ответ</option><option value="conflict">Конфликт 409</option><option value="pending">Ожидание</option></select></label>
      <button data-testid="switch-identity" onClick={() => { setEpoch(value => value + 1); setDrafts({ [order.id]: emptyExecutorDraft() }); setIntent(null); setOrders(resource([order])); }}>Сменить тестовую сессию</button>
      <button data-testid="resolve-old" onClick={() => pending.current?.({ kind: 'confirmed' })}>Завершить старый ответ</button>
      <button data-testid="stale" onClick={() => setOrders(value => ({ ...value, freshness: 'stale', loadStatus: 'error', error: 'Синтетический отказ загрузки' }))}>Устаревший снимок</button>
      <output hidden data-testid="calls">{calls}</output><output hidden data-testid="retries">{retries}</output><output hidden data-testid="intent">{JSON.stringify(intent)}</output>
    </aside>
    <ExecutorScreen sessionKey={`synthetic:${epoch}`} orders={orders} dictionaries={resource({ workCodes: [{ id: 'code', code: 'TEST', label: 'Тестовый шифр' }], materials: [] })}
      selectedOrderId={order.id} drafts={drafts} mutation={{ status: 'idle', error: null }} pendingIntent={null}
      onSelectOrder={() => undefined} onDraftChange={(id, draft) => setDrafts(value => ({ ...value, [id]: draft }))}
      onIntent={onIntent} onRetry={async () => { setRetries(value => value + 1); return { kind: 'confirmed' }; }}
      onRefresh={() => setOrders(() => ({ ...resource([{ ...order, version: 2 }]), lastConfirmedAt: '2026-10-07T19:01:00Z' }))}
      onResolveConflict={() => undefined}/>
  </>;
}
createRoot(document.getElementById('root')!).render(<Fixture/>);
