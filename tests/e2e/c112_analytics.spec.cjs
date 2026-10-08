'use strict';
// Only real, same-origin API traffic; no backend replacement or DOM simulation.
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');
const c = require('./c112_contract.cjs');
const proof = require('./c112_preflight_proof.cjs');
const { createDiagnostics, checkpoint, observeAnalyticsStatus, failDiagnostic } = require('./c112_diagnostics.cjs');
const { PRIVATE_ACTION_TIMEOUT_MS, privateLoginBoundary } = require('./c112_private_boundary.cjs');
const root = process.env.DALA_C112_PLAYWRIGHT_PACKAGE || path.dirname(require.resolve('@playwright/test/package.json'));
const pw = createRequire(path.join(root, 'package.json'));
c.check(pw('./package.json').name === '@playwright/test' && pw('./package.json').version === '1.63.0', 'PINNED_PLAYWRIGHT_REQUIRED');
const { test, expect, devices } = pw(root);
const runFile = promisify(execFile);
let fixture;
test.beforeAll(() => {
  fixture = c.fixtureFromEnv();
  // Playwright reloads config in workers; claim only once in the actual suite.
  fs.mkdirSync(c.artifactDir(), { recursive: true });
  try { fs.writeFileSync(path.join(c.artifactDir(), 'run-claim.json'), JSON.stringify({ run_id: fixture.run_id, harness_sha: proof.sourceSha() }), { flag: 'wx', mode: 0o600 }); }
  catch { throw new Error('C112 BLOCKED: fresh artifact run ID required'); }
});
test(c.TITLE, async ({ browser, browserName }, info) => {
  c.validateEffectiveRunner(info.config, info.project, path.join(__dirname, 'c112_playwright.config.cjs'), path.join(c.artifactDir(), 'playwright.json'));
  c.check(browserName === 'chromium' && info.project.name === c.PROJECT, 'ANDROID_PROJECT_REQUIRED');
  const sourceSha = proof.sourceSha(), hashes = proof.fingerprint();
  const device = devices['Pixel 7'];
  c.check(device.isMobile && device.hasTouch, 'MOBILE_PROFILE_REQUIRED');
  const evidence = { schema_version: 1, result: 'FAIL', test: c.TITLE, run_id: fixture.run_id,
    harness_sha: sourceSha, frontend_sha: fixture.frontend_sha, backend_sha: fixture.backend_sha,
    source_files: hashes, manifest: fixture.manifest, manifest_sha256: fixture.manifest_sha256,
    secrecy_proof: fixture.proof, diagnostics: createDiagnostics(), started_at: new Date().toISOString(), steps: [], observations: [], restrictions: [],
    period: c.PERIOD, ui_period_utc_plus_5: c.LOCAL_PERIOD,
    provenance: 'operator-pinned app SHAs; committed harness; real API and independent read-only PostgreSQL',
    browser: { mode: 'ANDROID_EMULATION', engine: 'chromium', version: browser.version(), profile: 'Pixel 7',
      playwright: '1.63.0', contexts: 2, mobile: true, touch: true, locale: 'ru-RU', timezone: 'Asia/Almaty',
      credential_environment: 'excluded_from_browser_process', trusted_tls: true, service_workers: 'blocked' },
    separate_gates: { c110_lifecycle: 'NOT_RUN', physical_android: 'NOT_RUN', native_camera: 'NOT_RUN',
      push_delivery: 'NOT_RUN', provider_model: 'NOT_RUN', report_export: 'NOT_RUN', live_closure: 'NOT_RUN' } };
  const contexts = [], network = { blocked_external: 0, blocked_mutation: 0, login_posts: 0, business_mutations: 0 };
  let before, after, master, executor, facts, selected;
  const stage = async (name, work) => test.step(name, async () => { const row = { name, result: 'FAIL' }; evidence.steps.push(row); checkpoint(evidence.diagnostics, 'OTHER_JOURNEY_STEP'); await work(); row.result = 'PASS'; });
  const observe = async () => {
    try {
      const { stdout } = await runFile(process.env.DALA_C112_PYTHON || 'python', [path.join(__dirname, 'c112_observe.py'), fixture.master.id, fixture.executor.id], { env: process.env, timeout: 30_000, maxBuffer: 1024 * 1024 });
      const data = JSON.parse(stdout);
      require('./c112_gate.cjs').validateDatabase(data, fixture.manifest);
      return data;
    } catch { throw new Error('C112 BLOCKED: read-only observer unavailable; details suppressed'); }
  };
  const query = new URLSearchParams(c.PERIOD).toString();
  const responseBody = async (response, expectedPath, expectedStatus = 200) => {
    try {
      checkpoint(evidence.diagnostics, 'CHECK_RESPONSE_IDENTITY_STATUS');
      const url = new URL(response.url());
      if (expectedPath === '/api/v1/analytics/shift') observeAnalyticsStatus(evidence.diagnostics, response.status());
      c.check(url.origin === fixture.origin && url.pathname === expectedPath && response.status() === expectedStatus, 'REAL_RESPONSE_REQUIRED');
      checkpoint(evidence.diagnostics, 'CHECK_PROTECTED_HEADERS');
      const headers = response.headers();
      checkpoint(evidence.diagnostics, 'CHECK_CACHE_PRIVATE');
      c.check(/(?:^|,)\s*private(?:,|$)/i.test(headers['cache-control'] || ''), 'PROTECTED_RESPONSE_HEADERS_REQUIRED');
      checkpoint(evidence.diagnostics, 'CHECK_CACHE_NO_STORE');
      c.check(/no-store/i.test(headers['cache-control'] || ''), 'PROTECTED_RESPONSE_HEADERS_REQUIRED');
      checkpoint(evidence.diagnostics, 'CHECK_VARY_COOKIE');
      c.check(/cookie/i.test(headers.vary || ''), 'PROTECTED_RESPONSE_HEADERS_REQUIRED');
      checkpoint(evidence.diagnostics, 'CHECK_NOSNIFF');
      c.check(headers['x-content-type-options'] === 'nosniff', 'PROTECTED_RESPONSE_HEADERS_REQUIRED');
      checkpoint(evidence.diagnostics, 'CHECK_SERVICE_WORKER_ABSENCE');
      if (response.fromServiceWorker) c.check(response.fromServiceWorker() === false, 'SERVICE_WORKER_RESPONSE_FORBIDDEN');
      checkpoint(evidence.diagnostics, 'PARSE_RESPONSE_JSON');
      const body = await response.json();
      return { body, status: response.status(), path: expectedPath, body_sha256: c.digest(body), cache: 'private,no-store', vary: 'Cookie', nosniff: true };
    } catch { throw new Error('C112 FAIL: protected response unavailable; details suppressed'); }
  };
  const liveRead = async (context, pathname) => {
    try { return await context.request.get(`${fixture.origin}${pathname}`, { maxRedirects: 0 }); }
    catch { throw new Error('C112 FAIL: authenticated read unavailable; details suppressed'); }
  };
  const newSession = async role => {
    const context = await browser.newContext({ ...device, locale: 'ru-RU', timezoneId: 'Asia/Almaty', serviceWorkers: 'block', ignoreHTTPSErrors: false });
    contexts.push(context); context.setDefaultTimeout(PRIVATE_ACTION_TIMEOUT_MS); context.setDefaultNavigationTimeout(15_000);
    await context.route('**/*', route => {
      const request = route.request(), url = new URL(request.url());
      if (url.origin !== fixture.origin) { network.blocked_external++; return route.abort('blockedbyclient'); }
      if (!['GET','HEAD'].includes(request.method())) {
        if (request.method() === 'POST' && url.pathname === '/api/v1/auth/login') network.login_posts++;
        else { network.blocked_mutation++; network.business_mutations++; return route.abort('blockedbyclient'); }
      }
      return route.continue();
    });
    await context.routeWebSocket('**/*', socket => { network.blocked_external++; socket.close(); });
    const page = await context.newPage();
    // A fixed category reveals a received analytics response even if period
    // matching or later rendering fails; no URL/header/body is retained.
    if (role === 'master') page.on('response', response => {
      try { const url = new URL(response.url());
        if (url.origin === fixture.origin && url.pathname === '/api/v1/analytics/shift') observeAnalyticsStatus(evidence.diagnostics, response.status());
      } catch { /* Do not retain transport exceptions. */ }
    });
    await privateLoginBoundary(role, async () => {
      await page.goto(fixture.origin, { waitUntil: 'domcontentloaded' });
      await page.getByLabel('Табельный код', { exact: true }).fill(fixture[role].employee_code);
      await page.getByLabel('PIN', { exact: true }).fill(c.readOperatorPin(role), { timeout: PRIVATE_ACTION_TIMEOUT_MS });
      const [response] = await Promise.all([page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/auth/login' && r.request().method() === 'POST'), page.getByRole('button', { name: 'Войти', exact: true }).click()]);
      if (response.status() !== 200) throw new Error('login failed');
      const meResponse = await liveRead(context, '/api/v1/me');
      if (meResponse.status() !== 200) throw new Error('principal failed');
      const me = (await meResponse.json()).principal;
      if (me.user_id !== fixture[role].id || me.role !== role || !me.active || c.stable([...me.section_ids].sort()) !== c.stable([...fixture[role].section_ids].sort())) throw new Error('principal mismatch');
      // Do not retain /me's CSRF field, login body, cookie value or request body.
    });
    return { context, page };
  };
  const uiRead = async (page, pathname, click) => {
    checkpoint(evidence.diagnostics, 'WAIT_MATCHING_UI_RESPONSE');
    const [response] = await Promise.all([page.waitForResponse(r => {
      const url = new URL(r.url());
      return url.origin === fixture.origin && url.pathname === pathname && r.request().method() === 'GET' &&
        Date.parse(url.searchParams.get('start')) === Date.parse(c.PERIOD.start) && Date.parse(url.searchParams.get('end')) === Date.parse(c.PERIOD.end);
    }), click()]);
    const result = await responseBody(response, pathname);
    checkpoint(evidence.diagnostics, 'CHECK_RESPONSE_PERIOD');
    require('./c112_gate.cjs').validatePeriod(result.body.period);
    return result;
  };
  const provenanceUi = async (scope, p) => {
    const h = p.historical_evidence;
    checkpoint(evidence.diagnostics, 'WAIT_SYNTHETIC_WATERMARK');
    await expect(scope.getByText('СИНТЕТИЧЕСКИЕ ДАННЫЕ — не история предприятия', { exact: true })).toBeVisible();
    const notice = scope.getByRole('complementary', { name: 'Исторические фото недоступны', exact: true });
    checkpoint(evidence.diagnostics, 'WAIT_UNAVAILABLE_PHOTO_NOTICE');
    await expect(notice).toBeVisible();
    checkpoint(evidence.diagnostics, 'CHECK_UNAVAILABLE_PHOTO_COUNTS');
    await expect(notice).toContainText(`Исторических нарядов: ${h.historical_order_count}; попыток: ${h.historical_submission_count}; ссылок на фото после работ: ${h.historical_after_photo_reference_count}; отсутствующих записей фото: ${h.missing_after_photo_row_count}.`);
    checkpoint(evidence.diagnostics, 'CHECK_PHYSICAL_EVIDENCE_DISCLOSURE');
    await expect(notice).toContainText('Физические доказательства не проверены.');
    checkpoint(evidence.diagnostics, 'EXPAND_PROVENANCE_DISCLOSURE');
    await scope.getByText('Источник и границы снимка', { exact: true }).click();
    checkpoint(evidence.diagnostics, 'CHECK_PROVENANCE_HASHES');
    await expect(scope).toContainText(h.history_sha256);
    await expect(scope).toContainText(h.source_commit);
    await expect(scope).toContainText(h.identity_mapping_sha256);
  };
  const record = (kind, result, counts, extra = {}) => {
    const { body, ...transport } = result;
    evidence.observations.push({ kind, ...transport, provenance: body.provenance, period: body.period,
      counts, ui_provenance_visible: true, ...extra });
  };
  try {
    await stage(c.REQUIRED_STEPS[0], async () => { before = await observe(); evidence.database_before = before; });
    await stage(c.REQUIRED_STEPS[1], async () => {
      master = await newSession('master'); executor = await newSession('executor');
      const cookies = await Promise.all(contexts.map(ctx => ctx.cookies()));
      const sessions = cookies.map(list => list.find(item => item.name === '__Host-naryadai_session'));
      c.check(sessions.every(s => s && s.httpOnly && s.secure && s.sameSite === 'Strict') && sessions[0].value !== sessions[1].value, 'SEPARATE_SECURE_SESSIONS_REQUIRED');
      evidence.distinct_secure_sessions = true;
      await expect(executor.page.getByRole('heading', { name: 'Мои наряды', level: 1, exact: true })).toBeVisible();
    });
    await stage(c.REQUIRED_STEPS[2], async () => {
      checkpoint(evidence.diagnostics, 'NAVIGATE_ANALYTICS');
      await master.page.getByRole('navigation', { name: 'Основная навигация' }).getByRole('button', { name: 'Аналитика и отчёты', exact: true }).click();
      const scope = master.page.getByRole('region', { name: 'Аналитика и отчёты', exact: true });
      const periodStart = scope.getByLabel('Начало периода', { exact: true });
      const periodEnd = scope.getByLabel('Конец периода (не включён)', { exact: true });
      checkpoint(evidence.diagnostics, 'FILL_PERIOD_START');
      await periodStart.fill(c.LOCAL_PERIOD.start);
      checkpoint(evidence.diagnostics, 'FILL_PERIOD_END');
      await periodEnd.fill(c.LOCAL_PERIOD.end);
      await expect(periodStart).toHaveValue(c.LOCAL_PERIOD.start);
      await expect(periodEnd).toHaveValue(c.LOCAL_PERIOD.end);
      const result = await uiRead(master.page, '/api/v1/analytics/shift', () => scope.getByRole('button', { name: 'Показать факты', exact: true }).click());
      facts = result.body;
      checkpoint(evidence.diagnostics, 'CHECK_HISTORICAL_PROVENANCE');
      c.historicalCounts(facts.provenance);
      checkpoint(evidence.diagnostics, 'CHECK_FACTS_SCHEMA');
      c.check(facts.schema_version === 'c3-runtime-facts/1' && facts.totals_available === true, 'COMPLETE_FACTS_REQUIRED');
      checkpoint(evidence.diagnostics, 'CHECK_ORDER_COUNT');
      c.check(Array.isArray(facts.orders) && facts.orders.length === 540, 'EXACT_ORDER_COUNT_REQUIRED');
      checkpoint(evidence.diagnostics, 'CHECK_API_DATABASE_IDENTITIES');
      const ids = facts.orders.map(f => f.order.id), subs = facts.orders.flatMap(f => f.attempts.map(a => a.submission.id));
      c.check(c.stable(ids.sort()) === c.stable(before.order_ids) && c.stable(subs.sort()) === c.stable(before.submission_ids), 'API_DB_IDENTITIES_MISMATCH');
      checkpoint(evidence.diagnostics, 'CHECK_PHOTO_REFERENCES');
      c.check(facts.orders.reduce((n, f) => n + f.attempts.reduce((sum,a) => sum + a.submission.payload.after_photo_ids.length,0),0) === 444, 'ACTUAL_PHOTO_REFERENCE_COUNT_REQUIRED');
      checkpoint(evidence.diagnostics, 'SELECT_OBSERVED_HISTORICAL_ORDER');
      selected = facts.orders.find(f => f.attempts.some(a => a.submission.payload.after_photo_ids.length > 0));
      c.check(selected && c.UUID.test(selected.order.id), 'OBSERVED_HISTORICAL_ORDER_REQUIRED');
      await provenanceUi(scope.getByRole('region', { name: 'Происхождение отчёта', exact: true }), facts.provenance);
      checkpoint(evidence.diagnostics, 'WAIT_PERIOD_METRICS_HEADING');
      await expect(scope.getByRole('heading', { name: 'События за выбранный период', exact: true })).toBeVisible();
      checkpoint(evidence.diagnostics, 'WAIT_EXECUTOR_METRICS_HEADING');
      await expect(scope.getByRole('heading', { name: 'Показатели исполнителей', exact: true })).toBeVisible();
      checkpoint(evidence.diagnostics, 'CHECK_ISSUED_API_METRIC');
      const issued = facts.metrics.find(m => m.name === 'issued_orders');
      c.check(issued?.value === '540', 'ISSUED_METRIC_REQUIRED');
      checkpoint(evidence.diagnostics, 'CHECK_ISSUED_UI_METRIC');
      const issuedCard = scope.getByRole('article').filter({ has: master.page.getByRole('heading', { name: 'Выдано нарядов', exact: true }) });
      await expect(issuedCard.locator('.analytics-value')).toHaveText('540');
      checkpoint(evidence.diagnostics, 'RECORD_ANALYTICS_OBSERVATION');
      record('analytics', result, { orders: 540, submissions: 568, photo_references: 444 }, { order_ids_sha256: c.digest(before.order_ids), submission_ids_sha256: c.digest(before.submission_ids), totals_available: true, issued_orders: '540' });
    });
    await stage(c.REQUIRED_STEPS[3], async () => {
      const result = await uiRead(master.page, '/api/v1/reports/shift', () => master.page.getByRole('button', { name: 'Открыть отчёт смены / периода', exact: true }).click());
      c.historicalCounts(result.body.provenance);
      c.check(result.body.report_kind === 'shift' && result.body.totals_available === true && c.stable(result.body.metrics) === c.stable(facts.metrics) && c.stable(result.body.ratings) === c.stable(facts.ratings) && c.stable(result.body.closed_materials) === c.stable(facts.closed_materials), 'SHIFT_REPORT_FACTS_MISMATCH');
      const scope = master.page.getByRole('region', { name: 'Выбранный отчёт', exact: true });
      await expect(scope.getByRole('heading', { name: 'Защищённый отчёт смены / периода', exact: true })).toBeVisible();
      await provenanceUi(scope.getByRole('region', { name: 'Происхождение отчёта', exact: true }), result.body.provenance);
      record('shift_report', result, { orders: 540, submissions: 568, photo_references: 444 }, { totals_available: true, agrees_with_analytics: true });
    });
    await stage(c.REQUIRED_STEPS[4], async () => {
      // A wrapping label's raw text includes its options; use the select's accessible name.
      const orderSelect = master.page.getByRole('region', { name: 'Аналитика и отчёты', exact: true })
        .getByRole('combobox', { name: 'Наряд для отчёта', exact: true });
      await expect(orderSelect).toHaveCount(1);
      const selectedValues = await orderSelect.selectOption({ value: selected.order.id });
      expect(selectedValues).toEqual([selected.order.id]);
      await expect(orderSelect).toHaveValue(selected.order.id);
      const pathname = `/api/v1/reports/orders/${selected.order.id}`;
      const result = await uiRead(master.page, pathname, () => master.page.getByRole('button', { name: 'Открыть отчёт наряда', exact: true }).click());
      const photoCount = selected.attempts.reduce((n,a) => n + a.submission.payload.after_photo_ids.length, 0);
      c.historicalCounts(result.body.provenance, 1, selected.attempts.length, photoCount);
      c.check(result.body.report_kind === 'order' && c.stable(result.body.order) === c.stable(selected), 'SELECTED_ORDER_REPORT_MISMATCH');
      const scope = master.page.getByRole('region', { name: 'Выбранный отчёт', exact: true });
      await expect(scope.getByRole('heading', { name: `Защищённый отчёт: наряд №${selected.order.number}`, exact: true })).toBeVisible();
      await provenanceUi(scope.getByRole('region', { name: 'Происхождение отчёта', exact: true }), result.body.provenance);
      await expect(scope.getByText('Это не проверка физических доказательств.', { exact: false }).first()).toBeVisible();
      record('order_report', result, { orders: 1, submissions: selected.attempts.length, photo_references: photoCount }, { order_id: selected.order.id, agrees_with_analytics: true });
    });
    await stage(c.REQUIRED_STEPS[5], async () => {
      await expect(executor.page.getByRole('button', { name: 'Аналитика и отчёты', exact: true })).toHaveCount(0);
      await expect(executor.page.getByRole('region', { name: 'Аналитика и отчёты', exact: true })).toHaveCount(0);
      for (const pathname of ['/api/v1/analytics/shift','/api/v1/reports/shift',`/api/v1/reports/orders/${selected.order.id}`]) {
        const result = await responseBody(await liveRead(executor.context, `${pathname}?${query}`), pathname, 403);
        c.check(result.body.code === 'FORBIDDEN' && !('provenance' in result.body) && !('orders' in result.body) && !('order' in result.body), 'EXECUTOR_RESTRICTION_REQUIRED');
        evidence.restrictions.push({ path: pathname, status: 403, code: 'FORBIDDEN', no_report_data: true, cache: result.cache });
      }
      evidence.executor_ui_absent = true;
    });
    await stage(c.REQUIRED_STEPS[6], async () => {
      after = await observe(); evidence.database_after = after;
      c.check(before.business_sha256 === after.business_sha256 && c.stable(before.counts) === c.stable(after.counts), 'BUSINESS_DATABASE_CHANGED');
      c.check(network.blocked_external === 0 && network.blocked_mutation === 0 && network.business_mutations === 0 && network.login_posts === 2, 'UNEXPECTED_NETWORK_ACTIVITY');
      c.check(proof.sourceSha() === sourceSha && c.stable(proof.fingerprint()) === c.stable(hashes), 'SOURCE_CHANGED_DURING_JOURNEY');
    });
    evidence.result = 'PASS';
  } catch { evidence.result = 'FAIL'; failDiagnostic(evidence.diagnostics); }
  finally {
    for (const context of contexts) await context.close().catch(() => { evidence.result = 'FAIL'; });
    evidence.network = network; evidence.finished_at = new Date().toISOString();
    const bytes = Buffer.from(JSON.stringify(evidence, null, 2) + '\n');
    fs.mkdirSync(c.artifactDir(), { recursive: true });
    fs.writeFileSync(path.join(c.artifactDir(), 'evidence.json'), bytes, { flag: 'wx', mode: 0o600 });
    await info.attach('c112_evidence', { body: bytes, contentType: 'application/json' });
  }
  c.check(evidence.result === 'PASS', 'ANALYTICS_JOURNEY_FAILED_SEE_SAFE_STAGE_RESULTS');
});
