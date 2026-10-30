import copy
import json
from pathlib import Path
import tempfile
import unittest
from profile import load_profile
from install import plan

EXAMPLE=json.loads((Path(__file__).resolve().parents[1]/'config/equipo.example.json').read_text())


class ProfileTests(unittest.TestCase):
    def validate(self,data,ready=True):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'equipo.json';path.write_text(json.dumps(data))
            return load_profile(path,ready=ready)

    def test_example_is_accepted_only_for_preview(self):
        self.assertEqual(self.validate(EXAMPLE,ready=False)['lan_interface'],'eth0')
        with self.assertRaises(ValueError):self.validate(EXAMPLE)

    def test_ready_profile_is_valid(self):
        data=copy.deepcopy(EXAMPLE);data['vpn_id']='EQUIPO_002';data['vpn_server']='198.51.100.20'
        self.assertEqual(self.validate(data)['vpn_id'],'EQUIPO_002')

    def test_credential_fields_are_rejected(self):
        data=copy.deepcopy(EXAMPLE);data['psk']='not-a-real-secret'
        with self.assertRaises(ValueError):self.validate(data,ready=False)

    def test_broadcast_cannot_be_admin_address(self):
        data=copy.deepcopy(EXAMPLE);data['vpn_admin_ip']='10.254.0.7'
        with self.assertRaises(ValueError):self.validate(data,ready=False)

    def test_subnets_must_not_overlap(self):
        data=copy.deepcopy(EXAMPLE);data['vpn_remote_subnet']='10.254.0.0/24'
        with self.assertRaises(ValueError):self.validate(data,ready=False)

    def test_shell_metacharacters_cannot_be_an_identifier(self):
        data=copy.deepcopy(EXAMPLE);data['vpn_id']='item;touch /tmp/unsafe'
        with self.assertRaises(ValueError):self.validate(data,ready=False)

    def test_standard_install_does_not_start_a_24_hour_experiment(self):
        self.assertEqual(plan('todo',EXAMPLE),['vpn','ssh','cockpit','paneles'])
        self.assertNotIn('observacion',plan('todo',EXAMPLE))

    def test_overview_adaptation_is_an_explicit_profile_option(self):
        data=copy.deepcopy(EXAMPLE);data['overview_overlay']=True
        self.assertEqual(plan('todo',data)[-1],'resumen')


if __name__=='__main__':unittest.main()
