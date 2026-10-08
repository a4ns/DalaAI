import { expect, test } from '@playwright/test';
import type { Page, TestInfo } from '@playwright/test';

/**
 * 33 browser cases: 18 healthy geometry, 9 negative feedback, 3 empty-history,
 * 3 receipt/version cases. Actual React components with synthetic props only.
 * Run ONLY chromium-390 for the declared matrix; the spec sets/asserts all sizes.
 * cd frontend && UI_REVIEW_SHA=<product SHA> npm run test:ui -- \
 *   tests/browser/quiet-refresh-geometry.spec.ts --project=chromium-390
 * No polling-store, API/DB, network timing, physical Android, or live-device claim.
 * The labelled fixture tail provides nonzero scroll even for short empty screens.
 */
const viewports = [{ width: 320, height: 800 }, { width: 390, height: 844 }, { width: 768, height: 1024 }] as const;
const screens = ['master', 'executor', 'panel'] as const;
type Screen = typeof screens[number];
type Content = 'populated' | 'empty' | 'history-empty';
const emptyText = {
  master: 'Сейчас нет результатов на проверке.', executor: 'Назначенных нарядов нет', panel: 'Доступных нарядов нет',
};
const waitText = 'Обновляемый статус ещё не получен.';
const failuresByPage = new WeakMap<Page, string[]>();
const tolerance = 0.25; // CSS px, smaller than a visible one-pixel shift.

