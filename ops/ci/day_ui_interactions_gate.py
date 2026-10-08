#!/usr/bin/env python3
"""Single-project native component interactions with explicitly synthetic parents."""
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
PRODUCT='8081a2984b2f27b909fa2b86cd9f10ffd01d1e11'
SOURCE='cbc8fd64764a7dcb8fe0dc45e2f8ce737fe0a3a9'
BRANCH='refs/heads/validation/day-ui-interactions-20261008'
PROJECT='focused-interactions'
VIEWPORTS={'owned effects 320x800','owned effects 390x844','owned effects 768x1024'}
TITLES={
 'explicit command owns one feedback scroll; its late result and a poll own none',
 'explicit retry owns exactly one additional scroll and no fresh command',
 'late result from a different selected scope and confirmation from polling cannot scroll',
 'canceling actual photo preparation announces cancellation and never adds the late decoded file',
 'an owned keyboard deletion returns focus to file selection exactly after removal',
 'late parent deletion and an already moved focus cannot steal user attention',
}


def run(argv,cwd,env,timeout=300):
    return subprocess.run(argv,cwd=cwd,env=env,capture_output=True,timeout=timeout,check=False)


def environment(source,harness):
    env={k:v for k,v in os.environ.items() if k in {'PATH','HOME','LANG','LC_ALL','TMPDIR','PLAYWRIGHT_BROWSERS_PATH'}}
    env.update(CI='1',UI_TEST_PORT='4176',UI_REVIEW_ROOT=str(source/'frontend'),UI_REVIEW_SHA=PRODUCT,
        DALA_INTERACTIONS_SOURCE=str(source),DALA_INTERACTIONS_TEST_SHA=SOURCE,DALA_INTERACTIONS_HARNESS_SHA=harness)
    return env


def contract():
    c=json.loads((ROOT/'ops/ci/day_ui_interactions_contract.json').read_text())
    if (c.get('accepted') is not True or c.get('product_sha')!=PRODUCT or c.get('test_source_sha')!=SOURCE
        or c.get('case_count')!=18 or c.get('cases_per_viewport')!=6 or c.get('viewports')!=[[320,800],[390,844],[768,1024]]
        or len(c.get('files',{}))!=3 or len(c.get('product_dependencies',{}))!=5):raise ValueError('INTERACTIONS_EXACT_CONTRACT_REQUIRED')
    return c


def verify_source(source,c):
    env=environment(source,'source-check');head=run(['git','rev-parse','HEAD'],source,env,15)
    if not source.is_absolute() or head.returncode or head.stdout.decode().strip()!=SOURCE:raise ValueError('INTERACTIONS_EXACT_SOURCE_REQUIRED')
    changed=run(['git','diff','--exit-code','HEAD','--','frontend','backend'],source,env,15)
    extra=run(['git','ls-files','--others','--exclude-standard','--','frontend','backend'],source,env,15)
    if changed.returncode or extra.returncode or extra.stdout.strip():raise ValueError('INTERACTIONS_CLEAN_SOURCE_REQUIRED')
    diff=run(['git','diff','--name-status',PRODUCT,'HEAD','--','frontend','backend'],source,env,15)
    if diff.returncode or set(diff.stdout.decode().splitlines())!={'A\t'+p for p in c['files']}:raise ValueError('INTERACTIONS_PRODUCT_UNCHANGED_REQUIRED')
    for group in ('files','product_dependencies'):
        for name,digest in c[group].items():
            p=source/name
            if not name.startswith('frontend/') or '..' in Path(name).parts or p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:
                raise ValueError('INTERACTIONS_IMMUTABLE_BLOB_REQUIRED')
    package=json.loads((source/'frontend/package.json').read_text())
    if package.get('devDependencies',{}).get('@playwright/test')!='1.63.0':raise ValueError('INTERACTIONS_LOCKED_PLAYWRIGHT_REQUIRED')
    if any(p.name!='.env.example' for p in (source/'frontend').glob('.env*')):raise ValueError('INTERACTIONS_ENV_FILE_FORBIDDEN')


def harness():
    if os.environ.get('GITHUB_REF')!=BRANCH:raise ValueError('INTERACTIONS_EXACT_BRANCH_REQUIRED')
    result=run(['git','rev-parse','HEAD'],ROOT,os.environ,15);sha=result.stdout.decode().strip()
    if result.returncode or os.environ.get('GITHUB_SHA')!=sha or not re.fullmatch('[a-f0-9]{40}',sha):raise ValueError('INTERACTIONS_HARNESS_SHA_REQUIRED')
    paths=['ops/ci/day_ui_interactions_gate.py','ops/ci/day_ui_interactions_playwright.cjs','ops/ci/day_ui_interactions_contract.json','ops/ci/day_ui_interactions_tests.py','.github/workflows/day-ui-interactions.yml']
    if run(['git','diff','--exit-code','HEAD','--',*paths],ROOT,os.environ,15).returncode:raise ValueError('INTERACTIONS_HARNESS_CHANGED')
    extra=run(['git','ls-files','--others','--exclude-standard','--',*paths],ROOT,os.environ,15)
    if extra.returncode or extra.stdout.strip():raise ValueError('INTERACTIONS_HARNESS_UNTRACKED')
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
    if (meta.get('scope')!='SYNTHETIC_NATIVE_COMPONENT_INTERACTIONS_ONLY' or meta.get('testSource')!=SOURCE
        or meta.get('productSha')!=PRODUCT or meta.get('harnessSha')!=sha or data.get('errors')
        or data.get('stats',{}).get('expected')!=18 or any(data.get('stats',{}).get(k)!=0 for k in ('unexpected','flaky','skipped'))):
        raise ValueError('INTERACTIONS_COMPLETE_BOUND_REPORT_REQUIRED')
    found=rows(data);pairs=[]
    for chain,spec,test in found:
        groups=[name for name in chain if name in VIEWPORTS]
        if (len(groups)!=1 or spec.get('title') not in TITLES or Path(spec.get('file','')).name!='interaction-owned-effects.spec.ts'
            or test.get('projectName')!=PROJECT or test.get('expectedStatus')!='passed' or test.get('status')!='expected'
            or len(test.get('results',[]))!=1 or test['results'][0].get('status')!='passed'
            or test['results'][0].get('retry')!=0 or test['results'][0].get('errors')):raise ValueError('INTERACTIONS_FAILED_OR_FOREIGN_CASE')
        pairs.append((groups[0],spec['title']))
    if len(pairs)!=18 or set(pairs)!={(v,t) for v in VIEWPORTS for t in TITLES}:raise ValueError('INTERACTIONS_EXACT_MATRIX_REQUIRED')
    return [{'viewport':v.removeprefix('owned effects '),'passed':6,'skipped':0,'retries':0} for v in sorted(VIEWPORTS)]


