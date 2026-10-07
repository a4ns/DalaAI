"""Fixed sidecar entry: one assigned runtime secret, then unchanged read-only C observer."""
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
from uuid import UUID


def main():
    try:
        if len(sys.argv) != 2:
            raise ValueError('one UUID required')
        order_id=str(UUID(sys.argv[1]))
        dsn=urlsplit(Path('/run/secrets/runtime_dsn').read_text().strip())
        if (dsn.scheme!='postgresql' or dsn.hostname!='db' or dsn.port!=5432
                or dsn.username!='naryadai_api' or not dsn.password or dsn.path!='/naryadai'
                or dsn.query or dsn.fragment):
            raise ValueError('assigned runtime DSN invalid')
        if os.environ.get('DALA_C110_AUTHORIZED')!='operator-provisioned-synthetic-only' or os.environ.get('DALA_C110_DATABASE_SCHEMA')!='dalaai_demo':
            raise ValueError('isolated observer configuration required')
        os.environ['DALA_C110_OBSERVER_DATABASE_URL']=f'postgresql://naryadai_api:{dsn.password}@127.0.0.1:5432/naryadai'
        os.execv(sys.executable,[sys.executable,'/ci/c110_observe.py',order_id])
    except Exception:
        print(json.dumps({'status':'BLOCKED','code':'C110_DB_OBSERVATION_UNAVAILABLE','error_type':'ObserverRunnerError'}))
        return 2


if __name__=='__main__':
    raise SystemExit(main())
