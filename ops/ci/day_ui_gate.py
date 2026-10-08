#!/usr/bin/env python3
"""Exact combined UI: unchanged source cases and synthetic viewport scenarios."""
import argparse
import base64
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

SOURCE='a880371589aa1dd117dde9e80936c687d146f919'
BRANCH='refs/heads/validation/day-ui-viewports-20261008'
VIEWPORTS={'viewport-320':(320,800),'viewport-390':(390,844),'viewport-768':(768,1024)}
PROJECTS={'independent-source':218,**{name:18 for name in VIEWPORTS}}
FILES={'ai-assistance-mounted.spec.ts':5,'executor-synthetic.spec.ts':5,'identity-synthetic.spec.ts':2,'master-synthetic.spec.ts':3,'shell.spec.ts':3}
AI_TITLES={
 'synthetic mounted advice stays explicit and choosing changes only the current draft',
 'synthetic mounted advice403 clears dictionary access and cannot request again before explicit refresh',
 'synthetic mounted report is not automatic and unknown retry preserves exact POST body',
 'synthetic mounted confirmed close survives refresh removing the review card',
 'synthetic mounted confirmed rework survives refresh removing the review card',
}
ROOT=Path(__file__).resolve().parents[2]


def run(argv,cwd,env,timeout=300):
    return subprocess.run(argv,cwd=cwd,env=env,capture_output=True,timeout=timeout,check=False)


def environment(source,harness):
    env={k:v for k,v in os.environ.items() if k in {'PATH','HOME','LANG','LC_ALL','TMPDIR','PLAYWRIGHT_BROWSERS_PATH'}}
    env.update(CI='1',UI_REVIEW_SHA=SOURCE,UI_REVIEW_ROOT=str(source/'frontend'),UI_TEST_PORT='4176',
               DALA_DAY_UI_SOURCE=str(source),DALA_DAY_UI_HARNESS_SHA=harness)
    return env


def verify_source(source):
    if not source.is_absolute() or not (source/'.git').exists():raise ValueError('DAY_UI_EXACT_CHECKOUT_REQUIRED')
    env=environment(source,'source-check');result=run(['git','rev-parse','HEAD'],source,env,15)
    if result.returncode or result.stdout.decode().strip()!=SOURCE:raise ValueError('DAY_UI_SOURCE_SHA_MISMATCH')
    changed=run(['git','diff','--exit-code','HEAD','--','frontend'],source,env,15)
    extra=run(['git','ls-files','--others','--exclude-standard','--','frontend'],source,env,15)
    if changed.returncode or extra.returncode or extra.stdout.strip():raise ValueError('DAY_UI_SOURCE_CHANGED')
    if any(p.name!='.env.example' for p in (source/'frontend').glob('.env*')):raise ValueError('DAY_UI_AMBIENT_ENV_FILE_FORBIDDEN')
    package=json.loads((source/'frontend/package.json').read_text())
    if package.get('devDependencies',{}).get('@playwright/test')!='1.63.0':raise ValueError('DAY_UI_LOCKED_PLAYWRIGHT_REQUIRED')


def verify_harness():
    if os.environ.get('GITHUB_REF')!=BRANCH:raise ValueError('DAY_UI_EXACT_BRANCH_REQUIRED')
    result=run(['git','rev-parse','HEAD'],ROOT,os.environ,15);sha=result.stdout.decode().strip()
    if result.returncode or not re.fullmatch('[a-f0-9]{40}',sha) or os.environ.get('GITHUB_SHA')!=sha:raise ValueError('DAY_UI_EXACT_HARNESS_REQUIRED')
    paths=['ops/ci/day_ui_gate.py','ops/ci/day_ui_playwright.cjs','ops/ci/day_ui_tests.py','.github/workflows/day-ui-viewport.yml']
    if run(['git','diff','--exit-code','HEAD','--',*paths],ROOT,os.environ,15).returncode:raise ValueError('DAY_UI_HARNESS_CHANGED')
    extra=run(['git','ls-files','--others','--exclude-standard','--',*paths],ROOT,os.environ,15)
    if extra.returncode or extra.stdout.strip():raise ValueError('DAY_UI_HARNESS_UNTRACKED')
    return sha


