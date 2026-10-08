#!/usr/bin/env python3
"""Run one immutable offline six-test reproduction without changing export caps."""
import argparse
import ast
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
BRANCH='refs/heads/validation/canonical-history-exports-20261008'
SOURCE='743474bcb60212c98c0d2b28776164467d5f67bf'
CURRENT='038bcb06351b187301614d9f18cef49fa27b96df'
TEST_SHA='523586b9e7f656c621a1ddf76511adc4e38db29eb07093902ef00bd8ce37ce82'
PREFIX='canonical_history_export_'


def command(argv,cwd,timeout=20):
    env={k:v for k,v in os.environ.items() if k in {'PATH','HOME','LANG','LC_ALL','TMPDIR'}}
    return subprocess.run(argv,cwd=cwd,env=env,capture_output=True,timeout=timeout,check=False)


def contract():
    c=json.loads((ROOT/'ops/ci/canonical_history_export_contract.json').read_text())
    if c.get('accepted') is not True or c.get('source_sha')!=SOURCE or c.get('current_reference_sha')!=CURRENT or c.get('test_sha256')!=TEST_SHA or len(c.get('core_blobs',{}))!=109 or len(c.get('cases',[]))!=6 or len(set(c['cases']))!=6:raise ValueError('CANONICAL_EXACT_CONTRACT_REQUIRED')
    return c


def blob(path):
    if path.is_symlink() or not path.is_file():raise ValueError('CANONICAL_REGULAR_SOURCE_REQUIRED')
    data=path.read_bytes();return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()


def verify_inputs(source,current,c):
    for root,sha in ((source,SOURCE),(current,CURRENT)):
        result=command(['git','rev-parse','HEAD'],root)
        if result.returncode or result.stdout.decode().strip()!=sha:raise ValueError('CANONICAL_IMMUTABLE_CHECKOUT_REQUIRED')
        changed=command(['git','diff','--exit-code','HEAD','--','backend','scripts/synthetic'],root)
        extra=command(['git','ls-files','--others','--exclude-standard','--','backend','scripts/synthetic'],root)
        if changed.returncode or extra.returncode or extra.stdout.strip():raise ValueError('CANONICAL_CLEAN_SOURCE_REQUIRED')
        for name,expected in c['core_blobs'].items():
            if '..' in Path(name).parts or not (name.startswith('backend/') or name.startswith('scripts/synthetic/')) or blob(root/name)!=expected:raise ValueError('CANONICAL_REUSED_CORE_MISMATCH')
    diff=command(['git','diff','--name-status',c['base_sha'],'HEAD'],source)
    if diff.returncode or diff.stdout.decode().splitlines()!=['A\t'+c['test_path']]:raise ValueError('CANONICAL_TEST_ONLY_SOURCE_REQUIRED')
    file=source/c['test_path']
    if file.is_symlink() or hashlib.sha256(file.read_bytes()).hexdigest()!=TEST_SHA:raise ValueError('CANONICAL_TEST_BLOB_MISMATCH')
    tree=ast.parse(file.read_text());names=[]
    for item in tree.body:
        if isinstance(item,ast.ClassDef):
            names.extend('test_c_day_canonical_history_exports.'+item.name+'.'+fn.name for fn in item.body if isinstance(fn,ast.FunctionDef) and fn.name.startswith('test_'))
    if sorted(names)!=sorted(c['cases']):raise ValueError('CANONICAL_EXACT_SIX_CASES_REQUIRED')
    locked=(source/'backend/requirements.lock').read_text().splitlines()
    expected=[name+'=='+version for name,version in c['export_packages'].items()]
    actual=[line for line in (ROOT/'ops/ci/canonical_history_export_requirements.lock').read_text().splitlines() if line and not line.startswith('#')]
    if actual!=expected or any(line not in locked for line in expected):raise ValueError('CANONICAL_EXISTING_EXPORT_LOCK_REQUIRED')


