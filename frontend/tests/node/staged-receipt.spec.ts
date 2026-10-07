import { expect, test } from '@playwright/test';
import { sourceModule } from '../support/source';
import { ids, json, session } from '../support/synthetic';
import type * as Client from '../../src/shared/api/client';
import type * as Validation from '../../src/shared/api/validation';
import type { StagedPhoto } from '../../src/shared/api/wire';
const { ApiClient } = sourceModule<typeof Client>('src/shared/api/client.ts');
const { isWire } = sourceModule<typeof Validation>('src/shared/api/validation.ts');
const validPhoto = (): StagedPhoto => ({ id: ids.event, section_id: ids.section, purpose: 'after', owner_id: ids.first, order_id: ids.order, assignment_revision: 1, mime_type: 'image/jpeg', bytes: 25, sha256: 'a'.repeat(64), uploaded_at: '2026-10-07T19:00:00Z', expires_at: '2099-01-01T00:00:00Z', exif_removed: true });
const file = () => new File(['synthetic serialization bytes'], 'synthetic.jpg', { type: 'image/jpeg' });
const login = { employee_code: 'SYNTHETIC-UI-TEST', pin: '0000' };

type ContextField = 'owner' | 'section' | 'purpose' | 'order' | 'assignment';
function wrongContext(field: ContextField): StagedPhoto {
  const photo = validPhoto();
  if (field === 'owner') photo.owner_id = ids.second;
  if (field === 'section') photo.section_id = ids.equipment;
  if (field === 'purpose') { photo.purpose = 'before'; photo.order_id = null; photo.assignment_revision = null; }
  if (field === 'order') photo.order_id = ids.second;
  if (field === 'assignment') photo.assignment_revision = 2;
  return photo;
}

for (const field of ['owner', 'section', 'purpose', 'order', 'assignment'] as const) {
  test(`stage receipt: wrong ${field} is never cached; explicit retry resends identical intent and accepts valid context`, async () => {
    const wrong = wrongContext(field);
    expect(isWire('StagedPhoto', wrong), 'The negative receipt is schema-valid; this tests relational binding.').toBe(true);
    const bodies: Uint8Array[] = [];
    const contentTypes: string[] = [];
    const client = new ApiClient({ online: () => true, fetch: async (url, init) => {
      if (String(url).endsWith('/auth/login')) return json(session());
      bodies.push(new Uint8Array(await (init!.body as Blob).arrayBuffer()));
      contentTypes.push(new Headers(init?.headers).get('Content-Type')!);
      return json(bodies.length === 1 ? wrong : validPhoto(), 201);
    } });
    await client.login(login);
    const intent = await client.preparePhoto({ sectionId: ids.section, purpose: 'after', orderId: ids.order, assignmentRevision: 1, file: file() });
    await expect(client.execute(intent)).rejects.toMatchObject({ outcomeUnknown: true, status: 201 });
    expect(bodies).toHaveLength(1);
    await expect(client.execute(intent)).resolves.toEqual(validPhoto());
    expect(bodies).toHaveLength(2);
    expect(bodies[1]).toEqual(bodies[0]);
    expect(contentTypes[1]).toBe(contentTypes[0]);
    expect(new TextDecoder().decode(bodies[1])).toContain(intent.operationId);
    await expect(client.execute(intent)).resolves.toEqual(validPhoto());
    expect(bodies, 'A valid confirmed receipt is cached only after binding succeeds.').toHaveLength(2);
  });
}

test('stage receipt: before-photo receipt must remain unbound to any order or assignment', async () => {
  const valid = { ...validPhoto(), purpose: 'before' as const, order_id: null, assignment_revision: null };
  const wrong = { ...valid, order_id: ids.order, assignment_revision: 1 };
  expect(isWire('StagedPhoto', wrong)).toBe(true);
  const bodies: string[] = [];
  const client = new ApiClient({ online: () => true, fetch: async (url, init) => {
    if (String(url).endsWith('/auth/login')) return json(session());
    bodies.push(await (init!.body as Blob).text());
    return json(bodies.length === 1 ? wrong : valid, 201);
  } });
  await client.login(login);
  const intent = await client.preparePhoto({ sectionId: ids.section, purpose: 'before', file: file() });
  await expect(client.execute(intent)).rejects.toMatchObject({ outcomeUnknown: true });
  await expect(client.execute(intent)).resolves.toEqual(valid);
  expect(bodies).toHaveLength(2);
  expect(bodies[1]).toBe(bodies[0]);
});

test('stage receipt: caller edits during preparation cannot change captured request or expected receipt context', async () => {
  let fields: FormData | null = null;
  const client = new ApiClient({ online: () => true, fetch: async (url, init) => {
    if (String(url).endsWith('/auth/login')) return json(session());
    fields = await new Response(init!.body as Blob, { headers: init!.headers }).formData();
    return json(validPhoto(), 201);
  } });
  await client.login(login);
  const input: Client.StagePhotoInput = { sectionId: ids.section, purpose: 'after', orderId: ids.order, assignmentRevision: 1, file: file() };
  const preparing = client.preparePhoto(input);
  input.sectionId = ids.equipment; input.orderId = ids.second; input.assignmentRevision = 99;
  const intent = await preparing;
  await expect(client.execute(intent)).resolves.toEqual(validPhoto());
  expect(fields!.get('section_id')).toBe(ids.section);
  expect(fields!.get('order_id')).toBe(ids.order);
  expect(fields!.get('assignment_revision')).toBe('1');
  expect(fields!.get('operation_id')).toBe(intent.operationId);
});

test('stage receipt: PhotoStore unknown context mismatch recovers by resending once with identical upload bytes', async () => {
  const { PhotoStore } = sourceModule<typeof import('../../src/app/photoStore')>('src/app/photoStore.ts');
  const bodies: string[] = [];
  const client = new ApiClient({ online: () => true, fetch: async (url, init) => {
    if (String(url).endsWith('/auth/login')) return json(session());
    bodies.push(await (init!.body as Blob).text());
    return json(bodies.length === 1 ? wrongContext('order') : validPhoto(), 201);
  } });
  await client.login(login);
  const store = new PhotoStore(client);
  const context = { key: 'synthetic-context-retry', phase: 'after' as const, sectionId: ids.section, orderId: ids.order, assignmentRevision: 1 };
  const local = { id: 'synthetic-local', file: file(), originalName: 'synthetic.jpg', originalBytes: 29, width: 1, height: 1, preparedAt: '2026-10-07T19:00:00Z' };
  store.select(context, [local]);
  await expect.poll(() => store.get(context).jobs[local.id]?.status).toBe('unknown');
  expect(store.confirmedIds(context)).toEqual([]);
  store.retry(context, local);
  await new Promise(resolve => setTimeout(resolve, 0));
  expect(bodies).toHaveLength(2);
  await expect.poll(() => store.get(context).jobs[local.id]?.status).toBe('confirmed');
  expect(store.confirmedIds(context)).toEqual([ids.event]);
  expect(bodies[1]).toBe(bodies[0]);
});
