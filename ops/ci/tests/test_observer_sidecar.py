from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from observer_python import command_for


class ObserverSidecarTests(unittest.TestCase):
    def test_exact_script_uuid_and_service_only(self):
        root=Path('/repo'); uuid='00000000-0000-0000-0000-000000000000'
        command=command_for(root,'dalaai-ci-1234567890abcdef',str(root/'tests/e2e/c110_observe.py'),uuid)
        self.assertEqual(command[-6:],['exec','-T','observer','python','/ci/observer_in_container.py',uuid])
        self.assertNotIn('dsn',' '.join(command).lower())
        self.assertNotIn('password',' '.join(command).lower())

    def test_other_script_and_real_project_are_rejected(self):
        for project,script,order in [('dalaai-demo','/repo/tests/e2e/c110_observe.py','0'*32),
            ('dalaai-ci-1234567890abcdef','/bin/sh','0'*32),
            ('dalaai-ci-1234567890abcdef','/repo/tests/e2e/c110_observe.py','; echo bad')]:
            with self.assertRaises(ValueError): command_for(Path('/repo'),project,script,order)


if __name__=='__main__': unittest.main()
