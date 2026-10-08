import { useCallback, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react';
import { MasterScreen } from '../mobile/master/MasterScreen';
import { dueLocalToIso, resourceIsCurrent } from '../mobile/master/masterModel';
import { emptyMasterCreateDraft } from '../mobile/master/types';
import type { MasterCreateDraft, MasterReviewDraft, MasterReviewIntent } from '../mobile/master/types';
import { ExecutorScreen } from '../mobile/executor/ExecutorScreen';
import { ResultAnalysisDisclosure } from '../mobile/executor/ResultAnalysisDisclosure';
import type { ExecutorDraft, ExecutorIntent } from '../mobile/executor/types';
import { PanelScreen } from '../panel/PanelScreen';
import type { PanelHistory } from '../panel/types';
import { ApiError, SessionChangedError, safeErrorMessage } from '../shared/api/client';
import type { ApiClient, PreparedMutation } from '../shared/api/client';
import { readAllOrderEvents } from '../shared/api/orderStore';
import type { OrderStore } from '../shared/api/orderStore';
import type { CommandResult, Dictionaries, Order, Session, Submission } from '../shared/api/wire';
import { initialResource } from '../shared/ui/types';
import type { MutationOutcome, MutationState, ResourceState } from '../shared/ui/types';
import { useConnectivity } from '../pwa/useConnectivity';
import { executorDictionaries, executorOrder, mapResource, masterDictionaries, masterOrder, panelEmployees, panelEvent, panelOrder } from './adapters';
import { useResource } from './useResource';
import { mutationFailureState, withNewIntentGuard } from './mutationFailure';
import { PhotoStore } from './photoStore';
import type { PhotoContext } from './photoStore';
import { PhotoStages } from './PhotoStages';
import { ProtectedPhoto } from './ProtectedPhoto';
import { ExecutorController } from './executorController';
import { AnalyticsScreen } from '../features/analytics/AnalyticsScreen';
import { AssigneeRecommendations } from '../features/assigneeRecommendations/AssigneeRecommendations';
import { assigneeContextKey, eligibleExecutor } from '../features/assigneeRecommendations/controller';
import type { AssigneeContext } from '../features/assigneeRecommendations/controller';
import { sameId } from '../features/aiReports/validation';

function recommendationContext(draft: MasterCreateDraft, generation: number, dicts: ResourceState<Dictionaries>): AssigneeContext | null {
  if (!resourceIsCurrent(dicts) || !dicts.lastConfirmedAt || !dicts.snapshot?.sections.some(section => sameId(section.id, draft.sectionId))) return null;
  return { sectionId: draft.sectionId, workCodeId: null, brigadeId: draft.brigadeId, dictionaryKey: dicts.lastConfirmedAt,
    draftKey: JSON.stringify([generation, draft.sectionId, draft.equipmentId, draft.type, draft.brigadeId, draft.description, draft.priority, draft.dueLocal, draft.normMinutes, draft.comment]) };
}
const submissionKey = (order: Order): string => `${order.id}:${order.version}:${order.assignment_revision}:${order.current_submission_id ?? 'none'}`;
type Pending = { token: PreparedMutation<CommandResult>; status: MutationState['status']; epoch: number; unresolved: boolean };
export function Workspace({ client, orders, session, sessionKey, section, isAuthReady = () => true, authBusy = false }: { client: ApiClient; orders: OrderStore; session: Session; sessionKey: string; section: string; isAuthReady?: () => boolean; authBusy?: boolean }) {
  const source = useSyncExternalStore(orders.subscribe, orders.getSnapshot);
  const { state: dictState, refresh: refreshDicts, setState: setDictState } = useResource(client, () => client.getDictionaries());
  const [createDraft, setCreateDraft] = useState(emptyMasterCreateDraft);
  const [draftGeneration, setDraftGeneration] = useState(0);
  const [photos] = useState(() => new PhotoStore(client));
  useSyncExternalStore(photos.subscribe, photos.getSnapshot);
  const [executor] = useState(() => new ExecutorController(client, orders, photos, sessionKey));
  useSyncExternalStore(executor.subscribe, executor.getSnapshot);
  useEffect(() => { const timer = setInterval(() => photos.tick(), 1000); return () => clearInterval(timer); }, [photos]);
  const beforeContext: PhotoContext = { key: `${sessionKey}:draft:${draftGeneration}:${createDraft.sectionId}:before`, phase: 'before', sectionId: createDraft.sectionId };
  const [reviewDrafts, setReviewDrafts] = useState<Record<string, MasterReviewDraft>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const pending = useRef(new Map<string, Pending>());
  const dirty = JSON.stringify(createDraft) !== JSON.stringify(emptyMasterCreateDraft()) || Object.values(reviewDrafts).some(draft => draft.reason || draft.finalScore) || executor.hasDrafts || photos.hasWork;
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  const mounted = useRef(true);
  const connectivity = useConnectivity();
  const online = connectivity !== 'offline';
  const adviceDictionaryAllowed = useRef(false);
  const adviceSnapshot = useRef({ draft: createDraft, generation: draftGeneration, dicts: dictState, online, authBusy });
  useLayoutEffect(() => { adviceDictionaryAllowed.current = resourceIsCurrent(dictState); }, [dictState]);
  useLayoutEffect(() => { adviceSnapshot.current = { draft: createDraft, generation: draftGeneration, dicts: dictState, online, authBusy }; }, [createDraft, draftGeneration, dictState, online, authBusy]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { void refreshDicts(); }, [refreshDicts]);
  const rows = source.snapshot ?? [];
  const reviewFingerprint = rows.filter(order => order.status === 'ai_review' && order.current_submission_id).map(order => `${order.id}:${order.version}:${order.current_submission_id}:${order.assignment_revision}`).join('|');
  const { state: submissionState, refresh: refreshSubmissions } = useResource<Record<string, Submission>>(client, async () => {
    const epoch = client.epoch;
    const loaded: Record<string, Submission> = {};
    const requested = (orders.getSnapshot().snapshot ?? []).filter(order => order.status === 'ai_review' && order.current_submission_id);
    for (let offset = 0; offset < requested.length; offset += 3) {
      if (epoch !== client.epoch) throw new SessionChangedError();
      await Promise.all(requested.slice(offset, offset + 3).map(async order => {
        const submission = await client.getSubmission(order.id, order.current_submission_id!);
        const latest = orders.getSnapshot().snapshot?.find(item => item.id === order.id);
        if (submission.order_id !== order.id || !latest || latest.version !== order.version || latest.current_submission_id !== submission.id || latest.assignment_revision !== submission.assignment_revision) throw new ApiError('Результат изменился во время загрузки. Обновите данные.');
        loaded[submissionKey(order)] = submission;
      }));
    }
    return loaded;
  });
  useEffect(() => { if (session.principal.role === 'master') void refreshSubmissions(); }, [reviewFingerprint, session.principal.role, refreshSubmissions]);
  const refresh = useCallback(async () => { adviceDictionaryAllowed.current = false; try { const epoch = client.epoch; await client.getMe(); if (epoch !== client.epoch) return; setNotice(null); await Promise.all([orders.refresh(), refreshDicts()]); if (session.principal.role === 'master') await refreshSubmissions(); } catch (error) { if (mounted.current && !(error instanceof SessionChangedError)) setNotice(safeErrorMessage(error)); } }, [client, orders, refreshDicts, refreshSubmissions, session.principal.role]);
  const { state: historyState, refresh: refreshHistory } = useResource<PanelHistory>(client, async () => {
    if (!selected) throw new ApiError('Выберите наряд.');
    const orderId = selected; const epoch = client.epoch;
    const events = await readAllOrderEvents(client, orderId);
    if (epoch !== client.epoch) throw new SessionChangedError();
    const current = await client.getOrder(orderId);
    if (epoch !== client.epoch) throw new SessionChangedError();
    orders.record(current, epoch);
    return { orderId, events: events.map(event => panelEvent(event, dictState.snapshot, session.principal)) };
  });
  const selectedVersion = rows.find(order => order.id === selected)?.version;
  useEffect(() => { if (selected && (session.principal.role === 'master' || session.principal.role === 'manager')) void refreshHistory(); }, [selected, selectedVersion, refreshHistory, session.principal.role]);

  async function execute(key: string, make: (() => PreparedMutation<CommandResult>) | null): Promise<MutationOutcome> {
    let entry = pending.current.get(key);
    if (make) {
      if (entry && (entry.status === 'pending' || entry.status === 'unknown_result')) return { kind: 'unknown', message: 'Предыдущее действие ещё не подтверждено. Повторите исходную операцию.' };
      try { entry = { token: make(), status: 'pending', epoch: client.epoch, unresolved: false }; }
      catch (error) { return { kind: 'rejected', message: safeErrorMessage(error) }; }
      pending.current.set(key, entry);
    }
    if (!entry) return { kind: 'rejected', message: 'Исходная операция недоступна в этой сессии.' };
    entry.status = 'pending';
    try {
      const result = await client.execute(entry.token);
      if (!mounted.current || entry.epoch !== client.epoch) return { kind: 'rejected', message: 'Сессия изменилась.' };
      orders.record(result.order, entry.epoch); entry.status = 'confirmed'; entry.unresolved = false;
      if (key === 'create') { const empty = emptyMasterCreateDraft(); adviceSnapshot.current = { ...adviceSnapshot.current, draft: empty, generation: adviceSnapshot.current.generation + 1 }; setCreateDraft(empty); setDraftGeneration(value => value + 1); }
      void refresh();
      return { kind: 'confirmed' };
    } catch (error) {
      if (!mounted.current || entry.epoch !== client.epoch || error instanceof SessionChangedError) return { kind: 'rejected', message: 'Сессия изменилась.' };
      const status = mutationFailureState(error, entry.unresolved);
      entry.unresolved = status === 'unknown_result'; entry.status = status;
      const message = status === 'unknown_result' ? `Результат исходной операции всё ещё не подтверждён. Последняя попытка: ${safeErrorMessage(error)}` : safeErrorMessage(error);
      if (status === 'conflict') void refresh();
      return { kind: status === 'unknown_result' ? 'unknown' : status === 'conflict' ? 'conflict' : 'rejected', message };
    }
  }
  function create(draft: MasterCreateDraft): Promise<MutationOutcome> {
    return withNewIntentGuard(pending.current.get('create'), () => {
    if (photos.blocked(beforeContext)) return Promise.resolve({ kind: 'rejected', message: 'Подтвердите загрузку выбранных фото или удалите неудачный выбор.' });
    const dueAt = dueLocalToIso(draft.dueLocal);
    if (!dueAt) return Promise.resolve({ kind: 'rejected', message: 'Проверьте срок в UTC+5.' });
    return execute('create', () => client.prepareCreate({ type: draft.type, description: draft.description.trim(), section_id: draft.sectionId, equipment_id: draft.equipmentId, assignment: { executor_id: draft.executorId, brigade_id: draft.brigadeId || null }, due_at: dueAt, norm_minutes: Number(draft.normMinutes), priority: draft.priority, comment: draft.comment.trim(), before_photo_ids: photos.confirmedIds(beforeContext) }));
    });
  }
  function review(intent: MasterReviewIntent): Promise<MutationOutcome> {
    return execute(`review:${intent.orderId}`, () => client.prepareCommand(intent.orderId, { expected_version: intent.expectedVersion, action: 'review', payload: { submission_id: intent.submissionId, decision: intent.decision, reason: intent.reason, final_score: intent.finalScore } }));
  }
  async function act(intent: ExecutorIntent): Promise<MutationOutcome> {
    const outcome = await executor.act(intent);
    if (outcome.kind === 'confirmed' || outcome.kind === 'conflict') void refresh();
    return outcome;
  }
  async function retryExecutor(scope: string): Promise<MutationOutcome> {
    const outcome = await executor.retry(scope);
    if (outcome.kind === 'confirmed' || outcome.kind === 'conflict') void refresh();
    return outcome;
  }
  const masterRows = mapResource(source, items => items.map(order => masterOrder(order, dictState.snapshot, submissionState.snapshot?.[submissionKey(order)] ?? null)));
  if (rows.some(order => order.status === 'ai_review') && (submissionState.freshness !== 'fresh' || submissionState.loadStatus !== 'ready' || rows.some(order => order.status === 'ai_review' && !submissionState.snapshot?.[submissionKey(order)]))) {
    masterRows.freshness = masterRows.snapshot ? 'stale' : 'never'; masterRows.incomplete = true;
    masterRows.loadStatus = submissionState.loadStatus; masterRows.error = submissionState.error;
  }
  const domainNow = rows.reduce<string | null>((latest, order) => !latest || Date.parse(order.domain_now) > Date.parse(latest) ? order.domain_now : latest, null);
  const access = orders.access;
  const executorRows = executor.visibleOrders();
  const visibleDrafts: Record<string, ExecutorDraft> = Object.fromEntries(executorRows.map(order => [order.id, executor.draft(order)]));
  const selectedOrder = executorRows.find(order => order.id === selected);
  const selectedPhotosBusy = selectedOrder ? photos.blocked(executor.photoContext(selectedOrder)) : false;
  const executorView = executor.view(selectedOrder);
  const quarantinedScopes = executor.quarantinedScopes();
  function changeCreateDraft(next: MasterCreateDraft) {
    const intent = pending.current.get('create');
    if (intent?.status === 'pending' || intent?.unresolved) return;
    let nextGeneration = draftGeneration;
    if (next.sectionId !== createDraft.sectionId) {
      if (photos.blocked(beforeContext)) { setNotice('Сначала завершите подготовку или загрузку фото текущего участка.'); return; }
      if (photos.get(beforeContext).files.length) setNotice('Фото относятся к прежнему участку. Для нового участка выберите фото заново.');
      nextGeneration += 1; setDraftGeneration(value => value + 1);
    }
    const accepted = { ...next, beforePhotoIds: [] };
    adviceSnapshot.current = { ...adviceSnapshot.current, draft: accepted, generation: nextGeneration };
    setCreateDraft(accepted);
  }
  const adviceContext = recommendationContext(createDraft, draftGeneration, dictState);
  const adviceKey = assigneeContextKey(adviceContext);
  function adviceIsCurrent(expected: string): boolean {
    const current = adviceSnapshot.current; const intent = pending.current.get('create');
    return mounted.current && isAuthReady() && !current.authBusy && current.online && adviceDictionaryAllowed.current && intent?.status !== 'pending' && !intent?.unresolved
      && expected !== '' && assigneeContextKey(recommendationContext(current.draft, current.generation, current.dicts)) === expected;
  }
  function chooseRecommendedExecutor(id: string) {
    if (!adviceIsCurrent(adviceKey)) return;
    const current = adviceSnapshot.current; const context = recommendationContext(current.draft, current.generation, current.dicts);
    if (!context || !current.dicts.snapshot) return;
    const candidate = masterDictionaries(current.dicts.snapshot).executors.find(row => sameId(row.id, id) && eligibleExecutor(row, context));
    if (candidate) changeCreateDraft({ ...current.draft, executorId: candidate.id });
  }
  if (!session.principal.active) return <section className="card" role="alert"><h3>Учётная запись неактивна</h3><p>Производственные действия недоступны.</p></section>;
  if (access === 'forbidden') return <section className="card" role="alert"><h3>Доступ к нарядам ограничен</h3><p>Прежние данные скрыты. Проверьте текущую сессию.</p><button type="button" onClick={() => void refresh()}>Проверить доступ</button></section>;
  return <>
    {notice && <p className="error" role="alert">{notice}</p>}
    {session.principal.role === 'master' && <div hidden={section !== 'Наряды'}><MasterScreen dictionaries={mapResource(dictState, masterDictionaries)} orders={masterRows} createDraft={{ ...createDraft, beforePhotoIds: photos.confirmedIds(beforeContext) }} onCreateDraftChange={changeCreateDraft} renderAssigneeRecommendations={context => <AssigneeRecommendations client={client} context={adviceContext} executors={dictState.snapshot ? masterDictionaries(dictState.snapshot).executors : []} request={(query,signal)=>client.getAssigneeRecommendations(query,signal)} isAuthReady={isAuthReady} isDraftCurrent={()=>adviceIsCurrent(adviceKey)} disabled={context.disabled || authBusy || !online || !resourceIsCurrent(dictState)} onChoose={chooseRecommendedExecutor} onAccessLost={()=>{ adviceDictionaryAllowed.current=false; setDictState(initialResource<Dictionaries>()); setNotice('Доступ к рекомендациям не подтверждён. Справочники скрыты; обновите данные для повторной проверки доступа.'); }}/>} beforePhotosBusy={photos.blocked(beforeContext)} renderBeforePhotos={context => <PhotoStages store={photos} context={beforeContext} disabled={context.disabled} canEdit={() => { const intent = pending.current.get('create'); return intent?.status !== 'pending' && !intent?.unresolved; }}/>} renderAfterPhotos={order => { const wire = rows.find(item => item.id === order.id); const result = wire ? submissionState.snapshot?.[submissionKey(wire)] : null; return result?.payload.after_photo_ids.map((photoId, index) => <ProtectedPhoto key={photoId} client={client} photoId={photoId} index={index}/>); }} reviewDrafts={reviewDrafts} onReviewDraftChange={(orderId, draft) => { const intent = pending.current.get(`review:${orderId}`); if (intent?.status === 'pending' || intent?.unresolved) return; setReviewDrafts(previous => ({ ...previous, [orderId]: draft })); }} online={online} domainNow={domainNow} onCreate={create} onReview={review} onRetryCreate={() => execute('create', null)} onRetryReview={orderId => execute(`review:${orderId}`, null)} onReload={refresh}/></div>}
    {session.principal.role === 'executor' && <>
      <ExecutorScreen resultAnalysisDisclosure={<ResultAnalysisDisclosure/>} sessionKey={sessionKey} operationScopeKey={executorView.scope} quarantinedIntentCount={quarantinedScopes.length}
        orders={mapResource(source, () => executorRows.map(order => executorOrder(order, dictState.snapshot)))}
        dictionaries={mapResource(dictState, executorDictionaries)} selectedOrderId={selected} drafts={visibleDrafts} photoBusy={selectedPhotosBusy}
        renderPhotoPicker={context => <PhotoStages store={photos} context={executor.photoContext({ id: context.orderId, section_id: context.sectionId, assignment_revision: context.assignmentRevision })} disabled={context.disabled} required={selectedOrder?.type === 'unplanned'} canEdit={() => executor.canEdit(context.orderId, context.assignmentRevision)}/>}
        mutation={executorView.mutation} pendingIntent={executorView.pendingIntent} onSelectOrder={setSelected}
        onDraftChange={(orderId, draft, revision) => executor.setDraft(orderId, revision, draft)} onIntent={act}
        onRetry={() => retryExecutor(executorView.scope)} onRefresh={() => void refresh()} onResolveConflict={() => executor.resolveConflict(executorView.scope)}/>
      {quarantinedScopes.length > 0 && <aside className="notice" aria-label="Сохранённые неподтверждённые действия">
        <p>Прежние данные скрыты, пока доступ к назначению не подтверждён. Исходные запросы и черновики сохранены только в этой сессии. Повтор не создаёт новую попытку.</p>
        {quarantinedScopes.map((scope, index) => <button type="button" key={scope} onClick={() => void retryExecutor(scope)}>Повторить исходное действие {index + 1}</button>)}
      </aside>}
    </>}
    {(session.principal.role === 'master' || session.principal.role === 'manager') && <div hidden={session.principal.role === 'master' && section !== 'Обзор смены'}><PanelScreen orders={mapResource(source, items => items.map(order => panelOrder(order, dictState.snapshot)))} employees={mapResource(dictState, panelEmployees)} selectedOrderId={selected} onSelectOrder={setSelected} history={historyState} onRefresh={() => void refresh()} onRefreshHistory={() => void refreshHistory()} access={access}/></div>}
    {session.principal.role === 'master' && <div hidden={section !== 'Аналитика и отчёты'}><AnalyticsScreen client={client} isAuthReady={isAuthReady} authBusy={authBusy} domainNow={rows.map(row=>row.domain_now).sort((a,b)=>Date.parse(b)-Date.parse(a))[0]??null} onRefreshClock={()=>void refresh()}/></div>}
    {session.principal.role === 'admin' && <section className="card"><h3>Административная сессия</h3><p>Производственные действия и административные инструменты не предоставлены этой версии интерфейса.</p></section>}
  </>;
}
