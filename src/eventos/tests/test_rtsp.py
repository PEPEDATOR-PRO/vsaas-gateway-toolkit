import base64
import hashlib
import socketserver
import struct
import threading
import time
from urllib.parse import urlparse

import pytest
from requests.utils import parse_dict_header

from collector.manager import Manager
from collector.rtsp import MAX_XML, RTPMetadataAssembler, RTSPMetadataClient, metadata_track, parse_metadata
from collector.storage import Store

XML = b'''<tt:MetadataStream xmlns:tt="http://www.onvif.org/ver10/schema" xmlns:v="urn:vendor">
<tt:VideoAnalytics><tt:Frame UtcTime="2026-10-21T18:00:00Z"><tt:Transformation><tt:Scale x="1" y="1"/></tt:Transformation>
<tt:Object ObjectId="7"><tt:Appearance><tt:Shape><tt:BoundingBox left="-0.5" top="0.7" right="0.5" bottom="-0.7"/></tt:Shape>
<tt:Class><tt:ClassCandidate><tt:Type>Human</tt:Type><tt:Likelihood>0.98</tt:Likelihood></tt:ClassCandidate></tt:Class>
<v:Clothing><v:ColorString>Blue</v:ColorString></v:Clothing></tt:Appearance></tt:Object>
</tt:Frame></tt:VideoAnalytics></tt:MetadataStream>'''


def rtp(payload, sequence=1, timestamp=123, marker=True):
    return struct.pack('!BBHII', 0x80, 107 | (128 if marker else 0), sequence, timestamp, 10) + payload


def test_rtp_reassembly_packet_loss_and_wraparound():
    assembler = RTPMetadataAssembler()
    assert assembler.feed(rtp(XML[:80], 65535, marker=False)) is None
    assert assembler.feed(rtp(XML[80:], 0)) == XML
    assert assembler.feed(rtp(b'<partial', 10, marker=False)) is None
    assert assembler.feed(rtp(b'/>', 12)) is None
    assert assembler.feed(rtp(XML, 13, timestamp=124)) == XML
    with pytest.raises(ValueError):
        assembler.feed(b'short')


def test_rtp_csrc_extension_padding_and_size_limit():
    packet = struct.pack('!BBHII', 0xB1, 235, 1, 2, 3) + b'csrc' + b'\x00\x01\x00\x01' + b'extn' + XML + b'\x00\x00\x00\x04'
    assert RTPMetadataAssembler().feed(packet) == XML
    assembler = RTPMetadataAssembler()
    assembler.buffer.extend(b'x' * MAX_XML)
    assembler.timestamp = 123
    with pytest.raises(ValueError, match='8 MiB'):
        assembler.feed(rtp(b'overflow'))


