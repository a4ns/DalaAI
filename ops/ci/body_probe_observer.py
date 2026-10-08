#!/usr/bin/env python3
"""Fixed private adapter. Its context is rendered by the reviewed parent runner."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import UUID

CONTEXT = None


def render(root,private,project,clock,source,interpreter):
    if not all(p.is_absolute() and p==p.resolve() for p in (root,private,interpreter)):
        raise ValueError('canonical absolute context required')
    if not re.fullmatch('dalaai-controls-ci-[a-f0-9]{16}',project) or not re.fullmatch('[a-f0-9]{40}',source) or str(UUID(clock))!=clock:
        raise ValueError('fixed context required')
    context={'root':str(root),'private':str(private),'project':project,'clock':clock,'source':source}
    template=Path(__file__).read_text()
    return template.replace('#!/usr/bin/env python3','#!'+str(interpreter),1).replace('CONTEXT = None','CONTEXT = '+repr(context),1)


def context_command(context,wrapper,argv):
    if not isinstance(context,dict) or set(context)!={'root','private','project','clock','source'} or len(argv)!=3:
        raise ValueError('fixed context required')
    root=Path(context['root']);private=Path(context['private'])
    if (not root.is_absolute() or root!=root.resolve() or not private.is_absolute() or private!=private.resolve()
            or private.is_symlink() or wrapper.resolve().parent!=private or wrapper.is_symlink()
            or not re.fullmatch('dalaai-controls-ci-[a-f0-9]{16}',context['project'])
            or not re.fullmatch('[a-f0-9]{40}',context['source']) or str(UUID(context['clock']))!=context['clock']):
        raise ValueError('owned context required')
    for name,value in (('.fixture-owner','dalaai-mobile-ci-private-v1'),('.controls-owner','dalaai-controls-ci-v1'),('.body-probe-owner','dalaai-body-probe-private-v1')):
        file=private/name
        if file.is_symlink() or not file.is_file() or file.stat().st_size>100 or file.read_text()!=value:
            raise ValueError('owned marker required')
    fixture=private/'fixture.json'
    if fixture.is_symlink() or not fixture.is_file() or fixture.stat().st_size>16384:
        raise ValueError('bounded public fixture required')
    sys.path.insert(0,str(root/'ops/ci'))
    from controls_observer_python import command_for
    command=command_for(root,private,context['project'],argv[0],argv[1:],json.loads(fixture.read_text()))
    # No child-provided project, Docker override, loader, PIN or database input is forwarded.
    env={'PATH':'/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C.UTF-8',
         'HOME':str(private/'browser-home'),'PYTHONDONTWRITEBYTECODE':'1','DOCKER_HOST':'unix:///var/run/docker.sock',
         'DALA_CI_ROOT_DIR':str(root),'DALA_CI_SOURCE_DIR':str(root/'ops/ci'),
         'DALA_CI_PRIVATE_DIR':str(private),'DALA_CI_COMPOSE_PROJECT':context['project'],
         'DALA_DEMO_CLOCK_INSTANCE_ID':context['clock']}
    return root,command,env


def main():
    try:
        if os.environ.get('DALA_C113_AUTHORIZED')!='operator-provisioned-synthetic-only' or os.environ.get('DALA_C113_DATABASE_SCHEMA')!='dalaai_demo':
            raise ValueError('fixed observer authority required')
        root,command,env=context_command(CONTEXT,Path(__file__),sys.argv[1:])
        head=subprocess.run(['git','rev-parse','HEAD'],cwd=root,env=env,capture_output=True,timeout=3,check=False)
        if head.returncode or head.stdout.decode().strip()!=CONTEXT['source']: raise ValueError('same source required')
        clean=subprocess.run(['git','diff','--exit-code','HEAD','--','ops/ci','tests/e2e/c113_observe.py'],cwd=root,env=env,capture_output=True,timeout=3,check=False)
        if clean.returncode: raise ValueError('clean source required')
        result=subprocess.run(command,cwd=root,env=env,capture_output=True,timeout=20,check=False)
        if result.returncode or len(result.stdout)>1024*1024: raise ValueError('bounded observation required')
        if json.loads(result.stdout).get('source')!='actual_postgresql_read_only': raise ValueError('actual observation required')
        sys.stdout.buffer.write(result.stdout)  # private pipe to the immutable probe only
        return 0
    except Exception:
        print('{"status":"BLOCKED","code":"BODY_PROBE_OBSERVER_UNAVAILABLE"}')
        return 2


if __name__=='__main__':raise SystemExit(main())
