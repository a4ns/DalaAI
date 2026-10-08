'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const c = require('./c113_contract.cjs');
const p = require('./c113_preflight_proof.cjs');
const { privateLoginBoundary } = require('./c113_private_boundary.cjs');
function report() { return { config:{metadata:{frontend_sha:c.FRONTEND_SHA,run_id:'c113-source-test-0001'}},errors:[],stats:{expected:0,unexpected:1,skipped:0,flaky:0},suites:[{specs:[{title:p.PREFLIGHT_TITLE,tests:[{expectedStatus:'passed',status:'unexpected',results:[{status:'failed',retry:0,errors:[{message:'C113_DUMMY_FAILURE_EXPECTED'}]}]}]}]}] }; }
test('dummy proof requires exactly the intentional unexpected failure',()=>{assert.equal(p.preflightOutcome(report(),1,'c113-source-test-0001'),true); for(const mutate of [r=>{r.stats.unexpected=0;},r=>{r.stats.skipped=1;},r=>{r.suites=[];},r=>{r.suites[0].specs[0].title='C110 dummy credential failure output';},r=>{r.suites[0].specs[0].tests[0].results[0].errors=[];},r=>{r.suites[0].specs[0].tests[0].expectedStatus='failed';},r=>{r.config.metadata.frontend_sha='0'.repeat(40);}]){const r=report();mutate(r);assert.equal(p.preflightOutcome(r,1,'c113-source-test-0001'),false);} assert.equal(p.preflightOutcome(report(),0,'c113-source-test-0001'),false);});
test('private boundary suppresses all transport exception details',async()=>{await assert.rejects(privateLoginBoundary('executor',async()=>{throw Error('DUMMY_COOKIE DUMMY_DSN DUMMY_PIN DUMMY_CSRF');}),{message:'C113 BLOCKED: synthetic executor login failed; credential-bearing details suppressed'});});
test('effective runner rejects capture, inherited browser env, retries, extra reporters and config changes',()=>{const file=path.join(__dirname,'c113_playwright.config.cjs'), output='/public/report.json';const config={configFile:file,workers:1,forbidOnly:true,reporter:[['list',{printSteps:false}],['json',{outputFile:output}]]},project={retries:0,repeatEach:1,use:c.runnerUse()};c.validateEffectiveRunner(config,project,file,output);for(const mutate of [(_,pr)=>{pr.use.trace='on';},(_,pr)=>{pr.use.ignoreHTTPSErrors=true;},(_,pr)=>{pr.use.launchOptions={};},(_,pr)=>{pr.use.launchOptions.env.DALA_C113_OBSERVER_DATABASE_URL='DUMMY';},(_,pr)=>{pr.retries=1;},co=>{co.reporter.push(['html']);},co=>{co.configFile='/different';},co=>{co.workers=2;},co=>{co.forbidOnly=false;}]){const co=structuredClone(config),pr=structuredClone(project);mutate(co,pr);assert.throws(()=>c.validateEffectiveRunner(co,pr,file,output));}});

test('download diagnostics and inspector failure projection cannot serialize private values',()=>{
 const d=require('./c113_downloads.cjs'),state=d.createDownloadDiagnostic(),secret='DUMMY_PRIVATE_SENTINEL';
 d.downloadCheckpoint(state,secret,secret);d.downloadResponse(state,secret);d.downloadTransport(state,{'content-encoding':secret,'content-length':secret});state.inspector=d.inspectorFailure({stdout:JSON.stringify({status:'BLOCKED',code:'C113_DOWNLOAD_INSPECTION_FAILED',stage:secret})});
 assert.deepEqual(state,{...d.createDownloadDiagnostic(),target:'UNCLASSIFIED',substep:'UNCLASSIFIED',response:'HTTP_OTHER_OR_UNAVAILABLE',encoding:'OTHER',content_length:'INVALID',inspector:'PROCESS_FAILED'});
 assert.ok(!JSON.stringify(state).includes(secret));
 for(const stage of ['PDF_XREF','PDF_PAGE_SHAPE','PDF_CONTENT','XLSX_CONTENT'])assert.equal(d.inspectorFailure({stdout:JSON.stringify({status:'BLOCKED',code:'C113_DOWNLOAD_INSPECTION_FAILED',stage})}),stage);
 for(const stdout of [secret,'{bad',JSON.stringify({status:'BLOCKED',code:'C113_DOWNLOAD_INSPECTION_FAILED',stage:'PDF_CONTENT',raw:secret}),JSON.stringify({status:'PASS',code:'C113_DOWNLOAD_INSPECTION_FAILED',stage:'PDF_CONTENT'}),'a'.repeat(16385)])assert.equal(d.inspectorFailure({stdout}),'PROCESS_FAILED');
 d.downloadTransport(state,{});assert.equal(state.encoding,'IDENTITY');assert.equal(state.content_length,'ABSENT');
 d.downloadTransport(state,{'content-encoding':'gzip','content-length':'500'});assert.equal(state.encoding,'GZIP');assert.equal(state.content_length,'POSITIVE_WITHIN_LIMIT');
 d.downloadResponse(state,200);assert.equal(state.response,'HTTP_OK');d.downloadCheckpoint(state,'WAIT_SAVE_DOWNLOAD','SHIFT_PDF');assert.equal(state.substep,'WAIT_SAVE_DOWNLOAD');
});

