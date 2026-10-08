'use strict';
// Separate experiment. A failed original CDP observation is never replaced.
const fs = require('node:fs'), path = require('node:path'), { createRequire } = require('node:module');
const { randomBytes, createHash } = require('node:crypto'), { execFile } = require('node:child_process'), { promisify } = require('node:util');
const k = require('./contract.cjs'), proof = require('./proof.cjs'), o = require('./observations.cjs'), { installReaderTap } = require('./browser_tap.cjs');
const c = require('../c113_contract.cjs'), files = require('../c113_downloads.cjs'), clock = require('../c113_clock.cjs'), gate = require('../c113_gate.cjs');
const { privateLoginBoundary, privateOperationBoundary, PRIVATE_ACTION_TIMEOUT_MS } = require('../c113_private_boundary.cjs');
const root = process.env.DALA_BCP_PLAYWRIGHT_PACKAGE || path.dirname(require.resolve('@playwright/test/package.json'));
const { test, expect, devices } = createRequire(path.join(root, 'package.json'))(root), runFile = promisify(execFile);
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
test(k.TITLE, async ({ browser }, info) => {
  k.validateRunner(info.config, info.project, path.join(__dirname, 'runner.config.cjs'), path.join(k.privateOutput(), 'report.json'));
  k.check(info.project.name === k.PROJECT, 'EXACT_PROJECT');
  k.claimExecution();
  const fixture = k.fixture(), sha = proof.sourceSha(), hashes = proof.fingerprint(), run = k.runId(), nonce = randomBytes(32).toString('hex');
  const e = { schema_version: 1, scope: 'INSTRUMENTED_DIAGNOSTIC_ONLY', c113_acceptance: 'NOT_ESTABLISHED', status: 'BLOCKED',
    source_sha: sha, product_sha: k.PRODUCT_SHA, frontend_sha: k.FRONTEND_SHA, source_files: hashes, run_id: run,
    baseline_failed_run: '37726366034', baseline_failed_job: '113145335028', phase: 'INITIALIZE',
    cdp: { status: 'NOT_RUN', failure: 'NOT_OBSERVED', bytes: null, sha256: null }, client: null, binding: null,
    request_before: null, request_after: null, ui_at_save: 'NOT_OBSERVED', ui_before: 'NOT_OBSERVED', ui_after: 'NOT_OBSERVED',
    saved: { status: 'NOT_RUN', bytes: null, sha256: null, cdp_exact_equality: 'UNAVAILABLE', client_hash_equality: false, content_inspection: 'NOT_RUN', no_export_on_save: false },
    authority: 'NOT_ESTABLISHED', database_unchanged: false, interpretation: 'NOT_ESTABLISHED', cleanup: 'PENDING',
    timing_effect: 'EXTRA_PROMISE_OBSERVERS_AND_BYTE_COPIES', raw_artifacts: 'PRIVATE_DELETE_AFTER_RUN' };
  const contexts = [], network = { login_posts: 0, clock_posts: 0, blocked: 0 }; let master, executor, binding, requestObserver, expectedCommand = null;
  let before, selected, originalBytes, savedPath, expectedPath, disposed = false, clockScope;
  const phase = name => { e.phase = name; };
  const headers = (response, pathname, status = 200, isClock = false, responseKind = 'page') =>
    o.protectedResponseHeaders(response, fixture.origin, pathname, status, isClock, responseKind);
  const observe = async () => {
    const { stdout } = await runFile(process.env.DALA_BCP_PYTHON || 'python', [path.join(__dirname, '../c113_observe.py'), fixture.master.id, fixture.executor.id],
      { env: k.observerEnv(), timeout: 30000, maxBuffer: 1024 * 1024 });
    const db = JSON.parse(stdout); gate.validateDatabase(db, fixture.manifest); return db;
  };
  const newSession = async role => {
    const context = await browser.newContext({ ...devices['Pixel 7'], locale: 'ru-RU', timezoneId: 'Asia/Almaty', serviceWorkers: 'block', ignoreHTTPSErrors: false, acceptDownloads: true });
    contexts.push(context); context.setDefaultTimeout(15000); context.setDefaultNavigationTimeout(15000);
    const page = await context.newPage();
    if (role === 'master') { binding = o.originalBinding(page, nonce); await page.addInitScript(installReaderTap, { nonce, sourceSha: sha, runId: run }); }
    await context.route('**/*', route => {
      const request = route.request(), url = new URL(request.url());
      if (url.origin !== fixture.origin) { network.blocked++; return route.abort('blockedbyclient'); }
      if (role === 'master' && !binding.allow(request)) { network.blocked++; return route.abort('blockedbyclient'); }
      if (!['GET','HEAD'].includes(request.method())) {
        if (request.method() === 'POST' && url.pathname === '/api/v1/auth/login' && network.login_posts < 2) network.login_posts++;
        else if (role === 'master' && request.method() === 'POST' && url.pathname === '/api/v1/demo/clock' && expectedCommand && network.clock_posts < 3) {
          try { k.check(!url.search && c.stable(request.postDataJSON()) === c.stable(expectedCommand), 'EXACT_CLOCK_COMMAND'); }
          catch { network.blocked++; return route.abort('blockedbyclient'); }
          network.clock_posts++; expectedCommand = null;
        } else { network.blocked++; return route.abort('blockedbyclient'); }
      }
      return route.continue();
    });
    await context.routeWebSocket('**/*', socket => { network.blocked++; socket.close(); });
    await privateLoginBoundary(role, async () => {
      await page.goto(fixture.origin, { waitUntil: 'domcontentloaded' });
      await page.getByLabel('Табельный код', { exact: true }).fill(fixture[role].employee_code);
      await page.getByLabel('PIN', { exact: true }).fill(k.readPin(role), { timeout: PRIVATE_ACTION_TIMEOUT_MS });
      const [response] = await Promise.all([page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/auth/login' && r.request().method() === 'POST'), page.getByRole('button', { name: 'Войти', exact: true }).click()]);
      k.check(response.status() === 200, 'LOGIN');
    });
    return { context, page };
  };
  const currentPrincipal = async (session, role) => {
    const response = await session.context.request.get(`${fixture.origin}/api/v1/me`, { maxRedirects: 0 });
    k.check(response.status() === 200, 'CURRENT_PRINCIPAL'); const body = await response.json(), me = body.principal;
    k.check(me.user_id === fixture[role].id && me.role === role && me.active && c.stable([...me.section_ids].sort()) === c.stable([...fixture[role].section_ids].sort()), 'CURRENT_SCOPE');
  };
  const clockUi = async (name, method, click, command = null) => {
    if (command) expectedCommand = command;
    const [response] = await Promise.all([master.page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/demo/clock' && r.request().method() === method), click()]);
    headers(response, '/api/v1/demo/clock', 200, true); const snap = clock.snapshot(await response.json());
    if (command) k.check(expectedCommand === null && c.stable(response.request().postDataJSON()) === c.stable(command), 'CLOCK_RECEIPT');
    await expect(clockScope).toContainText(`Версия: ${snap.version}. Скорость: ${snap.scale}×`);
    const shown = new Date(Date.parse(snap.domain_now) + 5 * 3600000).toISOString().slice(0,19).replace('T',' ') + ' UTC+5';
    await expect(clockScope).toContainText('Бизнес-время снимка: ' + shown);
    return { name, method, path: '/api/v1/demo/clock', status: 200, cache: 'private,no-store', vary: 'Cookie', ui_snapshot_visible: true, body_sha256: c.digest(snap), snapshot: snap, command };
  };
  const report = async (pathname, click) => {
    const [response] = await Promise.all([master.page.waitForResponse(r => {
      const u = new URL(r.url()); return u.origin === fixture.origin && u.pathname === pathname && r.request().method() === 'GET' && Date.parse(u.searchParams.get('start')) === Date.parse(c.PERIOD.start) && Date.parse(u.searchParams.get('end')) === Date.parse(c.PERIOD.end);
    }), click()]); headers(response, pathname); const body = await response.json(); gate.validatePeriod(body.period); return body;
  };
  try { await privateOperationBoundary(async () => {
    phase('READ_DATABASE'); before = await observe();
    phase('CURRENT_SESSIONS'); master = await newSession('master'); executor = await newSession('executor');
    await currentPrincipal(master, 'master'); await currentPrincipal(executor, 'executor');
    const sessions = (await Promise.all(contexts.map(x => x.cookies()))).map(a => a.find(x => x.name === '__Host-naryadai_session'));
    k.check(sessions.every(x => x && x.httpOnly && x.secure && x.sameSite === 'Strict') && sessions[0].value !== sessions[1].value, 'DISTINCT_SECURE_SESSIONS');
    await expect(executor.page.getByRole('heading', { name: 'Мои наряды', level: 1, exact: true })).toBeVisible();
    phase('EQUIVALENT_CLOCK_SEQUENCE'); await master.page.getByRole('navigation', { name: 'Основная навигация' }).getByRole('button', { name: 'Демо-время', exact: true }).click();
    clockScope = master.page.getByRole('region', { name: 'Синтетическое демо-время', exact: true }); await expect(clockScope).toContainText('Реальное время авторизации');
    const start = Date.now(), rows = [];
    rows.push(await clockUi('initial','GET', () => clockScope.getByRole('button',{name:'Проверить доступ к демо-часам',exact:true}).click())); k.check(rows[0].snapshot.scale === 1, 'INITIAL_CLOCK');
    rows.push(await clockUi('pause','POST', () => clockScope.getByRole('button',{name:'Пауза (0×)',exact:true}).click(), clock.command(rows[0].snapshot,'pause'))); clock.transition(rows[0].snapshot,rows[1].snapshot,'pause');
    await new Promise(r => setTimeout(r,350)); rows.push(await clockUi('paused_read','GET', () => clockScope.getByRole('button',{name:'Обновить показание сервера',exact:true}).click())); clock.readAfter(rows[1].snapshot,rows[2].snapshot,250);
    await clockScope.getByLabel('Продвинуть вперёд на секунды (1–3600)',{exact:true}).fill(String(c.ADVANCE_SECONDS));
    rows.push(await clockUi('advance','POST', () => clockScope.getByRole('button',{name:'Продвинуть бизнес-время вперёд',exact:true}).click(),clock.command(rows[2].snapshot,'advance'))); clock.transition(rows[2].snapshot,rows[3].snapshot,'advance');
    rows.push(await clockUi('resume','POST', () => clockScope.getByRole('button',{name:'Продолжить (1×)',exact:true}).click(),clock.command(rows[3].snapshot,'resume'))); clock.transition(rows[3].snapshot,rows[4].snapshot,'resume');
    await new Promise(r => setTimeout(r,350)); rows.push(await clockUi('resumed_read','GET', () => clockScope.getByRole('button',{name:'Обновить показание сервера',exact:true}).click())); clock.readAfter(rows[4].snapshot,rows[5].snapshot,250); clock.validateJourney(rows,start,Date.now());
    phase('CANONICAL_REPORT'); await master.page.getByRole('navigation',{name:'Основная навигация'}).getByRole('button',{name:'Аналитика и отчёты',exact:true}).click();
    const scope = master.page.getByRole('region',{name:'Аналитика и отчёты',exact:true});
    const from = scope.getByLabel('Начало периода',{exact:true}), to = scope.getByLabel('Конец периода (не включён)',{exact:true});
    await from.fill(c.LOCAL_PERIOD.start); await to.fill(c.LOCAL_PERIOD.end); await expect(from).toHaveValue(c.LOCAL_PERIOD.start); await expect(to).toHaveValue(c.LOCAL_PERIOD.end);
    const facts = await report('/api/v1/analytics/shift', () => scope.getByRole('button',{name:'Показать факты',exact:true}).click()); c.historicalCounts(facts.provenance);
    k.check(facts.orders.length === 540 && facts.totals_available === true && c.stable(facts.orders.map(x=>x.order.id).sort()) === c.stable(before.order_ids) && facts.provenance.historical_evidence.identity_mapping_sha256 === before.identity_mapping_sha256, 'DATABASE_CORROBORATION');
    selected = facts.orders.find(x => x.attempts.some(a => a.submission.payload.after_photo_ids.length > 0)); k.check(selected, 'HISTORICAL_ORDER');
    const shift = await report('/api/v1/reports/shift', () => master.page.getByRole('button',{name:'Открыть отчёт смены / периода',exact:true}).click()); c.historicalCounts(shift.provenance); k.check(shift.report_kind === 'shift','SHIFT_KIND');
    await expect(master.page.getByRole('region',{name:'Выбранный отчёт',exact:true}).getByRole('heading',{name:'Защищённый отчёт смены / периода',exact:true})).toBeVisible();
    const downloadScope = master.page.getByRole('region',{name:'Скачать выбранный отчёт',exact:true}), expected = files.expected('shift',selected);
    let observed = 0; const watcher = () => { observed++; }; master.page.on('download',watcher);
    requestObserver = files.requestCompletionObserver(master.page);
    phase('ARM_ORIGINAL_REQUEST'); binding.arm(nonce); await master.page.evaluate(n => globalThis.__DALA_BODY_CAPTURE_PROBE__.arm(n), nonce);
    const [response] = await Promise.all([master.page.waitForResponse(r => r.url() === k.EXACT_URL && r.request().method() === 'GET'), downloadScope.getByRole('button',{name:'Подготовить PDF',exact:true}).click()]);
    binding.bind(response); requestObserver.bind(response.request()); const h = headers(response,'/api/v1/reports/shift.pdf');
    k.check(h['content-type'] === files.MEDIA.pdf && h['content-disposition'] === 'attachment; filename="naryadai-shift.pdf"' && h['content-security-policy'] === "default-src 'none'; sandbox" && /^[0-9]+$/.test(h['content-length'] || '') && Number(h['content-length']) > 0 && Number(h['content-length']) <= c.MAX_DOWNLOAD_BYTES && (!h['content-encoding'] || h['content-encoding'].trim().toLowerCase() === 'identity'),'EXPORT_HEADERS');
    phase('ORIGINAL_CDP_BODY'); e.ui_before = await files.sampleDownloadUi(downloadScope,'pdf'); e.request_before = requestObserver.snapshot();
    try { originalBytes = await files.boundedResponseBody(response); e.cdp = { status:'OK',failure:'NOT_OBSERVED',bytes:originalBytes.length,sha256:digest(originalBytes) };
    } catch (error) { e.cdp = { status:'FAILED',failure:files.bodyFailure(error),bytes:null,sha256:null }; originalBytes = null; }
    if (originalBytes) k.check(originalBytes.length === Number(h['content-length']) && originalBytes.length <= c.MAX_DOWNLOAD_BYTES,'ORIGINAL_BYTE_BOUND');
    e.ui_after = await files.sampleDownloadUi(downloadScope,'pdf'); e.request_after = requestObserver.snapshot();
    phase('CLIENT_OBSERVATION'); const deadline = Date.now() + 25000;
    do { e.client = o.validateClient(await master.page.evaluate(n => globalThis.__DALA_BODY_CAPTURE_PROBE__.snapshot(n),nonce),sha,run);
      if (['COMPLETE','NOT_COMPARABLE'].includes(e.client.state)) break; await new Promise(r=>setTimeout(r,25));
    } while (Date.now() < deadline);
    binding.requireBound(); e.binding = binding.snapshot();
    if (e.client.comparability === 'COMPARABLE') {
      await expect(downloadScope.getByRole('button',{name:'Сохранить PDF',exact:true})).toBeVisible();
      e.ui_at_save = await files.sampleDownloadUi(downloadScope,'pdf'); k.check(e.ui_at_save === 'READY','READY_BEFORE_SAVE');
      phase('ACTUAL_SAVE'); k.check(observed === 0,'NO_EARLY_DOWNLOAD');
      const [saved] = await Promise.all([master.page.waitForEvent('download'), downloadScope.getByRole('button',{name:'Сохранить PDF',exact:true}).click()]);
      k.check(saved.suggestedFilename() === 'naryadai-shift.pdf' && await saved.failure() === null,'COMPLETED_BROWSER_SAVE');
      savedPath = path.join(k.privateOutput(),'saved-shift.pdf'); k.check(!fs.existsSync(savedPath),'FRESH_SAVED_FILE'); await saved.saveAs(savedPath);
      const stat = fs.lstatSync(savedPath); k.check(stat.isFile() && !stat.isSymbolicLink() && stat.size > 0 && stat.size <= c.MAX_DOWNLOAD_BYTES,'SAVED_BOUND');
      const bytes = fs.readFileSync(savedPath); binding.requireBound(); k.check(observed === 1,'ONE_SAVE');
      e.saved = { status:'NOT_VERIFIED',bytes:bytes.length,sha256:digest(bytes),cdp_exact_equality:originalBytes ? (bytes.equals(originalBytes) ? 'EQUAL':'MISMATCH'):'UNAVAILABLE',
        client_hash_equality:e.client.sha256 === digest(bytes) && e.client.observed_bytes === bytes.length,content_inspection:'NOT_RUN',no_export_on_save:true };
      phase('ACTUAL_CONTENT_INSPECTION'); expectedPath = path.join(k.privateOutput(),'expected-shift-pdf.json'); fs.writeFileSync(expectedPath,c.stable(expected),{flag:'wx',mode:0o600});
      try { const { stdout } = await runFile(process.env.DALA_BCP_INSPECT_PYTHON || 'python',[path.join(__dirname,'../c113_inspect_download.py'),savedPath,'pdf',expectedPath],
        { env:{PATH:process.env.PATH,LANG:'C.UTF-8',PYTHONDONTWRITEBYTECODE:'1'},timeout:15000,maxBuffer:16384 });
        const inspection = JSON.parse(stdout); files.validateInspection(inspection,expected,'pdf'); k.check(inspection.sha256 === e.saved.sha256 && inspection.bytes === bytes.length,'INSPECTOR_FILE_BINDING');
        e.saved.content_inspection = 'VERIFIED'; e.saved.status = 'VERIFIED';
      } catch(error) { e.saved.content_inspection = files.inspectorFailure(error); }
      bytes.fill(0);
    }
    master.page.off('download',watcher); phase('CURRENT_AUTHORIZATION');
    await currentPrincipal(master,'master'); await currentPrincipal(executor,'executor');
    for (const name of ['Демо-время','Аналитика и отчёты']) await expect(executor.page.getByRole('button',{name,exact:true})).toHaveCount(0);
    const denied = await executor.context.request.get(k.EXACT_URL,{maxRedirects:0}); headers(denied,'/api/v1/reports/shift.pdf',403,false,'api');
    const denial = await denied.json(); o.requireExecutorDenial(denial); e.authority = 'VERIFIED';
    phase('FINAL_CORROBORATION'); const after = await observe(); k.check(before.business_sha256 === after.business_sha256 && c.stable(before.counts) === c.stable(after.counts),'DATABASE_UNCHANGED'); e.database_unchanged = true;
    binding.requireBound(); binding.finish(); e.binding = binding.snapshot();
    k.check(network.login_posts === 2 && network.clock_posts === 3 && network.blocked === 0,'EXACT_NETWORK');
    k.check(proof.sourceSha() === sha && c.stable(proof.fingerprint()) === c.stable(hashes),'SOURCE_UNCHANGED');
    e.interpretation = o.interpretation(e.cdp,e.client,e.saved,e.binding,e.authority);
    e.status = ['CDP_UNAVAILABLE_CLIENT_AND_SAVE_VERIFIED_INSTRUMENTED','THREE_OBSERVATIONS_AGREE_INSTRUMENTED'].includes(e.interpretation) ? 'DIAGNOSTIC_COMPLETE':'INCONCLUSIVE'; phase('DONE');
  }); } catch { e.status = 'BLOCKED'; }
  finally {
    expectedCommand = null; originalBytes?.fill(0); originalBytes = null; requestObserver?.dispose();
    if (master) { try { const final = await master.page.evaluate(n => globalThis.__DALA_BODY_CAPTURE_PROBE__.dispose(n),nonce); e.client = o.validateClient(final,sha,run); disposed = final.disposed && final.retained_capture_bytes === 0; } catch {} }
    if (binding) e.binding = binding.snapshot();
    let contextsClosed = true;
    for (const context of contexts) await context.close().catch(()=>{e.status='BLOCKED';contextsClosed=false;});
    for (const file of [savedPath,expectedPath]) if(file) fs.rmSync(file,{force:true});
    e.cleanup = !contextsClosed ? 'CONTEXT_CLOSURE_UNCONFIRMED' : disposed ? 'OWN_CAPTURE_DISPOSED_CONTEXTS_CLOSED':'CONTEXTS_CLOSED_TAP_DISPOSAL_UNCONFIRMED';
    if (!disposed) e.status = 'BLOCKED';
    if (e.status !== 'BLOCKED') {
      e.interpretation = o.interpretation(e.cdp,e.client,e.saved,e.binding,e.authority);
      e.status = ['CDP_UNAVAILABLE_CLIENT_AND_SAVE_VERIFIED_INSTRUMENTED','THREE_OBSERVATIONS_AGREE_INSTRUMENTED'].includes(e.interpretation) ? 'DIAGNOSTIC_COMPLETE':'INCONCLUSIVE';
    }
    fs.writeFileSync(path.join(k.privateOutput(),'safe-evidence.json'),JSON.stringify(e)+'\n',{flag:'wx',mode:0o600});
  }
  // Passing this test means only that a bounded diagnostic was collected.
  k.check(e.status !== 'BLOCKED','DIAGNOSTIC_BLOCKED_SEE_SAFE_EVIDENCE');
});
