"""Separate, source-bound instrumentation; never a C113 acceptance gate."""
import hashlib
import json
from pathlib import Path
import re

from controls_driver import run, contract_inputs as controls_inputs
from controls_profile import ControlsBlocked

PRODUCT='064a7a3785a95d61d7150e7785ff17db892bc110'
FRONTEND='1594a930de4b9f15d11dd35bbc59e5b4b0b1d964'
PROBE='74f164e19c87a1569889b21e0e1f6be4c4bdd40d'
BRANCH='refs/heads/validation/body-capture-probe-20261008'
PROBE_DIR='tests/e2e/body_capture_probe'


def require(result,code):
    if result.returncode: raise ControlsBlocked(code)


def contract_inputs(root):
    c=json.loads((root/'ops/ci/body_probe_contract.json').read_text())
    if (c.get('product_sha'),c.get('frontend_sha'),c.get('probe_sha'))!=(PRODUCT,FRONTEND,PROBE):
        raise ControlsBlocked('BODY_PROBE_EXACT_CONTRACT_REQUIRED')
    controls_inputs(root)
    for group in ('probe_blobs','shared_blobs'):
        rows=c.get(group,{})
        if not rows: raise ControlsBlocked('BODY_PROBE_SOURCE_MANIFEST_REQUIRED')
        for name,digest in rows.items():
            if (Path(name).is_absolute() or '..' in Path(name).parts or not re.fullmatch('[a-f0-9]{40}',digest)):
                raise ControlsBlocked('BODY_PROBE_INVALID_SOURCE_PATH')
            file=root/name
            if file.is_symlink() or not file.is_file(): raise ControlsBlocked('BODY_PROBE_SOURCE_MISSING')
            data=file.read_bytes()
            if hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()!=digest:
                raise ControlsBlocked('BODY_PROBE_SOURCE_MISMATCH')
    actual={str(p.relative_to(root)) for p in (root/PROBE_DIR).iterdir() if p.suffix in ('.cjs','.md')}
    if actual!=set(c['probe_blobs']): raise ControlsBlocked('BODY_PROBE_EXACT_SOURCE_SET_REQUIRED')
    return c


def source_hash(root,env):
    head=run(['git','rev-parse','HEAD'],root,env,15)
    sha=head.stdout.decode().strip()
    if head.returncode or not re.fullmatch('[a-f0-9]{40}',sha) or env.get('GITHUB_SHA')!=sha or env.get('GITHUB_REF')!=BRANCH:
        raise ControlsBlocked('BODY_PROBE_EXACT_ISOLATED_BRANCH_REQUIRED')
    paths=['frontend','backend','ops','scripts/synthetic','tests/e2e','.github/workflows/body-capture-probe.yml']
    require(run(['git','diff','--exit-code','HEAD','--',*paths],root,env,15),'BODY_PROBE_CLEAN_SOURCE_REQUIRED')
    extra=run(['git','ls-files','--others','--exclude-standard','--',*paths],root,env,15)
    if extra.returncode or extra.stdout.strip(): raise ControlsBlocked('BODY_PROBE_NO_UNTRACKED_SOURCE_REQUIRED')
    require(run(['git','diff','--exit-code',PRODUCT,'HEAD','--','frontend','backend','ops/demo','ops/provision','scripts/synthetic'],root,env,15),'BODY_PROBE_UNCHANGED_PRODUCT_REQUIRED')
    return sha


def preflight(root,env,private):
    forbidden={'DALA_E2E_MASTER_PIN_FILE','DALA_E2E_EXECUTOR_PIN_FILE','DALA_E2E_FIXTURE_FILE',
               'DALA_BCP_OBSERVER_DATABASE_URL','DALA_BCP_AUTHORIZED','DALA_BCP_DATABASE_SCHEMA'}
    if any(v and (k.startswith('PG') or k in forbidden) for k,v in env.items()):
        raise ControlsBlocked('BODY_PROBE_PREFLIGHT_BEFORE_PRIVATE_INPUTS_REQUIRED')
    target=private/'body-probe-preflight.json'
    if target.exists() or target.is_symlink(): raise ControlsBlocked('BODY_PROBE_FRESH_PROOF_REQUIRED')
    bound=dict(env,DALA_BCP_PREFLIGHT_RECEIPT=str(target))
    require(run(['node',str(root/PROBE_DIR/'secrecy_preflight.cjs')],root,bound,90),'BODY_PROBE_DUMMY_PREFLIGHT_UNPROVEN')
    if target.is_symlink() or not target.is_file() or target.stat().st_size>=65536:
        raise ControlsBlocked('BODY_PROBE_BOUNDED_PROOF_REQUIRED')
    require(run(['node','-e',"require('./tests/e2e/body_capture_probe/proof.cjs').requireProof()"],root,bound,30),'BODY_PROBE_SOURCE_BOUND_PROOF_REQUIRED')
    proof=json.loads(target.read_text())
    return target,{k:proof[k] for k in ('version','result','scope','playwright','source_sha','product_sha','frontend_sha','run_id','created_at','expected_failures','observed_failures','scanned_outputs','sentinel_matches','scanned_sha256')}


def execute_probe(root,env,private,summary):
    target=private/'body-probe-safe.json'
    if target.exists() or target.is_symlink(): raise ControlsBlocked('BODY_PROBE_FRESH_SAFE_OUTPUT_REQUIRED')
    bound=dict(env,DALA_BCP_SAFE_RESULT=str(target))
    result=run(['node',str(root/PROBE_DIR/'execute.cjs')],root,bound,330)
    if not target.is_file() or target.is_symlink() or target.stat().st_size>=32768:
        raise ControlsBlocked('BODY_PROBE_SAFE_RESULT_UNAVAILABLE')
    # Validate again with the immutable producer schema; all subprocess output stays private.
    verify="const f=require('node:fs'),p=require('./tests/e2e/body_capture_probe/proof.cjs');require('./tests/e2e/body_capture_probe/observations.cjs').validateEvidence(JSON.parse(f.readFileSync(process.env.DALA_BCP_SAFE_RESULT)),p.requireProof());"
    require(run(['node','-e',verify],root,bound,30),'BODY_PROBE_SAFE_SCHEMA_REQUIRED')
    raw=target.read_bytes()
    for name in ('master_pin','executor_pin','postgres_owner_password','postgres_runtime_password','postgres_worker_password'):
        secret=(private/name).read_bytes().strip()
        if secret and secret in raw: raise ControlsBlocked('BODY_PROBE_PUBLIC_SECRET_DETECTED')
    body=json.loads(raw)
    summary.update(probe_status=body['status'],interpretation=body['interpretation'],probe_phase=body['phase'],
                   cdp=body['cdp'],request_before=body['request_before'],request_after=body['request_after'],
                   ui_before=body['ui_before'],ui_after=body['ui_after'],ui_at_save=body['ui_at_save'],
                   saved=body['saved'],authority=body['authority'],database_unchanged=body['database_unchanged'],
                   instrumentation_cleanup=body['cleanup'])
    return body,result.returncode
