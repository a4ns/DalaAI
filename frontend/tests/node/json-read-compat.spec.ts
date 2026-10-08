import { expect, test } from '@playwright/test';
import { sourceModule } from '../support/source';
import { json, session } from '../support/synthetic';
import { clock } from '../support/demo-clock';
import rawShift from '../fixtures/analytics/report-shift.json' with { type: 'json' };
import rawSummary from '../../src/features/aiReports/__fixtures__/serializer-response.json' with { type: 'json' };
import type * as Client from '../../src/shared/api/client';
const { ApiClient } = sourceModule<typeof Client>('src/shared/api/client.ts');
async function setup(response: () => Response) {
  const client = new ApiClient({ online: () => true, fetch: async url => String(url).endsWith('/auth/login') ? json(session()) : response() });
  await client.login({ employee_code: 'SYNTHETIC', pin: '0000' }); return client;
}
test('existing clock and shift JSON keep the legacy text consumer and their schema checks', async () => {
  for (const kind of ['clock', 'shift'] as const) {
    let textReads = 0; let readerAccess = 0;
    const client = await setup(() => {
      const response = json(kind === 'clock' ? clock() : rawShift); const text = response.text.bind(response);
      response.text = async () => { textReads++; return text(); };
      Object.defineProperty(response, 'body', { get() { readerAccess++; throw new Error('Legacy route must not acquire a reader'); } });
      return response;
    });
    if (kind === 'clock') expect((await client.getDemoClock()).mode).toBe('synthetic_demo');
    else expect((await client.getShiftReport(rawShift.period)).report_kind).toBe('shift');
    expect(textReads).toBe(1); expect(readerAccess).toBe(0);
  }
});
test('legacy clock retains its4KiB byte cap even though the consumer is text', async () => {
  const client = await setup(() => json({ ...clock(), synthetic_padding: 'я'.repeat(4096) }));
  await expect(client.getDemoClock()).rejects.toMatchObject({ status: 200, outcomeUnknown: false });
});
test('new summary JSON still uses streaming and does not call the legacy text consumer', async () => {
  let textReads = 0; const client = await setup(() => { const response = json(rawSummary); response.text = async () => { textReads++; throw new Error('New summary must stream'); }; return response; });
  const summary = await client.createAiSummary({ operation_id: rawSummary.operation_id, start: rawSummary.period.start, end: rawSummary.period.end, report_kind: 'shift' });
  expect(summary.mode).toBe('deterministic_fallback'); expect(textReads).toBe(0);
});
