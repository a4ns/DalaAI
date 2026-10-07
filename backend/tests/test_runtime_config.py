"""Configuration and failure wiring only; real mounted runtime needs PG gate."""
import os
import unittest
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from app.main import create_app
from app.runtime import RuntimeSettings, connection_factory

class RuntimeConfigTests(unittest.TestCase):
    def test_health_is_default_and_has_no_domain_routes(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = RuntimeSettings.from_env()
            self.assertEqual(settings.mode,'health')
            with TestClient(create_app(settings=settings)) as client:
                self.assertEqual(client.get('/api/v1/me').status_code,404)

    def test_demo_is_explicit_and_dsn_is_never_repr(self):
        for kwargs in ({'mode':'production'}, {'mode':'demo'},
                       {'mode':'demo','database_url':'synthetic','allowed_origin':'http://example.test'},
                       {'database_schema':'public;DROP TABLE orders'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                RuntimeSettings(**kwargs)
        settings = RuntimeSettings('demo','private-marker','https://example.test')
        self.assertNotIn('private-marker',repr(settings))

    def test_invalid_environment_does_not_silently_fall_back(self):
        with patch.dict(os.environ,{'DALA_API_MODE':'typo'},clear=True), self.assertRaises(ValueError):
            create_app()

    def test_demo_cannot_serve_without_startup(self):
        settings = RuntimeSettings('demo','synthetic','https://example.test')
        connector = Mock(side_effect=RuntimeError('private-connection-error'))
        app = create_app(settings=settings,connect=connector)
        client = TestClient(app,base_url='https://example.test')
        self.assertEqual(client.get('/api/v1/me').status_code,503)
        self.assertEqual(client.get('/readyz').status_code,503)
        self.assertEqual(client.get('/healthz').status_code,200)
        connector.assert_not_called()

    def test_failed_database_startup_does_not_leak_driver_details(self):
        settings = RuntimeSettings('demo','synthetic','https://example.test')
        connector = Mock(side_effect=RuntimeError('private-connection-error'))
        with self.assertRaisesRegex(RuntimeError,'^Runtime database prerequisites failed$'):
            with TestClient(create_app(settings=settings,connect=connector),base_url='https://example.test'):
                self.fail('Startup should reject absent prerequisites')

    def test_connection_settings_have_bounded_timeouts_and_explicit_schema(self):
        settings = RuntimeSettings('demo','synthetic','https://example.test','test_schema')
        with patch('psycopg.connect') as connect:
            connection_factory(settings)()
            options = connect.call_args.kwargs
            self.assertTrue(options['autocommit'])
            self.assertEqual(options['connect_timeout'],3)
            self.assertIn('search_path=test_schema',options['options'])
            self.assertIn('lock_timeout=5000',options['options'])
            self.assertIn('statement_timeout=10000',options['options'])

    def test_route_inventory_is_real_factory_without_docs(self):
        settings = RuntimeSettings('demo','synthetic','https://example.test')
        app = create_app(settings=settings,connect=Mock())
        from fastapi.testclient import TestClient
        client = TestClient(app,base_url='https://example.test')
        self.assertEqual(client.get('/docs').status_code,404)
        self.assertFalse(app.dependency_overrides)
        self.assertFalse(app.state.runtime_ready)


    def test_readiness_timeout_latches_api_closed_even_after_thread_finishes(self):
        import time
        settings=RuntimeSettings('demo','synthetic','https://example.test')
        calls=[]
        def validation(connect):
            calls.append(True)
            if len(calls)>1:
                time.sleep(0.08)
        with patch('app.main.validate_database',validation), patch('app.health.READINESS_TIMEOUT_SECONDS',0.01):
            app=create_app(settings=settings,connect=Mock())
            with TestClient(app,base_url='https://example.test') as client:
                self.assertTrue(app.state.runtime_ready)
                self.assertEqual(client.get('/readyz').status_code,503)
                self.assertFalse(app.state.runtime_ready)
                response=client.get('/api/v1/me')
                self.assertEqual(response.status_code,503)
                self.assertEqual(response.json()['code'],'TEMPORARILY_UNAVAILABLE')
                self.assertEqual(response.headers['retry-after'],'1')
                time.sleep(0.1)
                self.assertFalse(app.state.runtime_ready)
