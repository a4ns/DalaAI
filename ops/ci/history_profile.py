"""C112's distinct history Compose seam; shared C110 and demo source stay unchanged."""
from pathlib import Path
import re

HISTORY_SERVICES = {'db','prepare','photo-directory','api','web','observer'}
INACTIVE_SERVICES = {'worker','budget-directory'}
HISTORY_VERSION = 'dalaai-canonical-history-live-demo-v1'
HISTORY_DIGEST = '7d888cdd5bb6a9c01ca7c543fae9e393335d07210dab811aa754f12331d1d2e1'


class HistoryBlocked(RuntimeError):
    pass


def compose_command(root: Path, private: Path, project: str) -> list[str]:
    if not root.is_absolute() or not private.is_absolute() or not re.fullmatch(r'dalaai-history-ci-[a-f0-9]{16}',project):
        raise HistoryBlocked('C112_EXPLICIT_ISOLATED_PATHS_AND_PROJECT_REQUIRED')
    return ['docker','compose','--project-name',project,'--project-directory',str(root/'ops/demo'),
            '--env-file',str(private/'env'),'--env-file',str(private/'workers.env'),
            '-f',str(root/'ops/demo/compose.yaml'),'-f',str(root/'ops/demo/compose.workers.yaml'),
            '-f',str(root/'ops/ci/history_compose.yaml')]


def public_actor_ids(manifest: dict) -> tuple[str,str]:
    from uuid import UUID
    if (manifest.get('fixture_version')!=HISTORY_VERSION or manifest.get('fixture_mode')!='history'
            or manifest.get('history_sha256')!=HISTORY_DIGEST or manifest.get('synthetic') is not True
            or manifest.get('history_orders')!=540 or manifest.get('historical_actor_count')!=17
            or manifest.get('historical_actor_state')!='disabled_no_login'):
        raise HistoryBlocked('C112_REVIEWED_HISTORY_MANIFEST_REQUIRED')
    if len(manifest.get('users',[]))!=2:
        raise HistoryBlocked('C112_EXACTLY_TWO_PUBLIC_ACTORS_REQUIRED')
    actors=[]
    for role,code in [('master','DALA-DEMO-MASTER'),('executor','DALA-DEMO-EXECUTOR')]:
        users=[u for u in manifest.get('users',[]) if u.get('role')==role and u.get('employee_code')==code]
        if len(users)!=1:
            raise HistoryBlocked('C112_PUBLIC_FIXTURE_ACTORS_REQUIRED')
        actors.append(str(UUID(users[0]['id'])))
    if actors[0]==actors[1]:
        raise HistoryBlocked('C112_DISTINCT_FIXTURE_ACTORS_REQUIRED')
    return tuple(actors)


def validate_profile(model: dict, root: Path) -> list[str]:
    services=model.get('services',{})
    if set(services)!=HISTORY_SERVICES|INACTIVE_SERVICES:
        raise HistoryBlocked('C112_UNREVIEWED_SERVICE_SET')
    for name in INACTIVE_SERVICES:
        if services[name].get('profiles')!=['c112-inactive']:
            raise HistoryBlocked('C112_WORKER_SERVICES_MUST_BE_INACTIVE')
    for name in HISTORY_SERVICES:
        if set(services[name].get('depends_on',{})) & INACTIVE_SERVICES:
            raise HistoryBlocked('C112_ACTIVE_SERVICE_DEPENDS_ON_WORKER')
    if model.get('networks',{}).get('backend',{}).get('internal') is not True or services['db'].get('ports') or set(services['db'].get('networks',{}))!={'backend'}:
        raise HistoryBlocked('C112_DATABASE_MUST_REMAIN_INTERNAL_UNPUBLISHED')
    setup=services['prepare'].get('environment',{})
    if setup.get('DALA_DEMO_FIXTURE_MODE')!='history' or setup.get('DALA_DEMO_WORKER_CAPABILITY_ALLOWED')!='1':
        raise HistoryBlocked('C112_REVIEWED_FULL_HISTORY_BOOTSTRAP_REQUIRED')
    for name in ('api','worker'):
        env=services[name].get('environment',{})
        if str(env.get('DALA_WEB_PUSH_ENABLED','')).lower()!='false' or env.get('OPENAI_API_KEY') or env.get('DALA_VAPID_PRIVATE_KEY'):
            raise HistoryBlocked('C112_EXTERNAL_PROVIDER_INPUTS_FORBIDDEN')
    for name in ('prepare','api','worker'):
        if str(services[name].get('environment',{}).get('DALA_DEMO_CLOCK_ENABLED','')).lower()!='false':
            raise HistoryBlocked('C112_CLOCK_MUST_REMAIN_DISABLED')
    if any(str(services['worker'].get('environment',{}).get(key,'')).lower()!='false'
           for key in ('DALA_WORKER_ENABLED','DALA_WORKER_AI_ENABLED','DALA_WORKER_NOTIFY_ENABLED')):
        raise HistoryBlocked('C112_WORKER_FLAGS_MUST_BE_DISABLED')
    if str(services['worker'].get('environment',{}).get('DALA_MODEL_FORCE_OFF','')).lower()!='true':
        raise HistoryBlocked('C112_MODEL_MUST_BE_OFF')
    observer=services['observer']
    if (observer.get('network_mode')!='service:db' or observer.get('user')!='10001:10001'
            or observer.get('read_only') is not True or observer.get('ports') or observer.get('networks')
            or observer.get('cap_drop')!=['ALL'] or observer.get('cap_add') or observer.get('privileged')
            or observer.get('security_opt')!=['no-new-privileges:true']):
        raise HistoryBlocked('C112_OBSERVER_BOUNDARY_INVALID')
    assigned={item.get('source') if isinstance(item,dict) else item for item in observer.get('secrets',[])}
    if assigned!={'runtime_dsn'}:
        raise HistoryBlocked('C112_OBSERVER_INPUT_SCOPE_INVALID')
    expected={'/ci/c112_observe.py':root/'tests/e2e/c112_observe.py',
              '/ci/history_observer_in_container.py':root/'ops/ci/history_observer_in_container.py'}
    volumes=observer.get('volumes',[])
    if len(volumes)!=2 or {v.get('target') for v in volumes}!=set(expected):
        raise HistoryBlocked('C112_EXACT_OBSERVER_MOUNTS_REQUIRED')
    if any(v.get('type')!='bind' or v.get('read_only') is not True or Path(v.get('source','')).resolve()!=expected[v['target']].resolve() for v in volumes):
        raise HistoryBlocked('C112_FROZEN_OBSERVER_SOURCE_REQUIRED')
    build=observer.get('build',{})
    if build.get('dockerfile')!='ops/demo/Dockerfile.api' or Path(build.get('context','')).resolve()!=root:
        raise HistoryBlocked('C112_EXISTING_API_IMAGE_REQUIRED')
    return sorted(HISTORY_SERVICES)


def validate_actual_services(rows: list[dict]) -> list[str]:
    if {row.get('Service') for row in rows}!=HISTORY_SERVICES:
        raise HistoryBlocked('C112_UNEXPECTED_RUNNING_SERVICE_SET')
    for row in rows:
        if row['Service'] in {'db','api','web','observer'} and row.get('State')!='running':
            raise HistoryBlocked('C112_REQUIRED_SERVICE_NOT_RUNNING')
    return sorted(HISTORY_SERVICES)
