"""Capability settings stay independent from external delivery activation."""
import os
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import create_app
from app.runtime import RuntimeSettings

class WorkerIntegrationConfigTests(unittest.TestCase):
    def test_real_channel_requires_installed_notification_capability(self):
        with self.assertRaises(ValueError):
            RuntimeSettings(delivery_channel='web_push')
        with self.assertRaises(ValueError):
            RuntimeSettings(notification_enabled=True)

    def test_invalid_capability_flag_cannot_silently_downgrade(self):
        with patch.dict(os.environ,{'DALA_PUSH_CAPABILITY':'yes'},clear=True),self.assertRaises(ValueError):
            RuntimeSettings.from_env()

    def test_push_routes_mount_and_full_profile_validates_while_provider_paused(self):
        settings=RuntimeSettings(mode='demo',database_url='synthetic-not-used',
            allowed_origin='https://naryadai.test',notification_enabled=True,
            push_enabled=True,delivery_channel='web_push')
        def forbidden():raise AssertionError('No request may use a DB without authentication')
        with patch.dict(os.environ,{'DALA_WEB_PUSH_ENABLED':'false'},clear=True),patch('app.main.validate_database') as check:
            with TestClient(create_app(settings=settings,connect=forbidden),base_url=settings.allowed_origin) as client:
                self.assertEqual(client.get('/api/v1/push/config').status_code,401)
                check.assert_called_once_with(forbidden,photo_enabled=False,notification_enabled=True,push_enabled=True)

if __name__=='__main__':unittest.main()
