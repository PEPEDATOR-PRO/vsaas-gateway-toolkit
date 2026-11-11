#!/usr/bin/env python3
"""Private LAN/VPN health collector for a laptop. Not an Internet-facing server."""
import argparse
import contextlib
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from common import clean_report, device_id, MAX_BODY


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Store:
    def __init__(self, path, clock=time.time):
        self.path, self.clock = str(path), clock
        self.lock = threading.RLock()
        self.last_monotonic = {}
        self.receipt_times = {}
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT NOT NULL,
                    timeout INTEGER NOT NULL, created REAL NOT NULL, received REAL, report TEXT, state TEXT NOT NULL DEFAULT 'pending');
                CREATE TABLE IF NOT EXISTS samples(id INTEGER PRIMARY KEY, device TEXT NOT NULL, received REAL NOT NULL, report TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS samples_device ON samples(device, received);
                CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY, device TEXT NOT NULL, at REAL NOT NULL, state TEXT NOT NULL);
            ''')

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        # Bound DB to 256 MiB, plus a rollback journal of at most the same size.
        size = db.execute('PRAGMA page_size').fetchone()[0]
        db.execute('PRAGMA max_page_count=' + str(256 * 1024 * 1024 // size))
        try:
            with db:
                yield db
        finally:
            db.close()

    def add(self, data):
        identity = device_id(data.get('id'))
        name, timeout = data.get('name'), data.get('timeout', 120)
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 128 or isinstance(timeout, bool) or not isinstance(timeout, int) or not 60 <= timeout <= 86400:
            raise ValueError('Nombre o tiempo sin reportes (60–86400 s) no válidos.')
        token = secrets.token_urlsafe(32)
        with self.lock, self.db() as db:
            if db.execute('SELECT count(*) FROM devices').fetchone()[0] >= 500:
                raise ValueError('Límite de 500 equipos alcanzado.')
            try:
                db.execute('INSERT INTO devices(id,name,token_hash,timeout,created) VALUES(?,?,?,?,?)', (identity, name.strip(), digest(token), timeout, self.clock()))
            except sqlite3.IntegrityError:
                raise ValueError('Ese equipo ya está registrado.') from None
        self.last_monotonic[identity] = time.monotonic()
        return {'id': identity, 'token': token}

    def configure(self, data):
        identity = device_id(data.get('id'))
        name, timeout = data.get('name'), data.get('timeout')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 128 or isinstance(timeout, bool) or not isinstance(timeout, int) or not 60 <= timeout <= 86400:
            raise ValueError('Nombre o tiempo sin reportes no válidos.')
        with self.lock, self.db() as db:
            if db.execute('UPDATE devices SET name=?, timeout=? WHERE id=?', (name.strip(), timeout, identity)).rowcount != 1:
                raise ValueError('Equipo no encontrado.')

    def rotate(self, identity):
        identity = device_id(identity)
        token = secrets.token_urlsafe(32)
        with self.lock, self.db() as db:
            if db.execute('UPDATE devices SET token_hash=? WHERE id=?', (digest(token), identity)).rowcount != 1:
                raise ValueError('Equipo no encontrado.')
        return {'id': identity, 'token': token}

    def receive(self, data, token):
        report = clean_report(data)
        identity, now = report['device_id'], self.clock()
        payload = json.dumps(report, allow_nan=False)
        with self.lock, self.db() as db:
            row = db.execute('SELECT token_hash,state FROM devices WHERE id=?', (identity,)).fetchone()
            if not row or not hmac.compare_digest(row['token_hash'], digest(token)):
                raise PermissionError('No autorizado.')
            # Reserve capacity before inserting. No unbounded history or offline replay.
            db.execute('DELETE FROM samples WHERE received<?', (now - 7 * 86400,))
            db.execute('DELETE FROM samples WHERE id IN (SELECT id FROM samples ORDER BY id DESC LIMIT -1 OFFSET 9999)')
            db.execute('DELETE FROM alerts WHERE id IN (SELECT id FROM alerts ORDER BY id DESC LIMIT -1 OFFSET 999)')
            db.execute('UPDATE devices SET received=?,report=?,state=? WHERE id=?', (now, payload, 'online', identity))
            db.execute('INSERT INTO samples(device,received,report) VALUES(?,?,?)', (identity, now, payload))
            if row['state'] != 'online':
                db.execute('INSERT INTO alerts(device,at,state) VALUES(?,?,?)', (identity, now, 'recovered' if row['state'] == 'offline' else 'first_report'))
        self.last_monotonic[identity] = time.monotonic()
        self.receipt_times[identity] = now

    def status(self):
        now, mono = self.clock(), time.monotonic()
        with self.lock, self.db() as db:
            rows = db.execute('SELECT * FROM devices ORDER BY name').fetchall()
            devices = []
            for row in rows:
                anchor = row['received'] if row['received'] is not None else row['created']
                age = max(0, now - anchor)
                if row['received'] is not None and self.receipt_times.get(row['id']) != anchor:
                    # A report may have been committed by another/previous process.
                    self.last_monotonic[row['id']] = mono - age
                    self.receipt_times[row['id']] = anchor
                elapsed = mono - self.last_monotonic[row['id']] if row['id'] in self.last_monotonic else age
                state = 'offline' if elapsed >= row['timeout'] else ('online' if row['received'] is not None else 'pending')
                if state == 'offline' and row['state'] != state:
                    db.execute('UPDATE devices SET state=? WHERE id=?', (state, row['id']))
                    db.execute('INSERT INTO alerts(device,at,state) VALUES(?,?,?)', (row['id'], now, state))
                devices.append({'id': row['id'], 'name': row['name'], 'timeout': row['timeout'], 'state': state,
                                'received_at': row['received'], 'age_seconds': round(max(0, elapsed)),
                                'report': json.loads(row['report']) if row['report'] else None})
            db.execute('DELETE FROM samples WHERE received<?', (now - 7 * 86400,))
            db.execute('DELETE FROM alerts WHERE id IN (SELECT id FROM alerts ORDER BY id DESC LIMIT -1 OFFSET 1000)')
            alerts = [dict(r) for r in db.execute('SELECT a.id,a.at,a.state,d.name FROM alerts a JOIN devices d ON a.device=d.id ORDER BY a.id DESC LIMIT 100')]
            count = db.execute('SELECT count(*) FROM samples').fetchone()[0]
        return {'server_time': now, 'devices': devices, 'alerts': alerts, 'samples': count, 'database_bytes': Path(self.path).stat().st_size}


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, store, token):
        self.store, self.token = store, token
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version = 'VsaasHealth/1'

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *args):
        pass  # Never log tokens, device payloads, URLs or headers.

    def reply(self, code, data, content_type='application/json'):
        body = data if isinstance(data, bytes) else json.dumps(data, allow_nan=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', content_type + '; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def token(self):
        value = self.headers.get('Authorization', '')
        return value[7:] if value.startswith('Bearer ') and len(value) <= 300 else ''

    def admin(self):
        return hmac.compare_digest(digest(self.token()), digest(self.server.token))

    def do_GET(self):
        static = {'/': ('collector.html', 'text/html'), '/collector.js': ('collector.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}
        if self.path in static:
            filename, kind = static[self.path]
            self.reply(200, Path(__file__).with_name(filename).read_bytes(), kind)
        elif self.path == '/api/status':
            if not self.admin():
                self.reply(401, {'error': 'No autorizado.'})
                return
            self.reply(200, self.server.store.status())
        else:
            self.reply(404, {'error': 'Ruta no encontrada.'})

    def do_POST(self):
        try:
            # No browser cross-origin writes and no CORS. Ingest authenticates each device.
            if self.headers.get('Origin') and self.headers.get('Sec-Fetch-Site') not in ('same-origin', 'none'):
                self.reply(403, {'error': 'Origen no permitido.'})
                return
            if self.path != '/api/heartbeat' and not self.admin():
                self.reply(401, {'error': 'No autorizado.'})
                return
            length = int(self.headers.get('Content-Length', '-1'))
            if self.headers.get('Transfer-Encoding') or not 0 < length <= MAX_BODY:
                self.reply(413, {'error': 'Tamaño no permitido.'})
                return
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                self.reply(415, {'error': 'Usa application/json.'})
                return
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError('Reporte incompleto.')
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError('Se esperaba un objeto JSON.')
            if self.path == '/api/heartbeat':
                self.server.store.receive(data, self.token())
                result = {'ok': True}
            elif self.path == '/api/devices':
                result = self.server.store.add(data)
            elif self.path == '/api/device-settings':
                self.server.store.configure(data)
                result = {'ok': True}
            elif self.path == '/api/rotate':
                result = self.server.store.rotate(data.get('id'))
            else:
                self.reply(404, {'error': 'Ruta no encontrada.'})
                return
            self.reply(200, result)
        except PermissionError:
            self.reply(401, {'error': 'No autorizado.'})
        except (ValueError, TypeError, KeyError, UnicodeError):
            self.reply(400, {'error': 'Datos no válidos o equipo ya registrado. Revisa identificador, nombre y tiempos.'})
        except sqlite3.Error:
            self.reply(503, {'error': 'Almacenamiento ocupado o sin capacidad; no se confirmó la recepción.'})


@contextlib.contextmanager
def exclusive(path):
    handle = Path(path).open('a+b')
    if handle.tell() == 0:
        handle.write(b'0')
        handle.flush()
    handle.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise ValueError('Ya hay un colector usando este directorio de datos. Detén la instancia anterior antes de iniciar otra.') from None
    try:
        yield
    finally:
        handle.close()


def serve(args, token):
    store = Store(args.data / 'health.sqlite3')
    servers = []
    stop = threading.Event()
    try:
        servers.append(Server((args.listen, args.port), store, token))
        if not ipaddress.ip_address(args.listen).is_loopback and args.listen != '0.0.0.0':
            # Both entry points share one Store and one monotonic clock cache.
            servers.append(Server(('127.0.0.1', args.port), store, token))

        def watch():
            while not stop.wait(5):
                try:
                    store.status()
                except (OSError, sqlite3.Error):
                    pass

        threading.Thread(target=watch, daemon=True).start()
        for server in servers[1:]:
            threading.Thread(target=server.serve_forever, daemon=True).start()
        print('Colector local/VPN: http://' + args.listen + ':' + str(args.port), flush=True)
        print('Panel local: http://127.0.0.1:' + str(args.port), flush=True)
        print('Llave del panel: ejecuta el mismo comando con --show-key. Mantén esta ventana abierta.', flush=True)
        try:
            servers[0].serve_forever()
        except KeyboardInterrupt:
            pass
    finally:
        stop.set()
        for server in servers[1:]:
            server.shutdown()
        for server in servers:
            server.server_close()


def main():
    parser = argparse.ArgumentParser(description='Colector de salud local/VPN; no publicar directamente en Internet.')
    parser.add_argument('--listen', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8082)
    parser.add_argument('--data', type=Path, default=Path.home() / '.vsaas-salud')
    parser.add_argument('--show-key', action='store_true')
    args = parser.parse_args()
    ipaddress.ip_address(args.listen)
    if not 1 <= args.port <= 65535:
        parser.error('Puerto no válido.')
    args.data.mkdir(mode=0o700, parents=True, exist_ok=True)
    key_file = args.data / 'admin.token'
    if not key_file.exists():
        key_file.write_text(secrets.token_urlsafe(32), encoding='utf-8')
        key_file.chmod(0o600)
    token = key_file.read_text(encoding='utf-8').strip()
    if args.show_key:
        print(token)
        return
    with exclusive(args.data / 'collector.lock'):
        serve(args, token)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        raise SystemExit(str(error))
