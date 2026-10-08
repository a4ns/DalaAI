import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { ids, result, session } from '../support/synthetic';
import type { Dictionaries, Order, Submission } from '../../src/shared/api/wire';

/** Real mounted App/OrderStore, intercepted synthetic HTTP. No API/DB, OS-push or physical-device evidence. */
const order = (patch: Partial<Order> = {}): Order => ({ ...result().order, status: 'issued', type: 'planned', ...patch });
async function mount(page: Page, role: 'master' | 'executor' = 'executor', initial: Order[] = [], initiallyFailed = false) {
  const now = new Date('2026-10-08T12:00:00Z'); await page.clock.install({ time: now }); await page.clock.pauseAt(now);
  let signed = session(role === 'executor' ? ids.second : ids.first); signed.principal.role = role;
  let items = initial; let mode: 'healthy' | 'failed' | 'partial' | 'forbidden' = initiallyFailed ? 'failed' : 'healthy';
  const requests: { path: string; method: string }[] = []; let reads = 0;
  const dictionaries: Dictionaries = { sections: [{ id: ids.section, code: 'S', label: 'Синтетический участок' }], equipment: [{ id: ids.equipment, code: 'EQ', label: 'Синтетическое оборудование', section_id: ids.section }], executors: [{ id: ids.second, employee_code: 'SYNTHETIC-EXECUTOR', section_ids: [ids.section], brigade_id: null, on_shift: true, active_order_id: null, queue_count: 0 }], brigades: [], work_codes: [{ id: ids.first, code: 'WORK', label: 'Синтетический шифр' }], materials: [] };
  await page.route('**/api/v1/**', async route => {
    const request = route.request(); const url = new URL(request.url()); requests.push({ path: url.pathname, method: request.method() });
    if (url.pathname === '/api/v1/me') return route.fulfill({ json: signed });
    if (url.pathname === '/api/v1/dicts') return route.fulfill({ json: dictionaries });
    if (url.pathname === '/api/v1/auth/logout') return route.fulfill({ status: 204, body: '' });
    if (url.pathname === '/api/v1/orders' && request.method() === 'GET') {
      reads++;
      if (mode === 'failed' || (mode === 'partial' && url.searchParams.has('cursor'))) return route.fulfill({ status: 503, json: {} });
      if (mode === 'forbidden') return route.fulfill({ status: 403, json: {} });
      return route.fulfill({ json: { items, next_cursor: mode === 'partial' ? 'synthetic-next' : null } });
    }
    if (url.pathname.includes('/submissions/')) {
      const current = items.find(item => item.current_submission_id);
      const submission: Submission = { id: current?.current_submission_id ?? ids.event, order_id: current?.id ?? ids.order, assignment_revision: current?.assignment_revision ?? 1, attempt_number: 1, submitted_by: ids.second, submitted_at: '2026-10-08T11:00:00Z', done_late: false, completeness: 'complete', missing_evidence: [], payload: { work_description: 'Синтетическая работа', work_code_id: ids.first, materials: [], after_photo_ids: [], comment: '' }, assessments: [], reviews: [] };
      return route.fulfill({ json: submission });
    }
    if (url.pathname.endsWith('/commands')) {
      const body = request.postDataJSON(); const current = items[0];
      const changed = { ...current, version: current.version + 1, status: body.action === 'accept' ? 'accepted' as const : 'closed' as const };
      items = [changed]; return route.fulfill({ json: { order: changed, event_ids: [ids.event], submission_id: changed.current_submission_id } });
    }
    return route.fulfill({ status: 404, json: {} });
  });
  const firstResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/orders');
  await page.goto('/'); await (await firstResponse).finished(); await expect.poll(() => reads).toBeGreaterThan(0);
  await expect(page.getByRole('status', { name: 'Уведомления', exact: true })).toBeAttached();
  // Wait for the initial full response to render before advancing a mocked polling clock.
  await page.evaluate(() => Promise.resolve());
  return {
    requests, reads: () => reads,
    items: (next: Order[]) => { items = next; }, mode: (next: typeof mode) => { mode = next; },
    identity: (userId: string) => { signed = { ...signed, principal: { ...signed.principal, user_id: userId } }; },
    async poll() {
      const before = reads; const partial = mode === 'partial';
      const response = page.waitForResponse(response => { const url = new URL(response.url()); return url.pathname === '/api/v1/orders' && (!partial || url.searchParams.has('cursor')); });
      await page.clock.runFor(2100); await (await response).finished(); await page.evaluate(() => Promise.resolve());
      await expect.poll(() => reads).toBeGreaterThan(before);
    },
  };
}
const notices = (page: Page) => page.locator('.in-app-notice');
const close = (page: Page) => page.getByRole('button', { name: /^Закрыть уведомление:/ });

