from collections import namedtuple
import pytest
from fastapi.testclient import TestClient
from collector.app import create_app
from collector.storage import Store,StorageFull
import collector.storage as storage


def test_rejected_writes_preserve_history_and_return_503(tmp_path,monkeypatch):
    monkeypatch.setenv('COLLECTOR_MAX_DATA_MB','1')
    app=create_app(tmp_path)
    with TestClient(app) as client:
        client.headers['Authorization']='Bearer '+(tmp_path/'admin.token').read_text()
        camera=client.post('/api/cameras',json={'name':'Synthetic input','mode':'webhook'}).json()
        headers={'X-Camera-Token':camera['webhook_token']}
        assert client.post(camera['webhook_path'],content=b'first',headers=headers).status_code==201
        result=client.post(camera['webhook_path'],content=b'x'*1024**2,headers=headers)
        assert result.status_code==503
        assert app.state.store.count()==1
        assert client.get('/api/status').json()['storage']['blocked'] is True
        assert camera['webhook_token'] not in result.text


def test_minimum_free_space_blocks_capture_without_deleting_events(tmp_path,monkeypatch):
    monkeypatch.setenv('COLLECTOR_MIN_FREE_MB','512')
    store=Store(tmp_path)
    monkeypatch.setattr(storage.shutil,'disk_usage',lambda path:namedtuple('Disk','total used free')(1024**3,1024**3-1,1))
    with pytest.raises(StorageFull):store.save('synthetic','http',b'event','text/plain',[{'topic':'test','metadata':{}}])
    assert store.count()==0
    assert store.storage_status()['blocked'] is True
