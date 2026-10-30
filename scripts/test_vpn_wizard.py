import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import vpn_wizard as wizard


class WizardTests(unittest.TestCase):
    def test_only_two_prompts_and_no_secret_in_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'equipo.json'
            with patch('builtins.input',side_effect=['TEST_GATEWAY','10.254.8.0/29']) as prompt:
                result=wizard.configure(target)
            self.assertEqual(prompt.call_count,2)
            self.assertEqual(result['vpn_admin_ip'],'10.254.8.1')
            self.assertEqual(json.loads(target.read_text()),result)
            self.assertNotIn('psk',result)

    def test_preview_does_not_write(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'equipo.json'
            with patch('builtins.input',side_effect=['TEST_GATEWAY','10.254.8.0/29']):
                wizard.configure(target,write=False)
            self.assertFalse(target.exists())

    def test_invalid_data_does_not_replace_existing_profile(self):
        for identity,subnet in [('bad;id','10.254.8.0/29'),('TEST','10.254.8.1/29'),('TEST','10.254.8.0/32'),('TEST','172.31.0.0/24')]:
            with self.subTest(identity=identity,subnet=subnet),tempfile.TemporaryDirectory() as folder:
                target=Path(folder)/'equipo.json'
                original=(Path(wizard.__file__).resolve().parents[1]/'config/equipo.example.json').read_text()
                target.write_text(original)
                with patch('builtins.input',side_effect=[identity,subnet]),self.assertRaises(ValueError):
                    wizard.configure(target)
                self.assertEqual(target.read_text(),original)

    def test_non_vpn_preferences_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'equipo.json'
            data=json.loads((Path(wizard.__file__).resolve().parents[1]/'config/equipo.example.json').read_text())
            data.update(lan_interface='enp1s0',overview_overlay=True)
            target.write_text(json.dumps(data))
            with patch('builtins.input',side_effect=['TEST','10.254.8.0/29']):
                result=wizard.configure(target)
            self.assertEqual(result['lan_interface'],'enp1s0')
            self.assertTrue(result['overview_overlay'])


if __name__=='__main__':unittest.main()
