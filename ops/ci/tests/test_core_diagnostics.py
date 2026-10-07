import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core_diagnostics as diag


class CoreDiagnosticTests(unittest.TestCase):
    def test_progress_projection_never_echoes_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); report=root/'report.json'; evidence=root/'evidence.json'
            report.write_text(json.dumps({'errors':[], 'suites':[{'specs':[{'title':'private-pin', 'tests':[{'results':[{'errors':[{
                'message':'private-pin C110 BLOCKED: PostgreSQL observer unavailable; subprocess details suppressed private-token',
                'location':{'file':'/private-pin/c110_core.spec.cjs','line':137},
                'stack':'private-password at /private-token/c110_core.spec.cjs:137:12'
            }]}]}]}]}]}))
            evidence.write_text(json.dumps({'steps':[{'name':diag.STAGES[0],'result':'PASS'},{'name':diag.STAGES[1],'result':'FAIL'}],
                'commands':[{'action':'create','operation_id':'private-token'}], 'database':{'secret':'private-password'}}))
            out=diag.failure_projection(report,evidence)
            text=json.dumps(out)
            self.assertNotIn('private-',text)
            self.assertEqual(out['stages'],[{'stage_id':1,'result':'PASS'},{'stage_id':2,'result':'FAIL'}])
            self.assertEqual(out['committed_command_count'],1)
            self.assertEqual(out['error_classes'],['READONLY_OBSERVER_FAILED'])
            self.assertEqual(out['source_locations'],[{'file':'c110_core.spec.cjs','line':137}])

    def test_missing_report_stays_diagnostic_not_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=diag.failure_projection(Path(tmp)/'absent',None)
            self.assertEqual(out['report'],'unavailable')
            self.assertEqual(out['scope'],'diagnostic_only_no_core_pass')

    def test_unknown_dynamic_stage_and_location_are_not_emitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); report=root/'report.json'; evidence=root/'evidence.json'
            report.write_text(json.dumps({'errors':[{'message':'secret','location':{'file':'secret-file','line':200000}}], 'suites':[]}))
            evidence.write_text(json.dumps({'steps':[{'name':'secret-stage','result':'secret-result'}],'commands':[{'action':'secret-action'}]}))
            out=diag.failure_projection(report,evidence)
            self.assertNotIn('secret',json.dumps(out)); self.assertEqual(out['stages'],[])

    def test_working_filtered_python_needs_no_loader_override(self):
        with patch.object(diag.subprocess,'run') as run:
            run.return_value.returncode=0
            env={'PATH':'/trusted/bin'}
            actual,status=diag.python_environment(env)
            self.assertIs(actual,env); self.assertEqual(status,'PASS_FILTERED_ENV'); self.assertEqual(run.call_count,1)
            self.assertEqual(run.call_args.args[0][1:],['-c','import psycopg'])

    def test_loader_repair_uses_only_interpreter_own_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); lib=root/'lib'; lib.mkdir()
            with patch.object(diag.sys,'base_prefix',str(root)), patch.object(diag.sysconfig,'get_config_var',return_value=str(lib)), patch.object(diag.subprocess,'run') as run:
                run.side_effect=[type('R',(),{'returncode':1})(),type('R',(),{'returncode':0})()]
                env,status=diag.python_environment({'PATH':'/trusted/bin'})
                self.assertEqual(status,'PASS_INTERPRETER_OWN_LIBDIR_ONLY')
                self.assertEqual(env['LD_LIBRARY_PATH'],str(lib))
                self.assertNotIn('LD_PRELOAD',env)

    def test_library_outside_interpreter_prefix_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); lib=root/'untrusted'; lib.mkdir(); prefix=root/'python'; prefix.mkdir()
            with patch.object(diag.sys,'base_prefix',str(prefix)), patch.object(diag.sysconfig,'get_config_var',return_value=str(lib)), patch.object(diag.subprocess,'run') as run:
                run.return_value.returncode=1
                env,status=diag.python_environment({'PATH':'/trusted/bin'})
                self.assertEqual(status,'FAIL_PYTHON_OR_PSYCOPG_IMPORT'); self.assertEqual(run.call_count,1)
                self.assertNotIn('LD_LIBRARY_PATH',env)


if __name__=='__main__': unittest.main()
