#!/usr/bin/env python3
"""Exact source and mounted before-photo cases with intercepted synthetic HTTP."""
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
BRANCH='refs/heads/validation/before-photo-browser-20261008'
SCOPE='SYNTHETIC_MOUNTED_BEFORE_PHOTO_ANDROID_EMULATION_ONLY'
DESCRIPTOR={'name':'Pixel 9','width':360,'height':732,'deviceScaleFactor':3,'isMobile':True,'hasTouch':True}
COUNTS={'before-photo-source':21,'before-photo-android':8}


def run(argv,cwd,env,timeout=300):
    return subprocess.run(argv,cwd=cwd,env=env,capture_output=True,timeout=timeout,check=False)


def environment(source,c,harness):
    env={k:v for k,v in os.environ.items() if k in {'PATH','HOME','LANG','LC_ALL','TMPDIR','PLAYWRIGHT_BROWSERS_PATH'}}
    env.update(CI='1',UI_TEST_PORT='4176',UI_REVIEW_ROOT=str(source/'frontend'),UI_REVIEW_SHA=c['product_sha'],
        DALA_BEFORE_PHOTO_SOURCE=str(source),DALA_BEFORE_PHOTO_PRODUCT_SHA=c['product_sha'],DALA_BEFORE_PHOTO_TEST_SHA=c['test_source_sha'],DALA_BEFORE_PHOTO_HARNESS_SHA=harness)
    return env


def contract():
    c=json.loads((ROOT/'ops/ci/before_photo_contract.json').read_text())
    if (c.get('accepted') is not True or any(not re.fullmatch('[a-f0-9]{40}',c.get(k,'')) for k in ('base_sha','product_sha','test_source_sha'))
        or c.get('case_counts')!=COUNTS or len(c.get('cases',[]))!=29 or len(c.get('files',{}))!=8):raise ValueError('BEFORE_PHOTO_EXACT_CONTRACT_REQUIRED')
    pairs={(r['project'],r['file'],r['title']) for r in c['cases']}
    if len(pairs)!=29 or {p:sum(row[0]==p for row in pairs) for p in COUNTS}!=COUNTS:raise ValueError('BEFORE_PHOTO_EXACT_CASE_MATRIX_REQUIRED')
    return c


def verify_source(source,c):
    env=environment(source,c,'source-check');head=run(['git','rev-parse','HEAD'],source,env,15)
    if head.returncode or head.stdout.decode().strip()!=c['test_source_sha']:raise ValueError('BEFORE_PHOTO_EXACT_SOURCE_REQUIRED')
    changed=run(['git','diff','--exit-code','HEAD','--','frontend','backend'],source,env,15)
    extra=run(['git','ls-files','--others','--exclude-standard','--','frontend','backend'],source,env,15)
    if changed.returncode or extra.returncode or extra.stdout.strip():raise ValueError('BEFORE_PHOTO_CLEAN_SOURCE_REQUIRED')
    diff=run(['git','diff','--name-status',c['base_sha'],'HEAD','--','frontend','backend'],source,env,15)
    if diff.returncode or set(diff.stdout.decode().splitlines())!=set(c['source_diff']):raise ValueError('BEFORE_PHOTO_EXACT_PRODUCT_SCOPE_REQUIRED')
    product=run(['git','diff','--exit-code',c['product_sha'],'HEAD','--','frontend/src','frontend/package.json','frontend/package-lock.json','backend'],source,env,15)
    if product.returncode:raise ValueError('BEFORE_PHOTO_PRODUCT_IDENTITY_REQUIRED')
    for group in ('files','product_dependencies'):
        for name,digest in c[group].items():
            file=source/name
            if not name.startswith('frontend/') or '..' in Path(name).parts or file.is_symlink() or not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=digest:raise ValueError('BEFORE_PHOTO_IMMUTABLE_BLOB_REQUIRED')
    package=json.loads((source/'frontend/package.json').read_text())
    if package.get('devDependencies',{}).get('@playwright/test')!='1.63.0':raise ValueError('BEFORE_PHOTO_LOCKED_PLAYWRIGHT_REQUIRED')
    if any(p.name!='.env.example' for p in (source/'frontend').glob('.env*')):raise ValueError('BEFORE_PHOTO_ENV_FILE_FORBIDDEN')


def harness():
    if os.environ.get('GITHUB_REF')!=BRANCH:raise ValueError('BEFORE_PHOTO_EXACT_BRANCH_REQUIRED')
    env={k:v for k,v in os.environ.items() if k in {'PATH','HOME','LANG','LC_ALL','TMPDIR'}}
    result=run(['git','rev-parse','HEAD'],ROOT,env,15);sha=result.stdout.decode().strip()
    if result.returncode or os.environ.get('GITHUB_SHA')!=sha or not re.fullmatch('[a-f0-9]{40}',sha):raise ValueError('BEFORE_PHOTO_HARNESS_SHA_REQUIRED')
    paths=['ops/ci/before_photo_gate.py','ops/ci/before_photo_contract.json','ops/ci/before_photo_playwright.cjs','ops/ci/before_photo_tests.py','.github/workflows/before-photo-browser.yml']
    changed=run(['git','diff','--exit-code','HEAD','--',*paths],ROOT,env,15)
    extra=run(['git','ls-files','--others','--exclude-standard','--',*paths],ROOT,env,15)
    if changed.returncode or extra.returncode or extra.stdout.strip():raise ValueError('BEFORE_PHOTO_HARNESS_CHANGED')
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
        or meta.get('androidDescriptor')!=DESCRIPTOR or data.get('errors') or stats.get('expected')!=29
        or any(stats.get(k)!=0 for k in ('unexpected','flaky','skipped'))):raise ValueError('BEFORE_PHOTO_COMPLETE_BOUND_REPORT_REQUIRED')
    pairs=[]
    for spec,test in rows(data):
        pair=(test.get('projectName'),spec.get('file'),spec.get('title'));pairs.append(pair)
        if (test.get('expectedStatus')!='passed' or test.get('status')!='expected' or len(test.get('results',[]))!=1
            or test['results'][0].get('status')!='passed' or test['results'][0].get('retry')!=0 or test['results'][0].get('errors')):raise ValueError('BEFORE_PHOTO_FAILED_OR_RETRIED_CASE')
    expected={(r['project'],r['file'],r['title']) for r in c['cases']}
    if len(pairs)!=29 or set(pairs)!=expected:raise ValueError('BEFORE_PHOTO_EXACT_CASE_MATRIX_REQUIRED')
    return {'source_cases':21,'mounted_android_cases':8,'skipped':0,'retries':0}


