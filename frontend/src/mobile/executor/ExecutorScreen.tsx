import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import type { MutationOutcome, MutationState, ResourceState } from '../../shared/ui/types';
import {
  ACTION_LABELS, STATUS_LABELS, allowedActions, emptyExecutorDraft, formatExecutorTime,
  incompleteEvidence, isConfirmedEmpty, isFreshResource, toSubmitPayload, validateExecutorDraft,
} from './model';
import type { DraftErrors } from './model';
import type { ExecutorAction, ExecutorDraft, ExecutorIntent, ExecutorIntentSummary, ExecutorPhotoContext, ExecutorScreenProps } from './types';
import './executor.css';

export type { ExecutorScreenProps } from './types';

// Presentation only: freshness guards still require a completed successful load.
function isRefreshingConfirmedSnapshot(resource: ResourceState<unknown>): boolean {
  return resource.loadStatus === 'loading' && resource.snapshot !== null &&
    resource.freshness !== 'never' && Boolean(resource.lastConfirmedAt) && !resource.incomplete && resource.error === null;
}

function ResourceNotice<T>({ resource, name }: { resource: ResourceState<T>; name: string }) {
  if (isRefreshingConfirmedSnapshot(resource)) return null;
  if (resource.loadStatus === 'loading') return <p role="status">{name}: загрузка…</p>;
  if (resource.loadStatus === 'offline') return <p className="executor-notice" role="status">Нет сети. {resource.snapshot ? 'Показаны сохранённые данные; они могут быть устаревшими.' : `${name} пока не получены.`} Отправка недоступна.</p>;
  if (resource.loadStatus === 'error' || resource.loadStatus === 'unavailable') return <p className="executor-notice executor-notice--error" role="alert">{resource.error || `${name} не удалось получить.`} {resource.snapshot ? 'Показан последний снимок.' : 'Наличие данных не подтверждено.'}</p>;
  if (resource.freshness === 'stale' || resource.incomplete) return <p className="executor-notice" role="status">{name}: {resource.incomplete ? 'получены не полностью' : 'снимок устарел'}. Обновите данные перед действием.</p>;
  if (resource.freshness === 'never') return <p role="status">{name} ещё не загружены.</p>;
  return null;
}

function outcomeState(outcome: MutationOutcome): MutationState {
  if (outcome.kind === 'confirmed') return { status: 'confirmed', error: null };
  return { status: outcome.kind === 'unknown' ? 'unknown_result' : outcome.kind === 'conflict' ? 'conflict' : 'failed', error: outcome.message };
}

function PhotoPickerSlot({ render, context }: { render: NonNullable<ExecutorScreenProps['renderPhotoPicker']>; context: ExecutorPhotoContext }) {
  return render(context);
}

type FormState = { scopeKey: string; orderId: string | null; mode: 'result' | 'pause' | 'reject'; errors: DraftErrors };
type LocalFeedback = { scopeKey: string; value: MutationState | null; parentStatus: MutationState['status']; parentError: string | null };

/** Controlled feature: snapshots and drafts live in the shell, never in storage here. */
export function ExecutorScreen(props: ExecutorScreenProps) {
  return <ExecutorScreenContent key={props.sessionKey} {...props} />;
}

