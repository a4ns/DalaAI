'use strict';
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const frontend=path.resolve(process.argv[2]);const ts=require(path.join(frontend,'node_modules/typescript'));
const source=fs.readFileSync(path.join(__dirname,'dalaai-experimental-binary-transform.ts'),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const m={exports:{}};new vm.Script(`(function(exports,module){${compiled}\n})`).runInThisContext()(m.exports,m);
const read=m.exports.readReportFileTransformed;
const cap=8*1024*1024;const mime={pdf:'application/pdf',xlsx:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'};
const bytes=format=>format==='pdf'?new TextEncoder().encode('%PDF-SYNTHETIC-SIGNATURE-ONLY'):new Uint8Array([80,75,3,4,11,22]);
const response=(body,format='pdf',extra={})=>new Response(body,{headers:{'Content-Type':mime[format],'Content-Disposition':`attachment; filename="synthetic.${format}"`,...extra}});
const within=async p=>{let t;try{return await Promise.race([p,new Promise((_,reject)=>{t=setTimeout(()=>reject(new Error('UNIT_WALL_TIMEOUT')),250);})]);}finally{clearTimeout(t);}};
(async()=>{
 const checks=[];
 for(const format of ['pdf','xlsx']){
  const expected=bytes(format);let at=0;const stream=new ReadableStream({pull(c){if(at===expected.length)c.close();else c.enqueue(expected.slice(at,++at));}});
  const file=await within(read(response(stream,format),format,`synthetic.${format}`,()=>{}));assert.deepEqual(new Uint8Array(await file.blob.arrayBuffer()),expected);checks.push(`exact_split_signature_${format}`);
 }
 let cancelled=0;const over=new ReadableStream({pull(c){c.enqueue(new Uint8Array(cap+1));},cancel(){cancelled++;return new Promise(()=>{});}},{highWaterMark:0});
 await assert.rejects(()=>within(read(response(over),'pdf','synthetic.pdf',()=>{})),/byte limit/);assert.equal(cancelled,1);checks.push('overflow_rejects_without_waiting_cancel');
 let epoch=1;const captured=epoch;let controller,markFirst;let checksSeen=0;const firstSeen=new Promise(resolve=>{markFirst=resolve;});const stale=new ReadableStream({start(c){controller=c;}});
 const pending=read(response(stale),'pdf','synthetic.pdf',()=>{if(epoch!==captured)throw new Error('STALE_EPOCH');if(++checksSeen===2)markFirst();});controller.enqueue(bytes('pdf').slice(0,2));await within(firstSeen);epoch++;controller.enqueue(bytes('pdf').slice(2));controller.close();await assert.rejects(()=>within(pending),/STALE_EPOCH/);checks.push('epoch_fence_during_stream');
 const abort=new AbortController();let finish;const late=new ReadableStream({start(c){finish=()=>{c.enqueue(bytes('pdf'));c.close();};}});
 const canceled=read(response(late),'pdf','synthetic.pdf',()=>abort.signal.throwIfAborted());abort.abort();finish();await assert.rejects(()=>within(canceled));checks.push('real_abort_fence');
 const failed=new ReadableStream({start(c){c.error(new Error('SYNTHETIC_STREAM_ERROR'));}});await assert.rejects(()=>within(read(response(failed),'pdf','synthetic.pdf',()=>{})),/SYNTHETIC_STREAM_ERROR/);checks.push('stream_error_no_blob');
 for(const format of ['pdf','xlsx'])await assert.rejects(()=>within(read(response(new Uint8Array([1,2,3,4,5]),format),format,`synthetic.${format}`,()=>{})),/signature/);checks.push('signature_failures_no_blob');
 await assert.rejects(()=>within(read(response(bytes('pdf'),'pdf',{'Content-Length':String(cap+1)}),'pdf','synthetic.pdf',()=>{})),/byte limit/);checks.push('declared_cap_preserved');
 console.log(JSON.stringify({scope:'Experimental source-only probes; no browser/product/API acceptance',checks,result:'PASS'},null,2));
})().catch(error=>{console.log(JSON.stringify({result:'FAIL',error:String(error.message)}));process.exitCode=1;});
