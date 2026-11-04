import logging
import threading
import time

from .onvif import OnvifClient, OnvifHTTPError
from .rtsp import RTSPMetadataClient, parse_metadata

log = logging.getLogger(__name__)


class Manager:
    def __init__(self, store):
        self.store = store
        self.workers = {}
        self.metadata_workers = {}

    def start(self, camera):
        if camera['mode'] == 'webhook':
            self.store.status(camera['id'], 'esperando HTTP')
            return
        stop = threading.Event()
        thread = threading.Thread(target=self.run, args=(camera, stop), daemon=True)
        self.workers[camera['id']] = (stop, thread)
        thread.start()
        if camera.get('metadata_rtsp_url'):
            metadata_thread = threading.Thread(target=self.run_metadata, args=(camera, stop), daemon=True)
            self.metadata_workers[camera['id']] = (stop, metadata_thread)
            metadata_thread.start()

    def stop(self, camera_id):
        workers = [worker for worker in (self.workers.pop(camera_id, None),
                   self.metadata_workers.pop(camera_id, None)) if worker]
        for stop, _ in workers:
            stop.set()
        for _, thread in workers:
            thread.join(timeout=50)

    def close(self):
        workers = list(self.workers.values()) + list(self.metadata_workers.values())
        for stop, _ in workers:
            stop.set()
        for _, thread in workers:
            thread.join(timeout=50)

    def run(self, camera, stop):
        delay = 1
        while not stop.is_set():
            client, subscription = OnvifClient(camera), None
            try:
                self.store.status(camera['id'], 'conectando')
                event_url = client.discover()
                subscription, deadline = client.subscribe(event_url)
                self.store.status(camera['id'], 'conectada')
                pull_errors = 0
                while not stop.is_set():
                    if deadline - time.monotonic() < 35:
                        deadline = client.renew(subscription)
                    remaining = deadline - time.monotonic()
                    if remaining < 3:
                        raise ValueError('Duración de suscripción insuficiente')
                    started = time.monotonic()
                    try:
                        raw, events = client.pull(subscription, max(1, min(20, int(remaining - 2))))
                        pull_errors = 0
                    except OnvifHTTPError as exc:
                        # Some NVRs return HTTP 500 on the first pull of every new subscription.
                        # Keep the subscription alive for two bounded retries before reconnecting.
                        if exc.status_code != 500 or pull_errors >= 2:
                            raise
                        pull_errors += 1
                        self.store.status(camera['id'], 'reintentando', str(exc))
                        log.warning('Cámara %s: %s; reintento %s/2 en la misma suscripción',
                                    camera['id'], exc, pull_errors)
                        if stop.wait(pull_errors):
                            break
                        continue
                    if events:
                        # Do not consume another batch until this one has committed.
                        while True:
                            try:
                                self.store.save(camera['id'], 'onvif', raw, 'application/soap+xml', events)
                                break
                            except Exception:
                                log.error('No se pudo guardar el lote de %s; se reintentará', camera['id'])
                                self.store.status(camera['id'], 'error de almacenamiento', 'No se pudo guardar el lote recibido')
                                if stop.wait(2):
                                    return
                    self.store.status(camera['id'], 'conectada')
                    delay = 1
                    stop.wait(max(0, 0.25 - (time.monotonic() - started)))
            except Exception as exc:
                error = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                self.store.status(camera['id'], 'reintentando', error[:180])
                log.warning('Cámara %s: %s', camera['id'], error[:180])
            finally:
                if subscription:
                    try:
                        client.unsubscribe(subscription)
                    except Exception:
                        pass
                client.session.close()
            if stop.wait(delay):
                break
            delay = min(delay * 2, 60)
        self.store.status(camera['id'], 'detenida')

    def run_metadata(self, camera, stop):
        delay = 1
        while not stop.is_set():
            client = RTSPMetadataClient(camera['metadata_rtsp_url'], camera['username'], camera['password'])
            try:
                self.store.set_metadata_status(camera['id'], 'conectando')
                client.open()
                self.store.set_metadata_status(camera['id'], 'conectada')
                for raw in client.documents(stop):
                    try:
                        events = parse_metadata(raw)
                    except Exception:
                        events = [{'topic': 'ONVIF/Metadata/Unparsed', 'metadata': {'parse_error': True}}]
                    if not events:
                        events = [{'topic': 'ONVIF/Metadata', 'metadata': {}}]
                    for event in events:
                        event['metadata']['rtsp_source'] = camera['metadata_rtsp_url']
                    # Commit this complete XML document before consuming another one.
                    while True:
                        try:
                            self.store.save(camera['id'], 'rtsp_metadata', raw, 'application/xml', events)
                            break
                        except Exception:
                            log.error('No se pudo guardar metadato RTP de %s; se reintentará', camera['id'])
                            if stop.wait(2):
                                return
                    self.store.set_metadata_status(camera['id'], 'conectada')
                    delay = 1
            except Exception as exc:
                error = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                self.store.set_metadata_status(camera['id'], 'reintentando', error[:180])
                log.warning('Metadatos RTSP de %s: %s', camera['id'], error[:180])
            finally:
                client.close()
            if stop.wait(delay):
                break
            delay = min(delay * 2, 60)
        self.store.set_metadata_status(camera['id'], 'detenida')
