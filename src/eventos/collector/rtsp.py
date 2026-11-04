"""Receive ONVIF XML metadata over RTSP/TCP without requesting video or audio."""
import base64
from collections import deque
import re
import select
import socket
import time
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

from defusedxml.ElementTree import fromstring
from requests.auth import HTTPDigestAuth
from requests.utils import parse_dict_header

from .onvif import NS, parse_events

MAX_XML = 8 * 1024 * 1024


def xml_tree(node):
    result = {'tag': node.tag, 'attributes': dict(node.attrib)}
    if node.text and node.text.strip():
        result['text'] = node.text.strip()
    if len(node):
        result['children'] = [xml_tree(child) for child in node]
    return result


def parse_metadata(raw):
    root = fromstring(raw)
    events = parse_events(raw)
    for frame in root.iter('{' + NS['tt'] + '}Frame'):
        objects = []
        for obj in frame.findall('tt:Object', NS):
            classes = []
            for candidate in obj.findall('.//tt:ClassCandidate', NS):
                classes.append({'type': candidate.findtext('tt:Type', namespaces=NS),
                                'likelihood': candidate.findtext('tt:Likelihood', namespaces=NS)})
            box = obj.find('.//tt:BoundingBox', NS)
            objects.append({'object_id': obj.get('ObjectId'), 'classes': classes,
                            'bounding_box': dict(box.attrib) if box is not None else None,
                            'details': xml_tree(obj)})
        events.append({'topic': 'ONVIF/VideoAnalytics/Objects', 'source_time': frame.get('UtcTime'),
                       'metadata': {'attributes': dict(frame.attrib), 'objects': objects,
                                    'frame_xml': ET.tostring(frame, encoding='unicode')}})
    return events


class RTPMetadataAssembler:
    def __init__(self):
        self.timestamp = None
        self.sequence = None
        self.buffer = bytearray()
        self.damaged = False

    def feed(self, packet):
        if len(packet) < 12 or packet[0] >> 6 != 2:
            raise ValueError('Paquete RTP inválido')
        sequence = int.from_bytes(packet[2:4], 'big')
        timestamp = int.from_bytes(packet[4:8], 'big')
        offset = 12 + 4 * (packet[0] & 15)
        if offset > len(packet):
            raise ValueError('Cabecera RTP truncada')
        if packet[0] & 16:
            if offset + 4 > len(packet):
                raise ValueError('Extensión RTP truncada')
            offset += 4 + 4 * int.from_bytes(packet[offset + 2:offset + 4], 'big')
        padding = packet[-1] if packet[0] & 32 else 0
        if offset > len(packet) - padding or ((packet[0] & 32) and padding == 0):
            raise ValueError('Longitud RTP inválida')
        if timestamp != self.timestamp:
            self.buffer.clear()
            self.damaged = False
        elif self.sequence is not None and sequence != (self.sequence + 1) % 65536:
            self.damaged = True
        self.timestamp, self.sequence = timestamp, sequence
        self.buffer.extend(packet[offset:len(packet) - padding if padding else len(packet)])
        if len(self.buffer) > MAX_XML:
            raise ValueError('Documento de metadatos superior a 8 MiB')
        if packet[1] & 128:
            result = None if self.damaged else bytes(self.buffer)
            self.buffer.clear()
            self.timestamp = self.sequence = None
            self.damaged = False
            return result
        return None


def metadata_track(sdp, base):
    current = None
    for line in sdp.splitlines():
        line = line.strip()
        if line.startswith('m='):
            if current and current.get('metadata') and current.get('control'):
                return urljoin(base, current['control']), current['payload_type']
            current = {'application': line.startswith('m=application ')}
        elif current is not None and line.startswith('a=control:'):
            current['control'] = line.split(':', 1)[1]
        elif current is not None and line.startswith('a=rtpmap:') and 'vnd.onvif.metadata/' in line.lower():
            current['metadata'] = current['application']
            current['payload_type'] = int(line.split(':', 1)[1].split()[0])
    if current and current.get('metadata') and current.get('control'):
        return urljoin(base, current['control']), current['payload_type']
    raise ValueError('El NVR no anuncia una pista ONVIF de metadatos en este canal')


class RTSPError(ValueError):
    def __init__(self, operation, status):
        self.status = status
        super().__init__(f'RTSP {status} al ejecutar {operation}')


