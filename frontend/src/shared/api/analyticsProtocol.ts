/** Exact additive C111 JSON projections over C3/C4. Decimal values remain strings. */
export interface AnalyticsPeriod { start: string; end: string; display_timezone: 'Asia/Almaty' }
export type PeriodRequest = Pick<AnalyticsPeriod, 'start' | 'end'>;
export interface HistoricalEvidence {
  status: 'synthetic_historical_evidence_unavailable'; historical_order_count: number; historical_submission_count: number;
  historical_after_photo_reference_count: number; missing_after_photo_row_count: number;
  physical_evidence_verified: false; historical_completeness_is_verified_evidence: false;
  source_commit: string; history_sha256: string; loader_version: string; identity_mapping_sha256: string;
}
export interface ReportProvenance { synthetic: boolean; source_ref: string; scope_description: string; domain_as_of: string; captured_at_real: string; coverage: 'consistent_snapshot' | 'frozen_complete_export' | 'partial_keyset' | 'drained_moving_keyset'; history_complete: boolean; historical_evidence?: HistoricalEvidence }
export interface MetricFact { name: string; source_table: 'orders' | 'submissions' | 'reviews'; status: 'ok' | 'no_cohort' | 'missing' | 'partial'; numerator: string | null; denominator: number | null; eligible: number; missing: number; excluded: number; value: string | null; source_ids: string[]; missing_source_ids: string[]; excluded_source_ids: string[]; small_sample: boolean }
export interface ExecutorRating { executor_id: string; human_score: MetricFact; closed_on_time: MetricFact; closed_with_rework: MetricFact; composite_score: null; composite_status: 'unsupported_inputs' }
export interface MaterialFact { material_id: string; label: string | null; unit: string | null; quantity: string; order_ids: string[]; submission_ids: string[]; review_ids: string[] }
export interface ReportOrder { id: string; number: string; version: number; assignment_revision: number; scheduling_revision: number; status: string; type: 'planned' | 'unplanned'; description: string; section_id: string; equipment_id: string; assignment: { executor_id: string; brigade_id: string | null }; created_by: string; issued_at: string; due_at: string; updated_at: string; norm_minutes: number; priority: 'normal' | 'high' | 'emergency'; comment: string; before_photo_ids: string[]; current_submission_id: string | null }
export interface ReportSubmission { id: string; order_id: string; assignment_revision: number; attempt_number: number; submitted_by: string; submitted_at: string; done_late: boolean | null; completeness: 'complete' | 'incomplete' | null; missing_evidence: string[]; payload: { work_description: string; work_code_id: string | null; materials: { material_id: string; quantity: string }[]; after_photo_ids: string[]; comment: string } }
export interface ReportReview { id: string; submission_id: string; reviewer_id: string; decision: 'close' | 'rework'; reason: string; final_score: number | null; created_at: string }
export interface ReportAssessment { id: string; submission_id: string; assignment_revision: number; schema_version: string; mode: 'model' | 'rules_fallback' | 'manual'; model: string | null; model_version: string | null; duration_ms: number; recommendation: 'satisfactory' | 'rework_recommended' | 'needs_master_review'; score: number | null; reasons: string[]; evidence_ids: string[]; fallback_reason: string | null; stale: boolean; created_at: string }
export interface OrderFact { order: ReportOrder; is_overdue: boolean; attempts: { submission: ReportSubmission; review: ReportReview | null; assessments: ReportAssessment[]; assessment_status: 'absent' | 'recorded' }[] }
interface ReportBase { provenance: ReportProvenance; period: AnalyticsPeriod; unavailable_reasons: string[] }
interface Totals { totals_available: boolean; metrics: MetricFact[] | null; ratings: ExecutorRating[] | null; closed_materials: MaterialFact[] | null }
export interface AnalyticsFacts extends ReportBase, Totals { schema_version: 'c3-runtime-facts/1'; orders: OrderFact[] }
export interface ShiftReport extends ReportBase, Totals { report_kind: 'shift'; fact_schema_version: 'c3-runtime-facts/1'; limitations: string[] }
export interface OrderReport extends ReportBase { report_kind: 'order'; fact_schema_version: 'c3-runtime-facts/1'; limitations: string[]; order: OrderFact }

