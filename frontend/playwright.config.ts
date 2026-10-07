import { defineConfig } from '@playwright/test';
const root = process.cwd();
const port = Number(process.env.UI_TEST_PORT ?? 4176);
const nodeOnly = process.env.UI_TEST_NO_SERVER === '1';
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;

export default defineConfig({
  testDir: './tests',
  testIgnore: '**/.artifacts/**',
  outputDir: './tests/.artifacts/results',
  forbidOnly: Boolean(process.env.CI),
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 5_000 },
  reporter: [['list'], ['json', { outputFile: './tests/.artifacts/results.json' }]],
  metadata: {
    evidenceLevel: 'local synthetic UI and independent source tests; not API/DB or Android acceptance',
    reviewedSha: process.env.UI_REVIEW_SHA ?? 'UNRECORDED',
  },
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    locale: 'ru-RU',
    timezoneId: 'Asia/Almaty',
    viewport: { width: 390, height: 844 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    serviceWorkers: 'block',
    launchOptions: executablePath ? { executablePath } : {},
  },
  projects: [
    { name: 'independent-source', testMatch: 'node/**/*.spec.ts' },
    { name: 'chromium-390', testMatch: 'browser/**/*.spec.ts', use: { browserName: 'chromium' } },
  ],
  webServer: nodeOnly ? undefined : {
    command: `npm run dev -- --port ${port}`,
    cwd: process.env.UI_REVIEW_ROOT ?? root,
    url: `http://127.0.0.1:${port}`,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
