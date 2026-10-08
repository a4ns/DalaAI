// Synthetic in-process transport only. No real business clock, credentials or POST.
const assert=require('node:assert/strict'),fs=require('node:fs'),ts=require('typescript');
require.extensions['.ts']=(module,file)=>module._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,file);
const {ApiClient}=require('../../shared/api/client.ts');const {DemoClockController}=require('./controller.ts');
const base={mode:'synthetic_demo',label:'Синтетическое демо-время',instance_id:'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',version:0,scale:1,real_now:'2026-10-08T00:00:00Z',domain_now:'2026-10-08T00:00:00Z',real_anchor:'2026-10-08T00:00:00Z',domain_anchor:'2026-10-08T00:00:00Z',domain_limit:'2026-10-15T00:00:00Z',storage:'postgres_shared',reset_supported:false,limits:{max_scale:60,max_advance_seconds:3600}};
const session={principal:{user_id:'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',active:true,employee_code:'SYNTHETIC',role:'master',section_ids:[],on_shift:true},csrf_token:'synthetic-csrf',expires_at:'2099-01-01T00:00:00Z'};
const json=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});
async function setup(post){let current=structuredClone(base);const sent=[];const client=new ApiClient({online:()=>true,fetch:async(url,options)=>{if(String(url).endsWith('/auth/login'))return json(session);if(options.method==='POST'){sent.push(options);return post(options);}return json(current);}});await client.login({employee_code:'SYNTHETIC',pin:'0000'});const controller=new DemoClockController(client);const detach=controller.attach();await controller.refresh();return{client,controller,sent,detach,setCurrent:value=>{current=value;}};}
(async()=>{
 const h=await setup(async()=>{throw new TypeError('Synthetic lost reply');});
 const token=h.client.prepareDemoClock(base,{action:'advance',seconds:60});
 await assert.rejects(h.client.executeDemoClock(token));await assert.rejects(h.client.executeDemoClock(token));assert.equal(h.sent.length,1);
 assert.deepEqual(JSON.parse(h.sent[0].body),{instance_id:base.instance_id,expected_version:0,action:'advance',seconds:60});assert.equal(h.sent[0].headers.get('X-CSRF-Token'),'synthetic-csrf');
 await h.controller.change({action:'advance',seconds:60});assert.equal(h.controller.getSnapshot().operation,'unknown');
 h.setCurrent({...base,version:2,scale:0,domain_now:'2026-10-08T00:02:00Z',domain_anchor:'2026-10-08T00:02:00Z'});await h.controller.refresh();h.controller.resolveConflict();await h.controller.change({action:'set_scale',scale:1});assert.equal(h.sent.length,2);assert.equal(h.controller.getSnapshot().operation,'unknown');h.detach();
 console.log('PASS synthetic: token is sent once; unknown intent stays locked across changed GET and explicit attempted new action');
 let calls=0;const g=await setup(async()=>++calls===1?json({code:'VERSION_CONFLICT',message:'Synthetic conflict',request_id:'cccccccc-cccc-4ccc-8ccc-cccccccccccc',retryable:false,current_version:1,field_errors:[]},409):json({...base,version:2,scale:0}));
 await g.controller.change({action:'set_scale',scale:0});assert.equal(g.controller.getSnapshot().operation,'conflict');g.controller.resolveConflict();assert.equal(g.controller.getSnapshot().operation,'conflict');g.setCurrent({...base,version:1});await g.controller.refresh();assert.equal(g.controller.getSnapshot().operation,'conflict');g.controller.resolveConflict();await g.controller.change({action:'set_scale',scale:0});assert.equal(g.controller.getSnapshot().operation,'confirmed');assert.equal(g.sent.length,2);g.detach();
 assert.throws(()=>g.client.prepareDemoClock(base,{action:'advance',seconds:60,expected_version:99}));
 console.log('PASS synthetic: known409 needs fresh read plus explicit acknowledgment; caller cannot override captured version');
})().catch(error=>{console.error(error);process.exitCode=1;});
