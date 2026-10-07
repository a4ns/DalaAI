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
        return {'services': {name: ({'ports': [{'host_ip': '127.0.0.1', 'published': '15432', 'target': 5432}]} if name == 'db' else {})
                             for name in driver.SERVICES}}

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
        model = self.model(); model['services']['db']['ports'][0]['host_ip'] = '0.0.0.0'
        with self.assertRaises(driver.C110Error): driver.verify_service_inventory(model)

    def test_enabled_worker_flag_fails(self):
        model = self.model(); model['services']['api']['environment'] = {'DALA_WORKER_ENABLED': '1'}
        with self.assertRaises(driver.C110Error): driver.verify_service_inventory(model)

    def test_actual_worker_running_fails(self):
        rows = [{'Service': name, 'State': 'running'} for name in driver.SERVICES | {'worker'}]
        with self.assertRaises(driver.C110Error): driver.verify_started_inventory(json.dumps(rows).encode())

    def test_actual_inventory_json_lines(self):
        rows = [{'Service': name, 'State': 'running' if name in {'api','web','db'} else 'exited'} for name in driver.SERVICES]
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


if __name__ == '__main__': unittest.main()
