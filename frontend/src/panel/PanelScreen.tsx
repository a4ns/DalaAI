import { useEffect, useId, useRef, useState } from 'react';
import type { ResourceState } from '../shared/ui/types';
import { employeeActivityLabel, filterPanelOrders, formatPanelTime, isConfirmedEmpty, sortedPanelEvents } from './model';
import { eventLabel, panelStatuses, priorityLabel, statusLabel } from './ru';
import type { PanelHistory, PanelOrder, PanelScreenProps } from './types';
import './panel.css';

export type { PanelScreenProps } from './types';

function ResourceNotice<T>({ resource, subject }: { resource: ResourceState<T>; subject: string }) {
  let message: string;
  if (resource.loadStatus === 'unavailable') message = `${subject}: загрузка недоступна.`;
  else if (resource.loadStatus === 'offline') message = `${subject}: нет сети. Актуальность данных не подтверждена.`;
  else if (resource.loadStatus === 'error') message = `${subject}: не удалось завершить загрузку.`;
  else if (resource.loadStatus === 'loading') message = `${subject}: ${resource.snapshot === null ? 'загружаем данные' : 'обновляем данные'}.`;
  else if (resource.freshness === 'never') message = `${subject}: данные ещё не получены.`;
  else if (resource.freshness === 'stale') message = `${subject}: данные могут быть устаревшими.`;
  else message = `${subject}: последняя загрузка завершена.`;

  const caution = resource.incomplete || resource.freshness === 'stale'
    || ['error', 'offline', 'unavailable'].includes(resource.loadStatus);
  return (
    <div className={`panel-notice${caution ? ' panel-notice--caution' : ''}`} role="status" aria-live="polite">
      <p>{message}</p>
      {resource.incomplete && <p>Получены не все страницы. Полнота списка не подтверждена.</p>}
      {resource.snapshot !== null && resource.freshness !== 'never' && resource.lastConfirmedAt && (
        <p className="panel-muted">Последнее подтверждение: {formatPanelTime(resource.lastConfirmedAt)}</p>
      )}
      {resource.error && <p>{resource.error}</p>}
    </div>
  );
}

function OrderBadges({ order }: { order: PanelOrder }) {
  return (
    <div className="panel-badges">
      <span className="panel-badge">{statusLabel(order.status)}</span>
      <span className={`panel-badge${order.priority === 'emergency' ? ' panel-badge--urgent' : ''}`}>
        Приоритет: {priorityLabel(order.priority)}
      </span>
      {order.isOverdue && <span className="panel-badge panel-badge--overdue">Срок истёк</span>}
    </div>
  );
}

function OrderHistory({ order, resource, onRefresh }: {
  order: PanelOrder;
  resource?: ResourceState<PanelHistory>;
  onRefresh?: (orderId: string) => void;
}) {
  // A response for a previous selection must never be presented as this order's audit.
  const history = resource?.freshness !== 'never' && resource?.snapshot?.orderId === order.id
    ? resource.snapshot : null;
  const events = history ? sortedPanelEvents(history.events) : [];
  const matchingResource = resource?.snapshot && resource.snapshot.orderId !== order.id ? undefined : resource;
  return (
    <>
      <h3>Наряд № {order.number}</h3>
      <p className="panel-order-title">{order.title}</p>
      <OrderBadges order={order} />
      <p className="panel-muted">Версия наряда: {order.version}. Оценка результата в этой панели не загружена.</p>
      {onRefresh && <button type="button" className="panel-button panel-button--secondary"
        onClick={() => onRefresh(order.id)} disabled={matchingResource?.loadStatus === 'loading'}>
        Обновить историю
      </button>}
      {matchingResource ? <ResourceNotice resource={matchingResource} subject="История" />
        : <p role="status">История выбранного наряда ещё не загружена.</p>}
      {events.length > 0 && <ol className="panel-timeline" aria-label={`История наряда № ${order.number}, новые события сначала`}>
        {events.map((event) => (
          <li key={event.id}>
            <div className="panel-event-heading"><strong>{eventLabel(event.kind)}</strong><span>Событие {event.sequence}</span></div>
            <p><time dateTime={event.occurredAt}>{formatPanelTime(event.occurredAt)}</time></p>
            <p>{event.actorLabel || 'Автор не указан'}</p>
            <p>{event.fromStatus ? `${statusLabel(event.fromStatus)} → ` : ''}{statusLabel(event.toStatus)}</p>
            {event.reason && <p className="panel-reason">Причина: {event.reason}</p>}
          </li>
        ))}
      </ol>}
      {history && events.length === 0 && resource?.freshness === 'fresh'
        && resource.loadStatus === 'ready' && !resource.incomplete
        && <p>В загруженной истории событий нет.</p>}
    </>
  );
}

