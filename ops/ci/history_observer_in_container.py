"""C112 sidecar entry: assigned runtime input, then unchanged read-only observer."""
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
from uuid import UUID


def main():
    try:
        if len(sys.argv) != 3:
            raise ValueError('two UUIDs required')
        actors=[str(UUID(value)) for value in sys.argv[1:]]
        if actors[0]==actors[1]: raise ValueError('distinct public actors required')
        dsn=urlsplit(Path('/run/secrets/runtime_dsn').read_text().strip())
        if (dsn.scheme!='postgresql' or dsn.hostname!='db' or dsn.port!=5432
                or dsn.username!='naryadai_api' or not dsn.password or dsn.path!='/naryadai'
                or dsn.query or dsn.fragment):
            raise ValueError('assigned runtime DSN invalid')
        if os.environ.get('DALA_C112_AUTHORIZED')!='operator-provisioned-synthetic-only' or os.environ.get('DALA_C112_DATABASE_SCHEMA')!='dalaai_demo':
            raise ValueError('isolated observer configuration required')
        os.environ['DALA_C112_OBSERVER_DATABASE_URL']=f'postgresql://naryadai_api:{dsn.password}@127.0.0.1:5432/naryadai'
        os.execv(sys.executable,[sys.executable,'/ci/c112_observe.py',*actors])
    except Exception:
        print(json.dumps({'status':'BLOCKED','code':'C112_DB_OBSERVATION_UNAVAILABLE','error_type':'ObserverRunnerError'}))
        return 2


if __name__=='__main__':
    raise SystemExit(main())
