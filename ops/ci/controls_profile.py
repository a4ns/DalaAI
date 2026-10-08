"""C113's distinct history Compose seam; shared C110 and demo source stay unchanged."""
from pathlib import Path
import re

HISTORY_SERVICES = {'db','prepare','photo-directory','api','web','observer'}
INACTIVE_SERVICES = {'worker','budget-directory'}
HISTORY_VERSION = 'dalaai-canonical-history-live-demo-v1'
HISTORY_DIGEST = '7d888cdd5bb6a9c01ca7c543fae9e393335d07210dab811aa754f12331d1d2e1'


class ControlsBlocked(RuntimeError):
    pass


def compose_command(root: Path, private: Path, project: str) -> list[str]:
    if not root.is_absolute() or not private.is_absolute() or not re.fullmatch(r'dalaai-controls-ci-[a-f0-9]{16}',project):
        raise ControlsBlocked('C113_EXPLICIT_ISOLATED_PATHS_AND_PROJECT_REQUIRED')
    return ['docker','compose','--project-name',project,'--project-directory',str(root/'ops/demo'),
            '--env-file',str(private/'env'),'--env-file',str(private/'workers.env'),
            '-f',str(root/'ops/demo/compose.yaml'),'-f',str(root/'ops/demo/compose.workers.yaml'),
            '-f',str(root/'ops/ci/controls_compose.yaml')]


def public_actor_ids(manifest: dict) -> tuple[str,str]:
    from uuid import UUID
    if (manifest.get('fixture_version')!=HISTORY_VERSION or manifest.get('fixture_mode')!='history'
            or manifest.get('history_sha256')!=HISTORY_DIGEST or manifest.get('synthetic') is not True
            or manifest.get('history_orders')!=540 or manifest.get('historical_actor_count')!=17
            or manifest.get('historical_actor_state')!='disabled_no_login'):
        raise ControlsBlocked('C113_REVIEWED_HISTORY_MANIFEST_REQUIRED')
    if len(manifest.get('users',[]))!=2:
        raise ControlsBlocked('C113_EXACTLY_TWO_PUBLIC_ACTORS_REQUIRED')
    actors=[]
    for role,code in [('master','DALA-DEMO-MASTER'),('executor','DALA-DEMO-EXECUTOR')]:
        users=[u for u in manifest.get('users',[]) if u.get('role')==role and u.get('employee_code')==code]
        if len(users)!=1:
            raise ControlsBlocked('C113_PUBLIC_FIXTURE_ACTORS_REQUIRED')
        actors.append(str(UUID(users[0]['id'])))
    if actors[0]==actors[1]:
        raise ControlsBlocked('C113_DISTINCT_FIXTURE_ACTORS_REQUIRED')
    return tuple(actors)


