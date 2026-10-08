'use strict';
const path=require('node:path'),{createRequire}=require('node:module');
const source=process.env.DALA_POLL_GEOMETRY_SOURCE,output=process.env.DALA_POLL_GEOMETRY_OUTPUT;
if(!path.isAbsolute(source||'')||!path.isAbsolute(output||'')||process.env.DEBUG||process.env.PWDEBUG||process.env.NODE_OPTIONS)throw new Error('POLL_GEOMETRY_FIXED_RUNNER_REQUIRED');
const frontend=path.join(source,'frontend'),pw=createRequire(path.join(frontend,'package.json'))('@playwright/test');
module.exports=pw.defineConfig({
  testDir:path.join(frontend,'tests'),testMatch:'browser/quiet-refresh-geometry.spec.ts',outputDir:output,
  forbidOnly:true,fullyParallel:false,workers:1,retries:0,maxFailures:1,timeout:30000,
  expect:{timeout:5000},reporter:[['json']],
  metadata:{scope:'SYNTHETIC_QUIET_REFRESH_GEOMETRY_ONLY',testSource:process.env.DALA_POLL_GEOMETRY_TEST_SHA,
    productSha:'6fa27276f14ef31757cb0da5ee9d7acc15789111',harnessSha:process.env.DALA_POLL_GEOMETRY_HARNESS_SHA},
  use:{baseURL:'http://127.0.0.1:4176',locale:'ru-RU',timezoneId:'Asia/Almaty',browserName:'chromium',
    serviceWorkers:'block',ignoreHTTPSErrors:false,trace:'off',screenshot:'off',video:'off',
    viewport:{width:390,height:844},isMobile:false,hasTouch:false,deviceScaleFactor:1},
  projects:[{name:'quiet-refresh-geometry'}],
  webServer:{command:'npm run dev -- --port 4176',cwd:frontend,url:'http://127.0.0.1:4176',
    reuseExistingServer:false,timeout:30000,stdout:'ignore',stderr:'pipe'},
});
