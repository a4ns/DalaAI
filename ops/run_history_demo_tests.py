"""Mandatory history/live fixture gate in a disposable local PostgreSQL service."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-reports',action='store_true')
    args=parser.parse_args()
    if os.environ.get('DALA_ACCEPTANCE_DISPOSABLE')!='1' or not os.environ.get('DALA_TEST_DATABASE_URL'):
        raise SystemExit('NOT_RUN: explicit disposable PostgreSQL database required')
    sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'backend/tests')]
    from psycopg.conninfo import conninfo_to_dict
    parts=conninfo_to_dict(os.environ['DALA_TEST_DATABASE_URL'])
    if (parts.get('host') not in {'127.0.0.1','localhost','::1'} or not parts.get('dbname') or
            any(parts.get(k) for k in ('service','servicefile','hostaddr')) or
            any(os.environ.get(k) for k in ('PGSERVICE','PGSERVICEFILE','PGHOSTADDR'))):
        raise SystemExit('BLOCKED: direct localhost disposable database required')
    from test_persistence_role import ApplicationRoleTests
    ApplicationRoleTests.setUpClass()
    try:
        environment=dict(os.environ,DALA_ACCEPTANCE_RUNTIME_DATABASE_URL=ApplicationRoleTests.runtime_dsn,
            DALA_HISTORY_DEMO_DISPOSABLE='1',DALA_DEMO_TEST_BACKEND=str(ROOT/'backend'))
        command=[sys.executable,str(ROOT/'ops/provision/tests/test_history_demo_postgres.py')]
        if args.with_reports:command.append('--with-reports')
        return subprocess.run(command,env=environment,cwd=ROOT).returncode
    finally:
        ApplicationRoleTests.doClassCleanups()
        if ApplicationRoleTests.tearDown_exceptions:
            raise SystemExit('FAIL: disposable history-role cleanup not confirmed')

if __name__=='__main__':raise SystemExit(main())
