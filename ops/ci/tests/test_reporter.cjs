const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const Reporter = require('../safe-reporter.cjs');

test('reporter exports IDs/counts, never raw output/errors/credentials/attachments', () => {
  const privateDir = fs.mkdtempSync(path.join(os.tmpdir(), 'dalaai-reporter-'));
  process.env.DALA_CI_PRIVATE_DIR = privateDir;
  try {
    const reporter = new Reporter();
    reporter.onBegin({}, { allTests: () => [{}, {}] });
    reporter.onStdOut('private-pin-value');
    reporter.onStdErr('private-session-token');
    reporter.onError(new Error('private-cookie-value'));
    reporter.onTestEnd({ title: 'C-110-HERO title private-pin-value', expectedStatus: 'passed', location: { line: 7 } }, {
      status: 'passed', retry: 0, duration: 15,
      error: { message: 'private-session-token' }, attachments: [{ body: 'private-cookie-value' }],
    });
    reporter.onEnd({ status: 'failed' });
    const text = fs.readFileSync(path.join(privateDir, 'safe-results.json'), 'utf8');
    assert.equal(text.includes('private-'), false);
    const data = JSON.parse(text);
    assert.equal(data.errors, 1);
    assert.deepEqual(data.results[0].ids, ['C-110-HERO']);
    assert.equal(reporter.printsToStdio(), false);
    assert.equal(fs.statSync(path.join(privateDir, 'safe-results.json')).mode & 0o777, 0o600);
  } finally {
    fs.rmSync(privateDir, { recursive: true });
    delete process.env.DALA_CI_PRIVATE_DIR;
  }
});
