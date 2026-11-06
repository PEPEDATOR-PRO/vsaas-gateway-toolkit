import asyncio
import hmac
import json
import os
import secrets
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator

from .manager import Manager
from .onvif import parse_events
from .storage import Store, StorageFull
from .forwarding import Forwarder
from .capabilities import inspect_camera


class MetadataSource(BaseModel):
    metadata_rtsp_url: str = Field(default='', max_length=2048)

    @field_validator('metadata_rtsp_url')
    @classmethod
    def validate_rtsp_url(cls, value):
        value = value.strip()
        if not value:
            return value
        parsed = urlparse(value)
        try:
            parsed.port
        except ValueError:
            raise ValueError('Puerto RTSP inválido') from None
        if parsed.scheme != 'rtsp' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError('Usa una URL rtsp:// sin usuario ni contraseña incluidos')
        if '\r' in value or '\n' in value:
            raise ValueError('Dirección RTSP inválida')
        return value


class Camera(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    mode: Literal['onvif', 'webhook'] = 'onvif'
    device_url: str = ''
    username: str = Field(default='', max_length=256)
    password: str = Field(default='', max_length=1024)
    verify_tls: bool = True
    clock_offset_seconds: int = Field(default=0, ge=-86400, le=86400)

    @field_validator('device_url')
    @classmethod
    def validate_url(cls, value):
        if not value:
            return value
        if '://' not in value:
            value = 'http://' + value
        parsed = urlparse(value)
        try:
            parsed.port
        except ValueError:
            raise ValueError('Puerto inválido') from None
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError('Usa IP o URL HTTP(S) sin credenciales')
        if not parsed.path or parsed.path == '/':
            value = value.rstrip('/') + '/onvif/device_service'
        return value

    @model_validator(mode='after')
    def validate_mode(self):
        if self.mode == 'onvif' and (not self.device_url or not self.username or not self.password):
            raise ValueError('ONVIF requiere dirección, usuario y contraseña')
        return self


def create_app(data_dir=None):
    store = Store(data_dir or os.environ.get('COLLECTOR_DATA_DIR', 'data'))
    token_file = store.directory / 'admin.token'
    try:
        with token_file.open('x', encoding='utf-8') as handle:
            handle.write(secrets.token_urlsafe(32))
        os.chmod(token_file, 0o600)
    except FileExistsError:
        pass
    token = os.environ.get('COLLECTOR_ADMIN_TOKEN') or token_file.read_text().strip()
    viewer_file = store.directory / 'viewer.token'
    try:
        with viewer_file.open('x', encoding='utf-8') as handle:
            handle.write(secrets.token_urlsafe(32))
        os.chmod(viewer_file, 0o600)
    except FileExistsError:
        pass
    viewer_token = os.environ.get('COLLECTOR_VIEWER_TOKEN') or viewer_file.read_text().strip()
    if not viewer_token or hmac.compare_digest(viewer_token.encode(), token.encode()):
        raise ValueError('La llave de consulta debe ser distinta de la llave de administración')
    manager = Manager(store)
    forwarder=Forwarder(store)
    inspection_slots = threading.BoundedSemaphore(2)
    inspections = set()
    inspection_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(app):
        forwarder.start()
        for camera in store.cameras(secrets=True):
            manager.start(camera)
        yield
        await asyncio.to_thread(forwarder.close)
        await asyncio.to_thread(manager.close)

    app = FastAPI(title='Colector de eventos de cámaras', version='1.0.0', lifespan=lifespan)
    app.mount('/assets', StaticFiles(directory=Path(__file__).with_name('static')), name='assets')
    app.state.store = store
    app.state.manager = manager
    app.state.forwarder=forwarder

    def authorize(request: Request):
        supplied = request.headers.get('Authorization', '').removeprefix('Bearer ')
        if not hmac.compare_digest(supplied.encode(), token.encode()):
            if hmac.compare_digest(supplied.encode(), viewer_token.encode()):
                raise HTTPException(403, 'La llave de consulta no permite modificar cámaras')
            raise HTTPException(401, 'Token de administración incorrecto')

    def authorize_read(request: Request):
        supplied = request.headers.get('Authorization', '').removeprefix('Bearer ')
        if hmac.compare_digest(supplied.encode(), token.encode()):
            return 'admin'
        if hmac.compare_digest(supplied.encode(), viewer_token.encode()):
            return 'viewer'
        raise HTTPException(401, 'Llave de acceso incorrecta')

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        return Response(content='{"detail":"Error interno; revisa el servicio y el espacio en disco"}',
                        status_code=500, media_type='application/json')

    @app.exception_handler(StorageFull)
    async def storage_full(request,exc):
        return Response(content=json.dumps({'detail':str(exc)}),status_code=503,media_type='application/json')

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Do not echo passwords or entire camera configurations in validation errors.
        errors = [{'loc': e['loc'], 'msg': e['msg'], 'type': e['type']} for e in exc.errors()]
        return Response(content=json.dumps({'detail': errors}), status_code=422,
                        media_type='application/json')

    @app.get('/', include_in_schema=False)
    def index():
        return FileResponse(Path(__file__).with_name('index.html'))

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    @app.get('/api/status')
    def status(access_role: str = Depends(authorize_read)):
        cameras = store.cameras()
        if access_role == 'viewer':
            cameras = [{key: camera.get(key) for key in
                        ('id', 'name', 'mode', 'status', 'last_error', 'last_seen',
                         'metadata_enabled', 'metadata_status', 'metadata_last_error', 'metadata_last_seen')} for camera in cameras]
        return {'events': store.count(), 'cameras': cameras, 'access_role': access_role,'storage':store.storage_status()}

    @app.post('/api/cameras', status_code=201, dependencies=[Depends(authorize)])
    def add_camera(camera: Camera):
        config = camera.model_dump()
        webhook_token = secrets.token_urlsafe(32)
        camera_id = store.add_camera(dict(config, webhook_token=webhook_token))
        saved = next(c for c in store.cameras(secrets=True) if c['id'] == camera_id)
        manager.start(saved)
        return {'id': camera_id, 'webhook_path': f'/ingest/{camera_id}',
                'webhook_token': webhook_token if camera.mode == 'webhook' else None}

    @app.delete('/api/cameras/{camera_id}', dependencies=[Depends(authorize)])
    def delete_camera(camera_id: str):
        if not any(c['id'] == camera_id for c in store.cameras()):
            raise HTTPException(404, 'Cámara no encontrada')
        manager.stop(camera_id)
        store.delete_camera(camera_id)
        return {'deleted': True, 'history_preserved': True}

    @app.post('/api/cameras/{camera_id}/capabilities', dependencies=[Depends(authorize)])
    def camera_capabilities(camera_id: str):
        camera = next((c for c in store.cameras(secrets=True) if c['id'] == camera_id), None)
        if camera is None:
            raise HTTPException(404, 'Cámara no encontrada')
        with inspection_lock:
            if camera_id in inspections or not inspection_slots.acquire(blocking=False):
                raise HTTPException(409, 'Hay una consulta en curso. Espera a que termine e inténtalo de nuevo.')
            inspections.add(camera_id)
        try:
            samples = store.capability_samples(camera_id)
            return inspect_camera(camera, samples)
        finally:
            with inspection_lock:
                inspections.discard(camera_id)
                inspection_slots.release()

    @app.put('/api/cameras/{camera_id}/metadata', dependencies=[Depends(authorize)])
    def configure_metadata(camera_id: str, source: MetadataSource):
        camera = next((c for c in store.cameras(secrets=True) if c['id'] == camera_id), None)
        if camera is None:
            raise HTTPException(404, 'Cámara no encontrada')
        if camera['mode'] != 'onvif':
            raise HTTPException(400, 'Configura metadatos en una conexión ONVIF')
        if source.metadata_rtsp_url and urlparse(source.metadata_rtsp_url).hostname != urlparse(camera['device_url']).hostname:
            raise HTTPException(400, 'La pista RTSP debe pertenecer al mismo equipo ONVIF')
        manager.stop(camera_id)
        store.configure_metadata(camera_id, source.metadata_rtsp_url)
        updated = next(c for c in store.cameras(secrets=True) if c['id'] == camera_id)
        manager.start(updated)
        return {'id': camera_id, 'metadata_enabled': bool(source.metadata_rtsp_url)}

    @app.get('/api/forwarding',dependencies=[Depends(authorize_read)])
    def forwarding_status():return forwarder.status()

    @app.put('/api/forwarding',dependencies=[Depends(authorize)])
    def forwarding_config(data: dict):
        try:return forwarder.configure(data)
        except ValueError as exc:raise HTTPException(422,str(exc)) from None

    @app.post('/api/forwarding/test',dependencies=[Depends(authorize)])
    def forwarding_test():
        try:return forwarder.test()
        except ValueError as exc:raise HTTPException(422,str(exc)) from None

    @app.get('/api/events', dependencies=[Depends(authorize_read)])
    def events(camera_id: str | None = None, topic: str | None = None,
               after_id: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000),
               order: Literal['asc', 'desc'] = 'asc',
               before_id: int | None = Query(None, ge=1), include_raw: bool = True):
        return store.events(camera_id, topic, after_id, limit, order, before_id, include_raw)

    @app.get('/api/events/{event_id}/raw', dependencies=[Depends(authorize_read)])
    def raw_event(event_id: int):
        with store.connect() as db:
            row = db.execute('SELECT raw FROM events WHERE id=?', (event_id,)).fetchone()
        if row is None:
            raise HTTPException(404, 'Evento no encontrado')
        return Response(bytes(row['raw']), media_type='application/octet-stream',
                        headers={'Content-Disposition': f'attachment; filename="evento-{event_id}.bin"'})

    @app.post('/ingest/{camera_id}', status_code=201)
    async def ingest(camera_id: str, request: Request):
        camera = next((c for c in store.cameras(secrets=True) if c['id'] == camera_id and c['mode'] == 'webhook'), None)
        supplied = request.headers.get('X-Camera-Token', '') or request.headers.get('Authorization', '').removeprefix('Bearer ')
        if camera is None or not hmac.compare_digest(supplied.encode(), camera['webhook_token'].encode()):
            raise HTTPException(401, 'Cámara o token incorrectos')
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 8 * 1024 * 1024:
                raise HTTPException(413, 'Límite de mensaje: 8 MB')
        raw = bytes(body)
        content_type = request.headers.get('content-type', 'application/octet-stream')
        parsed_events = []
        metadata, topic = {}, 'http/raw'
        try:
            if 'xml' in content_type or raw.lstrip().startswith(b'<'):
                parsed_events = parse_events(raw)
                topic = 'http/xml'
            elif 'json' in content_type:
                metadata = json.loads(raw)
                topic = 'http/json'
        except Exception:
            # Even malformed or unknown vendor payloads are retained verbatim.
            metadata = {'parse_error': True}
        parsed_events = parsed_events or [{'topic': topic, 'metadata': metadata}]
        await asyncio.to_thread(store.save, camera_id, 'http', raw, content_type, parsed_events)
        await asyncio.to_thread(store.status, camera_id, 'conectada')
        return {'stored': len(parsed_events)}

    return app
