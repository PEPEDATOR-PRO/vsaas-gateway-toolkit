import base64
import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from collector.app import create_app
from collector.onvif import NS, OnvifClient, OnvifHTTPError, parse_events
from collector.storage import Store

NOTIFICATION = '''<wsnt:NotificationMessage xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2" xmlns:tt="http://www.onvif.org/ver10/schema" xmlns:v="urn:vendor">
<wsnt:Topic>tns:RuleEngine/Motion</wsnt:Topic><wsnt:Message><tt:Message UtcTime="2026-10-15T10:00:00Z" PropertyOperation="Changed">
<tt:Source><tt:SimpleItem Name="VideoSource" Value="1"/></tt:Source><tt:Data><tt:SimpleItem Name="State" Value="true"/><tt:ElementItem Name="Person"><v:Score>0.98</v:Score></tt:ElementItem></tt:Data>
</tt:Message></wsnt:Message></wsnt:NotificationMessage>'''


def envelope(body):
    declarations = ' '.join(f'xmlns:{k}="{v}"' for k, v in NS.items())
    return f'<s:Envelope {declarations}><s:Body>{body}</s:Body></s:Envelope>'.encode()


@pytest.fixture
def api(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer ' + (tmp_path / 'admin.token').read_text()
        yield client, app.state.store


def test_webhook_storage_security_export_and_restart(api):
    client, store = api
    assert client.get('/api/status', headers={'Authorization': 'wrong'}).status_code == 401
    assert client.get('/').status_code == 200
    assert client.get('/health').json() == {'status': 'ok'}
    camera = client.post('/api/cameras', json={'name': 'Entrada', 'mode': 'webhook'}).json()
    raw = envelope(NOTIFICATION + NOTIFICATION)
    assert client.post(camera['webhook_path'], content=raw).status_code == 401
    response = client.post(camera['webhook_path'], content=raw, headers={
        'X-Camera-Token': camera['webhook_token'], 'content-type': 'application/xml'})
    assert response.status_code == 201
    assert response.json()['stored'] == 2
    events = client.get('/api/events').json()
    assert len(events) == 2
    assert base64.b64decode(events[0]['raw_base64']) == raw
    assert events[0]['source_time'] == '2026-10-15T10:00:00Z'
    assert '0.98' in events[0]['metadata']['notification_xml']
    assert client.get(f"/api/events/{events[0]['id']}/raw").content == raw
    assert len(client.get('/api/events?after_id=1&topic=Motion').json()) == 1
    assert client.get('/api/events?limit=1001').status_code == 422
    status = client.get('/api/status').json()
    assert 'webhook_token' not in status['cameras'][0]
    assert camera['webhook_token'].encode() not in store.path.read_bytes()
    assert Store(store.directory).count() == 2
    assert client.delete('/api/cameras/' + camera['id']).status_code == 200
    assert client.get('/api/status').json()['cameras'] == []
    assert client.get('/api/status').json()['events'] == 2


def test_unknown_and_malformed_payloads_are_preserved(api):
    client, store = api
    camera = client.post('/api/cameras', json={'name': 'Vendor', 'mode': 'webhook'}).json()
    headers = {'X-Camera-Token': camera['webhook_token']}
    for payload, content_type in [(b'\x00\xff', 'application/octet-stream'),
                                  (b'{broken', 'application/json'),
                                  (b'<broken', 'application/xml')]:
        response = client.post(camera['webhook_path'], content=payload,
                               headers=dict(headers, **{'content-type': content_type}))
        assert response.status_code == 201
    assert store.count() == 3
    assert client.post(camera['webhook_path'], content=b'x' * (8 * 1024 * 1024 + 1), headers=headers).status_code == 413


def test_configuration_and_unsafe_xml(api):
    client, _ = api
    assert client.post('/api/cameras', json={'name': 'Missing'}).status_code == 422
    assert client.post('/api/cameras', json={'name': 'Bad', 'device_url': 'file:///etc/passwd'}).status_code == 422
    with pytest.raises(Exception):
        parse_events(b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>')


def test_latest_events_history_and_live_cursor(api):
    client, store = api
    for number in range(1, 8):
        store.save('camera-a' if number % 2 else 'camera-b', 'http', b'original',
                   'application/json', [{'topic': 'Motion', 'metadata': {'number': number}}])
    latest = client.get('/api/events?order=desc&limit=3&include_raw=false').json()
    assert [event['id'] for event in latest] == [7, 6, 5]
    assert all('raw_base64' not in event for event in latest)
    assert latest[0]['metadata'] == {'number': 7}
    older = client.get('/api/events?order=desc&before_id=5&limit=3').json()
    assert [event['id'] for event in older] == [4, 3, 2]
    store.save('camera-a', 'http', b'new', 'application/json', [{'topic': 'Motion'}])
    resumed = client.get('/api/events?after_id=7&order=asc&include_raw=false').json()
    assert [event['id'] for event in resumed] == [8]
    assert [event['id'] for event in client.get('/api/events?camera_id=camera-a&order=desc&limit=2').json()] == [8, 7]
    assert client.get('/api/events?order=invalid').status_code == 422
    assert client.get('/api/events?before_id=0').status_code == 422
    assert client.get('/assets/panel.js').status_code == 200
    assert client.get('/assets/panel.css').status_code == 200


def test_viewer_can_read_events_but_cannot_change_devices(api):
    client, store = api
    camera_id = store.add_camera({'name': 'Privada', 'mode': 'webhook',
                                 'username': 'private-user', 'password': 'private-password'})
    store.save(camera_id, 'http', b'original-xml', 'application/xml', [{'topic': 'Motion'}])
    admin_headers = dict(client.headers)
    client.headers['Authorization'] = 'Bearer ' + (store.directory / 'viewer.token').read_text().strip()
    result = client.get('/api/status')
    assert result.status_code == 200
    assert result.json()['access_role'] == 'viewer'
    assert 'username' not in result.json()['cameras'][0]
    assert 'password' not in result.json()['cameras'][0]
    assert client.get('/api/events').status_code == 200
    assert client.get('/api/events/1/raw').content == b'original-xml'
    assert client.post('/api/cameras', json={'name': 'Blocked', 'mode': 'webhook'}).status_code == 403
    assert client.delete('/api/cameras/' + camera_id).status_code == 403
    assert client.put('/api/cameras/' + camera_id + '/metadata', json={'metadata_rtsp_url': ''}).status_code == 403
    assert len(store.cameras()) == 1
    assert client.get('/api/events', headers={'Authorization': 'wrong'}).status_code == 401
    assert client.get('/api/status', headers=admin_headers).json()['access_role'] == 'admin'


def test_metadata_configuration_preserves_camera_and_credentials(api, monkeypatch):
    client, store = api
    camera_id = store.add_camera({'name': 'NVR', 'mode': 'onvif', 'device_url': 'http://127.0.0.1',
                                 'username': 'user', 'password': 'secret'})
    manager = client.app.state.manager
    monkeypatch.setattr(manager, 'stop', lambda camera_id: None)
    monkeypatch.setattr(manager, 'start', lambda camera: None)
    url = '/api/cameras/' + camera_id + '/metadata'
    assert client.put(url, json={'metadata_rtsp_url': 'rtsp://other-host/live'}).status_code == 400
    assert client.put(url, json={'metadata_rtsp_url': 'rtsp://user:secret@127.0.0.1/live'}).status_code == 422
    response = client.put(url, json={'metadata_rtsp_url': 'rtsp://127.0.0.1:4520/LiveChannel/0/media.smp'})
    assert response.status_code == 200
    camera = store.cameras(secrets=True)[0]
    assert camera['id'] == camera_id
    assert camera['password'] == 'secret'
    assert camera['metadata_enabled'] is True
    assert client.put(url, json={'metadata_rtsp_url': ''}).status_code == 200
    assert store.cameras()[0]['metadata_enabled'] is False


@pytest.fixture
def fake_camera():
    state = {'actions': [], 'pulled': 0, 'fail_next_pull': False, 'http500_remaining': 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers['content-length']))
            root = ET.fromstring(body)
            action = root.findtext('s:Header/a:Action', namespaces=NS)
            state['actions'].append(action)
            assert root.find('.//wsse:Username', NS).text == 'user'
            nonce = base64.b64decode(root.find('.//wsse:Nonce', NS).text)
            created = root.find('.//wsu:Created', NS).text
            expected = base64.b64encode(hashlib.sha1(nonce + created.encode() + b'secret').digest()).decode()
            assert root.find('.//wsse:Password', NS).text == expected
            if action.endswith('/GetCapabilities'):
                output = f'<tds:GetCapabilitiesResponse><tds:Capabilities><tt:Events><tt:XAddr>{base}/events</tt:XAddr></tt:Events></tds:Capabilities></tds:GetCapabilitiesResponse>'
            elif action.endswith('/CreatePullPointSubscriptionRequest'):
                output = f'''<tev:CreatePullPointSubscriptionResponse><tev:SubscriptionReference><a:Address>{base}/subscription</a:Address><a:ReferenceParameters><tt:SubscriptionId>123</tt:SubscriptionId></a:ReferenceParameters></tev:SubscriptionReference><wsnt:CurrentTime>2026-10-15T00:00:00Z</wsnt:CurrentTime><wsnt:TerminationTime>2026-10-15T00:02:00Z</wsnt:TerminationTime></tev:CreatePullPointSubscriptionResponse>'''
            else:
                assert root.find('.//tt:SubscriptionId', NS).text == '123'
                if action.endswith('/PullMessagesRequest'):
                    if state['http500_remaining']:
                        state['http500_remaining'] -= 1
                        self.send_response(500)
                        self.end_headers()
                        self.wfile.write(b'<html><body>Internal Server Error</body></html>')
                        return
                    if state['fail_next_pull']:
                        state['fail_next_pull'] = False
                        self.send_response(503)
                        self.end_headers()
                        return
                    state['pulled'] += 1
                    output = '<tev:PullMessagesResponse>' + (NOTIFICATION if state['pulled'] == 1 else '') + '</tev:PullMessagesResponse>'
                elif action.endswith('/RenewRequest'):
                    output = '<wsnt:RenewResponse><wsnt:CurrentTime>2026-10-15T00:00:00Z</wsnt:CurrentTime><wsnt:TerminationTime>2026-10-15T00:02:00Z</wsnt:TerminationTime></wsnt:RenewResponse>'
                else:
                    output = '<wsnt:UnsubscribeResponse/>'
            data = envelope(output)
            self.send_response(200)
            self.send_header('Content-Type', 'application/soap+xml')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    base = f'http://127.0.0.1:{server.server_port}'
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield base, state
    server.shutdown()
    server.server_close()
    thread.join()


def test_onvif_soap_lifecycle(fake_camera):
    base, state = fake_camera
    camera = {'device_url': base, 'username': 'user', 'password': 'secret', 'verify_tls': True}
    client = OnvifClient(camera)
    endpoint = client.discover()
    subscription, deadline = client.subscribe(endpoint)
    assert 110 < deadline - time.monotonic() <= 120
    raw, events = client.pull(subscription)
    assert len(events) == 1
    assert client.renew(subscription) > time.monotonic()
    client.unsubscribe(subscription)
    client.session.close()
    assert len(state['actions']) == 5


def test_non_soap_http_error_reports_status_and_operation(fake_camera):
    base, state = fake_camera
    client = OnvifClient({'device_url': base, 'username': 'user', 'password': 'secret', 'verify_tls': True})
    subscription, _ = client.subscribe(client.discover())
    try:
        state['http500_remaining'] = 1
        with pytest.raises(OnvifHTTPError) as error:
            client.pull(subscription, seconds=1)
        assert error.value.status_code == 500
        assert error.value.operation == 'PullMessages'
        assert 'secret' not in str(error.value)
    finally:
        client.unsubscribe(subscription)
        client.session.close()


def test_worker_retries_initial_http500_on_same_subscription(tmp_path, fake_camera):
    base, state = fake_camera
    state['http500_remaining'] = 1
    app = create_app(tmp_path)
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer ' + (tmp_path / 'admin.token').read_text()
        response = client.post('/api/cameras', json={'name': 'NVR', 'device_url': base,
                               'username': 'user', 'password': 'secret'})
        assert response.status_code == 201
        deadline = time.monotonic() + 8
        while (app.state.store.count() == 0 or app.state.store.cameras()[0]['status'] != 'conectada') and time.monotonic() < deadline:
            time.sleep(0.05)
        assert app.state.store.count() == 1
        assert sum(a.endswith('/CreatePullPointSubscriptionRequest') for a in state['actions']) == 1
        assert app.state.store.cameras()[0]['status'] == 'conectada'


def test_background_worker_reconnects_and_resumes_after_restart(tmp_path, fake_camera):
    base, state = fake_camera
    app = create_app(tmp_path)
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer ' + (tmp_path / 'admin.token').read_text()
        response = client.post('/api/cameras', json={'name': 'ONVIF', 'device_url': base,
                               'username': 'user', 'password': 'secret'})
        assert response.status_code == 201
        deadline = time.monotonic() + 8
        while app.state.store.count() == 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert app.state.store.count() == 1
        state['fail_next_pull'] = True
        while sum(a.endswith('/CreatePullPointSubscriptionRequest') for a in state['actions']) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert sum(a.endswith('/CreatePullPointSubscriptionRequest') for a in state['actions']) >= 2
        assert 'password' not in client.get('/api/status').json()['cameras'][0]
    previous = len(state['actions'])
    restarted = create_app(tmp_path)
    with TestClient(restarted):
        deadline = time.monotonic() + 5
        while len(state['actions']) <= previous + 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert len(state['actions']) > previous + 2
        assert restarted.state.store.count() == 1