async function settle(page: Page) {
  await page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
  });
}
async function phase(page: Page, value: string, cycle = 0) {
  // No locator click or scrollIntoView: the driver itself must never move the viewport.
  await page.evaluate(detail => window.dispatchEvent(new CustomEvent('synthetic-quiet-refresh', { detail })), { phase: value, cycle });
  await expect(page.getByTestId('fixture-state')).toHaveAttribute('data-phase', value);
  await expect(page.getByTestId('fixture-state')).toHaveAttribute('data-cycle', String(cycle));
  await settle(page);
}
async function mount(page: Page, screen: Screen, content: Content, receipt = 'none') {
  await page.goto(`/tests/fixtures/quiet-refresh-geometry.html?screen=${screen}&content=${content}&receipt=${receipt}`);
  await expect(page.getByTestId('product-screen').locator(':scope > section')).toHaveCount(1);
  await expect(page.getByTestId('fixture-state')).toHaveAttribute('data-phase', 'ready');
  await expect(page.getByLabel('Синтетическая проверка', { exact: true })).toContainText('Без API, БД и физического устройства');
  await settle(page);
}
async function geometry(page: Page) {
  return page.getByTestId('product-screen').evaluate(root => ({
    scrollX: window.scrollX, scrollY: window.scrollY,
    documentWidth: document.documentElement.scrollWidth, documentHeight: document.documentElement.scrollHeight,
    nodes: [root, ...root.querySelectorAll('*')].map((node, index) => {
      const rect = node.getBoundingClientRect();
      return { key: `${index}:${node.tagName}:${node.id}:${node.className}`,
        x: rect.x, y: rect.y, width: rect.width, height: rect.height,
        documentX: rect.x + window.scrollX, documentY: rect.y + window.scrollY };
    }),
  }));
}
type Geometry = Awaited<ReturnType<typeof geometry>>;
function unchanged(before: Geometry, after: Geometry, label: string) {
  expect(after.nodes.map(node => node.key), `${label}: retained DOM structure`).toEqual(before.nodes.map(node => node.key));
  let maximumDelta = 0;
  for (const key of ['scrollX', 'scrollY', 'documentWidth', 'documentHeight'] as const) {
    expect(Math.abs(after[key] - before[key]), `${label}: ${key}`).toBeLessThanOrEqual(tolerance);
  }
  for (let index = 0; index < before.nodes.length; index++) {
    for (const key of ['x', 'y', 'width', 'height', 'documentX', 'documentY'] as const) {
      const delta = Math.abs(after.nodes[index][key] - before.nodes[index][key]);
      maximumDelta = Math.max(maximumDelta, delta);
      expect(delta, `${label}: element ${index} ${key}`).toBeLessThanOrEqual(tolerance);
    }
  }
  return maximumDelta;
}
async function scrollBaseline(page: Page) {
  await page.evaluate(() => window.scrollTo({ top: 173, left: 0, behavior: 'instant' }));
  await settle(page);
  const baseline = await geometry(page);
  expect(baseline.scrollY, 'nonzero scroll is required, including empty states').toBe(173);
  expect(baseline.documentWidth).toBeLessThanOrEqual((page.viewportSize()!).width);
  return baseline;
}
async function guards(page: Page, screen: Screen, content: Content, blocked: boolean) {
  const root = page.getByTestId('product-screen');
  if (screen === 'master') {
    const actions = [root.getByRole('button', { name: 'Выдать наряд', exact: true })];
    if (content !== 'empty' && await root.getByRole('button', { name: 'Принять и закрыть', exact: true }).count()) {
      actions.push(root.getByRole('button', { name: 'Принять и закрыть', exact: true }), root.getByRole('button', { name: 'Вернуть на доработку', exact: true }));
    }
    for (const action of actions) {
      if (blocked) await expect(action).toBeDisabled(); else await expect(action).toBeEnabled();
    }
  }
  if (screen === 'executor' && content !== 'empty') {
    for (const name of ['Приостановить', 'Отправить на проверку']) {
      const action = root.getByRole('button', { name, exact: true });
      // During the initial null snapshot the detail and its actions must be absent.
      if (await page.getByTestId('fixture-state').getAttribute('data-phase') === 'initial') await expect(action).toHaveCount(0);
      else if (blocked) await expect(action).toBeDisabled(); else await expect(action).toBeEnabled();
    }
  }
  if (blocked && screen !== 'panel') {
    // Also dispatch submit directly: disabled styling alone is not a mutation guard.
    await root.locator('form').evaluateAll(forms => forms.forEach(form => form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))));
  }
  await expect(page.getByTestId('fixture-state')).toHaveText('0:0');
}
async function healthy(page: Page, screen: Screen, content: Content, info: TestInfo, receipt = 'none') {
  await mount(page, screen, content, receipt);
  if (content === 'empty') await expect(page.getByText(emptyText[screen], { exact: true })).toBeVisible();
  if (content === 'history-empty') {
    await expect(page.getByText('В загруженной истории событий нет.', { exact: true })).toBeVisible();
    await expect(page.getByText('В загруженном справочнике нет доступных исполнителей.', { exact: true })).toBeVisible();
  }
  await guards(page, screen, content, false);
  const before = await scrollBaseline(page);
  const deltas: number[] = [];
  for (let cycle = 1; cycle <= 3; cycle++) {
    await phase(page, 'polling', cycle - 1);
    if (content === 'empty') await expect(page.getByText(emptyText[screen], { exact: true })).toBeVisible();
    if (screen === 'panel') {
      await expect(page.getByRole('button', { name: 'Обновить данные', exact: true })).toBeDisabled();
      if (content !== 'empty') await expect(page.getByRole('button', { name: 'Обновить историю', exact: true })).toBeDisabled();
      await expect(page.locator('.panel-orders')).toHaveAttribute('aria-busy', 'true');
      await expect(page.locator('.panel-notice--caution')).toHaveCount(0);
    }
    if (receipt === 'observed') await expect(page.getByText(waitText, { exact: false })).toHaveCount(0);
    await guards(page, screen, content, true);
    deltas.push(unchanged(before, await geometry(page), `poll ${cycle} loading`));
    await phase(page, 'ready', cycle);
    await guards(page, screen, content, false);
    deltas.push(unchanged(before, await geometry(page), `poll ${cycle} completed`));
  }
  await info.attach('synthetic-quiet-refresh-geometry.json', { contentType: 'application/json', body: JSON.stringify({
    evidenceLevel: 'synthetic real React rendering in Chromium; no API, DB or physical device',
    screen, content, receipt, viewport: page.viewportSize(), cycles: 3, measuredElements: before.nodes.length,
    scrollY: before.scrollY, maximumRectDeltaCssPx: Math.max(...deltas), toleranceCssPx: tolerance,
    scrollTail: 'labelled test-only footer outside product subtree',
  }) });
}

