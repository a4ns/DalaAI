"""Render a separate restricted worker-role SQL proposal. NEVER execute it.

The operator supplies an EXISTING dedicated nonowner LOGIN in the same isolated
schema/database. No passwords, keys, CREATE ROLE, ALTER ROLE, or network access.
An elevated/inherited preexisting role will fail worker startup even after GRANT.
"""
import argparse
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app.worker_runtime import worker_grants


def identifier(value):
    if type(value) is not str or re.fullmatch(r'[a-z_][a-z0-9_]{0,62}', value) is None:
        raise ValueError('WORKER_PROFILE_IDENTIFIER_INVALID')
    return '"' + value + '"'


def render_worker_profile(*, schema, worker_role, api_role, ai_enabled=True,
                          notify_enabled=True, web_push=True):
    namespace, role, api = map(identifier, (schema, worker_role, api_role))
    if role == api:
        raise ValueError('WORKER_ROLE_MUST_DIFFER_FROM_API_ROLE')
    grants = worker_grants(ai_enabled=ai_enabled, notify_enabled=notify_enabled, web_push=web_push)
    lines = [
        '-- REVIEW-ONLY worker role profile. This program has not applied any SQL.',
        '-- Apply only to an operator-provided existing dedicated LOGIN after approval.',
        '-- Separate owner and API LOGIN required. No memberships, elevated attributes,',
        '-- ownership, schema CREATE, or inherited/PUBLIC data privileges are allowed.',
        '-- This script never revokes unrelated permissions. Startup fails closed on extras.',
        '-- No secrets/keys, human decisions, PIN hashes, CSRF, DELETE, DDL or sequence grants.',
        'BEGIN;', f'GRANT USAGE ON SCHEMA {namespace} TO {role};']
    for table, columns in sorted(grants['select'].items()):
        clause = 'SELECT' if columns == '*' else 'SELECT (' + ', '.join(map(identifier, columns)) + ')'
        lines.append(f'GRANT {clause} ON {namespace}.{identifier(table)} TO {role};')
    for table in grants['insert']:
        lines.append(f'GRANT INSERT ON {namespace}.{identifier(table)} TO {role};')
    for table, columns in sorted(grants['update'].items()):
        clause = ', '.join(map(identifier, columns))
        lines.append(f'GRANT UPDATE ({clause}) ON {namespace}.{identifier(table)} TO {role};')
    lines.extend(['COMMIT;', '-- Validate as the direct worker LOGIN before starting any job lane:',
                  '-- PYTHONPATH=backend python -m app.worker_runtime --check'])
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Print reviewed SQL only; does not connect or create credentials')
    parser.add_argument('--schema', required=True)
    parser.add_argument('--worker-role', required=True)
    parser.add_argument('--api-role', required=True)
    parser.add_argument('--no-ai', action='store_true')
    parser.add_argument('--no-notify', action='store_true')
    parser.add_argument('--channel', choices=('web_push', 'telegram'), default='web_push')
    args = parser.parse_args(argv)
    try:
        result = render_worker_profile(schema=args.schema, worker_role=args.worker_role,
            api_role=args.api_role, ai_enabled=not args.no_ai, notify_enabled=not args.no_notify,
            web_push=not args.no_notify and args.channel == 'web_push')
    except ValueError:
        print('WORKER_PROFILE_CONFIGURATION_INVALID', file=sys.stderr)
        return 2
    print(result, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
