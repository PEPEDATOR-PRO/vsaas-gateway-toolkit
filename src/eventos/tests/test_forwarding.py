import json
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import pytest
import requests
from fastapi.testclient import TestClient
from collector.app import create_app
from collector.forwarding import Forwarder,validate
from collector.storage import Store

CONFIG={'enabled':True,'scheme':'http','host':'127.0.0.1','port':12345,'path':'/events','token':'synthetic-bearer'}


def add(store):store.save('camera-test','http',b'original','text/plain',[{'topic':'test','metadata':{'value':1}}])


def test_persisted_retry_ack_and_stable_identity(tmp_path,monkeypatch):
    store=Store(tmp_path);worker=Forwarder(store);worker.configure(CONFIG);add(store)
    ids=[]
    def failed(config,payload):ids.append(payload['event_id']);raise requests.ConnectionError('do not echo credentials')
    monkeypatch.setattr(worker,'post',failed)
    assert worker.once() is False
    assert store.count()==1
    worker=Forwarder(Store(tmp_path))
    def success(config,payload):
        assert config['token']=='synthetic-bearer'
        assert 'raw_base64' not in payload['event']
        ids.append(payload['event_id']);return 201
    monkeypatch.setattr(worker,'post',success)
    assert worker.once() is True
    assert ids[0]==ids[1]
    assert store.count()==0
    assert worker.status()['sent']==1
    assert 'synthetic-bearer' not in json.dumps(worker.status())
    assert b'synthetic-bearer' not in store.path.read_bytes()


def test_redirect_never_acknowledges_event(tmp_path,monkeypatch):
    store=Store(tmp_path);worker=Forwarder(store);worker.configure(CONFIG);add(store)
    monkeypatch.setattr(worker,'post',lambda *args:302)
    assert worker.once() is False
    assert store.count()==1


def test_rollover_discards_old_pending_and_bounds_database_files(tmp_path,monkeypatch):
    monkeypatch.setenv('COLLECTOR_MAX_DATA_BYTES',str(1024**2));monkeypatch.setenv('COLLECTOR_ROLLOVER','1')
    store=Store(tmp_path);worker=Forwarder(store)
    first=None
    for i in range(80):
        store.save('synthetic','http',b'x'*16384,'text/plain',[{'topic':'test','metadata':{'n':i}}])
        assert store.storage_status()['bytes']<=1024**2
        if i==0:first=store.events()[0]['id']
    assert worker.status()['dropped']>0
    assert all(row['id']>first for row in store.events())
    assert store.events(order='desc')[0]['metadata']['n']==79
    assert (tmp_path/'secret.key').exists()


def test_api_roles_and_token_is_not_returned(tmp_path):
    app=create_app(tmp_path)
    with TestClient(app) as client:
        client.headers['Authorization']='Bearer '+(tmp_path/'admin.token').read_text()
        result=client.put('/api/forwarding',json={**CONFIG,'enabled':False})
        assert result.status_code==200 and result.json()['has_token'] is True
        assert 'synthetic-bearer' not in result.text
        client.headers['Authorization']='Bearer '+(tmp_path/'viewer.token').read_text()
        assert client.get('/api/forwarding').status_code==200
        assert client.put('/api/forwarding',json=CONFIG).status_code==403
        assert client.post('/api/forwarding/test').status_code==403


def test_rollover_does_not_discard_the_event_currently_in_flight(tmp_path,monkeypatch):
    monkeypatch.setenv('COLLECTOR_MAX_DATA_BYTES',str(1024**2));monkeypatch.setenv('COLLECTOR_ROLLOVER','1')
    store=Store(tmp_path);worker=Forwarder(store);worker.configure(CONFIG);add(store)
    identifier=store.events()[0]['id']
    def receiver(config,payload):
        for i in range(40):store.save('synthetic','http',b'x'*16384,'text/plain',[{'metadata':{'n':i}}])
        assert store.events()[0]['id']==identifier
        return 204
    monkeypatch.setattr(worker,'post',receiver)
    assert worker.once() is True
    assert store.inflight_event is None
    assert worker.status()['sent']==1 and worker.status()['dropped']>0


def test_target_validation_and_secret_clear(tmp_path):
    for changes in [{'host':'http://example.invalid'},{'host':'user@host'},{'path':'//other.invalid'},{'port':0},{'token':'bad\r\nvalue'}]:
        with pytest.raises(ValueError):validate({**CONFIG,**changes})
    worker=Forwarder(Store(tmp_path));worker.configure(CONFIG)
    worker.configure({**CONFIG,'token':''})
    assert worker.config(secret=True)['token']=='synthetic-bearer'
    worker.configure({**CONFIG,'token':'','clear_token':True})
    assert worker.config(secret=True)['token']==''
    worker.configure(CONFIG)
    worker.configure({**CONFIG,'host':'another.example.invalid','token':''})
    assert worker.config(secret=True)['token']==''


def test_local_http_receiver_gets_json_without_following_redirects(tmp_path):
    bodies=[]
    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            bodies.append((self.path,json.loads(self.rfile.read(int(self.headers['Content-Length']))),self.headers.get('Idempotency-Key')))
            self.send_response(204);self.end_headers()
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Receiver);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        store=Store(tmp_path);worker=Forwarder(store);worker.configure({**CONFIG,'port':server.server_port});add(store)
        assert worker.once() is True
        assert bodies[0][0]=='/events'
        assert bodies[0][1]['type']=='camera_event'
        assert bodies[0][1]['event_id']==bodies[0][2]
    finally:server.shutdown();server.server_close();thread.join(2)
