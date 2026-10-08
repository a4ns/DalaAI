'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path');
const { execFileSync } = require('node:child_process');
const k = require('./contract.cjs'), p = require('./proof.cjs');
const { preflightNodeEnvironment } = require('./secrecy_preflight.cjs');

test('isolated browser locator reaches only the Node preflight driver', () => {
  const env = { PATH: '/usr/bin', HOME: '/tmp/dummy-home', LANG: 'C.UTF-8', PLAYWRIGHT_BROWSERS_PATH: '/tmp/isolated chromium',
    DALA_E2E_MASTER_PIN_FILE: '/private/not-read', DALA_BCP_OBSERVER_DATABASE_URL: 'private-not-read',
    DALA_BCP_AUTHORIZED: 'operator-provisioned-synthetic-only', DALA_C113_PREFLIGHT_RECEIPT: '/stale/not-read',
    PGPASSWORD: 'private-not-read', NODE_OPTIONS: '--require=/private/not-read', DEBUG: '*', PWDEBUG: '1',
    DALA_CI_PRIVATE: '/private/not-read' };
  assert.deepEqual(preflightNodeEnvironment(env), { PATH: env.PATH, HOME: env.HOME, LANG: env.LANG, PLAYWRIGHT_BROWSERS_PATH: env.PLAYWRIGHT_BROWSERS_PATH });
  assert.deepEqual(k.runnerUse(env).launchOptions.env, { PATH: env.PATH, HOME: env.HOME, LANG: env.LANG });
  assert(!JSON.stringify(preflightNodeEnvironment(env)).includes('private-not-read'));
});
test('absent browser locator stays absent without inheriting ambient inputs', () => {
  assert.deepEqual(preflightNodeEnvironment({ PATH: '/usr/bin', SECRET: 'not-copied' }), { PATH: '/usr/bin' });
});
for (const locator of ['', '0', 'relative/browser', '/tmp/browser\nPRIVATE', '/tmp/browser\0PRIVATE', '/' + 'a'.repeat(4096)]) {
  test('malformed or non-absolute browser locator is blocked: ' + JSON.stringify(locator).slice(0, 60), () => {
    assert.throws(() => preflightNodeEnvironment({ PLAYWRIGHT_BROWSERS_PATH: locator }), /EXPLICIT_BROWSER_LOCATOR/);
  });
}
function repository(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'bcp-source-security-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const git = args => execFileSync('git', args, { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
  git(['init', '--quiet']);
  for (const area of ['frontend', 'backend']) {
    fs.mkdirSync(path.join(root, area)); fs.writeFileSync(path.join(root, area, 'source.txt'), 'committed product bytes\n');
  }
  git(['add', '--', 'frontend', 'backend']);
  git(['-c', 'user.name=Probe source test', '-c', 'user.email=probe@example.invalid', 'commit', '--quiet', '-m', 'Synthetic product baseline']);
  return { root, git };
}
test('clean actual product index and worktree pass the read-only guard', t => {
  const { git } = repository(t); assert.doesNotThrow(() => p.assertProductWorkingTreeClean(git));
});
for (const area of ['frontend', 'backend']) {
  for (const action of ['modified', 'staged', 'deleted', 'renamed', 'untracked']) {
    test(`${area} ${action} actual product bytes reject source proof`, t => {
      const { root, git } = repository(t), file = path.join(root, area, 'source.txt');
      if (action === 'deleted') fs.unlinkSync(file);
      else if (action === 'renamed') git(['mv', '--', `${area}/source.txt`, `${area}/renamed.txt`]);
      else if (action === 'untracked') fs.writeFileSync(path.join(root, area, 'new-runtime.txt'), 'untracked runtime bytes\n');
      else {
        fs.appendFileSync(file, 'dirty runtime bytes\n');
        if (action === 'staged') git(['add', '--', `${area}/source.txt`]);
      }
      assert.throws(() => p.assertProductWorkingTreeClean(git));
      assert.notEqual(git(['status', '--porcelain', '--untracked-files=all', '--', 'frontend', 'backend']), '');
    });
  }
}
test('sourceSha always invokes the actual working-tree guard before accepting product trees', () => {
  const source = p.sourceSha.toString();
  assert(source.includes('assertProductWorkingTreeClean();'));
  assert(source.indexOf('assertProductWorkingTreeClean();') < source.indexOf("for (const tree of ['frontend', 'backend'])"));
});
