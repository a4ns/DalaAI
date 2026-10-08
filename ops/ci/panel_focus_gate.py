#!/usr/bin/env python3
"""Native Panel reset focus under StrictMode with synthetic props."""
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
PRODUCT='ff6784a399132e29958cfa615e733270627706c1'
SOURCE='25edea72dce27e597ba2c54b6f3404d8f73dfdb8'
BRANCH='refs/heads/validation/panel-focus-browser-20261008'
PROJECT='panel-reset-focus'
VIEWPORTS={'synthetic Panel reset focus 320x800','synthetic Panel reset focus 390x844','synthetic Panel reset focus 768x1024'}
TITLES={'newer focus in the reset event is preserved and the consumed request stays dead on polling', 'focused keyboard Reset unmounts, restores native search focus once without scrolling, and never replays on polls', 'access loss in the reset event removes the search and cannot revive its pending focus after access returns', 'filter changes, ordinary polls, and an unfocused reset do not request search focus', 'newer selected-order navigation owns history focus with no transient search restoration', 'navigation unmount in the reset event drops the request and remount does not steal focus'}


def run(argv,cwd,env,timeout=300):
    return subprocess.run(argv,cwd=cwd,env=env,capture_output=True,timeout=timeout,check=False)


def environment(source,harness):
    env={k:v for k,v in os.environ.items() if k in {'PATH','HOME','LANG','LC_ALL','TMPDIR','PLAYWRIGHT_BROWSERS_PATH'}}
    env.update(CI='1',UI_TEST_PORT='4176',UI_REVIEW_ROOT=str(source/'frontend'),UI_REVIEW_SHA=PRODUCT,
        DALA_PANEL_FOCUS_SOURCE=str(source),DALA_PANEL_FOCUS_TEST_SHA=SOURCE,DALA_PANEL_FOCUS_HARNESS_SHA=harness)
    return env


def contract():
    c=json.loads((ROOT/'ops/ci/panel_focus_contract.json').read_text())
    if (c.get('accepted') is not True or c.get('product_sha')!=PRODUCT or c.get('test_source_sha')!=SOURCE
        or c.get('case_count')!=18 or c.get('cases_per_viewport')!=6 or c.get('viewports')!=[[320,800],[390,844],[768,1024]]
        or len(c.get('files',{}))!=3 or len(c.get('product_dependencies',{}))!=13):raise ValueError('PANEL_FOCUS_EXACT_CONTRACT_REQUIRED')
    return c


def verify_source(source,c):
    env=environment(source,'source-check');head=run(['git','rev-parse','HEAD'],source,env,15)
    if not source.is_absolute() or head.returncode or head.stdout.decode().strip()!=SOURCE:raise ValueError('PANEL_FOCUS_EXACT_SOURCE_REQUIRED')
    changed=run(['git','diff','--exit-code','HEAD','--','frontend','backend'],source,env,15)
    extra=run(['git','ls-files','--others','--exclude-standard','--','frontend','backend'],source,env,15)
    if changed.returncode or extra.returncode or extra.stdout.strip():raise ValueError('PANEL_FOCUS_CLEAN_SOURCE_REQUIRED')
    diff=run(['git','diff','--name-status',PRODUCT,'HEAD','--','frontend','backend'],source,env,15)
    if diff.returncode or set(diff.stdout.decode().splitlines())!={'A\t'+p for p in c['files']}:raise ValueError('PANEL_FOCUS_PRODUCT_UNCHANGED_REQUIRED')
    for group in ('files','product_dependencies'):
        for name,digest in c[group].items():
            p=source/name
            if not name.startswith('frontend/') or '..' in Path(name).parts or p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:
                raise ValueError('PANEL_FOCUS_IMMUTABLE_BLOB_REQUIRED')
    package=json.loads((source/'frontend/package.json').read_text())
    if package.get('devDependencies',{}).get('@playwright/test')!='1.63.0':raise ValueError('PANEL_FOCUS_LOCKED_PLAYWRIGHT_REQUIRED')
    if any(p.name!='.env.example' for p in (source/'frontend').glob('.env*')):raise ValueError('PANEL_FOCUS_ENV_FILE_FORBIDDEN')


