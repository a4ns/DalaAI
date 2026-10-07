"""Runner safety/metadata tests; full immutable source-only replay is separate."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('offline_runner', Path(__file__).with_name('offline_runner.py'))
r = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(r)


class OfflineRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sources = self.root / 'sources'; self.sources.mkdir()
        self.manifest = {'schema_version': 1, 'packages': {}}
        for name in ('C1', 'C2', 'C3', 'C4'):
            data = (name + '\n').encode(); (self.sources / name).write_bytes(data)
            self.manifest['packages'][name] = {'source_sha': '1' * 40, 'files': {name: hashlib.sha256(data).hexdigest()}}
        self.pin = self.root / 'pin.json'; self.pin.write_text(json.dumps(self.manifest))

    def test_complete_exact_source_set(self):
        self.assertEqual(len(r.verify_sources(self.sources, self.manifest)), 4)

    def test_missing_package_blocks_before_execution(self):
        (self.sources / 'C3').unlink()
        code, report = r.run(self.sources, self.root / 'result', self.pin)
        self.assertEqual((code, report['status']), (2, 'BLOCKED'))
        self.assertEqual(report['stages'], [])
        self.assertTrue(all(value == 'NOT_RUN' for value in report['product_gates'].values()))
        self.assertIn('C3', report['reason'])

    def test_modified_source_is_not_executed(self):
        (self.sources / 'C1').write_text('print("not executed")')
        with self.assertRaisesRegex(r.Blocked, 'hash mismatch'):
            r.verify_sources(self.sources, self.manifest)

    def test_symlink_source_rejected(self):
        target = self.root / 'outside'; target.write_text('C1\n')
        (self.sources / 'C1').unlink(); (self.sources / 'C1').symlink_to(target)
        with self.assertRaisesRegex(r.Blocked, 'symlink'):
            r.verify_sources(self.sources, self.manifest)

    def test_parent_traversal_and_absolute_path_rejected(self):
        for path in ('../outside', '/outside'):
            with self.subTest(path=path), self.assertRaises(r.Blocked):
                r.checked_file(self.sources, path)

    def test_duplicate_ownership_rejected(self):
        self.manifest['packages']['C2']['files'] = dict(self.manifest['packages']['C1']['files'])
        with self.assertRaisesRegex(r.Blocked, 'duplicate source'):
            r.verify_sources(self.sources, self.manifest)

    def test_missing_package_manifest_rejected(self):
        del self.manifest['packages']['C4']
        with self.assertRaises(r.Blocked):
            r.verify_sources(self.sources, self.manifest)

    def test_invalid_commit_or_empty_package_rejected(self):
        self.manifest['packages']['C1']['source_sha'] = 'main'
        with self.assertRaises(r.Blocked):
            r.verify_sources(self.sources, self.manifest)
        self.manifest['packages']['C1']['source_sha'] = '1' * 40
        self.manifest['packages']['C1']['files'] = {}
        with self.assertRaises(r.Blocked):
            r.verify_sources(self.sources, self.manifest)

    def test_existing_output_preserved(self):
        output = self.root / 'result'; output.mkdir(); marker = output / 'keep'; marker.write_text('original')
        with self.assertRaisesRegex(r.Blocked, 'already exists'):
            r.run(self.sources, output, self.pin)
        self.assertEqual(marker.read_text(), 'original')
        self.assertEqual(list(output.iterdir()), [marker])

    def test_output_symlink_rejected(self):
        output = self.root / 'result'; output.symlink_to(self.sources, target_is_directory=True)
        with self.assertRaises(r.Blocked):
            r.run(self.sources, output, self.pin)
        self.assertEqual(len(list(self.sources.iterdir())), 4)

    def test_unit_count_rejects_skips_missing_and_failure(self):
        self.assertEqual(r.unit_count('\nRan 22 tests in 0.1s\n\nOK\n'), 22)
        for text in ('\nRan 22 tests in 0.1s\nOK (skipped=1)\n', 'OK\n', '\nRan 2 tests in 1s\nFAILED (errors=1)\n', '\nRan 0 tests in 0.1s\nOK\n'):
            with self.assertRaises(ValueError):
                r.unit_count(text)

    def test_active_or_external_html_is_rejected(self):
        for text in ('<script>bad()</script>', '<img src="https://example.invalid">', '<a href="x">x</a>', '<div onclick="x">', '<iframe></iframe>', '<svg><use xlink:href="x"></use></svg>', '<style>@import "x";</style>', '<style>@import url(https://example.invalid/track.css);</style>', '<svg><image xlink:href="https://example.invalid/track.png" /></svg>', '<style>p { background: url(x) }</style>', '<p style="color:red">', '<style>p{background-image:image-set("https://example.invalid/x.png" 1x)}</style>', '<style>p{background-image:-webkit-image-set("https://example.invalid/x.png" 1x)}</style>', '<meta http-equiv="refresh" content="0;url=x">'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                r.InertHTML().feed(text)
        r.InertHTML().feed('<meta charset="UTF-8"><meta name="viewport" content="width=device-width"><h1>Синтетика</h1>')

    def test_unclosed_style_rejected_at_eof(self):
        parser = r.InertHTML()
        parser.feed('<style>p{background-image:image-set("https://example.invalid/x.png" 1x)}')
        with self.assertRaises(ValueError):
            parser.close()
        empty = r.InertHTML()
        empty.feed('<style>')
        with self.assertRaisesRegex(ValueError, 'unclosed'):
            empty.close()

    def test_private_source_paths_redacted_in_logs(self):
        result = r.clean_log('error /private/workspace/source/file.py', [(Path('/private/workspace/source'), '<WORK>')])
        self.assertEqual(result, 'error <WORK>/file.py')


if __name__ == '__main__':
    unittest.main(verbosity=2)