function ExecutorScreenContent(props: ExecutorScreenProps) {
  const id = useId();
  const scopedOperations = props.operationScopeKey !== undefined;
  const scopeKey = props.operationScopeKey ?? 'legacy';
  const [form, setForm] = useState<FormState>({ scopeKey, orderId: props.selectedOrderId, mode: 'result', errors: {} });
  const [localFeedback, setLocalFeedback] = useState<LocalFeedback>({ scopeKey, value: null, parentStatus: props.mutation.status, parentError: props.mutation.error });
  const feedbackIsCurrent = localFeedback.scopeKey === scopeKey && localFeedback.parentStatus === props.mutation.status && localFeedback.parentError === props.mutation.error;
  if (!feedbackIsCurrent) {
    // Guarded render-time adjustment prevents old feedback resurfacing after a parent-state cycle.
    setLocalFeedback({ scopeKey, value: null, parentStatus: props.mutation.status, parentError: props.mutation.error });
  }
  const [conflictRefresh, setConflictRefresh] = useState<{ scopeKey: string; lastConfirmedAt: string | null } | null>(null);
  const mode = form.scopeKey === scopeKey && form.orderId === props.selectedOrderId ? form.mode : 'result';
  const errors = form.scopeKey === scopeKey && form.orderId === props.selectedOrderId ? form.errors : {};
  const [localIntent, setLocalIntent] = useState<{ scopeKey: string; intent: ExecutorIntentSummary } | null>(null);
  const [filter, setFilter] = useState<'active' | 'all'>('active');
  const inFlight = useRef(false);
  const committedScope = useRef(scopeKey);
  const mounted = useRef(true);
  const draftLocked = useRef(false);
  const detailHeading = useRef<HTMLHeadingElement | null>(null);
  const requestedDetailFocus = useRef<string | null>(null);
  const operationFeedbackRegion = useRef<HTMLDivElement | null>(null);
  const requestedOperationScroll = useRef<{ scopeKey: string; selectedOrderId: string | null; assignmentRevision: number | null; intentOrderId: string | null } | null>(null);
  const latestDrafts = useRef(props.drafts);
  const latestOrders = useRef(props.orders.snapshot);
  const rows = useRef(0);
  const mutation = feedbackIsCurrent && localFeedback.value ? localFeedback.value : props.mutation;
  const activeIntent = props.pendingIntent ?? (localIntent?.scopeKey === scopeKey ? localIntent.intent : null);
  const orders = props.orders.snapshot ?? [];
  const selected = orders.find((order) => order.id === props.selectedOrderId) ?? null;
  const draft = selected ? props.drafts[selected.id] ?? emptyExecutorDraft() : emptyExecutorDraft();
  const pending = mutation.status === 'pending';
  const unresolved = mutation.status === 'unknown_result' || mutation.status === 'conflict';
  const frozen = pending || unresolved;
  const fresh = isFreshResource(props.orders);
  const dictionariesFresh = isFreshResource(props.dictionaries);
  const actedOrder = activeIntent ? orders.find((order) => order.id === activeIntent.orderId) : null;
  const awaitingSnapshot = mutation.status === 'confirmed' && activeIntent !== null &&
    (!fresh || Boolean(actedOrder && actedOrder.version <= activeIntent.expectedVersion));
  const canCommand = fresh && !frozen && !awaitingSnapshot;
  const refreshingConfirmedSnapshot = isRefreshingConfirmedSnapshot(props.orders);
  // A routine poll must not retract an already observed post-command version.
  // Keep the wait notice when that version is still missing, including a missing order.
  const showAwaitingSnapshot = awaitingSnapshot && !(refreshingConfirmedSnapshot && activeIntent &&
    actedOrder && actedOrder.version > activeIntent.expectedVersion);
  const missing = selected ? incompleteEvidence(selected, draft) : [];
  const photoBlocked = props.photoBusy === true;
  const photoBlockedReason = props.photoBusyReason || 'Результат подготовки или загрузки фото ещё не подтверждён. Завершите действие с фото перед отправкой результата.';
  const visibleOrders = orders.filter((order) => filter === 'all' || !['closed', 'cancelled', 'rejected'].includes(order.status));
  const activeCount = orders.filter((order) => !['closed', 'cancelled', 'rejected'].includes(order.status)).length;

  useLayoutEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useLayoutEffect(() => {
    if (committedScope.current !== scopeKey) inFlight.current = false;
    committedScope.current = scopeKey;
    latestDrafts.current = props.drafts;
    latestOrders.current = props.orders.snapshot;
    draftLocked.current = frozen;
  }, [props.drafts, props.orders.snapshot, frozen, scopeKey]);
  useEffect(() => {
    // Only a deliberate card selection requests focus. Polls and initial selection never do.
    if (requestedDetailFocus.current !== props.selectedOrderId) return;
    requestedDetailFocus.current = null;
    detailHeading.current?.focus({ preventScroll: true });
    detailHeading.current?.scrollIntoView({ block: 'start', inline: 'nearest' });
  }, [props.selectedOrderId]);
  useEffect(() => {
    // Consume only a deliberate command/retry request. Polls and late outcomes never request scrolling.
    const request = requestedOperationScroll.current;
    requestedOperationScroll.current = null;
    if (!request || request.scopeKey !== scopeKey || request.selectedOrderId !== props.selectedOrderId ||
      request.assignmentRevision !== (selected?.assignmentRevision ?? null) || request.intentOrderId !== (activeIntent?.orderId ?? null)) return;
    operationFeedbackRegion.current?.scrollIntoView({ block: 'start', inline: 'nearest' });
  }, [localFeedback, localIntent, props.selectedOrderId, selected?.assignmentRevision, scopeKey, activeIntent?.orderId]);
  function acceptsEventFromScope(): boolean {
    return mounted.current && (!scopedOperations || committedScope.current === scopeKey);
  }
  function setMode(value: FormState['mode']) {
    if (!acceptsEventFromScope()) return;
    setForm((previous) => ({ scopeKey, orderId: props.selectedOrderId, mode: value, errors: previous.scopeKey === scopeKey && previous.orderId === props.selectedOrderId ? previous.errors : {} }));
  }
  function setErrors(value: DraftErrors) {
    if (!acceptsEventFromScope()) return;
    setForm((previous) => ({ scopeKey, orderId: props.selectedOrderId, mode: previous.scopeKey === scopeKey && previous.orderId === props.selectedOrderId ? previous.mode : 'result', errors: value }));
  }
  function setLocalMutation(value: MutationState) {
    if (!acceptsEventFromScope()) return;
    setLocalFeedback({ scopeKey, value, parentStatus: props.mutation.status, parentError: props.mutation.error });
  }
  function refreshOrders() {
    if (!acceptsEventFromScope()) return;
    if (mutation.status === 'conflict') setConflictRefresh({ scopeKey, lastConfirmedAt: props.orders.lastConfirmedAt });
    props.onRefresh();
  }

  const patchDraft = (patch: Partial<ExecutorDraft>) => {
    if (!selected || !mounted.current || (scopedOperations && committedScope.current !== scopeKey) || draftLocked.current || inFlight.current) return;
    props.onDraftChange(selected.id, { ...(latestDrafts.current[selected.id] ?? emptyExecutorDraft()), ...patch }, selected.assignmentRevision);
  };

  function selectOrder(orderId: string) {
    if (!acceptsEventFromScope() || (!scopedOperations && (draftLocked.current || inFlight.current))) return;
    if (orderId === props.selectedOrderId) {
      requestedDetailFocus.current = null;
      detailHeading.current?.focus({ preventScroll: true });
      detailHeading.current?.scrollIntoView({ block: 'start', inline: 'nearest' });
      return;
    }
    requestedDetailFocus.current = orderId;
    setForm({ scopeKey, orderId, mode: 'result', errors: {} });
    props.onSelectOrder(orderId);
  }

  async function perform(intent?: ExecutorIntent) {
    // Synchronous latch closes the gap before React renders a disabled button.
    if (!mounted.current || (scopedOperations && committedScope.current !== scopeKey) || inFlight.current || pending) return;
    if (intent && (!canCommand || draftLocked.current)) return;
    if (!intent && mutation.status !== 'unknown_result') return;
    inFlight.current = true;
    draftLocked.current = true;
    setConflictRefresh(null);
    const attemptScope = scopeKey;
    requestedOperationScroll.current = { scopeKey: attemptScope, selectedOrderId: props.selectedOrderId, assignmentRevision: selected?.assignmentRevision ?? null, intentOrderId: intent?.orderId ?? activeIntent?.orderId ?? null };
    if (intent) setLocalIntent({ scopeKey: attemptScope, intent: { orderId: intent.orderId, expectedVersion: intent.expectedVersion, action: intent.action } });
    setLocalMutation({ status: 'pending', error: null });
    try {
      const outcome = intent ? await props.onIntent(intent) : await props.onRetry();
      if (mounted.current && (!scopedOperations || committedScope.current === attemptScope)) setLocalMutation(outcomeState(outcome));
    } catch {
      // An adapter exception does not prove that the server rejected the command.
      if (mounted.current && (!scopedOperations || committedScope.current === attemptScope)) setLocalMutation({ status: 'unknown_result', error: 'Ответ не получен. Результат действия не подтверждён.' });
    } finally {
      if (!scopedOperations || committedScope.current === attemptScope) inFlight.current = false;
    }
  }

  function command(action: ExecutorAction) {
    if (!acceptsEventFromScope()) return;
    if (!selected || !canCommand || !allowedActions(selected.status).includes(action)) return;
    const base = { orderId: selected.id, expectedVersion: selected.version, expectedAssignmentRevision: selected.assignmentRevision };
    if (action === 'submit') {
      const nextErrors = validateExecutorDraft(draft, props.dictionaries.snapshot);
      if (!dictionariesFresh) nextErrors.dictionaries = 'Обновите справочники перед отправкой результата.';
      if (photoBlocked) nextErrors.photoActivity = photoBlockedReason;
      setErrors(nextErrors);
      if (Object.keys(nextErrors).length) return;
      void perform({ ...base, action, payload: toSubmitPayload(draft) });
    } else if (action === 'reject' || action === 'pause') {
      const reason = draft.reason.trim();
      if (!reason || reason.length > 2000) { setErrors({ reason: 'Укажите причину: от 1 до 2000 символов.' }); return; }
      setErrors({});
      void perform({ ...base, action, payload: { reason } });
    } else {
      setErrors({});
      void perform({ ...base, action, payload: {} });
    }
  }

  function changeFilter(value: 'active' | 'all') {
    if (!acceptsEventFromScope()) return;
    setFilter(value);
  }
  function addMaterial() {
    if (!acceptsEventFromScope() || draftLocked.current || inFlight.current) return;
    rows.current += 1;
    patchDraft({ materials: [...draft.materials, { rowId: `${id}-${rows.current}`, materialId: '', quantity: '' }] });
  }

  const fieldError = (key: string) => errors[key] ? <span className="executor-field-error" id={`${id}-${key.replace(':', '-')}-error`}>{errors[key]}</span> : null;
  const describedBy = (key: string) => errors[key] ? `${id}-${key.replace(':', '-')}-error` : undefined;
  const hasConfirmedRefresh = mutation.status === 'conflict' && conflictRefresh !== null && conflictRefresh.scopeKey === scopeKey && fresh && props.orders.lastConfirmedAt !== null && props.orders.lastConfirmedAt !== conflictRefresh.lastConfirmedAt;

  // Keep one announcement beside its order; a different or absent selection uses the global location.
  const operationBelongsToSelected = selected !== null && (!activeIntent || activeIntent.orderId === selected.id);
  const operationFeedback = (!scopedOperations || selected !== null) && <div ref={operationFeedbackRegion} className="executor-operation">
    <p role="status" aria-live="polite" aria-atomic="true">{pending ? 'Отправляем действие. Дождитесь ответа; повторное нажатие заблокировано.' : mutation.status === 'confirmed' ? <>Действие подтверждено сервером.{showAwaitingSnapshot ? ' Обновляемый статус ещё не получен. Нажмите «Обновить».' : ''}</> : null}</p>
    {mutation.status === 'unknown_result' && <div className="executor-notice" role="alert"><strong>Результат не подтверждён</strong><p>{mutation.error} Черновик сохранён в этом сеансе и заморожен. Повтор отправит исходное действие с тем же идентификатором; новое действие не создаётся.</p><button className="executor-button" type="button" disabled={props.orders.loadStatus === 'offline'} onClick={() => void perform()}>Повторить исходное действие</button></div>}
    {mutation.status === 'conflict' && <div className="executor-notice" role="alert"><strong>Наряд изменился</strong><p>{mutation.error || 'Сервер отклонил действие из-за конфликта.'} Черновик сохранён. Обновите наряды, проверьте текущий статус и явно подтвердите работу с новой версией.</p><button className="executor-button executor-button--secondary" type="button" disabled={props.orders.loadStatus === 'loading'} onClick={refreshOrders}>Загрузить актуальное состояние</button><button className="executor-button" type="button" disabled={!hasConfirmedRefresh} onClick={() => { if (!hasConfirmedRefresh || (scopedOperations && committedScope.current !== scopeKey)) return; props.onResolveConflict(); setLocalMutation({ status: 'idle', error: null }); setConflictRefresh(null); setLocalIntent(null); setErrors({}); }}>Состояние проверено, продолжить</button></div>}
    {mutation.status === 'failed' && <p className="executor-notice executor-notice--error" role="alert">{mutation.error || 'Действие отклонено.'} Черновик сохранён. Исправьте причину перед новой отправкой.</p>}
  </div>;

  return <section className="executor-screen" aria-labelledby={`${id}-title`}>
    <header className="executor-header">
      <div><p className="executor-eyebrow">Исполнитель · НарядAI</p><h1 id={`${id}-title`}>Мои наряды</h1><p>{fresh || refreshingConfirmedSnapshot ? `Активных: ${activeCount}` : 'Список требует подтверждения'}</p></div>
      <button type="button" className="executor-button executor-button--secondary" onClick={refreshOrders} disabled={pending || props.orders.loadStatus === 'loading'}>Обновить</button>
    </header>
    <ResourceNotice resource={props.orders} name="Наряды" />
    {props.orders.lastConfirmedAt && <p className="executor-caption">Последнее подтверждение: {formatExecutorTime(props.orders.lastConfirmedAt)}</p>}
    {(props.quarantinedIntentCount ?? 0) > 0 && <p className="executor-notice" role="status">Есть действие с неподтверждённым результатом для наряда с изменившимся доступом. Исходная попытка сохранена отдельно. Можно работать с другими доступными нарядами.</p>}
    {!operationBelongsToSelected && operationFeedback}
    {orders.length > 0 && <div className="executor-filters" role="group" aria-label="Какие наряды показать"><button type="button" aria-pressed={filter === 'active'} onClick={() => changeFilter('active')}>Активные</button><button type="button" aria-pressed={filter === 'all'} onClick={() => changeFilter('all')}>Все</button></div>}
    {(isConfirmedEmpty(props.orders) || (refreshingConfirmedSnapshot && orders.length === 0)) && <div className="executor-empty"><h2>Назначенных нарядов нет</h2><p>Список получен с сервера. Обновите его, когда мастер выдаст новый наряд.</p></div>}
    {orders.length > 0 && visibleOrders.length === 0 && <p>В полученном списке нет активных нарядов. Выберите «Все», чтобы увидеть остальные.</p>}
    <div className="executor-layout">
      <nav aria-label="Назначенные наряды" className="executor-order-list">
        {visibleOrders.map((order) => <button key={order.id} type="button" disabled={!scopedOperations && frozen} className={`executor-order-card${selected?.id === order.id ? ' executor-order-card--selected' : ''}`} aria-pressed={selected?.id === order.id} onClick={() => selectOrder(order.id)}>
          <span className="executor-order-top"><strong>Наряд {order.number}</strong><span className="executor-status">{STATUS_LABELS[order.status]}</span></span>
          <span>{order.equipmentLabel}</span><span className="executor-card-description">{order.description}</span>
          <span className="executor-caption">До {formatExecutorTime(order.dueAt)}</span>
          {order.priority === 'emergency' && <span className="executor-urgent">Аварийный · требуется внимание</span>}
          {order.priority === 'high' && <span>Высокий приоритет</span>}
          {order.isOverdue && <span className="executor-urgent">Срок истёк</span>}
        </button>)}
      </nav>
      {selected ? <article className="executor-detail" aria-labelledby={`${id}-order-title`}>
        <header><p className="executor-eyebrow">{selected.sectionLabel} · Версия {selected.version}</p><h2 ref={detailHeading} tabIndex={-1} className="executor-detail-title" id={`${id}-order-title`}>Наряд {selected.number}</h2><p className="executor-detail-equipment">{selected.equipmentLabel}</p><p><span className="executor-status">{STATUS_LABELS[selected.status]}</span> · {selected.type === 'unplanned' ? 'Внеплановая работа' : 'Плановая работа'}</p></header>
        {operationBelongsToSelected && operationFeedback}
        <p className="executor-preserve-lines">{selected.description}</p>
        {selected.comment && <p className="executor-preserve-lines"><strong>Комментарий мастера: </strong>{selected.comment}</p>}
        <p>Срок: <time dateTime={selected.dueAt}>{formatExecutorTime(selected.dueAt)}</time>{selected.isOverdue && <strong className="executor-urgent"> · Просрочен</strong>}</p>
        {!fresh && !refreshingConfirmedSnapshot && <p className="executor-caption">Действия станут доступны после получения актуального полного списка.</p>}
        <div className="executor-actions" role="group" aria-label={`Действия по наряду ${selected.number}`}>
          {allowedActions(selected.status).filter((action) => action !== 'submit').map((action) => <button className={`executor-button${action === 'reject' || action === 'pause' || action === 'queue' ? ' executor-button--secondary' : ''}`} type="button" key={action} disabled={!canCommand} onClick={() => { if (action === 'reject' || action === 'pause') { setMode(action); setErrors({}); } else command(action); }}>{ACTION_LABELS[action]}</button>)}
        </div>
        {(mode === 'reject' && selected.status === 'issued' || mode === 'pause' && selected.status === 'in_progress') && <form className="executor-form" onSubmit={(event) => { event.preventDefault(); command(mode === 'reject' ? 'reject' : 'pause'); }}>
          <h3>{mode === 'reject' ? 'Причина отклонения' : 'Причина паузы'}</h3>
          <label htmlFor={`${id}-reason`}>Причина обязательна</label><textarea id={`${id}-reason`} value={draft.reason} maxLength={2000} disabled={frozen} onChange={(event) => patchDraft({ reason: event.target.value })} aria-invalid={Boolean(errors.reason)} aria-describedby={describedBy('reason')} rows={3} />{fieldError('reason')}
          <div className="executor-actions"><button className="executor-button" type="submit" disabled={!canCommand}>{mode === 'reject' ? 'Отклонить с причиной' : 'Поставить на паузу'}</button><button className="executor-button executor-button--secondary" type="button" disabled={frozen} onClick={() => { setMode('result'); setErrors({}); }}>Вернуться без отправки</button></div>
        </form>}
        {((selected.status === 'in_progress' && mode === 'result') || ['done', 'ai_review', 'rework', 'closed'].includes(selected.status)) && props.resultAnalysisDisclosure}
        {selected.status === 'in_progress' && mode === 'result' && <form className="executor-form" noValidate onSubmit={(event) => { event.preventDefault(); command('submit'); }}>
          <h3>Результат работы</h3><p className="executor-caption">Черновик сохраняется в текущем сеансе. После перезагрузки или выхода он может быть потерян.</p>
          <ResourceNotice resource={props.dictionaries} name="Справочники" />
          <label htmlFor={`${id}-work`}>Что выполнено <span aria-hidden="true">*</span></label><textarea id={`${id}-work`} value={draft.workDescription} onChange={(event) => patchDraft({ workDescription: event.target.value })} disabled={frozen} maxLength={6000} rows={5} required aria-invalid={Boolean(errors.workDescription)} aria-describedby={describedBy('workDescription')} placeholder="Опишите выполненные действия и результат" />{fieldError('workDescription')}
          <label htmlFor={`${id}-code`}>Шифр работ</label><select id={`${id}-code`} value={draft.workCodeId} onChange={(event) => patchDraft({ workCodeId: event.target.value })} disabled={frozen || !dictionariesFresh} aria-invalid={Boolean(errors.workCodeId)} aria-describedby={describedBy('workCodeId')}><option value="">Не указан</option>{props.dictionaries.snapshot?.workCodes.map((option) => <option key={option.id} value={option.id}>{option.code} · {option.label}</option>)}</select>{fieldError('workCodeId')}
          <fieldset disabled={frozen}><legend>Материалы и расход</legend><p className="executor-caption">Если материалы не использовались, оставьте список пустым. Единица расхода указана в справочнике.</p>
            {draft.materials.map((row, index) => {
              const materialKey = `material:${row.rowId}`;
              const quantityKey = `quantity:${row.rowId}`;
              const material = props.dictionaries.snapshot?.materials.find((item) => item.id === row.materialId);
              const rowPrefix = `${id}-row-${row.rowId}`;
              return <div className="executor-material" key={row.rowId}><label htmlFor={`${rowPrefix}-material`}>Материал {index + 1}</label><select id={`${rowPrefix}-material`} value={row.materialId} disabled={!dictionariesFresh} onChange={(event) => patchDraft({ materials: draft.materials.map((item) => item.rowId === row.rowId ? { ...item, materialId: event.target.value } : item) })} aria-invalid={Boolean(errors[materialKey])} aria-describedby={describedBy(materialKey)}><option value="">Выберите материал</option>{props.dictionaries.snapshot?.materials.map((option) => <option key={option.id} value={option.id}>{option.code} · {option.label} ({option.unit})</option>)}</select>{fieldError(materialKey)}<label htmlFor={`${rowPrefix}-quantity`}>Количество{material ? `, ${material.unit}` : ''}</label><input id={`${rowPrefix}-quantity`} inputMode="decimal" type="text" value={row.quantity} onChange={(event) => patchDraft({ materials: draft.materials.map((item) => item.rowId === row.rowId ? { ...item, quantity: event.target.value } : item) })} aria-invalid={Boolean(errors[quantityKey])} aria-describedby={describedBy(quantityKey)} placeholder="Например, 1,5" />{fieldError(quantityKey)}<button className="executor-button executor-button--secondary" type="button" aria-label={`Убрать материал ${index + 1}`} onClick={() => patchDraft({ materials: draft.materials.filter((item) => item.rowId !== row.rowId) })}>Убрать материал</button></div>;
            })}
            <button className="executor-button executor-button--secondary" type="button" disabled={!dictionariesFresh || draft.materials.length >= 40 || props.dictionaries.snapshot?.materials.length === 0} onClick={addMaterial}>Добавить материал</button>{fieldError('materials')}
          </fieldset>
          <fieldset disabled={frozen}><legend>Фото после выполнения</legend>{photoBlocked && <p className="executor-notice" role="status">{photoBlockedReason}</p>}{props.renderPhotoPicker ? <PhotoPickerSlot render={props.renderPhotoPicker} context={{ orderId: selected.id, sectionId: selected.sectionId, assignmentRevision: selected.assignmentRevision, disabled: frozen, confirmedPhotoIds: draft.afterPhotoIds, onConfirmedPhotoIdsChange: (ids) => {
            const currentOrder = latestOrders.current?.find((order) => order.id === selected.id);
            if (!currentOrder || currentOrder.assignmentRevision !== selected.assignmentRevision || currentOrder.sectionId !== selected.sectionId) return;
            patchDraft({ afterPhotoIds: [...ids] });
          } }} /> : <p className="executor-caption">Загрузка фото пока недоступна. Выбранный локальный файл сам по себе не считается загруженным фото.</p>}<p>Подтверждённых фото: {draft.afterPhotoIds.length} из 5.</p>{fieldError('photos')}</fieldset>
          <label htmlFor={`${id}-comment`}>Комментарий к результату</label><textarea id={`${id}-comment`} value={draft.comment} disabled={frozen} onChange={(event) => patchDraft({ comment: event.target.value })} maxLength={2000} rows={3} aria-invalid={Boolean(errors.comment)} aria-describedby={describedBy('comment')} />{fieldError('comment')}
          {missing.length > 0 && <p className="executor-notice">Не хватает: {missing.join(', ')}. Можно отправить неполный результат на проверку. Закрытие наряда будет недоступно, пока обязательные доказательства не добавлены.</p>}
          {Object.keys(errors).length > 0 && <div className="executor-notice executor-notice--error" role="alert"><strong>Проверьте форму:</strong><ul>{Object.entries(errors).map(([key, message]) => <li key={key}>{message}</li>)}</ul></div>}
          <button className="executor-button executor-button--submit" type="submit" disabled={!canCommand || !dictionariesFresh || photoBlocked}>{missing.length ? 'Отправить неполный результат на проверку' : 'Отправить на проверку'}</button>
          <p className="executor-caption">Отправка результата не означает приёмку. Решение принимает мастер.</p>
        </form>}
        {selected.status === 'ai_review' && <p className="executor-notice">Результат на проверке. Окончательное решение принимает мастер. Статус работы ИИ здесь не подтверждён.</p>}
        {selected.status === 'done' && <p className="executor-notice">Результат отправлен. Обновите наряд, чтобы получить актуальный статус проверки.</p>}
        {selected.status === 'rework' && <p className="executor-notice">Мастер вернул работу на доработку. Нажмите «Начать работу», затем отправьте новый результат.</p>}
        {selected.status === 'paused' && <p>Работа приостановлена. Для продолжения нажмите «Продолжить работу».</p>}
        {selected.status === 'queued' && <p>Наряд в очереди. Когда будете готовы, примите его.</p>}
        {selected.status === 'closed' && <p>Наряд закрыт мастером.</p>}
        {selected.status === 'cancelled' && <p>Наряд отменён. Исполнительские действия недоступны.</p>}
        {selected.status === 'rejected' && <p>Наряд отклонён. Дальнейшее назначение определяет мастер.</p>}
      </article> : orders.length > 0 ? <div className="executor-detail"><h2>{props.selectedOrderId ? 'Выбранный наряд отсутствует в полученном списке' : 'Выберите наряд'}</h2><p>{props.selectedOrderId ? 'Обновите список или выберите доступный наряд. Сохранённый черновик не удалён.' : 'Здесь появятся описание, действия и форма результата.'}</p></div> : null}
    </div>
  </section>;
}
