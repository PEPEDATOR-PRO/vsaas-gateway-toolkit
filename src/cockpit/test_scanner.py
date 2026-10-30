import importlib.util
import pathlib
import subprocess
import unittest
import tempfile
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('scanner', pathlib.Path(__file__).with_name('gateway-scanner.py'))
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)
NET = {'name': 'eth0', 'addresses': ['192.168.1.10/24']}


class ScannerTests(unittest.TestCase):
    def test_discovery_deduplicates_and_sorts_numerically(self):
        text = '''Interface: eth0
192.168.1.100 aa:bb:cc:dd:ee:ff (Unknown)
192.168.1.2 12:34:56:78:90:ab Vendor with spaces
192.168.1.2 12:34:56:78:90:ab Vendor with spaces
invalid aa:bb:cc:dd:ee:ff Not a host
67 responded'''
        hosts = scanner.parse_arp(text)
        self.assertEqual([h['ip'] for h in hosts], ['192.168.1.2', '192.168.1.100'])
        self.assertEqual(hosts[1]['vendor'], 'No identificado')

    def test_interface_list_excludes_docker_and_vpn(self):
        import json
        values = [{'ifname': n, 'link_type': 'ether', 'flags': ['UP','BROADCAST'],
                   'addr_info': [{'family': 'inet', 'scope': 'global', 'local': '192.168.1.10', 'prefixlen': 24}]}
                  for n in ['eth0', 'docker0', 'veth123', 'br-123', 'tun0']]
        with patch.object(scanner, 'execute', return_value=subprocess.CompletedProcess([], 0, json.dumps(values), '')):
            self.assertEqual([i['name'] for i in scanner.interfaces()], ['eth0'])

    def test_unknown_interface_is_rejected(self):
        with patch.object(scanner, 'interfaces', return_value=[NET]):
            with self.assertRaises(ValueError):
                scanner.get_interface('eth0;touch /tmp/unwanted')

    def test_ipv4_output_without_link_type_keeps_lan_interfaces(self):
        import json
        data = [{'ifname': name, 'flags': ['UP', 'BROADCAST', 'MULTICAST'],
                 'addr_info': [{'family': 'inet', 'scope': 'global', 'local': address, 'prefixlen': 24}]}
                for name, address in [('eth0', '192.168.1.10'), ('wlan0', '192.168.60.10')]]
        data.append({'ifname': 'vpn0', 'flags': ['UP', 'POINTOPOINT'], 'addr_info':
                     [{'family': 'inet', 'scope': 'global', 'local': '10.0.0.1', 'prefixlen': 32}]})
        with patch.object(scanner, 'execute', return_value=subprocess.CompletedProcess([], 0, json.dumps(data), '')):
            self.assertEqual([i['name'] for i in scanner.interfaces()], ['eth0', 'wlan0'])

    def test_port_scan_rejects_target_outside_local_network(self):
        with patch.object(scanner, 'get_interface', return_value=NET), patch.object(scanner, 'execute') as execute:
            with self.assertRaises(ValueError):
                scanner.ports('eth0', '8.8.8.8')
            execute.assert_not_called()

    def test_oversized_network_is_not_scanned(self):
        with patch.object(scanner, 'get_interface', return_value={'addresses':['10.0.0.1/8']}), patch.object(scanner, 'execute') as execute:
            with self.assertRaises(ValueError):
                scanner.scan('eth0')
            execute.assert_not_called()

    def test_closed_ports_are_a_valid_result(self):
        xml = '<nmaprun><host><ports><extraports state="closed" count="5"/></ports></host></nmaprun>'
        with patch.object(scanner, 'get_interface', return_value=NET), patch.object(scanner.shutil, 'which', return_value='/usr/bin/nmap'), patch.object(scanner, 'execute', return_value=subprocess.CompletedProcess([], 0, xml, '')) as execute:
            self.assertEqual(scanner.ports('eth0', '192.168.1.20')['ports'], [])
            args = execute.call_args.args[0]
            self.assertEqual(args[-1], '192.168.1.20')
            self.assertNotIn('-sV', args)

    def test_open_ports_are_parsed(self):
        xml = '<nmaprun><host><ports><port portid="554"><state state="open"/></port><port portid="80"><state state="closed"/></port></ports></host></nmaprun>'
        self.assertEqual(scanner.parse_ports(xml), [554])

    def test_vendor_text_is_not_interpreted(self):
        hosts = scanner.parse_arp('192.168.1.2 aa:bb:cc:dd:ee:ff <script>alert(1)</script>')
        self.assertEqual(hosts[0]['vendor'], '<script>alert(1)</script>')

    def test_traffic_reads_counters_without_privileges(self):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            stats = root / 'eth0' / 'statistics'
            stats.mkdir(parents=True)
            for key in ['rx_bytes','tx_bytes','rx_packets','tx_packets','rx_errors','tx_errors','rx_dropped','tx_dropped']:
                (stats/key).write_text('125000')
            (root/'eth0'/'speed').write_text('1000')
            with patch.object(scanner, 'Path', return_value=root), patch.object(scanner.time, 'monotonic', return_value=42):
                result = scanner.traffic_snapshot('eth0')
                self.assertEqual(result['rx_bytes'], 125000)
                self.assertEqual(result['speed_mbps'], 1000)
                self.assertEqual(result['timestamp'], 42)
            (root/'eth0'/'speed').unlink()
            with patch.object(scanner, 'Path', return_value=root):
                self.assertIsNone(scanner.traffic_snapshot('eth0')['speed_mbps'])

    def test_traffic_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            scanner.traffic_snapshot('../../etc')


if __name__ == '__main__':
    unittest.main()
