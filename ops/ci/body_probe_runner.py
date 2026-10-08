#!/usr/bin/env python3
"""One isolated body diagnostic. Never establishes C113 acceptance."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from uuid import uuid4

from fixtures import ORIGIN,prepare_private,prepare_tls,write_private
from run_mobile import clean_environment,wait_ready
from c110_driver import verify_frontend_provenance,observer_dsn
from controls_runner import public_fixture,clock_instance
from controls_profile import ControlsBlocked,compose_command,validate_profile,validate_actual_services
from startup_diagnostics import collect as startup_diagnostics
from body_probe_driver import PRODUCT,FRONTEND,contract_inputs,source_hash,preflight,execute_probe,require,run
from body_probe_observer import render

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent


def browser_environment(env,private,package,browsers,run_id):
    return dict(env,HOME=str(private/'browser-home'),XDG_CONFIG_HOME=str(private/'browser-home/.config'),
        XDG_DATA_HOME=str(private/'browser-home/.local/share'),NODE_EXTRA_CA_CERTS=str(private/'tls/root.crt'),
        SSL_CERT_FILE=str(private/'tls/root.crt'),PLAYWRIGHT_BROWSERS_PATH=str(browsers),
        DALA_BCP_PLAYWRIGHT_PACKAGE=str(package),DALA_BCP_PRODUCT_SHA=PRODUCT,
        DALA_E2E_FRONTEND_SHA=FRONTEND,DALA_BCP_RUN_ID=run_id)


def run_probe(summary):
    for name in ('docker','node','openssl','certutil'):
        if not shutil.which(name):raise ControlsBlocked('BODY_PROBE_REQUIRED_TOOL_MISSING')
    if (ROOT/'body-probe-evidence.json').exists() or (ROOT/'body-probe-evidence.json').is_symlink():
        raise ControlsBlocked('BODY_PROBE_FRESH_PUBLIC_OUTPUT_REQUIRED')
    sha=source_hash(ROOT,os.environ);summary.update(source_sha=sha,product_sha=PRODUCT,frontend_sha=FRONTEND)
    verify_frontend_provenance(ROOT,ROOT/'.ci-body-probe-frontend-reference',FRONTEND)
    package=ROOT/'tests/e2e/node_modules/@playwright/test'
    locator=os.environ.get('PLAYWRIGHT_BROWSERS_PATH','')
    browsers=Path(locator)
    if (not (package/'cli.js').is_file() or not locator or not browsers.is_absolute()
            or not browsers.is_dir() or browsers.is_symlink() or any(ord(c)<32 or ord(c)==127 for c in locator)):
        raise ControlsBlocked('BODY_PROBE_INSTALLED_BROWSER_LOCATOR_REQUIRED')
    env=clean_environment()
    if env.get('DOCKER_HOST','unix:///var/run/docker.sock')!='unix:///var/run/docker.sock' or env.get('DOCKER_CONTEXT','default')!='default':
        raise ControlsBlocked('BODY_PROBE_LOCAL_DEFAULT_DOCKER_REQUIRED')
    env.update(DOCKER_HOST='unix:///var/run/docker.sock',PYTHONDONTWRITEBYTECODE='1')
    project='dalaai-controls-ci-'+uuid4().hex[:16]
    with tempfile.TemporaryDirectory(prefix='dalaai-body-probe-') as temp:
        private=Path(temp)/'private';prepare_private(private,credentials=False)
        write_private(private/'.controls-owner','dalaai-controls-ci-v1')
        write_private(private/'.body-probe-owner','dalaai-body-probe-private-v1')
        prepare_tls(private)
        browser_env=browser_environment(env,private,package,browsers,'bcp-'+uuid4().hex)
        summary['stage']='credential_free_inspector_import'
        require(run([sys.executable,'-c','import zipfile,xml.etree.ElementTree,zlib'],ROOT,
            {'PATH':env['PATH'],'LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'},20),'BODY_PROBE_INSPECTOR_PYTHON_UNAVAILABLE')
        summary['stage']='fresh_body_probe_dummy_preflight'
        proof,summary['secrecy_preflight']=preflight(ROOT,browser_env,private)
        # The independent proof must succeed before any actual PIN/DB fixture exists.
        summary['stage']='history_clock_fixture_preparation'
        require(run([sys.executable,str(ROOT/'ops/demo/prepare.py'),'--workers','--fixture-mode','history',
            '--demo-clock','true','--directory',str(private),'--domain','localhost','--bind','127.0.0.1',
            '--http-port','18080','--https-port','18443'],ROOT,env,60),'BODY_PROBE_FIXTURE_PREPARATION_FAILED')
        clock=clock_instance(private)
        public_fixture(ROOT,private/'fixture.json')
        compose_env=dict(env,DALA_CI_PRIVATE_DIR=str(private),DALA_CI_ROOT_DIR=str(ROOT),
            DALA_CI_SOURCE_DIR=str(HERE),DALA_CI_COMPOSE_PROJECT=project,DALA_DEMO_CLOCK_INSTANCE_ID=clock)
        compose=compose_command(ROOT,private,project);started=False
        try:
            summary['stage']='history_clock_compose_config'
            config=run([*compose,'--profile','c113-inactive','config','--format','json'],ROOT,compose_env,30)
            require(config,'BODY_PROBE_COMPOSE_CONFIG_FAILED')
            summary['declared_service_inventory']=validate_profile(json.loads(config.stdout),ROOT)
            summary['stage']='history_clock_compose_start';started=True
            result=run([*compose,'up','--build','--detach','--wait','--wait-timeout','240','api','web','observer'],ROOT,compose_env,900)
            if result.returncode:
                summary['startup_diagnostic']=startup_diagnostics(compose,compose_env,ROOT,result.stdout+result.stderr)
                raise ControlsBlocked('BODY_PROBE_COMPOSE_START_FAILED')
            result=run([*compose,'ps','--all','--format','json'],ROOT,compose_env,30)
            require(result,'BODY_PROBE_INVENTORY_UNAVAILABLE')
            try:rows=json.loads(result.stdout)
            except json.JSONDecodeError:rows=[json.loads(line) for line in result.stdout.decode().splitlines() if line.strip()]
            summary['actual_service_inventory']=validate_actual_services([rows] if isinstance(rows,dict) else rows)
            mapping=run([*compose,'port','db','5432'],ROOT,compose_env,15)
            if mapping.returncode==0 and mapping.stdout.strip():raise ControlsBlocked('BODY_PROBE_DATABASE_PUBLISHED')
            summary['stage']='trusted_https_readiness';wait_ready(private/'tls/root.crt')
            public_env=dict(browser_env,DALA_C113_PLAYWRIGHT_PACKAGE=str(package))
            require(run(['node',str(HERE/'controls_transport_probe.cjs')],ROOT,public_env,60),'BODY_PROBE_PUBLIC_TLS_FAILED')
            summary['public_tls_probe']='PASS'
            adapter=private/'body-probe-observer-python'
            write_private(adapter,render(ROOT,private,project,clock,sha,Path(sys.executable).resolve()));os.chmod(adapter,0o700)
            browser_env.update(DALA_BCP_PREFLIGHT_RECEIPT=str(proof),DALA_BCP_AUTHORIZED='operator-provisioned-synthetic-only',
                DALA_BCP_WORKERS_DISABLED='ai,delivery,providers',DALA_E2E_BASE_URL=ORIGIN,DALA_E2E_BACKEND_SHA=PRODUCT,
                DALA_E2E_FIXTURE_FILE=str(private/'fixture.json'),DALA_E2E_MASTER_PIN_FILE=str(private/'master_pin'),
                DALA_E2E_EXECUTOR_PIN_FILE=str(private/'executor_pin'),DALA_BCP_DATABASE_SCHEMA='dalaai_demo',
                DALA_BCP_OBSERVER_DATABASE_URL=observer_dsn(private),DALA_BCP_PYTHON=str(adapter),
                DALA_BCP_INSPECT_PYTHON=str(Path(sys.executable).resolve()))
            summary['stage']='instrumented_body_diagnostic'
            evidence,code=execute_probe(ROOT,browser_env,private,summary)
            if source_hash(ROOT,os.environ)!=sha:raise ControlsBlocked('BODY_PROBE_SOURCE_CHANGED')
            contract_inputs(ROOT)
        finally:
            if started:
                summary['cleanup']='pending'
                result=run([*compose,'down','--volumes','--remove-orphans'],ROOT,compose_env,120)
                if result.returncode:
                    summary['cleanup']='failed';raise ControlsBlocked('BODY_PROBE_COMPOSE_CLEANUP_FAILED')
            summary['cleanup']='completed'
        with (ROOT/'body-probe-evidence.json').open('x') as stream:stream.write(json.dumps(evidence,indent=2)+'\n')
        summary['status']=evidence['status'];summary['stage']='completed'
        return 0 if code==0 and evidence['status']!='BLOCKED' else 2


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check-inputs',action='store_true')
    args=parser.parse_args()
    summary={'schema_version':1,'status':'BLOCKED','stage':'source_inputs','observed_at':datetime.now(timezone.utc).isoformat(),
        'scope':'INSTRUMENTED_DIAGNOSTIC_ONLY','c113_acceptance':'NOT_ESTABLISHED','baseline_failed_run':'37726366034',
        'deployment_performed':False,'physical_android':'NOT_RUN','providers':'NOT_RUN','full_cycle_green':False}
    try:
        contract_inputs(ROOT)
        if args.check_inputs:print('PASS: immutable body probe and shared source inputs');return 0
        status=run_probe(summary)
    except ControlsBlocked as error:
        # Codes raised by shared source are fixed literals too.
        summary['reason_code']=str(error);status=2
    except Exception:
        summary['reason_code']='BODY_PROBE_UNEXPECTED_RUNNER_FAILURE';status=2
    if args.check_inputs:print('BLOCKED: body probe source inputs');return 2
    (ROOT/'body-probe-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2));return status


if __name__=='__main__':raise SystemExit(main())
