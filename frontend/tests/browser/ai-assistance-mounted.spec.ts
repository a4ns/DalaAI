import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { ids, result, session } from '../support/synthetic';
import rawReport from '../../src/features/aiReports/__fixtures__/serializer-response.json' with { type: 'json' };
import rawAdvice from '../../src/features/assigneeRecommendations/__fixtures__/contract-response.json' with { type: 'json' };
import rawFacts from '../fixtures/analytics/analytics-shift.json' with { type: 'json' };
import type { Dictionaries, Order, Submission } from '../../src/shared/api/wire';

/** Mounted real App with intercepted synthetic HTTP only. Never actual API/DB/model evidence. */
async function mount(page: Page, options: { adviceDenied?: boolean; malformedReportOnce?: boolean; reviewing?: boolean } = {}) {
  const counts = { recommendations: 0, summaries: [] as string[], orderMutations: 0 };
  let order: Order = { ...result().order, type: 'planned', status: options.reviewing ? 'ai_review' : 'accepted', current_submission_id: options.reviewing ? ids.event : null, domain_now: rawFacts.provenance.domain_as_of };
  const dictionaries: Dictionaries = {
    sections: [{ id: ids.section, code: 'S', label: 'Синтетический участок' }],
    equipment: [{ id: ids.equipment, code: 'EQ', label: 'Синтетический насос', section_id: ids.section }, { id: ids.event, code: 'EQ2', label: 'Синтетический насос 2', section_id: ids.section }],
    executors: [{ id: ids.second, employee_code: 'SYNTHETIC-EXECUTOR', section_ids: [ids.section], brigade_id: null, on_shift: true, active_order_id: null, queue_count: 0 }], brigades: [],
    work_codes: [{ id: ids.first, code: 'SYNTHETIC', label: 'Синтетический шифр' }], materials: [],
  };
  const submission: Submission = { id: ids.event, order_id: ids.order, assignment_revision: 1, attempt_number: 1, submitted_by: ids.second, submitted_at: '2026-10-08T01:00:00Z', done_late: false, completeness: 'complete', missing_evidence: [], payload: { work_description: 'Синтетическая выполненная работа', work_code_id: ids.first, materials: [], after_photo_ids: [], comment: '' }, assessments: [], reviews: [] };
  await page.route('**/api/v1/**', async route => {
    const request = route.request(); const url = new URL(request.url());
    if (url.pathname === '/api/v1/me') return route.fulfill({ json: session() });
    if (url.pathname === '/api/v1/dicts') return route.fulfill({ json: dictionaries });
    if (url.pathname === '/api/v1/orders' && request.method() === 'GET') return route.fulfill({ json: { items: [order], next_cursor: null } });
    if (url.pathname.includes('/submissions/')) return route.fulfill({ json: submission });
    if (url.pathname.endsWith('/commands')) {
      counts.orderMutations++; const body = request.postDataJSON();
      order = { ...order, status: body.payload.decision === 'close' ? 'closed' : 'rework', version: order.version + 1 };
      return route.fulfill({ json: { order, event_ids: [ids.event], submission_id: ids.event } });
    }
    if (url.pathname === '/api/v1/recommendations/assignees') {
      counts.recommendations++;
      if (options.adviceDenied) return route.fulfill({ status: 403, json: {} });
      const now = Date.now(); const advice = structuredClone(rawAdvice);
      advice.section_id = ids.section; advice.as_of = new Date(now).toISOString(); advice.expires_at = new Date(now + 30000).toISOString(); advice.candidates[0].executor_id = ids.second; advice.candidates[0].employee_code = 'SYNTHETIC-EXECUTOR';
      return route.fulfill({ json: advice });
    }
    if (url.pathname === '/api/v1/analytics/shift') return route.fulfill({ json: { ...rawFacts, period: { start: url.searchParams.get('start'), end: url.searchParams.get('end'), display_timezone: 'Asia/Almaty' } } });
    if (url.pathname === '/api/v1/reports/ai-summary') {
      counts.summaries.push(request.postData()!); const body = request.postDataJSON();
      if (options.malformedReportOnce && counts.summaries.length === 1) return route.fulfill({ json: { synthetic: 'unsupported-success' } });
      return route.fulfill({ json: { ...rawReport, provenance: { ...rawReport.provenance, domain_as_of: rawFacts.provenance.domain_as_of, captured_at_real: new Date().toISOString() }, operation_id: body.operation_id, report_kind: body.report_kind, period: { start: body.start, end: body.end, display_timezone: 'Asia/Almaty' } } });
    }
    if (request.method() === 'POST') counts.orderMutations++;
    return route.fulfill({ status: 404, json: {} });
  });
  await page.goto('/'); await expect(page.getByRole('heading', { name: 'Выдать и проверить работу' })).toBeVisible();
  return counts;
}

