"""Profile binding preserves existing minimal receipts and never guesses a mode."""
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'ops/provision')]
from enable_worker_capabilities import selected_fixture, capability_fingerprint
from prepare_demo_database import worker_migration_plan

class FixtureModeTests(unittest.TestCase):
    def test_minimal_fingerprint_matches_previous_release(self):
        mode, _, manifest=selected_fixture({})
        self.assertEqual(mode,'minimal');self.assertIsNone(manifest)
        actual=capability_fingerprint(worker_migration_plan(ROOT/'backend'),
            owner_role='owner',api_role='api',worker_role='worker',fixture_manifest=manifest)
        self.assertEqual(actual,'2db9177be2d0c012a8228727e7528820f309e89c379ffa43a23cdcc897075908')

    def test_history_scope_and_source_are_bound_to_a_distinct_profile(self):
        mode, _, manifest=selected_fixture({'DALA_DEMO_FIXTURE_MODE':'history'})
        self.assertEqual(mode,'history');self.assertEqual(manifest['history_orders'],540)
        self.assertEqual([len(u['section_ids']) for u in manifest['users']],[4,1])
        plan=worker_migration_plan(ROOT/'backend')
        common=dict(owner_role='owner',api_role='api',worker_role='worker')
        self.assertNotEqual(capability_fingerprint(plan,**common),
                            capability_fingerprint(plan,**common,fixture_manifest=manifest))

    def test_unknown_or_empty_mode_is_never_minimal_fallback(self):
        for value in ('','History','production','auto',None):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'WORKER_FIXTURE_MODE_INVALID'):
                selected_fixture({'DALA_DEMO_FIXTURE_MODE':value})

if __name__=='__main__':unittest.main()
