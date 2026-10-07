/* Public health endpoint only, before the C110 process receives PIN/observer inputs. */
const path = require('node:path');
const { createRequire } = require('node:module');
async function main() {
  let browser;
  try {
    const root = process.env.DALA_C110_PLAYWRIGHT_PACKAGE;
    const pw = createRequire(path.join(root, 'package.json'))(root);
    browser = await pw.chromium.launch();
    const context = await browser.newContext({ ignoreHTTPSErrors: false, serviceWorkers: 'block' });
    const page = await context.newPage();
    const response = await page.goto('https://localhost:18443/healthz', { timeout: 15000, waitUntil: 'domcontentloaded' });
    if (response.status() !== 200 || !(await page.evaluate(() => isSecureContext))) throw new Error('HEALTH_NOT_SECURE');
    const api = await context.request.get('https://localhost:18443/healthz', { timeout: 15000 });
    if (api.status() !== 200) throw new Error('API_HEALTH_NOT_OK');
    process.stdout.write('{"status":"PASS","scope":"public_health_browser_and_node_tls_only"}\n');
    return 0;
  } catch (error) {
    const text = String(error.message || '');
    const code = text.includes('ERR_CERT_AUTHORITY_INVALID') ? 'BROWSER_CA_UNTRUSTED'
      : text.includes('ERR_CERT_COMMON_NAME_INVALID') ? 'BROWSER_CA_HOSTNAME_MISMATCH'
      : text.includes('unable to verify') || text.includes('self-signed') || text.includes('UNABLE_TO_VERIFY') ? 'NODE_CA_UNTRUSTED'
      : text.includes('ERR_CONNECTION_REFUSED') ? 'BROWSER_CONNECTION_REFUSED'
      : 'PUBLIC_TLS_HEALTH_PROBE_FAILED';
    process.stdout.write(JSON.stringify({status:'FAIL',code})+'\n');
    return 2;
  } finally { if (browser) await browser.close(); }
}
main().then(code=>process.exitCode=code).catch(()=>{process.stdout.write('{"status":"FAIL","code":"PUBLIC_TLS_HEALTH_PROBE_FAILED"}\n');process.exitCode=2;});
