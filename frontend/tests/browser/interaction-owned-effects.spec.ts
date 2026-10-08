import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

declare global {
  interface Window {
    __ownedEffects: {
      scrolls: { target: 'operation' | 'detail' | 'other'; block: string | null }[];
      holdBitmaps: boolean; bitmapAvailable: boolean; bitmapGates: (() => void)[];
    };
  }
}
const viewports = [{ width: 320, height: 800 }, { width: 390, height: 844 }, { width: 768, height: 1024 }];
const settled = (page: Page) => page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
const operationScrolls = (page: Page) => page.evaluate(() => window.__ownedEffects.scrolls.filter(row => row.target === 'operation'));
async function imageBuffer(page: Page): Promise<Buffer> {
  const encoded = await page.evaluate(() => {
    const canvas = document.createElement('canvas'); canvas.width = 32; canvas.height = 32;
    const context = canvas.getContext('2d'); if (!context) throw new Error('Synthetic test requires Canvas2D');
    context.fillStyle = '#27856d'; context.fillRect(0, 0, 32, 32); return canvas.toDataURL('image/png').split(',')[1];
  });
  return Buffer.from(encoded, 'base64');
}
for (const viewport of viewports) test.describe(`owned effects ${viewport.width}x${viewport.height}`, () => {
  test.use({ viewport, isMobile: false, hasTouch: false, deviceScaleFactor: 1 });
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      window.__ownedEffects = { scrolls: [], holdBitmaps: false, bitmapAvailable: typeof createImageBitmap === 'function', bitmapGates: [] };
      // Observe the actual browser call and delegate to it. Never suppress scrolling.
      const nativeScroll = Element.prototype.scrollIntoView;
      Element.prototype.scrollIntoView = function(options?: boolean | ScrollIntoViewOptions) {
        const target = this.classList.contains('executor-operation') ? 'operation' : this.classList.contains('executor-detail-title') ? 'detail' : 'other';
        window.__ownedEffects.scrolls.push({ target, block: typeof options === 'object' ? options.block ?? null : null });
        return nativeScroll.call(this, options);
      };
      // Hold only the asynchronous boundary; after release use the native decoder.
      // This makes cancellation deterministic without replacing preparePhoto/output.
      const nativeBitmap = globalThis.createImageBitmap;
      if (typeof nativeBitmap === 'function') globalThis.createImageBitmap = (async (...args: unknown[]) => {
        if (window.__ownedEffects.holdBitmaps) await new Promise<void>(resolve => window.__ownedEffects.bitmapGates.push(resolve));
        return Reflect.apply(nativeBitmap, globalThis, args) as Promise<ImageBitmap>;
      }) as typeof createImageBitmap;
    });
    await page.goto('/tests/fixtures/interaction-owned-effects.html');
    await expect(page.getByText('СИНТЕТИЧЕСКИЙ ТЕСТ реальных компонентов.', { exact: false })).toBeVisible();
    expect(page.viewportSize()).toEqual(viewport);
    await settled(page);
  });

  test('explicit command owns one feedback scroll; its late result and a poll own none', async ({ page }) => {
    expect(await operationScrolls(page)).toHaveLength(0);
    await page.getByRole('button', { name: 'Принять', exact: true }).click();
    await expect.poll(() => operationScrolls(page)).toEqual([{ target: 'operation', block: 'start' }]);
    await expect(page.locator('.executor-operation')).toBeInViewport();
    await expect(page.getByTestId('command-count')).toHaveText('1');
    await page.getByTestId('resolve-confirmed').click();
    await expect(page.locator('.executor-operation')).toContainText('Действие подтверждено сервером.');
    await settled(page); expect(await operationScrolls(page)).toHaveLength(1);
    await page.getByTestId('poll').click(); await settled(page); expect(await operationScrolls(page)).toHaveLength(1);
  });

  test('explicit retry owns exactly one additional scroll and no fresh command', async ({ page }) => {
    await page.getByRole('button', { name: 'Принять', exact: true }).click();
    await expect.poll(() => operationScrolls(page)).toHaveLength(1);
    await page.getByTestId('resolve-unknown').click();
    await expect(page.getByRole('button', { name: 'Повторить исходное действие', exact: true })).toBeVisible();
    await settled(page); expect(await operationScrolls(page)).toHaveLength(1);
    await page.getByRole('button', { name: 'Повторить исходное действие', exact: true }).click();
    await expect.poll(() => operationScrolls(page)).toHaveLength(2);
    await expect(page.getByTestId('command-count')).toHaveText('1'); await expect(page.getByTestId('retry-count')).toHaveText('1');
    await page.getByTestId('resolve-confirmed').click(); await expect(page.locator('.executor-operation')).toContainText('Действие подтверждено сервером.');
    await settled(page); expect(await operationScrolls(page)).toHaveLength(2);
  });

  test('late result from a different selected scope and confirmation from polling cannot scroll', async ({ page }) => {
    await page.getByRole('button', { name: 'Принять', exact: true }).click(); await expect.poll(() => operationScrolls(page)).toHaveLength(1);
    await page.getByRole('navigation', { name: 'Назначенные наряды', exact: true }).getByRole('button', { name: /Наряд OWNED-B/ }).click();
    await expect(page.getByRole('heading', { name: 'Наряд OWNED-B', exact: true })).toBeFocused(); await settled(page);
    await page.evaluate(() => { window.__ownedEffects.scrolls = []; });
    await page.getByTestId('resolve-confirmed').click(); await settled(page);
    expect(await operationScrolls(page)).toHaveLength(0); await expect(page.locator('.executor-detail')).not.toContainText('Действие подтверждено сервером.');
    await page.getByTestId('poll-confirmed').click(); await expect(page.locator('.executor-operation')).toContainText('Действие подтверждено сервером.');
    await settled(page); expect(await operationScrolls(page)).toHaveLength(0);
  });

  test('canceling actual photo preparation announces cancellation and never adds the late decoded file', async ({ page }) => {
    expect(await page.evaluate(() => window.__ownedEffects.bitmapAvailable)).toBe(true);
    await page.evaluate(() => { window.__ownedEffects.holdBitmaps = true; });
    await page.getByLabel('Выбрать фотографии', { exact: true }).setInputFiles({ name: 'synthetic-cancel.png', mimeType: 'image/png', buffer: await imageBuffer(page) });
    await expect.poll(() => page.evaluate(() => window.__ownedEffects.bitmapGates.length)).toBe(1);
    await expect(page.getByTestId('photo-busy')).toHaveText('true');
    await page.getByTestId('disable-photos').click(); await settled(page);
    await page.evaluate(() => { window.__ownedEffects.holdBitmaps = false; window.__ownedEffects.bitmapGates.splice(0).forEach(release => release()); });
    await expect(page.locator('.photo-picker__status')).toHaveText('Подготовка отменена. Новые фото не добавлены.');
    await expect(page.getByTestId('photo-busy')).toHaveText('false'); await expect(page.getByTestId('photo-count')).toHaveText('0');
    await page.getByTestId('enable-photos').click(); await settled(page);
    await expect(page.getByTestId('photo-count')).toHaveText('0'); await expect(page.getByRole('img', { name: /^Выбранное фото:/ })).toHaveCount(0);
  });

  test('an owned keyboard deletion returns focus to file selection exactly after removal', async ({ page }) => {
    await page.getByTestId('seed-photos').click(); await expect(page.getByTestId('photo-count')).toHaveText('2');
    const remove = page.getByRole('button', { name: 'Удалить фото 1: synthetic-one.png', exact: true }); await remove.focus(); await expect(remove).toBeFocused(); await remove.press('Enter');
    await expect(page.getByTestId('photo-count')).toHaveText('1');
    await expect(page.getByRole('button', { name: 'Выбрать из файлов', exact: true })).toBeFocused();
    await expect(page.locator('.photo-picker__status')).toHaveText('Фото удалено из локального выбора.');
  });

  test('late parent deletion and an already moved focus cannot steal user attention', async ({ page }) => {
    await page.getByTestId('seed-photos').click(); await expect(page.getByTestId('photo-count')).toHaveText('2');
    await page.getByTestId('deletion-mode').selectOption('deferred');
    const remove = page.getByRole('button', { name: 'Удалить фото 1: synthetic-one.png', exact: true }); await remove.focus(); await remove.press('Enter');
    await expect(page.locator('.photo-picker__status')).toHaveText('Фото удалено из локального выбора.'); await expect(page.getByTestId('photo-count')).toHaveText('2');
    await page.getByTestId('outside-focus').focus();
    // Model a delayed parent callback, not a second user gesture granting focus.
    await page.getByTestId('apply-delayed-delete').evaluate(button => (button as HTMLButtonElement).click());
    await expect(page.getByTestId('photo-count')).toHaveText('1'); await expect(page.getByTestId('outside-focus')).toBeFocused();
    await page.getByTestId('seed-photos').click(); await expect(page.getByTestId('photo-count')).toHaveText('2');
    await page.getByTestId('deletion-mode').selectOption('redirect');
    const next = page.getByRole('button', { name: 'Удалить фото 1: synthetic-one.png', exact: true }); await next.focus(); await next.press('Enter');
    await expect(page.getByTestId('photo-count')).toHaveText('1'); await expect(page.getByTestId('outside-focus')).toBeFocused();
  });
});
