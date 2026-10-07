"""Verify committed offline samples against their manifest and pinned source."""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import unittest

import c4_c1_history_report as adapter


class Tags(HTMLParser):
    def __init__(self,source):
        super().__init__();self.tags=[];self.attrs=[];self.feed(source)
    def handle_starttag(self,tag,attrs):
        self.tags.append(tag);self.attrs.extend(attrs)


class C1Artifacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder=Path(__file__).with_name('c1-demo')
        cls.manifest=json.loads((cls.folder/'manifest.json').read_text())
        cls.trace=json.loads((cls.folder/'report-source-trace.json').read_text())

    def test_artifact_bytes_and_source_provenance(self):
        for filename,metadata in self.manifest['artifacts'].items():
            raw=(self.folder/filename).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(),metadata['sha256'])
            self.assertEqual(len(raw),metadata['bytes'])
        self.assertEqual(self.manifest['source_history_sha256'],adapter.SOURCE_HASH)
        self.assertEqual(self.trace['source_commit'],adapter.HISTORICAL_EXPORT_COMMIT)
        self.assertEqual(self.trace['coverage']['as_of'],adapter.END)

    def test_selected_source_rows_are_original_and_photos_only_placeholders(self):
        history,_=adapter.load_history()
        selected=self.trace['order']
        self.assertEqual(selected['order_events'],[e for e in history['order_events'] if e['order_id']==adapter.DEMO_ORDER])
        self.assertEqual(len(selected['submissions']),2)
        self.assertIsNone(selected['submissions'][1]['reviews'][0]['final_score'])
        self.assertTrue(all(s['assessments']==[] for s in selected['submissions']))
        self.assertTrue(all(p['artifact_available'] is False for p in selected['photo_placeholders']))
        self.assertEqual(len(self.trace['shift_summary']['closed_order_ids']),23)

    def test_html_discloses_level_and_has_no_active_or_external_content(self):
        for name in ['order-521.html','period-september-27-30.html']:
            html=(self.folder/name).read_text()
            tags=Tags(html)
            self.assertNotIn('script',tags.tags)
            self.assertNotIn('img',tags.tags)
            self.assertFalse(any(k in ('href','src') or k.startswith('on') for k,v in tags.attrs))
            for marker in ['СИНТЕТИЧЕСКИЙ АВТОНОМНЫЙ ПРИМЕР',adapter.HISTORICAL_EXPORT_COMMIT,adapter.SOURCE_HASH,'image bytes отсутствуют','AI assessments отсутствуют']:
                self.assertIn(marker,html)
        html=(self.folder/'order-521.html').read_text()
        for s in self.trace['order']['submissions']:
            self.assertIn(s['id'],html)
            self.assertIn(s['reviews'][0]['id'],html)


if __name__=='__main__':
    unittest.main()
