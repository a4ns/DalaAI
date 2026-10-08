#!/usr/bin/env python3
"""One public synthetic comparison, preserving app and CDP outcomes separately."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess

ROOT=Path(__file__).resolve().parents[2]
SOURCE='a880371589aa1dd117dde9e80936c687d146f919'
BRANCH='refs/heads/validation/json-reader-probe-20261008'
SCRIPT_SHA='670fad19f7837ca4e98999530301950a626a15077acf3a368aa2a5d8bbd3f5ae'
READER_SHA='51b53cc09d9458e020dddfc032ef86d1c937d9dcc08d753de5e6cc598fbf9010'
PAYLOAD_SHA='f72550801d9cef183196ed76f83191b1d0051cd8f6e28dfa3162a02a3ebaf63a'
PAYLOAD_BYTES=175949


def environment():
    return {k:v for k,v in os.environ.items() if k in {'PATH','HOME','LANG','LC_ALL','TMPDIR','PLAYWRIGHT_BROWSERS_PATH'}}


def command(argv,cwd,env,timeout=20):
    return subprocess.run(argv,cwd=cwd,env=env,capture_output=True,timeout=timeout,check=False)


def verify_source(source):
    env=environment()
    result=command(['git','rev-parse','HEAD'],source,env)
    if result.returncode or result.stdout.decode().strip()!=SOURCE:raise ValueError('JSON_READER_EXACT_SOURCE_REQUIRED')
    if command(['git','diff','--exit-code','HEAD','--','frontend'],source,env).returncode:raise ValueError('JSON_READER_DIRTY_SOURCE')
    extra=command(['git','ls-files','--others','--exclude-standard','--','frontend'],source,env)
    if extra.returncode or extra.stdout.strip():raise ValueError('JSON_READER_UNTRACKED_SOURCE')
    file=source/'frontend/src/shared/api/client.ts'
    if file.is_symlink() or not file.is_file():raise ValueError('JSON_READER_REGULAR_SOURCE_REQUIRED')
    text=file.read_text();start=text.index('async function readBoundedJson(');end=text.index('\nfunction authorityKey(',start)
    if hashlib.sha256(text[start:end].encode()).hexdigest()!=READER_SHA:raise ValueError('JSON_READER_HELPER_HASH_MISMATCH')
    script=ROOT/'ops/ci/json_reader_probe.cjs'
    if script.is_symlink() or hashlib.sha256(script.read_bytes()).hexdigest()!=SCRIPT_SHA:raise ValueError('JSON_READER_AUTHOR_SOURCE_MISMATCH')
    package=json.loads((source/'frontend/package.json').read_text())
    if any(package.get('devDependencies',{}).get(k)!=v for k,v in {'@playwright/test':'1.63.0','typescript':'6.0.3'}.items()):raise ValueError('JSON_READER_LOCKED_PACKAGES_REQUIRED')


def verify_harness():
    if os.environ.get('GITHUB_REF')!=BRANCH:raise ValueError('JSON_READER_EXACT_BRANCH_REQUIRED')
    result=command(['git','rev-parse','HEAD'],ROOT,environment());sha=result.stdout.decode().strip()
    if result.returncode or not re.fullmatch('[a-f0-9]{40}',sha) or os.environ.get('GITHUB_SHA')!=sha:raise ValueError('JSON_READER_EXACT_HARNESS_REQUIRED')
    files=['ops/ci/json_reader_gate.py','ops/ci/json_reader_probe.cjs','ops/ci/json_reader_tests.py','.github/workflows/json-reader-probe.yml']
    if command(['git','diff','--exit-code','HEAD','--',*files],ROOT,environment()).returncode:raise ValueError('JSON_READER_HARNESS_CHANGED')
    extra=command(['git','ls-files','--others','--exclude-standard','--',*files],ROOT,environment())
    if extra.returncode or extra.stdout.strip():raise ValueError('JSON_READER_HARNESS_UNTRACKED')
    return sha


def category(value):
    if not isinstance(value,dict):return 'OTHER'
    name=value.get('error_name',value.get('name',''));message=value.get('error_message',value.get('message',value.get('errorText','')))
    message=message if isinstance(message,str) and len(message)<=8192 else ''
    if name in ('ProbeTimeout','TimeoutError') or 'exceeded the public diagnostic wall bound' in message:return 'TIMEOUT'
    if name=='AbortError' or 'ERR_ABORTED' in message:return 'ABORTED'
    if 'No resource with given identifier' in message or 'No data found for resource' in message:return 'BODY_UNAVAILABLE'
    if 'Network.getResponseBody' in message:return 'BODY_PROTOCOL_FAILURE'
    if 'Target closed' in message or 'Target page, context or browser has been closed' in message:return 'TARGET_CLOSED'
    if name=='SyntaxError':return 'PARSE_FAILED'
    return 'OTHER'


def outcome(value):
    if not isinstance(value,dict) or value.get('outcome') not in ('parsed','failed'):raise ValueError('JSON_READER_OUTCOME_SHAPE')
    if value['outcome']=='failed':return {'outcome':'failed','failure_category':category(value)}
    if (not isinstance(value.get('hash'),str) or not re.fullmatch('[a-f0-9]{64}',value['hash'])
        or type(value.get('bytes')) is not int or not 0<=value['bytes']<=1048576
        or type(value.get('rows')) is not int or not 0<=value['rows']<=1500):raise ValueError('JSON_READER_PARSED_BOUNDS')
    return {'outcome':'parsed','hash':value['hash'],'bytes':value['bytes'],'rows':value['rows'],
            'matches_fixed_payload':value['hash']==PAYLOAD_SHA and value['bytes']==PAYLOAD_BYTES and value['rows']==1500}


def projection(raw):
    if (not isinstance(raw,dict) or raw.get('reader_source_sha256')!=READER_SHA or raw.get('payload_sha256')!=PAYLOAD_SHA
        or raw.get('payload_bytes')!=PAYLOAD_BYTES):raise ValueError('JSON_READER_PUBLIC_SOURCE_BINDING')
    counts=raw.get('counts');arms=raw.get('arms')
    if (not isinstance(counts,dict) or set(counts)!={'text','reader'} or any(type(v) is not int or v not in (0,1) for v in counts.values())
        or not isinstance(arms,list) or len(arms)>2):raise ValueError('JSON_READER_SINGLE_REQUEST_REQUIRED')
    output={'reader_source_sha256':READER_SHA,'payload_sha256':PAYLOAD_SHA,'payload_bytes':PAYLOAD_BYTES,'counts':counts,'arms':[]}
    seen=[]
    for row in arms:
        arm=row.get('arm');seen.append(arm)
        if arm not in ('text','reader') or counts[arm]!=1 or row.get('status')!=200:raise ValueError('JSON_READER_ARM_BINDING')
        app=outcome(row.get('app'));observer=outcome(row.get('observer'));failure=row.get('request_failure')
        if failure is not None and not isinstance(failure,dict):raise ValueError('JSON_READER_FAILURE_SHAPE')
        equal=app.get('matches_fixed_payload') is True and observer.get('matches_fixed_payload') is True
        if row.get('exact_bytes') is not equal:raise ValueError('JSON_READER_NO_RESULT_PROMOTION')
        output['arms'].append({'arm':arm,'http_status':200,'app':app,'observer':observer,
            'request_failure_present':failure is not None,'request_failure_category':category(failure) if failure is not None else 'NONE','exact_bytes':equal})
    if seen!=['text','reader'][:len(seen)]:raise ValueError('JSON_READER_FIXED_ARM_ORDER')
    result=raw.get('result')
    if result=='BLOCKED':output.update(status='BLOCKED',probe_result='BLOCKED',blocker_category=category(raw.get('blocker')))
    else:
        if seen!=['text','reader'] or counts!={'text':1,'reader':1}:raise ValueError('JSON_READER_INCOMPLETE_COMPARISON')
        expected='BOTH_ARMS_PASS' if all(a['exact_bytes'] for a in output['arms']) else 'OBSERVED_DIFFERENCE_OR_FAILURE'
        if result!=expected:raise ValueError('JSON_READER_NO_RESULT_PROMOTION')
        output.update(status='COMPARISON_COMPLETE',probe_result=expected)
    version=raw.get('browser','')
    output['browser_version']=version if isinstance(version,str) and re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,4}',version) else 'UNRECORDED'
    return output


def dummy_safety_check():
    value={'outcome':'failed','error_name':'CANARY_PRIVATE','error_message':'CANARY_PRIVATE','extra':'CANARY_PRIVATE'}
    if 'CANARY_PRIVATE' in json.dumps(outcome(value)):raise ValueError('JSON_READER_DUMMY_OUTPUT_UNSAFE')


def official_browser(source,env):
    frontend=source/'frontend'
    for package,version in (('playwright','1.63.0'),('typescript','6.0.3')):
        if json.loads((frontend/'node_modules'/package/'package.json').read_text()).get('version')!=version:raise ValueError('JSON_READER_INSTALLED_PACKAGE_MISMATCH')
    result=command(['node','-e','process.stdout.write(require(process.argv[1]).chromium.executablePath())',str(frontend/'node_modules/playwright')],frontend,env)
    base=Path(env.get('PLAYWRIGHT_BROWSERS_PATH',''));browser=Path(result.stdout.decode())
    if result.returncode or not base.is_absolute() or not browser.is_absolute() or not browser.resolve().is_relative_to(base.resolve()) or not browser.is_file() or not os.access(browser,os.X_OK):
        raise ValueError('JSON_READER_OFFICIAL_CHROMIUM_REQUIRED')
    return browser


def execute(source,browser,env):
    child=subprocess.Popen(['node',str(ROOT/'ops/ci/json_reader_probe.cjs'),str(source/'frontend'),str(browser)],cwd=ROOT,env=env,
                           stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    try:stdout,_=child.communicate(timeout=120)
    except subprocess.TimeoutExpired:
        for sig in (signal.SIGTERM,signal.SIGKILL):
            try:os.killpg(child.pid,sig)
            except ProcessLookupError:pass
            try:child.communicate(timeout=5);break
            except subprocess.TimeoutExpired:continue
        return {'status':'INCONCLUSIVE','reason_code':'JSON_READER_OUTER_TIMEOUT','counts':None,'arms':[]}
    if child.returncode or len(stdout)>65536:raise ValueError('JSON_READER_PROCESS_OR_OUTPUT_BOUND')
    try:raw=json.loads(stdout)
    except Exception:raise ValueError('JSON_READER_OUTPUT_UNAVAILABLE') from None
    return projection(raw)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True);parser.add_argument('--check-inputs',action='store_true');args=parser.parse_args()
    source=args.source.resolve();summary={'schema_version':1,'status':'BLOCKED','scope':'PUBLIC_SYNTHETIC_JSON_READER_DIAGNOSTIC_ONLY',
        'source_sha':SOURCE,'observed_at':datetime.now(timezone.utc).isoformat(),'original_C_gates':'NOT_INVOKED_OR_MODIFIED','actual_app_api_db':'NOT_RUN',
        'provider_calls':'NOT_RUN','physical_device':'NOT_RUN','deployment_performed':False,'full_cycle_green':False}
    status=2
    try:
        dummy_safety_check();verify_source(source)
        if args.check_inputs:print('PASS: exact public probe, helper and payload contract');return 0
        harness=verify_harness();summary['harness_sha']=harness;env=environment();browser=official_browser(source,env)
        summary.update(execute(source,browser,env));verify_source(source)
        if verify_harness()!=harness:raise ValueError('JSON_READER_HARNESS_CHANGED')
        summary['dummy_output_safety']='PASS'
        status=0 if summary['status']=='COMPARISON_COMPLETE' else 2
    except ValueError as error:
        code=str(error);summary['reason_code']=code if re.fullmatch('JSON_READER_[A-Z_]+',code) else 'JSON_READER_INVALID_OUTPUT'
        summary['status']='BLOCKED'
    except Exception:summary['status']='BLOCKED';summary['reason_code']='JSON_READER_UNEXPECTED_RUNNER_FAILURE'
    if args.check_inputs:print('BLOCKED: public comparison input unavailable');return 2
    (ROOT/'json-reader-summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2));return status


if __name__=='__main__':raise SystemExit(main())