/** Read-only UI. Session isolation, complete sweeps and DTO mapping belong to B4. */
export function PanelScreen({ orders, employees, selectedOrderId, history, onSelectOrder,
  onRefresh, onRefreshHistory, access = 'allowed', dataOrigin = 'api' }: PanelScreenProps) {
  const id = useId();
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('all');
  const [overdueOnly, setOverdueOnly] = useState(false);
  const historyRegion = useRef<HTMLElement>(null);
  const previousSelection = useRef(selectedOrderId);

  useEffect(() => {
    if (access === 'allowed' && selectedOrderId && previousSelection.current !== selectedOrderId) {
      historyRegion.current?.focus();
    }
    previousSelection.current = selectedOrderId;
  }, [access, selectedOrderId]);

  if (access !== 'allowed') {
    return <section className="panel-screen" lang="ru" aria-labelledby={`${id}-title`}>
      <h1 id={`${id}-title`}>Обзор нарядов</h1>
      <p role="alert">{access === 'unauthenticated' ? 'Сеанс завершён. Войдите снова, чтобы увидеть наряды.'
        : 'Нет доступа к этой панели. Данные скрыты.'}</p>
    </section>;
  }

  const rows = orders.freshness === 'never' ? [] : orders.snapshot ?? [];
  const filtered = filterPanelOrders(rows, query, status, overdueOnly);
  const selected = rows.find((order) => order.id === selectedOrderId);
  const staff = employees?.freshness === 'never' ? [] : employees?.snapshot ?? [];
  const filtersActive = query.trim() !== '' || status !== 'all' || overdueOnly;

  return (
    <section className="panel-screen" lang="ru" aria-labelledby={`${id}-title`}>
      <header className="panel-header">
        <div><p className="panel-eyebrow">НарядAI · Только просмотр</p><h1 id={`${id}-title`}>Обзор нарядов</h1>
          <p className="panel-muted">Доступные вам наряды и история изменений. Время UTC+5.</p></div>
        {onRefresh && <button type="button" className="panel-button" onClick={onRefresh}
          disabled={orders.loadStatus === 'loading'}>Обновить данные</button>}
      </header>

      {dataOrigin === 'synthetic' && <p className="panel-synthetic">Синтетические данные · демонстрационный набор</p>}
      <ResourceNotice resource={orders} subject="Наряды" />

      <div className="panel-layout">
        <section className="panel-orders" aria-labelledby={`${id}-orders-title`} aria-busy={orders.loadStatus === 'loading'}>
          <h2 id={`${id}-orders-title`} tabIndex={-1}>Список нарядов</h2>
          <div className="panel-filters" role="search" aria-label="Фильтры загруженных нарядов">
            <div className="panel-field panel-field--search"><label htmlFor={`${id}-search`}>Поиск в загруженных нарядах</label>
              <input id={`${id}-search`} type="search" value={query} placeholder="Номер, оборудование, исполнитель"
                onChange={(event) => setQuery(event.target.value)} /></div>
            <div className="panel-field"><label htmlFor={`${id}-status`}>Статус</label>
              <select id={`${id}-status`} value={status} onChange={(event) => setStatus(event.target.value)}>
                <option value="all">Все статусы</option>
                {Object.entries(panelStatuses).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select></div>
            <label className="panel-checkbox" htmlFor={`${id}-overdue`}>
              <input id={`${id}-overdue`} type="checkbox" checked={overdueOnly}
                onChange={(event) => setOverdueOnly(event.target.checked)} />Только с истёкшим сроком
            </label>
            {filtersActive && <button type="button" className="panel-button panel-button--secondary" onClick={() => {
              setQuery(''); setStatus('all'); setOverdueOnly(false);
            }}>Сбросить фильтры</button>}
          </div>
          {rows.length > 0 && <p className="panel-muted" role="status">Показано из загруженных: {filtered.length} / {rows.length}.
            {orders.incomplete ? ' Список неполный.' : ''}</p>}
          {isConfirmedEmpty(orders) && <div className="panel-empty"><h3>Доступных нарядов нет</h3>
            <p>Это результат последней полной загрузки в вашей области доступа.</p></div>}
          {rows.length > 0 && filtered.length === 0 && <p className="panel-empty" role="status">В загруженных нарядах нет совпадений. Измените или сбросьте фильтры.</p>}
          {filtered.length > 0 && <ul className="panel-order-list">
            {filtered.map((order) => <li key={order.id}>
              <article className={`panel-order${selectedOrderId === order.id ? ' panel-order--selected' : ''}`}>
                <h3>Наряд № {order.number}</h3><p className="panel-order-title">{order.title}</p>
                <OrderBadges order={order} />
                <dl className="panel-facts">
                  <div><dt>Участок</dt><dd>{order.sectionLabel || 'Не указан'}</dd></div>
                  <div><dt>Оборудование</dt><dd>{order.equipmentLabel || 'Не указано'}</dd></div>
                  <div><dt>Ответственный</dt><dd>{order.executorLabel || 'Не указан'}</dd></div>
                  <div><dt>Срок</dt><dd><time dateTime={order.dueAt}>{formatPanelTime(order.dueAt)}</time></dd></div>
                </dl>
                <button type="button" className="panel-button panel-button--secondary" aria-controls={`${id}-history`}
                  aria-pressed={selectedOrderId === order.id} aria-label={`Показать историю наряда № ${order.number}`}
                  onClick={() => onSelectOrder(order.id)}>История наряда</button>
              </article>
            </li>)}
          </ul>}
        </section>

        <section className="panel-history" id={`${id}-history`} ref={historyRegion} tabIndex={-1}
          aria-labelledby={`${id}-history-title`}>
          <h2 id={`${id}-history-title`}>История изменений</h2>
          <a className="panel-back" href={`#${id}-orders-title`}>К списку нарядов</a>
          {selected ? <OrderHistory order={selected} resource={history} onRefresh={onRefreshHistory} />
            : <p>{selectedOrderId ? 'Выбранный наряд отсутствует в доступном списке. Выберите наряд заново.'
              : 'Выберите «История наряда» в списке.'}</p>}
        </section>
      </div>

      <section className="panel-staff" aria-labelledby={`${id}-staff-title`}>
        <h2 id={`${id}-staff-title`}>Исполнители</h2>
        <p className="panel-muted">Очередь учитывает только наряды со статусом «В очереди». Показанный активный наряд может быть одним из нескольких.</p>
        {employees ? <ResourceNotice resource={employees} subject="Исполнители" />
          : <p>Сведения об исполнителях ещё не загружены.</p>}
        {employees && isConfirmedEmpty(employees) && <p>В загруженном справочнике нет доступных исполнителей.</p>}
        {staff.length > 0 && <ul className="panel-staff-list">
          {staff.map((employee) => <li key={employee.id} className="panel-person">
            <h3>{employee.label}</h3>
            <p><span className="panel-badge">{employeeActivityLabel(employee)}</span></p>
            <p>В очереди: {employee.queueCount}</p>
            {employee.activeOrderId && <p>Пример активного наряда: {
              rows.find((order) => order.id === employee.activeOrderId)?.number
                ? `№ ${rows.find((order) => order.id === employee.activeOrderId)?.number}`
                : 'номер не загружен'
            }</p>}
          </li>)}
        </ul>}
      </section>

      <aside className="panel-unavailable" aria-labelledby={`${id}-limits-title`}>
        <h2 id={`${id}-limits-title`}>Отчёты и аналитика</h2>
        <p>Отчёт смены, экспорт, рейтинг и аналитика пока недоступны в подключённом API.</p>
      </aside>
    </section>
  );
}
