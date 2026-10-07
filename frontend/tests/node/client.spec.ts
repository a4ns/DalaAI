import { expect, test } from '@playwright/test';
import { sourceModule } from '../support/source';
import { deferred, ids, json, result, session } from '../support/synthetic';
import type * as Client from '../../src/shared/api/client';

const { ApiClient, ApiError, SessionChangedError } = sourceModule<typeof Client>('src/shared/api/client.ts');
const login = { employee_code: 'SYNTHETIC-UI-TEST', pin: '0000' };

test('unknown outcome keeps the captured body and operation ID despite later draft edits', async () => {
  const sent: RequestInit[] = [];
  let mutationCount = 0;
  const client = new ApiClient({ online: () => true, fetch: async (url, init) => {
    if (String(url).endsWith('/auth/login')) return json(session());
    sent.push(init!);
    if (++mutationCount === 1) throw new TypeError('Synthetic lost response');
    return json(result());
  } });
  await client.login(login);
  const command = { expected_version: 1, action: 'pause' as const, payload: { reason: 'Исходная причина' } };
  const prepared = client.prepareCommand(ids.order, command);
  await expect(client.execute(prepared)).rejects.toMatchObject({ outcomeUnknown: true });
  command.expected_version = 99;
  command.payload.reason = 'Изменённый после отправки черновик';
  await client.execute(prepared);
  expect(sent).toHaveLength(2);
  expect(sent[1].body).toBe(sent[0].body);
  expect(JSON.parse(String(sent[1].body))).toMatchObject({ operation_id: prepared.operationId, expected_version: 1, payload: { reason: 'Исходная причина' } });
  expect(sent[0].credentials).toBe('same-origin');
  expect(new Headers(sent[0].headers).get('X-CSRF-Token')).toBe(session().csrf_token);
});

test('repeated execute shares one in-flight operation and a confirmed receipt is reused', async () => {
  const response = deferred<Response>();
  let sends = 0;
  const client = new ApiClient({ online: () => true, fetch: async url => {
    if (String(url).endsWith('/auth/login')) return json(session());
    sends += 1;
    return response.promise;
  } });
  await client.login(login);
  const prepared = client.prepareCommand(ids.order, { expected_version: 1, action: 'accept', payload: {} });
  const first = client.execute(prepared);
  const second = client.execute(prepared);
  expect(first).toBe(second);
  expect(sends).toBe(1);
  response.resolve(json(result()));
  await Promise.all([first, second]);
  await client.execute(prepared);
  expect(sends).toBe(1);
});

test('expired session clears identity and invalidates old prepared commands without another send', async () => {
  let sends = 0;
  const client = new ApiClient({ online: () => true, fetch: async url => {
    sends += 1;
    return String(url).endsWith('/auth/login') ? json(session()) : json({}, 401);
  } });
  await client.login(login);
  const prepared = client.prepareCommand(ids.order, { expected_version: 1, action: 'accept', payload: {} });
  await expect(client.listOrders()).rejects.toBeInstanceOf(ApiError);
  expect(client.session).toBeNull();
  await expect(client.execute(prepared)).rejects.toBeInstanceOf(SessionChangedError);
  expect(sends).toBe(2);
});

test('a response from a cleared identity cannot repopulate session or order data', async () => {
  const pending = deferred<Response>();
  const client = new ApiClient({ online: () => true, fetch: async () => pending.promise });
  const request = client.getMe();
  const rejected = expect(request).rejects.toBeInstanceOf(SessionChangedError);
  client.clearIdentity();
  pending.resolve(json(session()));
  await rejected;
  expect(client.session).toBeNull();
});

test('newer login wins over an interrupted earlier login', async () => {
  const old = deferred<Response>();
  let calls = 0;
  const client = new ApiClient({ online: () => true, fetch: async () => ++calls === 1 ? old.promise : json(session(ids.second)) });
  const first = client.login(login);
  const rejected = expect(first).rejects.toBeInstanceOf(SessionChangedError);
  await client.login({ ...login, employee_code: 'SYNTHETIC-SECOND' });
  old.resolve(json(session(ids.first)));
  await rejected;
  expect(client.session?.principal.user_id).toBe(ids.second);
});

test('completion of an old logout cannot clear a newer login', async () => {
  const logout = deferred<Response>();
  let logins = 0;
  const client = new ApiClient({ online: () => true, fetch: async url => {
    if (String(url).endsWith('/auth/logout')) return logout.promise;
    return json(session(++logins === 1 ? ids.first : ids.second));
  } });
  await client.login(login);
  const outgoing = client.logout();
  const rejected = expect(outgoing).rejects.toBeInstanceOf(SessionChangedError);
  await client.login({ ...login, employee_code: 'SYNTHETIC-SECOND' });
  logout.resolve(new Response(null, { status: 204 }));
  await rejected;
  expect(client.session?.principal.user_id).toBe(ids.second);
});

test('malformed successful mutation remains unknown rather than becoming fake success', async () => {
  const client = new ApiClient({ online: () => true, fetch: async url => String(url).endsWith('/auth/login') ? json(session()) : json({ ok: true }) });
  await client.login(login);
  const prepared = client.prepareCommand(ids.order, { expected_version: 1, action: 'accept', payload: {} });
  await expect(client.execute(prepared)).rejects.toMatchObject({ outcomeUnknown: true, status: 200 });
});

test('409 is explicit conflict, 503 is unknown outcome, and no command retries itself', async () => {
  for (const status of [409, 503]) {
    let commands = 0;
    const client = new ApiClient({ online: () => true, fetch: async url => {
      if (String(url).endsWith('/auth/login')) return json(session());
      commands += 1;
      return json({}, status);
    } });
    await client.login(login);
    const prepared = client.prepareCommand(ids.order, { expected_version: 1, action: 'accept', payload: {} });
    await expect(client.execute(prepared)).rejects.toMatchObject({ status, outcomeUnknown: status === 503 });
    expect(commands).toBe(1);
  }
});

