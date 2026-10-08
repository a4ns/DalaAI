import { expect, test } from '@playwright/test';
import type { Page, Route } from '@playwright/test';
import { ids, result, session } from '../support/synthetic';
import type { Dictionaries, Order, Submission } from '../../src/shared/api/wire';

/** Real mounted App/OrderStore with synthetic intercepted HTTP; not production timing or API/DB evidence. */
test.use({ viewport: { width: 390, height: 844 }, isMobile: false, hasTouch: false, deviceScaleFactor: 1 });
async function mount(page: Page, role: 'master' | 'executor') {
  const signed = session(role === 'executor' ? ids.second : ids.first); signed.principal.role = role;
  let order: Order = { ...result().order, version: 1, status: role === 'master' ? 'ai_review' : 'issued', type: 'planned', current_submission_id: role === 'master' ? ids.event : null, domain_now: '2026-10-08T02:00:00Z' };
  const dictionaries: Dictionaries = { sections: [{ id: ids.section, code: 'S', label: 'Синтетический участок' }], equipment: [{ id: ids.equipment, code: 'EQ', label: 'Синтетическое оборудование', section_id: ids.section }], brigades: [], executors: [{ id: ids.second, employee_code: 'SYNTHETIC-EXECUTOR', section_ids: [ids.section], brigade_id: null, on_shift: true, active_order_id: null, queue_count: 0 }], work_codes: [{ id: ids.first, code: 'WORK', label: 'Синтетический шифр' }], materials: [] };
  const submission: Submission = { id: ids.event, order_id: ids.order, assignment_revision: 1, attempt_number: 1, submitted_by: ids.second, submitted_at: '2026-10-08T01:00:00Z', done_late: false, completeness: 'complete', missing_evidence: [], payload: { work_description: 'Синтетическая работа', work_code_id: ids.first, materials: [], after_photo_ids: [], comment: '' }, assessments: [], reviews: [] };
  let reads = 0; let held: { route: Route; snapshot: Order } | null = null; let released = false; let failReads = false; let logout: Route | null = null; let holdMe = false; let heldMe: Route | null = null;
  const posts: { body: Record<string, unknown>; beforeRelease: boolean }[] = [];
  await page.route('**/api/v1/**', async route => {
    const request = route.request(); const url = new URL(request.url());
    if (url.pathname === '/api/v1/me') { if (holdMe) { heldMe = route; return; } return route.fulfill({ json: signed }); }
    if (url.pathname === '/api/v1/dicts') return route.fulfill({ json: dictionaries });
    if (url.pathname.includes('/submissions/')) return route.fulfill({ json: submission });
    if (url.pathname === '/api/v1/orders' && request.method() === 'GET') {
      reads++;
      if (reads === 2) { held = { route, snapshot: structuredClone(order) }; return; }
      return failReads ? route.fulfill({ status: 503, json: {} }) : route.fulfill({ json: { items: [order], next_cursor: null } });
    }
    if (url.pathname === '/api/v1/auth/logout') { logout = route; return; }
    if (url.pathname.endsWith('/commands')) {
      const body = request.postDataJSON() as Record<string, unknown>; posts.push({ body, beforeRelease: !released });
      const payload = body.payload as { decision?: string };
      order = { ...order, version: order.version + 1, status: body.action === 'review' ? payload.decision === 'close' ? 'closed' : 'rework' : 'accepted' };
      return route.fulfill({ json: { order, event_ids: [ids.event], submission_id: order.current_submission_id } });
    }
    return route.fulfill({ status: 404, json: {} });
  });
  await page.goto('/');
  if (role === 'executor') await page.getByRole('navigation', { name: 'Назначенные наряды', exact: true }).getByRole('button', { name: /Наряд SYNTHETIC-001/ }).click();
  const action = page.getByRole('button', { name: role === 'master' ? 'Принять и закрыть' : 'Принять', exact: true });
  await expect(action).toBeEnabled();
  return {
    posts, action, reads: () => reads, held: () => held !== null, logoutHeld: () => logout !== null, meHeld: () => heldMe !== null, holdNextMe: () => { holdMe = true; },
    async releaseMe() { if (!heldMe) throw new Error('Synthetic /me not observed'); holdMe = false; await heldMe.fulfill({ json: signed }); },
    async release(status = 200) { if (!held) throw new Error('Synthetic held GET not observed'); released = true; failReads = status !== 200; const current = held; held = null; await current.route.fulfill(status === 200 ? { json: { items: [current.snapshot], next_cursor: null } } : { status, json: {} }).catch(() => undefined); },
    async releaseLogout() { if (!logout) throw new Error('Synthetic logout not observed'); await logout.fulfill({ status: 204, body: '' }); },
  };
}
const settle = (page: Page) => page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));

