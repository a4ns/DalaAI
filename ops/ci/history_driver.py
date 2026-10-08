"""C112's distinct proof and gate. Never substitutes a C110 receipt or config."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

from history_profile import HistoryBlocked
from history_diagnostics import failure_projection

TITLE='C112 real history analytics and protected reports'
STEPS=('fresh history database corroborated','separate authenticated mobile sessions',
       'master loads canonical historical analytics','master opens protected shift report',
       'master opens observed historical order report','executor cannot access analytics or reports',
       'read-only database unchanged')


def run(argv,root,env,timeout):
    return subprocess.run(argv,cwd=root,env=env,capture_output=True,timeout=timeout,check=False)


def contract_inputs(root):
    c=json.loads((root/'ops/ci/history_contract.json').read_text())
    if (c.get('accepted') is not True or c.get('required_test_title')!=TITLE
            or c.get('expected_test_count')!=1 or c.get('project')!='c112-android-chromium'
            or c.get('config_path')!='tests/e2e/c112_playwright.config.cjs'
            or any(not re.fullmatch('[a-f0-9]{40}',c.get(k,'')) for k in ('frontend_sha','c112_source_sha'))):
        raise HistoryBlocked('C112_EXACT_SOURCE_CONTRACT_REQUIRED')
    expected=c.get('source_blobs',{})
    if len(expected)!=18:
        raise HistoryBlocked('C112_COMPLETE_SOURCE_MANIFEST_REQUIRED')
    for name,digest in expected.items():
        if not re.fullmatch(r'tests/e2e/(?:c112_[A-Za-z0-9_.]+|package(?:-lock)?\.json)',name):
            raise HistoryBlocked('C112_INVALID_SOURCE_PATH')
        file=root/name
        if file.is_symlink() or not file.is_file():
            raise HistoryBlocked('C112_SOURCE_INPUT_MISSING')
        raw=file.read_bytes()
        if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=digest:
            raise HistoryBlocked('C112_SOURCE_BLOB_MISMATCH')
    package=json.loads((root/'tests/e2e/package.json').read_text())
    if {**package.get('dependencies',{}),**package.get('devDependencies',{})}.get('@playwright/test')!='1.63.0':
        raise HistoryBlocked('C112_LOCKED_PLAYWRIGHT_REQUIRED')
    for file in ('ops/demo/prepare.py','ops/demo/compose.yaml','ops/demo/compose.workers.yaml',
                 'ops/provision/history_demo.py','scripts/synthetic/load_demo.py','scripts/synthetic/generate.py'):
        if not (root/file).is_file(): raise HistoryBlocked('C112_HISTORY_SOURCE_INPUT_MISSING')
    return c


def secrecy_preflight(root,env,private):
    if any(value and (key.startswith('PG') or key in {'DALA_E2E_MASTER_PIN_FILE','DALA_E2E_EXECUTOR_PIN_FILE',
        'DALA_E2E_FIXTURE_FILE','DALA_C112_OBSERVER_DATABASE_URL'}) for key,value in env.items()):
        raise HistoryBlocked('C112_PREFLIGHT_BEFORE_PRIVATE_INPUTS_REQUIRED')
    target=private/'c112-preflight-receipt.json'
    if target.exists() or target.is_symlink():
        raise HistoryBlocked('C112_FRESH_PREFLIGHT_REQUIRED')
    proof_env=dict(env,DALA_C112_PREFLIGHT_RECEIPT=str(target))
    result=run(['node',str(root/'tests/e2e/c112_secrecy_preflight.cjs')],root,proof_env,90)
    if result.returncode or not target.is_file() or target.is_symlink() or target.stat().st_size>16384:
        raise HistoryBlocked('C112_DUMMY_FAILURE_PREFLIGHT_NOT_PROVEN')
    proof=json.loads(target.read_text())
    if (proof.get('version')!='c112-failure-output-v1' or proof.get('result')!='PASS'
            or proof.get('frontend_sha')!=env['DALA_E2E_FRONTEND_SHA'] or proof.get('run_id')!=env['DALA_C112_RUN_ID']
            or proof.get('expected_dummy_failures')!=1 or proof.get('observed_dummy_failures')!=1
            or proof.get('sentinel_matches')!=0):
        raise HistoryBlocked('C112_PREFLIGHT_RECEIPT_INVALID')
    checked=run(['node','-e',"require('./tests/e2e/c112_preflight_proof.cjs').requireProof()"],root,proof_env,30)
    if checked.returncode: raise HistoryBlocked('C112_SOURCE_BOUND_PREFLIGHT_INVALID')
    return target,{key:proof[key] for key in ('version','result','playwright','source_sha','frontend_sha','run_id',
        'created_at','expected_dummy_failures','observed_dummy_failures','scanned_outputs','sentinel_matches','scanned_output_sha256')}


def execute_history(root,env,private,cli,summary):
    parent=root/'tests/e2e/c112_artifacts'
    if parent.exists() or parent.is_symlink():
        raise HistoryBlocked('C112_ARTIFACT_TREE_MUST_BE_FRESH')
    parent.mkdir(mode=0o700)
    folder=parent/env['DALA_C112_RUN_ID']
    report=folder/'playwright.json'; evidence=folder/'evidence.json'
    try:
        try:
            result=run(['node',str(cli),'test','--config',str(root/'tests/e2e/c112_playwright.config.cjs')],root,env,300)
            runner_code=result.returncode
        except Exception:
            runner_code=1
        # Mandatory even when a browser test or its report is missing.
        gate=run(['node',str(root/'tests/e2e/c112_gate.cjs'),str(report),str(evidence)],root,env,30)
        receipt={}
        try: receipt=json.loads(gate.stdout)
        except Exception: pass
        if runner_code or gate.returncode or receipt.get('status')!='PASS':
            summary['history_diagnostic']=failure_projection(report,evidence)
            raise HistoryBlocked('C112_REAL_HISTORY_OR_EVIDENCE_GATE_FAILED')
        if evidence.is_symlink() or evidence.stat().st_size>4*1024*1024:
            raise HistoryBlocked('C112_BOUNDED_EVIDENCE_REQUIRED')
        raw=evidence.read_bytes()
        for name in ('master_pin','executor_pin','postgres_owner_password','postgres_runtime_password','postgres_worker_password'):
            secret=(private/name).read_bytes().strip()
            if secret and secret in raw: raise HistoryBlocked('C112_PUBLIC_EVIDENCE_SECRET_DETECTED')
        body=json.loads(raw)
        # Values here follow the independent gate, not a substitute success oracle.
        summary.update(tests_passed=1,tests_failed=0,tests_skipped=0,asserted_steps=len(body['steps']),
            protected_api_observations=len(body['observations']),executor_denials=len(body['restrictions']),
            business_rows_unchanged=body['database_before']['business_sha256']==body['database_after']['business_sha256'],
            historical_orders=body['database_after']['counts']['orders'],
            historical_submissions=body['database_after']['counts']['submissions'],
            unavailable_photo_references=body['database_after']['after_photo_references'])
        return body,receipt
    finally:
        shutil.rmtree(parent)
