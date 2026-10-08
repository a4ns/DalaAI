'use strict';
// Public synthetic loopback diagnostic. Two fixed arms, one payload GET per arm.
// No credentials, external hosts, private records, application mutations or C-source edits.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const os = require('node:os');
const crypto = require('node:crypto');
const frontend = path.resolve(process.argv[2]);
const executablePath = process.argv[3];
const { chromium, devices } = require(path.join(frontend, 'node_modules/playwright'));
const ts = require(path.join(frontend, 'node_modules/typescript'));
const source = fs.readFileSync(path.join(frontend, 'src/shared/api/client.ts'), 'utf8');
const reader = source.slice(source.indexOf('async function readBoundedJson('), source.indexOf('\nfunction authorityKey('));
if (!reader.startsWith('async function readBoundedJson(') || !reader.includes('reader.releaseLock()')) throw new Error('Expected current bounded-reader source');
const readerJs = ts.transpileModule(reader, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const bounded = async (work, label, ms = 20000) => { let timer; try { return await Promise.race([work, new Promise((_, reject) => { timer = setTimeout(() => { const error = new Error(label + ' exceeded the public diagnostic wall bound'); error.name = 'ProbeTimeout'; reject(error); }, ms); })]); } finally { clearTimeout(timer); } };
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const payload = Buffer.from(JSON.stringify({ kind: 'PUBLIC_SYNTHETIC_JSON_READER_DIAGNOSTIC', rows: Array.from({ length: 1500 }, (_, index) => ({ index, text: 'Синтетические открытые данные. Проверка чтения JSON.' })) }));
const expectedHash = sha(payload);
const counts = { text: 0, reader: 0 };
const html = `<!doctype html><meta charset="utf-8"><title>Public synthetic reader comparison</title><button id="start">Run controlled public arm</button><script>${readerJs}
window.runArm = async mode => {
 const abort = new AbortController(); const timer = setTimeout(() => abort.abort(), 15000);
 try {
  const response = await fetch('/payload?arm=' + mode, {signal:abort.signal, cache:'no-store', credentials:'omit'});
  const value = mode === 'text' ? JSON.parse(await response.text()) : await readBoundedJson(response,1048576,abort.signal,()=>{});
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(v=>v.toString(16).padStart(2,'0')).join('');
  return {outcome:'parsed',hash:digest,bytes:bytes.length,rows:value.rows.length};
 } catch(error) {return {outcome:'failed',error_name:error.name,error_message:String(error.message).slice(0,400)};}
 finally {clearTimeout(timer);}
};</script>`;
const server = http.createServer((req, res) => {
 const url = new URL(req.url, 'http://127.0.0.1');
 if (url.pathname === '/') { res.writeHead(200, {'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'});res.end(html);return; }
 if (url.pathname !== '/payload' || !Object.hasOwn(counts,url.searchParams.get('arm'))) { res.writeHead(404);res.end();return; }
 counts[url.searchParams.get('arm')]++;
 res.writeHead(200, {'Content-Type':'application/json; charset=utf-8','Content-Length':payload.length,'Cache-Control':'private, no-store','Vary':'Cookie','X-Content-Type-Options':'nosniff'});
 let position = 0;
 const next = () => { if (position >= payload.length) {res.end();return;}res.write(payload.subarray(position,position+8192));position+=8192;setImmediate(next); };
 next();
});
(async()=>{
 let browser; const browserHome=fs.mkdtempSync(path.join(os.tmpdir(),'dala-public-json-browser-'));
 const report={evidence:'public synthetic loopback, isolated parser and CDP observer, not app/API/DB acceptance',reader_source_sha256:sha(reader),payload_sha256:expectedHash,payload_bytes:payload.length,arms:[],counts};
 try {
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
  const origin=`http://127.0.0.1:${server.address().port}`;
  browser=await bounded(chromium.launch({executablePath,headless:true,env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8',HOME:browserHome,TMPDIR:browserHome}}),'browser launch');
  report.browser=browser.version();
  const context=await browser.newContext({...devices['Pixel 9'],serviceWorkers:'block'});
  await context.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort('blockedbyclient'));
  const page=await context.newPage();page.setDefaultTimeout(20000);
  const failures=[];page.on('requestfailed',request=>failures.push({path:new URL(request.url()).pathname,error:request.failure()?.errorText}));
  await page.goto(origin);
  for(const arm of ['text','reader']){
   const waiting=page.waitForResponse(response=>new URL(response.url()).pathname==='/payload'&&new URL(response.url()).searchParams.get('arm')===arm);
   await page.evaluate(mode=>{window.armPromise=window.runArm(mode);},arm);
   const response=await waiting;let observer;
   try{observer=await bounded((async()=>{const value=await response.json();const bytes=await response.body();return {outcome:'parsed',hash:sha(bytes),bytes:bytes.length,rows:value.rows.length};})(),'CDP observer');}
   catch(error){observer={outcome:'failed',error_name:error.name,error_message:String(error.message).slice(0,400)};}
   let app;try{app=await bounded(page.evaluate(()=>window.armPromise),'app arm result');}catch(error){app={outcome:'failed',error_name:error.name,error_message:String(error.message).slice(0,400)};}
   report.arms.push({arm,status:response.status(),app,observer,request_failure:response.request().failure(),exact_bytes:app.hash===expectedHash&&observer.hash===expectedHash});
  }
  report.failures=failures;
  report.result=report.arms.every(x=>x.exact_bytes)&&counts.text===1&&counts.reader===1?'BOTH_ARMS_PASS':'OBSERVED_DIFFERENCE_OR_FAILURE';
 }catch(error){report.result='BLOCKED';report.blocker={name:error.name,message:String(error.message).slice(0,500)};}
 finally{if(browser)await bounded(browser.close(),'browser close',5000).catch(()=>undefined);server.closeAllConnections();await bounded(new Promise(resolve=>server.close(resolve)),'server close',5000).catch(()=>undefined);fs.rmSync(browserHome,{recursive:true,force:true});console.log(JSON.stringify(report,null,2));}
})();
