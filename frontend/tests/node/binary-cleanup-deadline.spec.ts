import { expect, test } from '@playwright/test';
import { sourceModule } from '../support/source';
import { json, session } from '../support/synthetic';
import type * as Client from '../../src/shared/api/client';
import type * as Files from '../../src/shared/api/reportFiles';
const { ApiClient } = sourceModule<typeof Client>('src/shared/api/client.ts');
const { REPORT_FILE_LIMIT, REPORT_FILE_MIME } = sourceModule<typeof Files>('src/shared/api/reportFiles.ts');
const period = { start: '2026-10-07T00:00:00Z', end: '2026-10-08T00:00:00Z' };
async function clientWith(send: (init: RequestInit) => Response) {
  const client = new ApiClient({ timeoutMs: 50, online: () => true, fetch: async (url, init) => String(url).endsWith('/auth/login') ? json(session()) : send(init!) });
  await client.login({ employee_code: 'SYNTHETIC', pin: '0000' }); return client;
}
async function boundedOutcome(promise: Promise<unknown>) {
  let timeout: ReturnType<typeof setTimeout> | undefined;
  try { return await Promise.race([promise.then(() => 'unexpected_file', error => { expect(error).toMatchObject({ name: 'ApiError' }); return 'rejected'; }), new Promise<string>(resolve => { timeout = setTimeout(() => resolve('pending_after_deadline'), 200); })]); }
  finally { clearTimeout(timeout); }
}
for (const format of ['pdf', 'xlsx'] as const) {
  for (const failure of ['declared_overflow', 'streamed_overflow', 'wrong_mime'] as const) test(`binary ${format} ${failure} rejects without awaiting uncooperative cancellation`, async () => {
    let cancellations = 0; let signal!: AbortSignal;
    const stream = new ReadableStream<Uint8Array>({ pull(controller) { if (failure === 'streamed_overflow') controller.enqueue(new Uint8Array(REPORT_FILE_LIMIT + 1)); }, cancel() { cancellations++; return new Promise<void>(() => {}); } }, { highWaterMark: 0 });
    const client = await clientWith(init => {
      signal = init.signal!; const headers = new Headers({ 'Content-Type': failure === 'wrong_mime' ? 'text/html' : REPORT_FILE_MIME[format], 'Content-Disposition': `attachment; filename="naryadai-shift.${format}"` });
      if (failure === 'declared_overflow') headers.set('Content-Length', String(REPORT_FILE_LIMIT + 1));
      return new Response(stream, { headers });
    });
    const outcome = await boundedOutcome(client.getReportFile('shift', format, period));
    expect(outcome).toBe('rejected'); expect(cancellations).toBe(1); expect(stream.locked).toBe(false);
    // A rejected transfer has already cleared its real50ms request timer.
    await new Promise(resolve => setTimeout(resolve, 70)); expect(signal.aborted).toBe(false);
  });
}
test('successful PDF and XLSX preserve exact bytes and do not invoke error cancellation', async () => {
  for (const format of ['pdf', 'xlsx'] as const) {
    const bytes = format === 'pdf' ? new TextEncoder().encode('%PDF-SYNTHETIC-ONLY') : new Uint8Array([80, 75, 3, 4, 1, 2, 3]);
    let cancellations = 0;
    const client = await clientWith(() => new Response(new ReadableStream({ start(controller) { controller.enqueue(bytes); controller.close(); }, cancel() { cancellations++; return new Promise<void>(() => {}); } }), { headers: { 'Content-Type': REPORT_FILE_MIME[format], 'Content-Disposition': `attachment; filename="naryadai-shift.${format}"` } }));
    const result = await client.getReportFile('shift', format, period);
    expect(new Uint8Array(await result.blob.arrayBuffer())).toEqual(bytes); expect(result.blob.type).toBe(REPORT_FILE_MIME[format]); expect(cancellations).toBe(0);
  }
});
