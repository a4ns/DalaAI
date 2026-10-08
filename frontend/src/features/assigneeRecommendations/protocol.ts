import { awareInstant } from '../../shared/api/analyticsProtocol';
import { array, integer, nullable, object, sameId, text, texts, uuid } from '../aiReports/validation';

export interface AssigneeRecommendationRequest { section_id: string; work_code_id: string | null; limit: number }
export const reasonLabels: Record<string, string> = {
  ACTIVE_ON_SHIFT: 'Активен и на смене', SELECTED_SECTION_MEMBER: 'Прикреплён к выбранному участку',
  NO_VISIBLE_OUTSTANDING_ORDERS: 'В видимой области нет незавершённых назначений', VISIBLE_OUTSTANDING_ORDERS: 'Есть незавершённые назначения в видимой области',
  ACTIVE_ASSIGNMENTS: 'Есть работа в процессе или на паузе', NO_CLOSED_HISTORY: 'Закрытых работ в выбранной истории нет', HUMAN_SCORE_UNKNOWN: 'Оценка мастера неизвестна',
  WORK_CODE_NOT_SELECTED: 'Шифр работ не выбран; соответствие по шифру не оценивалось', MATCHING_WORK_CODE_HISTORY: 'Есть закрытые работы с выбранным шифром', NO_MATCHING_WORK_CODE_HISTORY: 'Закрытые работы с выбранным шифром не найдены',
};
export const limitationLabels: Record<string, string> = {
  DETERMINISTIC_RULES_NOT_AI: 'Сортировка по правилам; модель ИИ не вызывается', QUALIFICATIONS_UNVERIFIED: 'Специальность, квалификация и допуски не подтверждены',
  WORKLOAD_VISIBLE_SCOPE_ONLY: 'Загрузка учитывает только разрешённые мастеру участки', WORKLOAD_NORM_NOT_REMAINING: 'Сумма норм не означает оставшееся время работы',
  SNAPSHOT_NOT_RESERVATION: 'Снимок не резервирует исполнителя; доступность проверяется снова при выдаче', HISTORICAL_OBSERVATIONS_NOT_SKILL: 'Прошлые работы не доказывают навык или пригодность к этой задаче',
  SYNTHETIC_DATA: 'Синтетические данные, не история предприятия', ONLY_ONE_ELIGIBLE_EXECUTOR: 'Доступен только один исполнитель; альтернативы не выдумываются', NO_ELIGIBLE_EXECUTORS: 'Доступных исполнителей на смене не найдено',
};
const workStatuses = ['issued', 'queued', 'accepted', 'in_progress', 'paused', 'rework', 'done', 'ai_review'] as const;
export interface AssigneeCandidate {
  executor_id: string; employee_code: string; rank: number; on_shift: true;
  workload: {
    outstanding_count: number; active_count: number; queued_count: number; awaiting_review_count: number; overdue_count: number; norm_minutes_total: number;
    status_counts: Record<(typeof workStatuses)[number], number>; scope: 'current_master_authorized_sections';
    evidence: { order_id: string; status: string; due_at: string; updated_at: string }[]; evidence_truncated: boolean;
  };
  history: {
    status: 'observed' | 'no_observations'; window_start: string; window_end: string; closed_count: number; matching_work_code_count: number | null;
    human_score_mean: number | null; human_score_count: number; on_time_rate: number | null; on_time_count: number; latest_closed_at: string | null;
    evidence: { order_id: string; submission_id: string; review_id: string; submitted_at: string; reviewed_at: string; work_code_id: string | null; final_score: number | null; done_late: boolean }[];
    evidence_truncated: boolean;
  };
  reason_codes: string[];
}
export interface AssigneeRecommendations {
  schema_version: '1'; mode: 'rules_baseline'; model: null; model_status: 'disabled_for_purpose'; advisory_only: true; synthetic: boolean;
  section_id: string; work_code_id: string | null; as_of: string; domain_as_of: string; expires_at: string;
  eligible_count: number; returned_count: number; candidates: AssigneeCandidate[]; limitations: string[];
  ranking_policy: 'outstanding_then_active_then_observed_work_code_v1';
}
const bounded = (v: unknown, max: number): v is number => typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= max;
function candidate(v: unknown): v is AssigneeCandidate {
  if (!object(v) || !uuid(v.executor_id) || !text(v.employee_code) || !integer(v.rank) || v.rank < 1 || v.on_shift !== true || !texts(v.reason_codes) || !v.reason_codes.every(code => Object.hasOwn(reasonLabels, code)) || !object(v.workload) || !object(v.history)) return false;
  const w = v.workload; const h = v.history;
  if (!['outstanding_count', 'active_count', 'queued_count', 'awaiting_review_count', 'overdue_count', 'norm_minutes_total'].every(k => integer(w[k])) || w.scope !== 'current_master_authorized_sections' || !object(w.status_counts) || !workStatuses.every(s => integer((w.status_counts as Record<string, unknown>)[s])) || typeof w.evidence_truncated !== 'boolean' || !array(w.evidence, e => object(e) && uuid(e.order_id) && workStatuses.includes(e.status as typeof workStatuses[number]) && awareInstant(e.due_at) && awareInstant(e.updated_at), 5)) return false;
  const counts = w.status_counts as AssigneeCandidate['workload']['status_counts'];
  if (w.outstanding_count !== counts.issued + counts.queued + counts.accepted + counts.in_progress + counts.paused + counts.rework || w.active_count !== counts.in_progress + counts.paused || w.queued_count !== counts.queued || w.awaiting_review_count !== counts.done + counts.ai_review || Number(w.overdue_count) > Number(w.outstanding_count)) return false;
  if (!['observed', 'no_observations'].includes(String(h.status)) || !awareInstant(h.window_start) || !awareInstant(h.window_end) || Date.parse(h.window_start) >= Date.parse(h.window_end) || !['closed_count', 'human_score_count', 'on_time_count'].every(k => integer(h[k])) || !nullable(integer, h.matching_work_code_count) || !nullable(v => bounded(v, 100), h.human_score_mean) || !nullable(v => bounded(v, 1), h.on_time_rate) || !nullable(awareInstant, h.latest_closed_at) || typeof h.evidence_truncated !== 'boolean' || !array(h.evidence, e => object(e) && uuid(e.order_id) && uuid(e.submission_id) && uuid(e.review_id) && awareInstant(e.submitted_at) && awareInstant(e.reviewed_at) && Date.parse(e.submitted_at) <= Date.parse(e.reviewed_at) && nullable(uuid, e.work_code_id) && nullable(v => integer(v) && v <= 100, e.final_score) && typeof e.done_late === 'boolean', 5)) return false;
  const history = h as unknown as AssigneeCandidate['history'];
  return history.human_score_count <= history.closed_count && history.on_time_count <= history.closed_count && (history.matching_work_code_count === null || history.matching_work_code_count <= history.closed_count) && (history.human_score_count === 0) === (history.human_score_mean === null) && (history.closed_count === 0) === (history.status === 'no_observations') && (history.closed_count === 0) === (history.on_time_rate === null) && (history.closed_count === 0) === (history.latest_closed_at === null) && history.evidence.length <= history.closed_count;
}
export function isAssigneeRecommendations(v: unknown): v is AssigneeRecommendations {
  if (!object(v) || v.schema_version !== '1' || v.mode !== 'rules_baseline' || v.model !== null || v.model_status !== 'disabled_for_purpose' || v.advisory_only !== true || typeof v.synthetic !== 'boolean' || !uuid(v.section_id) || !nullable(uuid, v.work_code_id) || !awareInstant(v.as_of) || !awareInstant(v.domain_as_of) || !awareInstant(v.expires_at) || Date.parse(v.expires_at) <= Date.parse(v.as_of) || Date.parse(v.expires_at) - Date.parse(v.as_of) > 30000 || !integer(v.eligible_count) || !integer(v.returned_count) || v.returned_count > v.eligible_count || !array(v.candidates, candidate, 5) || !texts(v.limitations) || !v.limitations.every(code => Object.hasOwn(limitationLabels, code)) || v.ranking_policy !== 'outstanding_then_active_then_observed_work_code_v1') return false;
  const candidates = v.candidates as AssigneeCandidate[];
  return candidates.length === v.returned_count && new Set(candidates.map(c => c.executor_id.toLowerCase())).size === candidates.length && candidates.every(c => (v.work_code_id === null) === (c.history.matching_work_code_count === null) && Date.parse(c.history.window_end) === Date.parse(String(v.domain_as_of)));
}
export function decodeAssigneeRecommendations(value: unknown, request: AssigneeRecommendationRequest, now = Date.now()): AssigneeRecommendations {
  if (!isAssigneeRecommendations(value) || !sameId(value.section_id, request.section_id) || !sameId(value.work_code_id, request.work_code_id) || value.returned_count > request.limit || Date.parse(value.expires_at) <= now) throw new Error('Ответ рекомендаций устарел или не соответствует выбранному участку.');
  return value;
}
