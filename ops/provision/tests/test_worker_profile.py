import importlib.util
from pathlib import Path
import unittest

PATH=Path(__file__).resolve().parents[1]/'worker_profile.py'
spec=importlib.util.spec_from_file_location('worker_profile',PATH)
profile=importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


class WorkerProfileTests(unittest.TestCase):
    def test_render_only_and_disjoint_role(self):
        sql=profile.render_worker_profile(schema='demo',worker_role='demo_worker',api_role='demo_api')
        self.assertIn('GRANT INSERT ON "demo"."ai_assessments" TO "demo_worker";',sql)
        self.assertIn('GRANT UPDATE ("exif_removed") ON "demo"."photos"',sql)
        for forbidden in ('CREATE ROLE','ALTER ROLE','PASSWORD','ALL TABLES','ALL SEQUENCES','TO "demo_api"'):
            self.assertNotIn(forbidden,sql)
        with self.assertRaises(ValueError):
            profile.render_worker_profile(schema='demo',worker_role='same',api_role='same')

    def test_untrusted_identifier_rejected(self):
        for name in ('x;DROP TABLE orders','public.foo','CAPITAL','a"b','',None):
            with self.subTest(name=name),self.assertRaises(ValueError):
                profile.render_worker_profile(schema=name,worker_role='worker',api_role='api')

    def test_optional_profiles(self):
        sql=profile.render_worker_profile(schema='demo',worker_role='worker',api_role='api',
                                         notify_enabled=False,web_push=False)
        self.assertNotIn('push_subscriptions',sql)
        self.assertNotIn('auth_sessions',sql)
        self.assertNotIn('delivery_jobs',sql)
        sql=profile.render_worker_profile(schema='demo',worker_role='worker',api_role='api',
                                         ai_enabled=False,web_push=False)
        self.assertNotIn('ai_jobs',sql)
        self.assertNotIn('ai_assessments',sql)


if __name__=='__main__':unittest.main()
