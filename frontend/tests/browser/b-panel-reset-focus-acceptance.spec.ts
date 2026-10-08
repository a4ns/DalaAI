import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

// Actual React layout effects and Chromium focus/scroll, with synthetic props only.
// This fixture is served by the existing Vite dev test server, not the production
// bundle. It does not establish App routing, API/DB authorization, or screen-reader
// or physical Android behavior. The focus observer calls the native implementation.
type FocusProbe = { calls: { preventScroll: boolean; connected: boolean }[]; events: number };
type ProbedWindow = Window & { panelResetFocusProbe: FocusProbe };
const search = (page: Page) => page.getByRole('searchbox', { name: 'Поиск в загруженных нарядах', exact: true });
const reset = (page: Page) => page.getByRole('button', { name: 'Сбросить фильтры', exact: true });
const history = (page: Page) => page.getByRole('region', { name: 'История изменений', exact: true });

async function mount(page: Page) {
  await page.addInitScript(() => {
    const probe: FocusProbe = { calls: [], events: 0 };
    (window as unknown as ProbedWindow).panelResetFocusProbe = probe;
    const nativeFocus = HTMLElement.prototype.focus;
    HTMLElement.prototype.focus = function (options?: FocusOptions) {
      if (this.matches('input[type="search"]')) probe.calls.push({ preventScroll: options?.preventScroll === true, connected: this.isConnected });
      nativeFocus.call(this, options);
    };
    document.addEventListener('focusin', event => {
      if (event.target instanceof HTMLInputElement && event.target.type === 'search') probe.events++;
    });
  });
  await page.goto('/tests/fixtures/panel-reset-focus.html');
  await expect(page.getByText('СИНТЕТИЧЕСКИЙ UI-ТЕСТ ФОКУСА.', { exact: false })).toBeVisible();
  await expect(search(page)).toBeVisible();
}
async function clearProbe(page: Page) {
  await page.evaluate(() => { const probe = (window as unknown as ProbedWindow).panelResetFocusProbe; probe.calls.length = 0; probe.events = 0; });
}
async function probe(page: Page) {
  return page.evaluate(() => (window as unknown as ProbedWindow).panelResetFocusProbe);
}
async function activeFilters(page: Page) {
  await search(page).fill('SYNTHETIC');
  await page.getByRole('combobox', { name: 'Статус', exact: true }).selectOption('accepted');
  await page.getByRole('checkbox', { name: 'Только с истёкшим сроком', exact: true }).check();
  await expect(reset(page)).toBeVisible();
}
async function pollCycle(page: Page) {
  const start = Number(await page.getByTestId('poll-tick').textContent());
  for (const offset of [1, 2]) {
    // A native programmatic click advances synthetic props without moving focus.
    await page.getByTestId('poll').evaluate(button => (button as HTMLButtonElement).click());
    await expect(page.getByTestId('poll-tick')).toHaveText(String(start + offset));
    await expect(page.locator('.panel-orders')).toHaveAttribute('aria-busy', offset === 1 ? 'true' : 'false');
  }
}
async function focusedReset(page: Page) {
  await reset(page).focus();
  await expect(reset(page)).toBeFocused();
  await clearProbe(page);
  await page.keyboard.press('Enter');
}
async function filtersCleared(page: Page) {
  await expect(reset(page)).toHaveCount(0);
  await expect(search(page)).toHaveValue('');
  await expect(page.getByRole('combobox', { name: 'Статус', exact: true })).toHaveValue('all');
  await expect(page.getByRole('checkbox', { name: 'Только с истёкшим сроком', exact: true })).not.toBeChecked();
}

