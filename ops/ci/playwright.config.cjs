/* Execute C-110-owned scenarios against the real composed app. No test doubles. */
const path = require('node:path');
const { createRequire } = require('node:module');

if (!process.env.DALA_CI_PRIVATE_DIR || !process.env.DALA_E2E_CONFIG_PATH || !process.env.DALA_E2E_PACKAGE_DIR) {
  throw new Error('Run through ops/ci/run_mobile.py');
}
const requireC = createRequire(path.join(process.env.DALA_E2E_PACKAGE_DIR, 'package.json'));
const { defineConfig, devices } = requireC('@playwright/test');
const imported = require(process.env.DALA_E2E_CONFIG_PATH);
const base = imported.default || imported;
if (base.webServer) throw new Error('C-110 must use the composed app; webServer is forbidden in CI');
const configured = base.projects || [{ name: 'android-chromium' }];
const selected = configured.find(project => project.name === process.env.DALA_E2E_PROJECT);
if (!selected) throw new Error('Required C-110 Android project absent');
if ((selected.dependencies || []).length || selected.teardown) {
  throw new Error('C-110 must include setup in its fixtures; project dependencies cannot be silently omitted');
}
const baseDir = path.dirname(process.env.DALA_E2E_CONFIG_PATH);
const testDir = path.resolve(baseDir, selected.testDir || base.testDir || '.');
const mergedUse = { ...(base.use || {}), ...(selected.use || {}) };
const launch = mergedUse.launchOptions || {};
if ((launch.args || []).length || launch.ignoreDefaultArgs || launch.executablePath) {
  throw new Error('Custom browser launch flags/binaries are not allowed in this gate');
}
module.exports = defineConfig({
  ...base,
  testDir,
  forbidOnly: true,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  repeatEach: 1,
  maxFailures: 0,
  outputDir: path.join(process.env.DALA_CI_PRIVATE_DIR, 'test-output'),
  reporter: [[path.join(__dirname, 'safe-reporter.cjs')]],
  use: {},
  projects: [{
    ...selected,
    name: 'android-chromium',
    testDir,
    dependencies: [],
    teardown: undefined,
    use: {
      ...mergedUse,
      ...devices['Pixel 7'],
      baseURL: 'https://localhost:18443',
      browserName: 'chromium',
      headless: true,
      channel: undefined,
      ignoreHTTPSErrors: false,
      launchOptions: {},
      trace: 'off',
      screenshot: 'off',
      video: 'off',
      serviceWorkers: 'allow',
    },
  }],
});
