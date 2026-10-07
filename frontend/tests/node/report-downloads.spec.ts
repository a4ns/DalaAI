import { expect, test } from '@playwright/test';
import { sourceModule } from '../support/source';
import { deferred, json, session } from '../support/synthetic';
import shiftFixture from '../fixtures/analytics/report-shift.json' with { type: 'json' };
import factsFixture from '../fixtures/analytics/analytics-shift.json' with { type: 'json' };
import type * as Client from '../../src/shared/api/client';
import type * as Files from '../../src/shared/api/reportFiles';
import type * as Downloads from '../../src/features/analytics/downloads';
import type * as Analytics from '../../src/features/analytics/controller';
import type { ShiftReport } from '../../src/shared/api/analyticsProtocol';
const { ApiClient, SessionChangedError } = sourceModule<typeof Client>('src/shared/api/client.ts');
const { REPORT_FILE_LIMIT, REPORT_FILE_MIME } = sourceModule<typeof Files>('src/shared/api/reportFiles.ts');
const { ReportDownloadController, browserDownloadPort } = sourceModule<typeof Downloads>('src/features/analytics/downloads.ts');
const { AnalyticsController } = sourceModule<typeof Analytics>('src/features/analytics/controller.ts');
const period = { start: shiftFixture.period.start, end: shiftFixture.period.end };
const credentials = { employee_code: 'SYNTHETIC-UI-TEST', pin: '0000' };
/** Signature-only synthetic bytes; these are not renderer output or a valid PDF/XLSX document. */
const pdf = new TextEncoder().encode('%PDF-SYNTHETIC-SIGNATURE-ONLY');
const xlsx = new Uint8Array([80, 75, 3, 4, 83, 89, 78, 84, 72]);
function fileResponse(format: Files.ReportFileFormat = 'pdf', filename = `naryadai-shift.${format}`, bytes: Uint8Array<ArrayBuffer> = format === 'pdf' ? pdf : xlsx): Response {
  return new Response(bytes, { headers: { 'Content-Type': REPORT_FILE_MIME[format], 'Content-Disposition': `attachment; filename="${filename}"` } });
}
function fakePort() {
  const created: string[] = []; const revoked: string[] = []; const saved: { url: string; filename: string }[] = [];
  const timers: { callback: () => void; ms: number; cancelled: boolean }[] = [];
  const port: Downloads.DownloadPort = {
    createUrl: () => { const url = `blob:synthetic-only/${created.length + 1}`; created.push(url); return url; },
    revokeUrl: url => { revoked.push(url); }, save: (url, filename) => { saved.push({ url, filename }); },
    schedule: (callback, ms) => { const timer = { callback, ms, cancelled: false }; timers.push(timer); return () => { timer.cancelled = true; }; },
  };
  return { port, created, revoked, saved, timers, fire(ms: number) { for (const timer of [...timers]) if (!timer.cancelled && timer.ms === ms) { timer.cancelled = true; timer.callback(); } } };
}
async function signedClient(send: (url: string, init?: RequestInit) => Promise<Response>, role: 'master'|'executor' = 'master') {
  const signed = session(); signed.principal.role = role;
  const client = new ApiClient({ online: () => true, fetch: async (url, init) => String(url).endsWith('/auth/login') ? json(signed) : send(String(url), init) });
  await client.login(credentials); return client;
}
async function prepared(send: (url: string) => Promise<Response> = async () => fileResponse()) {
  const client = await signedClient(send); const fake = fakePort(); let current = true; const denied: number[] = [];
  const download = new ReportDownloadController(client, shiftFixture as ShiftReport, () => current, error => denied.push(error.status), fake.port);
  const detach = download.attach();
  return { client, fake, download, denied, detach, changeContext: () => { current = false; } };
}

