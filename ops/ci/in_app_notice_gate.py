#!/usr/bin/env python3
"""Mounted in-app notices and unchanged polling commands with synthetic HTTP."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[2]
BRANCH='refs/heads/validation/in-app-notices-browser-20261008'
SCOPE='SYNTHETIC_MOUNTED_IN_APP_NOTICES_ONLY'
PROFILE={'name':'Chromium390','width':390,'height':844,'deviceScaleFactor':1,'isMobile':False,'hasTouch':False}
COUNTS={'in-app-notice-chromium':18}
TOTAL=sum(COUNTS.values())


def run(argv,cwd,env,timeout=300):
    return subprocess.run(argv,cwd=cwd,env=env,capture_output=True,timeout=timeout,check=False)


def environment(source,c,harness):
    env={k:v for k,v in os.environ.items() if k in {'PATH','HOME','LANG','LC_ALL','TMPDIR','PLAYWRIGHT_BROWSERS_PATH'}}
    env.update(CI='1',UI_TEST_PORT='4176',UI_REVIEW_ROOT=str(source/'frontend'),UI_REVIEW_SHA=c['product_sha'],
        DALA_IN_APP_NOTICE_SOURCE=str(source),DALA_IN_APP_NOTICE_PRODUCT_SHA=c['product_sha'],DALA_IN_APP_NOTICE_TEST_SHA=c['test_source_sha'],DALA_IN_APP_NOTICE_HARNESS_SHA=harness)
    return env


def contract():
    c=json.loads((ROOT/'ops/ci/in_app_notice_contract.json').read_text())
    if (c.get('accepted') is not True or any(not re.fullmatch('[a-f0-9]{40}',c.get(k,'')) for k in ('base_sha','product_sha','test_source_sha'))
        or any(type(value) is not int or value<1 for value in COUNTS.values()) or c.get('case_counts')!=COUNTS or len(c.get('cases',[]))!=TOTAL or len(c.get('files',{}))!=6):raise ValueError('IN_APP_NOTICE_EXACT_CONTRACT_REQUIRED')
    pairs={(r['project'],r['file'],r['title']) for r in c['cases']}
    if len(pairs)!=TOTAL or {p:sum(row[0]==p for row in pairs) for p in COUNTS}!=COUNTS:raise ValueError('IN_APP_NOTICE_EXACT_CASE_MATRIX_REQUIRED')
    return c


def verify_source(source,c):
    env=environment(source,c,'source-check');head=run(['git','rev-parse','HEAD'],source,env,15)
    if head.returncode or head.stdout.decode().strip()!=c['test_source_sha']:raise ValueError('IN_APP_NOTICE_EXACT_SOURCE_REQUIRED')
    changed=run(['git','diff','--exit-code','HEAD','--','frontend','backend'],source,env,15)
    extra=run(['git','ls-files','--others','--exclude-standard','--','frontend','backend'],source,env,15)
    if changed.returncode or extra.returncode or extra.stdout.strip():raise ValueError('IN_APP_NOTICE_CLEAN_SOURCE_REQUIRED')
    diff=run(['git','diff','--name-status',c['base_sha'],'HEAD','--','frontend','backend'],source,env,15)
    if diff.returncode or set(diff.stdout.decode().splitlines())!=set(c['source_diff']):raise ValueError('IN_APP_NOTICE_EXACT_PRODUCT_SCOPE_REQUIRED')
    product=run(['git','diff','--exit-code',c['product_sha'],'HEAD','--','frontend/src','frontend/package.json','frontend/package-lock.json','backend'],source,env,15)
    if product.returncode:raise ValueError('IN_APP_NOTICE_PRODUCT_IDENTITY_REQUIRED')
    for group in ('files','product_dependencies'):
        for name,digest in c[group].items():
            file=source/name
            if not name.startswith('frontend/') or '..' in Path(name).parts or file.is_symlink() or not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=digest:raise ValueError('IN_APP_NOTICE_IMMUTABLE_BLOB_REQUIRED')
    package=json.loads((source/'frontend/package.json').read_text())
    if package.get('devDependencies',{}).get('@playwright/test')!='1.63.0':raise ValueError('IN_APP_NOTICE_LOCKED_PLAYWRIGHT_REQUIRED')
    if any(p.name!='.env.example' for p in (source/'frontend').glob('.env*')):raise ValueError('IN_APP_NOTICE_ENV_FILE_FORBIDDEN')


def harness():
    if os.environ.get('GITHUB_REF')!=BRANCH:raise ValueError('IN_APP_NOTICE_EXACT_BRANCH_REQUIRED')
    env={k:v for k,v in os.environ.items() if k in {'PATH','HOME','LANG','LC_ALL','TMPDIR'}}
    result=run(['git','rev-parse','HEAD'],ROOT,env,15);sha=result.stdout.decode().strip()
    if result.returncode or os.environ.get('GITHUB_SHA')!=sha or not re.fullmatch('[a-f0-9]{40}',sha):raise ValueError('IN_APP_NOTICE_HARNESS_SHA_REQUIRED')
    paths=['ops/ci/in_app_notice_gate.py','ops/ci/in_app_notice_contract.json','ops/ci/in_app_notice_playwright.cjs','ops/ci/in_app_notice_tests.py','.github/workflows/in-app-notices-browser.yml']
    changed=run(['git','diff','--exit-code','HEAD','--',*paths],ROOT,env,15)
    extra=run(['git','ls-files','--others','--exclude-standard','--',*paths],ROOT,env,15)
    if changed.returncode or extra.returncode or extra.stdout.strip():raise ValueError('IN_APP_NOTICE_HARNESS_CHANGED')
    return sha


def rows(data):
    found=[]
    def walk(suites):
        for suite in suites:
            for spec in suite.get('specs',[]):
                for test in spec.get('tests',[]):found.append((spec,test))
            walk(suite.get('suites',[]))
    walk(data.get('suites',[]));return found


def verify_report(data,c,sha):
    meta=data.get('config',{}).get('metadata',{});stats=data.get('stats',{})
    if (meta.get('scope')!=SCOPE or meta.get('testSource')!=c['test_source_sha'] or meta.get('productSha')!=c['product_sha'] or meta.get('harnessSha')!=sha
        or meta.get('serverMode')!='PRODUCTION_BUILD_PREVIEW' or meta.get('browserProfile')!=PROFILE or data.get('errors') or stats.get('expected')!=TOTAL
        or any(stats.get(k)!=0 for k in ('unexpected','flaky','skipped'))):raise ValueError('IN_APP_NOTICE_COMPLETE_BOUND_REPORT_REQUIRED')
    pairs=[]
    for spec,test in rows(data):
        pair=(test.get('projectName'),spec.get('file'),spec.get('title'));pairs.append(pair)
        if (test.get('expectedStatus')!='passed' or test.get('status')!='expected' or len(test.get('results',[]))!=1
            or test['results'][0].get('status')!='passed' or test['results'][0].get('retry')!=0 or test['results'][0].get('errors')):raise ValueError('IN_APP_NOTICE_FAILED_OR_RETRIED_CASE')
    expected={(r['project'],r['file'],r['title']) for r in c['cases']}
    if len(pairs)!=TOTAL or set(pairs)!=expected:raise ValueError('IN_APP_NOTICE_EXACT_CASE_MATRIX_REQUIRED')
    return {'notice_cases':11,'poll_command_cases':7,'mounted_browser_cases':18,'skipped':0,'retries':0}


def diagnostic(data,c):
    expected={(r['project'],r['file'],r['title']) for r in c['cases']};output=[]
    for spec,test in rows(data):
        failed=[r for r in test.get('results',[]) if r.get('status') in ('failed','timedOut','interrupted')]
        if not failed:continue
        key=(test.get('projectName'),spec.get('file'),spec.get('title'))
        if key not in expected:continue
        errors=[]
        def collect(value,depth=0):
            if depth>8 or not isinstance(value,dict):return
            for key in ('error','location'):
                item=value.get(key)
                if isinstance(item,dict):errors.append(item)
            for key in ('errors','steps'):
                for item in value.get(key,[])[:100] if isinstance(value.get(key),list) else []:
                    if isinstance(item,dict):errors.append(item);collect(item,depth+1)
        for result in failed:collect(result)
        message=' '.join(str(e.get('message','')) for e in errors)
        category='STRICT_LOCATOR' if 'strict mode violation' in message else 'TIMEOUT' if 'Timed out' in message or 'TimeoutError' in message else 'ASSERTION_OR_OPERATION_FAILED'
        lines={int(n) for e in errors for n in re.findall(r'(?:in-app-notifications|poll-command-lock)\.spec\.ts:(\d+):\d+',str(e.get('stack',''))+' '+str(e.get('message',''))) if 1<=int(n)<=1000}
        for error in errors:
            locations=[error,error.get('location',{})]
            for location in locations:
                if isinstance(location,dict) and Path(str(location.get('file',''))).name in {'in-app-notifications.spec.ts','poll-command-lock.spec.ts'} and type(location.get('line')) is int and 1<=location['line']<=1000:lines.add(location['line'])
        line=spec.get('line')
        if type(line) is int and 1<=line<=1000:lines.add(line)
        output.append({'project':key[0],'case':key[2],'category':category,'source_lines':sorted(lines)[:5]})
    return output[:3]


def progress(data,c):
    expected={(r['project'],r['file'],r['title']) for r in c['cases']};seen=set()
    output={p:{'passed':0,'failed':0,'skipped':0,'not_run':0} for p in COUNTS}
    for spec,test in rows(data):
        key=(test.get('projectName'),spec.get('file'),spec.get('title'))
        if key not in expected or key in seen:continue
        seen.add(key);results=test.get('results',[]);status=results[-1].get('status') if results else None
        category='passed' if status=='passed' else 'failed' if status in ('failed','timedOut','interrupted') else 'skipped' if status=='skipped' else 'not_run'
        output[key[0]][category]+=1
    for project,_,_ in expected-seen:output[project]['not_run']+=1
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True);parser.add_argument('--check-inputs',action='store_true');args=parser.parse_args();source=args.source.resolve()
    summary={'schema_version':1,'status':'BLOCKED','stage':'exact_source','scope':SCOPE,'observed_at':datetime.now(timezone.utc).isoformat(),
        'http_responses':'SYNTHETIC_INTERCEPTED','server_mode':'PRODUCTION_BUILD_PREVIEW','physical_device':'NOT_RUN','backend_authorization':'NOT_RUN',
        'provider_delivery':'NOT_RUN','C_gates':'NOT_INVOKED_OR_MODIFIED','deployment_performed':False,'full_cycle_green':False}
    code=1
    try:
        c=contract();summary.update(product_sha=c['product_sha'],test_source_sha=c['test_source_sha']);verify_source(source,c)
        if args.check_inputs:print('PASS: exact in-app-notice product and scenario source');return 0
        sha=harness();summary['harness_sha']=sha;env=environment(source,c,sha);front=source/'frontend';summary['stage']='source_types_and_build'
        if run(['npm','run','check'],front,env).returncode:raise ValueError('IN_APP_NOTICE_APP_CHECK_FAILED')
        if not (front/'dist/index.html').is_file() or (front/'dist/index.html').is_symlink():raise ValueError('IN_APP_NOTICE_PRODUCTION_BUILD_REQUIRED')
        if run(['node',str(front/'node_modules/typescript/bin/tsc'),'-p','tests/tsconfig.json'],front,env,120).returncode:raise ValueError('IN_APP_NOTICE_TEST_TYPES_FAILED')
        summary['source_checks']='PASS';summary['stage']='mounted_notice_and_poll_scenarios'
        with tempfile.TemporaryDirectory(prefix='dalaai-in-app-notice-private-') as output:
            env['DALA_IN_APP_NOTICE_OUTPUT']=output
            result=run(['node',str(front/'node_modules/@playwright/test/cli.js'),'test','--config',str(ROOT/'ops/ci/in_app_notice_playwright.cjs')],front,env,600)
            if len(result.stdout)>8*1024*1024:raise ValueError('IN_APP_NOTICE_REPORT_TOO_LARGE')
            try:data=json.loads(result.stdout)
            except Exception:raise ValueError('IN_APP_NOTICE_REPORT_UNAVAILABLE') from None
            summary['observed_cases']=progress(data,c);summary['diagnostic']=diagnostic(data,c);summary['cases']=verify_report(data,c,sha)
            if result.returncode:raise ValueError('IN_APP_NOTICE_RUNNER_NONZERO')
        verify_source(source,c)
        if harness()!=sha:raise ValueError('IN_APP_NOTICE_HARNESS_CHANGED')
        summary.update(status='PASS_SYNTHETIC_MOUNTED_IN_APP_NOTICE_ONLY',stage='completed',default_browser_profile=PROFILE,authored_viewport_override={'notice_case':'three visible notices, safe mobile width, reduced motion and no delayed backlog','width':360,'height':732});code=0
    except ValueError as error:
        value=str(error);summary['reason_code']=value if re.fullmatch('IN_APP_NOTICE_[A-Z_]+',value) else 'IN_APP_NOTICE_INVALID_REPORT';summary['status']='BLOCKED' if summary['stage']=='exact_source' else 'FAIL'
    except Exception:summary['status']='FAIL';summary['reason_code']='IN_APP_NOTICE_RUNNER_FAILURE'
    if args.check_inputs:print('BLOCKED: in-app-notice source input');return 1
    (ROOT/'in-app-notice-summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2));return code


if __name__=='__main__':raise SystemExit(main())
