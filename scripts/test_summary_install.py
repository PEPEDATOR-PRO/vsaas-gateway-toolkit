import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import install


class SummaryInstallTests(unittest.TestCase):
    def test_summary_installs_assets_before_reapplying_overlay(self):
        profile=json.loads((install.ROOT/'config/equipo.example.json').read_text())
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch.object(install,'ROOT',root),patch.object(install,'CONFIG_DIR',root/'etc'),patch.object(install,'load_profile',return_value=profile),patch.object(install.os,'geteuid',return_value=0,create=True),patch.object(install.sys,'platform','linux'),patch.object(install.sys,'argv',['install.py','resumen']),patch.object(install.subprocess,'run') as run,contextlib.redirect_stdout(io.StringIO()):
                install.main()
            self.assertEqual(run.call_count,2)
            self.assertEqual(run.call_args.args[0],['bash',str(root/'dist/instalar-resumen-general.sh')])
            self.assertFalse((root/'etc/config.json').exists())

    def test_summary_does_not_load_or_write_device_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch.object(install,'ROOT',root),patch.object(install,'load_profile',side_effect=AssertionError('Profile must not be read')),patch.object(install.os,'geteuid',return_value=0,create=True),patch.object(install.sys,'platform','linux'),patch.object(install.sys,'argv',['install.py','resumen']),patch.object(install.subprocess,'run') as run,contextlib.redirect_stdout(io.StringIO()):
                install.main()
            self.assertEqual(run.call_count,2)

    def test_summary_dry_run_without_profile(self):
        with patch.object(install,'load_profile',side_effect=AssertionError('Profile must not be read')),patch.object(install.sys,'argv',['install.py','resumen','--dry-run']),patch.object(install.subprocess,'run') as run,contextlib.redirect_stdout(io.StringIO()):
            install.main()
        run.assert_not_called()


if __name__=='__main__':unittest.main()
