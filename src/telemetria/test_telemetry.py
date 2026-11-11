import contextlib
import io
import json
import subprocess
import collections
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
import agent
import collector
from common import clean_report, endpoint


def report():
    return {'schema': 1, 'device_id': 'synthetic-gateway', 'name': 'Sitio sintético', 'hostname': 'test',
            'sent_at': '2000-01-01T00:00:00Z', 'boot_id': 'synthetic-boot', 'cpu_percent': 8,
            'ram_percent': 20, 'disk_percent': 10, 'temperature_c': 45, 'uptime_seconds': 60,
            'health': {'vsaas': 'ok', 'vpn': 'critical', 'cameras_configured': 2, 'cameras_enabled': 2},
            'network': [{'name': 'eth0', 'addresses': ['192.0.2.10/24'], 'rx_mbps': 3, 'tx_mbps': 4}]}


class ProtocolTests(unittest.TestCase):
    def test_allowlist_never_forwards_private_probe_output(self):
        data = report() | {'password': 'synthetic-secret', 'logs': 'private log'}
        data['health']['credentials'] = 'no'
        cleaned = clean_report(data)
        self.assertNotIn('secret', json.dumps(cleaned))
        self.assertNotIn('credentials', cleaned['health'])

    def test_nonfinite_metrics_rejected(self):
        for invalid in [float('nan'), float('inf'), -1, 101, True]:
            with self.assertRaises(ValueError):
                clean_report(report() | {'cpu_percent': invalid})

    def test_endpoint_has_no_embedded_secrets_redirect_query_or_bad_scheme(self):
        for invalid in ['file:///tmp/test', 'http://a:b@example.com/report', 'http://example.com/?token=x', 'http://example.com/#x', 'http://example.com:0/x', 'http://example.com/\n']:
            with self.assertRaises(ValueError):
                endpoint(invalid)
        self.assertEqual(endpoint('https://example.invalid:8082/api/heartbeat'), 'https://example.invalid:8082/api/heartbeat')

    def test_token_preserved_only_for_same_destination(self):
        old = agent.initial()
        old['destinations'] = [dict(id='synthetic-dest', name='Test', url='http://example.invalid:8082/api/heartbeat', enabled=True, token='x'*32)]
        new = json.loads(json.dumps(old))
        new['destinations'][0]['token'] = ''
        self.assertEqual(agent.validate(new, old)['destinations'][0]['token'], 'x'*32)
        new['destinations'][0]['url'] = 'http://other.invalid/api/heartbeat'
        with self.assertRaises(ValueError):
            agent.validate(new, old)
        self.assertNotIn('x'*32, json.dumps(agent.public_config(old)))

    def test_disabled_agent_does_not_probe_or_send(self):
        with patch.object(agent, 'snapshot', side_effect=AssertionError('Do not collect')):
            self.assertEqual(agent.run_once(agent.initial(), {})['deliveries'], [])

    def test_multiple_destinations_independent_and_no_backlog(self):
        config = agent.initial() | {'enabled': True, 'destinations': [dict(id=n, enabled=True) for n in ['dest-one', 'dest-two']]}
        with patch.object(agent, 'snapshot', return_value=(report(), {'boot_id': 'test'})), patch.object(agent, 'deliver', side_effect=lambda d, r: {'id': d['id'], 'ok': d['id'] == 'dest-one'}):
            result = agent.run_once(config, {})
        self.assertEqual([d['ok'] for d in result['deliveries']], [True, False])
        self.assertNotIn('report', result)

    def test_snapshot_rates_and_first_read_are_not_invented(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            files = {'/proc/stat': 'cpu 100 0 100 800 0 0 0 0\n', '/proc/meminfo': 'MemTotal: 1000 kB\nMemAvailable: 800 kB\n',
                     '/proc/sys/kernel/random/boot_id': 'test-boot', '/proc/uptime': '3600 0', '/sys/class/thermal/thermal_zone0/temp': '45000',
                     '/sys/class/net/eth0/statistics/rx_bytes': '1000000', '/sys/class/net/eth0/statistics/tx_bytes': '2000000'}
            for name, value in files.items():
                dest = root/name.lstrip('/')
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(value)
            def run(args, **kw):
                value = [{'ifname': 'eth0', 'addr_info': [{'family': 'inet', 'scope': 'global', 'local': '192.0.2.10', 'prefixlen': 24}]}] if args[0] == 'ip' else {'local_status': 'ok', 'vpn': {'status': 'critical'}, 'containers': [{'state': 'running'}], 'internal': {'database': {'camera_total': 2, 'camera_enabled': 2}}, 'secret': 'private'}
                return subprocess.CompletedProcess(args, 0, json.dumps(value), '')
            with patch.object(agent, 'Path', side_effect=lambda p: root/str(p).lstrip('/')), patch.object(agent.subprocess, 'run', side_effect=run), patch.object(agent.shutil, 'disk_usage', return_value=collections.namedtuple('Disk', 'total used free')(1000, 300, 700)), patch.object(agent.time, 'monotonic', return_value=100):
                first, sample = agent.snapshot(agent.initial(), {})
                self.assertIsNone(first['cpu_percent'])
                self.assertIsNone(first['network'][0]['rx_mbps'])
                self.assertEqual(first['ram_percent'], 20)
                sample['cpu'] = [900, 750]
                sample['monotonic'] = 90
                sample['counters']['eth0']['rx'] = 0
                second, _ = agent.snapshot(agent.initial(), {'sample': sample})
                self.assertEqual(second['cpu_percent'], 50)
                self.assertEqual(second['network'][0]['rx_mbps'], 0.8)
                self.assertNotIn('private', json.dumps(second))

    def test_vpn_source_selection_only_for_remote_segment(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder)/'telemetria.json'
            config.with_name('config.json').write_text(json.dumps({'vpn_remote_subnet': '198.51.100.0/24', 'vpn_admin_ip': '192.0.2.137'}))
            with patch.object(agent, 'CONFIG', config), patch.object(agent.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', ('198.51.100.10', 0))]):
                self.assertEqual(agent.source_address({'url': 'http://collector.invalid/api/heartbeat'}), ('192.0.2.137', 0))
            with patch.object(agent, 'CONFIG', config), patch.object(agent.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', ('203.0.113.10', 0))]):
                self.assertIsNone(agent.source_address({'url': 'http://collector.invalid/api/heartbeat'}))
            self.assertEqual(agent.source_address({'source_ip': '127.0.0.1'}), ('127.0.0.1', 0))


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.now = 1000
        self.store = collector.Store(Path(self.folder.name)/'test.sqlite3', clock=lambda: self.now)
        self.registration = self.store.add({'id': 'synthetic-gateway', 'name': '<script>test</script>', 'timeout': 120})

    def test_receive_missing_recovery_uses_receipt_clock(self):
        self.store.receive(report(), self.registration['token'])
        status = self.store.status()
        self.assertEqual(status['devices'][0]['state'], 'online')
        self.assertEqual(status['devices'][0]['received_at'], 1000)
        self.assertNotIn('token_hash', json.dumps(status))
        with patch.object(collector.time, 'monotonic', return_value=self.store.last_monotonic['synthetic-gateway'] + 121):
            self.now += 121
            self.assertEqual(self.store.status()['devices'][0]['state'], 'offline')
            self.store.status()
        self.assertEqual(sum(a['state'] == 'offline' for a in self.store.status()['alerts']), 1)
        self.store.receive(report(), self.registration['token'])
        self.assertEqual(self.store.status()['alerts'][0]['state'], 'recovered')

    def test_reader_refreshes_clock_for_report_written_by_another_instance(self):
        self.store.receive(report(), self.registration['token'])
        previous_mono = self.store.last_monotonic['synthetic-gateway']
        self.now += 121
        with patch.object(collector.time, 'monotonic', return_value=previous_mono+121):
            self.assertEqual(self.store.status()['devices'][0]['state'], 'offline')
        other = collector.Store(Path(self.folder.name)/'test.sqlite3', clock=lambda: self.now)
        other.receive(report(), self.registration['token'])
        device = self.store.status()['devices'][0]
        self.assertEqual(device['state'], 'online')
        self.assertEqual(device['age_seconds'], 0)
        self.assertEqual(sum(a['state']=='offline' for a in self.store.status()['alerts']), 1)

    def test_exclusive_lock_rejects_second_process_and_releases(self):
        path = Path(self.folder.name)/'collector.lock'
        with collector.exclusive(path):
            with self.assertRaises(ValueError):
                with collector.exclusive(path):
                    self.fail('Duplicate lock accepted')
        with collector.exclusive(path):
            pass

    def test_no_first_report_also_alerts_and_rotate_revokes_old_key(self):
        with patch.object(collector.time, 'monotonic', return_value=self.store.last_monotonic['synthetic-gateway'] + 121):
            self.assertEqual(self.store.status()['devices'][0]['state'], 'offline')
        result = self.store.rotate('synthetic-gateway')
        with self.assertRaises(PermissionError):
            self.store.receive(report(), self.registration['token'])
        self.store.receive(report(), result['token'])

    def test_history_age_and_count_bounded(self):
        with self.store.db() as db:
            db.executemany('INSERT INTO samples(device,received,report) VALUES(?,?,?)', [('synthetic-gateway', self.now, '{}')]*10010)
            db.execute('INSERT INTO samples(device,received,report) VALUES(?,?,?)', ('synthetic-gateway', self.now-8*86400, '{}'))
        self.store.receive(report(), self.registration['token'])
        self.assertEqual(self.store.status()['samples'], 10000)

    def test_http_auth_and_actual_delivery(self):
        server = collector.Server(('127.0.0.1', 0), self.store, 'admin-test-key')
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = 'http://127.0.0.1:' + str(server.server_port)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with self.assertRaises(urllib.error.HTTPError) as caught:
            opener.open(url+'/api/status')
        self.assertEqual(caught.exception.code, 401)
        dest = dict(id='synthetic-dest', url=url+'/api/heartbeat', token=self.registration['token'])
        self.assertTrue(agent.deliver(dest, report())['ok'])
        dest['token'] = 'wrong'
        self.assertEqual(agent.deliver(dest, report())['http'], 401)
        request = urllib.request.Request(url+'/api/status', headers={'Authorization': 'Bearer admin-test-key'})
        with opener.open(request) as response:
            data = json.load(response)
        self.assertEqual(data['devices'][0]['report']['health']['vpn'], 'critical')
        self.assertNotIn(self.registration['token'], json.dumps(data))


if __name__ == '__main__':
    unittest.main()