test('binary routes use fixed suffixes, only start/end and canonical ASCII filenames through same-origin GET', async () => {
  const calls: { url: URL; init: RequestInit }[] = []; const orderId = 'ABCDEFAB-CDEF-4ABC-8DEF-ABCDEFABCDEF';
  const client = await signedClient(async (url, init) => {
    const parsed = new URL(url, 'https://synthetic.example.invalid'); calls.push({ url: parsed, init: init! });
    const format = parsed.pathname.endsWith('.pdf') ? 'pdf' : 'xlsx';
    return fileResponse(format, `naryadai-${parsed.pathname.includes('/orders/') ? `order-${orderId.toLowerCase()}` : 'shift'}.${format}`);
  });
  for (const format of ['pdf', 'xlsx'] as const) {
    for (const kind of ['shift', { orderId }] as const) {
      const file = await client.getReportFile(kind, format, period);
      expect(file.filename).toBe(`naryadai-${kind === 'shift' ? 'shift' : `order-${orderId.toLowerCase()}`}.${format}`);
      expect(file.blob.type).toBe(REPORT_FILE_MIME[format]); expect(file.blob.size).toBeGreaterThan(0);
    }
  }
  expect(calls.map(call => call.url.pathname)).toEqual(['/api/v1/reports/shift.pdf', `/api/v1/reports/orders/${orderId.toLowerCase()}.pdf`, '/api/v1/reports/shift.xlsx', `/api/v1/reports/orders/${orderId.toLowerCase()}.xlsx`]);
  for (const call of calls) {
    expect([...call.url.searchParams.keys()].sort()).toEqual(['end', 'start']);
    expect(call.init).toMatchObject({ method: 'GET', credentials: 'same-origin', mode: 'same-origin', cache: 'no-store', redirect: 'error' });
    expect(new Headers(call.init.headers).get('Accept')).toBe(call.url.pathname.endsWith('.pdf') ? REPORT_FILE_MIME.pdf : REPORT_FILE_MIME.xlsx);
  }
});

test('binary validation rejects wrong status, HTML, MIME, signatures, empty bodies and unsafe or mismatched attachment names', async () => {
  const bad: Response[] = [
    new Response(pdf, { status: 206, headers: fileResponse().headers }),
    new Response('<html>synthetic</html>', { headers: { 'Content-Type': 'text/html', 'Content-Disposition': 'attachment; filename="naryadai-shift.pdf"' } }),
    fileResponse('pdf', 'naryadai-shift.pdf', new TextEncoder().encode('<html>synthetic</html>')),
    fileResponse('pdf', '../../synthetic.html'), fileResponse('pdf', 'naryadai-order-foreign.pdf'),
    new Response(pdf, { headers: { 'Content-Type': REPORT_FILE_MIME.pdf } }),
    fileResponse('pdf', 'naryadai-shift.pdf', new Uint8Array()),
    fileResponse('xlsx'),
  ];
  for (const response of bad) {
    const client = await signedClient(async () => response);
    await expect(client.getReportFile('shift', 'pdf', period)).rejects.toThrow();
  }
});

test('binary streamed byte limit permits exactly8MiB and cancels an over-limit body rather than handing it off', async () => {
  const maximum = new Uint8Array(REPORT_FILE_LIMIT); maximum.set(pdf);
  const valid = await signedClient(async () => fileResponse('pdf', 'naryadai-shift.pdf', maximum));
  expect((await valid.getReportFile('shift', 'pdf', period)).blob.size).toBe(REPORT_FILE_LIMIT);
  let cancelled = false;
  const overflow = new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(maximum); controller.enqueue(new Uint8Array([1])); }, cancel() { cancelled = true; } });
  const client = await signedClient(async () => new Response(overflow, { headers: fileResponse().headers }));
  await expect(client.getReportFile('shift', 'pdf', period)).rejects.toThrow(/формата или размера/);
  expect(cancelled).toBe(true);
  const declared = fileResponse(); declared.headers.set('Content-Length', String(REPORT_FILE_LIMIT + 1));
  const rejected = await signedClient(async () => declared);
  await expect(rejected.getReportFile('shift', 'pdf', period)).rejects.toThrow();
});