for (const decision of ['close', 'rework'] as const) test(`healthy background poll permits one explicit master ${decision} POST before GET release`, async ({ page }) => {
  const h = await mount(page, 'master'); await page.getByRole('textbox', { name: /^Причина решения/ }).fill('Синтетическая подтверждённая проверка');
  await expect.poll(h.held).toBe(true);
  const action = page.getByRole('button', { name: decision === 'close' ? 'Принять и закрыть' : 'Вернуть на доработку', exact: true }); await expect(action).toBeEnabled();
  // Native click semantics: a disabled baseline button drops this gesture; nothing is queued.
  await action.evaluate(button => (button as HTMLButtonElement).click()); await expect.poll(() => h.posts.length).toBe(1);
  expect(h.posts[0]).toMatchObject({ beforeRelease: true, body: { expected_version: 1, action: 'review', payload: { decision, submission_id: ids.event } } });
  await h.release(); await expect(page.getByText('Решение мастера по наряду № SYNTHETIC-001 подтверждено сервером.', { exact: true })).toBeVisible(); await settle(page); expect(h.posts).toHaveLength(1);
});
test('healthy background poll permits one explicit executor POST with the confirmed original version', async ({ page }) => {
  const h = await mount(page, 'executor'); await expect.poll(h.held).toBe(true); await expect(h.action).toBeEnabled();
  await h.action.evaluate(button => (button as HTMLButtonElement).click()); await expect.poll(() => h.posts.length).toBe(1);
  expect(h.posts[0]).toMatchObject({ beforeRelease: true, body: { expected_version: 1, action: 'accept', payload: {} } });
  await h.release(); await expect(page.locator('.executor-operation')).toContainText('Действие подтверждено сервером.'); await settle(page); expect(h.posts).toHaveLength(1);
});
test('failed background poll blocks the retained snapshot and sends no deferred command', async ({ page }) => {
  const h = await mount(page, 'executor'); await expect.poll(h.held).toBe(true); await h.release(503); await expect(h.action).toBeDisabled();
  await h.action.evaluate(button => (button as HTMLButtonElement).click()); await settle(page); expect(h.posts).toHaveLength(0);
});
test('known offline invalidation and release of an old GET cannot restore command eligibility', async ({ page }) => {
  const h = await mount(page, 'executor'); await expect.poll(h.held).toBe(true); await page.context().setOffline(true); await expect(h.action).toBeDisabled();
  await h.action.evaluate(button => (button as HTMLButtonElement).click()); await h.release(); await settle(page);
  await expect(h.action).toBeDisabled(); expect(h.posts).toHaveLength(0);
});
test('manual refresh joining a held automatic poll blocks now and does not replay a dropped gesture', async ({ page }) => {
  const h = await mount(page, 'executor'); await expect.poll(h.held).toBe(true); await expect(h.action).toBeEnabled();
  h.holdNextMe(); await page.getByRole('button', { name: 'Обновить', exact: true }).click(); await expect.poll(h.meHeld).toBe(true); await expect(h.action).toBeDisabled(); expect(h.reads()).toBe(2);
  await h.action.evaluate(button => (button as HTMLButtonElement).click()); expect(h.posts).toHaveLength(0);
  await h.releaseMe(); await h.release(); await expect(h.action).toBeEnabled(); await settle(page); expect(h.posts).toHaveLength(0);
});
test('synchronous logout latch refuses a raced new command while the old session still exists', async ({ page }) => {
  const h = await mount(page, 'executor'); await expect.poll(h.held).toBe(true); await expect(h.action).toBeEnabled();
  page.once('dialog', dialog => { void dialog.accept(); }); await page.getByRole('button', { name: 'Выйти', exact: true }).click(); await expect.poll(h.logoutHeld).toBe(true);
  await h.action.evaluate(button => (button as HTMLButtonElement).click()); await settle(page); expect(h.posts).toHaveLength(0);
  await h.releaseLogout(); await h.release(); await expect(page.getByRole('heading', { name: 'Войдите в систему', exact: true })).toBeVisible(); expect(h.posts).toHaveLength(0);
});
