"""Stage the exact historical baseline schema, then run the non-skipping gate.

Current application Python is used. This does not validate newer worker schema
extensions or import history into the live two-account demo database.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT=Path(__file__).resolve().parents[1]
FILES=('backend/db/migrations/001_vertical_slice.sql',
       'backend/db/migrations/002_trusted_evidence.sql',
       'backend/db/migrations/004_immutable_reference_keys.sql',
       'backend/db/proposals/003_auth_rate_limits.sql')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-inputs',action='store_true')
    args=parser.parse_args()
    if not args.check_inputs:
        if os.environ.get('DALA_C107_DISPOSABLE')!='1' or not os.environ.get('DALA_C107_DATABASE_URL'):
            raise SystemExit('NOT_RUN: explicit disposable C107 database required')
        from psycopg.conninfo import conninfo_to_dict
        parts=conninfo_to_dict(os.environ['DALA_C107_DATABASE_URL'])
        if (parts.get('host') not in {'127.0.0.1','localhost','::1'} or
                any(parts.get(key) for key in ('service','servicefile','hostaddr')) or
                any(os.environ.get(key) for key in ('PGSERVICE','PGSERVICEFILE','PGHOSTADDR'))):
            raise SystemExit('BLOCKED: C107 CI wrapper requires a direct localhost disposable database')
    with TemporaryDirectory(prefix='dalaai-c107-baseline-') as directory:
        fixture=Path(directory)
        for name in FILES:
            target=fixture/name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/name,target)
        environment=dict(os.environ,DALA_C107_MIGRATION_ROOT=str(fixture))
        command=[sys.executable,str(ROOT/'backend/tests/integration/test_c107_history_postgres.py')]
        if args.check_inputs:command.append('--check-inputs')
        return subprocess.run(command,env=environment,cwd=ROOT).returncode

if __name__=='__main__':raise SystemExit(main())
