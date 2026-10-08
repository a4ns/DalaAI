#!/usr/bin/env python3
"""Separate C113 clock-controls/download gate on a fresh real synthetic stack."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from uuid import UUID, uuid4

from fixtures import ORIGIN, prepare_private, prepare_tls, write_private
from run_mobile import clean_environment, wait_ready
from c110_driver import verify_frontend_provenance, observer_dsn, C110Error
from startup_diagnostics import collect as startup_diagnostics
from controls_driver import contract_inputs, secrecy_preflight, execute_controls, run
from controls_profile import ControlsBlocked, compose_command, public_actor_ids, validate_profile, validate_actual_services

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent


def source_hash(root):
    value=run(['git','rev-parse','HEAD'],root,os.environ,15)
    sha=value.stdout.decode().strip()
    if value.returncode or not re.fullmatch('[a-f0-9]{40}',sha) or os.environ.get('GITHUB_SHA',sha)!=sha:
        raise ControlsBlocked('C113_EXACT_CHECKOUT_REQUIRED')
    paths=['backend','frontend','ops','tests/e2e','.github/workflows/controls-mobile-e2e.yml']
    if run(['git','diff','--exit-code','HEAD','--',*paths],root,os.environ,15).returncode:
        raise ControlsBlocked('C113_CLEAN_SOURCE_REQUIRED')
    extra=run(['git','ls-files','--others','--exclude-standard','--',*paths],root,os.environ,15)
    if extra.returncode or extra.stdout.strip(): raise ControlsBlocked('C113_NO_UNTRACKED_SOURCE_REQUIRED')
    return sha


def public_fixture(root,target):
    directory=root/'ops/provision'
    sys.path.insert(0,str(directory))
    try:
        spec=importlib.util.spec_from_file_location('c113_public_history',directory/'history_demo.py')
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        manifest=module.public_manifest()
    finally: sys.path.remove(str(directory))
    public_actor_ids(manifest)
    write_private(target,json.dumps(manifest,ensure_ascii=False))
    return manifest


def require(result,code):
    if result.returncode: raise ControlsBlocked(code)


def clock_instance(private):
    if (private/'.controls-owner').read_text()!='dalaai-controls-ci-v1':
        raise ControlsBlocked('C113_OWNED_CLOCK_INPUT_REQUIRED')
    for name in ('clock_mode','clock_instance'):
        file=private/name
        if file.is_symlink() or not file.is_file() or file.stat().st_size>100:
            raise ControlsBlocked('C113_FRESH_CLOCK_INPUT_REQUIRED')
    value=(private/'clock_instance').read_text().strip()
    if (private/'clock_mode').read_text().strip()!='true' or str(UUID(value))!=value:
        raise ControlsBlocked('C113_INVALID_CLOCK_INSTANCE')
    return value


def run_gate(summary,c):
    for name in ('docker','node','openssl','certutil'):
        if not shutil.which(name): raise ControlsBlocked('C113_REQUIRED_RUNNER_TOOL_MISSING')
    for name in ('controls-ci-evidence.json','controls-ci-gate.json'):
        if (ROOT/name).exists() or (ROOT/name).is_symlink(): raise ControlsBlocked('C113_FRESH_PUBLIC_OUTPUT_REQUIRED')
    summary.update(source_sha=source_hash(ROOT),frontend_sha=c['frontend_sha'],accepted_c113_source_sha=c['c113_source_sha'])
    try: verify_frontend_provenance(ROOT,ROOT/'.ci-c113-frontend-reference',c['frontend_sha'])
    except C110Error: raise ControlsBlocked('C113_BUILT_FRONTEND_PROVENANCE_MISMATCH') from None
    package=ROOT/'tests/e2e/node_modules/@playwright/test'; cli=package/'cli.js'
    if not cli.is_file(): raise ControlsBlocked('C113_LOCKED_DEPENDENCIES_REQUIRED')
    project='dalaai-controls-ci-'+uuid4().hex[:16]
    env=clean_environment()
    if env.get('DOCKER_HOST','unix:///var/run/docker.sock')!='unix:///var/run/docker.sock' or env.get('DOCKER_CONTEXT','default')!='default':
        raise ControlsBlocked('C113_LOCAL_DEFAULT_DOCKER_REQUIRED')
    env.update(DOCKER_HOST='unix:///var/run/docker.sock',PYTHONDONTWRITEBYTECODE='1')
    original_home=Path(env.get('HOME',str(Path.home())))
    with tempfile.TemporaryDirectory(prefix='dalaai-controls-ci-') as temp:
        private=Path(temp)/'private'
        prepare_private(private,credentials=False)
        write_private(private/'.controls-owner','dalaai-controls-ci-v1')
        prepare_tls(private)
        env.update(DALA_CI_PRIVATE_DIR=str(private),DALA_CI_SOURCE_DIR=str(HERE),DALA_CI_ROOT_DIR=str(ROOT),
                   DALA_CI_COMPOSE_PROJECT=project,DALA_MODEL_FORCE_OFF='true',DALA_WEB_PUSH_ENABLED='false',
                   DALA_DEMO_FIXTURE_MODE='history',DALA_DEMO_CLOCK_ENABLED='true')
        browser_env=dict(env,HOME=str(private/'browser-home'),
            XDG_CONFIG_HOME=str(private/'browser-home/.config'),XDG_DATA_HOME=str(private/'browser-home/.local/share'),
            NODE_EXTRA_CA_CERTS=str(private/'tls/root.crt'),SSL_CERT_FILE=str(private/'tls/root.crt'),
            PLAYWRIGHT_BROWSERS_PATH=env.get('PLAYWRIGHT_BROWSERS_PATH',str(original_home/'.cache/ms-playwright')),
            DALA_C113_PLAYWRIGHT_PACKAGE=str(package),DALA_E2E_FRONTEND_SHA=c['frontend_sha'],
            DALA_C113_RUN_ID='c113-'+uuid4().hex)
        summary['stage']='credential_free_inspector_import'
        inspect_env={'PATH':env['PATH'],'LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'}
        require(run([sys.executable,'-c','import zipfile,xml.etree.ElementTree,zlib'],ROOT,inspect_env,20),'C113_INSPECTOR_PYTHON_UNAVAILABLE')
        summary['inspector_python_import']='PASS_FILTERED_STDLIB_ENV'
        summary['stage']='c113_dummy_secret_preflight'
        proof,summary['secrecy_preflight']=secrecy_preflight(ROOT,browser_env,private)
        # No actual login/database material exists until the exact C113 proof passes.
        summary['stage']='history_fixture_preparation'
        prepare=run([sys.executable,str(ROOT/'ops/demo/prepare.py'),'--workers','--fixture-mode','history',
            '--demo-clock','true','--directory',str(private),'--domain','localhost','--bind','127.0.0.1',
            '--http-port','18080','--https-port','18443'],ROOT,env,60)
        require(prepare,'C113_HISTORY_PREPARATION_FAILED')
        clock_id=clock_instance(private)
        env['DALA_DEMO_CLOCK_INSTANCE_ID']=clock_id
        browser_env['DALA_DEMO_CLOCK_INSTANCE_ID']=clock_id
        public_fixture(ROOT,private/'fixture.json')
        compose=compose_command(ROOT,private,project)
        started=False
        try:
            summary['stage']='history_compose_config'
            # Inspect even the inactive profiles; start command below omits them.
            config=run([*compose,'--profile','c113-inactive','config','--format','json'],ROOT,env,30)
            require(config,'C113_COMPOSE_CONFIG_FAILED')
            summary['worker_absence_service_inventory']=validate_profile(json.loads(config.stdout),ROOT)
            summary['stage']='history_compose_build_start'; started=True
            result=run([*compose,'up','--build','--detach','--wait','--wait-timeout','240','api','web','observer'],ROOT,env,900)
            if result.returncode:
                summary['startup_diagnostic']=startup_diagnostics(compose,env,ROOT,result.stdout+result.stderr)
                raise ControlsBlocked('C113_COMPOSE_BUILD_OR_START_FAILED')
            inventory=run([*compose,'ps','--all','--format','json'],ROOT,env,30)
            require(inventory,'C113_ACTUAL_INVENTORY_UNAVAILABLE')
            text=inventory.stdout.decode()
            try: rows=json.loads(text)
            except json.JSONDecodeError: rows=[json.loads(line) for line in text.splitlines() if line.strip()]
            if isinstance(rows,dict): rows=[rows]
            summary['actual_service_inventory']=validate_actual_services(rows)
            mapping=run([*compose,'port','db','5432'],ROOT,env,15)
            if mapping.returncode==0 and mapping.stdout.strip(): raise ControlsBlocked('C113_DATABASE_UNEXPECTEDLY_PUBLISHED')
            summary['stage']='trusted_https_readiness'; wait_ready(private/'tls/root.crt')
            summary['stage']='public_browser_tls_probe'
            probe=run(['node',str(HERE/'controls_transport_probe.cjs')],ROOT,browser_env,60)
            require(probe,'C113_PUBLIC_BROWSER_TLS_PROBE_FAILED')
            if json.loads(probe.stdout).get('status')!='PASS': raise ControlsBlocked('C113_PUBLIC_BROWSER_TLS_PROBE_FAILED')
            summary['browser_transport_probe']={'status':'PASS','scope':'public_health_browser_and_node_tls_only'}
            adapter=private/'controls-observer-python'
            write_private(adapter,(HERE/'controls_observer_python.py').read_text()); os.chmod(adapter,0o700)
            browser_env.update(DALA_E2E_BASE_URL=ORIGIN,DALA_E2E_BACKEND_SHA=summary['source_sha'],
                DALA_E2E_FIXTURE_FILE=str(private/'fixture.json'),DALA_E2E_MASTER_PIN_FILE=str(private/'master_pin'),
                DALA_E2E_EXECUTOR_PIN_FILE=str(private/'executor_pin'),DALA_C113_PREFLIGHT_RECEIPT=str(proof),
                DALA_C113_AUTHORIZED='operator-provisioned-synthetic-only',DALA_C113_WORKERS_DISABLED='ai,delivery,providers',
                DALA_C113_OBSERVER_DATABASE_URL=observer_dsn(private),DALA_C113_DATABASE_SCHEMA='dalaai_demo',
                DALA_C113_PYTHON=str(adapter),DALA_C113_INSPECT_PYTHON=str(Path(sys.executable).resolve()))
            summary['stage']='c113_controls_android_browser'
            evidence,receipt=execute_controls(ROOT,browser_env,private,cli,summary)
            with (ROOT/'controls-ci-evidence.json').open('x') as f: f.write(json.dumps(evidence,indent=2)+'\n')
            with (ROOT/'controls-ci-gate.json').open('x') as f: f.write(json.dumps(receipt,indent=2)+'\n')
            summary['status']='PASS_ANDROID_EMULATION_CLOCK_AND_DOWNLOADS'
        finally:
            if started:
                summary['cleanup']='pending'
                result=run([*compose,'down','--volumes','--remove-orphans'],ROOT,env,120)
                if result.returncode:
                    summary['cleanup']='failed'; raise ControlsBlocked('C113_COMPOSE_CLEANUP_FAILED')
            summary['cleanup']='completed'
    summary['stage']='completed'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-inputs',action='store_true')
    parser.add_argument('--report',type=Path,default=ROOT/'controls-ci-summary.json')
    args=parser.parse_args()
    summary={'schema_version':1,'status':'BLOCKED_NOT_RUN','stage':'input_contract',
        'observed_at':datetime.now(timezone.utc).isoformat(),'scope':'actual_synthetic_clock_controls_and_saved_downloads_android_emulation',
        'c110_lifecycle':'SEPARATE_GATE','physical_android':'NOT_RUN','push_delivery':'NOT_RUN','provider_model':'NOT_RUN',
        'c112_analytics':'SEPARATE_GATE','native_pdf_excel_apps':'NOT_RUN','security_clock_expiry':'NOT_RUN','live_closure':'NOT_RUN','worker_execution':'NOT_RUN',
        'full_cycle_green':False,'deployment_performed':False}
    status=1
    try:
        c=contract_inputs(ROOT)
        if args.check_inputs:
            print('PASS: exact C113 source inputs and locked Playwright are present'); return 0
        run_gate(summary,c); status=0
    except ControlsBlocked as error:
        summary['status']='BLOCKED_NOT_RUN' if summary['stage']=='input_contract' else 'FAIL'
        summary['reason_code']=str(error)
    except Exception:
        summary['status']='FAIL'; summary['reason_code']='C113_UNEXPECTED_RUNNER_FAILURE'
    if args.check_inputs: print('BLOCKED: '+summary['reason_code'])
    else:
        args.report.write_text(json.dumps(summary,indent=2)+'\n'); print(json.dumps(summary,indent=2))
    return status


if __name__=='__main__': raise SystemExit(main())
