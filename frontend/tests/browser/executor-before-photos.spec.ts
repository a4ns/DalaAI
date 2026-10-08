import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { deferred, ids, result, session } from '../support/synthetic';
import type { Dictionaries, Order } from '../../src/shared/api/wire';

// Real mounted App/React and decoded PNG pixels, with explicitly synthetic intercepted HTTP.
// This is not backend authorization, stored attachment, production, or physical Android evidence.
const photoA = '20000000-0000-4000-8000-000000000001';
const photoB = '20000000-0000-4000-8000-000000000002';
const photoC = '20000000-0000-4000-8000-000000000003';
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=', 'base64');
async function mount(page: Page, mode: 'happy' | '403' | '404' | 'slow' | 'retry' = 'happy') {
  const gate = deferred<void>(); const logoutGate = deferred<void>();
  const stats = { reads: [] as string[], commands: 0, lists: 0, active: 0, maximum: 0 };
  let current = { ...session(ids.second), principal: { ...session(ids.second).principal, role: 'executor' as const } };
  let rows: Order[] = [
    { ...result().order, id: ids.order, number: 'SYNTHETIC-BEFORE-A', before_photo_ids: [photoA], status: 'accepted' },
    { ...result().order, id: ids.event, number: 'SYNTHETIC-BEFORE-B', before_photo_ids: [photoB], status: 'accepted' },
    { ...result().order, id: ids.equipment, number: 'SYNTHETIC-UNRELATED', before_photo_ids: [photoC], assignment: { executor_id: ids.first, brigade_id: null } },
  ];
  const dicts: Dictionaries = { sections: [{ id: ids.section, code: 'S', label: 'Синтетический участок' }], equipment: [{ id: ids.equipment, code: 'E', label: 'Синтетическое оборудование', section_id: ids.section }], executors: [], brigades: [], work_codes: [], materials: [] };
  await page.addInitScript(() => {
    const created: string[] = []; const revoked: string[] = [];
    const create = URL.createObjectURL.bind(URL); const revoke = URL.revokeObjectURL.bind(URL);
    URL.createObjectURL = value => { const url = create(value); created.push(url); return url; };
    URL.revokeObjectURL = url => { revoked.push(url); revoke(url); };
    Object.assign(window, { syntheticBeforeUrls: { created, revoked } });
  });
  await page.route('**/api/v1/**', async route => {
    const request = route.request(); const url = new URL(request.url());
    if (url.pathname === '/api/v1/me') return route.fulfill({ json: current });
    if (url.pathname === '/api/v1/dicts') return route.fulfill({ json: dicts });
    if (url.pathname === '/api/v1/orders' && request.method() === 'GET') { stats.lists++; return route.fulfill({ json: { items: rows, next_cursor: null } }); }
    if (url.pathname.startsWith('/api/v1/photos/')) {
      const id = url.pathname.split('/').at(-1)!; stats.reads.push(id); stats.active++; stats.maximum = Math.max(stats.maximum, stats.active);
      try {
        if (mode === 'slow' && id === photoA) await gate.promise;
        if (id === photoA && (mode === '403' || mode === '404')) return await route.fulfill({ status: Number(mode), json: {} });
        if (mode === 'retry' && stats.reads.filter(photo => photo === photoA).length === 1) return await route.fulfill({ status: 503, json: {} });
        return await route.fulfill({ contentType: 'image/png', body: png });
      } catch { /* Context switching can cancel the deliberately delayed synthetic request. */ }
      finally { stats.active--; }
      return;
    }
    if (url.pathname.endsWith('/commands')) {
      stats.commands++; const id = url.pathname.split('/')[4]; const order = rows.find(row => row.id === id)!;
      rows = rows.map(row => row.id === id ? { ...row, version: row.version + 1, status: 'in_progress' } : row);
      return route.fulfill({ json: { order: rows.find(row => row.id === order.id), event_ids: [ids.event], submission_id: null } });
    }
    if (url.pathname === '/api/v1/auth/logout') { await logoutGate.promise; return route.fulfill({ status: 204 }); }
    return route.fulfill({ status: 404, json: {} });
  });
  await page.goto('/'); await expect(page.getByRole('heading', { name: 'Мои наряды', exact: true, level: 1 })).toBeVisible();
  return { stats, gate, logoutGate, setRows: (next: Order[]) => { rows = next; }, rows: () => rows,
    loseScope: () => { current = { ...current, principal: { ...current.principal, section_ids: [] } }; } };
}
const card = (page: Page, name: string) => page.getByRole('navigation', { name: 'Назначенные наряды' }).getByRole('button', { name: new RegExp(name) });
const beforeImage = (page: Page) => page.getByRole('img', { name: 'Фото до выполнения 1', exact: true });
async function urls(page: Page) { return page.evaluate(() => (window as unknown as { syntheticBeforeUrls: { created: string[]; revoked: string[] } }).syntheticBeforeUrls); }

