'use strict';
// Actual composed app only. Browser execution belongs to A's isolated CI.
const fs=require('node:fs'),path=require('node:path');
const {createHash}=require('node:crypto');
const {createRequire}=require('node:module');
const {execFile}=require('node:child_process');
const {promisify}=require('node:util');
const c=require('./c113_contract.cjs'),proof=require('./c113_preflight_proof.cjs');
const clock=require('./c113_clock.cjs'),files=require('./c113_downloads.cjs');
const {PRIVATE_ACTION_TIMEOUT_MS,privateLoginBoundary,privateOperationBoundary}=require('./c113_private_boundary.cjs');
const root=process.env.DALA_C113_PLAYWRIGHT_PACKAGE||path.dirname(require.resolve('@playwright/test/package.json'));
const pw=createRequire(path.join(root,'package.json'));
c.check(pw('./package.json').name==='@playwright/test'&&pw('./package.json').version==='1.63.0','PINNED_PLAYWRIGHT_REQUIRED');
const {test,expect,devices}=pw(root),runFile=promisify(execFile);
const bytesHash=b=>createHash('sha256').update(b).digest('hex');
let fixture;
test.beforeAll(()=>{
  fixture=c.fixtureFromEnv();
  fs.mkdirSync(c.artifactDir(),{recursive:true});
  try{fs.writeFileSync(path.join(c.artifactDir(),'run-claim.json'),JSON.stringify({run_id:fixture.run_id,harness_sha:proof.sourceSha()}),{flag:'wx',mode:0o600});}
  catch{throw new Error('C113 BLOCKED: fresh artifact run ID required');}
});
test(c.TITLE,async({browser,browserName},info)=>{
  c.validateEffectiveRunner(info.config,info.project,path.join(__dirname,'c113_playwright.config.cjs'),path.join(c.artifactDir(),'playwright.json'));
  c.check(browserName==='chromium'&&info.project.name===c.PROJECT,'ANDROID_PROJECT_REQUIRED');
  const sourceSha=proof.sourceSha(),hashes=proof.fingerprint(),device=devices['Pixel 7'];
  c.check(device.isMobile&&device.hasTouch,'MOBILE_PROFILE_REQUIRED');
  const e={schema_version:1,result:'FAIL',test:c.TITLE,run_id:fixture.run_id,harness_sha:sourceSha,
    frontend_sha:fixture.frontend_sha,backend_sha:fixture.backend_sha,source_files:hashes,
    manifest:fixture.manifest,manifest_sha256:fixture.manifest_sha256,secrecy_proof:fixture.proof,
    started_at:new Date().toISOString(),steps:[],clock:[],downloads:[],restrictions:[],download_diagnostic:files.createDownloadDiagnostic(),
    period:c.PERIOD,ui_period_utc_plus_5:c.LOCAL_PERIOD,
    browser:{mode:'ANDROID_EMULATION',engine:'chromium',version:browser.version(),profile:'Pixel 7',playwright:'1.63.0',contexts:2,mobile:true,touch:true,locale:'ru-RU',timezone:'Asia/Almaty',trusted_tls:true,credential_environment:'excluded_from_browser_process',service_workers:'blocked'},
    separate_gates:Object.fromEntries(['c110_lifecycle','c112_analytics','physical_android','native_excel','native_camera','push_delivery','provider_model','live_closure','security_clock_expiry'].map(k=>[k,'NOT_RUN']))};
  const contexts=[],network={blocked_external:0,blocked_mutation:0,login_posts:0,master_clock_posts:0,executor_clock_posts:0,export_gets:0};
  let master,executor,before,after,selected,expectedCommand=null,clockScope;
  const stage=async(name,work)=>test.step(name,async()=>{const row={name,result:'FAIL'};e.steps.push(row);await privateOperationBoundary(work);row.result='PASS';});
  const observe=async()=>privateOperationBoundary(async()=>{
    const {stdout}=await runFile(process.env.DALA_C113_PYTHON||'python',[path.join(__dirname,'c113_observe.py'),fixture.master.id,fixture.executor.id],{env:process.env,timeout:30000,maxBuffer:1024*1024});
    const result=JSON.parse(stdout);require('./c113_gate.cjs').validateDatabase(result,fixture.manifest);return result;
  });
  function protectedHeaders(response,pathname,status=200,isClock=false){
    const url=new URL(response.url()),h=response.headers();
    c.check(url.origin===fixture.origin&&url.pathname===pathname&&response.status()===status,'EXACT_RESPONSE_REQUIRED');
    c.check(/(?:^|,)\s*private(?:,|$)/i.test(h['cache-control']||'')&&/no-store/i.test(h['cache-control']||'')&&/cookie/i.test(h.vary||''),'PROTECTED_RESPONSE_REQUIRED');
    if(!isClock)c.check(h['x-content-type-options']==='nosniff','NOSNIFF_REQUIRED');
    if(response.fromServiceWorker)c.check(response.fromServiceWorker()===false,'SERVICE_WORKER_FORBIDDEN');
    return h;
  }
  const newSession=async role=>{
    const context=await browser.newContext({...device,locale:'ru-RU',timezoneId:'Asia/Almaty',serviceWorkers:'block',ignoreHTTPSErrors:false,acceptDownloads:true});
    contexts.push(context);context.setDefaultTimeout(15000);context.setDefaultNavigationTimeout(15000);
    await context.route('**/*',route=>{
      const request=route.request(),url=new URL(request.url());
      if(url.origin!==fixture.origin){network.blocked_external++;return route.abort('blockedbyclient');}
      if(request.method()==='GET'&&/\/reports\/.+\.(pdf|xlsx)$/.test(url.pathname))network.export_gets++;
      if(!['GET','HEAD'].includes(request.method())){
        if(request.method()==='POST'&&url.pathname==='/api/v1/auth/login')network.login_posts++;
        else if(role==='master'&&request.method()==='POST'&&url.pathname==='/api/v1/demo/clock'&&expectedCommand&&network.master_clock_posts<3){
          try{c.check(!url.search&&c.stable(request.postDataJSON())===c.stable(expectedCommand),'EXACT_PLANNED_CLOCK_COMMAND_REQUIRED');}
          catch{network.blocked_mutation++;return route.abort('blockedbyclient');}
          network.master_clock_posts++;expectedCommand=null;
        }else{network.blocked_mutation++;return route.abort('blockedbyclient');}
      }
      return route.continue();
    });
    await context.routeWebSocket('**/*',socket=>{network.blocked_external++;socket.close();});
    const page=await context.newPage();let csrf;
    await privateLoginBoundary(role,async()=>{
      await page.goto(fixture.origin,{waitUntil:'domcontentloaded'});
      await page.getByLabel('Табельный код',{exact:true}).fill(fixture[role].employee_code);
      await page.getByLabel('PIN',{exact:true}).fill(c.readOperatorPin(role),{timeout:PRIVATE_ACTION_TIMEOUT_MS});
      const [response]=await Promise.all([page.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/auth/login'&&r.request().method()==='POST'),page.getByRole('button',{name:'Войти',exact:true}).click()]);
      if(response.status()!==200)throw new Error('login failed');
      const meResponse=await context.request.get(`${fixture.origin}/api/v1/me`,{maxRedirects:0});
      if(meResponse.status()!==200)throw new Error('principal failed');
      const body=await meResponse.json(),me=body.principal;
      if(me.user_id!==fixture[role].id||me.role!==role||!me.active||c.stable([...me.section_ids].sort())!==c.stable([...fixture[role].section_ids].sort()))throw new Error('principal mismatch');
      if(typeof body.csrf_token!=='string'||body.csrf_token.length<16)throw new Error('csrf missing');
      csrf=body.csrf_token; // Never written to evidence, logs, filenames or arguments.
    });
    return {context,page,csrf};
  };
  const clockUi=async(name,method,click,command=null)=>privateOperationBoundary(async()=>{
    if(command)expectedCommand=command;
    const [response]=await Promise.all([master.page.waitForResponse(r=>new URL(r.url()).origin===fixture.origin&&new URL(r.url()).pathname==='/api/v1/demo/clock'&&r.request().method()===method),click()]);
    protectedHeaders(response,'/api/v1/demo/clock',200,true);
    const snapshot=clock.snapshot(await response.json());
    if(command)c.check(c.stable(response.request().postDataJSON())===c.stable(command)&&expectedCommand===null,'CLOCK_COMMAND_RECEIPT_REQUIRED');
    await expect(clockScope).toContainText(`Версия: ${snapshot.version}. Скорость: ${snapshot.scale}×`);
    const shown=new Date(Date.parse(snapshot.domain_now)+5*3600000).toISOString().slice(0,19).replace('T',' ')+' UTC+5';
    await expect(clockScope).toContainText('Бизнес-время снимка: '+shown);
    e.clock.push({name,method,path:'/api/v1/demo/clock',status:200,cache:'private,no-store',vary:'Cookie',ui_snapshot_visible:true,body_sha256:c.digest(snapshot),snapshot,command});
    return snapshot;
  });
  const uiReport=async(pathname,click)=>privateOperationBoundary(async()=>{
    const [response]=await Promise.all([master.page.waitForResponse(r=>{
      const u=new URL(r.url());return u.origin===fixture.origin&&u.pathname===pathname&&r.request().method()==='GET'&&Date.parse(u.searchParams.get('start'))===Date.parse(c.PERIOD.start)&&Date.parse(u.searchParams.get('end'))===Date.parse(c.PERIOD.end);
    }),click()]);
    protectedHeaders(response,pathname);
    const body=await response.json();require('./c113_gate.cjs').validatePeriod(body.period);return body;
  });
  const markDownload=(label,target)=>files.downloadCheckpoint(e.download_diagnostic,label,target);
  const download=async(kind,format)=>privateOperationBoundary(async()=>{
    markDownload('PREPARE_EXPECTATION',`${kind}_${format}`.toUpperCase());
    const target=e.download_diagnostic.target;Object.assign(e.download_diagnostic,files.createDownloadDiagnostic());markDownload('PREPARE_EXPECTATION',target);
    const expected=files.expected(kind,selected),pathname=files.pathname(expected,format),filename=files.filename(expected,format);
    const scope=master.page.getByRole('region',{name:'Скачать выбранный отчёт',exact:true});
    let observed=0;const watch=()=>observed++;master.page.on('download',watch);
    const requestObserver=files.requestCompletionObserver(master.page);
    try{
    markDownload('WAIT_PREPARE_RESPONSE');
    const [response]=await Promise.all([master.page.waitForResponse(r=>{
      const u=new URL(r.url());return u.origin===fixture.origin&&u.pathname===pathname&&r.request().method()==='GET'&&Date.parse(u.searchParams.get('start'))===Date.parse(c.PERIOD.start)&&Date.parse(u.searchParams.get('end'))===Date.parse(c.PERIOD.end);
    }),scope.getByRole('button',{name:`Подготовить ${format.toUpperCase()}`,exact:true}).click()]);
    requestObserver.bind(response.request());
    files.downloadResponse(e.download_diagnostic,response.status());markDownload('CHECK_PROTECTED_HEADERS');
    const h=response.headers();files.downloadTransport(e.download_diagnostic,h);protectedHeaders(response,pathname);
    markDownload('CHECK_EXPORT_MIME');c.check(h['content-type']===files.MEDIA[format],'EXACT_EXPORT_HEADERS_REQUIRED');
    markDownload('CHECK_EXPORT_DISPOSITION');c.check(h['content-disposition']===`attachment; filename="${filename}"`,'EXACT_EXPORT_HEADERS_REQUIRED');
    markDownload('CHECK_EXPORT_CSP');c.check(h['content-security-policy']==="default-src 'none'; sandbox",'EXACT_EXPORT_HEADERS_REQUIRED');
    markDownload('CHECK_CONTENT_LENGTH');
    c.check(/^[0-9]+$/.test(h['content-length']||'')&&Number(h['content-length'])>0&&Number(h['content-length'])<=c.MAX_DOWNLOAD_BYTES,'BOUNDED_CONTENT_LENGTH_REQUIRED');
    markDownload('READ_RESPONSE_BYTES');
    e.download_diagnostic.frontend_before_body=await files.sampleDownloadUi(scope,format);
    e.download_diagnostic.request_before_body=requestObserver.snapshot();
    let responseBytes;
    try{responseBytes=await files.boundedResponseBody(response);}
    catch(error){
      e.download_diagnostic.body_failure=files.bodyFailure(error);
      e.download_diagnostic.frontend_after_body=await files.sampleDownloadUi(scope,format);
      e.download_diagnostic.request_after_body=requestObserver.snapshot();
      // Preserve the original failed body operation. No GET retry, replacement
      // response, saved-blob substitution or inferred successful transfer.
      throw error;
    }
    e.download_diagnostic.frontend_after_body=await files.sampleDownloadUi(scope,format);
    e.download_diagnostic.request_after_body=requestObserver.snapshot();
    markDownload('CHECK_RESPONSE_SIZE');c.check(responseBytes.length===Number(h['content-length'])&&responseBytes.length<=c.MAX_DOWNLOAD_BYTES,'BOUNDED_RESPONSE_BYTES_REQUIRED');
    markDownload('WAIT_SAVE_CONTROL');await expect(scope.getByRole('button',{name:`Сохранить ${format.toUpperCase()}`,exact:true})).toBeVisible();
    markDownload('CHECK_NO_EARLY_SAVE');c.check(observed===0,'NO_SAVE_BEFORE_SECOND_GESTURE_REQUIRED');
    const gets=network.export_gets;
    markDownload('WAIT_SAVE_DOWNLOAD');const [saved]=await Promise.all([master.page.waitForEvent('download'),scope.getByRole('button',{name:`Сохранить ${format.toUpperCase()}`,exact:true}).click()]);
    markDownload('CHECK_SUGGESTED_FILENAME');c.check(saved.suggestedFilename()===filename,'BROWSER_DOWNLOAD_COMPLETION_REQUIRED');
    markDownload('WAIT_DOWNLOAD_COMPLETION');c.check(await saved.failure()===null,'BROWSER_DOWNLOAD_COMPLETION_REQUIRED');
    const savePath=path.join(c.artifactDir(),`saved-${kind}.${format}`);
    markDownload('SAVE_FILE');c.check(!fs.existsSync(savePath),'FRESH_DOWNLOAD_DESTINATION_REQUIRED');await saved.saveAs(savePath);
    markDownload('CHECK_SAVED_FILE');const stat=fs.lstatSync(savePath);c.check(stat.isFile()&&!stat.isSymbolicLink()&&stat.size>0&&stat.size<=c.MAX_DOWNLOAD_BYTES,'BOUNDED_SAVED_FILE_REQUIRED');
    markDownload('COMPARE_SAVED_BYTES');const bytes=fs.readFileSync(savePath);c.check(bytes.equals(responseBytes)&&observed===1&&network.export_gets===gets,'SAVED_EXACT_PREPARED_RESPONSE_REQUIRED');
    master.page.off('download',watch);
    markDownload('WRITE_EXPECTED_VALUES');const expectedPath=path.join(c.artifactDir(),`expected-${kind}-${format}.json`);
    fs.writeFileSync(expectedPath,c.stable(expected),{flag:'wx',mode:0o600});
    const env={PATH:process.env.PATH,LANG:'C.UTF-8',PYTHONDONTWRITEBYTECODE:'1'};
    markDownload('RUN_INSPECTOR');let stdout;
    try{({stdout}=await runFile(process.env.DALA_C113_INSPECT_PYTHON||'python',[path.join(__dirname,'c113_inspect_download.py'),savePath,format,expectedPath],{env,timeout:15000,maxBuffer:16384}));}
    catch(error){e.download_diagnostic.inspector=files.inspectorFailure(error);throw new Error('C113 BLOCKED: inspector failed; private details suppressed');}
    markDownload('PARSE_INSPECTOR_RESULT');const inspection=JSON.parse(stdout);
    markDownload('CHECK_INSPECTOR_BINDING');files.validateInspection(inspection,expected,format);e.download_diagnostic.inspector='PASS';
    const row={kind,format,path:pathname,filename,status:200,cache:'private,no-store',vary:'Cookie',nosniff:true,media:files.MEDIA[format],csp:"default-src 'none'; sandbox",
      prepare_via_ui:true,save_via_ui:true,download_completed:true,no_save_before_gesture:true,same_response_bytes:true,no_network_on_save:true,
      response_sha256:bytesHash(responseBytes),saved_sha256:bytesHash(bytes),bytes:bytes.length,inspection};
    markDownload('RECORD_DOWNLOAD');files.validateDownload(row,expected,format);e.downloads.push(row);markDownload('DONE');
    }finally{requestObserver.dispose();master.page.off('download',watch);}
  });
  try{
    await stage(c.REQUIRED_STEPS[0],async()=>{before=await observe();e.database_before=before;});
    await stage(c.REQUIRED_STEPS[1],async()=>{
      master=await newSession('master');executor=await newSession('executor');
      const cookies=await Promise.all(contexts.map(x=>x.cookies()));const sessions=cookies.map(a=>a.find(x=>x.name==='__Host-naryadai_session'));
      c.check(sessions.every(x=>x&&x.httpOnly&&x.secure&&x.sameSite==='Strict')&&sessions[0].value!==sessions[1].value,'SEPARATE_SECURE_SESSIONS_REQUIRED');e.distinct_secure_sessions=true;
      await expect(executor.page.getByRole('heading',{name:'Мои наряды',level:1,exact:true})).toBeVisible();
    });
    await stage(c.REQUIRED_STEPS[2],async()=>{
      await master.page.getByRole('navigation',{name:'Основная навигация'}).getByRole('button',{name:'Демо-время',exact:true}).click();
      clockScope=master.page.getByRole('region',{name:'Синтетическое демо-время',exact:true});
      await expect(clockScope).toContainText('Реальное время авторизации');
      const initial=await clockUi('initial','GET',()=>clockScope.getByRole('button',{name:'Проверить доступ к демо-часам',exact:true}).click());
      c.check(initial.scale===1,'INITIAL_CLOCK_RUNNING_REQUIRED');
      const paused=await clockUi('pause','POST',()=>clockScope.getByRole('button',{name:'Пауза (0×)',exact:true}).click(),clock.command(initial,'pause'));
      clock.transition(initial,paused,'pause');await new Promise(r=>setTimeout(r,350));
      const pausedRead=await clockUi('paused_read','GET',()=>clockScope.getByRole('button',{name:'Обновить показание сервера',exact:true}).click());clock.readAfter(paused,pausedRead,250);
      await clockScope.getByLabel('Продвинуть вперёд на секунды (1–3600)',{exact:true}).fill(String(c.ADVANCE_SECONDS));
      const advanced=await clockUi('advance','POST',()=>clockScope.getByRole('button',{name:'Продвинуть бизнес-время вперёд',exact:true}).click(),clock.command(pausedRead,'advance'));clock.transition(pausedRead,advanced,'advance');
      const resumed=await clockUi('resume','POST',()=>clockScope.getByRole('button',{name:'Продолжить (1×)',exact:true}).click(),clock.command(advanced,'resume'));clock.transition(advanced,resumed,'resume');
      await new Promise(r=>setTimeout(r,350));const resumedRead=await clockUi('resumed_read','GET',()=>clockScope.getByRole('button',{name:'Обновить показание сервера',exact:true}).click());clock.readAfter(resumed,resumedRead,250);
      clock.validateJourney(e.clock,Date.parse(e.started_at),Date.now());
    });
    await stage(c.REQUIRED_STEPS[3],async()=>{
      await master.page.getByRole('navigation',{name:'Основная навигация'}).getByRole('button',{name:'Аналитика и отчёты',exact:true}).click();
      const scope=master.page.getByRole('region',{name:'Аналитика и отчёты',exact:true});
      const start=scope.getByLabel('Начало периода',{exact:true}),end=scope.getByLabel('Конец периода (не включён)',{exact:true});
      await start.fill(c.LOCAL_PERIOD.start);await end.fill(c.LOCAL_PERIOD.end);await expect(start).toHaveValue(c.LOCAL_PERIOD.start);await expect(end).toHaveValue(c.LOCAL_PERIOD.end);
      const facts=await uiReport('/api/v1/analytics/shift',()=>scope.getByRole('button',{name:'Показать факты',exact:true}).click());
      c.historicalCounts(facts.provenance);c.check(facts.orders.length===540&&facts.totals_available===true,'CANONICAL_FACTS_REQUIRED');
      c.check(c.stable(facts.orders.map(x=>x.order.id).sort())===c.stable(before.order_ids),'ACTUAL_DATABASE_ORDER_IDS_REQUIRED');
      selected=facts.orders.find(x=>x.attempts.some(a=>a.submission.payload.after_photo_ids.length>0));c.check(selected&&before.order_ids.includes(selected.order.id),'OBSERVED_HISTORICAL_ORDER_REQUIRED');
      e.selected={order_id:selected.order.id,order_number:String(selected.order.number),attempts:selected.attempts.length,photos:selected.attempts.reduce((n,a)=>n+a.submission.payload.after_photo_ids.length,0)};
      e.facts={body_sha256:c.digest(facts),order_ids_sha256:c.digest(before.order_ids),history_sha256:fixturesafeHistory(facts.provenance),identity_mapping_sha256:facts.provenance.historical_evidence.identity_mapping_sha256};
      c.check(e.facts.identity_mapping_sha256===before.identity_mapping_sha256,'API_DATABASE_PROVENANCE_REQUIRED');
    });
    await stage(c.REQUIRED_STEPS[4],async()=>{
      markDownload('OPEN_SHIFT_REPORT','SHIFT_PDF');
      const report=await uiReport('/api/v1/reports/shift',()=>master.page.getByRole('button',{name:'Открыть отчёт смены / периода',exact:true}).click());
      c.historicalCounts(report.provenance);c.check(report.report_kind==='shift','SHIFT_REPORT_REQUIRED');
      markDownload('WAIT_SHIFT_REPORT_UI');await expect(master.page.getByRole('region',{name:'Выбранный отчёт',exact:true}).getByRole('heading',{name:'Защищённый отчёт смены / периода',exact:true})).toBeVisible();
      await download('shift','pdf');await download('shift','xlsx');
    });
    await stage(c.REQUIRED_STEPS[5],async()=>{
      const selector=master.page.getByRole('region',{name:'Аналитика и отчёты',exact:true}).getByRole('combobox',{name:'Наряд для отчёта',exact:true});
      await expect(selector).toHaveCount(1);c.check(c.stable(await selector.selectOption({value:selected.order.id}))===c.stable([selected.order.id]),'EXACT_ORDER_SELECTION_REQUIRED');await expect(selector).toHaveValue(selected.order.id);
      markDownload('OPEN_ORDER_REPORT','ORDER_PDF');
      const report=await uiReport(`/api/v1/reports/orders/${selected.order.id}`,()=>master.page.getByRole('button',{name:'Открыть отчёт наряда',exact:true}).click());
      c.check(report.report_kind==='order'&&c.stable(report.order)===c.stable(selected),'EXACT_ORDER_REPORT_REQUIRED');
      c.historicalCounts(report.provenance,1,e.selected.attempts,e.selected.photos);
      markDownload('WAIT_ORDER_REPORT_UI');await expect(master.page.getByRole('region',{name:'Выбранный отчёт',exact:true}).getByRole('heading',{name:`Защищённый отчёт: наряд №${selected.order.number}`,exact:true})).toBeVisible();
      await download('order','pdf');await download('order','xlsx');
    });
    await stage(c.REQUIRED_STEPS[6],async()=>{
      for(const name of ['Демо-время','Аналитика и отчёты'])await expect(executor.page.getByRole('button',{name,exact:true})).toHaveCount(0);
      for(const name of ['Синтетическое демо-время','Скачать выбранный отчёт'])await expect(executor.page.getByRole('region',{name,exact:true})).toHaveCount(0);
      const targets=[{method:'GET',path:'/api/v1/demo/clock'},{method:'POST',path:'/api/v1/demo/clock'},...e.downloads.map(x=>({method:'GET',path:x.path}))];
      for(const t of targets){
        const url=fixture.origin+t.path+(t.path==='/api/v1/demo/clock'?'':'?'+new URLSearchParams(c.PERIOD));
        const response=t.method==='POST'?await executor.context.request.post(url,{maxRedirects:0,headers:{Origin:fixture.origin,'X-CSRF-Token':executor.csrf},data:clock.command(e.clock[5].snapshot,'pause')}):await executor.context.request.get(url,{maxRedirects:0});
        if(t.method==='POST')network.executor_clock_posts++;
        protectedHeaders(response,t.path,403,t.path==='/api/v1/demo/clock');const body=await response.json();
        c.check(body.code==='FORBIDDEN'&&!['provenance','orders','order','domain_now','version'].some(k=>k in body),'EXECUTOR_SERVER_RESTRICTION_REQUIRED');
        e.restrictions.push({...t,status:403,code:'FORBIDDEN',no_protected_data:true,cache:'private,no-store'});
      }
      e.executor_ui_absent=true;
      // The forbidden executor POST must leave the clock version and mapping unchanged.
      const r=await master.context.request.get(`${fixture.origin}/api/v1/demo/clock`,{maxRedirects:0});protectedHeaders(r,'/api/v1/demo/clock',200,true);
      const snap=clock.snapshot(await r.json());clock.readAfter(e.clock[5].snapshot,snap,0);e.clock_after_restriction=snap;
    });
    await stage(c.REQUIRED_STEPS[7],async()=>{
      after=await observe();e.database_after=after;c.check(before.business_sha256===after.business_sha256&&c.stable(before.counts)===c.stable(after.counts),'BUSINESS_DATABASE_CHANGED');
      c.check(c.stable(network)===c.stable({blocked_external:0,blocked_mutation:0,login_posts:2,master_clock_posts:3,executor_clock_posts:1,export_gets:4}),'EXACT_NETWORK_COUNTS_REQUIRED');
      c.check(proof.sourceSha()===sourceSha&&c.stable(proof.fingerprint())===c.stable(hashes),'SOURCE_CHANGED_DURING_JOURNEY');
    });
    e.result='PASS';
  }catch{e.result='FAIL';}
  finally{
    expectedCommand=null;
    for(const context of contexts)await context.close().catch(()=>{e.result='FAIL';});
    e.network=network;e.finished_at=new Date().toISOString();
    const bytes=Buffer.from(JSON.stringify(e,null,2)+'\n');fs.writeFileSync(path.join(c.artifactDir(),'evidence.json'),bytes,{flag:'wx',mode:0o600});await info.attach('c113_evidence',{body:bytes,contentType:'application/json'});
  }
  c.check(e.result==='PASS','DOWNLOAD_CLOCK_JOURNEY_FAILED_SEE_SAFE_STAGE_RESULTS');
});
function fixturesafeHistory(p){return c.historicalCounts(p).history_sha256;}
