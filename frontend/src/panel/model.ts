import type { ResourceState } from '../shared/ui/types';
import type { PanelEmployee, PanelEvent, PanelOrder } from './types';

const formatter = new Intl.DateTimeFormat('ru-RU', {
  timeZone: 'UTC', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
});

/** Fixed UTC+5, independent of the browser/device timezone or wall clock. */
export function formatPanelTime(value: string | null): string {
  if (!value || !/T.*(?:Z|[+-]\d{2}:\d{2})$/i.test(value)) return 'Время не указано';
  const instant = Date.parse(value);
  if (!Number.isFinite(instant)) return 'Время не указано';
  return `${formatter.format(new Date(instant + 5 * 60 * 60 * 1000))} (UTC+5)`;
}

export function filterPanelOrders(
  items: readonly PanelOrder[], query: string, status: string, overdueOnly: boolean,
): readonly PanelOrder[] {
  const needle = query.trim().toLocaleLowerCase('ru-RU');
  return items.filter((order) =>
    (status === 'all' || order.status === status)
    && (!overdueOnly || order.isOverdue)
    && (!needle || [order.number, order.title, order.sectionLabel, order.equipmentLabel, order.executorLabel]
      .some((value) => value.toLocaleLowerCase('ru-RU').includes(needle))),
  );
}

/** Preserve API list order: its immutable-number keyset ordering belongs to B4. */
export function isConfirmedEmpty<T>(resource: ResourceState<readonly T[]>): boolean {
  return resource.snapshot?.length === 0 && resource.freshness === 'fresh'
    && resource.loadStatus === 'ready' && !resource.incomplete;
}

export function employeeActivityLabel(employee: PanelEmployee): string {
  if (!employee.onShift) return 'Вне смены';
  if (employee.activeOrderId) return 'Есть активный наряд';
  if (employee.queueCount > 0) return 'Есть наряды в очереди';
  return 'Занятость не подтверждена';
}

/** Audit order comes from order-local sequence, never a possibly skewed timestamp. */
export function sortedPanelEvents(events: readonly PanelEvent[]): readonly PanelEvent[] {
  const seen = new Set<string>();
  return [...events].sort((left, right) => right.sequence - left.sequence).filter((event) => {
    if (seen.has(event.id)) return false;
    seen.add(event.id);
    return true;
  });
}