test('silent initial snapshot; repeated polls, timestamp changes and reappearance do not repeat a notice', async ({ page }) => {
  const h = await mount(page, 'executor', [order()]); await expect(notices(page)).toHaveCount(0);
  h.items([order({ domain_now: '2026-10-08T12:01:00Z', updated_at: '2026-10-08T12:01:00Z', is_overdue: true })]); await h.poll(); await expect(notices(page)).toHaveCount(0);
  h.items([order({ version: 3, assignment_revision: 2 })]); await h.poll(); await expect(notices(page)).toHaveCount(1);
  const region = page.getByRole('status', { name: 'Уведомления', exact: true }); await expect(region).toHaveAttribute('aria-live', 'polite'); await expect(region).toHaveAttribute('aria-atomic', 'false');
  const box = await close(page).boundingBox(); expect(box!.width).toBeGreaterThanOrEqual(44); expect(box!.height).toBeGreaterThanOrEqual(44);
  const before = h.requests.length; await close(page).click(); expect(h.requests.length).toBe(before);
  await h.poll(); await expect(notices(page)).toHaveCount(0);
  h.items([]); await h.poll(); h.items([order({ version: 4, assignment_revision: 2 })]); await h.poll(); await expect(notices(page)).toHaveCount(0);
  expect(h.requests.some(request => /push|notification/.test(request.path))).toBe(false);
});

test('eight-second passive lifetime pauses on hover and keyboard focus, then resumes remaining time', async ({ page }) => {
  const h = await mount(page); h.items([order()]); await h.poll(); await expect(notices(page)).toHaveCount(1);
  await page.clock.runFor(3000); await notices(page).hover(); await page.clock.runFor(9000); await expect(notices(page)).toHaveCount(1);
  await close(page).focus(); await page.mouse.move(0, 0); await page.clock.runFor(9000); await expect(close(page)).toBeFocused(); await expect(notices(page)).toHaveCount(1);
  await page.getByRole('button', { name: 'Мои наряды', exact: true }).focus(); await page.clock.runFor(4800); await expect(notices(page)).toHaveCount(1);
  await page.clock.runFor(300); await expect(notices(page)).toHaveCount(0);
});

test('three visible notices, safe mobile width, reduced motion and no delayed backlog', async ({ page }, info) => {
  await page.setViewportSize({ width: 360, height: 732 }); await page.emulateMedia({ reducedMotion: 'reduce' });
  const h = await mount(page);
  const items = Array.from({ length: 5 }, (_, i) => order({ id: `10000000-0000-4000-8000-00000000001${i}`, number: `SYNTHETIC-${i}` })); h.items(items); await h.poll();
  await expect(notices(page)).toHaveCount(3); expect(await notices(page).first().evaluate(node => getComputedStyle(node).animationName)).toBe('none');
  for (const box of await notices(page).evaluateAll(nodes => nodes.map(node => { const rect = node.getBoundingClientRect(); return { left: rect.left, right: rect.right, bottom: rect.bottom }; }))) { expect(box.left).toBeGreaterThanOrEqual(0); expect(box.right).toBeLessThanOrEqual(360); expect(box.bottom).toBeLessThanOrEqual(732); }
  await page.screenshot({ path: info.outputPath('synthetic-in-app-notices-mobile.png') });
  while (await close(page).count()) await close(page).first().click(); await h.poll(); await expect(notices(page)).toHaveCount(0);
});

