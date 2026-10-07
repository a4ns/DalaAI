from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from history_profile import *
from history_observer_python import command_for
from history_driver import secrecy_preflight, execute_history, failure_projection

MASTER='8d27067c-4e86-50a2-87c4-f1012f53a2bb'
EXECUTOR='37baa480-be02-54bc-837c-6c0b2a00ec12'
ROOT=Path('/repo')
PROJECT='dalaai-history-ci-1234567890abcdef'


def manifest():
    return dict(fixture_version=HISTORY_VERSION,fixture_mode='history',history_sha256=HISTORY_DIGEST,
        synthetic=True,history_orders=540,historical_actor_count=17,historical_actor_state='disabled_no_login',
        users=[dict(role='master',employee_code='DALA-DEMO-MASTER',id=MASTER),
               dict(role='executor',employee_code='DALA-DEMO-EXECUTOR',id=EXECUTOR)])


def model():
    services={name:{} for name in HISTORY_SERVICES|INACTIVE_SERVICES}
    for name in INACTIVE_SERVICES: services[name]['profiles']=['c112-inactive']
    services['db']={'networks':{'backend':{}}}
    services['prepare']={'environment':{'DALA_DEMO_FIXTURE_MODE':'history','DALA_DEMO_WORKER_CAPABILITY_ALLOWED':'1','DALA_DEMO_CLOCK_ENABLED':'false'}}
    for name in ('api','worker'): services[name]['environment']={'DALA_WEB_PUSH_ENABLED':'false','DALA_DEMO_CLOCK_ENABLED':'false'}
    services['worker']['environment'].update(DALA_MODEL_FORCE_OFF='true',DALA_WORKER_ENABLED='false',DALA_WORKER_AI_ENABLED='false',DALA_WORKER_NOTIFY_ENABLED='false')
    services['observer']={'network_mode':'service:db','user':'10001:10001','read_only':True,
        'cap_drop':['ALL'],'security_opt':['no-new-privileges:true'],'secrets':[{'source':'runtime_dsn'}],
        'build':{'context':str(ROOT),'dockerfile':'ops/demo/Dockerfile.api'},
        'volumes':[{'type':'bind','source':str(ROOT/name),'target':target,'read_only':True} for name,target in
            [('tests/e2e/c112_observe.py','/ci/c112_observe.py'),('ops/ci/history_observer_in_container.py','/ci/history_observer_in_container.py')]]}
    return {'services':services,'networks':{'backend':{'internal':True}}}


