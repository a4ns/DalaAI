'use strict';
const path=require('node:path'),{createRequire}=require('node:module');
const source=process.env.DALA_BEFORE_PHOTO_SOURCE,output=process.env.DALA_BEFORE_PHOTO_OUTPUT;
if(!path.isAbsolute(source||'')||!path.isAbsolute(output||'')||process.env.DEBUG||process.env.PWDEBUG||process.env.NODE_OPTIONS)throw new Error('BEFORE_PHOTO_FIXED_RUNNER_REQUIRED');
const frontend=path.join(source,'frontend'),pw=createRequire(path.join(frontend,'package.json'))('@playwright/test');
const device=pw.devices['Pixel 9'];
if(!device||device.viewport.width!==360||device.viewport.height!==732||device.deviceScaleFactor!==3||device.isMobile!==true||device.hasTouch!==true||!device.userAgent.includes('Android 14'))throw new Error('BEFORE_PHOTO_PINNED_ANDROID_DESCRIPTOR_REQUIRED');
module.exports=pw.defineConfig({
  testDir:path.join(frontend,'tests'),outputDir:output,forbidOnly:true,fullyParallel:false,workers:1,retries:0,maxFailures:1,timeout:30000,
  expect:{timeout:5000},reporter:[['json']],
  metadata:{scope:'SYNTHETIC_MOUNTED_BEFORE_PHOTO_ANDROID_EMULATION_ONLY',testSource:process.env.DALA_BEFORE_PHOTO_TEST_SHA,
    productSha:process.env.DALA_BEFORE_PHOTO_PRODUCT_SHA,harnessSha:process.env.DALA_BEFORE_PHOTO_HARNESS_SHA,
    androidDescriptor:{name:'Pixel 9',width:360,height:732,deviceScaleFactor:3,isMobile:true,hasTouch:true}},
  use:{baseURL:'http://127.0.0.1:4176',locale:'ru-RU',timezoneId:'Asia/Almaty',browserName:'chromium',
    serviceWorkers:'block',ignoreHTTPSErrors:false,trace:'off',screenshot:'off',video:'off'},
  projects:[
    {name:'before-photo-source',testMatch:'node/executor-before-photos.spec.ts'},
    {name:'before-photo-android',testMatch:'browser/executor-before-photos.spec.ts',use:{...device,browserName:'chromium'}},
  ],
  webServer:{command:'npm run dev -- --port 4176',cwd:frontend,url:'http://127.0.0.1:4176',
    reuseExistingServer:false,timeout:30000,stdout:'ignore',stderr:'pipe'},
});
