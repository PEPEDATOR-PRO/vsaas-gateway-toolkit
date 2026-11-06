import json
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from xml.etree import ElementTree as ET

from fastapi.testclient import TestClient

from collector.app import create_app
from collector.capabilities import inspect_camera
from collector.onvif import NS
from collector.storage import Store


CAMERA = dict(id='synthetic-camera', name='Entrada', mode='onvif',
              device_url='http://camera.invalid/onvif/device_service', username='synthetic-user',
              password='synthetic-password', verify_tls=True)


class CapabilityTests(unittest.TestCase):
    def client(self, external=False, failure=False):
        client = Mock()
        client.session = Mock()
        def call(url, action, name, fields=(), **kwargs):
            op = name.split(':')[1]
            payload = ''
            if op == 'GetDeviceInformation':
                payload = '<tds:Manufacturer>Example</tds:Manufacturer><tds:Model>Test</tds:Model>'
            elif op == 'GetCapabilities':
                host = 'other.invalid' if external else 'camera.invalid'
                payload = f'<tds:Capabilities><tt:Events><tt:XAddr>http://{host}/events</tt:XAddr></tt:Events><tt:Analytics><tt:XAddr>http://{host}/analytics</tt:XAddr></tt:Analytics><tt:Media><tt:XAddr>http://{host}/media</tt:XAddr></tt:Media></tds:Capabilities>'
            elif op == 'GetEventProperties':
                payload = '<w:TopicSet xmlns:w="urn:topics"><w:RuleEngine><w:Motion w:topic="true"><tt:MessageDescription><tt:Data><tt:SimpleItemDescription Name="State" Type="xs:boolean"/></tt:Data></tt:MessageDescription></w:Motion></w:RuleEngine></w:TopicSet>'
            elif op == 'GetSupportedMetadata':
                if failure:
                    raise ValueError('synthetic-password private failure')
                payload = '<tan:SampleFrame><tt:Object ObjectId="1"><tt:Appearance><tt:Human><tt:Gender>Male</tt:Gender></tt:Human></tt:Appearance></tt:Object></tan:SampleFrame>'
            elif op == 'GetProfiles':
                payload = '<trt:Profiles token="one"><tt:VideoAnalyticsConfiguration token="config"/><tt:Name>synthetic-password</tt:Name></trt:Profiles>'
            elif op == 'GetSupportedRules':
                payload = '<tan:RuleDescription Name="LineCrossing"/>'
            declarations = ' '.join(f'xmlns:{k}="{v}"' for k, v in NS.items())
            prefix = name.split(':')[0]
            raw = f'<s:Envelope {declarations}><s:Body><{prefix}:{op}Response>{payload}</{prefix}:{op}Response></s:Body></s:Envelope>'.encode()
            return ET.fromstring(raw), raw
        client.call.side_effect = call
        return client

    def test_announced_properties_samples_and_read_only_operations(self):
        client = self.client()
        report = inspect_camera(CAMERA, [{'topic': 'Motion', 'metadata': {'groups': {'Data': [{'attributes': {'Name': 'State', 'Value': 'true'}}]}}}], lambda _: client)
        self.assertEqual(report['event_topics'][0]['topic'], 'RuleEngine/Motion')
        self.assertEqual(report['event_topics'][0]['properties'][0]['name'], 'State')
        self.assertTrue(any('Gender' in p for p in report['metadata_fields']))
        self.assertTrue(any('[State]' in p for p in report['observed']['fields']))
        self.assertIn('LineCrossing', report['analytics'])
        self.assertNotIn('synthetic-password', json.dumps(report))
        self.assertTrue(all(c.args[2].split(':')[1].startswith('Get') for c in client.call.call_args_list))
        client.session.close.assert_called_once()

    def test_partial_failure_and_foreign_services(self):
        report = inspect_camera(CAMERA, [], lambda _: self.client(failure=True))
        self.assertEqual(next(q for q in report['queries'] if q['operation'] == 'GetSupportedMetadata')['status'], 'no confirmada')
        self.assertEqual(len(report['event_topics']), 1)
        self.assertNotIn('synthetic-password', json.dumps(report))
        client = self.client(external=True)
        report = inspect_camera(CAMERA, [], lambda _: client)
        self.assertTrue(any(q['status'] == 'omitida' for q in report['queries']))
        self.assertTrue(all('other.invalid' not in c.args[0] for c in client.call.call_args_list))

    def test_webhook_uses_received_fields_without_network(self):
        factory = Mock()
        report = inspect_camera(dict(CAMERA, mode='webhook'), [{'topic': 'http/json', 'metadata': {'plate': 'SYNTHETIC'}}], factory)
        factory.assert_not_called()
        self.assertIn('metadata.plate', report['observed']['fields'])
        self.assertEqual(report['queries'], [])
        self.assertNotIn('SYNTHETIC', json.dumps(report))

    def test_api_auth_unknown_camera_and_duplicate_query(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(directory)
            api = TestClient(app)
            store = app.state.store
            identifier = store.add_camera(CAMERA)
            path = '/api/cameras/' + identifier + '/capabilities'
            self.assertEqual(api.post(path).status_code, 401)
            api.headers['Authorization'] = 'Bearer ' + (store.directory / 'viewer.token').read_text()
            self.assertEqual(api.post(path).status_code, 403)
            api.headers['Authorization'] = 'Bearer ' + (store.directory / 'admin.token').read_text()
            self.assertEqual(api.post('/api/cameras/missing/capabilities').status_code, 404)
            started, release = threading.Event(), threading.Event()
            def inspect(*args):
                started.set(); release.wait(5)
                return {'summary': ['synthetic']}
            with patch('collector.app.inspect_camera', side_effect=inspect):
                responses = []
                worker = threading.Thread(target=lambda: responses.append(api.post(path)))
                worker.start()
                try:
                    self.assertTrue(started.wait(3))
                    self.assertEqual(api.post(path).status_code, 409)
                finally:
                    release.set(); worker.join(5)
                self.assertEqual(responses[0].status_code, 200)
                self.assertEqual(api.post(path).status_code, 200)

    def test_sample_budget_skips_oversized_records_and_is_camera_specific(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            for camera, topic, metadata in [('one', 'Motion', {'state': True}),
                                             ('one', 'Large', {'xml': 'x' * 1000}),
                                             ('other', 'Other', {'private': True})]:
                store.save(camera, 'http', b'original', 'text/plain', [{'topic': topic, 'metadata': metadata}])
            samples = store.capability_samples('one', max_bytes=100)
            self.assertEqual(samples, [{'topic': 'Motion', 'metadata': {'state': True}}])
            self.assertEqual(store.count(), 3)


if __name__ == '__main__':
    unittest.main()
