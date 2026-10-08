import { awareInstant, validPeriod } from '../../shared/api/analyticsProtocol';
import type { AnalyticsPeriod, PeriodRequest, ReportProvenance } from '../../shared/api/analyticsProtocol';
import { array, ids, integer, nullable, object, sameId, text, texts, uuid } from './validation';

export type AiReportKind = 'shift' | 'history';
export interface AiReportRequest extends PeriodRequest { operation_id: string; report_kind: AiReportKind }
/** sourceRef is a local display fence. The server captures a fresh authorized snapshot. */
export interface AiReportSelection extends PeriodRequest { sourceRef: string }
export interface AiReport {
  schema_version: 'ai-report-summary/1'; operation_id: string; report_kind: AiReportKind;
  mode: 'openai' | 'recorded_fixture' | 'deterministic_fallback'; label: string; summary: string;
  highlights: { fact_id: string; text: string; source_table: string; source_ids: string[]; equipment_id: string | null }[];
  recommendations: { code: string; text: string; fact_ids: string[] }[];
  provenance: ReportProvenance; period: AnalyticsPeriod; limitations: string[]; unavailable_reasons: string[];
  fallback_reason: string | null; model: string | null; generated_at_real: string; advisory: true; reserved_upper_bound_microusd: number; actual_billed_cost: null;
}
export const aiReportSelectionKey = (selection: AiReportSelection | null): string => selection ? JSON.stringify([selection.start, selection.end, selection.sourceRef]) : '';
export function validAiReportRequest(value: unknown): value is AiReportRequest {
  if (!object(value) || !uuid(value.operation_id) || !['history', 'shift'].includes(String(value.report_kind))) return false;
  const kind = value.report_kind;
  return validPeriod(value) && (kind === 'history' || Date.parse(value.end) - Date.parse(value.start) <= 86400000);
}
function provenance(v: unknown): v is ReportProvenance {
  if (!object(v) || typeof v.synthetic !== 'boolean' || !text(v.source_ref) || !text(v.scope_description) || !awareInstant(v.domain_as_of) || !awareInstant(v.captured_at_real) || !['consistent_snapshot', 'frozen_complete_export', 'partial_keyset', 'drained_moving_keyset'].includes(String(v.coverage)) || typeof v.history_complete !== 'boolean') return false;
  if (v.historical_evidence === undefined) return true;
  const h = v.historical_evidence;
  return v.synthetic === true && object(h) && h.status === 'synthetic_historical_evidence_unavailable' && ['historical_order_count', 'historical_submission_count', 'historical_after_photo_reference_count', 'missing_after_photo_row_count'].every(k => integer(h[k])) && h.physical_evidence_verified === false && h.historical_completeness_is_verified_evidence === false && ['source_commit', 'history_sha256', 'loader_version', 'identity_mapping_sha256'].every(k => text(h[k]));
}
export function isAiReport(v: unknown): v is AiReport {
  if (!object(v) || v.schema_version !== 'ai-report-summary/1' || !uuid(v.operation_id) || !['shift', 'history'].includes(String(v.report_kind)) || !['openai', 'recorded_fixture', 'deterministic_fallback'].includes(String(v.mode)) || v.advisory !== true || !text(v.label) || !text(v.summary) || !provenance(v.provenance) || !validPeriod(v.period) || (v.period as AnalyticsPeriod).display_timezone !== 'Asia/Almaty' || Date.parse(v.period.end) > Date.parse(v.provenance.domain_as_of) || !awareInstant(v.generated_at_real) || !texts(v.limitations) || !texts(v.unavailable_reasons) || !nullable(text, v.fallback_reason) || !nullable(text, v.model) || !integer(v.reserved_upper_bound_microusd) || v.actual_billed_cost !== null) return false;
  if ((v.mode === 'openai' || v.mode === 'recorded_fixture') && (typeof v.model !== 'string' || !v.model.trim() || v.fallback_reason !== null)) return false;
  if (v.mode === 'deterministic_fallback' && (v.model !== null || typeof v.fallback_reason !== 'string' || !v.fallback_reason.trim())) return false;
  if (v.report_kind === 'shift' && Date.parse(v.period.end) - Date.parse(v.period.start) > 86400000) return false;
  if (!array(v.highlights, h => object(h) && text(h.fact_id) && !!h.fact_id && text(h.text) && ['orders', 'submissions', 'reviews'].includes(String(h.source_table)) && ids(h.source_ids) && nullable(uuid, h.equipment_id), 200)) return false;
  const highlights = v.highlights as AiReport['highlights'];
  const factIds = new Set(highlights.map(h => h.fact_id));
  return factIds.size === highlights.length && array(v.recommendations, r => object(r) && text(r.code) && text(r.text) && texts(r.fact_ids) && r.fact_ids.every(id => factIds.has(id)), 100);
}
export function decodeAiReport(value: unknown, request: AiReportRequest): AiReport {
  if (!isAiReport(value) || !sameId(value.operation_id, request.operation_id) || value.report_kind !== request.report_kind || Date.parse(value.period.start) !== Date.parse(request.start) || Date.parse(value.period.end) !== Date.parse(request.end)) throw new Error('Ответ сводки не соответствует выбранному периоду или исходному запросу.');
  return value;
}