test('request diagnostics bind exact identity and preserve terminal event before binding',()=>{
 const {EventEmitter}=require('node:events'),d=require('./c113_downloads.cjs'),page=new EventEmitter();
 const request={failure:()=>null},other={failure:()=>({errorText:'DUMMY_PRIVATE_FAILURE'})};
 const observer=d.requestCompletionObserver(page);
 page.emit('requestfinished',request);page.emit('requestfailed',other);observer.bind(request);
 assert.deepEqual(observer.snapshot(),{completion:'FINISHED',failure_present:false});
 page.emit('requestfailed',other);assert.deepEqual(observer.snapshot(),{completion:'FINISHED',failure_present:false});
 observer.bind(other);assert.deepEqual(observer.snapshot(),{completion:'FAILED',failure_present:true});
 assert.ok(!JSON.stringify(observer.snapshot()).includes('DUMMY_PRIVATE_FAILURE'));
 observer.bind({failure:()=>null});assert.deepEqual(observer.snapshot(),{completion:'NOT_OBSERVED',failure_present:false});
 observer.dispose();assert.equal(page.listenerCount('requestfinished'),0);assert.equal(page.listenerCount('requestfailed'),0);
});
test('body failure classification emits only fixed allowlisted categories',()=>{
 const d=require('./c113_downloads.cjs');
 for(const [error,category] of [[Object.assign(new Error('DUMMY_PRIVATE'),{name:'TimeoutError'}),'TIMEOUT'],[new Error('C113_RESPONSE_BODY_TIMEOUT'),'TIMEOUT'],[new Error('Protocol error (Network.getResponseBody): DUMMY_PRIVATE'),'BODY_PROTOCOL_FAILURE'],[new Error('Protocol error (Network.getResponseBody): No resource with given identifier found DUMMY_PRIVATE'),'BODY_UNAVAILABLE'],[new Error('Target page, context or browser has been closed DUMMY_PRIVATE'),'TARGET_CLOSED'],[new Error('DUMMY_PRIVATE'),'OTHER'],[{get message(){throw Error('DUMMY_PRIVATE');}},'OTHER']])assert.equal(d.bodyFailure(error),category);
 assert.equal(d.bodyFailure({message:'x'.repeat(8193)}),'OTHER');
});
test('original body is invoked once, bounded, and its error is preserved without retry',async()=>{
 const d=require('./c113_downloads.cjs');let calls=0;
 const bytes=Buffer.from('dummy');assert.equal(await d.boundedResponseBody({body(){calls++;return Promise.resolve(bytes);}},20),bytes);assert.equal(calls,1);
 const original=new Error('DUMMY_PRIVATE');calls=0;
 await assert.rejects(d.boundedResponseBody({body(){calls++;return Promise.reject(original);}},20),error=>error===original);assert.equal(calls,1);
 calls=0;await assert.rejects(d.boundedResponseBody({body(){calls++;return new Promise(()=>{});}},5),{message:'C113_RESPONSE_BODY_TIMEOUT'});assert.equal(calls,1);
});
test('frontend correlation is fixed-state only and short bounded on failed/slow probes',async()=>{
 const d=require('./c113_downloads.cjs');
 for(let i=0;i<4;i++)assert.equal(d.frontendState(Array.from({length:4},(_,j)=>i===j)),['READY','ERROR','LOADING','EXPIRED'][i]);
 for(const flags of [null,[],['DUMMY_PRIVATE',false,false,false],[true,true,false,false]])assert.equal(d.frontendState(flags),'NOT_OBSERVED');
 const failed={getByRole(){throw Error('DUMMY_PRIVATE');}};assert.equal(await d.sampleDownloadUi(failed,'pdf'),'NOT_OBSERVED');
 const delayed={getByRole(){return {isVisible:()=>new Promise(()=>{})};},getByText(){return {isVisible:()=>new Promise(()=>{})};}};
 const start=Date.now();assert.equal(await d.sampleDownloadUi(delayed,'pdf'),'NOT_OBSERVED');assert.ok(Date.now()-start<2000);
});
test('source registers exact request observer before Prepare and cleans it on all outcomes',()=>{
 const fs=require('node:fs'),s=fs.readFileSync(path.join(__dirname,'c113_download_clock.spec.cjs'),'utf8');
 assert.ok(s.indexOf('files.requestCompletionObserver(master.page)')<s.indexOf("markDownload('WAIT_PREPARE_RESPONSE')"));
 assert.match(s,/requestObserver\.bind\(response\.request\(\)\)/);
 assert.match(s,/finally\{requestObserver\.dispose\(\);master\.page\.off\('download',watch\);\}/);
 assert.match(s,/responseBytes=await files\.boundedResponseBody\(response\)/);
 assert.doesNotMatch(s,/response\.finished\(/);
});
