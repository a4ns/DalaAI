// Synthetic in-process controller checks. No live API, browser or database evidence.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
require.extensions['.ts'] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, filename);
const { ApiClient } = require('../shared/api/client.ts');
const { OrderStore } = require('../shared/api/orderStore.ts');
const { PhotoStore } = require('./photoStore.ts');
const { ExecutorController, executorScope } = require('./executorController.ts');
const { emptyExecutorDraft } = require('../mobile/executor/model.ts');
const id = number => `00000000-0000-4000-8000-${String(number).padStart(12, '0')}`;
const user = id(1), section = id(2), a = id(3), b = id(4);
const session = { principal: { user_id: user, active: true, employee_code: 'SYNTHETIC', role: 'executor', section_ids: [section], on_shift: true }, csrf_token: 'synthetic-csrf', expires_at: '2099-01-01T00:00:00Z' };
function order(orderId, number, status = 'issued', version = 1, assignment = 1) { return { id: orderId, number: String(number), version, assignment_revision: assignment, scheduling_revision: 1, status, type: 'unplanned', description: 'Synthetic work', section_id: section, equipment_id: id(8), assignment: { executor_id: user, brigade_id: null }, created_by: id(9), issued_at: '2026-10-07T19:00:00Z', due_at: '2099-01-01T00:00:00Z', norm_minutes: 30, priority: 'normal', comment: '', before_photo_ids: [], current_submission_id: null, is_overdue: false, domain_now: '2026-10-07T19:00:00Z', updated_at: '2026-10-07T19:00:00Z' }; }
const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
const receipt = value => json({ order: value, event_ids: [id(20)], submission_id: null });
const intent = value => ({ orderId: value.id, expectedVersion: value.version, expectedAssignmentRevision: value.assignment_revision, action: 'accept', payload: {} });
async function fixture(action) {
  let visible = [order(a, 1), order(b, 2)]; const bodies = [];
  const client = new ApiClient({ online: () => true, fetch: async (url, options) => {
    if (String(url).endsWith('/auth/login')) return json(session);
    if (String(url).includes('/commands')) { bodies.push({ url: String(url), body: options.body }); return action(String(url), options); }
    return json({ items: visible, next_cursor: null });
  } });
  await client.login({ employee_code: 'SYNTHETIC', pin: '0000' });
  const orders = new OrderStore(client); await orders.refresh();
  const controller = new ExecutorController(client, orders, new PhotoStore(client), 'synthetic-session');
  return { client, orders, controller, bodies, setVisible: next => { visible = next; } };
}
(async () => {
  let aCalls = 0;
  const f = await fixture(url => {
    if (url.includes(a)) { aCalls++; if (aCalls === 1) throw new TypeError('Synthetic response lost'); return json({}, 403); }
    return receipt(order(b, 2, 'accepted', 2));
  });
  f.controller.setDraft(a, 1, { ...emptyExecutorDraft(), workDescription: 'A private draft' });
  f.controller.setDraft(b, 1, { ...emptyExecutorDraft(), workDescription: 'B independent draft' });
  assert.equal((await f.controller.act(intent(order(a, 1)))).kind, 'unknown');
  const originalBody = f.bodies[0].body;
  assert.equal((await f.controller.retry(executorScope(a, 1))).kind, 'unknown');
  assert.deepEqual(f.controller.visibleOrders().map(row => row.id), [b]);
  assert.equal(f.controller.draft(order(a, 1)).workDescription, '');
  assert.equal((await f.controller.act(intent(order(b, 2)))).kind, 'confirmed');
  assert.equal(f.controller.view(order(b, 2, 'accepted', 2)).mutation.status, 'confirmed');
  assert.equal(f.controller.draft(order(b, 2, 'accepted', 2)).workDescription, 'B independent draft');
  assert.equal(aCalls, 2, 'B work must not retry A');
  assert.equal(f.bodies[1].body, originalBody);
  f.controller.resolveConflict(executorScope(a, 1));
  assert.equal((await f.controller.act(intent(order(a, 1)))).kind, 'unknown');
  f.setVisible([order(a, 1), order(b, 2, 'accepted', 2)]); await f.orders.refresh();
  assert.equal(f.controller.draft(order(a, 1)).workDescription, 'A private draft');
  f.controller.setDraft(a, 1, { ...emptyExecutorDraft(), workDescription: 'Forbidden overwrite' });
  assert.equal(f.controller.draft(order(a, 1)).workDescription, 'A private draft');
  f.setVisible([order(a, 1, 'issued', 3, 2), order(b, 2, 'accepted', 2)]); await f.orders.refresh();
  assert.equal((await f.controller.act(intent(order(a, 1, 'issued', 3, 2)))).kind, 'unknown');
  assert.equal(f.controller.draft(order(a, 1, 'issued', 3, 2)).workDescription, '');
  assert.equal(aCalls, 2);
  f.orders.dispose();
  console.log('PASS synthetic: A unknown/403 quarantine, B independent success, same-order revision guard, preserved hidden draft and exact retry body');

  let release;
  const delayed = new Promise(resolve => { release = resolve; });
  const g = await fixture(url => url.includes(a) ? delayed : receipt(order(b, 2, 'accepted', 2)));
  g.controller.setDraft(b, 1, { ...emptyExecutorDraft(), workDescription: 'Keep B draft' });
  const old = g.controller.act(intent(order(a, 1)));
  g.setVisible([order(b, 2)]); await g.orders.refresh();
  assert.equal((await g.controller.act(intent(order(b, 2)))).kind, 'confirmed');
  release(receipt(order(a, 1, 'accepted', 2))); await old;
  assert.equal(g.orders.getSnapshot().snapshot.some(row => row.id === a), false, 'Late A receipt must not restore omitted membership');
  assert.equal(g.controller.draft(order(b, 2, 'accepted', 2)).workDescription, 'Keep B draft');
  assert.equal(g.controller.view(order(b, 2, 'accepted', 2)).mutation.status, 'confirmed');
  g.orders.dispose();
  console.log('PASS synthetic: late A settlement cannot resurrect hidden A or overwrite B state/draft');
})().catch(error => { console.error(error); process.exitCode = 1; });
