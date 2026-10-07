import { expect, test } from '@playwright/test';
import { sourceModule } from '../support/source';
import analytics from '../fixtures/analytics/analytics-shift.json';
import shift from '../fixtures/analytics/report-shift.json';
import order from '../fixtures/analytics/report-order.json';
import zero from '../fixtures/analytics/report-shift-zero.json';
import type * as Protocol from '../../src/shared/api/analyticsProtocol';
import type * as Model from '../../src/features/analytics/model';
const { isAnalyticsFacts, isShiftReport, isOrderReport } = sourceModule<typeof Protocol>('src/shared/api/analyticsProtocol.ts');
const { parsePeriod, localToInstant, instantToLocal, snapshotMetrics } = sourceModule<typeof Model>('src/features/analytics/model.ts');

test('analytics guards accept actual pinned pure JSON projections without coercing decimal strings or human nulls', () => {
  expect(isAnalyticsFacts(analytics)).toBe(true); expect(isShiftReport(shift)).toBe(true); expect(isOrderReport(order)).toBe(true); expect(isShiftReport(zero)).toBe(true);
  expect(shift.closed_materials[0].quantity).toBe('1.250');
  expect(shift.metrics.find(metric => metric.name === 'human_score')).toMatchObject({ value: null, status: 'missing' });
  expect(zero.metrics.find(metric => metric.name === 'human_score')).toMatchObject({ value: '0.000000000000', status: 'ok' });
  expect(order.order.attempts[0].review.final_score).toBeNull();
  expect(order.order.attempts[0].assessments[0].score).toBe(99);
});

test('C3 facts, C4 shift and one-order JSON cannot substitute for each other or accept unknown versions', () => {
  expect(isAnalyticsFacts(shift)).toBe(false); expect(isShiftReport(analytics)).toBe(false); expect(isOrderReport(shift)).toBe(false);
  expect(isAnalyticsFacts({ ...analytics, schema_version: 'future-schema' })).toBe(false);
  expect(isShiftReport({ ...shift, fact_schema_version: 'future-schema' })).toBe(false);
  expect(isShiftReport({ ...shift, metrics: null })).toBe(false);
  expect(isShiftReport({ ...shift, provenance: { ...shift.provenance, history_complete: false } })).toBe(false);
  expect(isShiftReport({ ...shift, metrics: shift.metrics.map(metric => ({ ...metric, value: 0 })) })).toBe(false);
});

test('report parser rejects attempts, reviews and assessments belonging to another order or attempt', () => {
  const fact = order.order; const attempt = fact.attempts[0]; const foreign = '20000000-0000-4000-8000-000000000099';
  const withAttempt = (next: unknown) => ({ ...order, order: { ...fact, attempts: [next] } });
  expect(isOrderReport(withAttempt({ ...attempt, submission: { ...attempt.submission, order_id: foreign } }))).toBe(false);
  expect(isOrderReport(withAttempt({ ...attempt, review: { ...attempt.review, submission_id: foreign } }))).toBe(false);
  expect(isOrderReport(withAttempt({ ...attempt, assessments: [{ ...attempt.assessments[0], assignment_revision: 99 }] }))).toBe(false);
  expect(isOrderReport(withAttempt({ ...attempt, assessments: [], assessment_status: 'recorded' }))).toBe(false);
});

test('UTC+5 controls preserve the exact half-open93-day boundary and reject an extra second', () => {
  expect(localToInstant('2026-07-01T00:00:00')).toBe('2026-06-30T19:00:00.000Z');
  expect(instantToLocal('2026-06-30T19:00:00Z')).toBe('2026-07-01T00:00:00');
  expect(parsePeriod('2026-07-01T00:00:00', '2026-10-02T00:00:00')).toEqual({ start: '2026-06-30T19:00:00.000Z', end: '2026-10-01T19:00:00.000Z' });
  expect(() => parsePeriod('2026-07-01T00:00:00', '2026-10-02T00:00:01')).toThrow(/93/);
  expect(() => parsePeriod('2026-10-02T00:00:00', '2026-10-02T00:00:00')).toThrow();
});

test('calendar errors and end beyond authoritative domain time fail before report requests', () => {
  for (const value of ['2026-02-30T01:00', '2026-13-01T01:00', '2026-10-07T24:01', '2026-10-07T12:60', '2026-10-07']) expect(() => localToInstant(value)).toThrow();
  expect(() => parsePeriod('2026-10-07T00:00', '2026-10-08T00:00', '2026-10-07T18:59:59Z')).toThrow(/доменного/);
  expect(parsePeriod('2026-10-07T00:00', '2026-10-08T00:00', '2026-10-07T19:00:00Z').end).toBe('2026-10-07T19:00:00.000Z');
});

test('snapshot stocks are explicitly classified apart from issuance, closing and submission period flows', () => {
  expect([...snapshotMetrics].sort()).toEqual(['awaiting_review', 'overdue_active']);
  expect(analytics.period.end).not.toBe(analytics.provenance.domain_as_of);
  const active = analytics.orders.find(row => row.order.number === 'SYNTHETIC-ACTIVE')!;
  expect(Date.parse(active.order.due_at)).toBeGreaterThan(Date.parse(analytics.period.end));
  expect(active.is_overdue).toBe(true);
  expect(analytics.metrics.find(metric => metric.name === 'submission_attempts')?.value).toBe('0');
  expect(analytics.metrics.find(metric => metric.name === 'closed_orders')?.value).toBe('1');
});
