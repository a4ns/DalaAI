/* Count-only output: never publish error bodies, headers, credentials or attachments. */
const fs = require('node:fs');
const path = require('node:path');
class SafeReporter {
  constructor() { this.results = []; this.errors = 0; this.discovered = 0; }
  printsToStdio() { return false; }
  onBegin(_config, suite) { this.discovered = suite.allTests().length; }
  onStdOut() {}
  onStdErr() {}
  onError() { this.errors += 1; }
  onTestEnd(test, result) {
    // IDs are a bounded public test identifier, not arbitrary titles or messages.
    const ids = test.title.match(/\bC-110-[A-Z0-9][A-Z0-9-]{0,40}\b/g) || [];
    this.results.push({
      ids: [...new Set(ids)], status: result.status,
      expected_status: test.expectedStatus,
      retry: result.retry,
      duration_ms: result.duration,
      line: test.location.line,
    });
  }
  onEnd(result) {
    fs.writeFileSync(path.join(process.env.DALA_CI_PRIVATE_DIR, 'safe-results.json'), JSON.stringify({
      schema_version: 1, status: result.status, discovered: this.discovered,
      errors: this.errors, results: this.results,
    }, null, 2), { mode: 0o600 });
  }
}
module.exports = SafeReporter;