test('identity change while binary body is streaming rejects the file before any prepared handoff', async () => {
  let close!: () => void;
  const stream = new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(pdf); close = () => controller.close(); } });
  const client = await signedClient(async () => new Response(stream, { headers: fileResponse().headers }));
  const pending = client.getReportFile('shift', 'pdf', period);
  const rejected = expect(pending).rejects.toBeInstanceOf(SessionChangedError);
  await new Promise(resolve => setTimeout(resolve, 0)); client.clearIdentity(); close(); await rejected;
});

test('non-master and unsupported formats fail before binary fetch', async () => {
  let requests = 0; const client = await signedClient(async () => { requests++; return fileResponse(); }, 'executor');
  await expect(client.getReportFile('shift', 'pdf', period)).rejects.toMatchObject({ status: 403 });
  const master = await signedClient(async () => { requests++; return fileResponse(); });
  await expect(master.getReportFile('shift', 'html' as Files.ReportFileFormat, period)).rejects.toThrow();
  expect(requests).toBe(0);
});

test('download controller is inert on attach, dedupes repeated prepare and never saves after an asynchronous response', async () => {
  const late = deferred<Response>(); let requests = 0;
  const h = await prepared(async () => { requests++; return late.promise; });
  expect(requests).toBe(0); expect(h.fake.created).toEqual([]);
  const first = h.download.prepare('pdf'); const second = h.download.prepare('pdf');
  expect(requests).toBe(1);
  late.resolve(fileResponse()); await Promise.all([first, second]);
  expect(h.download.getSnapshot().status).toBe('ready'); expect(h.fake.saved).toEqual([]);
  h.download.save(); h.download.save();
  expect(h.fake.saved).toHaveLength(1); expect(h.download.getSnapshot().status).toBe('handed_off');
  expect(h.fake.revoked).toEqual([]); h.fake.fire(1000); expect(h.fake.revoked).toEqual(h.fake.created);
  h.detach(); expect(h.fake.revoked).toHaveLength(1);
});

test('cancelled preparation and stale report context never create or save a download URL', async () => {
  for (const cancel of [true, false]) {
    const late = deferred<Response>(); const h = await prepared(async () => late.promise);
    const pending = h.download.prepare('pdf'); if (cancel) h.download.cancel(); else h.changeContext();
    late.resolve(fileResponse()); await pending; h.download.save();
    expect(h.fake.created).toEqual([]); expect(h.fake.saved).toEqual([]); h.detach();
  }
});

test('ready file is revoked on context/logout invalidation and cannot be saved under another identity', async () => {
  for (const changeIdentity of [true, false]) {
    const h = await prepared(); await h.download.prepare('pdf');
    if (changeIdentity) h.client.clearIdentity(); else h.changeContext();
    h.download.save(); expect(h.fake.saved).toEqual([]); expect(h.fake.revoked).toEqual(h.fake.created); h.detach();
  }
});

test('ready lifetime expires synchronously after60seconds even if its background timer has not fired', async () => {
  const originalNow = Date.now; let now = originalNow(); Date.now = () => now;
  try {
    const h = await prepared(); await h.download.prepare('pdf');
    now += 60001; h.download.save();
    expect(h.fake.saved).toEqual([]);
    expect(h.download.getSnapshot().status).toBe('expired');
    expect(h.fake.revoked).toEqual(h.fake.created); h.detach();
  } finally { Date.now = originalNow; }
});

test('scheduled expiry, unmount and rejected native save clean URLs without inventing a completed download', async () => {
  const expired = await prepared(); await expired.download.prepare('pdf'); expired.fake.fire(60000);
  expect(expired.download.getSnapshot().status).toBe('expired'); expect(expired.fake.revoked).toEqual(expired.fake.created); expired.detach();
  const unmounted = await prepared(); await unmounted.download.prepare('pdf'); unmounted.detach();
  expect(unmounted.fake.revoked).toEqual(unmounted.fake.created); expect(unmounted.fake.saved).toEqual([]);
  const failed = await prepared(); failed.fake.port.save = () => { throw new Error('Synthetic browser rejection'); };
  await failed.download.prepare('pdf'); failed.download.save();
  expect(failed.download.getSnapshot().status).toBe('error'); expect(failed.fake.revoked).toEqual(failed.fake.created); failed.detach();
});

