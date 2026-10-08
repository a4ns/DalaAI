from copy import deepcopy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from controls_profile import ControlsBlocked,HISTORY_SERVICES,INACTIVE_SERVICES,validate_profile,validate_actual_services,compose_command

ROOT=Path('/repo')
INSTANCE='a22d4edf-340d-4a81-a84a-670cc95910e6'


def model():
    services={name:{} for name in HISTORY_SERVICES|INACTIVE_SERVICES}
    for name in INACTIVE_SERVICES:services[name]['profiles']=['c113-inactive']
    services['db']={'networks':{'backend':{}}}
    for name in ('prepare','api','worker'):
        services[name]['environment']={'DALA_DEMO_CLOCK_ENABLED':'true','DALA_DEMO_CLOCK_INSTANCE_ID':INSTANCE}
    services['prepare']['environment'].update(DALA_DEMO_FIXTURE_MODE='history',DALA_DEMO_WORKER_CAPABILITY_ALLOWED='1')
    for name in ('api','worker'):services[name]['environment']['DALA_WEB_PUSH_ENABLED']='false'
    services['worker']['environment'].update(DALA_MODEL_FORCE_OFF='true',DALA_WORKER_ENABLED='false',DALA_WORKER_AI_ENABLED='false',DALA_WORKER_NOTIFY_ENABLED='false')
    services['observer']={'network_mode':'service:db','user':'10001:10001','read_only':True,
        'cap_drop':['ALL'],'security_opt':['no-new-privileges:true'],'secrets':[{'source':'runtime_dsn'}],
        'build':{'context':str(ROOT),'dockerfile':'ops/demo/Dockerfile.api'},
        'volumes':[{'type':'bind','source':str(ROOT/name),'target':target,'read_only':True} for name,target in
        [('tests/e2e/c113_observe.py','/ci/c113_observe.py'),('ops/ci/controls_observer_in_container.py','/ci/controls_observer_in_container.py')]]}
    return {'services':services,'networks':{'backend':{'internal':True}}}


class ControlsProfile(unittest.TestCase):
    def test_exact_enabled_clock_worker_absent_profile(self):
        self.assertEqual(validate_profile(model(),ROOT),sorted(HISTORY_SERVICES))
    def test_clock_cannot_be_enabled_only_in_api(self):
        data=model();data['services']['prepare']['environment']['DALA_DEMO_CLOCK_ENABLED']='false'
        with self.assertRaises(ControlsBlocked):validate_profile(data,ROOT)
    def test_all_services_bind_same_clock_instance(self):
        data=model();data['services']['api']['environment']['DALA_DEMO_CLOCK_INSTANCE_ID']='b22d4edf-340d-4a81-a84a-670cc95910e6'
        with self.assertRaises(ControlsBlocked):validate_profile(data,ROOT)
    def test_missing_or_malformed_clock_instance_rejected(self):
        for value in ('','not-a-uuid'):
            data=model()
            for name in ('prepare','api','worker'):data['services'][name]['environment']['DALA_DEMO_CLOCK_INSTANCE_ID']=value
            with self.assertRaises(ControlsBlocked):validate_profile(data,ROOT)
    def test_worker_flag_cannot_be_enabled(self):
        data=model();data['services']['worker']['environment']['DALA_WORKER_ENABLED']='true'
        with self.assertRaises(ControlsBlocked):validate_profile(data,ROOT)
    def test_worker_profile_and_dependency_stay_separate(self):
        data=model();data['services']['api']['depends_on']={'worker':{}}
        with self.assertRaises(ControlsBlocked):validate_profile(data,ROOT)
    def test_observer_cannot_mount_other_suite(self):
        data=model();data['services']['observer']['volumes'][0]['source']='/repo/tests/e2e/c112_observe.py'
        with self.assertRaises(ControlsBlocked):validate_profile(data,ROOT)
    def test_observer_cannot_receive_owner_input(self):
        data=model();data['services']['observer']['secrets'].append({'source':'owner_dsn'})
        with self.assertRaises(ControlsBlocked):validate_profile(data,ROOT)
    def test_database_stays_unpublished(self):
        data=model();data['services']['db']['ports']=['127.0.0.1:15432:5432']
        with self.assertRaises(ControlsBlocked):validate_profile(data,ROOT)
    def test_project_cannot_adopt_history_or_operator_stack(self):
        for name in ('dalaai-history-ci-1234567890abcdef','dalaai-demo'):
            with self.assertRaises(ControlsBlocked):compose_command(ROOT,Path('/private'),name)
    def test_only_new_controls_overlay_is_selected(self):
        command=compose_command(ROOT,Path('/private'),'dalaai-controls-ci-1234567890abcdef')
        self.assertIn('/repo/ops/ci/controls_compose.yaml',command)
        self.assertNotIn('/repo/ops/ci/history_compose.yaml',command)
    def test_actual_worker_is_rejected(self):
        rows=[{'Service':name,'State':'running'} for name in HISTORY_SERVICES|{'worker'}]
        with self.assertRaises(ControlsBlocked):validate_actual_services(rows)


if __name__=='__main__':unittest.main()
