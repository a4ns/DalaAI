"""Credential-free negative checks for isolated diagnostic wiring."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from body_probe_driver import preflight,source_hash,BRANCH,PRODUCT
from body_probe_observer import render,context_command
from body_probe_runner import browser_environment
from controls_profile import ControlsBlocked,HISTORY_VERSION,HISTORY_DIGEST

ROOT=Path(__file__).resolve().parents[2]
MASTER='8d27067c-4e86-50a2-87c4-f1012f53a2bb'
EXECUTOR='37baa480-be02-54bc-837c-6c0b2a00ec12'
CLOCK='a22d4edf-340d-4a81-a84a-670cc95910e6'
PROJECT='dalaai-controls-ci-1234567890abcdef'


def fixture():
    return dict(fixture_version=HISTORY_VERSION,fixture_mode='history',history_sha256=HISTORY_DIGEST,
        synthetic=True,history_orders=540,historical_actor_count=17,historical_actor_state='disabled_no_login',
        users=[dict(role='master',employee_code='DALA-DEMO-MASTER',id=MASTER),dict(role='executor',employee_code='DALA-DEMO-EXECUTOR',id=EXECUTOR)])


def owned(directory):
    for name,value in (('.fixture-owner','dalaai-mobile-ci-private-v1'),('.controls-owner','dalaai-controls-ci-v1'),('.body-probe-owner','dalaai-body-probe-private-v1')):
        (directory/name).write_text(value)
    (directory/'fixture.json').write_text(json.dumps(fixture()))
    wrapper=directory/'body-probe-observer-python';wrapper.write_text('source-only dummy')
    context=dict(root=str(ROOT),private=str(directory),project=PROJECT,clock=CLOCK,source=PRODUCT)
    return context,wrapper


class Wiring(unittest.TestCase):
    def test_runtime_child_context_is_derived_without_inherited_overrides(self):
        with tempfile.TemporaryDirectory() as temp:
            c,w=owned(Path(temp))
            with patch.dict(os.environ,{'DALA_CI_ROOT_DIR':'CANARY','DOCKER_HOST':'CANARY','LD_PRELOAD':'CANARY','PGPASSWORD':'CANARY','DALA_C113_OBSERVER_DATABASE_URL':'CANARY'}):
                root,command,env=context_command(c,w,[str(ROOT/'tests/e2e/c113_observe.py'),MASTER,EXECUTOR])
            self.assertEqual(root,ROOT);self.assertEqual(command[-7:],['exec','-T','observer','python','/ci/controls_observer_in_container.py',MASTER,EXECUTOR])
            self.assertEqual(env['DOCKER_HOST'],'unix:///var/run/docker.sock')
            self.assertEqual(env['DALA_CI_COMPOSE_PROJECT'],PROJECT)
            self.assertNotIn('CANARY',json.dumps([command,env]))
            self.assertFalse(any(k.startswith('PG') or 'PIN' in k or 'DSN' in k or 'DATABASE_URL' in k or k.startswith('LD_') for k in env))
    def test_arbitrary_script_and_swapped_actors_rejected_before_docker(self):
        with tempfile.TemporaryDirectory() as temp:
            c,w=owned(Path(temp))
            for argv in ([str(ROOT/'tests/e2e/c113_inspect_download.py'),MASTER,EXECUTOR],
                         [str(ROOT/'tests/e2e/c113_observe.py'),EXECUTOR,MASTER]):
                with self.assertRaises(ValueError):context_command(c,w,argv)
    def test_project_and_missing_owner_marker_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            c,w=owned(Path(temp));args=[str(ROOT/'tests/e2e/c113_observe.py'),MASTER,EXECUTOR]
            with self.assertRaises(ValueError):context_command(dict(c,project='existing-operator-project'),w,args)
            (Path(temp)/'.body-probe-owner').unlink()
            with self.assertRaises(ValueError):context_command(c,w,args)
    def test_wrapper_in_other_directory_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            c,w=owned(Path(temp))
            with self.assertRaises(ValueError):context_command(c,ROOT/'other-wrapper',[str(ROOT/'tests/e2e/c113_observe.py'),MASTER,EXECUTOR])
    def test_fixture_link_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);c,w=owned(p);(p/'fixture.json').rename(p/'real.json');(p/'fixture.json').symlink_to(p/'real.json')
            with self.assertRaises(ValueError):context_command(c,w,[str(ROOT/'tests/e2e/c113_observe.py'),MASTER,EXECUTOR])
    def test_render_is_fixed_source_not_child_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            private=Path(temp).resolve();text=render(ROOT,private,PROJECT,CLOCK,PRODUCT,Path(sys.executable).resolve())
            compile(text,'generated-private-wrapper','exec')
            self.assertIn(repr(str(private)),text);self.assertIn(repr(PROJECT),text)
            self.assertNotIn('os.environ[\'DALA_CI_',text)
    def test_preflight_rejects_every_private_input_without_starting_process(self):
        keys=['DALA_E2E_MASTER_PIN_FILE','DALA_E2E_EXECUTOR_PIN_FILE','DALA_E2E_FIXTURE_FILE',
              'DALA_BCP_OBSERVER_DATABASE_URL','DALA_BCP_AUTHORIZED','DALA_BCP_DATABASE_SCHEMA','PGPASSWORD']
        with tempfile.TemporaryDirectory() as temp,patch('body_probe_driver.run') as child:
            for key in keys:
                with self.assertRaises(ControlsBlocked):preflight(ROOT,{key:'CANARY'},Path(temp))
            child.assert_not_called()
    def test_existing_preflight_cannot_be_reused_or_overwritten(self):
        with tempfile.TemporaryDirectory() as temp,patch('body_probe_driver.run') as child:
            p=Path(temp);(p/'body-probe-preflight.json').write_text('keep')
            with self.assertRaises(ControlsBlocked):preflight(ROOT,{},p)
            child.assert_not_called();self.assertEqual((p/'body-probe-preflight.json').read_text(),'keep')
    def test_dummy_failure_does_not_read_or_create_actual_fixture(self):
        with tempfile.TemporaryDirectory() as temp,patch('body_probe_driver.run',return_value=SimpleNamespace(returncode=2,stdout=b'CANARY')):
            with self.assertRaisesRegex(ControlsBlocked,'^BODY_PROBE_DUMMY_PREFLIGHT_UNPROVEN$'):preflight(ROOT,{},Path(temp))
            self.assertEqual(list(Path(temp).iterdir()),[])
    def test_main_or_other_branch_blocked_before_any_source_mutation(self):
        result=SimpleNamespace(returncode=0,stdout=(PRODUCT+'\n').encode())
        with patch('body_probe_driver.run',return_value=result) as child:
            for ref in ('refs/heads/main','refs/heads/other','refs/pull/1/merge'):
                with self.assertRaises(ControlsBlocked):source_hash(ROOT,{'GITHUB_SHA':PRODUCT,'GITHUB_REF':ref})
            self.assertEqual(child.call_count,3)
    def test_dirty_and_untracked_source_block(self):
        ok=SimpleNamespace(returncode=0,stdout=b'');head=SimpleNamespace(returncode=0,stdout=PRODUCT.encode())
        with patch('body_probe_driver.run',side_effect=[head,SimpleNamespace(returncode=1,stdout=b'CANARY')]):
            with self.assertRaisesRegex(ControlsBlocked,'CLEAN_SOURCE'):source_hash(ROOT,{'GITHUB_SHA':PRODUCT,'GITHUB_REF':BRANCH})
        with patch('body_probe_driver.run',side_effect=[head,ok,SimpleNamespace(returncode=0,stdout=b'CANARY')]):
            with self.assertRaisesRegex(ControlsBlocked,'UNTRACKED_SOURCE'):source_hash(ROOT,{'GITHUB_SHA':PRODUCT,'GITHUB_REF':BRANCH})
    def test_browser_locator_and_fresh_home_are_explicit(self):
        env=browser_environment({'PATH':'/usr/bin'},Path('/private'),Path('/package'),Path('/installed/chromium'),'bcp-source-tests')
        self.assertEqual(env['PLAYWRIGHT_BROWSERS_PATH'],'/installed/chromium');self.assertEqual(env['HOME'],'/private/browser-home')
        self.assertFalse(any(k.startswith('DALA_CI') for k in env))
    def test_workflow_has_only_exact_branch_and_safe_artifacts(self):
        import yaml
        config=yaml.safe_load((ROOT/'.github/workflows/body-capture-probe.yml').read_text())
        self.assertEqual(config['on'],{'push':{'branches':['validation/body-capture-probe-20261008']}})
        steps=config['jobs']['diagnostic-only']['steps']
        upload=steps[-1]['with'];self.assertEqual(upload['path'].split(),['body-probe-summary.json','body-probe-evidence.json'])
        self.assertIn('github.run_attempt',upload['name'])
        self.assertEqual(next(s for s in steps if s.get('name','').startswith('Install locked'))['timeout-minutes'],10)


if __name__=='__main__':unittest.main()
