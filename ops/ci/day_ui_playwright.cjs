'use strict';
const path=require('node:path'),{createRequire}=require('node:module');
const source=process.env.DALA_DAY_UI_SOURCE,output=process.env.DALA_DAY_UI_OUTPUT;
if(!path.isAbsolute(source||'')||!path.isAbsolute(output||'')||process.env.DEBUG||process.env.PWDEBUG||process.env.NODE_OPTIONS)throw new Error('DAY_UI_FIXED_RUNNER_REQUIRED');
const frontend=path.join(source,'frontend'),pw=createRequire(path.join(frontend,'package.json'))('@playwright/test');
module.exports=pw.defineConfig({
  testDir:path.join(frontend,'tests'),testIgnore:'**/.artifacts/**',outputDir:output,
  forbidOnly:true,fullyParallel:false,workers:1,retries:0,maxFailures:1,timeout:30000,
  expect:{timeout:5000},reporter:[['json']],
  metadata:{reviewedSha:process.env.UI_REVIEW_SHA,harnessSha:process.env.DALA_DAY_UI_HARNESS_SHA,
    scope:'SYNTHETIC_RESPONSIVE_CHROMIUM_ONLY'},
  use:{baseURL:'http://127.0.0.1:4176',locale:'ru-RU',timezoneId:'Asia/Almaty',browserName:'chromium',
    serviceWorkers:'block',ignoreHTTPSErrors:false,trace:'off',screenshot:'off',video:'off',
    isMobile:false,hasTouch:false,deviceScaleFactor:1},
  projects:[{name:'independent-source',testMatch:'node/**/*.spec.ts'},
    ...[[320,800],[390,844],[768,1024]].map(([width,height])=>({name:`viewport-${width}`,testMatch:'browser/**/*.spec.ts',
      use:{viewport:{width,height}},metadata:{width,height,evidence:'synthetic viewport; not a physical or Android device'}}))],
  webServer:{command:'npm run dev -- --port 4176',cwd:frontend,url:'http://127.0.0.1:4176',
    reuseExistingServer:false,timeout:30000,stdout:'ignore',stderr:'pipe'},
});