test('synthetic mounted advice stays explicit and choosing changes only the current draft', async ({ page }) => {
  const counts = await mount(page); expect(counts.recommendations).toBe(0); expect(counts.summaries).toHaveLength(0);
  await page.getByRole('combobox', { name: /^Участок/ }).selectOption(ids.section);
  await page.getByRole('button', { name: 'Предложить исполнителей', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Выбрать SYNTHETIC-EXECUTOR в черновике', exact: true })).toBeVisible();
  const select = page.getByRole('combobox', { name: /^Ответственный исполнитель/ }); await expect(select).toHaveValue('');
  await page.getByRole('button', { name: 'Выбрать SYNTHETIC-EXECUTOR в черновике', exact: true }).click(); await expect(select).toHaveValue(ids.second);
  expect(counts.orderMutations).toBe(0); expect(counts.recommendations).toBe(1);
  await page.getByRole('combobox', { name: /^Оборудование/ }).selectOption(ids.equipment);
  await expect(page.getByRole('button', { name: 'Выбрать SYNTHETIC-EXECUTOR в черновике', exact: true })).toHaveCount(0);
});
test('synthetic mounted advice403 clears dictionary access and cannot request again before explicit refresh', async ({ page }) => {
  const counts = await mount(page, { adviceDenied: true });
  await page.getByRole('combobox', { name: /^Участок/ }).selectOption(ids.section); await page.getByRole('button', { name: 'Предложить исполнителей', exact: true }).click();
  await expect(page.getByText('Доступ к рекомендациям не подтверждён.', { exact: false })).toBeVisible();
  const button = page.getByRole('button', { name: 'Предложить исполнителей', exact: true }); await expect(button).toBeDisabled();
  await button.evaluate(node => (node as HTMLButtonElement).click()); expect(counts.recommendations).toBe(1);
});
test('synthetic mounted report is not automatic and unknown retry preserves exact POST body', async ({ page }) => {
  const counts = await mount(page, { malformedReportOnce: true });
  await page.getByRole('button', { name: 'Аналитика и отчёты', exact: true }).click();
  await page.getByLabel('Начало периода', { exact: true }).fill('2026-10-08T00:00'); await page.getByLabel('Конец периода (не включён)', { exact: true }).fill('2026-10-08T05:00');
  await expect(page.getByLabel('Начало периода', { exact: true })).toHaveValue('2026-10-08T00:00'); await expect(page.getByLabel('Конец периода (не включён)', { exact: true })).toHaveValue('2026-10-08T05:00');
  await page.getByRole('button', { name: 'Показать факты', exact: true }).click();
  const generate = page.getByRole('button', { name: 'Сводка смены', exact: true }); await expect(generate).toBeEnabled(); expect(counts.summaries).toHaveLength(0);
  await generate.click(); await expect(page.getByRole('button', { name: 'Проверить тем же запросом', exact: true })).toBeVisible(); await expect(generate).toBeDisabled();
  await page.getByRole('button', { name: 'Проверить тем же запросом', exact: true }).click();
  await expect(page.getByText('Фактическая сводка по правилам, без ответа модели', { exact: true })).toBeVisible();
  expect(counts.summaries).toHaveLength(2); expect(counts.summaries[1]).toBe(counts.summaries[0]);
});
for (const decision of ['close', 'rework'] as const) test(`synthetic mounted confirmed ${decision} survives refresh removing the review card`, async ({ page }) => {
  const counts = await mount(page, { reviewing: true });
  await page.getByRole('textbox', { name: /^Причина решения/ }).fill('Синтетическая проверка мастера');
  await page.getByRole('button', { name: decision === 'close' ? 'Принять и закрыть' : 'Вернуть на доработку', exact: true }).click();
  await expect(page.getByText('Решение мастера по наряду № SYNTHETIC-001 подтверждено сервером.', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Принять и закрыть', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Вернуть на доработку', exact: true })).toHaveCount(0); expect(counts.orderMutations).toBe(1);
});
