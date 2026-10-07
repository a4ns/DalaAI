#!/usr/bin/env python3
"""Fixed interpreter adapter for C110; validates input and never passes credentials in argv."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import UUID


def command_for(root: Path, project: str, script: str, order: str) -> list[str]:
    if not root.is_absolute() or Path(script).resolve()!=(root/'tests/e2e/c110_observe.py').resolve():
        raise ValueError('only the accepted C observer is supported')
    if not re.fullmatch(r'dalaai-ci-[a-f0-9]{16}',project):
        raise ValueError('only this disposable project is supported')
    order_id=str(UUID(order))
    return ['docker','compose','--project-name',project,'--project-directory',str(root/'ops/demo'),
            '-f',str(root/'ops/demo/compose.yaml'),'-f',str(root/'ops/ci/compose.override.yaml'),
            'exec','-T','observer','python','/ci/observer_in_container.py',order_id]


def main():
    try:
        if len(sys.argv)!=3:
            raise ValueError('exact observer script and UUID required')
        root=Path(os.environ['DALA_CI_ROOT_DIR']).resolve()
        if os.environ.get('DALA_CI_SOURCE_DIR')!=str(root/'ops/ci') or os.environ.get('DOCKER_HOST')!='unix:///var/run/docker.sock':
            raise ValueError('explicit local CI context required')
        if os.environ.get('DOCKER_CONTEXT','default')!='default':
            raise ValueError('remote Docker context forbidden')
        private=Path(os.environ['DALA_CI_PRIVATE_DIR'])
        if (private/'.fixture-owner').read_text()!='dalaai-mobile-ci-private-v1':
            raise ValueError('owned disposable fixture required')
        command=command_for(root,os.environ['DALA_CI_COMPOSE_PROJECT'],sys.argv[1],sys.argv[2])
        process=subprocess.run(command,cwd=root,env=os.environ,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=12,check=False)
        if len(process.stdout)>512*1024:
            raise ValueError('observer output too large')
        data=json.loads(process.stdout)
        # Forward only the unchanged observer's structured response to its C caller.
        # This pipe is never a public log or artifact; the C gate selects evidence.
        if process.returncode==0 and data.get('source')=='actual_postgresql_read_only':
            sys.stdout.buffer.write(process.stdout)
            return 0
        allowed={'OperationalError','ProgrammingError','InsufficientPrivilege','UndefinedColumn','UndefinedTable',
                 'InvalidPassword','InvalidAuthorizationSpecification','ConnectionTimeout','Blocked','ValueError',
                 'ImportError','ModuleNotFoundError','SyntaxError','TypeError','KeyError','InterfaceError','ObserverRunnerError'}
        kind=data.get('error_type')
        print(json.dumps({'status':'BLOCKED','code':'C110_DB_OBSERVATION_UNAVAILABLE',
                          'error_type':kind if kind in allowed else 'ObserverRunnerError'}))
        return 2
    except Exception:
        print(json.dumps({'status':'BLOCKED','code':'C110_DB_OBSERVATION_UNAVAILABLE','error_type':'ObserverRunnerError'}))
        return 2


if __name__=='__main__':
    raise SystemExit(main())
