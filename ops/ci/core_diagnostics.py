"""Allowlisted C110 failure location/progress, with no raw messages or business values."""
import json
from pathlib import Path
import re
import subprocess
import sys
import sysconfig

STAGES = (
    'separate authenticated browser contexts',
    'master creates unplanned order through composed UI',
    'executor queue accept start pause resume',
    'incomplete result cannot close and master returns for rework',
    'executor supplies actual upload work code and materials',
    'human closure persists and full event history is visible',
)
ACTIONS = {'create','queue','accept','start','pause','resume','submit','review'}
SOURCE_FILES = {'c110_core.spec.cjs','c110_contract.cjs','c110_private_boundary.cjs','c110_playwright.config.cjs','c110_preflight_proof.cjs'}


def bounded_count(value, maximum=64):
    return min(len(value), maximum) if isinstance(value, list) else 0


def failure_projection(report: Path, evidence: Path | None) -> dict:
    out={'scope':'diagnostic_only_no_core_pass','report':'unavailable','stages':[], 'committed_command_count':0,
         'error_classes':[], 'source_locations':[]}
    try:
        if not report.is_file() or report.stat().st_size > 4*1024*1024:
            return out
        data=json.loads(report.read_text()); out['report']='present'
        errors=list(data.get('errors', [])); tests=[]
        def visit(suites):
            for suite in suites[:32]:
                for spec in suite.get('specs', [])[:32]:
                    for test in spec.get('tests', [])[:8]:
                        tests.append(test)
                        for result in test.get('results', [])[:8]:
                            errors.extend(result.get('errors', []))
                visit(suite.get('suites', [])[:32])
        visit(data.get('suites', []))
        out['observed_tests']=min(len(tests),32)
        classes=set(); locations=set()
        for error in errors[:32]:
            message=str(error.get('message',''))
            signatures={
                'MASTER_LOGIN_BOUNDARY_FAILED':'synthetic master login failed; credential-bearing details suppressed',
                'EXECUTOR_LOGIN_BOUNDARY_FAILED':'synthetic executor login failed; credential-bearing details suppressed',
                'READONLY_OBSERVER_FAILED':'PostgreSQL observer unavailable; subprocess details suppressed',
                'AUTHENTICATED_HTTP_READ_FAILED':'authenticated API read unavailable; transport details suppressed',
                'ASSERTION_TIMEOUT':'Timed out',
                'LOCATOR_TIMEOUT':'TimeoutError',
                'PREFLIGHT_PROOF_REJECTED':'verified current-source dummy-failure secrecy proof required',
                'EFFECTIVE_RUNNER_REJECTED':'effective reporters must match',
            }
            classes.update(name for name,signature in signatures.items() if signature in message)
            location=error.get('location',{})
            basename=Path(str(location.get('file',''))).name
            line=location.get('line')
            if basename in SOURCE_FILES and type(line) is int and 1<=line<=2000:
                locations.add((basename,line))
            for basename,line in re.findall(r'(c110_[A-Za-z_]+\.(?:spec\.)?cjs):(\d+):\d+',str(error.get('stack',''))):
                if basename in SOURCE_FILES and 1<=int(line)<=2000:
                    locations.add((basename,int(line)))
        out['error_classes']=sorted(classes)
        out['source_locations']=[{'file':file,'line':line} for file,line in sorted(locations)[:8]]
        if evidence and evidence.is_file() and evidence.stat().st_size<=1024*1024:
            body=json.loads(evidence.read_text())
            for stage in body.get('steps', [])[:6]:
                if stage.get('name') in STAGES:
                    out['stages'].append({'stage_id':STAGES.index(stage['name'])+1,
                                          'result':stage.get('result') if stage.get('result') in {'PASS','FAIL'} else 'unknown'})
            commands=body.get('commands', [])
            out['committed_command_count']=bounded_count(commands,32)
            if commands and isinstance(commands,list) and commands[-1].get('action') in ACTIONS:
                out['last_committed_action']=commands[-1]['action']
    except Exception:
        out['projection_incomplete']=True
    return out


def python_environment(env: dict) -> tuple[dict, str]:
    """Credential-free import probe; only derive an interpreter-owned lib path if needed."""
    command=[sys.executable,'-c','import psycopg']
    check=subprocess.run(command,env=env,capture_output=True,timeout=20,check=False)
    if check.returncode==0:
        return env,'PASS_FILTERED_ENV'
    library=Path(sysconfig.get_config_var('LIBDIR') or '').resolve()
    prefix=Path(sys.base_prefix).resolve()
    if library.is_dir() and library.is_relative_to(prefix) and library!=prefix:
        candidate=dict(env,LD_LIBRARY_PATH=str(library))
        retry=subprocess.run(command,env=candidate,capture_output=True,timeout=20,check=False)
        if retry.returncode==0:
            return candidate,'PASS_INTERPRETER_OWN_LIBDIR_ONLY'
    return env,'FAIL_PYTHON_OR_PSYCOPG_IMPORT'
