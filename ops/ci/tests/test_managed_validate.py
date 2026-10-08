import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location('managed_gate', HERE / 'managed_validate.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def config():
    inactive = {name: {'profiles': ['normal-demo-not-run']} for name in ('api','worker','web','photo-directory','budget-directory')}
    return {'networks': {'backend': {'internal': True}}, 'services': inactive | {
        'managed': {'image': 'fixture:candidate', 'build': {'dockerfile': 'ops/managed/Dockerfile'},
                    'networks': {'backend': {}}, 'environment': {'DALA_WORKER_NOTIFY_ENABLED': 'true',
                    'DALA_WEB_PUSH_ENABLED': 'false', 'DALA_MODEL_FORCE_OFF': 'true'}},
        'prepare': {'image': 'fixture:candidate'},
        'tls-edge': {'ports': [{'host_ip': '127.0.0.1', 'published': '443', 'target': 443}]}}}


def snapshot():
    return {'processes': {'api_uid':10001,'worker_uid':10001,'edge_uid':10002,
                         'api_loopback_only':True,'child_secret_scopes':'PASS'},
            'counts': {'orders':541,'photos':500,'submissions':569,'ai_assessments':1,'operation_receipts':6},
            'physical_photo_count':1,'photo_digest':'a'*64,'record_digest':'b'*64,
            'budget': {'calls_reserved':1,'outcome':'cancelled','actual_billed_cost':None,'reserved_upper_bound_microusd':100}}


class ManagedValidationTests(unittest.TestCase):
    def test_clean_environment_drops_accounts_and_remote_docker(self):
        with patch.dict(m.os.environ, {'PATH':'/bin','OPENAI_API_KEY':'fixture','DATABASE_URL':'fixture',
                                      'DOCKER_HOST':'tcp://untrusted','HTTP_PROXY':'fixture'}, clear=True):
            env=m.clean_environment()
        self.assertNotIn('OPENAI_API_KEY', env); self.assertNotIn('DATABASE_URL', env)
        self.assertNotIn('HTTP_PROXY', env)
        self.assertEqual(env['DOCKER_HOST'],'unix:///var/run/docker.sock')

    def test_project_is_bounded_and_reuses_base_compose(self):
        command=m.compose_command('dalaai-managed-ci-'+'a'*16,Path('/private'))
        self.assertEqual(sum('compose.yaml' in item for item in command),2)
        self.assertTrue(any('compose.workers.yaml' in item for item in command))
        self.assertFalse(any('history_compose' in item or 'c112' in item for item in command))
        with self.assertRaises(m.GateFailure):m.compose_command('dalaai-demo',Path('/private'))

    def test_correct_config(self):m.verify_config(config(),'fixture:candidate')

    def test_runtime_command_cannot_be_substituted(self):
        for key in ('command','entrypoint'):
            data=config();data['services']['managed'][key]=['fake']
            with self.assertRaises(m.GateFailure):m.verify_config(data,'fixture:candidate')

    def test_network_and_owner_secrets_fail_closed(self):
        for mutate in (lambda d:d['services']['managed'].update(ports=[443]),
                       lambda d:d['networks']['backend'].update(internal=False),
                       lambda d:d['services']['tls-edge']['ports'][0].update(host_ip='0.0.0.0'),
                       lambda d:d['services']['managed']['environment'].update(OPENAI_API_KEY='fixture'),
                       lambda d:d['services']['managed']['environment'].update(DALA_DEMO_OWNER_DATABASE_URL='fixture'),
                       lambda d:d['services']['managed']['environment'].update(DALA_WORKER_NOTIFY_ENABLED='false')):
            data=config();mutate(data)
            with self.assertRaises(m.GateFailure):m.verify_config(data,'fixture:candidate')

    def test_snapshot_requires_real_processes_identity_and_offline_ledger(self):
        self.assertEqual(m.validate_snapshot(snapshot()),snapshot())
        for mutate in (lambda d:d['processes'].update(api_uid=0),lambda d:d.update(photo_digest=''),
                       lambda d:d.update(record_digest=''),lambda d:d['counts'].update(orders=0),
                       lambda d:d['budget'].update(actual_billed_cost=1)):
            data=snapshot();mutate(data)
            with self.assertRaises(m.GateFailure):m.validate_snapshot(data)

    def test_smoke_requires_combined_real_oracles(self):
        sha='a'*40
        data={'source_sha':sha,'status':'PASS_COMPOSE_PHOTO_CYCLE','AI_worker':'PASS_PERSISTED_RULES_FALLBACK',
              'clock':'PASS_SHARED_PAUSE_ADVANCE_CAS_MASTER_ONLY',
              'history':'PASS_540_CANONICAL_ORDERS_VISIBLE_WITH_MISSING_EVIDENCE_DISCLOSURE',
              'exports':'PASS_ACTUAL_CONTAINER_PDF_XLSX_MASTER_ONLY'}
        self.assertEqual(m.validate_smoke(data,sha),data)
        for key in data:
            bad=dict(data);bad.pop(key)
            with self.assertRaises(m.GateFailure):m.validate_smoke(bad,sha)

    def test_missing_docker_is_not_run_before_secret_generation(self):
        report={'status':'FAIL'}
        with patch.object(m.shutil,'which',return_value=None),patch.object(m,'prepare_private') as prepare:
            m.run(report)
        self.assertEqual(report['status'],'NOT_RUN');prepare.assert_not_called()

    def test_blueprint_default_has_no_test_localhost_gate(self):
        source=(HERE.parent/'managed/render.yaml.example').read_text()
        self.assertNotIn('DALA_MANAGED_TEST_LOCALHOST',source)

    def test_workflow_only_uses_isolated_branch(self):
        import yaml
        data=yaml.safe_load((m.ROOT/'.github/workflows/managed-image-validation.yml').read_text())
        self.assertEqual(data['on']['push']['branches'],['validation/managed-image-20261008'])
        self.assertEqual(data['permissions'],{'contents':'read'})
        text=json.dumps(data)
        self.assertNotIn('workflow_dispatch',text);self.assertNotIn('c112',text.lower())

    def test_source_overlay_uses_actual_image_and_original_bootstrap(self):
        import yaml
        data=yaml.safe_load((HERE/'managed_compose.yaml').read_text())
        self.assertEqual(data['services']['managed']['build']['dockerfile'],'ops/managed/Dockerfile')
        self.assertEqual(data['services']['prepare']['command'],['python','/ci/setup.py'])
        self.assertTrue(any('ops/demo/setup.py:/ci/setup.py:ro' in x for x in data['services']['prepare']['volumes']))
        self.assertNotIn('command',data['services']['managed'])

    def test_no_raw_log_or_held_source_output(self):
        source=(HERE/'managed_validate.py').read_text()
        self.assertNotIn("['logs'",source)
        self.assertNotIn('history_driver',source)
        self.assertIn('ssl.CERT_REQUIRED',source)
        self.assertIn('context.check_hostname',source)


if __name__=='__main__':unittest.main()
