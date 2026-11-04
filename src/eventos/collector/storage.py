import base64
import json
import os
import sqlite3
import uuid
import shutil
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet


def now():
    return datetime.now(timezone.utc).isoformat()


class StorageFull(RuntimeError):
    pass


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.max_bytes=int(os.environ.get('COLLECTOR_MAX_DATA_MB','0'))*1024**2
        self.min_free_bytes=int(os.environ.get('COLLECTOR_MIN_FREE_MB','0'))*1024**2
        if self.max_bytes<0 or self.min_free_bytes<0:raise ValueError('Los límites de almacenamiento deben ser positivos.')
        self.write_lock=threading.Lock()
        self.storage_blocked=False
        key_file = self.directory / 'secret.key'
        try:
            with key_file.open('xb') as handle:
                handle.write(Fernet.generate_key())
            os.chmod(key_file, 0o600)
        except FileExistsError:
            pass
        self.cipher = Fernet(key_file.read_bytes())
        self.path = self.directory / 'events.sqlite3'
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS cameras (
                    id TEXT PRIMARY KEY, config TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pendiente',
                    last_error TEXT, last_seen TEXT);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    camera_id TEXT NOT NULL, received_at TEXT NOT NULL,
                    source_time TEXT, topic TEXT NOT NULL, transport TEXT NOT NULL,
                    metadata TEXT NOT NULL, raw BLOB NOT NULL,
                    content_type TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS metadata_status (
                    camera_id TEXT PRIMARY KEY, status TEXT NOT NULL,
                    last_error TEXT, last_seen TEXT);
                CREATE INDEX IF NOT EXISTS events_camera_id ON events(camera_id, id);
                CREATE INDEX IF NOT EXISTS events_received ON events(received_at);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL')
            with db:
                yield db
        finally:
            db.close()

    def cameras(self, secrets=False):
        with self.connect() as db:
            rows = db.execute('''SELECT c.*, m.status AS metadata_status,
                m.last_error AS metadata_last_error, m.last_seen AS metadata_last_seen
                FROM cameras c LEFT JOIN metadata_status m ON m.camera_id=c.id ORDER BY c.rowid''').fetchall()
        result = []
        for row in rows:
            camera = json.loads(row['config'])
            for field in ('password', 'webhook_token'):
                value = camera.pop(field, '')
                if secrets:
                    camera[field] = self.cipher.decrypt(value.encode()).decode() if value else ''
            camera.update({k: row[k] for k in ('status', 'last_error', 'last_seen',
                'metadata_status', 'metadata_last_error', 'metadata_last_seen')})
            camera['metadata_enabled'] = bool(camera.get('metadata_rtsp_url'))
            result.append(camera)
        return result

    def add_camera(self, config):
        camera = dict(config, id=uuid.uuid4().hex)
        for field in ('password', 'webhook_token'):
            camera[field] = self.cipher.encrypt(camera.get(field, '').encode()).decode()
        with self.connect() as db:
            db.execute('INSERT INTO cameras(id, config) VALUES (?, ?)',
                       (camera['id'], json.dumps(camera)))
        return camera['id']

    def status(self, camera_id, status, error=None):
        with self.connect() as db:
            db.execute('UPDATE cameras SET status=?, last_error=?, last_seen=CASE WHEN ? THEN ? ELSE last_seen END WHERE id=?',
                       (status, error, status == 'conectada', now(), camera_id))

    def delete_camera(self, camera_id):
        with self.connect() as db:
            db.execute('DELETE FROM cameras WHERE id=?', (camera_id,))
            db.execute('DELETE FROM metadata_status WHERE camera_id=?', (camera_id,))

    def configure_metadata(self, camera_id, url):
        with self.connect() as db:
            row = db.execute('SELECT config FROM cameras WHERE id=?', (camera_id,)).fetchone()
            if row is None:
                raise ValueError('Cámara no encontrada')
            config = json.loads(row['config'])
            config['metadata_rtsp_url'] = url
            db.execute('UPDATE cameras SET config=? WHERE id=?', (json.dumps(config), camera_id))
            db.execute('DELETE FROM metadata_status WHERE camera_id=?', (camera_id,))

    def set_metadata_status(self, camera_id, status, error=None):
        with self.connect() as db:
            db.execute('''INSERT INTO metadata_status(camera_id,status,last_error,last_seen)
                VALUES (?,?,?,?) ON CONFLICT(camera_id) DO UPDATE SET
                status=excluded.status,last_error=excluded.last_error,
                last_seen=CASE WHEN excluded.status='conectada' THEN excluded.last_seen ELSE metadata_status.last_seen END''',
                (camera_id, status, error, now() if status == 'conectada' else None))

    def save(self, camera_id, transport, raw, content_type, events):
        # The complete inbound body is retained for each notification, including extensions.
        with self.write_lock:
            estimated=sum(len(raw)+len(json.dumps(event,ensure_ascii=False).encode())+8192 for event in events)
            state=self.storage_status()
            if (self.max_bytes and state['bytes']+estimated>self.max_bytes) or state['free_bytes']-estimated<self.min_free_bytes:
                self.storage_blocked=True
                raise StorageFull('Almacenamiento del colector limitado: no se guardaron nuevos eventos ni se borró el historial.')
            self.storage_blocked=False
            with self.connect() as db:
                for event in events:
                    db.execute('''INSERT INTO events
                        (camera_id, received_at, source_time, topic, transport, metadata, raw, content_type)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                        (camera_id, now(), event.get('source_time'), event.get('topic', 'unknown'),
                         transport, json.dumps(event.get('metadata', {}), ensure_ascii=False), raw, content_type))

    def storage_status(self):
        size=sum(path.stat().st_size for path in self.directory.glob('events.sqlite3*') if path.is_file())
        free=shutil.disk_usage(self.directory).free
        return {'bytes':size,'limit_bytes':self.max_bytes or None,'free_bytes':free,
                'blocked':bool(self.storage_blocked or (self.max_bytes and size>=self.max_bytes) or free<self.min_free_bytes)}

    def events(self, camera_id=None, topic=None, after_id=0, limit=100,
               order='asc', before_id=None, include_raw=True):
        where, params = ['id > ?'], [after_id]
        if camera_id:
            where.append('camera_id = ?')
            params.append(camera_id)
        if topic:
            where.append('instr(topic, ?) > 0')
            params.append(topic)
        if before_id is not None:
            where.append('id < ?')
            params.append(before_id)
        columns = '*' if include_raw else 'id, camera_id, received_at, source_time, topic, transport, metadata, content_type'
        direction = 'DESC' if order == 'desc' else 'ASC'
        with self.connect() as db:
            rows = db.execute('SELECT ' + columns + ' FROM events WHERE ' + ' AND '.join(where)
                              + ' ORDER BY id ' + direction + ' LIMIT ?', (*params, limit)).fetchall()
        result = []
        for row in rows:
            value = dict(row)
            value['metadata'] = json.loads(value['metadata'])
            if include_raw:
                value['raw_base64'] = base64.b64encode(value.pop('raw')).decode()
            result.append(value)
        return result

    def count(self):
        with self.connect() as db:
            return db.execute('SELECT count(*) FROM events').fetchone()[0]