def diagnostic(data):
    result=[]
    for chain,spec,test in rows(data):
        if test.get('status')=='expected':continue
        if Path(spec.get('file','')).name!='interaction-owned-effects.spec.ts':continue
        group=next((v for v in chain if v in VIEWPORTS),'UNCLASSIFIED');title=spec.get('title')
        errors=[e for r in test.get('results',[]) for e in r.get('errors',[]) if isinstance(e,dict)]
        text=' '.join(str(e.get('message','')) for e in errors)
        category='STRICT_LOCATOR' if 'strict mode violation' in text else 'TIMEOUT' if 'Timed out' in text or 'TimeoutError' in text else 'ASSERTION_OR_OPERATION_FAILED'
        lines={int(n) for e in errors for n in re.findall(r'interaction-owned-effects\.spec\.ts:(\d+):\d+',str(e.get('stack',''))) if 1<=int(n)<=2000}
        line=spec.get('line')
        if type(line) is int and 1<=line<=2000:lines.add(line)
        result.append({'viewport':group,'case':title if title in TITLES else 'UNCLASSIFIED','category':category,'source_lines':sorted(lines)[:5]})
    return result[:3]


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True);parser.add_argument('--check-inputs',action='store_true');args=parser.parse_args();source=args.source.resolve()
    summary={'schema_version':1,'status':'BLOCKED','stage':'exact_source','product_sha':PRODUCT,'test_source_sha':SOURCE,
        'scope':'SYNTHETIC_NATIVE_COMPONENT_INTERACTIONS_ONLY','observed_at':datetime.now(timezone.utc).isoformat(),
        'parents_and_callbacks':'SYNTHETIC','images':'GENERATED_CANVAS','native_browser_effects':'REQUIRED_BY_SCENARIOS',
        'api_db_provider':'NOT_RUN','physical_device':'NOT_RUN','C_gates':'NOT_INVOKED_OR_MODIFIED','deployment_performed':False,'full_cycle_green':False}
    code=1
    try:
        c=contract();verify_source(source,c)
        if args.check_inputs:print('PASS: exact interaction fixture and unchanged component source');return 0
        sha=harness();summary['harness_sha']=sha;env=environment(source,sha);front=source/'frontend';summary['stage']='source_types_and_build'
        if run(['npm','run','check'],front,env).returncode:raise ValueError('INTERACTIONS_APP_CHECK_FAILED')
        if run(['node',str(front/'node_modules/typescript/bin/tsc'),'-p','tests/tsconfig.json'],front,env,120).returncode:raise ValueError('INTERACTIONS_TEST_TYPES_FAILED')
        summary['source_checks']='PASS';summary['stage']='single_chromium_interaction_matrix'
        with tempfile.TemporaryDirectory(prefix='dalaai-interactions-private-') as output:
            env['DALA_INTERACTIONS_OUTPUT']=output
            result=run(['node',str(front/'node_modules/@playwright/test/cli.js'),'test','--config',str(ROOT/'ops/ci/day_ui_interactions_playwright.cjs')],front,env,600)
            if len(result.stdout)>8*1024*1024:raise ValueError('INTERACTIONS_REPORT_TOO_LARGE')
            try:data=json.loads(result.stdout)
            except Exception:raise ValueError('INTERACTIONS_REPORT_UNAVAILABLE') from None
            summary['diagnostic']=diagnostic(data);summary['viewports']=verify_report(data,sha)
            if result.returncode:raise ValueError('INTERACTIONS_RUNNER_NONZERO')
        verify_source(source,c)
        if harness()!=sha:raise ValueError('INTERACTIONS_HARNESS_CHANGED')
        summary['status']='PASS_SYNTHETIC_COMPONENT_INTERACTIONS_ONLY';summary['stage']='completed';summary['native_browser_effects']='VERIFIED_WITH_SYNTHETIC_FIXTURES';code=0
    except ValueError as error:
        value=str(error);summary['reason_code']=value if re.fullmatch('INTERACTIONS_[A-Z_]+',value) else 'INTERACTIONS_INVALID_REPORT';summary['status']='BLOCKED' if summary['stage']=='exact_source' else 'FAIL'
    except Exception:summary['status']='FAIL';summary['reason_code']='INTERACTIONS_RUNNER_FAILURE'
    if args.check_inputs:print('BLOCKED: interaction source check');return 1
    (ROOT/'day-ui-interactions-summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2));return code


if __name__=='__main__':raise SystemExit(main())
