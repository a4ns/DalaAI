#!/usr/bin/env python3
"""Exact final-B source/build and fixture-based Android rendering; no real services."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

SOURCE_SHA='faef5d3d8b4c640fae013dbfa78074382e512e8f'
PROJECTS={'independent-source':153,'android-emulation-pixel-9':13}
CONFIG_BLOB='f244c2cce4c03672147e114e378238fd76809064'


def run(command,cwd,env,timeout=300):
    return subprocess.run(command,cwd=cwd,env=env,capture_output=True,timeout=timeout,check=False)


def source_environment(source):
    env={key:value for key,value in os.environ.items() if key in
         {'PATH','HOME','LANG','LC_ALL','TMPDIR','CI','PLAYWRIGHT_BROWSERS_PATH'}}
    env.update(CI='1',UI_TEST_PORT='4176',UI_REVIEW_SHA=SOURCE_SHA,UI_REVIEW_ROOT=str(source/'frontend'))
    return env


def verify_source(source):
    if not source.is_absolute() or not (source/'.git').exists(): raise ValueError('FINAL_B_EXACT_CHECKOUT_REQUIRED')
    env=source_environment(source)
    head=run(['git','rev-parse','HEAD'],source,env,15)
    if head.returncode or head.stdout.decode().strip()!=SOURCE_SHA: raise ValueError('FINAL_B_SHA_MISMATCH')
    changed=run(['git','diff','--exit-code','HEAD','--','frontend'],source,env,15)
    untracked=run(['git','ls-files','--others','--exclude-standard','--','frontend'],source,env,15)
    if changed.returncode or untracked.returncode or untracked.stdout.strip(): raise ValueError('FINAL_B_FRONTEND_SOURCE_MODIFIED')
    import hashlib
    file=source/'frontend/playwright.config.ts'
    if file.is_symlink() or not file.is_file(): raise ValueError('FINAL_B_CONFIG_NOT_REGULAR_FILE')
    raw=file.read_bytes()
    if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=CONFIG_BLOB:
        raise ValueError('FINAL_B_REVIEWED_CONFIG_MISMATCH')
    package=json.loads((source/'frontend/package.json').read_text())
    if package.get('devDependencies',{}).get('@playwright/test')!='1.63.0': raise ValueError('FINAL_B_LOCKED_PLAYWRIGHT_REQUIRED')


def verify_report(data,project):
    if project not in PROJECTS: raise ValueError('FINAL_B_UNREVIEWED_PROJECT')
    rows=[]
    def walk(suites):
        for suite in suites:
            for spec in suite.get('specs',[]): rows.extend(spec.get('tests',[]))
            walk(suite.get('suites',[]))
    walk(data.get('suites',[]))
    expected=PROJECTS[project]
    if (data.get('config',{}).get('metadata',{}).get('reviewedSha')!=SOURCE_SHA
            or data.get('errors') or len(rows)!=expected
            or data.get('stats',{}).get('expected')!=expected
            or any(data.get('stats',{}).get(key)!=0 for key in ('unexpected','flaky','skipped'))
            or any(row.get('projectName')!=project or row.get('expectedStatus')!='passed'
                   or row.get('status')!='expected' or len(row.get('results',[]))!=1
                   or row['results'][0].get('status')!='passed' or row['results'][0].get('retry')!=0
                   or row['results'][0].get('errors') for row in rows)):
        raise ValueError('FINAL_B_FAILED_OR_INCOMPLETE_PROJECT')
    return {'project':project,'tests_passed':expected,'tests_failed':0,'tests_skipped':0,'retries':0}


def execute_project(source,env,project):
    frontend=source/'frontend'; cli=frontend/'node_modules/@playwright/test/cli.js'
    if not cli.is_file(): raise ValueError('FINAL_B_LOCKED_DEPENDENCIES_NOT_INSTALLED')
    project_env=dict(env)
    if project=='independent-source': project_env['UI_TEST_NO_SERVER']='1'
    else: project_env.pop('UI_TEST_NO_SERVER',None)
    with tempfile.TemporaryDirectory(prefix='dalaai-final-b-output-') as output:
        result=run(['node',str(cli),'test','--project',project,'--reporter','json','--trace','off','--output',output],
                   frontend,project_env,600)
        # All trace/screenshots (including the fixture's explicit screenshot) are
        # ephemeral. Never publish raw reporter data or arbitrary assertion text.
        if len(result.stdout)>8*1024*1024: raise ValueError('FINAL_B_REPORT_TOO_LARGE')
        try: data=json.loads(result.stdout)
        except Exception: raise ValueError('FINAL_B_REPORT_UNAVAILABLE') from None
        summary=verify_report(data,project)
        if result.returncode: raise ValueError('FINAL_B_PLAYWRIGHT_NONZERO_EXIT')
        return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--check-inputs',action='store_true')
    parser.add_argument('--report',type=Path,default=Path('final-b-synthetic-summary.json'))
    args=parser.parse_args(); source=args.source.resolve()
    report={'schema_version':1,'status':'BLOCKED_NOT_RUN','stage':'exact_source','source_sha':SOURCE_SHA,
        'workflow_sha':os.environ.get('GITHUB_SHA','UNRECORDED'),'observed_at':datetime.now(timezone.utc).isoformat(),
        'scope':'FINAL_B_SOURCE_AND_SYNTHETIC_PIXEL9_RENDERING_ONLY','projects':[],
        'clock_controls':'SOURCE_FIXTURES_AND_STATIC_RENDER_ONLY','download_controls':'SYNTHETIC_BYTES_AND_INJECTED_SAVE_PORTS_ONLY',
        'live_api_db':'NOT_RUN','C110':'NOT_INVOKED','C112':'NOT_INVOKED','physical_android':'NOT_RUN',
        'real_push_delivery':'NOT_RUN','native_download_save':'NOT_RUN','live_clock_mutation':'NOT_RUN',
        'full_cycle_green':False,'deployment_performed':False}
    status=1
    try:
        verify_source(source)
        if args.check_inputs:
            print('PASS: exact final-B checkout and accepted config are present');return 0
        env=source_environment(source);frontend=source/'frontend'
        report['stage']='lint_typecheck_build'
        if run(['npm','run','check'],frontend,env,300).returncode: raise ValueError('FINAL_B_APP_CHECK_FAILED')
        report['app_lint_typecheck_build']='PASS'
        report['stage']='test_typecheck'
        if run(['node',str(frontend/'node_modules/typescript/bin/tsc'),'-p','tests/tsconfig.json'],frontend,env,120).returncode:
            raise ValueError('FINAL_B_TEST_TYPECHECK_FAILED')
        report['test_typecheck']='PASS'
        for project in PROJECTS:
            report['stage']=project
            report['projects'].append(execute_project(source,env,project))
        verify_source(source)
        report['android_emulation']={'mode':'SYNTHETIC_FIXTURES_ONLY','device':'Pixel 9','os_descriptor':'Android 14',
            'viewport':{'width':360,'height':732},'touch':True,'dpr':3}
        report['status']='PASS_FINAL_B_SOURCE_AND_SYNTHETIC_ANDROID_ONLY';report['stage']='completed';status=0
    except ValueError as error:
        code=str(error)
        report['reason_code']=code if re.fullmatch(r'FINAL_B_[A-Z_]+',code) else 'FINAL_B_INVALID_REPORT'
        report['status']='BLOCKED_NOT_RUN' if report['stage']=='exact_source' else 'FAIL'
    except Exception:
        report['reason_code']='FINAL_B_RUNNER_FAILURE';report['status']='FAIL'
    if args.check_inputs: print('BLOCKED: '+report['reason_code'])
    else:
        args.report.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
    return status


if __name__=='__main__':raise SystemExit(main())