def harness():
    if os.environ.get('GITHUB_REF')!=BRANCH:raise ValueError('PANEL_FOCUS_EXACT_BRANCH_REQUIRED')
    result=run(['git','rev-parse','HEAD'],ROOT,os.environ,15);sha=result.stdout.decode().strip()
    if result.returncode or os.environ.get('GITHUB_SHA')!=sha or not re.fullmatch('[a-f0-9]{40}',sha):raise ValueError('PANEL_FOCUS_HARNESS_SHA_REQUIRED')
    paths=['ops/ci/panel_focus_gate.py','ops/ci/panel_focus_playwright.cjs','ops/ci/panel_focus_contract.json','ops/ci/panel_focus_tests.py','.github/workflows/panel-focus-browser.yml']
    if run(['git','diff','--exit-code','HEAD','--',*paths],ROOT,os.environ,15).returncode:raise ValueError('PANEL_FOCUS_HARNESS_CHANGED')
    extra=run(['git','ls-files','--others','--exclude-standard','--',*paths],ROOT,os.environ,15)
    if extra.returncode or extra.stdout.strip():raise ValueError('PANEL_FOCUS_HARNESS_UNTRACKED')
    return sha


def rows(data):
    found=[]
    def walk(suites,parents=()):
        for suite in suites:
            chain=(*parents,suite.get('title',''))
            for spec in suite.get('specs',[]):
                for test in spec.get('tests',[]):found.append((chain,spec,test))
            walk(suite.get('suites',[]),chain)
    walk(data.get('suites',[]));return found


def verify_report(data,sha):
    meta=data.get('config',{}).get('metadata',{})
    if (meta.get('scope')!='SYNTHETIC_PANEL_RESET_FOCUS_ONLY' or meta.get('serverMode')!='VITE_DEV_STRICTMODE_FIXTURE' or meta.get('testSource')!=SOURCE
        or meta.get('productSha')!=PRODUCT or meta.get('harnessSha')!=sha or data.get('errors')
        or data.get('stats',{}).get('expected')!=18 or any(data.get('stats',{}).get(k)!=0 for k in ('unexpected','flaky','skipped'))):
        raise ValueError('PANEL_FOCUS_COMPLETE_BOUND_REPORT_REQUIRED')
    found=rows(data);pairs=[]
    for chain,spec,test in found:
        groups=[name for name in chain if name in VIEWPORTS]
        if (len(groups)!=1 or spec.get('title') not in TITLES or Path(spec.get('file','')).name!='b-panel-reset-focus-acceptance.spec.ts'
            or test.get('projectName')!=PROJECT or test.get('expectedStatus')!='passed' or test.get('status')!='expected'
            or len(test.get('results',[]))!=1 or test['results'][0].get('status')!='passed'
            or test['results'][0].get('retry')!=0 or test['results'][0].get('errors')):raise ValueError('PANEL_FOCUS_FAILED_OR_FOREIGN_CASE')
        pairs.append((groups[0],spec['title']))
    if len(pairs)!=18 or set(pairs)!={(v,t) for v in VIEWPORTS for t in TITLES}:raise ValueError('PANEL_FOCUS_EXACT_MATRIX_REQUIRED')
    return [{'viewport':v.removeprefix('synthetic Panel reset focus '),'passed':6,'skipped':0,'retries':0} for v in sorted(VIEWPORTS)]


def diagnostic(data):
    result=[]
    for chain,spec,test in rows(data):
        if not any(r.get('status') in ('failed','timedOut','interrupted') for r in test.get('results',[])):continue
        if Path(spec.get('file','')).name!='b-panel-reset-focus-acceptance.spec.ts':continue
        group=next((v for v in chain if v in VIEWPORTS),'UNCLASSIFIED');title=spec.get('title')
        errors=[]
        def collect(value,depth=0):
            if depth>8 or not isinstance(value,dict):return
            for key in ('error','location'):
                item=value.get(key)
                if isinstance(item,dict):errors.append(item)
            for key in ('errors','steps'):
                for item in value.get(key,[])[:100] if isinstance(value.get(key),list) else []:
                    if isinstance(item,dict):errors.append(item);collect(item,depth+1)
        for item in test.get('results',[]):collect(item)
        text=' '.join(str(e.get('message','')) for e in errors)
        category='STRICT_LOCATOR' if 'strict mode violation' in text else 'TIMEOUT' if 'Timed out' in text or 'TimeoutError' in text else 'ASSERTION_OR_OPERATION_FAILED'
        lines={int(n) for e in errors for n in re.findall(r'b-panel-reset-focus-acceptance\.spec\.ts:(\d+):\d+',str(e.get('stack',''))+' '+str(e.get('message',''))) if 1<=int(n)<=2000}
        for error in errors:
            for location in (error,error.get('location',{})):
                if isinstance(location,dict) and Path(str(location.get('file',''))).name=='b-panel-reset-focus-acceptance.spec.ts' and type(location.get('line')) is int and 1<=location['line']<=2000:lines.add(location['line'])
        line=spec.get('line')
        if type(line) is int and 1<=line<=2000:lines.add(line)
        result.append({'viewport':group,'case':title if title in TITLES else 'UNCLASSIFIED','category':category,'source_lines':sorted(lines)[:5]})
    return result[:3]


