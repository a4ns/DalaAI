'use strict';
/** Real composed app only. No successful request is fulfilled/intercepted by a fake.
 * A5 owns discovery/launch/config; B4 owns the installed Playwright dependency.
 */
const path = require('node:path');
const { createRequire } = require('node:module');
const { execFile, execFileSync } = require('node:child_process');
const { promisify } = require('node:util');
const { randomUUID, createHash } = require('node:crypto');
const { check, fixtureFromEnv, readOperatorPin, validateEffectiveRunner, syntheticPng, dueLocal, FRONTEND_SHA, TITLE, UUID } = require('./c110_contract.cjs');
const packageRoot = process.env.DALA_C110_PLAYWRIGHT_PACKAGE || path.dirname(require.resolve('@playwright/test/package.json'));
check(packageRoot && path.isAbsolute(packageRoot), 'A5 must supply B4 installed Playwright package directory');
const fromPlaywright = createRequire(path.join(packageRoot, 'package.json'));
check(fromPlaywright('./package.json').name === '@playwright/test' && fromPlaywright('./package.json').version === '1.63.0', 'reviewed Playwright 1.63.0 required');
const { test, expect, devices } = fromPlaywright(packageRoot);
const { PRIVATE_ACTION_TIMEOUT_MS, privateLoginBoundary } = require('./c110_private_boundary.cjs');
const runFile = promisify(execFile);
let fixture;

