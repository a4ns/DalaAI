import { expect, test } from '@playwright/test';
import { result, session } from '../support/synthetic';

test('synthetic auth: repeated login submits once and failed response returns to safe form', async ({ page }) => {
  let release!: () => void;
  const blocked = new Promise<void>(resolve => { release = resolve; });
  let logins = 0;
  await page.route('**/api/v1/**', async route => {
    if (route.request().url().endsWith('/auth/login')) { logins += 1; await blocked; }
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{"synthetic":"invalid-response"}' });
  });
  await page.goto('/');
  await page.getByRole('textbox', { name: 'Табельный код' }).fill('SYNTHETIC-UI-TEST');
  await page.getByLabel('PIN', { exact: true }).fill('0000');
  await page.getByRole('button', { name: 'Войти', exact: true }).evaluate(button => { (button as HTMLButtonElement).click(); (button as HTMLButtonElement).click(); });
  await expect.poll(() => logins).toBe(1);
  await expect(page.getByRole('textbox', { name: 'Табельный код' })).toBeDisabled();
  release();
  await expect(page.getByRole('heading', { name: 'Войдите в систему' })).toBeVisible();
  await expect(page.getByLabel('PIN', { exact: true })).toHaveValue('');
  await expect(page.getByRole('button', { name: 'Войти', exact: true })).toBeEnabled();
});

test('synthetic expired identity hides the prior order snapshot immediately', async ({ page }, info) => {
  let expired = false;
  const managerSession = session();
  managerSession.principal.role = 'manager';
  await page.route('**/api/v1/**', async route => {
    const url = route.request().url();
    if (url.endsWith('/me')) return route.fulfill({ json: managerSession });
    if (url.includes('/orders')) {
      if (expired) return route.fulfill({ status: 401, json: {} });
      return route.fulfill({ json: { items: [result().order], next_cursor: null } });
    }
    return route.fulfill({ status: 404, json: {} });
  });
  await page.goto('/');
  await expect(page.getByText('Наряд № SYNTHETIC-001').first()).toBeVisible();
  expired = true;
  // The app's existing read polling observes expiry; avoid racing its refresh button.
  await expect(page.getByRole('heading', { name: 'Войдите в систему' })).toBeVisible({ timeout: 8_000 });
  await expect(page.getByText('Наряд № SYNTHETIC-001')).toHaveCount(0);
  await expect(page.getByText('SYNTHETIC-UI-TEST', { exact: false })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('synthetic-expired-identity.png'), fullPage: true });
});
