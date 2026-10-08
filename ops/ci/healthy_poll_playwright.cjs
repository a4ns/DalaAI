'use strict';
const path=require('node:path'),{createRequire}=require('node:module');
const source=process.env.DALA_HEALTHY_POLL_SOURCE,output=process.env.DALA_HEALTHY_POLL_OUTPUT;
if(!path.isAbsolute(source||'')||!path.isAbsolute(output||'')||process.env.DEBUG||process.env.PWDEBUG||process.env.NODE_OPTIONS)throw new Error('HEALTHY_POLL_FIXED_RUNNER_REQUIRED');
const frontend=path.join(source,'frontend'),pw=createRequire(path.join(frontend,'package.json'))('@playwright/test');
module.exports=pw.defineConfig({
  testDir:path.join(frontend,'tests'),outputDir:output,forbidOnly:true,fullyParallel:false,workers:1,retries:0,maxFailures:1,timeout:30000,
  expect:{timeout:5000},reporter:[['json']],
  metadata:{scope:'SYNTHETIC_MOUNTED_HEALTHY_POLL_COMMANDS_ONLY',serverMode:'PRODUCTION_BUILD_PREVIEW',testSource:process.env.DALA_HEALTHY_POLL_TEST_SHA,
    productSha:process.env.DALA_HEALTHY_POLL_PRODUCT_SHA,harnessSha:process.env.DALA_HEALTHY_POLL_HARNESS_SHA,
    browserProfile:{name:'Chromium390',width:390,height:844,deviceScaleFactor:1,isMobile:false,hasTouch:false}},
  use:{baseURL:'http://127.0.0.1:4176',locale:'ru-RU',timezoneId:'Asia/Almaty',browserName:'chromium',
    serviceWorkers:'block',ignoreHTTPSErrors:false,trace:'off',screenshot:'off',video:'off',viewport:{width:390,height:844},isMobile:false,hasTouch:false,deviceScaleFactor:1},
  projects:[
    {name:'healthy-poll-source',testMatch:'node/healthy-order-poll.spec.ts'},
    {name:'healthy-poll-chromium',testMatch:'browser/poll-command-lock.spec.ts'},
  ],
  webServer:{command:'npm run preview -- --port 4176',cwd:frontend,url:'http://127.0.0.1:4176',
    reuseExistingServer:false,timeout:30000,stdout:'ignore',stderr:'pipe'},
});
