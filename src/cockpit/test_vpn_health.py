import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('vpn_health',Path(__file__).with_name('vxg-health.py'))
health=importlib.util.module_from_spec(spec);spec.loader.exec_module(health)
SAMPLE='list-sa event {gateway {state=ESTABLISHED established=120 remote-id=not-exported child-sas {administracion-1 {name=administracion state=INSTALLED bytes-in=0 bytes-out=2048 packets-in=0 packets-out=2}}}}'


class VpnTests(unittest.TestCase):
    def query(self,text=SAMPLE,service='active'):
        with patch.object(health.Path,'exists',return_value=True),patch.object(health.shutil,'which',return_value='/usr/sbin/swanctl'),patch.object(health,'run',side_effect=[service,text]):
            return health.vpn_health()

    def test_connected_idle_tunnel_is_healthy_and_sanitized(self):
        result=self.query()
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['uptime_seconds'],120)
        self.assertEqual(result['rx_bytes'],0)
        self.assertEqual(result['tx_bytes'],2048)
        self.assertNotIn('not-exported',str(result))

    def test_ike_without_installed_child_is_partial(self):
        self.assertEqual(self.query(SAMPLE.replace('state=INSTALLED','state=REKEYING'))['status'],'warning')

    def test_no_session_is_disconnected(self):
        self.assertEqual(self.query('list-sa reply {}')['status'],'critical')

    def test_other_tunnels_do_not_make_gateway_healthy(self):
        self.assertEqual(self.query(SAMPLE.replace('event {gateway','event {other'))['status'],'critical')

    def test_query_failure_is_unknown(self):
        with patch.object(health.Path,'exists',return_value=True),patch.object(health,'run',side_effect=subprocess.TimeoutExpired('systemctl',3)):
            self.assertEqual(health.vpn_health()['status'],'unknown')
        self.assertEqual(self.query('unexpected response')['status'],'unknown')
        self.assertEqual(self.query(SAMPLE[:-1])['status'],'unknown')

    def test_missing_config_is_unknown(self):
        with patch.object(health.Path,'exists',return_value=False),patch.object(health,'run') as command:
            self.assertEqual(health.vpn_health()['status'],'unknown');command.assert_not_called()

    def test_stopped_daemon_is_critical(self):
        self.assertEqual(self.query(service='inactive')['status'],'critical')

    def test_two_rekey_associations_counted_once_each(self):
        extra=' administracion-2 {name=administracion state=INSTALLED bytes-in=1 bytes-out=2 packets-in=1 packets-out=1}'
        result=self.query(SAMPLE[:-3]+extra+'}}}')
        self.assertEqual(result['tx_bytes'],2050)
        self.assertEqual(result['rx_bytes'],1)


if __name__=='__main__':unittest.main()