def diagnostic(data,c):
    expected={(r['project'],r['file'],r['title']) for r in c['cases']};output=[]
    for spec,test in rows(data):
        if test.get('status')=='expected':continue
        key=(test.get('projectName'),spec.get('file'),spec.get('title'))
        if key not in expected:continue
        errors=[e for r in test.get('results',[]) for e in r.get('errors',[]) if isinstance(e,dict)]
        message=' '.join(str(e.get('message','')) for e in errors)
        category='STRICT_LOCATOR' if 'strict mode violation' in message else 'TIMEOUT' if 'Timed out' in message or 'TimeoutError' in message else 'ASSERTION_OR_OPERATION_FAILED'
        lines={int(n) for e in errors for n in re.findall(r'executor-before-photos\.spec\.ts:(\d+):\d+',str(e.get('stack',''))) if 1<=int(n)<=1000}
        line=spec.get('line')
        if type(line) is int and 1<=line<=1000:lines.add(line)
        output.append({'project':key[0],'case':key[2],'category':category,'source_lines':sorted(lines)[:5]})
    return output[:3]


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True);parser.add_argument('--check-inputs',action='store_true');args=parser.parse_args();source=args.source.resolve()
    summary={'schema_version':1,'status':'BLOCKED','stage':'exact_source','scope':SCOPE,'observed_at':datetime.now(timezone.utc).isoformat(),
        'http_responses':'SYNTHETIC_INTERCEPTED','image_decode':'REQUIRED_BY_SCENARIOS','physical_device':'NOT_RUN','backend_authorization':'NOT_RUN',
        'stored_attachments':'NOT_RUN','provider_delivery':'NOT_RUN','C_gates':'NOT_INVOKED_OR_MODIFIED','deployment_performed':False,'full_cycle_green':False}
    code=1
    try:
        c=contract();summary.update(product_sha=c['product_sha'],test_source_sha=c['test_source_sha']);verify_source(source,c)
        if args.check_inputs:print('PASS: exact before-photo product and scenario source');return 0
        sha=harness();summary['harness_sha']=sha;env=environment(source,c,sha);front=source/'frontend';summary['stage']='source_types_and_build'
        if run(['npm','run','check'],front,env).returncode:raise ValueError('BEFORE_PHOTO_APP_CHECK_FAILED')
        if run(['node',str(front/'node_modules/typescript/bin/tsc'),'-p','tests/tsconfig.json'],front,env,120).returncode:raise ValueError('BEFORE_PHOTO_TEST_TYPES_FAILED')
        summary['source_checks']='PASS';summary['stage']='source_and_mounted_android_scenarios'
        with tempfile.TemporaryDirectory(prefix='dalaai-before-photo-private-') as output:
            env['DALA_BEFORE_PHOTO_OUTPUT']=output
            result=run(['node',str(front/'node_modules/@playwright/test/cli.js'),'test','--config',str(ROOT/'ops/ci/before_photo_playwright.cjs')],front,env,600)
            if len(result.stdout)>8*1024*1024:raise ValueError('BEFORE_PHOTO_REPORT_TOO_LARGE')
            try:data=json.loads(result.stdout)
            except Exception:raise ValueError('BEFORE_PHOTO_REPORT_UNAVAILABLE') from None
            summary['diagnostic']=diagnostic(data,c);summary['cases']=verify_report(data,c,sha)
            if result.returncode:raise ValueError('BEFORE_PHOTO_RUNNER_NONZERO')
        verify_source(source,c)
        if harness()!=sha:raise ValueError('BEFORE_PHOTO_HARNESS_CHANGED')
        summary.update(status='PASS_SYNTHETIC_MOUNTED_BEFORE_PHOTO_ONLY',stage='completed',image_decode='VERIFIED_WITH_SYNTHETIC_PNG',android_descriptor=DESCRIPTOR);code=0
    except ValueError as error:
        value=str(error);summary['reason_code']=value if re.fullmatch('BEFORE_PHOTO_[A-Z_]+',value) else 'BEFORE_PHOTO_INVALID_REPORT';summary['status']='BLOCKED' if summary['stage']=='exact_source' else 'FAIL'
    except Exception:summary['status']='FAIL';summary['reason_code']='BEFORE_PHOTO_RUNNER_FAILURE'
    if args.check_inputs:print('BLOCKED: before-photo source input');return 1
    (ROOT/'before-photo-summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2));return code


if __name__=='__main__':raise SystemExit(main())
