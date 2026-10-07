import { expect, test } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.goto('/tests/fixtures/master.html');
  await expect(page.getByText('СИНТЕТИЧЕСКИЙ UI-ТЕСТ.', { exact: false })).toBeVisible();
});

test('synthetic master: unknown result retains draft, blocks changes and replays only original action', async ({ page }) => {
  await page.getByRole('textbox', { name: 'Задача или неисправность' }).fill('Исходная синтетическая задача');
  await page.getByRole('button', { name: 'Выдать наряд', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Задача или неисправность' })).toBeDisabled();
  await page.getByRole('button', { name: 'Проверить повтором той же операции' }).click();
  await expect(page.getByTestId('calls')).toHaveText('1');
  await expect(page.getByTestId('retries')).toHaveText('1');
  await expect(page.getByRole('textbox', { name: 'Задача или неисправность' })).toHaveValue('Исходная синтетическая задача');
});

test('synthetic master:409 needs new snapshot and explicit resolution without losing draft', async ({ page }) => {
  await page.getByTestId('outcome').selectOption('conflict');
  await page.getByRole('button', { name: 'Выдать наряд', exact: true }).click();
  const resume = page.getByRole('button', { name: 'Продолжить с обновлёнными данными' });
  await expect(resume).toBeDisabled();
  await page.getByRole('button', { name: 'Обновить данные', exact: true }).click();
  await expect(resume).toBeEnabled();
  await resume.click();
  await expect(page.getByRole('textbox', { name: 'Задача или неисправность' })).toHaveValue('Синтетическая задача');
  await expect(page.getByTestId('calls')).toHaveText('1');
});

test('synthetic master: delayed photo cannot overwrite later typing or mutate an unresolved draft', async ({ page }) => {
  await page.getByTestId('start-photo').click();
  await page.getByRole('textbox', { name: 'Задача или неисправность' }).fill('Новое описание, которое нельзя потерять');
  await page.getByTestId('complete-photo').click();
  await expect(page.getByRole('textbox', { name: 'Задача или неисправность' })).toHaveValue('Новое описание, которое нельзя потерять');
  await page.getByTestId('start-photo').click();
  await page.getByRole('button', { name: 'Выдать наряд', exact: true }).click();
  const frozen = await page.getByTestId('draft').textContent();
  await page.getByTestId('complete-photo').click();
  await expect(page.getByTestId('draft')).toHaveText(frozen!);
  await page.getByTestId('switch-identity').click();
  await page.getByTestId('complete-photo').click();
  await expect(page.getByTestId('draft')).not.toContainText('synthetic-confirmed-photo');
});