test('synthetic mounted before-photo is selected-only, decodes bytes, and survives polling and repeated actions', async ({ page }) => {
  const h = await mount(page); expect(h.stats.reads).toEqual([]); await expect(card(page, 'SYNTHETIC-UNRELATED')).toHaveCount(0);
  await card(page, 'SYNTHETIC-BEFORE-A').click(); await expect(beforeImage(page)).toBeVisible();
  await expect.poll(() => beforeImage(page).evaluate(image => (image as HTMLImageElement).naturalWidth)).toBe(1);
  await expect(page.getByText('Фото результата 1', { exact: true })).toHaveCount(0);
  const imageUrl = await beforeImage(page).getAttribute('src'); const start = page.getByRole('button', { name: 'Начать работу', exact: true });
  await start.evaluate(button => { (button as HTMLButtonElement).click(); (button as HTMLButtonElement).click(); });
  await expect(page.getByRole('heading', { name: 'Результат работы', exact: true })).toBeVisible(); expect(h.stats.commands).toBe(1);
  const listCount = h.stats.lists; await expect.poll(() => h.stats.lists).toBeGreaterThan(listCount);
  expect(await beforeImage(page).getAttribute('src')).toBe(imageUrl); expect(h.stats.reads).toEqual([photoA]); expect((await urls(page)).revoked).toEqual([]);
  const oldScroll = await page.evaluate(() => window.scrollY); await expect.poll(() => h.stats.lists).toBeGreaterThan(listCount + 1);
  expect(await page.evaluate(() => window.scrollY)).toBe(oldScroll);
});
for (const status of ['403', '404'] as const) test(`synthetic mounted ${status} never shows missing bytes as before-photo evidence`, async ({ page }) => {
  const h = await mount(page, status); await card(page, 'SYNTHETIC-BEFORE-A').click();
  await expect(page.getByText(status === '403' ? 'Доступ к фото до выполнения не подтверждён.' : 'Фото до выполнения недоступно: файл не найден.', { exact: false })).toBeVisible();
  await expect(beforeImage(page)).toHaveCount(0); expect((await urls(page)).created).toEqual([]);
  await card(page, 'SYNTHETIC-BEFORE-A').click(); expect(h.stats.reads).toEqual([photoA]);
});
test('synthetic mounted slow old selection cannot replace new photo; switching back is a fresh lifetime', async ({ page }) => {
  const h = await mount(page, 'slow'); await card(page, 'SYNTHETIC-BEFORE-A').click(); await expect.poll(() => h.stats.reads.length).toBe(1);
  await card(page, 'SYNTHETIC-BEFORE-B').click(); await expect(beforeImage(page)).toBeVisible(); const newUrl = await beforeImage(page).getAttribute('src');
  h.gate.resolve(); await expect.poll(() => h.stats.active).toBe(0); expect(await beforeImage(page).getAttribute('src')).toBe(newUrl); expect((await urls(page)).created).toHaveLength(1);
  await card(page, 'SYNTHETIC-BEFORE-A').click(); await expect(beforeImage(page)).toBeVisible(); expect(h.stats.reads).toEqual([photoA, photoB, photoA]);
  expect((await urls(page)).revoked).toContain(newUrl);
});
test('synthetic mounted session scope loss removes displayed before-photo and revokes its URL', async ({ page }) => {
  const h = await mount(page); await card(page, 'SYNTHETIC-BEFORE-A').click(); await expect(beforeImage(page)).toBeVisible(); const old = await beforeImage(page).getAttribute('src');
  h.loseScope(); await page.getByRole('button', { name: 'Обновить', exact: true }).click(); await expect(beforeImage(page)).toHaveCount(0);
  expect((await urls(page)).revoked).toContain(old); expect(h.stats.reads).toEqual([photoA]);
});
test('synthetic mounted assignment removal clears immediately on the next confirmed list', async ({ page }) => {
  const h = await mount(page); await card(page, 'SYNTHETIC-BEFORE-A').click(); await expect(beforeImage(page)).toBeVisible(); const old = await beforeImage(page).getAttribute('src');
  h.setRows(h.rows().filter(row => row.id !== ids.order)); await page.getByRole('button', { name: 'Обновить', exact: true }).click();
  await expect(beforeImage(page)).toHaveCount(0); expect((await urls(page)).revoked).toContain(old);
});
test('synthetic mounted logout start hides photos before its delayed result', async ({ page }) => {
  const h = await mount(page); await card(page, 'SYNTHETIC-BEFORE-A').click(); await expect(beforeImage(page)).toBeVisible(); const old = await beforeImage(page).getAttribute('src');
  page.once('dialog', dialog => void dialog.accept()); await page.getByRole('button', { name: 'Выйти', exact: true }).click();
  await expect(beforeImage(page)).toHaveCount(0); expect((await urls(page)).revoked).toContain(old); h.logoutGate.resolve();
  await expect(page.getByRole('heading', { name: 'Войдите в систему', exact: true })).toBeVisible();
});
test('synthetic mounted repeated retry clicks create one bounded read attempt', async ({ page }) => {
  const h = await mount(page, 'retry'); await card(page, 'SYNTHETIC-BEFORE-A').click();
  const retry = page.getByRole('button', { name: 'Повторить загрузку фото до выполнения', exact: true }); await expect(retry).toBeVisible();
  await retry.evaluate(button => { (button as HTMLButtonElement).click(); (button as HTMLButtonElement).click(); });
  await expect(beforeImage(page)).toBeVisible(); expect(h.stats.reads).toEqual([photoA, photoA]);
});