test('new notification burst never evicts the keyboard-focused existing notice', async ({ page }) => {
  const h = await mount(page); h.items([order()]); await h.poll(); await expect(notices(page)).toHaveCount(1);
  const originalClose = page.getByRole('button', { name: 'Закрыть уведомление: Вам назначен наряд № SYNTHETIC-001.', exact: true });
  await originalClose.focus(); await expect(originalClose).toBeFocused();
  const incoming = Array.from({ length: 4 }, (_, i) => order({ id: `10000000-0000-4000-8000-00000000003${i}`, number: `INCOMING-${i}` }));
  h.items([order(), ...incoming]); await h.poll(); await expect(notices(page)).toHaveCount(3);
  await expect(originalClose).toBeFocused(); await expect(originalClose).toBeVisible();
});

test('master result notice preserves draft, focus, scroll and navigation, including the hidden workspace tab', async ({ page }) => {
  const h = await mount(page, 'master', [order({ status: 'in_progress' })]);
  const draft = page.getByRole('textbox', { name: /^Задача или неисправность/ }); await draft.fill('Синтетический незавершённый черновик'); await draft.focus();
  const before = await page.evaluate(() => ({ scroll: window.scrollY, url: location.href }));
  h.items([order({ version: 3, status: 'ai_review', current_submission_id: ids.event })]); await h.poll(); await expect(notices(page)).toContainText('ожидает решения мастера');
  await expect(draft).toBeFocused(); await expect(draft).toHaveValue('Синтетический незавершённый черновик');
  expect(await page.evaluate(() => ({ scroll: window.scrollY, url: location.href }))).toEqual(before);
  await expect(page.getByRole('button', { name: 'Наряды', exact: true })).toHaveAttribute('aria-current', 'page');
  await page.getByRole('button', { name: 'Демо-время', exact: true }).click(); await expect(notices(page)).toBeVisible(); await close(page).click();
  await page.getByRole('button', { name: 'Наряды', exact: true }).click(); await expect(draft).toHaveValue('Синтетический незавершённый черновик');
  expect(h.requests.filter(request => request.method === 'POST')).toHaveLength(0);
});

for (const role of ['master', 'executor'] as const) test(`own ${role} inline action confirmation is not duplicated by a toast`, async ({ page }) => {
  const h = await mount(page, role, [order(role === 'master' ? { status: 'ai_review', current_submission_id: ids.event } : {})]);
  if (role === 'executor') await page.getByRole('navigation', { name: 'Назначенные наряды', exact: true }).getByRole('button', { name: /Наряд SYNTHETIC-001/ }).click();
  else await page.getByRole('textbox', { name: /^Причина решения/ }).fill('Синтетическая проверка');
  await page.getByRole('button', { name: role === 'master' ? 'Принять и закрыть' : 'Принять', exact: true }).click();
  if (role === 'master') await expect(page.getByText('Решение мастера по наряду № SYNTHETIC-001 подтверждено сервером.', { exact: true })).toBeVisible();
  else await expect(page.locator('.executor-operation')).toContainText('Действие подтверждено сервером.');
  await h.poll(); await expect(notices(page)).toHaveCount(0); expect(h.requests.filter(request => request.method === 'POST')).toHaveLength(1);
});

test('failed and partial initial reads remain silent; first recovered full snapshot is a baseline', async ({ page }) => {
  const h = await mount(page, 'executor', [order()], true); await expect(notices(page)).toHaveCount(0);
  h.mode('partial'); await h.poll(); await expect(notices(page)).toHaveCount(0);
  h.mode('healthy'); await h.poll(); await expect(notices(page)).toHaveCount(0);
  h.items([order({ version: 3, assignment_revision: 2 })]); await h.poll(); await expect(notices(page)).toHaveCount(1);
});

for (const loss of ['logout', 'forbidden', 'account'] as const) test(`${loss} removes a visible toast and old session contents`, async ({ page }) => {
  const h = await mount(page); h.items([order()]); await h.poll(); await expect(notices(page)).toHaveCount(1);
  if (loss === 'logout') { page.once('dialog', dialog => { void dialog.accept(); }); await page.getByRole('button', { name: 'Выйти', exact: true }).click(); await expect(page.getByRole('heading', { name: 'Войдите в систему', exact: true })).toBeVisible(); }
  else if (loss === 'forbidden') { h.mode('forbidden'); await h.poll(); }
  else { h.identity(ids.first); await page.evaluate(() => window.dispatchEvent(new Event('online'))); }
  await expect(notices(page)).toHaveCount(0);
});
