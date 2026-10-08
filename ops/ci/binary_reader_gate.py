#!/usr/bin/env python3
"""One public binary consumer experiment; app and original CDP outcomes stay separate."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[2]
SOURCE='06877ab2502f8d91061fb2722a91084377b31dca'
BRANCH='refs/heads/validation/binary-reader-probe-20261008'
READER_SHA='73705ba4545e795ab3a59fa1a71de4638c1100457b606296538eb161fd0b0639'
CANDIDATE_SHA='02a844899e5490776d32558fdf9891701cd1ca8854d32aa20c821f6abdc1fa83'
SOURCES={
 'dalaai-public-binary-reader-probe.cjs':'5661c981699786197e5c422242926080531a066ceb25ef1832adb31a7ddd8634',
 'dalaai-experimental-binary-transform.ts':CANDIDATE_SHA,
 'dalaai-experimental-binary-transform-tests.cjs':'f42801eb3fd6479e9d64aff383695bf10972a66dab349eacef26de86d47fbf47',
}
ARMS=('manual','transform')
FLOWS=('valid_pdf','valid_xlsx','overflow_unknown_length','transport_error','caller_abort','invalid_signature')
PAIRS=[(a,f) for f in FLOWS for a in ARMS]
LIMIT=8388608
SIZE=175949
MIMES={'pdf':'application/pdf','xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}


def payload(format):
    data=bytearray(b'X'*SIZE);prefix=b'%PDF-' if format=='pdf' else bytes((80,75,3,4));data[:len(prefix)]=prefix
    marker=b'PUBLIC-SYNTHETIC-SIGNATURE-ONLY';data[32:32+len(marker)]=marker
    return {'bytes':SIZE,'hash':hashlib.sha256(data).hexdigest()}
PAYLOADS={format:payload(format) for format in MIMES}


def environment():
    return {k:v for k,v in os.environ.items() if k in {'PATH','HOME','LANG','LC_ALL','TMPDIR','PLAYWRIGHT_BROWSERS_PATH'}}


def command(argv,cwd,env,timeout=20):
    return subprocess.run(argv,cwd=cwd,env=env,capture_output=True,timeout=timeout,check=False)


def verify_source(source):
    env=environment();result=command(['git','rev-parse','HEAD'],source,env)
    if result.returncode or result.stdout.decode().strip()!=SOURCE:raise ValueError('BINARY_READER_EXACT_SOURCE_REQUIRED')
    changed=command(['git','diff','--exit-code','HEAD','--','frontend'],source,env)
    extra=command(['git','ls-files','--others','--exclude-standard','--','frontend'],source,env)
    if changed.returncode or extra.returncode or extra.stdout.strip():raise ValueError('BINARY_READER_CLEAN_SOURCE_REQUIRED')
    file=source/'frontend/src/shared/api/reportFiles.ts'
    if file.is_symlink() or not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=READER_SHA:raise ValueError('BINARY_READER_ORIGINAL_HASH_MISMATCH')
    for name,digest in SOURCES.items():
        file=ROOT/'ops/ci/binary_reader_sources'/name
        if file.is_symlink() or not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=digest:raise ValueError('BINARY_READER_AUTHOR_HASH_MISMATCH')
    package=json.loads((source/'frontend/package.json').read_text())
    if any(package.get('devDependencies',{}).get(k)!=v for k,v in {'@playwright/test':'1.63.0','typescript':'6.0.3'}.items()):raise ValueError('BINARY_READER_LOCKED_PACKAGES_REQUIRED')


def verify_harness():
    if os.environ.get('GITHUB_REF')!=BRANCH:raise ValueError('BINARY_READER_EXACT_BRANCH_REQUIRED')
    result=command(['git','rev-parse','HEAD'],ROOT,environment());sha=result.stdout.decode().strip()
    if result.returncode or not re.fullmatch('[a-f0-9]{40}',sha) or os.environ.get('GITHUB_SHA')!=sha:raise ValueError('BINARY_READER_EXACT_HARNESS_REQUIRED')
    paths=['ops/ci/binary_reader_gate.py','ops/ci/binary_reader_tests.py','ops/ci/binary_reader_sources','.github/workflows/binary-reader-probe.yml']
    changed=command(['git','diff','--exit-code','HEAD','--',*paths],ROOT,environment())
    extra=command(['git','ls-files','--others','--exclude-standard','--',*paths],ROOT,environment())
    if changed.returncode or extra.returncode or extra.stdout.strip():raise ValueError('BINARY_READER_HARNESS_CHANGED')
    return sha


def category(value):
    if not isinstance(value,dict):return 'OTHER'
    name=value.get('error_name',value.get('name',''));message=value.get('error_message',value.get('message',value.get('errorText','')))
    message=message if isinstance(message,str) and len(message)<=8192 else ''
    if name in ('ProbeTimeout','TimeoutError'):return 'TIMEOUT'
    if name=='AbortError' or 'ERR_ABORTED' in message:return 'ABORTED'
    if message=='Report exceeds byte limit':return 'BYTE_LIMIT'
    if message=='Invalid report signature':return 'INVALID_SIGNATURE'
    if 'No resource with given identifier' in message or 'No data found for resource' in message:return 'BODY_UNAVAILABLE'
    if 'Network.getResponseBody' in message:return 'BODY_PROTOCOL_FAILURE'
    if 'Target closed' in message or 'Target page, context or browser has been closed' in message:return 'TARGET_CLOSED'
    if name=='TypeError':return 'TYPE_ERROR'
    return 'OTHER'


def byte_outcome(value):
    if type(value.get('bytes')) is not int or not 0<=value['bytes']<=LIMIT+1 or not isinstance(value.get('hash'),str) or not re.fullmatch('[a-f0-9]{64}',value['hash']):raise ValueError('BINARY_READER_BYTE_BOUNDS')
    return {'bytes':value['bytes'],'hash':value['hash']}


def app_projection(value,flow):
    if not isinstance(value,dict) or value.get('outcome') not in ('accepted','rejected','inconclusive') or type(value.get('blob_received')) is not bool:raise ValueError('BINARY_READER_APP_SHAPE')
    result={'outcome':value['outcome'],'blob_received':value['blob_received']}
    for name in ('aborted','deadline_fired','caller_abort_fired'):
        if name not in value and value['outcome']=='inconclusive':result[name]=None
        elif type(value.get(name)) is not bool:raise ValueError('BINARY_READER_APP_BOOLEAN_REQUIRED')
        else:result[name]=value[name]
    format='xlsx' if flow=='valid_xlsx' else 'pdf'
    if value['outcome']=='accepted':
        if value['blob_received'] is not True:raise ValueError('BINARY_READER_ACCEPTED_BLOB_REQUIRED')
        result.update(byte_outcome(value));result['matches_fixed_payload']=all(result[k]==PAYLOADS[format][k] for k in ('bytes','hash'))
        result['mime_matches']=value.get('mime')==MIMES[format];result['filename_matches']=value.get('filename')=='synthetic.'+format
    else:result['failure_category']=category(value)
    if flow.startswith('valid_'):
        expected=result['outcome']=='accepted' and result.get('matches_fixed_payload') and result.get('mime_matches') and result.get('filename_matches') and result['aborted'] is False
    else:
        reason=(flow=='overflow_unknown_length' and value.get('error_message')=='Report exceeds byte limit' and result['aborted'] is False
            or flow=='invalid_signature' and value.get('error_message')=='Invalid report signature' and result['aborted'] is False
            or flow=='caller_abort' and value.get('error_name')=='AbortError' and result['aborted'] is True and result['caller_abort_fired'] is True
            or flow=='transport_error' and value.get('error_name')=='TypeError' and result['aborted'] is False)
        expected=result['outcome']=='rejected' and result['blob_received'] is False and reason
    return result,bool(expected and result['deadline_fired'] is False)


def observer_projection(value):
    if not isinstance(value,dict) or value.get('outcome') not in ('bytes','unavailable'):raise ValueError('BINARY_READER_OBSERVER_SHAPE')
    return {'outcome':'bytes',**byte_outcome(value)} if value['outcome']=='bytes' else {'outcome':'unavailable','failure_category':category(value)}


def projection(raw):
    if (not isinstance(raw,dict) or raw.get('original_source_sha256')!=READER_SHA or raw.get('candidate_source_sha256')!=CANDIDATE_SHA
        or raw.get('limit_bytes')!=LIMIT or raw.get('payloads')!=PAYLOADS):raise ValueError('BINARY_READER_SOURCE_PAYLOAD_BINDING')
    counts=raw.get('counts');rows=raw.get('flows')
    if (not isinstance(counts,dict) or set(counts)!={a+':'+f for a,f in PAIRS}
        or any(type(v) is not int or v not in (0,1) for v in counts.values()) or not isinstance(rows,list) or len(rows)>12):raise ValueError('BINARY_READER_SINGLE_REQUEST_REQUIRED')
    result={'original_source_sha256':READER_SHA,'candidate_source_sha256':CANDIDATE_SHA,'limit_bytes':LIMIT,'payloads':PAYLOADS,'counts':counts,'flows':[]}
    for index,row in enumerate(rows):
        if not isinstance(row,dict) or (row.get('arm'),row.get('flow'))!=PAIRS[index] or row.get('status')!=200:raise ValueError('BINARY_READER_FIXED_FLOW_ORDER')
        arm,flow=PAIRS[index]
        if counts[arm+':'+flow]!=1:raise ValueError('BINARY_READER_FLOW_REQUEST_MISSING')
        app,expected=app_projection(row.get('app'),flow);observer=observer_projection(row.get('observer'));failure=row.get('request_failure')
        if failure is not None and not isinstance(failure,dict):raise ValueError('BINARY_READER_FAILURE_SHAPE')
        format='xlsx' if flow=='valid_xlsx' else 'pdf';exact=(observer['outcome']=='bytes' and all(observer[k]==PAYLOADS[format][k] for k in ('bytes','hash'))) if flow.startswith('valid_') else None
        if row.get('app_expected') is not expected or row.get('original_cdp_exact') is not exact:raise ValueError('BINARY_READER_NO_RESULT_PROMOTION')
        result['flows'].append({'arm':arm,'flow':flow,'http_status':200,'app':app,'observer':observer,'app_expected':expected,'original_cdp_exact':exact,
            'request_failure_present':failure is not None,'request_failure_category':category(failure) if failure is not None else 'NONE'})
    complete=len(rows)==12 and all(v==1 for v in counts.values()) and not any(
        r['app'].get('outcome') not in ('accepted','rejected')
        or r['app'].get('error_name') in ('ProbeTimeout','TimeoutError')
        or r['observer'].get('error_name') in ('ProbeTimeout','TimeoutError')
        or r['app'].get('deadline_fired') is True for r in rows)
    supplied=raw.get('result')
    if supplied=='INCONCLUSIVE':
        if raw.get('complete') is True:raise ValueError('BINARY_READER_COMPLETENESS_MISMATCH')
        result.update(status='INCONCLUSIVE',probe_result=supplied,blocker_category=category(raw.get('blocker')))
    else:
        expected_result='COMPLETE_APP_CHECKS_PASS_OBSERVER_RECORDED' if all(r['app_expected'] for r in result['flows']) else 'COMPLETE_APP_CHECK_FAILED'
        if not complete or raw.get('complete') is not True or supplied!=expected_result:raise ValueError('BINARY_READER_INCOMPLETE_OR_PROMOTED_RESULT')
        result.update(status='COMPARISON_COMPLETE',probe_result=supplied)
    version=raw.get('browser','');result['browser_version']=version if isinstance(version,str) and re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,4}',version) else 'UNRECORDED'
    return result


def dummy_safety_check():
    value={'outcome':'rejected','blob_received':False,'aborted':False,'deadline_fired':False,'caller_abort_fired':False,'error_name':'CANARY_PRIVATE','error_message':'CANARY_PRIVATE','extra':'CANARY_PRIVATE'}
    if 'CANARY_PRIVATE' in json.dumps(app_projection(value,'invalid_signature')):raise ValueError('BINARY_READER_DUMMY_OUTPUT_UNSAFE')


def official_browser(source,env):
    frontend=source/'frontend'
    for package,version in (('playwright','1.63.0'),('typescript','6.0.3')):
        if json.loads((frontend/'node_modules'/package/'package.json').read_text()).get('version')!=version:raise ValueError('BINARY_READER_INSTALLED_PACKAGE_MISMATCH')
    result=command(['node','-e','process.stdout.write(require(process.argv[1]).chromium.executablePath())',str(frontend/'node_modules/playwright')],frontend,env)
    base=Path(env.get('PLAYWRIGHT_BROWSERS_PATH',''));browser=Path(result.stdout.decode())
    if result.returncode or not base.is_absolute() or not browser.is_absolute() or not browser.resolve().is_relative_to(base.resolve()) or not browser.is_file() or not os.access(browser,os.X_OK):raise ValueError('BINARY_READER_OFFICIAL_CHROMIUM_REQUIRED')
    return browser


def source_only_probes(source,env):
    result=command(['node',str(ROOT/'ops/ci/binary_reader_sources/dalaai-experimental-binary-transform-tests.cjs'),str(source/'frontend')],ROOT,env,30)
    if result.returncode or len(result.stdout)>8192:raise ValueError('BINARY_READER_SOURCE_PROBES_FAILED')
    try:value=json.loads(result.stdout)
    except Exception:raise ValueError('BINARY_READER_SOURCE_PROBES_FAILED') from None
    if value.get('result')!='PASS' or len(value.get('checks',[]))!=8:raise ValueError('BINARY_READER_SOURCE_PROBES_FAILED')


def execute(source,browser,env):
    # Chromium adds its own directory and SingletonSocket below the producer's
    # browser TMPDIR. Keep this fresh 0700 parent short enough for Linux sun_path.
    with tempfile.TemporaryDirectory(prefix='db-',dir='/tmp') as private:
        child_env=dict(env,TMPDIR=private)
        child=subprocess.Popen(['node',str(ROOT/'ops/ci/binary_reader_sources/dalaai-public-binary-reader-probe.cjs'),str(source/'frontend'),str(browser)],cwd=private,env=child_env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        try:stdout,_=child.communicate(timeout=180)
        except subprocess.TimeoutExpired:
            for sig in (signal.SIGTERM,signal.SIGKILL):
                try:os.killpg(child.pid,sig)
                except ProcessLookupError:pass
                try:child.communicate(timeout=5);break
                except subprocess.TimeoutExpired:continue
            return {'status':'INCONCLUSIVE','reason_code':'BINARY_READER_OUTER_TIMEOUT','counts':None,'flows':[]}
        if child.returncode or len(stdout)>131072:raise ValueError('BINARY_READER_PROCESS_OR_OUTPUT_BOUND')
        try:raw=json.loads(stdout)
        except Exception:raise ValueError('BINARY_READER_OUTPUT_UNAVAILABLE') from None
        return projection(raw)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True);parser.add_argument('--check-inputs',action='store_true');args=parser.parse_args();source=args.source.resolve()
    summary={'schema_version':1,'status':'BLOCKED','scope':'PUBLIC_SYNTHETIC_BINARY_READER_DIAGNOSTIC_ONLY','source_sha':SOURCE,
        'observed_at':datetime.now(timezone.utc).isoformat(),'payload_kind':'SIGNATURE_ONLY_NOT_VALID_DOCUMENTS','original_C_gates':'NOT_INVOKED_OR_MODIFIED',
        'actual_app_api_db':'NOT_RUN','provider_calls':'NOT_RUN','physical_device':'NOT_RUN','deployment_performed':False,'full_cycle_green':False,'experimental_transform_adopted':False}
    code=2
    try:
        dummy_safety_check();verify_source(source)
        if args.check_inputs:print('PASS: exact binary probe, experimental candidate and immutable original');return 0
        harness=verify_harness();summary['harness_sha']=harness;env=environment();browser=official_browser(source,env)
        source_only_probes(source,env);summary['source_only_candidate_checks']=8
        summary.update(execute(source,browser,env));verify_source(source)
        if verify_harness()!=harness:raise ValueError('BINARY_READER_HARNESS_CHANGED')
        summary['dummy_output_safety']='PASS';code=0 if summary['status']=='COMPARISON_COMPLETE' else 2
    except ValueError as error:
        value=str(error);summary['reason_code']=value if re.fullmatch('BINARY_READER_[A-Z_]+',value) else 'BINARY_READER_INVALID_OUTPUT';summary['status']='BLOCKED'
    except Exception:summary['status']='BLOCKED';summary['reason_code']='BINARY_READER_UNEXPECTED_RUNNER_FAILURE'
    if args.check_inputs:print('BLOCKED: binary comparison input unavailable');return 2
    (ROOT/'binary-reader-summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2));return code


if __name__=='__main__':raise SystemExit(main())
