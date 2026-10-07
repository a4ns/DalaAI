"""Pure observer-input tests: no DB, private file, browser or real login."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('c110_observe', Path(__file__).with_name('c110_observe.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ObserverInputTests(unittest.TestCase):
    def environment(self):
        return {'DALA_C110_AUTHORIZED': 'operator-provisioned-synthetic-only',
                'DALA_C110_DATABASE_SCHEMA': 'c110_parser_only',
                'DALA_C110_OBSERVER_DATABASE_URL': 'postgresql://unit:nonsecret-dummy@localhost/unit'}

    def test_accepts_loopback_explicit_input_without_connecting(self):
        self.assertEqual(module.validate_environment(self.environment())[1], 'c110_parser_only')

    def test_denies_public_schema_or_implicit_credential_files(self):
        for uri in ('postgresql://unit@localhost/unit', 'postgresql://unit:dummy@example.org/unit',
                    'postgresql://unit:dummy@localhost/unit?passfile=/private',
                    'postgresql://unit:dummy@localhost/unit?service=private',
                    'postgresql://unit:dummy@localhost/unit?host=public.example'):
            environment = self.environment(); environment['DALA_C110_OBSERVER_DATABASE_URL'] = uri
            with self.assertRaises(module.Blocked): module.validate_environment(environment)
        environment = self.environment(); environment['DALA_C110_DATABASE_SCHEMA'] = 'public'
        with self.assertRaises(module.Blocked): module.validate_environment(environment)

    def test_inherited_libpq_file_or_auth_overrides_are_rejected(self):
        for name in ('PGSERVICE', 'PGSERVICEFILE', 'PGPASSFILE', 'PGPASSWORD', 'PGSSLCERT', 'PGSSLKEY', 'PGHOST'):
            environment = self.environment(); environment[name] = 'nonsecret-unit-sentinel'
            with self.assertRaises(module.Blocked): module.validate_environment(environment)

    def test_authorization_and_schema_validation_are_fail_closed(self):
        with self.assertRaises(module.Blocked): module.validate_environment({})
        environment = self.environment(); environment['DALA_C110_DATABASE_SCHEMA'] = 'schema; SELECT 1'
        with self.assertRaises(module.Blocked): module.validate_environment(environment)


if __name__ == '__main__':
    unittest.main()
