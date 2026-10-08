#!/usr/bin/env python3
"""C113-only fixed adapter. Public actor IDs are bound to the fixture manifest."""
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import UUID


def command_for(root, private, project, script, actors, manifest):
    # Also used after copying this launcher into the owned private directory.
    sys.path.insert(0, str(root/'ops/ci'))
    from controls_profile import compose_command, public_actor_ids
    if Path(script).is_symlink() or Path(script).resolve() != (root/'tests/e2e/c113_observe.py').resolve():
        raise ValueError('accepted observer required')
    if tuple(str(UUID(value)) for value in actors) != public_actor_ids(manifest):
        raise ValueError('manifest actors required')
    return [*compose_command(root,private,project),'exec','-T','observer','python',
            '/ci/controls_observer_in_container.py',*actors]


def main():
    try:
        if len(sys.argv)!=4:
            raise ValueError('observer and two public actors required')
        root=Path(os.environ['DALA_CI_ROOT_DIR']).resolve()
        private=Path(os.environ['DALA_CI_PRIVATE_DIR'])
        if (os.environ.get('DALA_CI_SOURCE_DIR')!=str(root/'ops/ci')
                or os.environ.get('DOCKER_HOST')!='unix:///var/run/docker.sock'
                or os.environ.get('DOCKER_CONTEXT','default')!='default'
                or not private.is_absolute() or private.is_symlink()
                or (private/'.fixture-owner').read_text()!='dalaai-mobile-ci-private-v1'
                or (private/'.controls-owner').read_text()!='dalaai-controls-ci-v1'):
            raise ValueError('owned local disposable context required')
        fixture=private/'fixture.json'
        if fixture.is_symlink() or not fixture.is_file() or fixture.stat().st_size>16384:
            raise ValueError('bounded fixture required')
        cmd=command_for(root,private,os.environ['DALA_CI_COMPOSE_PROJECT'],sys.argv[1],sys.argv[2:],json.loads(fixture.read_text()))
        run=subprocess.run(cmd,cwd=root,env=os.environ,capture_output=True,timeout=25,check=False)
        if len(run.stdout)>1024*1024:
            raise ValueError('bounded observer output required')
        data=json.loads(run.stdout)
        if run.returncode==0 and data.get('source')=='actual_postgresql_read_only':
            # Private pipe to the frozen C test only; never a public log.
            sys.stdout.buffer.write(run.stdout)
            return 0
    except Exception:
        pass
    print('{"status":"BLOCKED","code":"C113_DB_OBSERVATION_UNAVAILABLE"}')
    return 2


if __name__=='__main__':
    raise SystemExit(main())