test('known offline commands do not reach the network', async () => {
  let online = true;
  let calls = 0;
  const client = new ApiClient({ online: () => online, fetch: async () => { calls += 1; return json(session()); } });
  await client.login(login);
  const prepared = client.prepareCommand(ids.order, { expected_version: 1, action: 'accept', payload: {} });
  online = false;
  await expect(client.execute(prepared)).rejects.toMatchObject({ outcomeUnknown: false });
  expect(calls).toBe(1);
});

test('multipart unknown retries reuse the exact original bytes, boundary and operation ID', async () => {
  const sent: RequestInit[] = [];
  const client = new ApiClient({ online: () => true, fetch: async (url, init) => {
    if (String(url).endsWith('/auth/login')) return json(session());
    sent.push(init!);
    throw new TypeError('Synthetic lost upload response');
  } });
  await client.login(login);
  const file = new File(['synthetic serialization bytes; not a decoded image'], 'synthetic.jpg', { type: 'image/jpeg' });
  const prepared = await client.preparePhoto({ purpose: 'after', sectionId: ids.section, orderId: ids.order, assignmentRevision: 3, file });
  await expect(client.execute(prepared)).rejects.toMatchObject({ outcomeUnknown: true });
  await expect(client.execute(prepared)).rejects.toMatchObject({ outcomeUnknown: true });
  expect(sent).toHaveLength(2);
  expect(new Headers(sent[0].headers).get('Content-Type')).toBe(new Headers(sent[1].headers).get('Content-Type'));
  const first = await (sent[0].body as Blob).text();
  expect(await (sent[1].body as Blob).text()).toBe(first);
  expect(first).toContain(prepared.operationId);
  expect(first).toContain('name="assignment_revision"');
  expect(first).toContain('synthetic serialization bytes');
});

test('Retry-After prevents an early resend while preserving the original request for later', async () => {
  const now = Date.now;
  let clock = now();
  Date.now = () => clock;
  try {
    let sent = 0;
    const client = new ApiClient({ online: () => true, fetch: async url => {
      if (String(url).endsWith('/auth/login')) return json(session());
      if (++sent === 1) return new Response('{}', { status: 429, headers: { 'Retry-After': '60' } });
      return json(result());
    } });
    await client.login(login);
    const prepared = client.prepareCommand(ids.order, { expected_version: 1, action: 'accept', payload: {} });
    await expect(client.execute(prepared)).rejects.toMatchObject({ status: 429, retryAfterSeconds: 60 });
    await expect(client.execute(prepared)).rejects.toMatchObject({ status: 429 });
    expect(sent).toBe(1);
    clock += 60_001;
    await client.execute(prepared);
    expect(sent).toBe(2);
  } finally { Date.now = now; }
});

test('photo reads negotiate supported image MIME and reject an HTML response', async () => {
  let accept = '';
  let calls = 0;
  const client = new ApiClient({ online: () => true, fetch: async (_url, init) => {
    accept = new Headers(init?.headers).get('Accept') ?? '';
    return ++calls === 1 ? new Response('synthetic bytes', { headers: { 'Content-Type': 'image/jpeg' } }) : new Response('<html>failure</html>', { headers: { 'Content-Type': 'text/html' } });
  } });
  expect((await client.getPhoto(ids.order)).type).toBe('image/jpeg');
  expect(accept).toBe('image/jpeg, image/png, image/webp');
  await expect(client.getPhoto(ids.order)).rejects.toBeInstanceOf(ApiError);
});

test('read polling honors Retry-After across query variations before another GET', async () => {
  const now = Date.now;
  let clock = now();
  Date.now = () => clock;
  try {
    let sends = 0;
    const client = new ApiClient({ online: () => true, fetch: async () => ++sends === 1
      ? new Response('{}', { status: 503, headers: { 'Retry-After': '30' } })
      : json({ items: [], next_cursor: null }) });
    await expect(client.listOrders()).rejects.toMatchObject({ status: 503 });
    await expect(client.listOrders({ status: 'issued' })).rejects.toMatchObject({ status: 503 });
    expect(sends).toBe(1);
    clock += 30_001;
    await client.listOrders();
    expect(sends).toBe(2);
  } finally { Date.now = now; }
});

test('raw int64 cursor outside safe integer range is rejected without a rounded follow-up request', async () => {
  const { readAllOrderEvents } = sourceModule<typeof import('../../src/shared/api/orderStore')>('src/shared/api/orderStore.ts');
  const urls: string[] = [];
  const client = new ApiClient({ online: () => true, fetch: async url => {
    urls.push(String(url));
    return new Response('{"items":[],"next_after_sequence":9007199254740993,"has_more":true}', { headers: { 'Content-Type': 'application/json' } });
  } });
  await expect(readAllOrderEvents(client, ids.order)).rejects.toBeInstanceOf(ApiError);
  expect(urls).toHaveLength(1);
  expect(urls[0]).toContain('after_sequence=0');
});

test('unsafe outgoing history cursor is rejected before fetch', async () => {
  let sends = 0;
  const client = new ApiClient({ online: () => true, fetch: async () => { sends += 1; return json({}); } });
  for (const cursor of [Number.MAX_SAFE_INTEGER + 1, -1, 1.5, Infinity]) await expect(client.listOrderEvents(ids.order, cursor)).rejects.toBeInstanceOf(ApiError);
  expect(sends).toBe(0);
});