def progress(data):
    expected={(v,t) for v in VIEWPORTS for t in TITLES};seen=set()
    output={v.removeprefix('synthetic Panel reset focus '):{'passed':0,'failed':0,'skipped':0,'not_run':0} for v in VIEWPORTS}
    for chain,spec,test in rows(data):
        group=next((v for v in chain if v in VIEWPORTS),None);key=(group,spec.get('title'))
        if key not in expected or key in seen or test.get('projectName')!=PROJECT:continue
        seen.add(key);results=test.get('results',[]);status=results[-1].get('status') if results else None
        category='passed' if status=='passed' else 'failed' if status in ('failed','timedOut','interrupted') else 'skipped' if status=='skipped' else 'not_run'
        output[group.removeprefix('synthetic Panel reset focus ')][category]+=1
    for group,_ in expected-seen:output[group.removeprefix('synthetic Panel reset focus ')]['not_run']+=1
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True);parser.add_argument('--check-inputs',action='store_true');args=parser.parse_args();source=args.source.resolve()
    summary={'schema_version':1,'status':'BLOCKED','stage':'exact_source','product_sha':PRODUCT,'test_source_sha':SOURCE,
        'scope':'SYNTHETIC_PANEL_RESET_FOCUS_ONLY','observed_at':datetime.now(timezone.utc).isoformat(),
        'resource_props':'SYNTHETIC','server_mode':'VITE_DEV_STRICTMODE_FIXTURE','native_focus_effects':'REQUIRED_BY_SCENARIOS',
        'api_db_provider':'NOT_RUN','physical_device':'NOT_RUN','C_gates':'NOT_INVOKED_OR_MODIFIED','deployment_performed':False,'full_cycle_green':False}
    code=1
    try:
        c=contract();verify_source(source,c)
        if args.check_inputs:print('PASS: exact Panel fixture and unchanged component source');return 0
        sha=harness();summary['harness_sha']=sha;env=environment(source,sha);front=source/'frontend';summary['stage']='source_types_and_build'
        if run(['npm','run','check'],front,env).returncode:raise ValueError('PANEL_FOCUS_APP_CHECK_FAILED')
        if run(['node',str(front/'node_modules/typescript/bin/tsc'),'-p','tests/tsconfig.json'],front,env,120).returncode:raise ValueError('PANEL_FOCUS_TEST_TYPES_FAILED')
        summary['source_checks']='PASS';summary['stage']='single_chromium_panel_focus_matrix'
        with tempfile.TemporaryDirectory(prefix='dalaai-panel-focus-private-') as output:
            env['DALA_PANEL_FOCUS_OUTPUT']=output
            result=run(['node',str(front/'node_modules/@playwright/test/cli.js'),'test','--config',str(ROOT/'ops/ci/panel_focus_playwright.cjs')],front,env,600)
            if len(result.stdout)>8*1024*1024:raise ValueError('PANEL_FOCUS_REPORT_TOO_LARGE')
            try:data=json.loads(result.stdout)
            except Exception:raise ValueError('PANEL_FOCUS_REPORT_UNAVAILABLE') from None
            summary['observed_cases']=progress(data);summary['diagnostic']=diagnostic(data);summary['viewports']=verify_report(data,sha)
            if result.returncode:raise ValueError('PANEL_FOCUS_RUNNER_NONZERO')
        verify_source(source,c)
        if harness()!=sha:raise ValueError('PANEL_FOCUS_HARNESS_CHANGED')
        summary['status']='PASS_SYNTHETIC_PANEL_FOCUS_ONLY';summary['stage']='completed';summary['native_focus_effects']='VERIFIED_WITH_SYNTHETIC_FIXTURE';code=0
    except ValueError as error:
        value=str(error);summary['reason_code']=value if re.fullmatch('PANEL_FOCUS_[A-Z_]+',value) else 'PANEL_FOCUS_INVALID_REPORT';summary['status']='BLOCKED' if summary['stage']=='exact_source' else 'FAIL'
    except Exception:summary['status']='FAIL';summary['reason_code']='PANEL_FOCUS_RUNNER_FAILURE'
    if args.check_inputs:print('BLOCKED: Panel source check');return 1
    (ROOT/'panel-focus-browser-summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2));return code


if __name__=='__main__':raise SystemExit(main())
