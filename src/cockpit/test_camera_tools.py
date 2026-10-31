import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.error
import base64
import http.server
import threading

spec=importlib.util.spec_from_file_location('camera_scanner',Path(__file__).with_name('gateway-scanner.py'))
scanner=importlib.util.module_from_spec(spec);spec.loader.exec_module(scanner)
NET={'name':'eth0','addresses':['192.0.2.10/24']}
OPTIONS={'mode':'onvif','scheme':'http','port':80,'username':'test-user','password':'dummy-password'}
SUCCESS=b'<GetDeviceInformationResponse xmlns="http://www.onvif.org/ver10/device/wsdl"/>'
DENIED=b'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body><s:Fault><s:Code><s:Subcode><s:Value>ter:NotAuthorized</s:Value></s:Subcode></s:Code></s:Fault></s:Body></s:Envelope>'


class CameraTests(unittest.TestCase):
    def query(self,responses,options=None):
        with patch.object(scanner,'get_interface',return_value=NET),patch.object(scanner,'camera_http',side_effect=responses):
            return scanner.camera_auth('eth0','192.0.2.20',options or OPTIONS)

    def test_challenge_then_onvif_success_confirms_credentials(self):
        result=self.query([(401,b''),(200,SUCCESS)])
        self.assertEqual(result['status'],'accepted')
        self.assertNotIn(OPTIONS['password'],json.dumps(result))
        self.assertNotIn(OPTIONS['username'],json.dumps(result))

    def test_public_service_does_not_validate_a_password(self):
        with patch.object(scanner,'get_interface',return_value=NET),patch.object(scanner,'camera_http',return_value=(200,SUCCESS)) as request:
            self.assertEqual(scanner.camera_auth('eth0','192.0.2.20',OPTIONS)['status'],'unknown')
            self.assertEqual(request.call_count,1)

    def test_rejection_and_fault_are_not_success(self):
        self.assertEqual(self.query([(401,b''),(401,b'')])['status'],'rejected')
        self.assertEqual(self.query([(500,DENIED),(500,DENIED)])['status'],'rejected')
        self.assertEqual(self.query([(401,b''),(200,b'<html>login</html>')])['status'],'unknown')

    def test_web_challenge_supported_but_login_form_not_supported(self):
        options={**OPTIONS,'mode':'web'}
        self.assertEqual(self.query([(401,b''),(200,b'authenticated page')],options)['status'],'accepted')
        self.assertEqual(self.query([(200,b'<form>login</form>')],options)['status'],'unknown')
        self.assertEqual(self.query([(401,b''),(302,b'')],options)['status'],'unknown')

    def test_errors_are_sanitized(self):
        self.assertNotIn('dummy-password',json.dumps(self.query([urllib.error.URLError('dummy-password')])) )

    def test_outside_lan_gateway_and_invalid_port_are_rejected(self):
        with patch.object(scanner,'get_interface',return_value=NET),patch.object(scanner,'camera_http') as request:
            for ip in ['198.51.100.10','192.0.2.10','192.0.2.255','192.0.2.0']:
                with self.assertRaises(ValueError):scanner.camera_auth('eth0',ip,OPTIONS)
            with self.assertRaises(ValueError):scanner.camera_auth('eth0','192.0.2.20',{**OPTIONS,'port':0})
            request.assert_not_called()

    def test_soap_escapes_username_and_does_not_send_plain_password(self):
        body=scanner.onvif_request('<test&user>',OPTIONS['password'])
        self.assertNotIn(OPTIONS['password'].encode(),body)
        self.assertIn(b'&lt;test&amp;user&gt;',body)
        scanner.ET.fromstring(body)

    def test_tunnel_is_local_only_and_does_not_execute_a_process(self):
        with patch.object(scanner,'get_interface',return_value=NET),patch.object(scanner.Path,'read_text',return_value=json.dumps({'vpn_admin_ip':'198.51.100.10'})),patch.object(scanner.subprocess,'run') as run:
            result=scanner.web_tunnel('eth0','192.0.2.20',{'port':80})
            self.assertIn('-L 127.0.0.1:18080:192.0.2.20:80',result['command'])
            self.assertEqual(result['url'],'http://127.0.0.1:18080')
            self.assertIn('ubuntu@198.51.100.10',result['command']);run.assert_not_called()
            with self.assertRaises(ValueError):scanner.web_tunnel('eth0','192.0.2.20',{'ssh_user':'ubuntu;bad'})

    def test_redirects_are_never_followed(self):
        self.assertIsNone(scanner.NoCameraRedirect().redirect_request(None,None,302,'Found',{},'http://198.51.100.1'))

    def test_basic_auth_handshake_against_local_fixture(self):
        seen=[]
        expected='Basic '+base64.b64encode(b'test-user:dummy-password').decode()
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.headers.get('Authorization'))
                if self.headers.get('Authorization')==expected:
                    self.send_response(200);self.end_headers();self.wfile.write(b'authenticated fixture')
                else:
                    self.send_response(401);self.send_header('WWW-Authenticate','Basic realm="fixture"');self.end_headers()
            def log_message(self,*args):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            url='http://127.0.0.1:'+str(server.server_port)+'/'
            self.assertEqual(scanner.camera_http(url)[0],401)
            self.assertEqual(scanner.camera_http(url,credentials=('test-user','dummy-password'))[0],200)
            self.assertEqual(scanner.camera_http(url,credentials=('test-user','wrong-fixture-password'))[0],401)
            self.assertIsNone(seen[0])
            self.assertLessEqual(len(seen),5)
        finally:
            server.shutdown();server.server_close();worker.join(timeout=2)


if __name__=='__main__':unittest.main()
