'use strict';
// Fixed public synthetic diagnostic: two consumers x six flows =12 original GETs.
// Signature-only payloads are not valid PDF/XLSX documents. No product or C edits.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),os=require('node:os'),crypto=require('node:crypto');
const frontend=path.resolve(process.argv[2]),executablePath=process.argv[3];
const {chromium,devices}=require(path.join(frontend,'node_modules/playwright'));
const ts=require(path.join(frontend,'node_modules/typescript'));
const sha=value=>crypto.createHash('sha256').update(value).digest('hex');
const original=fs.readFileSync(path.join(frontend,'src/shared/api/reportFiles.ts'),'utf8');
const candidate=fs.readFileSync(path.join(__dirname,'dalaai-experimental-binary-transform.ts'),'utf8');
const originalHash='73705ba4545e795ab3a59fa1a71de4638c1100457b606296538eb161fd0b0639';
if(sha(original)!==originalHash)throw new Error('Original06877 reportFiles source hash mismatch');
const compile=source=>ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText.replace(/^export /gm,'');
const cap=8*1024*1024;
const formats={pdf:'application/pdf',xlsx:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'};
const arms=['manual','transform'];
const flows=['valid_pdf','valid_xlsx','overflow_unknown_length','transport_error','caller_abort','invalid_signature'];
const counts=Object.fromEntries(flows.flatMap(flow=>arms.map(arm=>[`${arm}:${flow}`,0])));
function payload(format,size=175949,bad=false){const bytes=Buffer.alloc(size,88);(format==='pdf'?Buffer.from('%PDF-'):Buffer.from([80,75,3,4])).copy(bytes);Buffer.from('PUBLIC-SYNTHETIC-SIGNATURE-ONLY').copy(bytes,32);if(bad)bytes[0]=0;return bytes;}
const bodies={pdf:payload('pdf'),xlsx:payload('xlsx'),overflow:payload('pdf',cap+1),invalid:payload('pdf',175949,true)};
const bounded=async(work,label,ms=20000)=>{let timer;try{return await Promise.race([work,new Promise((_,reject)=>{timer=setTimeout(()=>{const error=new Error(label+' exceeded public diagnostic wall bound');error.name='ProbeTimeout';reject(error);},ms);})]);}finally{clearTimeout(timer);}};
const html=`<!doctype html><meta charset="utf-8"><title>Public synthetic binary consumer comparison</title><p>Signature-only synthetic bytes. No documents, API or private data.</p><script>${compile(original)}\n${compile(candidate)}
window.fixtureEpoch=1;
window.runBinary=async(arm,flow)=>{
 const format=flow==='valid_xlsx'?'xlsx':'pdf';const filename='synthetic.'+format;
 const control=new AbortController();const epoch=window.fixtureEpoch;let deadline,cancelTimer;let blobReceived=false,deadlineFired=false,callerAbortFired=false;
 const assertCurrent=()=>{if(window.fixtureEpoch!==epoch)throw new Error('SYNTHETIC_EPOCH_CHANGED');control.signal.throwIfAborted();};
 try{
  deadline=setTimeout(()=>{deadlineFired=true;control.abort();},15000);
  const response=await fetch('/payload?arm='+arm+'&flow='+flow,{signal:control.signal,credentials:'omit',cache:'no-store'});
  if(flow==='caller_abort')cancelTimer=setTimeout(()=>{callerAbortFired=true;control.abort();},100);
  const file=await(arm==='manual'?readReportFile:readReportFileTransformed)(response,format,filename,assertCurrent);
  assertCurrent();clearTimeout(deadline);clearTimeout(cancelTimer);blobReceived=true;
  const bytes=new Uint8Array(await file.blob.arrayBuffer());
  const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(v=>v.toString(16).padStart(2,'0')).join('');
  return {outcome:'accepted',blob_received:true,bytes:bytes.length,hash:digest,mime:file.blob.type,filename:file.filename,aborted:control.signal.aborted,deadline_fired:deadlineFired,caller_abort_fired:callerAbortFired};
 }catch(error){return {outcome:'rejected',blob_received:blobReceived,error_name:error.name,error_message:String(error.message).slice(0,300),aborted:control.signal.aborted,deadline_fired:deadlineFired,caller_abort_fired:callerAbortFired};}
 finally{clearTimeout(deadline);clearTimeout(cancelTimer);}
};</script>`;
const server=http.createServer((req,res)=>{
 const url=new URL(req.url,'http://127.0.0.1');
 if(url.pathname==='/'){res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'});res.end(html);return;}
 const arm=url.searchParams.get('arm'),flow=url.searchParams.get('flow'),key=`${arm}:${flow}`;
 if(url.pathname!=='/payload'||!Object.hasOwn(counts,key)){res.writeHead(404);res.end();return;}
 counts[key]++;if(counts[key]!==1){res.writeHead(429);res.end();return;}
 const format=flow==='valid_xlsx'?'xlsx':'pdf';
 const body=flow==='overflow_unknown_length'?bodies.overflow:flow==='invalid_signature'?bodies.invalid:bodies[format];
 const headers={'Content-Type':formats[format],'Content-Disposition':`attachment; filename="synthetic.${format}"`,'Cache-Control':'private, no-store','Vary':'Cookie','X-Content-Type-Options':'nosniff'};
 if(flow!=='overflow_unknown_length')headers['Content-Length']=body.length;
 res.writeHead(200,headers);res.flushHeaders();res.on('error',()=>{});
 if(flow==='caller_abort'){res.write(body.subarray(0,512));return;}
 if(flow==='transport_error'){res.write(body.subarray(0,512));const timer=setTimeout(()=>res.destroy(),50);res.once('close',()=>clearTimeout(timer));return;}
 let position=0;
 const next=()=>{if(res.destroyed)return;if(position>=body.length){res.end();return;}const writable=res.write(body.subarray(position,position+16384));position+=16384;if(writable)setImmediate(next);else res.once('drain',next);};next();
});
(async()=>{
 let browser;const browserHome=fs.mkdtempSync(path.join(os.tmpdir(),'dala-public-binary-browser-'));
 const report={evidence:'Public synthetic signature-only binary consumers, not valid documents/product/API/DB/C acceptance',original_source_sha256:originalHash,candidate_source_sha256:sha(candidate),limit_bytes:cap,payloads:{pdf:{bytes:bodies.pdf.length,hash:sha(bodies.pdf)},xlsx:{bytes:bodies.xlsx.length,hash:sha(bodies.xlsx)}},flows:[],counts};
 try{
  await bounded(new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);}),'server start');
  const origin=`http://127.0.0.1:${server.address().port}`;
  browser=await bounded(chromium.launch({executablePath,headless:true,env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8',HOME:browserHome,TMPDIR:browserHome}}),'browser launch');
  report.browser=browser.version();
  const context=await bounded(browser.newContext({...devices['Pixel 9'],serviceWorkers:'block'}),'context creation');
  await context.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort('blockedbyclient'));
  const page=await bounded(context.newPage(),'page creation');page.setDefaultTimeout(20000);await bounded(page.goto(origin),'fixture navigation');
  for(const flow of flows)for(const arm of arms){
   const waiting=page.waitForResponse(response=>{const u=new URL(response.url());return u.pathname==='/payload'&&u.searchParams.get('arm')===arm&&u.searchParams.get('flow')===flow;});
   await bounded(page.evaluate(({arm,flow})=>{window.armPromise=window.runBinary(arm,flow);},{arm,flow}),'arm dispatch');
   const response=await bounded(waiting,'original response headers');let observer;
   try{const bytes=await bounded(response.body(),'original CDP response body');observer={outcome:'bytes',bytes:bytes.length,hash:sha(bytes)};}
   catch(error){observer={outcome:'unavailable',error_name:error.name,error_message:String(error.message).slice(0,350)};}
   let app;try{app=await bounded(page.evaluate(()=>window.armPromise),'app flow result');}
   catch(error){app={outcome:'inconclusive',blob_received:false,error_name:error.name,error_message:String(error.message).slice(0,300)};}
   const valid=flow==='valid_pdf'||flow==='valid_xlsx';const expected=report.payloads[flow==='valid_xlsx'?'xlsx':'pdf'];
   const negativeReason=flow==='overflow_unknown_length'?app.error_message==='Report exceeds byte limit'&&!app.aborted:flow==='invalid_signature'?app.error_message==='Invalid report signature'&&!app.aborted:flow==='caller_abort'?app.error_name==='AbortError'&&app.aborted===true&&app.caller_abort_fired===true:flow==='transport_error'?app.error_name==='TypeError'&&!app.aborted:false;
   const appExpected=valid?app.outcome==='accepted'&&app.hash===expected.hash&&app.bytes===expected.bytes&&app.mime===formats[flow==='valid_xlsx'?'xlsx':'pdf']&&app.filename===`synthetic.${flow==='valid_xlsx'?'xlsx':'pdf'}`&&!app.aborted:app.outcome==='rejected'&&app.blob_received===false&&negativeReason;
   report.flows.push({arm,flow,status:response.status(),app,observer,request_failure:response.request().failure(),app_expected:appExpected&&!app.deadline_fired,original_cdp_exact:valid?observer.outcome==='bytes'&&observer.hash===expected.hash&&observer.bytes===expected.bytes:null});
  }
  report.complete=report.flows.length===12&&Object.values(counts).every(count=>count===1)&&!report.flows.some(row=>!['accepted','rejected'].includes(row.app.outcome)||['ProbeTimeout','TimeoutError'].includes(row.app.error_name)||['ProbeTimeout','TimeoutError'].includes(row.observer.error_name)||row.app.deadline_fired===true);
  report.result=report.complete?(report.flows.every(row=>row.app_expected)?'COMPLETE_APP_CHECKS_PASS_OBSERVER_RECORDED':'COMPLETE_APP_CHECK_FAILED'):'INCONCLUSIVE';
 }catch(error){report.result='INCONCLUSIVE';report.blocker={name:error.name,message:String(error.message).slice(0,500)};}
 finally{if(browser)await bounded(browser.close(),'browser close',5000).catch(()=>undefined);server.closeAllConnections();await bounded(new Promise(resolve=>server.close(resolve)),'server close',5000).catch(()=>undefined);fs.rmSync(browserHome,{recursive:true,force:true});console.log(JSON.stringify(report,null,2));}
})();
