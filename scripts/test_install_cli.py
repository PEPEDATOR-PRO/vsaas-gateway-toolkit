import subprocess
import unittest
from unittest.mock import patch
import install


class InstallErrorTests(unittest.TestCase):
    def test_apt_error_explains_recovery_without_exposing_command(self):
        with patch.object(install, 'main', side_effect=subprocess.CalledProcessError(100, ['private-command', 'synthetic-private-path'])):
            with self.assertRaises(SystemExit) as caught:
                install.cli()
        message = str(caught.exception)
        self.assertIn('unattended-upgrades', message)
        self.assertIn('No borres', message)
        self.assertNotIn('private', message)

    def test_other_failure_is_not_mislabeled_as_apt(self):
        with patch.object(install, 'main', side_effect=subprocess.CalledProcessError(2, ['synthetic-command'])):
            with self.assertRaises(SystemExit) as caught:
                install.cli()
        self.assertIn('código 2', str(caught.exception))
        self.assertNotIn('dpkg', str(caught.exception))
