import { expect, test } from '@playwright/test';
import { sourceModule } from '../support/source';
import { ids, json, result, session } from '../support/synthetic';
import type * as Client from '../../src/shared/api/client';

const { ApiClient, safeErrorMessage } = sourceModule<typeof Client>('src/shared/api/client.ts');
// These inputs stay inside injected test transport; no account or authentication service exists.
const syntheticLogin = { employee_code: 'SYNTHETIC-UI-TEST', pin: '0000' };
function expectOriginBoundary(init: RequestInit) {
  expect(init).toMatchObject({ credentials: 'same-origin', mode: 'same-origin', referrerPolicy: 'origin', cache: 'no-store', redirect: 'error' });
  const headers = new Headers(init.headers);
  expect(headers.has('Origin')).toBe(false);
  expect(headers.has('Referer')).toBe(false);
  expect(headers.has('Sec-Fetch-Site')).toBe(false);
}

test('login explicitly requests origin-only referrer policy without fabricating browser security headers', async () => {
  const calls: { url: string; init: RequestInit }[] = [];
  const client = new ApiClient({ online: () => true, fetch: async (url, init) => {
    calls.push({ url: String(url), init: init! }); return json(session());
  } });
  await client.login(syntheticLogin);
  expect(calls).toHaveLength(1); expect(calls[0].url).toBe('/api/v1/auth/login');
  expectOriginBoundary(calls[0].init);
  expect(calls[0].init.method).toBe('POST');
  expect(new Headers(calls[0].init.headers).has('X-CSRF-Token')).toBe(false);
  expect(JSON.parse(String(calls[0].init.body))).toEqual(syntheticLogin);
});

test('authenticated command and logout preserve session-bound CSRF and existing transport barriers', async () => {
  const calls: { url: string; init: RequestInit }[] = [];
  const client = new ApiClient({ online: () => true, fetch: async (url, init) => {
    const path = String(url); calls.push({ url: path, init: init! });
    return path.endsWith('/auth/login') ? json(session()) : path.endsWith('/auth/logout') ? new Response(null, { status: 204 }) : json(result());
  } });
  await client.login(syntheticLogin);
  const command = client.prepareCommand(ids.order, { expected_version: 1, action: 'accept', payload: {} });
  await client.execute(command); await client.logout();
  expect(calls).toHaveLength(3);
  for (const call of calls.slice(1)) {
    expectOriginBoundary(call.init); expect(call.init.method).toBe('POST');
    expect(new Headers(call.init.headers).get('X-CSRF-Token')).toBe(session().csrf_token);
  }
  expect(JSON.parse(String(calls[1].init.body)).operation_id).toBe(command.operationId);
});

test('session restoration uses the same narrow policy without adding CSRF to GET', async () => {
  let captured: RequestInit | undefined;
  const client = new ApiClient({ online: () => true, fetch: async (url, init) => {
    expect(String(url)).toBe('/api/v1/me'); captured = init; return json(session());
  } });
  await client.getMe(); expectOriginBoundary(captured!); expect(captured!.method).toBe('GET');
  expect(new Headers(captured!.headers).has('X-CSRF-Token')).toBe(false);
});

test('multipart upload shares the origin policy without replacing its prepared body or CSRF', async () => {
  const uploads: RequestInit[] = [];
  const client = new ApiClient({ online: () => true, fetch: async (url, init) => {
    if (String(url).endsWith('/auth/login')) return json(session());
    uploads.push(init!); throw new TypeError('Synthetic interrupted transport');
  } });
  await client.login(syntheticLogin);
  const prepared = await client.preparePhoto({ purpose: 'after', sectionId: ids.section, orderId: ids.order, assignmentRevision: 1, file: new File(['synthetic-only'], 'synthetic.jpg', { type: 'image/jpeg' }) });
  await expect(client.execute(prepared)).rejects.toMatchObject({ outcomeUnknown: true });
  expect(uploads).toHaveLength(1); expectOriginBoundary(uploads[0]);
  expect(new Headers(uploads[0].headers).get('X-CSRF-Token')).toBe(session().csrf_token);
  expect(new Headers(uploads[0].headers).get('Content-Type')).toMatch(/^multipart\/form-data; boundary=/);
  expect(await (uploads[0].body as Blob).text()).toContain(prepared.operationId);
});

for (const status of [403, 429]) test(`origin policy does not retry or bypass login ${status}`, async () => {
  let calls = 0;
  const client = new ApiClient({ online: () => true, fetch: async (_url, init) => {
    calls += 1; expectOriginBoundary(init!);
    return new Response('{}', { status, headers: status === 429 ? { 'Retry-After': '60' } : {} });
  } });
  let error: unknown;
  try { await client.login(syntheticLogin); } catch (caught) { error = caught; }
  expect(error).toMatchObject({ status }); expect(calls).toBe(1); expect(client.session).toBeNull();
  expect(safeErrorMessage(error)).toBe(status === 403 ? 'Нет доступа к этому действию или объекту.' : 'Слишком много запросов. Повторите позже.');
  if (status === 429) {
    await expect(client.login(syntheticLogin)).rejects.toMatchObject({ status: 429 });
    expect(calls).toBe(1);
  }
});
