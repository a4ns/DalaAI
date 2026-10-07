import { expect, test } from '@playwright/test';
import { sourceModule } from '../support/source';
import { deferred, json, session } from '../support/synthetic';
import type * as Client from '../../src/shared/api/client';
const { ApiClient, SessionChangedError } = sourceModule<typeof Client>('src/shared/api/client.ts');
const credentials = { employee_code: 'SYNTHETIC-UI-TEST', pin: '0000' };
const endpoint = 'https://push.example.invalid/synthetic-subscription';
const body = JSON.stringify({ endpoint, keys: { p256dh: 'synthetic-public-key', auth: 'synthetic-auth-test-value' } });
const config = { enabled: true, application_server_key: Buffer.from([4, ...Array<number>(64).fill(1)]).toString('base64url'), delivery_semantics: 'provider_acceptance_is_not_device_delivery', device_policy: 'latest_registration_per_user' };

test('push config validates the additive semantics and key without creating any subscription', async () => {
  for (const value of [config, { ...config, enabled: false, application_server_key: null }]) {
    const paths: string[] = [];
    const client = new ApiClient({ online: () => true, fetch: async url => { if (String(url).endsWith('/auth/login')) return json(session()); paths.push(String(url)); return json(value); } });
    await client.login(credentials);
    expect(await client.getPushConfig()).toEqual(value);
    expect(paths).toEqual(['/api/v1/push/config']);
  }
  for (const patch of [{ delivery_semantics: 'device_delivery_guaranteed' }, { device_policy: 'any_user' }, { application_server_key: 'invalid' }, { enabled: false }]) {
    const client = new ApiClient({ online: () => true, fetch: async url => String(url).endsWith('/auth/login') ? json(session()) : json({ ...config, ...patch }) });
    await client.login(credentials);
    await expect(client.getPushConfig()).rejects.toMatchObject({ outcomeUnknown: false });
  }
});

for (const [label, wrong] of [['false flag', json({ enabled: false })], ['extra field', json({ enabled: true, extra: true })], ['wrong status', json({ enabled: true }, 201)], ['malformed JSON', new Response('not-json', { status: 200 })]] as const) {
  test(`push register accepts only exact200 enabled:true; ${label} stays unknown`, async () => {
    const sent: RequestInit[] = []; const paths: string[] = [];
    const client = new ApiClient({ online: () => true, fetch: async (url, init) => {
      if (String(url).endsWith('/auth/login')) return json(session());
      paths.push(String(url)); sent.push(init!);
      return sent.length === 1 ? wrong.clone() : json({ enabled: true });
    } });
    await client.login(credentials);
    await expect(client.registerPushSubscription(body)).rejects.toMatchObject({ outcomeUnknown: true });
    expect(sent).toHaveLength(1);
    await expect(client.registerPushSubscription(body)).resolves.toBeUndefined();
    expect(paths).toEqual(['/api/v1/push/subscriptions', '/api/v1/push/subscriptions']);
    expect(sent.map(item => item.body)).toEqual([body, body]);
    expect(sent[1]).toMatchObject({ method: 'POST', credentials: 'same-origin', mode: 'same-origin', redirect: 'error', cache: 'no-store' });
    expect(new Headers(sent[1].headers).get('X-CSRF-Token')).toBe(session().csrf_token);
    expect(new Headers(sent[1].headers).get('Content-Type')).toBe('application/json');
  });
}

test('push removal uses the accepted endpoint body and requires204 rather than a misleading200', async () => {
  const requests: { url: string; body: string }[] = [];
  const client = new ApiClient({ online: () => true, fetch: async (url, init) => {
    if (String(url).endsWith('/auth/login')) return json(session());
    requests.push({ url: String(url), body: String(init?.body) });
    return requests.length === 1 ? json({ enabled: false }) : new Response(null, { status: 204 });
  } });
  await client.login(credentials);
  await expect(client.removePushSubscription(endpoint)).rejects.toMatchObject({ outcomeUnknown: true, status: 200 });
  await expect(client.removePushSubscription(endpoint)).resolves.toBeUndefined();
  expect(requests).toEqual(Array.from({ length: 2 }, () => ({ url: '/api/v1/push/subscriptions/remove', body: JSON.stringify({ endpoint }) })));
});

test('push register shares Retry-After cooldown and never silently retries an unknown request', async () => {
  let sends = 0;
  const client = new ApiClient({ online: () => true, fetch: async url => {
    if (String(url).endsWith('/auth/login')) return json(session());
    sends += 1; return new Response('{}', { status: 503, headers: { 'Content-Type': 'application/json', 'Retry-After': '60' } });
  } });
  await client.login(credentials);
  await expect(client.registerPushSubscription(body)).rejects.toMatchObject({ status: 503, outcomeUnknown: true });
  await expect(client.registerPushSubscription(body)).rejects.toMatchObject({ status: 503, outcomeUnknown: false, retryAfterSeconds: 60 });
  expect(sends).toBe(1);
});

test('push registration response from an old identity cannot be accepted after logout begins', async () => {
  const late = deferred<Response>();
  const client = new ApiClient({ online: () => true, fetch: async url => String(url).endsWith('/auth/login') ? json(session()) : late.promise });
  await client.login(credentials);
  const request = client.registerPushSubscription(body);
  const rejected = expect(request).rejects.toBeInstanceOf(SessionChangedError);
  client.clearIdentity(); late.resolve(json({ enabled: true }));
  await rejected;
  expect(client.session).toBeNull();
});
