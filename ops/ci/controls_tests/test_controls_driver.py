import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from controls_profile import ControlsBlocked,HISTORY_VERSION,HISTORY_DIGEST
from controls_driver import secrecy_preflight,execute_controls
from controls_runner import clock_instance
from controls_observer_python import command_for
from controls_diagnostics import failure_projection, file_presence, download_projection,request_projection,STEPS

MASTER='8d27067c-4e86-50a2-87c4-f1012f53a2bb'; EXECUTOR='37baa480-be02-54bc-837c-6c0b2a00ec12'
INSTANCE='a22d4edf-340d-4a81-a84a-670cc95910e6'

def manifest():
    return dict(fixture_version=HISTORY_VERSION,fixture_mode='history',history_sha256=HISTORY_DIGEST,
        synthetic=True,history_orders=540,historical_actor_count=17,historical_actor_state='disabled_no_login',
        users=[dict(role='master',employee_code='DALA-DEMO-MASTER',id=MASTER),dict(role='executor',employee_code='DALA-DEMO-EXECUTOR',id=EXECUTOR)])

class ControlsDriver(unittest.TestCase):
    def test_existing_proof_is_not_reused(self):
        with tempfile.TemporaryDirectory() as d,patch('controls_driver.run') as child:
            p=Path(d);(p/'c113-preflight-receipt.json').write_text('keep')
            with self.assertRaises(ControlsBlocked):secrecy_preflight(p,{},p)
            child.assert_not_called();self.assertEqual((p/'c113-preflight-receipt.json').read_text(),'keep')
    def test_private_inputs_forbidden_before_proof(self):
        with tempfile.TemporaryDirectory() as d,patch('controls_driver.run') as child:
            for key in ['DALA_E2E_MASTER_PIN_FILE','DALA_E2E_FIXTURE_FILE','DALA_C113_OBSERVER_DATABASE_URL','PGPASSWORD']:
                with self.assertRaises(ControlsBlocked):secrecy_preflight(Path(d),{key:'dummy'},Path(d))
            child.assert_not_called()
    def test_gate_runs_on_browser_failure_and_raw_tree_is_removed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'tests/e2e').mkdir(parents=True)
            with patch('controls_driver.run',return_value=SimpleNamespace(returncode=1,stdout=b'')) as child:
                with self.assertRaises(ControlsBlocked):execute_controls(p,{'DALA_C113_RUN_ID':'c113-fixture-run'},p,Path('/cli'),{})
                self.assertEqual(child.call_count,2);self.assertIn('c113_gate.cjs',child.call_args.args[0][1])
                self.assertFalse((p/'tests/e2e/c113_artifacts').exists())
    def test_gate_runs_even_after_runner_exception(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'tests/e2e').mkdir(parents=True)
            with patch('controls_driver.run',side_effect=[TimeoutError(),SimpleNamespace(returncode=2,stdout=b'{}')]) as child:
                with self.assertRaises(ControlsBlocked):execute_controls(p,{'DALA_C113_RUN_ID':'c113-fixture-run'},p,Path('/cli'),{})
                self.assertEqual(child.call_count,2)
    def test_saved_files_remain_until_c_owned_gate_executes(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'tests/e2e').mkdir(parents=True);folder=p/'tests/e2e/c113_artifacts/c113-fixture-run'
            def child(argv,*args):
                if 'test' in argv:
                    folder.mkdir();(folder/'saved-shift.pdf').write_bytes(b'dummy-source-test-only')
                    return SimpleNamespace(returncode=1,stdout=b'')
                self.assertTrue((folder/'saved-shift.pdf').exists())
                return SimpleNamespace(returncode=2,stdout=b'{}')
            with patch('controls_driver.run',side_effect=child):
                with self.assertRaises(ControlsBlocked):execute_controls(p,{'DALA_C113_RUN_ID':'c113-fixture-run'},p,Path('/cli'),{})
            self.assertFalse(folder.exists())
    def test_existing_artifact_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);f=p/'tests/e2e/c113_artifacts';f.mkdir(parents=True);(f/'keep').write_text('keep')
            with self.assertRaises(ControlsBlocked):execute_controls(p,{},p,Path('/cli'),{})
            self.assertTrue((f/'keep').exists())
    def test_clock_uuid_loaded_only_from_owned_enabled_fixture(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'.controls-owner').write_text('dalaai-controls-ci-v1');(p/'clock_mode').write_text('true');(p/'clock_instance').write_text(INSTANCE)
            self.assertEqual(clock_instance(p),INSTANCE)
            (p/'clock_mode').write_text('false')
            with self.assertRaises(ControlsBlocked):clock_instance(p)
    def test_clock_link_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'.controls-owner').write_text('dalaai-controls-ci-v1');(p/'clock_mode').write_text('true');(p/'real').write_text(INSTANCE);(p/'clock_instance').symlink_to(p/'real')
            with self.assertRaises(ControlsBlocked):clock_instance(p)
    def test_observer_adapter_remains_specific(self):
        p=Path('/repo');cmd=command_for(p,Path('/private'),'dalaai-controls-ci-1234567890abcdef',str(p/'tests/e2e/c113_observe.py'),[MASTER,EXECUTOR],manifest())
        self.assertEqual(cmd[-7:],['exec','-T','observer','python','/ci/controls_observer_in_container.py',MASTER,EXECUTOR])
        self.assertNotIn('password',' '.join(cmd))
        for script in ('c112_observe.py','c113_inspect_download.py'):
            with self.assertRaises(ValueError):command_for(p,Path('/private'),'dalaai-controls-ci-1234567890abcdef',str(p/'tests/e2e'/script),[MASTER,EXECUTOR],manifest())
    def test_observer_rejects_swapped_public_ids(self):
        with self.assertRaises(ValueError):command_for(Path('/repo'),Path('/private'),'dalaai-controls-ci-1234567890abcdef','/repo/tests/e2e/c113_observe.py',[EXECUTOR,MASTER],manifest())
    def test_diagnostic_excludes_raw_values_and_bounds_counts(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'e.json';p.write_text(json.dumps({'steps':[{'name':STEPS[0],'result':'PASS'},{'name':STEPS[1],'result':'FAIL'}],
                'clock':['CANARY']*90,'downloads':['CANARY']*99,'restrictions':['CANARY']*88,'raw':'CANARY'}))
            result=failure_projection(Path(d)/'none',p)
            self.assertEqual((result['completed_steps'],result['failed_step'],result['clock_observations'],result['downloads'],result['restrictions']),(1,2,6,4,6))
            self.assertNotIn('CANARY',json.dumps(result))
    def test_file_presence_has_only_eight_fixed_booleans(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'saved-shift.pdf').write_bytes(b'CANARY');(p/'expected-shift-pdf.json').write_text('CANARY')
            (p/'private-secret').write_text('CANARY')
            result=file_presence(p)
            self.assertEqual(len(result),8);self.assertTrue(result['shift_pdf_saved']);self.assertTrue(result['shift_pdf_expected'])
            self.assertTrue(all(type(v) is bool for v in result.values()))
            self.assertNotIn('CANARY',json.dumps(result));self.assertNotIn(d,json.dumps(result));self.assertNotIn('private-secret',json.dumps(result))
    def test_file_presence_does_not_follow_links(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'target').write_text('CANARY');(p/'saved-order.xlsx').symlink_to(p/'target')
            self.assertFalse(file_presence(p)['order_xlsx_saved'])
    def test_c_download_phase_retains_only_fixed_categories(self):
        row={'target':'SHIFT_PDF','substep':'RUN_INSPECTOR','response':'HTTP_OK','encoding':'IDENTITY',
             'content_length':'POSITIVE_WITHIN_LIMIT','inspector':'PDF_CONTENT',
             'frontend_before_body':'LOADING','frontend_after_body':'READY','body_failure':'NOT_OBSERVED',
             'request_before_body':{'completion':'NOT_OBSERVED','failure_present':False},
             'request_after_body':{'completion':'FINISHED','failure_present':False}}
        self.assertEqual(download_projection(row),row)
    def test_c_download_phase_drops_raw_or_malformed_values(self):
        row={'target':'CANARY','substep':{'secret':'CANARY'},'response':200,'encoding':'secret-CANARY',
             'content_length':12345,'inspector':'CANARY','raw_header':'CANARY'}
        result=download_projection(row)
        self.assertEqual(set(result),{'target','substep','response','encoding','content_length','inspector',
            'frontend_before_body','frontend_after_body','body_failure','request_before_body','request_after_body'})
        self.assertNotIn('CANARY',json.dumps(result));self.assertNotIn('12345',json.dumps(result))
        self.assertEqual(result['content_length'],'INVALID')
    def test_request_projection_rejects_raw_failure_and_non_boolean_values(self):
        result=request_projection({'completion':'FAILED','failure_present':True,'errorText':'CANARY','url':'CANARY'})
        self.assertEqual(result,{'completion':'FAILED','failure_present':True})
        self.assertNotIn('CANARY',json.dumps(result))
        for value in (None,'CANARY',[],{'completion':['CANARY'],'failure_present':1},
                      {'completion':'CANARY','failure_present':'CANARY'}):
            self.assertEqual(request_projection(value),{'completion':'NOT_OBSERVED','failure_present':False})
    def test_body_and_ui_projection_rejects_raw_exception_and_dom_values(self):
        result=download_projection({'body_failure':'CANARY','frontend_before_body':{'text':'CANARY'},
            'frontend_after_body':'CANARY','request_after_body':{'completion':'CANARY','failure_present':'CANARY'},
            'message':'CANARY','stack':'CANARY','dom':'CANARY'})
        self.assertEqual(result['body_failure'],'OTHER')
        self.assertEqual(result['frontend_before_body'],'NOT_OBSERVED')
        self.assertEqual(result['frontend_after_body'],'NOT_OBSERVED')
        self.assertNotIn('CANARY',json.dumps(result))
    def test_all_fixed_body_failure_classes_are_preserved_without_promotion(self):
        for category in ('NOT_OBSERVED','TIMEOUT','BODY_PROTOCOL_FAILURE','BODY_UNAVAILABLE','TARGET_CLOSED','OTHER'):
            result=download_projection({'body_failure':category,'frontend_after_body':'READY',
                'request_after_body':{'completion':'FINISHED','failure_present':False}})
            self.assertEqual(result['body_failure'],category)
            self.assertNotIn('status',result);self.assertNotIn('result',result)
    def test_failure_evidence_keeps_body_categories_and_never_raw_fields(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'e.json';p.write_text(json.dumps({'download_diagnostic':{
                'body_failure':'BODY_PROTOCOL_FAILURE','frontend_after_body':'READY',
                'request_after_body':{'completion':'FINISHED','failure_present':False,'errorText':'CANARY'},
                'message':'CANARY'}}))
            result=failure_projection(Path(d)/'none',p)
            self.assertEqual(result['scope'],'diagnostic_only_no_controls_pass')
            self.assertEqual(result['download_phase']['body_failure'],'BODY_PROTOCOL_FAILURE')
            self.assertEqual(result['download_phase']['frontend_after_body'],'READY')
            self.assertNotIn('CANARY',json.dumps(result))
    def test_fixed_error_locations_only(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'r.json';p.write_text(json.dumps({'errors':[{'message':'CANARY','location':{'file':'c113_download_clock.spec.cjs','line':141}}]}))
            result=failure_projection(p,Path(d)/'none')
            self.assertEqual(result['source_locations'],[{'file':'c113_download_clock.spec.cjs','line':141}]);self.assertNotIn('CANARY',json.dumps(result))

if __name__=='__main__':unittest.main()
