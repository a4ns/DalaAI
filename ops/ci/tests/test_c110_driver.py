import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import c110_driver as driver


class C110IntegrationTests(unittest.TestCase):
    def model(self):
        root=Path(driver.__file__).resolve().parents[2]
        services={name:{} for name in driver.SERVICES}
        services['db']={'networks':{'backend':{}}}
        services['observer']={'network_mode':'service:db','user':'10001:10001','read_only':True,
            'cap_drop':['ALL'],'security_opt':['no-new-privileges:true'],'secrets':[{'source':'runtime_dsn'}],
            'build':{'context':str(root),'dockerfile':'ops/demo/Dockerfile.api'},
            'volumes':[{'type':'bind','read_only':True,'source':str(root/'tests/e2e/c110_observe.py'),'target':'/ci/c110_observe.py'},
                       {'type':'bind','read_only':True,'source':str(root/'ops/ci/observer_in_container.py'),'target':'/ci/observer_in_container.py'}]}
        return {'services':services,'networks':{'backend':{'internal':True}}}

    def test_disabled_worker_inventory_passes(self):
        self.assertEqual(driver.verify_service_inventory(self.model()), sorted(driver.SERVICES))

    def test_worker_not_profile_gated_fails(self):
        model = self.model(); model['services']['worker'] = {}
        with self.assertRaises(driver.C110Error): driver.verify_service_inventory(model)

    def test_profile_gated_worker_not_dependency_is_allowed(self):
        model = self.model(); model['services']['worker'] = {'profiles': ['workers']}
        self.assertEqual(driver.verify_service_inventory(model), sorted(driver.SERVICES))

    def test_core_worker_dependency_fails(self):
        model = self.model(); model['services']['worker'] = {'profiles': ['workers']}
        model['services']['api']['depends_on'] = {'worker': {}}
        with self.assertRaises(driver.C110Error): driver.verify_service_inventory(model)

    def test_public_database_bind_fails(self):
        model = self.model(); model['services']['db']['ports']=[{'host_ip':'127.0.0.1','published':'15432','target':5432}]
        with self.assertRaises(driver.C110Error): driver.verify_service_inventory(model)

    def test_enabled_worker_flag_fails(self):
        model = self.model(); model['services']['api']['environment'] = {'DALA_WORKER_ENABLED': '1'}
        with self.assertRaises(driver.C110Error): driver.verify_service_inventory(model)

    def test_actual_worker_running_fails(self):
        rows = [{'Service': name, 'State': 'running'} for name in driver.SERVICES | {'worker'}]
        with self.assertRaises(driver.C110Error): driver.verify_started_inventory(json.dumps(rows).encode())

    def test_actual_inventory_json_lines(self):
        rows = [{'Service': name, 'State': 'running' if name in {'api','web','db','observer'} else 'exited'} for name in driver.SERVICES]
        self.assertEqual(driver.verify_started_inventory('\n'.join(map(json.dumps, rows)).encode()), sorted(driver.SERVICES))

    def test_private_inputs_cannot_enter_dummy_preflight(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(driver.C110Error):
                driver.secrecy_preflight(Path(temp), {'DALA_E2E_MASTER_PIN_FILE': 'not-read'}, Path(temp))

    def test_source_blob_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); path=root/'tests/e2e/file.cjs'; path.parent.mkdir(parents=True); path.write_text('test')
            with self.assertRaises(driver.C110Error): driver.verify_source_blobs(root, {'tests/e2e/file.cjs': '0'*40})

    def test_exact_body_attachment_extracts_without_promoting_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); artifact=root/'artifacts'; artifact.mkdir(); private=root/'private'; private.mkdir()
            report=artifact/'report.json'
            raw=b'{"result":"FAIL","test":"synthetic body only"}'
            report.write_text(json.dumps({'suites':[{'specs':[{'tests':[{'results':[{'attachments':[{
                'name':'c110_evidence','contentType':'application/json','body':base64.b64encode(raw).decode()
            }]}]}]}]}]}))
            evidence=driver.extract_evidence(report,artifact,private)
            self.assertEqual(evidence.read_bytes(),raw)
            self.assertEqual(evidence.stat().st_mode & 0o777,0o600)

    def test_external_attachment_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); artifact=root/'artifacts'; artifact.mkdir(); private=root/'private'; private.mkdir()
            outside=root/'other.json'; outside.write_text('{}'); report=artifact/'report.json'
            report.write_text(json.dumps({'suites':[{'specs':[{'tests':[{'results':[{'attachments':[{
                'name':'c110_evidence','contentType':'application/json','path':str(outside)
            }]}]}]}]}]}))
            self.assertIsNone(driver.extract_evidence(report,artifact,private))

    def test_gate_runs_even_when_browser_report_is_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); (root/'tests/e2e').mkdir(parents=True); private=root/'private'; private.mkdir()
            with patch.object(driver, 'run', side_effect=[1,2]) as run:
                with self.assertRaises(driver.C110Error):
                    driver.execute_core(root,{},private,root/'cli.js')
            self.assertEqual(run.call_count,2)
            self.assertEqual(Path(run.call_args_list[1].args[0][1]).name,'c110_gate.cjs')
            self.assertFalse((root/'tests/e2e/c110_artifacts').exists())

    def test_preexisting_artifacts_are_not_deleted(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); artifacts=root/'tests/e2e/c110_artifacts'; artifacts.mkdir(parents=True)
            sentinel=artifacts/'keep'; sentinel.write_text('prior user content')
            with self.assertRaises(driver.C110Error):
                driver.execute_core(root,{},root,root/'cli.js')
            self.assertEqual(sentinel.read_text(),'prior user content')

    def test_existing_preflight_proof_is_not_reused(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); receipt=root/'c110-preflight-receipt.json'; receipt.write_text('{}')
            with self.assertRaises(driver.C110Error): driver.secrecy_preflight(root,{},root)
            self.assertEqual(receipt.read_text(),'{}')

    def test_source_manifest_cannot_escape_e2e(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with self.assertRaises(driver.C110Error):
                driver.verify_source_blobs(root,{'tests/e2e/../../outside':'0'*40})

    def test_observer_probe_failure_exports_only_fixed_code_and_class(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(driver.subprocess,'run') as run:
            run.return_value.returncode=2
            run.return_value.stdout=json.dumps({'status':'BLOCKED','code':'C110_DB_OBSERVATION_UNAVAILABLE',
                'error_type':'OperationalError','dsn':'secret-password','rows':['private-token']}).encode()
            result=driver.readonly_observer_probe(Path(tmp),{},'python')
            self.assertEqual(result,{'status':'FAIL','code':'C110_DB_OBSERVATION_UNAVAILABLE','error_type':'OperationalError'})
            self.assertNotIn('secret',json.dumps(result)); self.assertNotIn('private',json.dumps(result))
            self.assertEqual(run.call_args.args[0][-1],'00000000-0000-0000-0000-000000000000')

    def test_observer_probe_does_not_export_success_rows(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(driver.subprocess,'run') as run:
            run.return_value.returncode=0
            run.return_value.stdout=json.dumps({'source':'actual_postgresql_read_only','identity':{
                'direct_login':True,'read_only':True,'isolated_schema':True},'order':{'description':'private-data'}}).encode()
            result=driver.readonly_observer_probe(Path(tmp),{},'python')
            self.assertEqual(result,{'status':'PASS','scope':'readonly_zero_uuid_projection_only'})

    def test_observer_probe_rejects_arbitrary_error_fields(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(driver.subprocess,'run') as run:
            run.return_value.returncode=2
            run.return_value.stdout=json.dumps({'code':'private-token','error_type':'private-password'}).encode()
            result=driver.readonly_observer_probe(Path(tmp),{},'python')
            self.assertEqual(result,{'status':'FAIL','code':'C110_OBSERVER_PROBE_FAILED','error_type':'UNKNOWN'})

    def test_observer_cannot_receive_owner_secret(self):
        model=self.model(); model['services']['observer']['secrets'].append({'source':'owner_dsn'})
        with self.assertRaises(driver.C110Error): driver.verify_service_inventory(model)

    def test_observer_frozen_source_mount_is_checked(self):
        model=self.model(); model['services']['observer']['volumes'][0]['source']='/tmp/replacement.py'
        with self.assertRaises(driver.C110Error): driver.verify_service_inventory(model)

    def test_database_network_cannot_gain_external_access(self):
        model=self.model(); model['networks']['backend']['internal']=False
        with self.assertRaises(driver.C110Error): driver.verify_service_inventory(model)

    def test_observer_cannot_gain_host_network_or_capabilities(self):
        for field,value in [('network_mode','host'),('cap_add',['SYS_ADMIN']),('user','0:0')]:
            model=self.model(); model['services']['observer'][field]=value
            with self.assertRaises(driver.C110Error): driver.verify_service_inventory(model)


if __name__ == '__main__': unittest.main()
