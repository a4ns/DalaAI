import { expect, test } from '@playwright/test';

// Actual React shell with an explicitly synthetic invalid API response, not integration.
// HTTP 200 avoids expected browser HTTP-error console noise; the client must reject the body.
test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/**', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{"synthetic":"unavailable-api"}' }));
});
test('synthetic unavailable API: RU shell at the configured viewport has a main landmark, no overflow or runtime console errors', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.goto('/');
  await expect(page.locator('html')).toHaveAttribute('lang', 'ru');
  await expect(page.getByRole('heading', { name: 'НарядAI', exact: true })).toBeVisible();
  await expect(page.getByRole('main')).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Основная навигация' })).toBeVisible();
  const overflow = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  expect(overflow.scroll).toBeLessThanOrEqual(overflow.viewport);
  const browserFacts = await page.evaluate(() => ({ userAgent: navigator.userAgent, touchPoints: navigator.maxTouchPoints, pixelRatio: devicePixelRatio, innerWidth }));
  await testInfo.attach('browser-emulation-observation', { body: JSON.stringify({ project: testInfo.project.name, viewport: page.viewportSize(), ...browserFacts, physicalDevice: false }), contentType: 'application/json' });
  if (testInfo.project.name === 'android-emulation-pixel-9') {
    expect(browserFacts.userAgent).toContain('Android');
    expect(browserFacts.touchPoints).toBeGreaterThan(0);
    expect(browserFacts.pixelRatio).toBe(3);
    expect(browserFacts.innerWidth).toBe(360);
  }
  expect(errors, 'Errors are not suppressed, including failed resource loads.').toEqual([]);
  await page.screenshot({ path: testInfo.outputPath(`synthetic-unavailable-api-${testInfo.project.name}.png`), fullPage: true });
});

test('keyboard skip link reaches main and navigation survives repeated activation', async ({ page }) => {
  await page.goto('/');
  await page.keyboard.press('Tab');
  await expect(page.getByRole('link', { name: 'Перейти к содержимому' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('main')).toBeFocused();
  const executor = page.getByRole('button', { name: 'Исполнение', exact: true });
  await executor.focus();
  await page.keyboard.press('Enter');
  await page.keyboard.press('Enter');
  await expect(executor).toHaveAttribute('aria-current', 'page');
  await expect(page.getByRole('heading', { name: 'Исполнение', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Наряды', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Наряды', exact: true })).toBeVisible();
});

test('synthetic unavailable API is distinct from empty orders or successful login', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Войдите в систему' })).toBeVisible();
  await expect(page.getByRole('alert')).toContainText('не соответствует согласованному контракту');
  await expect(page.getByText(/Нарядов пока нет|Наряд успешно выдан|ИИ подтвердил|Уведомление доставлено/i)).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Войти', exact: true })).toBeVisible();
});
