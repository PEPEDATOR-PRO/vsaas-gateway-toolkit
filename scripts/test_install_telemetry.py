import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import install
import install_telemetry


class TelemetryInstallTests(unittest.TestCase):
    def test_module_needs_no_profile(self):
        with patch.object(install.sys, 'argv', ['install.py', 'telemetria']), patch.object(install, 'load_profile', side_effect=AssertionError('No profile')), patch.object(install.subprocess, 'run') as run:
            install.main()
        self.assertEqual(run.call_count, 1)
        self.assertIn('install_telemetry.py', str(run.call_args.args[0]))

    def test_installer_preserves_configuration_and_starts_disabled(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.multiple(install_telemetry, LIBEXEC=root/'libexec', CONFIG=root/'etc/telemetria.json', PORTAL=root/'portal', UNITS=root/'units'), patch.object(install_telemetry.os, 'geteuid', return_value=0, create=True), patch.object(install_telemetry.sys, 'platform', 'linux'), patch.object(install_telemetry.shutil, 'which', return_value='/fake/cockpit'), patch.object(install_telemetry.subprocess, 'run') as run, contextlib.redirect_stdout(io.StringIO()):
                install_telemetry.install()
                first = json.loads((root/'etc/telemetria.json').read_text())
                self.assertFalse(first['enabled'])
                self.assertEqual(first['destinations'], [])
                first['enabled'] = True
                (root/'etc/telemetria.json').write_text(json.dumps(first))
                install_telemetry.install()
                self.assertEqual(json.loads((root/'etc/telemetria.json').read_text()), first)
                self.assertEqual(run.call_count, 6)


if __name__ == '__main__':
    unittest.main()