const obj = (v: unknown): v is Record<string, unknown> => Boolean(v && typeof v === 'object' && !Array.isArray(v));
const str = (v: unknown): v is string => typeof v === 'string';
const bool = (v: unknown) => typeof v === 'boolean';
const integer = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v) && v >= 0;
const positive = (v: unknown) => integer(v) && v > 0;
const nullable = (check: (v: unknown) => boolean, v: unknown) => v === null || check(v);
const one = (v: unknown, values: readonly unknown[]) => values.includes(v);
const uuid = (v: unknown): v is string => str(v) && /^[\da-f]{8}-(?:[\da-f]{4}-){3}[\da-f]{12}$/i.test(v);
const array = (v: unknown, check: (v: unknown) => boolean) => Array.isArray(v) && v.length <= 20000 && v.every(check);
const strings = (v: unknown) => array(v, str);
const ids = (v: unknown) => array(v, uuid);
const decimal = (v: unknown) => str(v) && /^-?\d+(?:\.\d+)?$/.test(v);
export const awareInstant = (v: unknown): v is string => str(v) && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
export function validPeriod(v: unknown): v is PeriodRequest { return obj(v) && awareInstant(v.start) && awareInstant(v.end) && Date.parse(v.start) < Date.parse(v.end) && Date.parse(v.end) - Date.parse(v.start) <= 93 * 86400000; }
function historical(v: unknown): boolean { return obj(v) && v.status === 'synthetic_historical_evidence_unavailable' && ['historical_order_count','historical_submission_count','historical_after_photo_reference_count','missing_after_photo_row_count'].every(k => integer(v[k])) && v.physical_evidence_verified === false && v.historical_completeness_is_verified_evidence === false && ['source_commit','history_sha256','loader_version','identity_mapping_sha256'].every(k => str(v[k])); }
function provenance(v: unknown): v is ReportProvenance { return obj(v) && bool(v.synthetic) && str(v.source_ref) && str(v.scope_description) && awareInstant(v.domain_as_of) && awareInstant(v.captured_at_real) && one(v.coverage, ['consistent_snapshot','frozen_complete_export','partial_keyset','drained_moving_keyset']) && bool(v.history_complete) && (v.historical_evidence === undefined || (v.synthetic === true && historical(v.historical_evidence))); }
function metric(v: unknown): boolean { return obj(v) && str(v.name) && one(v.source_table,['orders','submissions','reviews']) && one(v.status,['ok','no_cohort','missing','partial']) && nullable(decimal,v.numerator) && nullable(decimal,v.value) && nullable(integer,v.denominator) && ['eligible','missing','excluded'].every(k=>integer(v[k])) && ids(v.source_ids) && ids(v.missing_source_ids) && ids(v.excluded_source_ids) && bool(v.small_sample); }
function rating(v: unknown): boolean { return obj(v) && uuid(v.executor_id) && metric(v.human_score) && metric(v.closed_on_time) && metric(v.closed_with_rework) && v.composite_score === null && v.composite_status === 'unsupported_inputs'; }
function material(v: unknown): boolean { return obj(v) && uuid(v.material_id) && nullable(str,v.label) && nullable(str,v.unit) && decimal(v.quantity) && ids(v.order_ids) && ids(v.submission_ids) && ids(v.review_ids); }
function order(v: unknown): v is ReportOrder { return obj(v) && uuid(v.id) && str(v.number) && ['version','assignment_revision','scheduling_revision','norm_minutes'].every(k=>positive(v[k])) && one(v.status,['issued','queued','accepted','rejected','in_progress','paused','done','ai_review','rework','closed','cancelled']) && one(v.type,['planned','unplanned']) && str(v.description) && uuid(v.section_id) && uuid(v.equipment_id) && obj(v.assignment) && uuid(v.assignment.executor_id) && nullable(uuid,v.assignment.brigade_id) && uuid(v.created_by) && ['issued_at','due_at','updated_at'].every(k=>awareInstant(v[k])) && one(v.priority,['normal','high','emergency']) && str(v.comment) && ids(v.before_photo_ids) && nullable(uuid,v.current_submission_id); }
function submission(v: unknown): v is ReportSubmission { return obj(v) && uuid(v.id) && uuid(v.order_id) && positive(v.assignment_revision) && positive(v.attempt_number) && uuid(v.submitted_by) && awareInstant(v.submitted_at) && nullable(bool,v.done_late) && one(v.completeness,['complete','incomplete',null]) && strings(v.missing_evidence) && obj(v.payload) && str(v.payload.work_description) && nullable(uuid,v.payload.work_code_id) && array(v.payload.materials,m=>obj(m)&&uuid(m.material_id)&&decimal(m.quantity)) && ids(v.payload.after_photo_ids) && str(v.payload.comment); }
function review(v: unknown): v is ReportReview { return obj(v) && uuid(v.id) && uuid(v.submission_id) && uuid(v.reviewer_id) && one(v.decision,['close','rework']) && str(v.reason) && nullable(integer,v.final_score) && (v.final_score===null || (v.final_score as number)<=100) && awareInstant(v.created_at); }
function assessment(v: unknown): v is ReportAssessment { return obj(v) && uuid(v.id) && uuid(v.submission_id) && positive(v.assignment_revision) && str(v.schema_version) && one(v.mode,['model','rules_fallback','manual']) && nullable(str,v.model) && nullable(str,v.model_version) && integer(v.duration_ms) && one(v.recommendation,['satisfactory','rework_recommended','needs_master_review']) && nullable(integer,v.score) && (v.score===null || (v.score as number)<=100) && strings(v.reasons) && strings(v.evidence_ids) && nullable(str,v.fallback_reason) && bool(v.stale) && awareInstant(v.created_at); }
function orderFact(v: unknown): boolean {
  if (!obj(v) || !order(v.order) || !bool(v.is_overdue) || !Array.isArray(v.attempts)) return false;
  const o=v.order;
  return array(v.attempts,a=>{
    if(!obj(a)||!submission(a.submission))return false;
    const sub=a.submission;
    return sub.order_id.toLowerCase()===o.id.toLowerCase()&&nullable(review,a.review)&&(a.review===null||(a.review as ReportReview).submission_id.toLowerCase()===sub.id.toLowerCase())&&array(a.assessments,x=>assessment(x)&&x.submission_id.toLowerCase()===sub.id.toLowerCase()&&x.assignment_revision===sub.assignment_revision)&&one(a.assessment_status,['absent','recorded'])&&((a.assessments as unknown[]).length>0)===(a.assessment_status==='recorded');
  });
}
function base(v: unknown): v is Record<string, unknown> & ReportBase { return obj(v) && provenance(v.provenance) && validPeriod(v.period) && (v.period as AnalyticsPeriod).display_timezone==='Asia/Almaty' && Date.parse(v.period.end)<=Date.parse(v.provenance.domain_as_of) && strings(v.unavailable_reasons); }
function totals(v: Record<string, unknown> & ReportBase): boolean { return bool(v.totals_available) && (v.totals_available ? ['consistent_snapshot','frozen_complete_export'].includes(v.provenance.coverage) && v.provenance.history_complete && array(v.metrics,metric) && array(v.ratings,rating) && array(v.closed_materials,material) : v.metrics===null && v.ratings===null && v.closed_materials===null); }
export function isAnalyticsFacts(v: unknown): v is AnalyticsFacts { return base(v) && v.schema_version==='c3-runtime-facts/1' && totals(v) && array(v.orders,orderFact); }
export function isShiftReport(v: unknown): v is ShiftReport { return base(v) && v.report_kind==='shift' && v.fact_schema_version==='c3-runtime-facts/1' && totals(v) && strings(v.limitations); }
export function isOrderReport(v: unknown): v is OrderReport { return base(v) && v.report_kind==='order' && v.fact_schema_version==='c3-runtime-facts/1' && orderFact(v.order) && strings(v.limitations); }
