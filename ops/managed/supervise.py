"""One synthetic-demo container, three processes; no provisioning or auto-reset.

Only startup directory metadata is changed. Credentials are operator supplied.
API and worker intentionally share UID10001 and are ONE security principal.
"""
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time
from urllib.parse import urlsplit

ROOT = Path('/var/lib/naryadai')
API_COMMAND = [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1',
               '--port', '8000', '--workers', '1', '--no-access-log', '--no-proxy-headers']
WORKER_COMMAND = [sys.executable, '-m', 'app.worker_runtime']
EDGE_COMMAND = ['/usr/bin/caddy', 'run', '--config', '/service/ops/managed/Caddyfile', '--adapter', 'caddyfile']
BASE = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'PYTHONPATH': '/service',
        'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUNBUFFERED': '1', 'LANG': 'C.UTF-8', 'HOME': '/tmp'}
SHARED = {'DALA_DEMO_CLOCK_ENABLED','DALA_DEMO_CLOCK_INSTANCE_ID','DALA_API_MODE', 'DALA_DATABASE_SCHEMA', 'DALA_PHOTO_STORAGE_ROOT', 'DALA_PHOTO_MAX_TOTAL_BYTES'}
PUSH_PUBLIC = {'DALA_WEB_PUSH_ENABLED', 'DALA_VAPID_PUBLIC_KEY', 'DALA_VAPID_SUBJECT'}
API_KEYS = SHARED | PUSH_PUBLIC | {'DATABASE_URL', 'DALA_ALLOWED_ORIGIN', 'DALA_VAPID_PRIVATE_KEY', 'DALA_NOTIFICATION_CAPABILITY', 'DALA_PUSH_CAPABILITY', 'DALA_DELIVERY_CHANNEL'}
WORKER_KEYS = SHARED | PUSH_PUBLIC | {
    'DALA_WORKER_ENABLED', 'DALA_WORKER_AI_ENABLED', 'DALA_WORKER_NOTIFY_ENABLED',
    'DALA_WORKER_CHANNEL', 'DALA_WORKER_TELEGRAM_ENABLED',
    'DALA_WORKER_DATABASE_URL', 'DALA_WORKER_TICK_SECONDS', 'DALA_WORKER_TICK_ADMISSION_SECONDS',
    'DALA_WORKER_AI_LIMIT', 'DALA_WORKER_RECONCILE_LIMIT', 'DALA_WORKER_DISPATCH_LIMIT',
    'DALA_WORKER_MAX_CONSECUTIVE_ERRORS', 'DALA_VAPID_PRIVATE_KEY',
    'OPENAI_API_KEY', 'OPENAI_API_KEY_FILE', 'DALA_MODEL_APPROVAL_FILE',
    'DALA_MODEL_PROJECT_ID', 'DALA_MODEL_INSTANCE_ID',
    'DALA_MODEL_BUDGET_PATH', 'DALA_MODEL_FORCE_OFF', 'TELEGRAM_MODE'}
FORBIDDEN = {'DALA_DEMO_OWNER_DATABASE_URL', 'DALA_DEMO_MASTER_PIN', 'DALA_DEMO_EXECUTOR_PIN',
             'DALA_DEMO_SEED_ALLOWED', 'DALA_DEMO_RUNTIME_DATABASE_URL',
             'DALA_RUNTIME_DSN_FILE', 'DALA_WORKER_DATABASE_URL_FILE'}


def require(ok, code):
    if not ok:
        raise ValueError(code)