def validate_profile(model: dict, root: Path) -> list[str]:
    services=model.get('services',{})
    if set(services)!=HISTORY_SERVICES|INACTIVE_SERVICES:
        raise ControlsBlocked('C113_UNREVIEWED_SERVICE_SET')
    for name in INACTIVE_SERVICES:
        if services[name].get('profiles')!=['c113-inactive']:
            raise ControlsBlocked('C113_WORKER_SERVICES_MUST_BE_INACTIVE')
    for name in HISTORY_SERVICES:
        if set(services[name].get('depends_on',{})) & INACTIVE_SERVICES:
            raise ControlsBlocked('C113_ACTIVE_SERVICE_DEPENDS_ON_WORKER')
    if model.get('networks',{}).get('backend',{}).get('internal') is not True or services['db'].get('ports') or set(services['db'].get('networks',{}))!={'backend'}:
        raise ControlsBlocked('C113_DATABASE_MUST_REMAIN_INTERNAL_UNPUBLISHED')
    setup=services['prepare'].get('environment',{})
    if setup.get('DALA_DEMO_FIXTURE_MODE')!='history' or setup.get('DALA_DEMO_WORKER_CAPABILITY_ALLOWED')!='1':
        raise ControlsBlocked('C113_REVIEWED_FULL_HISTORY_BOOTSTRAP_REQUIRED')
    for name in ('api','worker'):
        env=services[name].get('environment',{})
        if str(env.get('DALA_WEB_PUSH_ENABLED','')).lower()!='false' or env.get('OPENAI_API_KEY') or env.get('DALA_VAPID_PRIVATE_KEY'):
            raise ControlsBlocked('C113_EXTERNAL_PROVIDER_INPUTS_FORBIDDEN')
    for name in ('prepare','api','worker'):
        if str(services[name].get('environment',{}).get('DALA_DEMO_CLOCK_ENABLED','')).lower()!='true':
            raise ControlsBlocked('C113_CLOCK_MUST_BE_ENABLED')
    from uuid import UUID
    instances=[services[name].get('environment',{}).get('DALA_DEMO_CLOCK_INSTANCE_ID','') for name in ('prepare','api','worker')]
    if len(set(instances))!=1 or not instances[0]:
        raise ControlsBlocked('C113_SAME_EXPLICIT_CLOCK_INSTANCE_REQUIRED')
    try:
        if str(UUID(instances[0]))!=instances[0]: raise ValueError()
    except ValueError:
        raise ControlsBlocked('C113_VALID_CLOCK_INSTANCE_REQUIRED') from None
    if any(str(services['worker'].get('environment',{}).get(key,'')).lower()!='false'
           for key in ('DALA_WORKER_ENABLED','DALA_WORKER_AI_ENABLED','DALA_WORKER_NOTIFY_ENABLED')):
        raise ControlsBlocked('C113_WORKER_FLAGS_MUST_BE_DISABLED')
    if str(services['worker'].get('environment',{}).get('DALA_MODEL_FORCE_OFF','')).lower()!='true':
        raise ControlsBlocked('C113_MODEL_MUST_BE_OFF')
    observer=services['observer']
    if (observer.get('network_mode')!='service:db' or observer.get('user')!='10001:10001'
            or observer.get('read_only') is not True or observer.get('ports') or observer.get('networks')
            or observer.get('cap_drop')!=['ALL'] or observer.get('cap_add') or observer.get('privileged')
            or observer.get('security_opt')!=['no-new-privileges:true']):
        raise ControlsBlocked('C113_OBSERVER_BOUNDARY_INVALID')
    assigned={item.get('source') if isinstance(item,dict) else item for item in observer.get('secrets',[])}
    if assigned!={'runtime_dsn'}:
        raise ControlsBlocked('C113_OBSERVER_INPUT_SCOPE_INVALID')
    expected={'/ci/c113_observe.py':root/'tests/e2e/c113_observe.py',
              '/ci/controls_observer_in_container.py':root/'ops/ci/controls_observer_in_container.py'}
    volumes=observer.get('volumes',[])
    if len(volumes)!=2 or {v.get('target') for v in volumes}!=set(expected):
        raise ControlsBlocked('C113_EXACT_OBSERVER_MOUNTS_REQUIRED')
    if any(v.get('type')!='bind' or v.get('read_only') is not True or Path(v.get('source','')).resolve()!=expected[v['target']].resolve() for v in volumes):
        raise ControlsBlocked('C113_FROZEN_OBSERVER_SOURCE_REQUIRED')
    build=observer.get('build',{})
    if build.get('dockerfile')!='ops/demo/Dockerfile.api' or Path(build.get('context','')).resolve()!=root:
        raise ControlsBlocked('C113_EXISTING_API_IMAGE_REQUIRED')
    return sorted(HISTORY_SERVICES)


def validate_actual_services(rows: list[dict]) -> list[str]:
    if {row.get('Service') for row in rows}!=HISTORY_SERVICES:
        raise ControlsBlocked('C113_UNEXPECTED_RUNNING_SERVICE_SET')
    for row in rows:
        if row['Service'] in {'db','api','web','observer'} and row.get('State')!='running':
            raise ControlsBlocked('C113_REQUIRED_SERVICE_NOT_RUNNING')
    return sorted(HISTORY_SERVICES)
