import { useLayoutEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { MasterScreen, emptyMasterCreateDraft } from '../../src/mobile/master/MasterScreen';
import type { MasterCreateDraft, MasterDictionaries, MasterOrderVM, MasterReviewDraft } from '../../src/mobile/master/types';
import { ExecutorScreen } from '../../src/mobile/executor/ExecutorScreen';
import { emptyExecutorDraft } from '../../src/mobile/executor/model';
import type { ExecutorDraft, ExecutorOrderViewModel } from '../../src/mobile/executor/types';
import { PanelScreen } from '../../src/panel/PanelScreen';
import type { PanelEmployee, PanelHistory, PanelOrder } from '../../src/panel/types';
import type { MutationOutcome, ResourceState } from '../../src/shared/ui/types';
import '../../src/shared/styles.css';

/** Synthetic presentation inputs only. No store, fetch, backend, timer or device simulation. */
const phases = ['ready', 'polling', 'initial', 'error', 'offline', 'unavailable', 'incomplete', 'stale',
  'loading-incomplete', 'loading-error', 'loading-unconfirmed', 'loading-never'] as const;
type Phase = typeof phases[number];
const params = new URLSearchParams(location.search);
const screen = params.get('screen') ?? 'master';
const content = params.get('content') ?? 'populated';
const receipt = params.get('receipt') ?? 'none';
const empty = content === 'empty';
const emptyHistory = content === 'history-empty';
const orderId = receipt === 'missing' ? 'synthetic-other-order' : 'synthetic-quiet-order';
const order: ExecutorOrderViewModel = {
  id: orderId, number: 'SYNTHETIC-Q01', version: receipt === 'older' ? 1 : receipt === 'equal' ? 2 : 3,
  assignmentRevision: 1, sectionId: 'synthetic-section', sectionLabel: 'Синтетический участок',
  equipmentLabel: 'Синтетический насос', status: 'in_progress', type: 'planned', priority: 'normal',
  description: 'Синтетическая проверка сохранённого снимка', comment: '', dueAt: '2026-10-08T10:00:00Z', isOverdue: false,
};
const masterOrder: MasterOrderVM = {
  ...order, status: 'ai_review', executorLabel: 'Синтетический исполнитель',
  submission: { id: 'synthetic-submission', assignmentRevision: 1, attemptNumber: 1,
    workDescription: 'Синтетическая выполненная работа', workCodeLabel: 'SYNTHETIC-CODE', materials: [],
    afterPhotoCount: 0, comment: '', completeness: 'complete', missingEvidence: [], assessment: null },
};
const masterDictionaries: MasterDictionaries = {
  sections: [{ id: 'synthetic-section', label: 'Синтетический участок' }],
  equipment: [{ id: 'synthetic-equipment', label: 'Синтетический насос', sectionId: 'synthetic-section' }], brigades: [],
  executors: [{ id: 'synthetic-executor', label: 'Синтетический исполнитель', sectionIds: ['synthetic-section'],
    brigadeId: null, onShift: true, activeOrderId: null, queueCount: 0 }],
};
const panelOrder: PanelOrder = { ...order, title: order.description, executorLabel: 'Синтетический исполнитель' };
const staff: PanelEmployee[] = [{ id: 'synthetic-executor', label: 'Синтетический исполнитель', onShift: true, activeOrderId: orderId, queueCount: 0 }];
const history: PanelHistory = { orderId, events: emptyHistory ? [] : [{ id: 'synthetic-event', sequence: 1,
  occurredAt: '2026-10-08T06:00:00Z', kind: 'order.created', actorLabel: 'Синтетический мастер',
  reason: null, fromStatus: null, toStatus: 'issued' }] };

function resource<T>(snapshot: T, phase: Phase, cycle: number): ResourceState<T> {
  const state: ResourceState<T> = { snapshot, freshness: 'fresh', loadStatus: 'ready', error: null,
    lastConfirmedAt: `2026-10-08T06:0${cycle}:00Z`, incomplete: false };
  if (phase === 'initial') return { ...state, snapshot: null, freshness: 'never', loadStatus: 'loading', lastConfirmedAt: null };
  if (phase === 'polling' || phase.startsWith('loading-')) {
    state.loadStatus = 'loading'; state.freshness = 'stale';
  }
  if (phase === 'error' || phase === 'offline' || phase === 'unavailable') {
    state.loadStatus = phase; state.freshness = 'stale';
  }
  if (phase === 'error' || phase === 'loading-error') state.error = 'Синтетическая ошибка чтения';
  if (phase === 'incomplete' || phase === 'loading-incomplete') state.incomplete = true;
  if (phase === 'stale') state.freshness = 'stale';
  if (phase === 'loading-unconfirmed') state.lastConfirmedAt = null;
  if (phase === 'loading-never') state.freshness = 'never';
  return state;
}

function Fixture() {
  const [state, setState] = useState<{ phase: Phase; cycle: number }>({ phase: 'ready', cycle: 0 });
  const [calls, setCalls] = useState(0);
  const [reads, setReads] = useState(0);
  const [draft, setDraft] = useState<MasterCreateDraft>({ ...emptyMasterCreateDraft(), type: 'planned' as const,
    description: 'Синтетический черновик мастера', sectionId: empty ? '' : 'synthetic-section',
    equipmentId: empty ? '' : 'synthetic-equipment', executorId: empty ? '' : 'synthetic-executor',
    dueLocal: '2026-10-08T15:00', normMinutes: '30' });
  const [reviewDrafts, setReviewDrafts] = useState<Record<string, MasterReviewDraft>>({ [orderId]: { reason: 'Синтетическая причина решения', finalScore: '80' } });
  const [drafts, setDrafts] = useState<Record<string, ExecutorDraft>>({ [orderId]: {
    ...emptyExecutorDraft(), workDescription: 'Синтетический черновик исполнителя', workCodeId: 'synthetic-code' } });
  useLayoutEffect(() => {
    const change = (event: Event) => {
      const detail: unknown = (event as CustomEvent).detail;
      if (!detail || typeof detail !== 'object' || !('phase' in detail) || !('cycle' in detail)) return;
      if (!phases.includes(detail.phase as Phase) || !Number.isInteger(detail.cycle) || Number(detail.cycle) < 0 || Number(detail.cycle) > 3) return;
      setState({ phase: detail.phase as Phase, cycle: Number(detail.cycle) });
    };
    window.addEventListener('synthetic-quiet-refresh', change);
    return () => window.removeEventListener('synthetic-quiet-refresh', change);
  }, []);
  const r = <T,>(snapshot: T) => resource(snapshot, state.phase, state.cycle);
  const mutate = async (): Promise<MutationOutcome> => {
    setCalls(value => value + 1); return { kind: 'rejected', message: 'Синтетический callback; сервер не вызывался' };
  };
  const read = () => setReads(value => value + 1);
  return <>
    <aside aria-label="Синтетическая проверка" style={{ padding: 12, background: '#ffe9ab', overflowWrap: 'anywhere' }}>
      СИНТЕТИЧЕСКИЙ UI-ТЕСТ. Настоящие React-компоненты; входные снимки заданы тестом. Без API, БД и физического устройства.
    </aside>
    <output hidden data-testid="fixture-state" data-phase={state.phase} data-cycle={state.cycle}>{calls}:{reads}</output>
    <div data-testid="product-screen">
      {screen === 'master' && <MasterScreen dictionaries={r(empty ? { sections: [], equipment: [], brigades: [], executors: [] } : masterDictionaries)}
        orders={r(empty ? [] : [{ ...masterOrder }])} createDraft={draft} onCreateDraftChange={setDraft}
        reviewDrafts={reviewDrafts} onReviewDraftChange={(id, value) => setReviewDrafts(previous => ({ ...previous, [id]: value }))}
        online={state.phase !== 'offline'} domainNow="2026-10-08T06:00:00Z" onCreate={mutate} onReview={mutate} onReload={async () => read()} />}
      {screen === 'executor' && <ExecutorScreen sessionKey="synthetic-quiet-session" operationScopeKey={`${orderId}:1`}
        orders={r(empty ? [] : [{ ...order }])} dictionaries={r({ workCodes: empty ? [] : [{ id: 'synthetic-code', code: 'SYNTHETIC', label: 'Синтетический шифр' }], materials: [] })}
        selectedOrderId={empty ? null : orderId} drafts={drafts}
        mutation={{ status: receipt === 'none' ? 'idle' : 'confirmed', error: null }}
        pendingIntent={receipt === 'none' ? null : { orderId: 'synthetic-quiet-order', expectedVersion: 2, action: 'start' }}
        onSelectOrder={() => undefined} onDraftChange={(id, value) => setDrafts(previous => ({ ...previous, [id]: value }))}
        onIntent={mutate} onRetry={mutate} onRefresh={read} onResolveConflict={() => undefined} />}
      {screen === 'panel' && <PanelScreen orders={r(empty ? [] : [{ ...panelOrder }])} employees={r(empty || emptyHistory ? [] : staff)}
        selectedOrderId={empty ? null : orderId} history={r(history)} onSelectOrder={() => undefined}
        onRefresh={read} onRefreshHistory={read} dataOrigin="synthetic" />}
    </div>
    {/* The labelled test-only tail enables a nonzero document scroll for short empty screens.
        It is outside the measured product tree; product CSS and geometry are not overridden. */}
    <footer data-testid="synthetic-scroll-tail" style={{ minHeight: 1200, padding: 12 }}>
      Синтетическая область прокрутки теста. Не часть интерфейса продукта.
    </footer>
  </>;
}
createRoot(document.getElementById('root')!).render(<Fixture/>);