def child_environments(environment):
    """Validate without reads/network; return allowlisted, separate child envs."""
    env = dict(environment)
    require(env.get('DALA_MANAGED_START_APPROVED') == 'true', 'MANAGED_OPERATOR_START_REQUIRED')
    require(not any(env.get(key) for key in FORBIDDEN), 'MANAGED_UNEXPECTED_BOOTSTRAP_SECRET')
    require(env.get('DALA_API_MODE') == 'demo', 'MANAGED_DEMO_ONLY')
    require(env.get('DALA_DATABASE_SCHEMA') == 'dalaai_demo', 'MANAGED_SCHEMA_REQUIRED')
    origin = env.get('DALA_ALLOWED_ORIGIN', '')
    parsed = urlsplit(origin)
    require(parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password,
            'MANAGED_EXACT_HTTPS_ORIGIN_REQUIRED')
    host = parsed.hostname
    require(re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', host) and '.' in host
            and not any(not label or len(label) > 63 for label in host.split('.'))
            and origin == 'https://' + host, 'MANAGED_EXACT_HTTPS_ORIGIN_REQUIRED')
    require(re.fullmatch(r'[0-9]{4,5}', env.get('PORT', '')) is not None
            and 1024 <= int(env['PORT']) <= 65535 and env['PORT'] != '8000', 'MANAGED_PORT_INVALID')
    require(env.get('DALA_WORKER_ENABLED') == 'true', 'MANAGED_SEPARATE_WORKER_REQUIRED')
    require(env.get('DALA_WORKER_TELEGRAM_ENABLED', 'false') == 'false'
            and env.get('TELEGRAM_MODE', 'disabled') == 'disabled', 'MANAGED_TELEGRAM_NOT_IN_PROFILE')
    require(env.get('DALA_PHOTO_STORAGE_ROOT') == str(ROOT / 'photos')
            and env.get('DALA_MODEL_BUDGET_PATH') == str(ROOT / 'budget/openai.sqlite3'), 'MANAGED_FIXED_STORAGE_REQUIRED')
    # Validating role identity here is not a substitute for database grant checks.
    api, worker = (urlsplit(env.get(key, '')) for key in ('DATABASE_URL', 'DALA_WORKER_DATABASE_URL'))
    require(all(d.scheme in ('postgres', 'postgresql') and d.hostname and d.username and d.password
                and d.path == '/naryadai' for d in (api, worker)), 'MANAGED_PRIVATE_DSN_REQUIRED')
    require(api.username != worker.username and api.hostname == worker.hostname
            and api.port == worker.port, 'MANAGED_DISTINCT_ROLES_SAME_DATABASE_REQUIRED')
    require(not (env.get('OPENAI_API_KEY') and env.get('OPENAI_API_KEY_FILE')),
            'MANAGED_DUPLICATE_MODEL_KEY_SOURCE')
    require(not any(env.get(key) for key in ('DALA_WORKER_OPENAI_ENABLED', 'DALA_MODEL_IMAGE_SELECTIONS_FILE')),
            'MANAGED_LEGACY_MODEL_CONFIG_UNSUPPORTED')
    for key in ('DALA_MODEL_APPROVAL_FILE', 'OPENAI_API_KEY_FILE'):
        if env.get(key):
            p = Path(env[key])
            require(p.parent == Path('/etc/secrets') and p.name not in ('', '.', '..'), 'MANAGED_SECRET_FILE_PATH_REQUIRED')
    api_env = BASE | {k: v for k, v in env.items() if k in API_KEYS}
    worker_env = BASE | {k: v for k, v in env.items() if k in WORKER_KEYS}
    edge_env = BASE | {'PORT': env['PORT'], 'DALA_PUBLIC_HOST': host,
                      'XDG_DATA_HOME': '/tmp/caddy-data', 'XDG_CONFIG_HOME': '/tmp/caddy-config'}
    return api_env, worker_env, edge_env


def prepare_storage(root=ROOT, uid=10001):
    """No recursive chown, symlink traversal, migration, seed or deletion."""
    require(os.geteuid() == 0, 'MANAGED_ROOT_INITIALIZER_REQUIRED')
    require(root == ROOT and os.path.ismount(root), 'MANAGED_DURABLE_MOUNT_REQUIRED')
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        require(os.fstat(fd).st_uid == 0, 'MANAGED_MOUNT_OWNER_INVALID')
        os.fchmod(fd, 0o755)  # children cannot replace fixed root subdirectories
        for name in ('photos', 'budget'):
            try:
                os.mkdir(name, mode=0o700, dir_fd=fd)
            except FileExistsError:
                pass
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            try:
                require(stat.S_ISDIR(os.fstat(child).st_mode), 'MANAGED_STORAGE_DIRECTORY_REQUIRED')
                os.fchown(child, uid, uid)
                os.fchmod(child, 0o700)
            finally:
                os.close(child)
    finally:
        os.close(fd)


def launch(command, environment, uid):
    return subprocess.Popen(command, env=environment, cwd='/service', user=uid, group=uid,
                            extra_groups=[], start_new_session=True, umask=0o077)


def stop_children(children, grace=75.0):
    for _, child in children:
        if child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    until = time.monotonic() + grace
    for _, child in children:
        if child.poll() is None:
            try:
                child.wait(timeout=max(0.01, until - time.monotonic()))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()


def main():
    children = []
    stopping = False
    def request_stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    try:
        api_env, worker_env, edge_env = child_environments(os.environ)
        prepare_storage()
        # Validate actual worker role/migrations before serving; never claims jobs.
        checked = subprocess.run(WORKER_COMMAND + ['--check'], env=worker_env, cwd='/service',
            user=10001, group=10001, extra_groups=[], umask=0o077, timeout=90, check=False)
        require(checked.returncode == 0, 'MANAGED_WORKER_PREFLIGHT_FAILED')
        if stopping:
            return 0
        for name, command, env, uid in [('api', API_COMMAND, api_env, 10001),
                ('worker', WORKER_COMMAND, worker_env, 10001), ('edge', EDGE_COMMAND, edge_env, 10002)]:
            children.append((name, launch(command, env, uid)))
        # Keep supervisor root so it can signal the distinct edge UID. It accepts
        # no network/input, uses fixed argv, and never executes runtime app code.
        os.environ.clear()
        while not stopping:
            for name, child in children:
                if child.poll() is not None:
                    print(json.dumps({'state': 'managed_child_exited', 'component': name}), flush=True)
                    return 1
            time.sleep(0.25)
        return 0
    except Exception:
        # No exception text, argv, env, connection URL, PIN or provider output.
        print('{"state":"managed_startup_failed","code":"CHECK_OPERATOR_CONFIGURATION"}', flush=True)
        return 1
    finally:
        stop_children(children)


if __name__ == '__main__':
    raise SystemExit(main())
