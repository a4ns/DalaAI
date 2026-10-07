import { expect, test } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.goto('/tests/fixtures/index.html');
  await expect(page.getByText('СИНТЕТИЧЕСКИЙ UI-ТЕСТ.', { exact: false })).toBeVisible();
});

test('synthetic: unknown result freezes draft and retry uses the original intent', async ({ page }, info) => {
  const work = page.getByRole('textbox', { name: 'Что выполнено' });
  await work.fill('Синтетический сохранённый результат');
  await page.getByRole('button', { name: 'Отправить неполный результат на проверку' }).click();
  await expect(page.getByRole('alert')).toContainText('Результат не подтверждён');
  await expect(work).toHaveValue('Синтетический сохранённый результат');
  await expect(work).toBeDisabled();
  const captured = await page.getByTestId('intent').textContent();
  await page.getByRole('button', { name: 'Повторить исходное действие' }).click();
  await expect(page.getByTestId('calls')).toHaveText('1');
  await expect(page.getByTestId('retries')).toHaveText('1');
  await expect(page.getByTestId('intent')).toHaveText(captured!);
  await expect(work).toHaveValue('Синтетический сохранённый результат');
  await page.screenshot({ path: info.outputPath('synthetic-executor-retained-draft.png'), fullPage: true });
});

test('synthetic: 409 preserves draft and needs both refresh and explicit review', async ({ page }) => {
  await page.getByTestId('outcome').selectOption('conflict');
  const work = page.getByRole('textbox', { name: 'Что выполнено' });
  await work.fill('Черновик не должен исчезнуть при 409');
  await page.getByRole('button', { name: 'Отправить неполный результат на проверку' }).click();
  const resume = page.getByRole('button', { name: 'Состояние проверено, продолжить' });
  await expect(resume).toBeDisabled();
  await page.getByRole('button', { name: 'Загрузить актуальное состояние' }).click();
  await expect(resume).toBeEnabled();
  await expect(work).toBeDisabled();
  await resume.click();
  await expect(work).toBeEnabled();
  await expect(work).toHaveValue('Черновик не должен исчезнуть при 409');
  await expect(page.getByTestId('calls')).toHaveText('1');
});

test('synthetic: repeat click cannot submit twice and old identity completion is ignored', async ({ page }) => {
  await page.getByTestId('outcome').selectOption('pending');
  await page.getByRole('textbox', { name: 'Что выполнено' }).fill('Данные прежнего пользователя');
  const submit = page.getByRole('button', { name: 'Отправить неполный результат на проверку' });
  await submit.evaluate(button => { (button as HTMLButtonElement).click(); (button as HTMLButtonElement).click(); });
  await expect(page.getByTestId('calls')).toHaveText('1');
  await expect(submit).toBeDisabled();
  await page.getByTestId('switch-identity').click();
  await page.getByTestId('resolve-old').click();
  await expect(page.getByRole('textbox', { name: 'Что выполнено' })).toHaveValue('');
  await expect(page.getByText('Действие подтверждено сервером.', { exact: false })).toHaveCount(0);
});

test('synthetic: stale snapshot retains context and disables mutation at 390px', async ({ page }, info) => {
  await page.getByTestId('stale').click();
  await expect(page.getByText('Синтетическое оборудование').first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Отправить неполный результат на проверку' })).toBeDisabled();
  await expect(page.getByRole('alert')).toContainText('Синтетический отказ загрузки');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('synthetic-executor-stale-390.png'), fullPage: true });
});

test('synthetic: photo activity blocks submission without inventing a command, and settling it preserves unknown command lock', async ({ page }) => {
  await page.getByRole('textbox', { name: 'Что выполнено' }).fill('Синтетический результат с выбранным фото');
  const submit = page.getByRole('button', { name: 'Отправить неполный результат на проверку' });
  await page.getByTestId('photo-busy').check();
  await expect(submit).toBeDisabled();
  await page.locator('form.executor-form').evaluate(form => (form as HTMLFormElement).requestSubmit());
  await expect(page.getByTestId('calls')).toHaveText('0');
  await expect(page.getByText('Синтетическая загрузка фото не подтверждена').first()).toBeVisible();
  await page.getByTestId('photo-busy').uncheck();
  await expect(submit).toBeEnabled();
  await submit.click();
  await expect(page.getByRole('alert')).toContainText('Результат не подтверждён');
  await page.getByTestId('photo-busy').check();
  await page.getByTestId('photo-busy').uncheck();
  await expect(submit).toBeDisabled();
  await expect(page.getByTestId('calls')).toHaveText('1');
});
