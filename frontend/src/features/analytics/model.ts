import { awareInstant, validPeriod } from '../../shared/api/analyticsProtocol';
import type { PeriodRequest } from '../../shared/api/analyticsProtocol';
export function localToInstant(value: string): string {
  const match=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(value);
  if (!match) throw new Error('Укажите дату и время в UTC+5.');
  const [y,m,d,h,min,s]=match.slice(1).map(v=>Number(v??0));
  const local=new Date(Date.UTC(y,m-1,d,h,min,s));
  if (y<1000 || local.getUTCFullYear()!==y || local.getUTCMonth()!==m-1 || local.getUTCDate()!==d || local.getUTCHours()!==h || local.getUTCMinutes()!==min || local.getUTCSeconds()!==s) throw new Error('Укажите существующую дату и время.');
  return new Date(local.getTime()-5*3600000).toISOString();
}
export function instantToLocal(value: string): string { return awareInstant(value) ? new Date(Date.parse(value)+5*3600000).toISOString().slice(0,19) : ''; }
export function parsePeriod(start: string, end: string, domainNow: string | null = null): PeriodRequest {
  const period={start:localToInstant(start),end:localToInstant(end)};
  if (!validPeriod(period)) throw new Error('Начало должно быть раньше конца; период — не более 93 суток.');
  if (domainNow && awareInstant(domainNow) && Date.parse(period.end)>Date.parse(domainNow)) throw new Error('Конец периода позже последнего подтверждённого доменного времени. Обновите время или выберите более ранний конец.');
  return period;
}
export function showTime(value: string): string { return awareInstant(value) ? `${instantToLocal(value).replace('T',' ')} UTC+5` : 'Время не подтверждено'; }
export const metricLabels: Record<string,string> = { issued_orders:'Выдано нарядов',submitted_orders:'Отправлено нарядов',submission_attempts:'Отправлено попыток',closed_orders:'Закрыто нарядов',rework_decisions:'Решений о доработке',awaiting_review:'Ожидают проверки',overdue_active:'Просроченные активные наряды',human_score:'Средняя оценка мастера среди закрытых',closed_on_time:'Доля закрытых в срок (0–1)',closed_with_rework:'Доля закрытых с доработкой (0–1)',attempt_on_time:'Доля отправленных попыток в срок (0–1)' };
export const snapshotMetrics=new Set(['awaiting_review','overdue_active']);
export const statusLabels: Record<string,string> = {issued:'Выдан',queued:'В очереди',accepted:'Принят',rejected:'Отклонён',in_progress:'В работе',paused:'Приостановлен',done:'Результат отправлен',ai_review:'На проверке',rework:'На доработке',closed:'Закрыт',cancelled:'Отменён'};
