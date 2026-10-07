"""Own a disposable CI login, then run the frozen actual-app lifecycle harness."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend/acceptance'))
from vertical_acceptance.support import require_local_dsn


def main():
    frozen = ROOT/'backend/acceptance/runtime_delta'
    for path, expected in json.loads((frozen/'REVIEWED_INPUTS.json').read_text())['owned_files'].items():
        if hashlib.sha256((frozen/path).read_bytes()).hexdigest() != expected:
            raise SystemExit(f'Frozen runtime harness changed: {path}')
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    dsn=os.environ.get('DALA_TEST_DATABASE_URL','')
    if not dsn:
        raise SystemExit('NOT_RUN: explicit disposable PostgreSQL DSN required')
    require_local_dsn(dsn,conninfo_to_dict)
    if any(os.environ.get(key) for key in ('PGSERVICE','PGSERVICEFILE','PGHOSTADDR')):
        raise SystemExit('NOT_RUN: ambient PostgreSQL service/address indirection is forbidden')
    role='a5_mounted_'+uuid4().hex
    password=secrets.token_urlsafe(32)
    created=False
    result=1
    report=ROOT/'mounted-runtime-acceptance.json'
    sha=os.environ.get('GITHUB_SHA') or subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    try:
        with psycopg.connect(dsn,autocommit=True,connect_timeout=5) as db:
            db.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS').format(sql.Identifier(role),sql.Literal(password)))
            created=True
        runtime_dsn=make_conninfo(dsn,user=role,password=password)
        with tempfile.TemporaryDirectory(prefix='dalaai-mounted-assembly-') as temp:
            backend=Path(temp)/'backend'
            shutil.copytree(ROOT/'backend',backend,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            shutil.copyfile(backend/'db/proposals/003_auth_rate_limits.sql',backend/'db/migrations/003_auth_rate_limits.sql')
            env=dict(os.environ,DALA_ACCEPTANCE_DISPOSABLE='1',DALA_ACCEPTANCE_RUNTIME_DATABASE_URL=runtime_dsn,PYTHONDONTWRITEBYTECODE='1')
            env['PYTHONPATH']=os.pathsep.join([str(ROOT/'backend/acceptance'),str(backend),env.get('PYTHONPATH','')])
            result=subprocess.run([sys.executable,str(ROOT/'backend/acceptance/runtime_delta/run_runtime.py'),
                '--backend',str(backend),'--source-sha',sha,'--report',str(report),'--run'],env=env).returncode
        if report.exists():
            data=json.loads(report.read_text())
            print(json.dumps({key:data.get(key) for key in ('status','source_sha','application_entrypoint',
                'owner_startup_rejection','runtime_identity','phases','cleanup','error_type','runtime_error_code','reason')},indent=2))
    except Exception as error:
        print('FAIL: actual runtime harness setup',type(error).__name__)
        result=1
    finally:
        if created:
            try:
                with psycopg.connect(dsn,autocommit=True,connect_timeout=5) as db:
                    db.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
                print('PASS: disposable runtime login removed')
            except Exception as error:
                print('FAIL: disposable login cleanup',type(error).__name__)
                result=1
    return result


if __name__=='__main__':
    raise SystemExit(main())
