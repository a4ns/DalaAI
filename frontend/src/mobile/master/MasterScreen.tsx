import { useId, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import type { MutationOutcome, ResourceState } from '../../shared/ui/types';
import type { MasterCreateDraft, MasterOrderVM, MasterPhotoControlProps, MasterScreenProps } from './types';
import { emptyMasterCreateDraft, emptyMasterReviewDraft } from './types';
import { canApplyPhotoResult, closeBlockers, executorLoad, formatMasterTime, normalizeOutcome, orderStatusLabels, resourceIsCurrent, reviewErrors, validateCreate, type DraftErrors } from './masterModel';
import './master.css';

export type * from './types';
export { emptyMasterCreateDraft, emptyMasterReviewDraft } from './types';

type Operation = { phase: 'idle' | 'pending' | MutationOutcome['kind']; message: string; conflictStamp?: string | null; submissionId?: string; order?: MasterOrderVM };
const idle = (): Operation => ({ phase: 'idle', message: '' });
const forOrder = (state: Operation | undefined, order: MasterOrderVM): Operation => state?.phase === 'confirmed' && state.submissionId !== order.submission?.id ? idle() : state || idle();
const locked = (state: Operation) => state.phase === 'pending' || state.phase === 'unknown' || state.phase === 'confirmed' || state.phase === 'conflict';
const unknown = (): MutationOutcome => ({ kind: 'unknown', message: 'Связь прервалась. Сервер мог принять операцию, но результат не подтверждён.' });

function ResourceNotice<T>({ resource, noun }: { resource: ResourceState<T>; noun: string }) {
  if (resource.loadStatus === 'loading') return <p role="status">{resource.snapshot ? `Обновляем ${noun}…` : `Загружаем ${noun}…`}</p>;
  if (resource.loadStatus === 'offline') return <p role="status">Нет сети. {resource.snapshot ? 'Показаны последние сохранённые данные.' : `${noun} ещё не загружены.`}</p>;
  if (resource.loadStatus === 'error' || resource.loadStatus === 'unavailable') return <p className="master-notice master-notice--warning" role="alert">{resource.error || `Не удалось загрузить ${noun}.`} {resource.snapshot ? 'Сохранённые данные могут быть устаревшими.' : 'Пустой список пока не подтверждён.'}</p>;
  if (resource.loadStatus === 'idle') return <p role="status">{noun} ещё не запрошены.</p>;
  if (resource.freshness !== 'fresh') return <p className="master-notice master-notice--warning" role="status">Данные устарели. Перед действием обновите {noun}.</p>;
  if (resource.incomplete) return <p className="master-notice master-notice--warning" role="status">Загружена только часть данных. Обновите {noun} перед действием.</p>;
  if (resource.snapshot === null) return <p role="status">{noun}: результат загрузки не подтверждён.</p>;
  return null;
}
function OperationNotice({ state, confirmedText, retry, resolve, canResolve, online }: {
  state: Operation; confirmedText: string; retry?: () => void; resolve: () => void; canResolve: boolean; online: boolean;
}) {
  if (state.phase === 'idle') return null;
  if (state.phase === 'pending') return <p className="master-notice" role="status">Отправляем. Дождитесь подтверждения сервера…</p>;
  if (state.phase === 'confirmed') return <p className="master-notice master-notice--success" role="status">{confirmedText} {state.message}</p>;
  return <div className="master-notice master-notice--warning" role="alert">
    <p>{state.phase === 'unknown' ? 'Результат не подтверждён. ' : state.phase === 'conflict' ? 'Конфликт данных (409). ' : 'Операция не выполнена. '}{state.message}</p>
    {state.phase === 'unknown' && <><p>Черновик сохранён в открытом экране. Редактирование остановлено, чтобы не создать дубликат.</p>{retry ? <button type="button" disabled={!online} onClick={retry}>Проверить повтором той же операции</button> : <p>Повтор пока недоступен. Обновление списка само по себе не подтверждает исход операции.</p>}</>}
    {state.phase === 'conflict' && <><p>Черновик сохранён. Нажмите «Обновить данные», проверьте изменения и подтвердите новое действие.</p><button type="button" disabled={!canResolve} onClick={resolve}>Продолжить с обновлёнными данными</button></>}
  </div>;
}
function Field({ id, label, error, children, hint }: { id: string; label: string; error?: string; children: ReactNode; hint?: string }) {
  return <div className="master-field"><label htmlFor={id}>{label}</label>{children}{hint && <span className="master-hint" id={`${id}-hint`}>{hint}</span>}{error && <span className="master-error" id={`${id}-error`}>{error}</span>}</div>;
}
function BeforePhotoControl({ render, ...controlProps }: MasterPhotoControlProps & { render: NonNullable<MasterScreenProps['renderBeforePhotos']> }) {
  return <>{render(controlProps)}</>;
}
function Assessment({ order }: { order: MasterOrderVM }) {
  const assessment = order.submission?.assessment;
  return <section className="master-assessment" aria-label="Рекомендация проверки">
    <h4>Помощь при проверке</h4>
    {!assessment ? <p>Оценка ИИ пока отсутствует. Это не подтверждение качества. При полном результате мастер может принять решение вручную.</p> : assessment.stale ? <p>Оценка относится к предыдущим данным и не применяется к этому решению.</p> : <>
      <p><strong>{assessment.mode === 'model' ? 'Модельная оценка' : assessment.mode === 'rules_fallback' ? 'Проверка по правилам, без модельной оценки' : 'Ручной режим проверки'}</strong></p>
      <p>{assessment.recommendation === 'satisfactory' ? 'Рекомендация: результат удовлетворительный.' : assessment.recommendation === 'rework_recommended' ? 'Рекомендация: требуется доработка.' : 'Рекомендация: нужна проверка мастера.'}</p>
      <p>{assessment.score === null ? 'Балл не выставлен.' : `Оценка: ${assessment.score} из 100. Это не вероятность безопасного ремонта.`}</p>
      {assessment.reasons.length ? <ul>{assessment.reasons.map((reason, index) => <li key={index}>{reason}</li>)}</ul> : <p>Объяснение оценки не предоставлено.</p>}
      {assessment.fallbackReason && <p>Причина резервного режима: {assessment.fallbackReason}</p>}
    </>}
    <p className="master-hint">ИИ даёт рекомендацию. Окончательное решение и его причина всегда за мастером. Балл не заменяет обязательные доказательства.</p>
  </section>;
}

/** Mount with an authenticated-user key. The adapter must retain unresolved receipts across navigation. */
export function MasterScreen(props: MasterScreenProps) {
  const prefix = useId();
  const [createState, setCreateState] = useState<Operation>(idle);
  const [reviewStates, setReviewStates] = useState<Record<string, Operation>>({});
  const [createErrors, setCreateErrors] = useState<DraftErrors>({});
  const [reviewValidation, setReviewValidation] = useState<Record<string, string[]>>({});
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState('');
  const mounted = useRef(true);
  useLayoutEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const latestProps = useRef(props);
  const currentCreateState = useRef(createState);
  const applyCreateState = (state: Operation) => { currentCreateState.current = state; setCreateState(state); };
  const photoContext = useMemo(() => ({ sectionId: props.createDraft.sectionId, phase: createState.phase }), [props.createDraft.sectionId, createState.phase]);
  const latestPhotoContext = useRef<object | null>(photoContext);
  useLayoutEffect(() => {
    latestProps.current = props;
    currentCreateState.current = createState;
    latestPhotoContext.current = photoContext;
  }, [props, createState, photoContext]);
  const photoSection = props.createDraft.sectionId;
  const createInFlight = useRef(false);
  const reviewInFlight = useRef(new Set<string>());
  const refreshInFlight = useRef(false);
  const dictionaries = props.dictionaries.snapshot;
  const createLocked = locked(createState);
  const createReady = props.online && resourceIsCurrent(props.dictionaries) && !props.beforePhotosBusy;
  const ordersReady = props.online && resourceIsCurrent(props.orders);
  const updateDraft = <K extends keyof MasterCreateDraft>(key: K, value: MasterCreateDraft[K]) => {
    if (!mounted.current || createInFlight.current || locked(currentCreateState.current)) return;
    latestProps.current.onCreateDraftChange({ ...latestProps.current.createDraft, [key]: value });
    setCreateErrors(current => ({ ...current, [key]: undefined }));
    if (currentCreateState.current.phase === 'rejected') applyCreateState(idle());
  };
  const freshAfter = (resource: ResourceState<unknown>, state: Operation) => resourceIsCurrent(resource) && !!resource.lastConfirmedAt && resource.lastConfirmedAt !== state.conflictStamp;
  async function reload() {
    if (!mounted.current || refreshInFlight.current || !props.online) return;
    refreshInFlight.current = true; setRefreshing(true); setRefreshError('');
    try { await props.onReload(); } catch { if (mounted.current) setRefreshError('Обновление не удалось. Сохранённые данные и черновики не изменены.'); }
    finally { refreshInFlight.current = false; if (mounted.current) setRefreshing(false); }
  }
  async function create(retry = false) {
    if (!mounted.current || createInFlight.current || !props.online) return;
    if (!retry) {
      if (createLocked || !createReady) return;
      const errors = validateCreate(props.createDraft, dictionaries, props.domainNow);
      setCreateErrors(errors);
      if (Object.keys(errors).length) return;
    } else if (createState.phase !== 'unknown' || !props.onRetryCreate) return;
    createInFlight.current = true; latestPhotoContext.current = null; applyCreateState({ phase: 'pending', message: '' });
    let result: MutationOutcome;
    try {
      result = normalizeOutcome(await (retry ? props.onRetryCreate!() : props.onCreate({ ...props.createDraft, beforePhotoIds: [...props.createDraft.beforePhotoIds] })));
    } catch { result = unknown(); }
    createInFlight.current = false;
    if (mounted.current) applyCreateState({ phase: result.kind, message: result.message || '', conflictStamp: latestProps.current.dictionaries.lastConfirmedAt });
  }
  async function review(order: MasterOrderVM, decision: 'close' | 'rework', retry = false) {
    const state = forOrder(reviewStates[order.id], order);
    if (!mounted.current || reviewInFlight.current.has(order.id) || !props.online) return;
    const draft = props.reviewDrafts[order.id] || emptyMasterReviewDraft();
    if (!retry) {
      if (locked(state) || !ordersReady || order.status !== 'ai_review' || !order.submission || order.submission.assignmentRevision !== order.assignmentRevision) return;
      const errors = [...reviewErrors(draft), ...(decision === 'close' ? closeBlockers(order) : [])];
      setReviewValidation(current => ({ ...current, [order.id]: errors }));
      if (errors.length) return;
    } else if (state.phase !== 'unknown' || !props.onRetryReview) return;
    const capturedOrder = retry ? state.order || order : order;
    const capturedSubmissionId = retry ? state.submissionId : order.submission?.id;
    reviewInFlight.current.add(order.id);
    setReviewStates(current => ({ ...current, [order.id]: { phase: 'pending', message: '', submissionId: capturedSubmissionId, order: capturedOrder } }));
    let result: MutationOutcome;
    try {
      result = normalizeOutcome(await (retry ? props.onRetryReview!(order.id) : props.onReview({ orderId: order.id, expectedVersion: order.version, submissionId: order.submission!.id, decision, reason: draft.reason.trim(), finalScore: draft.finalScore.trim() ? Number(draft.finalScore) : null })));
    } catch { result = unknown(); }
    reviewInFlight.current.delete(order.id);
    if (mounted.current) setReviewStates(current => ({ ...current, [order.id]: { phase: result.kind, message: result.message || '', conflictStamp: latestProps.current.orders.lastConfirmedAt, submissionId: capturedSubmissionId, order: capturedOrder } }));
  }
  const draft = props.createDraft;
  const inputId = (key: keyof MasterCreateDraft) => `${prefix}-${key}`;
  const a11y = (key: keyof MasterCreateDraft) => ({ id: inputId(key), 'aria-invalid': Boolean(createErrors[key]), 'aria-describedby': createErrors[key] ? `${inputId(key)}-error` : undefined });
  const currentOrders = props.orders.snapshot || [];
  const retainedOrders = Object.values(reviewStates).filter(state => ['pending', 'unknown', 'conflict'].includes(state.phase) && state.order && !currentOrders.some(order => order.id === state.order!.id)).map(state => state.order!);
  const reviews = [...currentOrders, ...retainedOrders].filter(order => order.status === 'ai_review' || forOrder(reviewStates[order.id], order).phase !== 'idle');
  return <section className="master-screen" lang="ru" aria-labelledby={`${prefix}-screen-title`}>
    <header className="master-header"><div><p className="master-eyebrow">НарядAI · Мастер</p><h1 id={`${prefix}-screen-title`}>Выдать и проверить работу</h1><p>Время указано для участка: UTC+5.</p></div><button type="button" onClick={() => void reload()} disabled={!props.online || refreshing}>{refreshing ? 'Обновляем…' : 'Обновить данные'}</button></header>
    {!props.online && <p className="master-notice master-notice--warning" role="status">Нет сети. Можно заполнить черновик. Он не отправится автоматически и хранится только в текущей сессии.</p>}
    {refreshError && <p className="master-error" role="alert">{refreshError}</p>}
    <section className="master-card" aria-labelledby={`${prefix}-create-title`}>
      <h2 id={`${prefix}-create-title`}>Новый наряд</h2>
      <ResourceNotice resource={props.dictionaries} noun="Справочники" />
      <form noValidate onSubmit={event => { event.preventDefault(); void create(); }} aria-busy={createState.phase === 'pending'}>
        <fieldset disabled={createLocked} className="master-fields"><legend className="master-visually-hidden">Данные нового наряда</legend>
          <div className="master-two-columns">
            <Field id={inputId('type')} label="Вид работы"><select {...a11y('type')} value={draft.type} onChange={event => updateDraft('type', event.target.value as MasterCreateDraft['type'])}><option value="unplanned">Внеплановая</option><option value="planned">Плановая</option></select></Field>
            <Field id={inputId('priority')} label="Приоритет"><select {...a11y('priority')} value={draft.priority} onChange={event => updateDraft('priority', event.target.value as MasterCreateDraft['priority'])}><option value="normal">Обычный</option><option value="high">Высокий</option><option value="emergency">Аварийный</option></select></Field>
          </div>
          {draft.priority === 'emergency' && <p className="master-emergency">Аварийный наряд. Требует срочного ответа исполнителя.</p>}
          <Field id={inputId('description')} label="Задача или неисправность *" error={createErrors.description}><textarea {...a11y('description')} required maxLength={2000} rows={3} value={draft.description} onChange={event => updateDraft('description', event.target.value)} /></Field>
          <div className="master-two-columns">
            <Field id={inputId('sectionId')} label="Участок *" error={createErrors.sectionId} hint={draft.beforePhotoIds.length ? 'Чтобы сменить участок, сначала уберите прикреплённые фото.' : undefined}><select {...a11y('sectionId')} required disabled={draft.beforePhotoIds.length > 0} value={draft.sectionId} onChange={event => { latestPhotoContext.current = null; props.onCreateDraftChange({ ...draft, sectionId: event.target.value, equipmentId: '', executorId: '', brigadeId: '' }); setCreateErrors({}); }}><option value="">Выберите участок</option>{dictionaries?.sections.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></Field>
            <Field id={inputId('equipmentId')} label="Оборудование *" error={createErrors.equipmentId}><select {...a11y('equipmentId')} required value={draft.equipmentId} onChange={event => updateDraft('equipmentId', event.target.value)}><option value="">Выберите оборудование</option>{dictionaries?.equipment.filter(item => item.sectionId === draft.sectionId).map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></Field>
          </div>
          <Field id={inputId('brigadeId')} label="Назначение бригаде" error={createErrors.brigadeId} hint="У бригады обязательно должен быть один ответственный исполнитель."><select {...a11y('brigadeId')} value={draft.brigadeId} onChange={event => { props.onCreateDraftChange({ ...draft, brigadeId: event.target.value, executorId: '' }); setCreateErrors({}); }}><option value="">Индивидуальный исполнитель</option>{dictionaries?.brigades.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></Field>
          <Field id={inputId('executorId')} label="Ответственный исполнитель *" error={createErrors.executorId}><select {...a11y('executorId')} required value={draft.executorId} onChange={event => updateDraft('executorId', event.target.value)}><option value="">Выберите исполнителя</option>{dictionaries?.executors.filter(item => item.sectionIds.includes(draft.sectionId) && (!draft.brigadeId || item.brigadeId === draft.brigadeId)).map(item => <option key={item.id} value={item.id} disabled={!item.onShift}>{item.label} · {executorLoad(item)}</option>)}</select></Field>
          <div className="master-two-columns">
            <Field id={inputId('dueLocal')} label="Срок выполнения (UTC+5) *" error={createErrors.dueLocal}><input {...a11y('dueLocal')} type="datetime-local" required value={draft.dueLocal} onChange={event => updateDraft('dueLocal', event.target.value)} /></Field>
            <Field id={inputId('normMinutes')} label="Норма времени, минут *" error={createErrors.normMinutes}><input {...a11y('normMinutes')} type="number" inputMode="numeric" required min={1} max={525600} step={1} value={draft.normMinutes} onChange={event => updateDraft('normMinutes', event.target.value)} /></Field>
          </div>
          {!props.domainNow && <p className="master-hint">Время сервера пока неизвестно. Допустимость срока будет проверена при выдаче; срок сам не изменится.</p>}
          <Field id={inputId('comment')} label="Комментарий к наряду" error={createErrors.comment}><textarea {...a11y('comment')} maxLength={2000} rows={2} value={draft.comment} onChange={event => updateDraft('comment', event.target.value)} /></Field>
          <section aria-label="Фото до выполнения"><h3>Фото до выполнения · необязательно</h3>{props.renderBeforePhotos ? <BeforePhotoControl render={props.renderBeforePhotos} disabled={createLocked || !props.online || !draft.sectionId} sectionId={draft.sectionId} photoIds={draft.beforePhotoIds} onPhotoIdsChange={photoIds => { if (canApplyPhotoResult({ mounted: mounted.current, locked: createInFlight.current || locked(currentCreateState.current), expectedGeneration: photoContext, currentGeneration: latestPhotoContext.current, expectedSection: photoSection, currentSection: latestProps.current.createDraft.sectionId })) updateDraft('beforePhotoIds', photoIds); }} /> : <p className="master-hint">Загрузка фото пока не подключена.</p>}{createErrors.beforePhotoIds && <p className="master-error">{createErrors.beforePhotoIds}</p>}</section>
        </fieldset>
        {Object.keys(createErrors).some(key => createErrors[key as keyof DraftErrors]) && <p className="master-error" role="alert">Проверьте отмеченные поля. Черновик не отправлен.</p>}
        {props.beforePhotosBusy && <p role="status">Дождитесь завершения загрузки выбранных фото перед выдачей.</p>}
        <button className="master-primary" type="submit" disabled={!createReady || createLocked}>{createState.phase === 'pending' ? 'Выдаём наряд…' : 'Выдать наряд'}</button>
      </form>
      <OperationNotice state={createState} online={props.online} confirmedText="Выдача наряда подтверждена сервером." retry={props.onRetryCreate ? () => void create(true) : undefined} canResolve={freshAfter(props.dictionaries, createState)} resolve={() => applyCreateState(idle())} />
      {createState.phase === 'confirmed' && <button type="button" onClick={() => { latestPhotoContext.current = null; props.onCreateDraftChange(emptyMasterCreateDraft()); setCreateErrors({}); applyCreateState(idle()); }}>Создать следующий наряд</button>}
    </section>
    <section className="master-review-list" aria-labelledby={`${prefix}-review-title`}>
      <h2 id={`${prefix}-review-title`}>Результаты на проверке</h2>
      <ResourceNotice resource={props.orders} noun="Наряды" />
      {props.online && resourceIsCurrent(props.orders) && reviews.length === 0 && <p className="master-notice">Сейчас нет результатов на проверке.</p>}
      {reviews.map(order => {
        const state = forOrder(reviewStates[order.id], order);
        const reviewDraft = props.reviewDrafts[order.id] || emptyMasterReviewDraft();
        const blockers = closeBlockers(order);
        const validTarget = order.status === 'ai_review' && !!order.submission && order.submission.assignmentRevision === order.assignmentRevision;
        const frozen = locked(state);
        const reasonId = `${prefix}-${order.id}-reason`;
        const scoreId = `${prefix}-${order.id}-score`;
        return <article key={order.id} className="master-card" aria-labelledby={`${prefix}-${order.id}-title`} aria-busy={state.phase === 'pending'}>
          <header><p className="master-eyebrow">{orderStatusLabels[order.status]} · версия {order.version}</p><h3 id={`${prefix}-${order.id}-title`}>Наряд {order.number}</h3></header>
          <p><strong>{order.equipmentLabel}</strong></p><p>{order.description}</p>
          <dl className="master-details"><div><dt>Ответственный</dt><dd>{order.executorLabel}</dd></div><div><dt>Срок</dt><dd>{formatMasterTime(order.dueAt)}{order.isOverdue ? ' · Просрочен' : ''}</dd></div></dl>
          {!order.submission ? <p className="master-notice">Детали результата ещё не загружены. Решение недоступно.</p> : <>
            <h4>Результат исполнителя · попытка {order.submission.attemptNumber}</h4><p className="master-preline">{order.submission.workDescription || 'Описание работ не указано.'}</p><p>Шифр работ: {order.submission.workCodeLabel || 'не указан'}</p>
            {order.submission.materials.length ? <ul>{order.submission.materials.map((material, index) => <li key={index}>{material.label}: {material.quantity} {material.unit}</li>)}</ul> : <p>Материалы не указаны.</p>}
            <p>Фото после выполнения: {order.submission.afterPhotoCount}{order.type === 'unplanned' ? ' · обязательны' : ''}</p>{props.renderAfterPhotos?.(order)}
            {order.submission.comment && <p className="master-preline">Комментарий: {order.submission.comment}</p>}
            <Assessment order={order} />
          </>}
          {blockers.length > 0 && <div className="master-notice master-notice--warning"><strong>Закрытие недоступно</strong><ul>{blockers.map((reason, index) => <li key={index}>{reason}</li>)}</ul><p>Можно вернуть результат на доработку с причиной, когда загружена актуальная попытка.</p></div>}
          <fieldset disabled={frozen || !validTarget} className="master-fields"><legend>Решение мастера</legend>
            <Field id={reasonId} label="Причина решения *"><textarea id={reasonId} required maxLength={2000} rows={3} value={reviewDraft.reason} onChange={event => { props.onReviewDraftChange(order.id, { ...reviewDraft, reason: event.target.value }); setReviewValidation(current => ({ ...current, [order.id]: [] })); }} /></Field>
            <Field id={scoreId} label="Итоговая оценка мастера (необязательно)" hint="Пустое поле означает «без оценки», а не ноль."><input id={scoreId} type="number" inputMode="numeric" min={0} max={100} step={1} value={reviewDraft.finalScore} onChange={event => { props.onReviewDraftChange(order.id, { ...reviewDraft, finalScore: event.target.value }); setReviewValidation(current => ({ ...current, [order.id]: [] })); }} /></Field>
          </fieldset>
          {!!reviewValidation[order.id]?.length && <ul className="master-error" role="alert">{reviewValidation[order.id].map((error, index) => <li key={index}>{error}</li>)}</ul>}
          <div className="master-actions"><button className="master-primary" type="button" disabled={!ordersReady || frozen || !validTarget || blockers.length > 0} onClick={() => void review(order, 'close')}>Принять и закрыть</button><button type="button" disabled={!ordersReady || frozen || !validTarget} onClick={() => void review(order, 'rework')}>Вернуть на доработку</button></div>
          <OperationNotice state={state} confirmedText="Решение мастера подтверждено сервером." online={props.online} retry={props.onRetryReview ? () => void review(order, 'close', true) : undefined} canResolve={freshAfter(props.orders, state)} resolve={() => setReviewStates(current => ({ ...current, [order.id]: idle() }))} />
        </article>;
      })}
    </section>
  </section>;
}