test.describe('C110 real browser API PostgreSQL acceptance', () => {
  test.describe.configure({ mode: 'serial', retries: 0, timeout: 180_000 });
  test.beforeAll(() => { fixture = fixtureFromEnv(); });
  test(TITLE, async ({ browser, browserName }, testInfo) => {
    check(browserName === 'chromium', 'Chromium required for recorded Android emulation');
    validateEffectiveRunner(testInfo.config, testInfo.project,
      path.join(__dirname, 'c110_playwright.config.cjs'), path.join(__dirname, 'c110_artifacts', 'playwright.json'));
    const repo = path.resolve(__dirname, '../..');
    let harnessSha;
    try {
      harnessSha = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
      execFileSync('git', ['diff', '--exit-code', 'HEAD', '--', 'tests/e2e/c110_*'], { cwd: repo, stdio: 'ignore' });
    } catch { check(false, 'committed, unchanged C110 sources required'); }
    const device = devices['Pixel 7'];
    check(device && device.isMobile && device.hasTouch, 'Pixel 7 emulation descriptor required');
    const report = {
      schema_version: 1, result: 'FAIL', test: TITLE, run_id: fixture.run_id,
      harness_sha: harnessSha, frontend_sha: FRONTEND_SHA, backend_sha: fixture.backend_sha,
      provenance: 'app source SHAs supplied by operator; C110 records actual harness HEAD',
      failure_output_protection: 'source-bound A5 dummy-failure proof verified before credential input',
      started_at: new Date().toISOString(), steps: [], commands: [],
      browser: { engine: 'chromium', version: browser.version(), playwright: '1.63.0',
        mode: 'ANDROID_EMULATION', profile: 'Pixel 7', viewport: device.viewport,
        user_agent: device.userAgent, device_scale_factor: device.deviceScaleFactor,
        mobile: device.isMobile, touch: device.hasTouch, contexts: 2,
        locale: 'ru-RU', timezone: 'Asia/Almaty', service_workers: 'blocked' },
      separate_gates: { physical_android: 'NOT_RUN', native_camera: 'NOT_RUN', push_delivery: 'NOT_RUN',
        provider_model: 'NOT_RUN', throttled_mobile_upload_10s: 'NOT_RUN', report_export: 'NOT_RUN' },
    };
    const contexts = [];
    let unexpectedNetwork = 0;
    const businessRequests = [];
    const observation = async orderId => {
      try {
        const { stdout } = await runFile(process.env.DALA_C110_PYTHON || 'python',
          [path.join(__dirname, 'c110_observe.py'), orderId],
          { env: process.env, timeout: 15_000, maxBuffer: 512 * 1024 });
        const result = JSON.parse(stdout);
        check(result.source === 'actual_postgresql_read_only', 'actual DB projection missing');
        return result;
      } catch { throw new Error('C110 BLOCKED: PostgreSQL observer unavailable; subprocess details suppressed'); }
    };
    const stage = async (name, work) => test.step(name, async () => {
      const row = { name, result: 'FAIL' }; report.steps.push(row);
      await work(); row.result = 'PASS';
    });
    const apiGet = async (context, pathname) => {
      try {
        const response = await context.request.get(`${fixture.origin}/api/v1${pathname}`, { maxRedirects: 0 });
        if (response.status() !== 200) throw new Error('unexpected read status');
        return await response.json();
      } catch { throw new Error('C110 FAIL: authenticated API read unavailable; transport details suppressed'); }
    };
    const newSession = async role => {
      const context = await browser.newContext({ ...device, locale: 'ru-RU', timezoneId: 'Asia/Almaty',
        serviceWorkers: 'block', ignoreHTTPSErrors: false });
      contexts.push(context);
      context.setDefaultTimeout(PRIVATE_ACTION_TIMEOUT_MS);
      context.setDefaultNavigationTimeout(15_000);
      // Network containment only: same-origin requests always use the real server.
      await context.route('**/*', route => {
        const url = new URL(route.request().url());
        if (url.origin !== fixture.origin) { unexpectedNetwork++; return route.abort('blockedbyclient'); }
        return route.continue();
      });
      context.on('request', request => {
        const url = new URL(request.url());
        if (request.method() !== 'POST' || url.origin !== fixture.origin ||
            !(url.pathname === '/api/v1/orders' || /^\/api\/v1\/orders\/[0-9a-f-]+\/commands$/.test(url.pathname))) return;
        if (businessRequests.length >= 32) { unexpectedNetwork++; return; }
        try {
          const body = request.postDataJSON();
          if (!['create', 'queue', 'accept', 'start', 'pause', 'resume', 'submit', 'review'].includes(body.action) || !UUID.test(body.operation_id || '')) throw new Error('invalid business envelope');
          businessRequests.push({ action: body.action, operation_id: body.operation_id, actor_id: fixture[role].id });
        } catch { businessRequests.push({ invalid: true }); }
      });
      const page = await context.newPage();
      await privateLoginBoundary(role, async () => {
        await page.goto(fixture.origin, { waitUntil: 'domcontentloaded' });
        await page.getByLabel('Табельный код', { exact: true }).fill(fixture[role].employee_code);
        await page.getByLabel('PIN', { exact: true }).fill(readOperatorPin(role), { timeout: PRIVATE_ACTION_TIMEOUT_MS });
        const response = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/auth/login' && r.request().method() === 'POST');
        await page.getByRole('button', { name: 'Войти', exact: true }).click();
        if ((await response).status() !== 200) throw new Error('login not confirmed');
        const me = await apiGet(context, '/me');
        if (me.principal.user_id !== fixture[role].id || me.principal.role !== role || !me.principal.active) throw new Error('principal mismatch');
        // Never preserve or expose the CSRF value from /me.
      });
      return { context, page };
    };
    let master, executor, order, db;
    const commits = [];
    const mutate = async (page, action, click, expectedStatus) => {
      const routePath = action === 'create' ? '/api/v1/orders' : `/api/v1/orders/${order.id}/commands`;
      const awaited = page.waitForResponse(response => {
        if (new URL(response.url()).pathname !== routePath || response.request().method() !== 'POST') return false;
        try { return response.request().postDataJSON().action === action; } catch { return false; }
      });
      await click();
      const response = await awaited;
      expect(response.status(), `${action} real response`).toBe(action === 'create' ? 201 : 200);
      const request = response.request().postDataJSON();
      const body = await response.json();
      expect(body.event_ids.length).toBeGreaterThan(0);
      expect(body.order.status).toBe(expectedStatus);
      expect(body.order.version).toBe((order?.version || 0) + 1);
      expect(body.order.assignment.executor_id).toBe(fixture.executor.id);
      expect(request.expected_version).toBe(order?.version || 0);
      order = body.order;
      commits.push({ action, operation_id: request.operation_id,
        actor_id: action === 'create' || action === 'review' ? fixture.master.id : fixture.executor.id,
        version: order.version, status: expectedStatus });
      report.commands = [...commits];
      for (const session of [master, executor]) {
        const persisted = await apiGet(session.context, `/orders/${order.id}`);
        expect(persisted.id).toBe(order.id); expect(persisted.version).toBe(order.version); expect(persisted.status).toBe(expectedStatus);
      }
      db = await observation(order.id);
      expect(db.order.id).toBe(order.id); expect(db.order.version).toBe(order.version); expect(db.order.status).toBe(expectedStatus);
      expect(db.order.created_by).toBe(fixture.master.id); expect(db.order.executor_id).toBe(fixture.executor.id);
      expect(db.receipts).toHaveLength(commits.length);
      for (const command of commits) {
        const receipt = db.receipts.filter(r => r.operation_id === command.operation_id && r.actor_id === command.actor_id);
        expect(receipt).toHaveLength(1); expect(receipt[0].committed).toBe(true);
      }
      report.order_id = order.id;
      return body;
    };
    const executorCommand = async (action, button, status) => mutate(executor.page, action,
      () => executor.page.getByRole('button', { name: button, exact: true }).click(), status);
    const reviewCard = () => master.page.getByRole('article', { name: `Наряд ${order.number}`, exact: true });
    try {
      await stage('separate authenticated browser contexts', async () => {
        master = await newSession('master'); executor = await newSession('executor');
        expect(master.context).not.toBe(executor.context);
        const cookies = await Promise.all([master.context.cookies(), executor.context.cookies()]);
        const sessionCookies = cookies.map(items => items.find(c => c.name === '__Host-naryadai_session'));
        expect(sessionCookies.every(c => c && c.secure && c.httpOnly && c.sameSite === 'Strict')).toBe(true);
        expect(Boolean(sessionCookies[0]?.value && sessionCookies[0].value !== sessionCookies[1]?.value)).toBe(true);
        await expect(master.page.getByRole('heading', { name: 'Выдать и проверить работу', exact: true })).toBeVisible();
        await expect(executor.page.getByRole('heading', { name: 'Мои наряды', level: 1, exact: true })).toBeVisible();
        await expect(executor.page.getByRole('button', { name: 'Выдать наряд', exact: true })).toHaveCount(0);
      });
      await stage('master creates unplanned order through composed UI', async () => {
        const page = master.page;
        await page.getByLabel('Вид работы', { exact: true }).selectOption('unplanned');
        await page.getByLabel('Задача или неисправность *', { exact: true }).fill(`Synthetic C110 ${fixture.run_id} ${randomUUID()}`);
        await page.getByLabel('Участок *', { exact: true }).selectOption(fixture.section_id);
        await page.getByLabel('Оборудование *', { exact: true }).selectOption(fixture.equipment_id);
        await page.getByLabel('Ответственный исполнитель *', { exact: true }).selectOption(fixture.executor.id);
        await page.getByLabel('Срок выполнения (UTC+5) *', { exact: true }).fill(dueLocal());
        await page.getByLabel('Норма времени, минут *', { exact: true }).fill('30');
        await mutate(page, 'create', () => page.getByRole('button', { name: 'Выдать наряд', exact: true }).click(), 'issued');
        await expect(page.getByText('Выдача наряда подтверждена сервером.', { exact: false })).toBeVisible();
        const card = executor.page.getByRole('navigation', { name: 'Назначенные наряды' }).getByRole('button').filter({ hasText: order.description });
        await expect(card).toBeVisible(); await card.click();
      });
      await stage('executor queue accept start pause resume', async () => {
        await executorCommand('queue', 'В очередь', 'queued');
        await executorCommand('accept', 'Принять', 'accepted');
        await executorCommand('start', 'Начать работу', 'in_progress');
        await executor.page.getByRole('button', { name: 'Приостановить', exact: true }).click();
        await executor.page.getByLabel('Причина обязательна', { exact: true }).fill('Synthetic C110 pause for inspection');
        await executorCommand('pause', 'Поставить на паузу', 'paused');
        await executorCommand('resume', 'Продолжить работу', 'in_progress');
        // The reason form is a retained UI mode; leave it explicitly before result entry.
        const back = executor.page.getByRole('button', { name: 'Вернуться без отправки', exact: true });
        if (await back.isVisible()) await back.click();
      });
      await stage('incomplete result cannot close and master returns for rework', async () => {
        await executor.page.getByLabel('Что выполнено', { exact: false }).fill('Synthetic incomplete inspection; evidence intentionally missing');
        await executorCommand('submit', 'Отправить неполный результат на проверку', 'ai_review');
        const first = db.submissions[0];
        expect(first.completeness).toBe('incomplete');
        expect(first.missing_evidence).toEqual(expect.arrayContaining(['WORK_CODE_REQUIRED', 'AFTER_PHOTO_REQUIRED']));
        await expect(reviewCard().getByText('Закрытие недоступно', { exact: true })).toBeVisible();
        await expect(reviewCard().getByRole('button', { name: 'Принять и закрыть', exact: true })).toBeDisabled();
        await reviewCard().getByLabel('Причина решения *', { exact: true }).fill('Synthetic rework: add work code and after photo');
        await mutate(master.page, 'review', () => reviewCard().getByRole('button', { name: 'Вернуть на доработку', exact: true }).click(), 'rework');
        expect(db.reviews[0].decision).toBe('rework'); expect(db.reviews[0].final_score).toBeNull();
      });
      await stage('executor supplies actual upload work code and materials', async () => {
        await executorCommand('start', 'Начать работу', 'in_progress');
        await executor.page.getByLabel('Что выполнено', { exact: false }).fill('Synthetic complete inspection, cleaned and checked test assembly');
        await executor.page.getByLabel('Шифр работ', { exact: true }).selectOption(fixture.work_code_id);
        await executor.page.getByRole('button', { name: 'Добавить материал', exact: true }).click();
        await executor.page.getByLabel('Материал 1', { exact: true }).selectOption(fixture.material_id);
        await executor.page.getByLabel(/^Количество/).fill('1,25');
        const png = syntheticPng();
        report.photo_input = { kind: 'generated synthetic raster; not a camera photo', sha256: createHash('sha256').update(png).digest('hex'), bytes: png.length };
        const staged = executor.page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/photos/stage' && r.request().method() === 'POST');
        await executor.page.getByLabel('Выбрать фотографии', { exact: true }).setInputFiles({ name: 'c110_synthetic.png', mimeType: 'image/png', buffer: png });
        expect((await staged).status()).toBe(201);
        await expect(executor.page.getByText('Подтверждённых фото: 1 из 5.', { exact: true })).toBeVisible();
        await executorCommand('submit', 'Отправить на проверку', 'ai_review');
        expect(db.submissions).toHaveLength(2);
        expect(db.submissions[1].completeness).toBe('complete'); expect(db.submissions[1].missing_evidence).toEqual([]);
        expect(db.submissions[1].work_code_id).toBe(fixture.work_code_id);
        expect(db.photos).toHaveLength(1);
        expect(db.photos[0]).toMatchObject({ owner_id: fixture.executor.id, purpose: 'after', attached: true, file_valid: true, exif_removed: true, submission_id: order.current_submission_id });
        expect(db.materials).toEqual([{ submission_id: order.current_submission_id, material_id: fixture.material_id, quantity: '1.250' }]);
        await expect(reviewCard().getByRole('img', { name: 'Фото результата 1', exact: true })).toBeVisible();
        let photo;
        try { photo = await master.context.request.get(`${fixture.origin}/api/v1/photos/${db.photos[0].id}`, { maxRedirects: 0 }); }
        catch { throw new Error('C110 FAIL: protected photo read unavailable; transport details suppressed'); }
        expect(photo.status()).toBe(200);
        const bytes = await photo.body();
        expect(createHash('sha256').update(bytes).digest('hex')).toBe(db.photos[0].sha256);
        expect(bytes.length).toBe(db.photos[0].bytes);
        const submission = await apiGet(master.context, `/orders/${order.id}/submissions/${order.current_submission_id}`);
        expect(submission.completeness).toBe('complete'); expect(submission.payload.after_photo_ids).toEqual([db.photos[0].id]);
        expect(submission.assessments).toEqual([]);
        await expect(reviewCard().getByText('Оценка ИИ пока отсутствует.', { exact: false })).toBeVisible();
      });
      await stage('human closure persists and full event history is visible', async () => {
        await reviewCard().getByLabel('Причина решения *', { exact: true }).fill('Synthetic evidence reviewed manually; accepted');
        await expect(reviewCard().getByLabel('Итоговая оценка мастера (необязательно)', { exact: true })).toHaveValue('');
        await mutate(master.page, 'review', () => reviewCard().getByRole('button', { name: 'Принять и закрыть', exact: true }).click(), 'closed');
        expect(db.reviews).toHaveLength(2); expect(db.reviews[1].decision).toBe('close'); expect(db.reviews[1].final_score).toBeNull();
        await expect(executor.page.getByText('Наряд закрыт мастером.', { exact: true })).toBeVisible();
        await master.page.getByRole('button', { name: 'Обзор смены', exact: true }).click();
        await master.page.getByRole('button', { name: `Показать историю наряда № ${order.number}`, exact: true }).click();
        const timeline = master.page.getByRole('list', { name: `История наряда № ${order.number}, новые события сначала`, exact: true });
        const expectedKinds = ['order.created', 'order.queued', 'order.accepted', 'order.started', 'order.paused', 'order.resumed', 'order.done', 'order.ai_review_requested', 'order.reviewed', 'order.started', 'order.done', 'order.ai_review_requested', 'order.reviewed'];
        expect(db.events.map(e => e.kind)).toEqual(expectedKinds);
        const history = await apiGet(master.context, `/orders/${order.id}/events?limit=100`);
        expect(history.has_more).toBe(false);
        expect(history.items.map(e => e.id)).toEqual(db.events.map(e => e.id));
        await expect(timeline.getByRole('listitem')).toHaveCount(expectedKinds.length);
        expect(db.assessments).toEqual([]);
        expect(unexpectedNetwork).toBe(0);
        expect(businessRequests).toEqual(commits.map(({ action, operation_id, actor_id }) => ({ action, operation_id, actor_id })));
        report.business_requests = businessRequests;
        report.database = db;
        report.result = 'PASS';
      });
    } finally {
      report.finished_at = new Date().toISOString();
      // Only allowlisted, synthetic projections are attached. Never trace/HAR/cookies.
      await testInfo.attach('c110_evidence', { body: Buffer.from(JSON.stringify(report, null, 2)), contentType: 'application/json' });
      for (const context of contexts) await context.close();
    }
  });
});