def rows(data):
    found=[]
    def walk(suites):
        for suite in suites:
            for spec in suite.get('specs',[]):
                for test in spec.get('tests',[]):found.append((spec,test))
            walk(suite.get('suites',[]))
    walk(data.get('suites',[]));return found


def observation(test,output):
    matches=[a for a in test['results'][0].get('attachments',[]) if a.get('name')=='browser-emulation-observation']
    if len(matches)!=1 or matches[0].get('contentType')!='application/json':raise ValueError('DAY_UI_VIEWPORT_OBSERVATION_REQUIRED')
    item=matches[0]
    if isinstance(item.get('body'),str) and len(item['body'])<=24000:
        raw=base64.b64decode(item['body'],validate=True)
    else:
        path=Path(item.get('path',''))
        if not path.is_absolute() or path.is_symlink() or not path.resolve().is_relative_to(output.resolve()) or not path.is_file() or path.stat().st_size>16384:
            raise ValueError('DAY_UI_PRIVATE_ATTACHMENT_BOUNDARY')
        raw=path.read_bytes()
    if len(raw)>16384:raise ValueError('DAY_UI_VIEWPORT_OBSERVATION_BOUND')
    return json.loads(raw)


def verify_report(data,harness,output):
    metadata=data.get('config',{}).get('metadata',{})
    if (metadata.get('reviewedSha')!=SOURCE or metadata.get('harnessSha')!=harness or metadata.get('scope')!='SYNTHETIC_RESPONSIVE_CHROMIUM_ONLY'
            or data.get('errors') or data.get('stats',{}).get('expected')!=272
            or any(data.get('stats',{}).get(k)!=0 for k in ('unexpected','flaky','skipped'))):raise ValueError('DAY_UI_FAILED_OR_INCOMPLETE_REPORT')
    found=rows(data)
    if len(found)!=272 or any(t.get('projectName') not in PROJECTS or t.get('expectedStatus')!='passed' or t.get('status')!='expected'
        or len(t.get('results',[]))!=1 or t['results'][0].get('status')!='passed' or t['results'][0].get('retry')!=0 or t['results'][0].get('errors') for _,t in found):
        raise ValueError('DAY_UI_FAILED_SKIPPED_OR_RETRIED_CASE')
    result=[]
    for project,count in PROJECTS.items():
        group=[(s,t) for s,t in found if t['projectName']==project]
        if len(group)!=count:raise ValueError('DAY_UI_EXACT_PROJECT_COUNTS_REQUIRED')
        if project in VIEWPORTS:
            distribution={name:sum(Path(s.get('file','')).name==name for s,_ in group) for name in FILES}
            if distribution!=FILES or {s.get('title') for s,_ in group if Path(s.get('file','')).name=='ai-assistance-mounted.spec.ts'}!=AI_TITLES:
                raise ValueError('DAY_UI_AUTHORED_SCENARIOS_REQUIRED')
            shell=[t for s,t in group if s.get('title','').startswith('synthetic unavailable API: RU shell')]
            if len(shell)!=1:raise ValueError('DAY_UI_VIEWPORT_CASE_REQUIRED')
            actual=observation(shell[0],output);width,height=VIEWPORTS[project]
            if (actual.get('project')!=project or actual.get('physicalDevice') is not False or actual.get('viewport')!={'width':width,'height':height}
                or actual.get('innerWidth')!=width or actual.get('pixelRatio')!=1 or actual.get('touchPoints')!=0):raise ValueError('DAY_UI_RUNTIME_VIEWPORT_MISMATCH')
        result.append({'project':project,'passed':count,'skipped':0,'retries':0,**({'viewport':dict(zip(('width','height'),VIEWPORTS[project]))} if project in VIEWPORTS else {})})
    return result