class HistorySafety(unittest.TestCase):
    def test_exact_history_profile(self): self.assertEqual(validate_profile(model(),ROOT),sorted(HISTORY_SERVICES))
    def test_exact_public_actors(self): self.assertEqual(public_actor_ids(manifest()),(MASTER,EXECUTOR))
    def test_minimal_or_altered_history_rejected(self):
        for key,value in [('fixture_mode','minimal'),('history_orders',539),('history_sha256','0'*64),('synthetic',False)]:
            with self.subTest(key=key):
                data=manifest(); data[key]=value
                with self.assertRaises(HistoryBlocked): public_actor_ids(data)
    def test_same_actor_rejected(self):
        data=manifest(); data['users'][1]['id']=MASTER
        with self.assertRaises(HistoryBlocked): public_actor_ids(data)
    def test_duplicate_identity_rejected(self):
        data=manifest(); data['users'].append(data['users'][0])
        with self.assertRaises(HistoryBlocked): public_actor_ids(data)
    def test_only_three_exact_compose_files_and_two_env_files(self):
        cmd=compose_command(ROOT,Path('/private'),PROJECT)
        self.assertEqual(cmd.count('-f'),3); self.assertEqual(cmd.count('--env-file'),2)
        self.assertNotIn('--profile',cmd)
    def test_real_project_relative_path_rejected(self):
        for root,private,project in [(ROOT,Path('/p'),'dalaai-demo'),(Path('.'),Path('/p'),PROJECT),(ROOT,Path('p'),PROJECT)]:
            with self.assertRaises(HistoryBlocked): compose_command(root,private,project)
    def test_adapter_binds_exact_source_and_both_actors(self):
        cmd=command_for(ROOT,Path('/private'),PROJECT,str(ROOT/'tests/e2e/c112_observe.py'),[MASTER,EXECUTOR],manifest())
        self.assertEqual(cmd[-7:],['exec','-T','observer','python','/ci/history_observer_in_container.py',MASTER,EXECUTOR])
        self.assertNotIn('password',' '.join(cmd)); self.assertNotIn('dsn',' '.join(cmd))
    def test_adapter_rejects_alternate_observer(self):
        with self.assertRaises(ValueError): command_for(ROOT,Path('/p'),PROJECT,'/repo/tests/e2e/c110_observe.py',[MASTER,EXECUTOR],manifest())
    def test_adapter_rejects_swapped_actors(self):
        with self.assertRaises(ValueError): command_for(ROOT,Path('/p'),PROJECT,'/repo/tests/e2e/c112_observe.py',[EXECUTOR,MASTER],manifest())
    def test_adapter_rejects_malformed_actor(self):
        with self.assertRaises(ValueError): command_for(ROOT,Path('/p'),PROJECT,'/repo/tests/e2e/c112_observe.py',[MASTER,'; echo no'],manifest())
    def test_active_dependency_on_worker_rejected(self):
        data=model(); data['services']['api']['depends_on']={'worker':{}}
        with self.assertRaises(HistoryBlocked): validate_profile(data,ROOT)
    def test_worker_profile_required(self):
        data=model(); data['services']['worker'].pop('profiles')
        with self.assertRaises(HistoryBlocked): validate_profile(data,ROOT)
    def test_extra_service_rejected(self):
        data=model(); data['services']['extra']={}
        with self.assertRaises(HistoryBlocked): validate_profile(data,ROOT)
    def test_db_publishing_rejected(self):
        data=model(); data['services']['db']['ports']=['15432:5432']
        with self.assertRaises(HistoryBlocked): validate_profile(data,ROOT)
    def test_db_external_network_rejected(self):
        data=model(); data['networks']['backend']['internal']=False
        with self.assertRaises(HistoryBlocked): validate_profile(data,ROOT)
    def test_provider_key_rejected(self):
        data=model(); data['services']['api']['environment']['OPENAI_API_KEY']='dummy-never-real'
        with self.assertRaises(HistoryBlocked): validate_profile(data,ROOT)
    def test_observer_owner_secret_rejected(self):
        data=model(); data['services']['observer']['secrets'].append({'source':'owner_dsn'})
        with self.assertRaises(HistoryBlocked): validate_profile(data,ROOT)
    def test_observer_host_namespace_rejected(self):
        data=model(); data['services']['observer']['network_mode']='host'
        with self.assertRaises(HistoryBlocked): validate_profile(data,ROOT)
    def test_observer_source_mount_rejected(self):
        data=model(); data['services']['observer']['volumes'][0]['source']='/other.py'
        with self.assertRaises(HistoryBlocked): validate_profile(data,ROOT)
    def test_observer_writable_mount_rejected(self):
        data=model(); data['services']['observer']['volumes'][0]['read_only']=False
        with self.assertRaises(HistoryBlocked): validate_profile(data,ROOT)
    def test_observer_capability_rejected(self):
        data=model(); data['services']['observer']['cap_add']=['DAC_OVERRIDE']
        with self.assertRaises(HistoryBlocked): validate_profile(data,ROOT)
    def test_actual_worker_rejected(self):
        rows=[{'Service':name,'State':'running'} for name in HISTORY_SERVICES|{'worker'}]
        with self.assertRaises(HistoryBlocked): validate_actual_services(rows)
    def test_actual_six_services_pass(self):
        self.assertEqual(validate_actual_services([{'Service':name,'State':'running'} for name in HISTORY_SERVICES]),sorted(HISTORY_SERVICES))
    def test_preflight_rejects_private_inputs_before_process(self):
        with tempfile.TemporaryDirectory() as temp,patch('history_driver.run') as child:
            for key in ['DALA_E2E_MASTER_PIN_FILE','DALA_E2E_EXECUTOR_PIN_FILE','DALA_E2E_FIXTURE_FILE','DALA_C112_OBSERVER_DATABASE_URL','PGPASSWORD']:
                with self.assertRaises(HistoryBlocked): secrecy_preflight(ROOT,{key:'dummy'},Path(temp))
            child.assert_not_called()
    def test_existing_receipt_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp,patch('history_driver.run') as child:
            p=Path(temp); (p/'c112-preflight-receipt.json').write_text('untouched')
            with self.assertRaises(HistoryBlocked): secrecy_preflight(ROOT,{},p)
            self.assertEqual((p/'c112-preflight-receipt.json').read_text(),'untouched'); child.assert_not_called()
    def test_missing_browser_report_still_runs_strict_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); (root/'tests/e2e').mkdir(parents=True)
            with patch('history_driver.run',return_value=SimpleNamespace(returncode=1,stdout=b'')) as child:
                with self.assertRaises(HistoryBlocked): execute_history(root,{'DALA_C112_RUN_ID':'c112-fresh-run'},root,Path('/cli'),{})
                self.assertEqual(child.call_count,2)
                self.assertIn('c112_gate.cjs',child.call_args.args[0][1])
                self.assertFalse((root/'tests/e2e/c112_artifacts').exists())
    def test_existing_artifacts_are_not_deleted(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); p=root/'tests/e2e/c112_artifacts'; p.mkdir(parents=True); (p/'keep').write_text('keep')
            with self.assertRaises(HistoryBlocked): execute_history(root,{},root,Path('/cli'),{})
            self.assertTrue((p/'keep').exists())
    def test_diagnostic_never_emits_dynamic_values(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'e.json'; p.write_text(json.dumps({'steps':[{'name':'SECRET','result':'FAIL'}],'error':'SECRET','observations':['SECRET']}))
            self.assertNotIn('SECRET',json.dumps(failure_projection(Path('/none'),p)))


if __name__=='__main__': unittest.main()