for (const viewport of viewports) {
  test.describe(`synthetic quiet refresh ${viewport.width}x${viewport.height}`, () => {
    test.use({ viewport, deviceScaleFactor: 1, isMobile: false, hasTouch: false });
    test.beforeEach(async ({ page, browserName }) => {
      expect(browserName).toBe('chromium');
      const failures: string[] = [];
      page.on('pageerror', () => failures.push('browser-page-error'));
      page.on('console', message => { if (message.type() === 'error') failures.push('browser-console-error'); });
      await page.route('**/api/**', route => { failures.push('unexpected-api-request'); return route.abort(); });
      // The page contains only public synthetic inputs; fail if it attempts any API access.
      test.info().annotations.push({ type: 'evidence', description: 'synthetic component props; desktop Chromium responsive viewport; not real backend/device' });
      failuresByPage.set(page, failures);
    });
    test.afterEach(async ({ page }) => {
      expect(failuresByPage.get(page)).toEqual([]);
      if (!page.isClosed() && page.url() !== 'about:blank') {
        expect(await page.evaluate(() => ({ width: innerWidth, height: innerHeight, dpr: devicePixelRatio })))
          .toEqual({ ...viewport, dpr: 1 });
      }
    });
    for (const screen of screens) {
      for (const content of ['populated', 'empty'] as const) {
        test(`${screen} ${content}: three unchanged polls preserve all bounds and scroll`, async ({ page }, info) => {
          await healthy(page, screen, content, info);
        });
      }
      test(`${screen}: initial error offline incomplete and true stale feedback survives`, async ({ page }) => {
        for (const content of ['populated', 'empty'] as const) {
          await mount(page, screen, content);
          for (const value of ['initial', 'error', 'offline', 'unavailable', 'incomplete', 'stale', 'loading-incomplete', 'loading-error', 'loading-unconfirmed', 'loading-never']) {
            await phase(page, value);
            const root = page.getByTestId('product-screen');
            const notices = root.locator('[role="status"], [role="alert"]');
            const text = (await notices.allTextContents()).join('\n');
            if (value === 'initial') expect(text).toMatch(/Загружаем|загрузка|загружаем/);
            else if (value === 'offline') expect(text).toMatch(/Нет сети|нет сети/);
            else if (value === 'error') expect(text).toMatch(/Синтетическая ошибка|не удалось завершить/);
            else if (value === 'unavailable') expect(text).toMatch(/Не удалось|не удалось|загрузка недоступна/);
            else if (value === 'incomplete') expect(text).toMatch(/часть данных|не полностью|не все страницы/);
            else if (value === 'stale') expect(text).toMatch(/устарел|устаревшими/);
            else expect(text).toMatch(/Обновляем|загрузка|обновляем/);
            // An empty result is only promised after a complete confirmed read.
            await expect(root.getByText(emptyText[screen], { exact: true })).toHaveCount(0);
            if (screen === 'panel' && value !== 'initial' && value !== 'loading-never') await expect(root.locator('.panel-notice--caution').first()).toBeVisible();
            await guards(page, screen, content, true);
          }
          await phase(page, 'ready');
          await guards(page, screen, content, false);
          if (content === 'empty') await expect(page.getByText(emptyText[screen], { exact: true })).toBeVisible();
        }
      });
    }
    test('panel empty history and staff: three unchanged polls preserve all bounds and scroll', async ({ page }, info) => {
      await healthy(page, 'panel', 'history-empty', info);
    });
    test('executor receipt: observed version stays quiet and unobserved versions stay blocked', async ({ page }, info) => {
      await healthy(page, 'executor', 'populated', info, 'observed');
      for (const receipt of ['equal', 'older', 'missing']) {
        await mount(page, 'executor', 'populated', receipt);
        for (const value of receipt === 'missing' ? ['polling'] : ['ready', 'polling']) {
          await phase(page, value);
          await expect(page.getByText(waitText, { exact: false })).toBeVisible();
          await guards(page, 'executor', 'populated', true);
        }
      }
    });
  });
}
