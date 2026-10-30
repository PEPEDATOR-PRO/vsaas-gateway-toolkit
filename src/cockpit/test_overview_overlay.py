import contextlib
import gzip
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('overlay',Path(__file__).with_name('install-overview-overlay.py'))
overlay=importlib.util.module_from_spec(spec)
spec.loader.exec_module(overlay)
HTML='''<!doctype html><html><head><script src="../base1/cockpit.js"></script><script src="overview.js"></script></head><body><div id="overview"></div></body></html>'''


class OverlayTests(unittest.TestCase):
    def test_injection_preserves_native_scripts_and_root(self):
        html=overlay.inject_html(HTML)
        self.assertIn('src="overview.js"',html)
        self.assertIn('id="overview"',html)
        self.assertEqual(html.count('overview-cards.js'),1)
        self.assertEqual(html.count('base1/cockpit.js'),1)

    def test_unknown_native_layout_is_not_modified(self):
        with self.assertRaises(RuntimeError):overlay.inject_html('<html><head></head><body>Changed page</body></html>')

    def test_compressed_native_index_is_supported(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder);(source/'index.html.gz').write_bytes(gzip.compress(HTML.encode()))
            self.assertEqual(overlay.read_index(source),HTML)

    def test_overlay_does_not_modify_native_package(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);source=base/'native';source.mkdir();resources=base/'resources';resources.mkdir();destination=base/'vsaas_system'
            (source/'index.html').write_text(HTML);(source/'overview.js').write_text('native-code')
            for resource in ['overview-cards.js','overview-cards.css']:(resources/resource).write_text('resource')
            manifest={'name':'system','menu':{'index':{'label':'Overview'},'services':{'label':'Services'}},'tools':{'terminal':{'label':'Terminal'}}}
            (source/'manifest.json').write_text(json.dumps(manifest))
            # Windows may disallow symlinks; check link intent separately here.
            with patch.object(overlay,'source_package',return_value=(source,dict(manifest))),patch.object(overlay,'OVERLAY',destination),patch.object(overlay,'RESOURCES',resources),patch.object(overlay,'BACKUPS',base/'backups'),patch.object(Path,'symlink_to') as link,contextlib.redirect_stdout(io.StringIO()):
                overlay.install()
            link.assert_called_once_with(source/'overview.js',target_is_directory=False)
            self.assertEqual((source/'index.html').read_text(),HTML)
            result=json.loads((destination/'manifest.json').read_text())
            self.assertEqual(result['menu'],manifest['menu']);self.assertEqual(result['tools'],manifest['tools']);self.assertGreater(result['priority'],0)
            self.assertTrue((destination/overlay.MARKER).is_file())


if __name__=='__main__':unittest.main()
