"""No real credentials/containers: exercise file safety with deterministic doubles."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

path=Path(__file__).resolve().parents[1]/'prepare.py'
spec=importlib.util.spec_from_file_location('demo_prepare',path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class PrivateBootstrapTests(unittest.TestCase):
    def test_preserves_credentials_and_prints_no_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)/'private';output=io.StringIO()
            with patch.object(module.secrets,'token_urlsafe',return_value='SYNTHETIC_'+'x'*34),patch.object(module.secrets,'randbelow',side_effect=[12345678,87654321]),contextlib.redirect_stdout(output):
                module.prepare(directory,'localhost','127.0.0.1',8080,8443)
                before={p.name:p.read_bytes() for p in directory.iterdir()}
                module.prepare(directory,'localhost','127.0.0.1',8080,8443)
            self.assertEqual(before,{p.name:p.read_bytes() for p in directory.iterdir()})
            self.assertNotIn('SYNTHETIC_',output.getvalue());self.assertNotIn('12345678',output.getvalue());self.assertNotIn('87654321',output.getvalue())
            self.assertEqual(directory.stat().st_mode&0o777,0o700)
            self.assertTrue(all(p.stat().st_mode&0o777==0o444 for p in directory.iterdir()))
            self.assertIn('DALA_ALLOWED_ORIGIN=https://localhost:8443',before['env'].decode())
            with self.assertRaises(ValueError):module.prepare(directory,'changed.test','127.0.0.1',8080,8443)
    def test_refuses_symlink_directory_or_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'target';target.mkdir(mode=0o700)
            link=Path(tmp)/'link';link.symlink_to(target)
            with self.assertRaises(ValueError):module.prepare(link,'localhost','127.0.0.1',8080,8443)
            config=target/'master_pin';config.symlink_to(Path(tmp)/'absent')
            with self.assertRaises((ValueError,FileExistsError)):module.save_once(config,'synthetic')
    def test_rejects_shell_or_url_injection_before_any_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            for host in ('https://site.test','x;touch bad','*.test','a.test/path','a..test','a.test:443'):
                target=Path(tmp)/'not-created'
                with self.assertRaises(ValueError):module.prepare(target,host,'127.0.0.1',8080,8443)
                self.assertFalse(target.exists())

if __name__=='__main__':unittest.main()
