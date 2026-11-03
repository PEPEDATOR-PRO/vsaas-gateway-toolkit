import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import vpn_wizard as wizard


class WizardTests(unittest.TestCase):
    def setUp(self):
        self.central=patch.object(wizard,'central_settings',return_value={'vpn_server':'198.51.100.20','vpn_remote_subnet':'172.20.0.0/16'})
        self.central.start();self.addCleanup(self.central.stop)

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
        for identity,subnet in [('bad;id','10.254.8.0/29'),('TEST','10.254.8.1/29'),('TEST','10.254.8.0/32'),('TEST','172.20.0.0/24')]:
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


class CentralSettingsTests(unittest.TestCase):
    def test_existing_device_central_settings_are_reused(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(wizard,'CENTRAL_CONFIG',Path(folder)/'absent.json'):
            data={'vpn_server':'10.200.0.1','vpn_remote_subnet':'172.20.0.0/16'}
            self.assertEqual(wizard.central_settings(data),data)

    def test_new_device_with_placeholder_stops_before_prompts(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(wizard,'CENTRAL_CONFIG',Path(folder)/'absent.json'),patch('builtins.input') as prompt:
            with self.assertRaises(ValueError):wizard.configure(Path(folder)/'equipo.json')
            prompt.assert_not_called()

    def test_local_central_config_overrides_profile_without_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'central.json';data={'vpn_server':'10.200.0.1','vpn_remote_subnet':'172.20.0.0/16'};path.write_text(json.dumps(data))
            with patch.object(wizard,'CENTRAL_CONFIG',path):
                self.assertEqual(wizard.central_settings({}),data)
                path.write_text(json.dumps({**data,'psk':'dummy-key'}))
                with self.assertRaises(ValueError):wizard.central_settings({})


if __name__=='__main__':unittest.main()
