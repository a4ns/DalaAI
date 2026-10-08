"""Bounded test probe inside the actual managed image; never logs raw data."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time


STAGES = {'authorization', 'process_inventory', 'process_api_status', 'process_api_environment',
          'process_worker_status', 'process_worker_environment', 'process_edge_status',
          'process_edge_environment', 'api_loopback', 'privilege_drop', 'imports',
          'database_snapshot', 'photo_store', 'photo_read', 'budget_create', 'budget_reserve', 'budget_verify'}
ERROR_TYPES = {'PermissionError', 'ValueError', 'KeyError', 'TypeError', 'OSError', 'FileNotFoundError',
               'PhotoUnavailable', 'OperationalError', 'InsufficientPrivilege', 'UndefinedTable',
               'UndefinedColumn', 'AssertionError', 'ImportError', 'ModuleNotFoundError', 'OTHER'}
STAGE = 'authorization'


def phase(name):
    global STAGE
    if name not in STAGES:
        raise ValueError('INVALID_PROBE_PHASE')
    STAGE = name


def failure_report(error):
    kind = type(error).__name__
    return {'status': 'FAIL', 'code': 'MANAGED_OBSERVER_FAILED', 'stage': STAGE,
            'error_type': kind if kind in ERROR_TYPES else 'OTHER'}


def require(condition):
    if not condition:
        raise ValueError('MANAGED_OBSERVER_ASSERTION_FAILED')


def processes():
    phase('process_inventory')
    expected = {'api': (b'app.main:app', 10001), 'worker': (b'app.worker_runtime', 10001),
                'edge': (b'/usr/bin/caddy\x00run', 10002)}
    found = {}
    for proc in Path('/proc').iterdir():
        if not proc.name.isdecimal():
            continue
        try:
            cmd = (proc / 'cmdline').read_bytes()
            for name, (needle, uid) in expected.items():
                if needle not in cmd:
                    continue
                require(name not in found)
                phase('process_' + name + '_status')
                status = (proc / 'status').read_text()
                uids = next(row for row in status.splitlines() if row.startswith('Uid:')).split()[1:]
                require(all(int(value) == uid for value in uids))
                phase('process_' + name + '_environment')
                os.setegid(uid)
                os.seteuid(uid)
                try:
                    raw_env = (proc / 'environ').read_bytes()
                finally:
                    os.seteuid(0)
                    os.setegid(0)
                env = dict(part.split(b'=', 1) for part in raw_env.split(b'\0') if b'=' in part)
                require(not env.get(b'OPENAI_API_KEY') and not env.get(b'OPENAI_API_KEY_FILE'))
                require(not any(b'OWNER' in key or b'PIN' in key for key in env))
                if name == 'api':
                    require(bool(env.get(b'DATABASE_URL')) and b'DALA_WORKER_DATABASE_URL' not in env)
                elif name == 'worker':
                    require(bool(env.get(b'DALA_WORKER_DATABASE_URL')) and b'DATABASE_URL' not in env)
                else:
                    require(not any(key in env for key in (b'DATABASE_URL', b'DALA_WORKER_DATABASE_URL', b'DALA_VAPID_PRIVATE_KEY')))
                found[name] = uid
        except (FileNotFoundError, ProcessLookupError):
            continue
    phase('process_inventory')
    require(set(found) == set(expected))
    phase('api_loopback')
    listeners = [row.split()[1] for row in Path('/proc/net/tcp').read_text().splitlines()[1:] if row.split()[3] == '0A']
    require('0100007F:1F40' in listeners and '00000000:1F40' not in listeners)
    return {'api_uid': found['api'], 'worker_uid': found['worker'], 'edge_uid': found['edge'],
            'api_loopback_only': True, 'child_secret_scopes': 'PASS'}


def snapshot(initialize=False):
    phase('authorization')
    require(os.environ.get('DALA_MANAGED_CI_AUTHORIZED') == 'disposable-image-only')
    require(os.geteuid() == 0)
    report = {'processes': processes()}
    phase('privilege_drop')
    os.setgroups([]); os.setgid(10001); os.setuid(10001)
    os.umask(0o077)
    phase('imports')
    sys.path.insert(0, '/service')
    from app.runtime import RuntimeSettings, connection_factory
    from app.photos.storage import PrivateFileStore
    from app.ai.model_budget import SqliteBudgetLedger, BudgetPolicy
    phase('database_snapshot')
    connector = connection_factory(RuntimeSettings.from_env())
    with connector() as db:
        counts = {}
        for table in ('orders', 'photos', 'submissions', 'ai_assessments', 'operation_receipts'):
            counts[table] = db.execute('SELECT count(*) AS n FROM ' + table).fetchone()['n']
        rows = db.execute('SELECT id,storage_key,sha256 FROM photos WHERE file_valid=true ORDER BY storage_key').fetchall()
        identity = hashlib.sha256()
        for table, column in (('orders','id'),('submissions','id'),('ai_assessments','id'),('operation_receipts','operation_id')):
            for row in db.execute('SELECT ' + column + ' AS identity FROM ' + table + ' ORDER BY ' + column).fetchall():
                identity.update((table + ':' + str(row['identity']) + '\n').encode())
    phase('photo_store')
    store = PrivateFileStore('/var/lib/naryadai/photos')
    digest = hashlib.sha256()
    require(len(rows) >= 1)
    for row in rows:
        phase('photo_read')
        data = store.get(row['storage_key'])
        sha = hashlib.sha256(data).hexdigest()
        require(sha == row['sha256'])
        digest.update((str(row['id']) + ':' + row['storage_key'] + ':' + sha + '\n').encode())
    phase('budget_create')
    ledger = SqliteBudgetLedger('/var/lib/naryadai/budget/openai.sqlite3',
                               BudgetPolicy('managed-ci-offline-reservation', 1000, 100, period_id='ci-only'))
    if initialize:
        phase('budget_reserve')
        require(ledger.counters()['calls_reserved'] == 0)
        # An offline cancelled reservation tests storage. No transport is created.
        token = ledger.reserve(now=time.time())
        ledger.finish(token, 'cancelled')
    phase('budget_verify')
    counters = ledger.counters()
    require(counters['calls_reserved'] == 1 and counters['outcomes'] == {'cancelled': 1})
    require(counters['actual_billed_cost'] is None)
    report.update(counts=counts, record_digest=identity.hexdigest(), physical_photo_count=len(rows), photo_digest=digest.hexdigest(),
                  budget={'calls_reserved': 1, 'outcome': 'cancelled', 'actual_billed_cost': None,
                          'reserved_upper_bound_microusd': counters['reserved_upper_bound_microusd']})
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--initialize-budget', action='store_true')
    args = parser.parse_args()
    try:
        result = snapshot(args.initialize_budget)
        print(json.dumps(result, sort_keys=True))
    except Exception as error:
        print(json.dumps(failure_report(error), sort_keys=True))
        raise SystemExit(1) from None