def harness():
    if os.environ.get('GITHUB_REF')!=BRANCH:raise ValueError('CANONICAL_EXACT_BRANCH_REQUIRED')
    result=command(['git','rev-parse','HEAD'],ROOT);sha=result.stdout.decode().strip()
    if result.returncode or not re.fullmatch('[a-f0-9]{40}',sha) or os.environ.get('GITHUB_SHA')!=sha:raise ValueError('CANONICAL_EXACT_HARNESS_REQUIRED')
    paths=[str(p.relative_to(ROOT)) for p in (ROOT/'ops/ci').glob(PREFIX+'*') if p.is_file()]+['.github/workflows/canonical-history-export-validation.yml']
    changed=command(['git','diff','--exit-code','HEAD','--',*paths],ROOT);extra=command(['git','ls-files','--others','--exclude-standard','--',*paths],ROOT)
    if changed.returncode or extra.returncode or extra.stdout.strip():raise ValueError('CANONICAL_HARNESS_CHANGED')
    return sha


def runtime_env(source,private):
    return {'PATH':os.defpath,'LANG':'C.UTF-8','LC_ALL':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1','PYTHONPATH':str(source/'backend'),'TMPDIR':str(private)}


def fixed_failure(value):
    if not isinstance(value,dict) or value.get('category') not in {'ASSERTION_FAILED','IMPORT_FAILED','RENDER_DOMAIN_ERROR','OTHER_ERROR'} or value.get('domain_code') not in {'NONE','TEMPORARILY_UNAVAILABLE','REPORT_LIMIT_EXCEEDED'} or type(value.get('subprocess_timeout_observed')) is not bool:raise ValueError('CANONICAL_FIXED_FAILURE_REQUIRED')
    return {k:value[k] for k in ('category','domain_code','subprocess_timeout_observed')}


def projection(raw,c):
    if not isinstance(raw,dict) or raw.get('status') not in {'PASS','FAIL','BLOCKED'}:raise ValueError('CANONICAL_RESULT_SHAPE')
    rows=raw.get('cases');fixture=raw.get('fixture_errors')
    if not isinstance(rows,list) or len(rows)>6 or not isinstance(fixture,list) or len(fixture)>6 or type(raw.get('tests_run')) is not int or not 0<=raw['tests_run']<=6:raise ValueError('CANONICAL_RESULT_BOUNDS')
    output={'status':raw['status'],'tests_run':raw['tests_run'],'cases':[],'fixture_errors':[fixed_failure(x) for x in fixture]}
    names=[];counts={s:0 for s in ('PASS','FAIL','ERROR','SKIP','EXPECTED_FAILURE','UNEXPECTED_SUCCESS','NOT_RUN')}
    for row in rows:
        if not isinstance(row,dict) or row.get('id') not in c['cases'] or row.get('status') not in counts or type(row.get('duration_ms')) is not int or not 0<=row['duration_ms']<=90000:raise ValueError('CANONICAL_FIXED_CASE_REQUIRED')
        names.append(row['id']);counts[row['status']]+=1
        error=fixed_failure(row['failure']) if row.get('failure') is not None else None
        if row['status'] in {'FAIL','ERROR','EXPECTED_FAILURE'} and error is None:raise ValueError('CANONICAL_FAILURE_DETAIL_REQUIRED')
        if row['status']=='PASS' and error is not None:raise ValueError('CANONICAL_PASS_CONTRADICTION')
        output['cases'].append({'id':row['id'],'status':row['status'],'duration_ms':row['duration_ms'],'failure':error})
    if len(names)!=len(set(names)):raise ValueError('CANONICAL_DUPLICATE_RESULT')
    if raw['status'] in {'PASS','FAIL'} and (names!=c['cases'] or raw.get('python')!=c['python'] or raw.get('packages')!=c['export_packages'] or raw.get('optional_packages')!={'lxml':False,'numpy':False}):raise ValueError('CANONICAL_EXACT_RUNTIME_RESULT_REQUIRED')
    if raw['status']=='PASS' and (raw['tests_run']!=6 or counts['PASS']!=6 or fixture):raise ValueError('CANONICAL_NO_FAILURE_PROMOTION')
    output['counts']=counts
    if raw.get('python')==c['python']:output.update(python=c['python'],packages=c['export_packages'],optional_packages={'lxml':False,'numpy':False})
    if raw['status']=='BLOCKED':
        reason=raw.get('reason_code');allowed={'EXACT_ISOLATED_PYTHON_REQUIRED','LOCKED_EXPORT_PACKAGES_REQUIRED','UNLOCKED_OPTIONAL_PACKAGE_PRESENT','EXACT_SIX_TESTS_REQUIRED','PRIVATE_OUTPUT_BOUND','DUPLICATE_TEST_RESULT','EXECUTION_SETUP_OR_RESULT_ERROR'}
        output['reason_code']=reason if reason in allowed else 'EXECUTION_SETUP_OR_RESULT_ERROR'
        if 'setup_failure' in raw:output['setup_failure']=fixed_failure(raw['setup_failure'])
    return output


def execute(source,python,c):
    if not python.is_absolute() or not python.is_file():raise ValueError('CANONICAL_EXPLICIT_INTERPRETER_REQUIRED')
    with tempfile.TemporaryDirectory(prefix='dala-canonical-private-') as private:
        child=subprocess.Popen([str(python),str(ROOT/'ops/ci/canonical_history_export_execute.py'),'--source',str(source)],cwd=source,env=runtime_env(source,private),stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        try:stdout,_=child.communicate(timeout=90)
        except subprocess.TimeoutExpired:
            for sig in (signal.SIGTERM,signal.SIGKILL):
                try:os.killpg(child.pid,sig)
                except ProcessLookupError:pass
                try:child.communicate(timeout=5);break
                except subprocess.TimeoutExpired:continue
            return {'status':'FAIL','reason_code':'CANONICAL_OUTER_PROCESS_TIMEOUT','tests_run':None,'cases':[]}
    if len(stdout)>65536:raise ValueError('CANONICAL_OUTPUT_BOUND')
    try:raw=json.loads(stdout)
    except Exception:raise ValueError('CANONICAL_PRIVATE_RESULT_UNAVAILABLE') from None
    result=projection(raw,c)
    if (result['status']=='PASS')!=(child.returncode==0):raise ValueError('CANONICAL_EXIT_STATUS_MISMATCH')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True);parser.add_argument('--current',type=Path,required=True);parser.add_argument('--python',type=Path);parser.add_argument('--check-inputs',action='store_true');args=parser.parse_args()
    source=args.source.resolve();current=args.current.resolve();summary={'schema_version':1,'status':'BLOCKED','scope':'OFFLINE_CANONICAL_HISTORY_EXPORT_REGRESSION_ONLY','source_sha':SOURCE,'current_reference_sha':CURRENT,
        'observed_at':datetime.now(timezone.utc).isoformat(),'renderer_seconds_unchanged':6,'provider_db_network_inputs':'NONE','actual_http_api':'NOT_RUN','C113_capture':'SEPARATE_EVIDENCE','deployment_performed':False,'full_cycle_green':False};code=1
    try:
        c=contract();verify_inputs(source,current,c)
        if args.check_inputs:print('PASS: exact six-test source and109 unchanged current core blobs');return 0
        sha=harness();summary['harness_sha']=sha
        if args.python is None:raise ValueError('CANONICAL_EXPLICIT_INTERPRETER_REQUIRED')
        summary.update(execute(source,args.python,c));verify_inputs(source,current,c)
        if harness()!=sha:raise ValueError('CANONICAL_HARNESS_CHANGED')
        code=0 if summary['status']=='PASS' else 1
    except ValueError as error:
        value=str(error);summary['reason_code']=value if re.fullmatch('CANONICAL_[A-Z_]+',value) else 'CANONICAL_INVALID_INPUT_OR_RESULT';summary['status']='BLOCKED'
    except Exception:summary['status']='BLOCKED';summary['reason_code']='CANONICAL_RUNNER_FAILURE'
    if args.check_inputs:print('BLOCKED: canonical export source inputs');return 1
    (ROOT/'canonical-history-export-summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2));return code


if __name__=='__main__':raise SystemExit(main())