def failure_projection(data):
    result=[]
    for spec,test in rows(data):
        if test.get('status')=='expected':continue
        filename=Path(spec.get('file','')).name;line=spec.get('line')
        if filename not in FILES or type(line) is not int or not 1<=line<=2000:continue
        messages=' '.join(str(e.get('message','')) for r in test.get('results',[]) for e in r.get('errors',[]) if isinstance(e,dict))
        category='LOCATOR_STRICT_MODE' if 'strict mode violation' in messages else 'TIMEOUT' if 'Timed out' in messages or 'TimeoutError' in messages else 'ASSERTION_OR_TEST_FAILURE'
        result.append({'file':filename,'line':line,'project':test.get('projectName') if test.get('projectName') in PROJECTS else 'UNCLASSIFIED','category':category})
    return result[:3]


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True);parser.add_argument('--check-inputs',action='store_true');args=parser.parse_args()
    source=args.source.resolve();report={'schema_version':1,'status':'BLOCKED','stage':'exact_source','source_sha':SOURCE,
        'scope':'SYNTHETIC_RESPONSIVE_CHROMIUM_ONLY','observed_at':datetime.now(timezone.utc).isoformat(),'C110':'NOT_INVOKED','C112':'NOT_INVOKED','C113':'NOT_INVOKED',
        'live_api_db':'NOT_RUN','live_ai_provider':'NOT_RUN','physical_android':'NOT_RUN','full_cycle_green':False,'deployment_performed':False}
    status=1
    try:
        verify_source(source)
        if args.check_inputs:print('PASS: exact combined UI source and locked Playwright');return 0
        harness=verify_harness();report['harness_sha']=harness;env=environment(source,harness);frontend=source/'frontend'
        report['stage']='lint_build_types'
        if run(['npm','run','check'],frontend,env).returncode:raise ValueError('DAY_UI_APP_CHECK_FAILED')
        if run(['node',str(frontend/'node_modules/typescript/bin/tsc'),'-p','tests/tsconfig.json'],frontend,env,120).returncode:raise ValueError('DAY_UI_TEST_TYPES_FAILED')
        report['app_source_checks']='PASS';report['stage']='synthetic_viewports'
        with tempfile.TemporaryDirectory(prefix='dalaai-day-ui-private-') as temporary:
            output=Path(temporary);env['DALA_DAY_UI_OUTPUT']=str(output)
            result=run(['node',str(frontend/'node_modules/@playwright/test/cli.js'),'test','--config',str(ROOT/'ops/ci/day_ui_playwright.cjs')],frontend,env,900)
            if len(result.stdout)>16*1024*1024:raise ValueError('DAY_UI_REPORT_TOO_LARGE')
            try:data=json.loads(result.stdout)
            except Exception:raise ValueError('DAY_UI_REPORT_UNAVAILABLE') from None
            report['diagnostic']=failure_projection(data)
            report['projects']=verify_report(data,harness,output)
            if result.returncode:raise ValueError('DAY_UI_PLAYWRIGHT_NONZERO')
        verify_source(source)
        if verify_harness()!=harness:raise ValueError('DAY_UI_HARNESS_CHANGED')
        report['status']='PASS_SYNTHETIC_VIEWPORTS_ONLY';report['stage']='completed';status=0
    except ValueError as error:
        code=str(error);report['reason_code']=code if re.fullmatch('DAY_UI_[A-Z_]+',code) else 'DAY_UI_INVALID_REPORT'
        report['status']='BLOCKED' if report['stage']=='exact_source' else 'FAIL'
    except Exception:report['status']='FAIL';report['reason_code']='DAY_UI_RUNNER_FAILURE'
    if args.check_inputs:print('BLOCKED: exact combined UI source unavailable');return 1
    (ROOT/'day-ui-summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));return status


if __name__=='__main__':raise SystemExit(main())