class RTSPMetadataClient:
    def __init__(self, url, username, password):
        parsed = urlparse(url)
        if parsed.scheme != 'rtsp' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Usa una URL rtsp:// sin credenciales incluidas')
        self.url, self.host = url, parsed.hostname
        self.port = parsed.port or 554
        self.username, self.password = username, password
        self.auth = HTTPDigestAuth(username, password)
        self.auth.init_per_thread_state()
        self.auth_mode = None
        self.socket = None
        self.buffer = bytearray()
        self.pending = deque()
        self.sequence = 0
        self.session = None
        self.channel = 0

    def _exact(self, size):
        while len(self.buffer) < size:
            chunk = self.socket.recv(65536)
            if not chunk:
                raise ConnectionError('El NVR cerró el flujo de metadatos')
            self.buffer.extend(chunk)
        result = bytes(self.buffer[:size])
        del self.buffer[:size]
        return result

    def _line(self):
        while b'\n' not in self.buffer:
            if len(self.buffer) > 65536:
                raise ValueError('Cabecera RTSP demasiado grande')
            chunk = self.socket.recv(65536)
            if not chunk:
                raise ConnectionError('Respuesta RTSP incompleta')
            self.buffer.extend(chunk)
        end = self.buffer.index(b'\n') + 1
        result = bytes(self.buffer[:end])
        del self.buffer[:end]
        return result

    def _packet_after_marker(self):
        header = self._exact(3)
        return header[0], self._exact(int.from_bytes(header[1:], 'big'))

    def _response(self):
        while True:
            first = self._exact(1)
            if first == b'$':
                if len(self.pending) >= 256:
                    raise ValueError('Demasiados metadatos pendientes durante la respuesta RTSP')
                self.pending.append(self._packet_after_marker())
                continue
            status = (first + self._line()).decode('latin1').strip().split()
            if len(status) < 2 or status[0] != 'RTSP/1.0':
                raise ValueError('Respuesta RTSP inválida')
            headers, total = {}, 0
            while True:
                line = self._line()
                total += len(line)
                if total > 65536:
                    raise ValueError('Cabeceras RTSP demasiado grandes')
                if line in (b'\r\n', b'\n'):
                    break
                key, value = line.decode('latin1').split(':', 1)
                headers[key.lower()] = value.strip()
            size = int(headers.get('content-length', '0'))
            if size < 0 or size > MAX_XML:
                raise ValueError('Respuesta RTSP demasiado grande')
            return int(status[1]), headers, self._exact(size)

    def call(self, method, url, extra=()):
        for attempt in range(2):
            self.sequence += 1
            lines = [f'{method} {url} RTSP/1.0', f'CSeq: {self.sequence}', 'User-Agent: CameraMetadataCollector/1.0']
            if self.auth_mode == 'digest':
                value = self.auth.build_digest_header(method, url)
                if not value:
                    raise ValueError('Algoritmo de autenticación RTSP no compatible')
                lines.append('Authorization: ' + value)
            elif self.auth_mode == 'basic':
                value = base64.b64encode((self.username + ':' + self.password).encode()).decode()
                lines.append('Authorization: Basic ' + value)
            if self.session:
                lines.append('Session: ' + self.session)
            lines.extend(extra)
            self.socket.sendall(('\r\n'.join(lines) + '\r\n\r\n').encode('utf-8'))
            status, headers, body = self._response()
            if status == 401 and attempt == 0:
                challenge = headers.get('www-authenticate', '')
                if challenge.lower().startswith('digest '):
                    self.auth._thread_local.chal = parse_dict_header(challenge[7:])
                    self.auth_mode = 'digest'
                elif challenge.lower().startswith('basic '):
                    self.auth_mode = 'basic'
                else:
                    raise ValueError('Autenticación RTSP no compatible')
                continue
            if status != 200:
                raise RTSPError(method, status)
            if 'session' in headers:
                self.session = headers['session'].split(';', 1)[0]
            return headers, body

    def open(self):
        self.socket = socket.create_connection((self.host, self.port), timeout=8)
        headers, body = self.call('DESCRIBE', self.url, ['Accept: application/sdp'])
        base = headers.get('content-base', self.url.rstrip('/') + '/')
        track, self.payload_type = metadata_track(body.decode('utf-8', 'replace'), base)
        parsed = urlparse(track)
        if parsed.hostname != self.host or parsed.scheme != 'rtsp' or parsed.username or parsed.password:
            raise ValueError('El NVR anunció una pista fuera de su dirección RTSP')
        headers, _ = self.call('SETUP', track, ['Transport: RTP/AVP/TCP;unicast;interleaved=0-1'])
        channels = re.search(r'interleaved=(\d+)-(\d+)', headers.get('transport', ''), flags=re.I)
        if channels:
            self.channel = int(channels.group(1))
        self.call('PLAY', self.url, ['Range: npt=0.000-'])

    def documents(self, stop):
        assembler = RTPMetadataAssembler()
        keepalive = time.monotonic()
        while not stop.is_set():
            if time.monotonic() - keepalive >= 20:
                try:
                    self.call('GET_PARAMETER', self.url)
                except RTSPError as error:
                    if error.status not in (400, 405, 501):
                        raise
                    self.call('OPTIONS', self.url)
                keepalive = time.monotonic()
            if self.pending:
                channel, packet = self.pending.popleft()
            else:
                if not self.buffer and not select.select([self.socket], [], [], 1)[0]:
                    continue
                if self._exact(1) != b'$':
                    raise ValueError('El NVR envió datos fuera del transporte RTP/TCP')
                channel, packet = self._packet_after_marker()
            if channel != self.channel or len(packet) < 2 or packet[1] & 127 != self.payload_type:
                continue
            raw = assembler.feed(packet)
            if raw:
                yield raw

    def close(self):
        if self.socket is not None:
            if self.session:
                try:
                    self.socket.settimeout(2)
                    self.call('TEARDOWN', self.url)
                except Exception:
                    pass
            self.socket.close()
            self.socket = None