for (const viewport of [{ width: 320, height: 800 }, { width: 390, height: 844 }, { width: 768, height: 1024 }]) {
  test.describe(`synthetic Panel reset focus ${viewport.width}x${viewport.height}`, () => {
    test.use({ viewport });

    test('focused keyboard Reset unmounts, restores native search focus once without scrolling, and never replays on polls', async ({ page }) => {
      await mount(page); await activeFilters(page);
      await reset(page).focus(); await expect(reset(page)).toBeFocused();
      const removedButton = await reset(page).elementHandle();
      // Keep keyboard focus on Reset but move the viewport away. Restoration must
      // not scroll back to the search field, even when that field is offscreen.
      const before = await page.evaluate(async () => {
        window.scrollTo(0, document.documentElement.scrollHeight - window.innerHeight - 300);
        await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
        return { x: window.scrollX, y: window.scrollY };
      });
      expect(before.y).toBeGreaterThan(0); await expect(reset(page)).toBeFocused();
      await clearProbe(page); await page.keyboard.press('Enter');
      await filtersCleared(page); await expect(search(page)).toBeFocused();
      expect(await removedButton!.evaluate(button => button.isConnected)).toBe(false);
      expect(await page.evaluate(() => ({ x: window.scrollX, y: window.scrollY }))).toEqual(before);
      expect(await probe(page)).toEqual({ calls: [{ preventScroll: true, connected: true }], events: 1 });
      await page.getByTestId('sentinel').focus();
      await pollCycle(page); await pollCycle(page);
      await expect(page.getByTestId('sentinel')).toBeFocused();
      expect(await probe(page)).toEqual({ calls: [{ preventScroll: true, connected: true }], events: 1 });
    });

    test('filter changes, ordinary polls, and an unfocused reset do not request search focus', async ({ page }) => {
      await mount(page); await search(page).fill('SYNTHETIC');
      await page.getByTestId('sentinel').focus(); await clearProbe(page);
      await pollCycle(page); await expect(page.getByTestId('sentinel')).toBeFocused();
      expect(await probe(page)).toEqual({ calls: [], events: 0 });
      const status = page.getByRole('combobox', { name: 'Статус', exact: true });
      await status.focus(); await status.selectOption('accepted');
      await expect(status).toBeFocused(); expect(await probe(page)).toEqual({ calls: [], events: 0 });
      await page.getByTestId('sentinel').focus();
      await reset(page).evaluate(button => (button as HTMLButtonElement).click());
      await filtersCleared(page); await expect(page.getByTestId('sentinel')).toBeFocused();
      await pollCycle(page); await expect(page.getByTestId('sentinel')).toBeFocused();
      expect(await probe(page)).toEqual({ calls: [], events: 0 });
    });

    test('newer focus in the reset event is preserved and the consumed request stays dead on polling', async ({ page }) => {
      await mount(page); await activeFilters(page);
      await page.getByTestId('interruption').selectOption('move-focus'); await focusedReset(page);
      await filtersCleared(page); await expect(page.getByTestId('sentinel')).toBeFocused();
      expect(await probe(page)).toEqual({ calls: [], events: 0 });
      await pollCycle(page); await expect(page.getByTestId('sentinel')).toBeFocused();
      expect(await probe(page)).toEqual({ calls: [], events: 0 });
    });

    test('access loss in the reset event removes the search and cannot revive its pending focus after access returns', async ({ page }) => {
      await mount(page); await activeFilters(page);
      await page.getByTestId('interruption').selectOption('lose-access'); await focusedReset(page);
      await expect(page.getByRole('alert')).toHaveText('Нет доступа к этой панели. Данные скрыты.');
      await expect(search(page)).toHaveCount(0); expect(await probe(page)).toEqual({ calls: [], events: 0 });
      await page.getByTestId('restore').click(); await filtersCleared(page);
      await expect(page.getByTestId('restore')).toBeFocused();
      await pollCycle(page); await expect(page.getByTestId('restore')).toBeFocused();
      expect(await probe(page)).toEqual({ calls: [], events: 0 });
    });

    test('navigation unmount in the reset event drops the request and remount does not steal focus', async ({ page }) => {
      await mount(page); await activeFilters(page);
      await page.getByTestId('interruption').selectOption('unmount'); await focusedReset(page);
      await expect(page.getByRole('heading', { name: 'Синтетическая панель закрыта', exact: true })).toBeVisible();
      await expect(search(page)).toHaveCount(0); expect(await probe(page)).toEqual({ calls: [], events: 0 });
      await page.getByTestId('restore').click(); await filtersCleared(page);
      await expect(page.getByTestId('restore')).toBeFocused();
      await pollCycle(page); await expect(page.getByTestId('restore')).toBeFocused();
      expect(await probe(page)).toEqual({ calls: [], events: 0 });
    });

    test('newer selected-order navigation owns history focus with no transient search restoration', async ({ page }) => {
      await mount(page); await activeFilters(page);
      await page.getByTestId('interruption').selectOption('select-order'); await focusedReset(page);
      await filtersCleared(page); await expect(history(page)).toBeFocused();
      await expect(history(page).getByRole('heading', { name: 'Наряд № SYNTHETIC-PANEL-B', exact: true })).toBeVisible();
      expect(await probe(page)).toEqual({ calls: [], events: 0 });
      await pollCycle(page); await expect(history(page)).toBeFocused();
      expect(await probe(page)).toEqual({ calls: [], events: 0 });
    });
  });
}
