'use strict';
// A5-only launcher: raw browser output and PDF never leave a private temp tree.
const fs = require('node:fs'), os = require('node:os'), path = require('node:path'), { spawnSync } = require('node:child_process');
const { createRequire } = require('node:module'), k = require('./contract.cjs'), p = require('./proof.cjs'), o = require('./observations.cjs');
function main() {
  let directory;
  try {
    const proof = p.requireProof(), run = k.validatePublic(), destination = process.env.DALA_BCP_SAFE_RESULT;
    k.check(path.isAbsolute(destination || '') && !['DALA_E2E_MASTER_PIN_FILE','DALA_E2E_EXECUTOR_PIN_FILE','DALA_E2E_FIXTURE_FILE','DALA_BCP_PREFLIGHT_RECEIPT'].some(key=>process.env[key]===destination), 'SAFE_RESULT_DESTINATION');
    const root = process.env.DALA_BCP_PLAYWRIGHT_PACKAGE || path.dirname(require.resolve('@playwright/test/package.json'));
    const pw = createRequire(path.join(root,'package.json')); k.check(path.isAbsolute(root) && pw('./package.json').name === '@playwright/test' && pw('./package.json').version === '1.63.0','LOCKED_PLAYWRIGHT');
    directory = fs.mkdtempSync(path.join(os.tmpdir(),'bcp-run-private-')); fs.chmodSync(directory,0o700);
    const child = spawnSync(process.execPath,[path.join(root,'cli.js'),'test','--config',path.join(__dirname,'runner.config.cjs')],
      {env:{...process.env,DALA_BCP_PRIVATE_OUTPUT:directory},timeout:300000,maxBuffer:4*1024*1024});
    k.check(!child.error && !child.signal,'BOUNDED_RUNNER');
    const filename = path.join(directory,'safe-evidence.json'), stat=fs.lstatSync(filename); k.check(stat.isFile()&&!stat.isSymbolicLink()&&stat.size<32768,'BOUNDED_EVIDENCE');
    const e = JSON.parse(fs.readFileSync(filename));
    k.check(e.scope==='INSTRUMENTED_DIAGNOSTIC_ONLY'&&e.c113_acceptance==='NOT_ESTABLISHED'&&e.source_sha===proof.source_sha&&e.run_id===run&&['DIAGNOSTIC_COMPLETE','INCONCLUSIVE','BLOCKED'].includes(e.status),'EXPERIMENT_BINDING');
    o.validateEvidence(e,proof);
    k.check(p.sourceSha()===proof.source_sha&&JSON.stringify(p.fingerprint())===JSON.stringify(proof.source_files),'SOURCE_UNCHANGED');
    // Only source-owned fixed projections. Never attach child stdout/report/PDF.
    fs.writeFileSync(destination,JSON.stringify(e,null,2)+'\n',{flag:'wx',mode:0o600});
    process.stdout.write(JSON.stringify({status:e.status,scope:e.scope,c113_acceptance:e.c113_acceptance,interpretation:e.interpretation})+'\n');
    return child.status===0&&e.status!=='BLOCKED'?0:2;
  } catch { process.stdout.write('{"status":"BLOCKED","code":"BODY_PROBE_DIAGNOSTIC_UNAVAILABLE","c113_acceptance":"NOT_ESTABLISHED"}\n'); return 2; }
  finally { if(directory)fs.rmSync(directory,{recursive:true,force:true}); }
}
if(require.main===module)process.exitCode=main();
module.exports={main};