test('download404 clears the current analytics capture through its actual access-loss callback', async () => {
  const client = await signedClient(async url => url.includes('.pdf?') ? json({}, 404) : url.includes('/analytics/') ? json(factsFixture) : json(shiftFixture));
  const analytics = new AnalyticsController(client); const cleanAnalytics = analytics.attach();
  await analytics.load(period); await analytics.openReport(null); const report = analytics.getSnapshot().report.data!;
  const fake = fakePort(); const download = new ReportDownloadController(client, report, () => analytics.getSnapshot().report.data === report, error => analytics.reportAccessLost(error, report), fake.port);
  const detach = download.attach(); await download.prepare('pdf');
  expect(analytics.getSnapshot()).toMatchObject({ facts: { data: null }, report: { status: 'error', data: null } });
  expect(fake.created).toEqual([]); expect(fake.saved).toEqual([]); detach(); cleanAnalytics();
});

test('old download access failure cannot erase a newer report capture', async () => {
  const client = await signedClient(async url => url.includes('/analytics/') ? json(factsFixture) : json(shiftFixture));
  const analytics = new AnalyticsController(client); const cleanup = analytics.attach(); await analytics.load(period); await analytics.openReport(null);
  const previous = analytics.getSnapshot().report.data!;
  await analytics.openReport(null); const current = analytics.getSnapshot().report.data!;
  const { ApiError } = sourceModule<typeof Client>('src/shared/api/client.ts');
  analytics.reportAccessLost(new ApiError('Synthetic previous denial', 404), previous);
  expect(analytics.getSnapshot().report.data).toBe(current); expect(analytics.getSnapshot().facts.data).not.toBeNull(); cleanup();
});

test('browser save port removes its temporary anchor even when a synthetic click throws', () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'document');
  let appended = false; let removed = false;
  const anchor = { href: '', download: '', rel: '', click() { throw new Error('Synthetic click failure'); }, remove() { removed = true; } };
  Object.defineProperty(globalThis, 'document', { configurable: true, value: { createElement: () => anchor, body: { append: () => { appended = true; } } } });
  try {
    expect(() => browserDownloadPort.save('blob:synthetic-only/url', 'naryadai-shift.pdf')).toThrow('Synthetic click failure');
    expect(appended).toBe(true); expect(removed).toBe(true); expect(anchor).toMatchObject({ href: 'blob:synthetic-only/url', download: 'naryadai-shift.pdf', rel: 'noopener' });
  } finally { if (previous) Object.defineProperty(globalThis, 'document', previous); else Reflect.deleteProperty(globalThis, 'document'); }
});


test('a format switch ignores the older PDF response and preserves only the explicitly newer XLSX choice', async () => {
  const old = deferred<Response>(); let calls = 0;
  const h = await prepared(async () => ++calls === 1 ? old.promise : fileResponse('xlsx'));
  const pdfRequest = h.download.prepare('pdf');
  await h.download.prepare('xlsx');
  old.resolve(fileResponse()); await pdfRequest;
  expect(h.fake.created).toHaveLength(1); expect(h.fake.saved).toEqual([]);
  h.download.save(); expect(h.fake.saved[0].filename).toBe('naryadai-shift.xlsx'); h.detach();
});

test('session expiry before the ready-link deadline prevents saving even without a401 response', async () => {
  const originalNow = Date.now; let now = originalNow(); Date.now = () => now;
  try {
    const signed = session(); signed.expires_at = new Date(now + 5000).toISOString();
    const client = new ApiClient({ online: () => true, fetch: async url => String(url).endsWith('/auth/login') ? json(signed) : fileResponse() });
    await client.login(credentials); const fake = fakePort();
    const download = new ReportDownloadController(client, shiftFixture as ShiftReport, () => true, () => undefined, fake.port);
    const detach = download.attach(); await download.prepare('pdf');
    now += 5001; download.save();
    expect(fake.saved).toEqual([]); expect(fake.revoked).toEqual(fake.created); detach();
  } finally { Date.now = originalNow; }
});
