import importlib.util
from pathlib import Path
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('managed_supervisor', ROOT / 'supervise.py')
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)


def config():
    return dict(DALA_MANAGED_START_APPROVED='true', PORT='10000', DALA_API_MODE='demo',
        DALA_DATABASE_SCHEMA='dalaai_demo', DALA_ALLOWED_ORIGIN='https://demo.example.com',
        DATABASE_URL='postgresql://api:fixture@private-db:5432/naryadai',
        DALA_WORKER_DATABASE_URL='postgresql://worker:fixture@private-db:5432/naryadai',
        DALA_PHOTO_STORAGE_ROOT='/var/lib/naryadai/photos',
        DALA_MODEL_BUDGET_PATH='/var/lib/naryadai/budget/openai.sqlite3',
        DALA_WORKER_ENABLED='true', DALA_WORKER_AI_ENABLED='true')


class ManagedTests(unittest.TestCase):
    def test_no_import_startup(self):
        self.assertEqual(s.ROOT, Path('/var/lib/naryadai'))

    def test_default_start_requires_operator(self):
        e = config(); e.pop('DALA_MANAGED_START_APPROVED')
        with self.assertRaises(ValueError): s.child_environments(e)

    def test_role_separation(self):
        e = config(); e['DALA_WORKER_DATABASE_URL'] = e['DATABASE_URL']
        with self.assertRaises(ValueError): s.child_environments(e)

    def test_mismatched_database(self):
        for value in ['postgresql://worker:fixture@other-db:5432/naryadai',
                      'postgresql://worker:fixture@private-db:5432/production', '']:
            e = config(); e['DALA_WORKER_DATABASE_URL'] = value
            with self.subTest(value=value), self.assertRaises(ValueError): s.child_environments(e)

    def test_bad_origins(self):
        for value in ['http://demo.example.com', 'https://demo.example.com/',
                      'https://demo.example.com/path', 'https://x@demo.example.com',
                      'https://*.example.com', 'https://demo.example.com:443',
                      'https://demo.example.com\nINJECT', 'https://demo..example.com']:
            e = config(); e['DALA_ALLOWED_ORIGIN'] = value
            with self.subTest(value=value), self.assertRaises(ValueError): s.child_environments(e)

    def test_localhost_is_test_only_and_still_exact_https(self):
        e = config() | {'DALA_ALLOWED_ORIGIN': 'https://localhost'}
        with self.assertRaises(ValueError): s.child_environments(e)
        api, worker, edge = s.child_environments(e | {'DALA_MANAGED_TEST_LOCALHOST': 'true'})
        self.assertEqual(api['DALA_ALLOWED_ORIGIN'], 'https://localhost')
        self.assertEqual(edge['DALA_PUBLIC_HOST'], 'localhost')
        self.assertNotIn('DALA_MANAGED_TEST_LOCALHOST', api)
        for origin in ('http://localhost', 'https://localhost:443', 'https://localhost:8443', 'https://localhost/'):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                s.child_environments(e | {'DALA_ALLOWED_ORIGIN': origin, 'DALA_MANAGED_TEST_LOCALHOST': 'true'})

    def test_owner_and_pin_rejected(self):
        for key in s.FORBIDDEN:
            e = config(); e[key] = 'fixture-do-not-propagate'
            with self.subTest(key=key), self.assertRaises(ValueError): s.child_environments(e)

    def test_filter_secrets_by_process(self):
        e = config() | {'OPENAI_API_KEY': 'fixture', 'DALA_VAPID_PRIVATE_KEY': 'fixture',
                        'UNKNOWN_SECRET': 'fixture', 'LD_PRELOAD': 'fixture', 'PYTHONPATH': 'fixture'}
        api, worker, edge = s.child_environments(e)
        self.assertNotIn('OPENAI_API_KEY', api)
        self.assertNotIn('DALA_WORKER_DATABASE_URL', api)
        self.assertEqual(api['DALA_VAPID_PRIVATE_KEY'], 'fixture')
        self.assertNotIn('DALA_VAPID_PRIVATE_KEY', edge)
        self.assertNotIn('DATABASE_URL', worker)
        self.assertEqual(worker['OPENAI_API_KEY'], 'fixture')
        self.assertFalse(set(edge) & {'DATABASE_URL', 'DALA_WORKER_DATABASE_URL', 'OPENAI_API_KEY'})
        for env in (api, worker, edge):
            self.assertNotIn('UNKNOWN_SECRET', env)
            self.assertNotIn('LD_PRELOAD', env)
            self.assertEqual(env['PYTHONPATH'], '/service')

    def test_secret_paths_must_be_platform_files(self):
        for value in ['/srv/approval.json', '/etc/secrets/../approval.json', 'approval.json']:
            e = config(); e['DALA_MODEL_APPROVAL_FILE'] = value
            with self.subTest(value=value), self.assertRaises(ValueError): s.child_environments(e)

    def test_canonical_interactive_model_env(self):
        e = config() | {'DALA_MODEL_PROJECT_ID': 'DalaAI', 'DALA_MODEL_INSTANCE_ID': 'fixture-instance',
                        'DALA_MODEL_APPROVAL_FILE': '/etc/secrets/demo-model-policy.json',
                        'OPENAI_API_KEY_FILE': '/etc/secrets/openai-key'}
        api, worker, edge = s.child_environments(e)
        for key in ('DALA_MODEL_PROJECT_ID', 'DALA_MODEL_INSTANCE_ID', 'OPENAI_API_KEY_FILE'):
            self.assertIn(key, worker)
            self.assertNotIn(key, api)
            self.assertNotIn(key, edge)
        self.assertNotIn('DALA_WORKER_OPENAI_ENABLED', worker)
        for key, value in [('OPENAI_API_KEY', 'fixture'), ('DALA_WORKER_OPENAI_ENABLED', 'false'),
                           ('DALA_MODEL_IMAGE_SELECTIONS_FILE', '/etc/secrets/obsolete.json')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                s.child_environments(e | {key: value})

    def test_fixed_paths_and_port(self):
        for key, value in [('DALA_PHOTO_STORAGE_ROOT', '/srv/photos'), ('PORT', '8000'),
                           ('PORT', '80'), ('PORT', '70000'), ('PORT', '10000;sh'),
                           ('DALA_MODEL_BUDGET_PATH', '/tmp/budget.sqlite3')]:
            e = config(); e[key] = value
            with self.subTest(key=key,value=value), self.assertRaises(ValueError): s.child_environments(e)

    def test_worker_cannot_be_silently_disabled(self):
        e = config(); e['DALA_WORKER_ENABLED'] = 'false'
        with self.assertRaises(ValueError): s.child_environments(e)

    def test_no_unreviewed_telegram_mode(self):
        e = config(); e['TELEGRAM_MODE'] = 'live'
        with self.assertRaises(ValueError): s.child_environments(e)

    def test_missing_real_mount_fails_before_metadata_writes(self):
        with patch.object(s.os, 'geteuid', return_value=0), patch.object(s.os.path, 'ismount', return_value=False), \
             patch.object(s.os, 'fchown') as chown, patch.object(s.os, 'fchmod') as chmod:
            with self.assertRaises(ValueError): s.prepare_storage()
            chown.assert_not_called(); chmod.assert_not_called()

    def test_symlink_directory_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); outside = root / 'outside'; outside.mkdir()
            (root / 'photos').symlink_to(outside, target_is_directory=True)
            original_fstat = os.fstat
            def checked(fd):
                info = original_fstat(fd)
                class Info:
                    st_uid = 0
                    st_mode = info.st_mode
                return Info()
            with patch.object(s, 'ROOT', root), patch.object(s.os, 'geteuid', return_value=0), \
                 patch.object(s.os.path, 'ismount', return_value=True), patch.object(s.os, 'fstat', side_effect=checked), \
                 patch.object(s.os, 'fchmod'), patch.object(s.os, 'fchown') as chown:
                with self.assertRaises(OSError): s.prepare_storage(root)
                chown.assert_not_called()

    def test_shutdown_terminates_child_group(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
        s.stop_children([('fixture', child)], grace=2)
        self.assertIsNotNone(child.poll())

    def test_fixed_api_proxy_boundary(self):
        self.assertIn('--no-proxy-headers', s.API_COMMAND)
        self.assertEqual(s.API_COMMAND[s.API_COMMAND.index('--host') + 1], '127.0.0.1')
        self.assertIn('--no-access-log', s.API_COMMAND)
        caddy = (ROOT / 'Caddyfile').read_text()
        self.assertIn('admin off', caddy)
        self.assertIn('root * /srv', caddy)
        self.assertNotIn('/var/lib/naryadai', caddy)

    def test_copied_managed_caddy_loses_unneeded_file_capability(self):
        import shlex
        dockerfile=(ROOT/'Dockerfile').read_text()
        line=next(row for row in dockerfile.splitlines() if row.startswith('RUN python -c ') and 'security.capability' in row)
        script=shlex.split(line)[3]
        for initially_present in (True,False):
            attrs=['security.capability'] if initially_present else []
            with patch.object(os,'listxattr',side_effect=lambda path:list(attrs)) as listing, \
                 patch.object(os,'removexattr',side_effect=lambda path,attribute:attrs.remove(attribute)) as removal:
                exec(compile(script,'<managed-caddy-capability-check>','exec'),{})
                self.assertNotIn('security.capability',attrs)
                self.assertTrue(all(call.args==('/usr/bin/caddy',) for call in listing.call_args_list))
                if initially_present:removal.assert_called_once_with('/usr/bin/caddy','security.capability')
                else:removal.assert_not_called()
        self.assertNotIn('SYS_PTRACE',dockerfile)

    def test_worker_preflight_failure_starts_no_listener(self):
        from types import SimpleNamespace
        import io
        with patch.dict(s.os.environ, config(), clear=True), patch.object(s, 'prepare_storage'), \
             patch.object(s.subprocess, 'run', return_value=SimpleNamespace(returncode=2)), \
             patch.object(s, 'launch') as start, patch.object(s.signal, 'signal'), \
             patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(s.main(), 1)
            start.assert_not_called()
            self.assertNotIn('fixture', output.getvalue())

    def test_launch_fixed_nonroot_identity_and_no_shell(self):
        for uid in (10001, 10002):
            with patch.object(s.subprocess, 'Popen') as popen:
                s.launch(['fixed-binary', 'fixed-arg'], {'SAFE': 'value'}, uid)
                _, kwargs = popen.call_args
                self.assertEqual(kwargs['user'], uid)
                self.assertEqual(kwargs['group'], uid)
                self.assertEqual(kwargs['extra_groups'], [])
                self.assertEqual(kwargs['umask'], 0o077)
                self.assertTrue(kwargs['start_new_session'])
                self.assertNotIn('shell', kwargs)

    def test_blueprint_is_inert_source_with_explicit_paid_resources(self):
        import yaml
        data = yaml.safe_load((ROOT / 'render.yaml.example').read_text())
        service = data['services'][0]
        self.assertEqual(service['autoDeployTrigger'], 'off')
        self.assertEqual(data['previews']['generation'], 'off')
        self.assertEqual(service['numInstances'], 1)
        self.assertEqual(service['plan'], '1c-2g')
        self.assertEqual(service['disk']['mountPath'], '/var/lib/naryadai')
        self.assertEqual(data['databases'][0]['ipAllowList'], [])
        env = {v['key']: v for v in service['envVars']}
        self.assertEqual(env['DALA_MANAGED_START_APPROVED']['value'], 'false')
        for key in ('DATABASE_URL', 'DALA_WORKER_DATABASE_URL'):
            self.assertFalse(env[key]['sync'])
            self.assertNotIn('value', env[key])
        self.assertNotIn('preDeployCommand', service)
        self.assertNotIn('initialDeployHook', service)


if __name__ == '__main__': unittest.main()