def test_metadata_parse_keeps_ai_objects_and_vendor_attributes():
    events = parse_metadata(XML)
    assert len(events) == 1
    event = events[0]
    assert event['topic'] == 'ONVIF/VideoAnalytics/Objects'
    assert event['source_time'] == '2026-10-21T18:00:00Z'
    obj = event['metadata']['objects'][0]
    assert obj['object_id'] == '7'
    assert obj['classes'] == [{'type': 'Human', 'likelihood': '0.98'}]
    assert obj['bounding_box']['left'] == '-0.5'
    assert 'Blue' in str(obj['details'])
    assert 'Blue' in event['metadata']['frame_xml']
    with pytest.raises(Exception):
        parse_metadata(b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>')


def test_track_selection_requests_only_metadata():
    sdp = 'm=video 0 RTP/AVP 98\na=control:video\nm=application 0 RTP/AVP 107\na=control:trackID=m\na=rtpmap:107 vnd.onvif.metadata/90000/1\nm=audio 0 RTP/AVP 0\na=control:audio\n'
    assert metadata_track(sdp, 'rtsp://127.0.0.1/live/') == ('rtsp://127.0.0.1/live/trackID=m', 107)
    with pytest.raises(ValueError):
        metadata_track('m=video 0 RTP/AVP 98', 'rtsp://127.0.0.1/')


@pytest.fixture
def rtsp_server():
    state = {'methods': [], 'errors': []}

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            try:
                while True:
                    line = self.rfile.readline()
                    if not line:
                        return
                    method, uri, _ = line.decode().strip().split()
                    headers = {}
                    while True:
                        line = self.rfile.readline()
                        if line == b'\r\n':
                            break
                        key, value = line.decode().split(':', 1)
                        headers[key.lower()] = value.strip()
                    state['methods'].append(method)
                    if 'authorization' not in headers:
                        self.wfile.write(b'RTSP/1.0 401 Unauthorized\r\nWWW-Authenticate: Digest realm="nvr", nonce="sample", algorithm=MD5, qop="auth"\r\nContent-Length: 0\r\n\r\n')
                        continue
                    values = parse_dict_header(headers['authorization'][7:])
                    assert values['uri'] in (uri, urlparse(uri).path)
                    md5 = lambda value: hashlib.md5(value.encode()).hexdigest()
                    expected = md5(':'.join([md5('user:nvr:secret'), 'sample', values['nc'], values['cnonce'], 'auth', md5(method + ':' + values['uri'])]))
                    assert values['response'] == expected
                    body = b''
                    extra = ['Session: test-session;timeout=60']
                    if method == 'DESCRIBE':
                        base = f'rtsp://127.0.0.1:{self.server.server_address[1]}/live/'
                        extra.append('Content-Base: ' + base)
                        body = b'm=video 0 RTP/AVP 98\na=control:video\nm=application 0 RTP/AVP 107\na=control:trackID=m\na=rtpmap:107 vnd.onvif.metadata/90000/1\n'
                    if method == 'SETUP':
                        assert uri.endswith('/trackID=m')
                        assert headers['transport'] == 'RTP/AVP/TCP;unicast;interleaved=0-1'
                        extra.append('Transport: RTP/AVP/TCP;unicast;interleaved=0-1')
                    response = '\r\n'.join(['RTSP/1.0 200 OK', 'CSeq: ' + headers['cseq'], *extra, 'Content-Length: ' + str(len(body))])
                    self.wfile.write(response.encode() + b'\r\n\r\n' + body)
                    if method == 'PLAY':
                        for sequence, payload, marker in [(1, XML[:200], False), (2, XML[200:], True)]:
                            packet = rtp(payload, sequence, marker=marker)
                            self.wfile.write(b'$\x00' + len(packet).to_bytes(2, 'big') + packet)
                    if method == 'TEARDOWN':
                        return
            except Exception as exc:
                state['errors'].append(str(exc))

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True
    server = Server(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'rtsp://127.0.0.1:{server.server_address[1]}/live', state
    server.shutdown(); server.server_close(); thread.join()


def test_rtsp_digest_session_and_interleaved_rtp_during_keepalive(rtsp_server):
    url, state = rtsp_server
    client = RTSPMetadataClient(url, 'user', 'secret')
    stop = threading.Event()
    try:
        client.open()
        client.call('GET_PARAMETER', url)
        document = next(client.documents(stop))
        assert document == XML
    finally:
        stop.set(); client.close()
    assert state['methods'].count('SETUP') == 1
    assert state['methods'][-1] == 'TEARDOWN'
    assert not state['errors']


def test_metadata_worker_persists_nvr_frames_under_existing_id(tmp_path, rtsp_server):
    url, state = rtsp_server
    store = Store(tmp_path)
    camera_id = store.add_camera({'name': 'NVR', 'mode': 'onvif', 'device_url': 'http://127.0.0.1',
                                 'username': 'user', 'password': 'secret', 'metadata_rtsp_url': url})
    camera = store.cameras(secrets=True)[0]
    manager = Manager(store); stop = threading.Event()
    thread = threading.Thread(target=manager.run_metadata, args=(camera, stop), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while store.count() == 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        events = store.events(camera_id=camera_id)
        assert len(events) == 1
        assert events[0]['transport'] == 'rtsp_metadata'
        assert base64.b64decode(events[0]['raw_base64']) == XML
        assert events[0]['metadata']['objects'][0]['object_id'] == '7'
        assert store.cameras()[0]['metadata_enabled'] is True
    finally:
        stop.set(); thread.join(timeout=5)
    assert not thread.is_alive()
    assert not state['errors']
