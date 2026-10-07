import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from startup_diagnostics import classify, safe_inventory


class StartupDiagnosticTests(unittest.TestCase):
    def test_only_fixed_error_classes_escape(self):
        raw=b'private-password-value open /run/ci-tls/server.key: permission denied; secret-token-value'
        result=classify(raw)
        self.assertEqual(result,['FILE_PERMISSION_DENIED','CI_TLS_FILE_UNREADABLE'])
        self.assertNotIn('private-password',json.dumps(result))
        self.assertNotIn('secret-token',json.dumps(result))

    def test_inventory_emits_only_known_enums_and_numeric_exit(self):
        result=safe_inventory(json.dumps([{'Service':'web','State':'exited','Health':'','ExitCode':1,
                                          'Command':'secret-password','Labels':{'token':'private'},'Status':'raw arbitrary status'}]).encode())
        self.assertEqual(result,[{'service':'web','state':'exited','health':'','exit_code':1}])

    def test_untrusted_names_and_values_are_not_emitted(self):
        result=safe_inventory(json.dumps([{'Service':'private-token','State':'running'},
            {'Service':'api','State':'private-password','Health':'private-csrf','ExitCode':'secret-token'}]).encode())
        self.assertEqual(result,[{'service':'api','state':'unknown','health':'unknown','exit_code':None}])

    def test_json_lines_inventory_is_supported(self):
        self.assertEqual(safe_inventory(b'{"Service":"db","State":"running","Health":"healthy","ExitCode":0}\n')[0]['service'],'db')


if __name__ == '__main__': unittest.main()
