#!/usr/bin/env python3
"""Bounded local network discovery for a Cockpit extension. No daemon."""
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import base64
import datetime
import hashlib
import urllib.request
import urllib.error
from xml.sax.saxutils import escape


def execute(args, timeout=10):
    return subprocess.run(args, check=True, text=True, capture_output=True,
                          timeout=timeout, env={**os.environ, 'LC_ALL': 'C'})


def interfaces():
    ip_tool = shutil.which('ip') or '/usr/sbin/ip'
    data = json.loads(execute([ip_tool, '-j', '-4', 'addr', 'show', 'up']).stdout)
    found = []
    for net in data:
        name = net.get('ifname', '')
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,32}', name):
            continue
        if name == 'lo' or name.startswith(('docker', 'veth', 'br-', 'tun', 'tap', 'ipsec', 'xfrm')):
            continue
        # IPv4-only iproute2 output may omit link_type even on eth0/wlan0.
        # Broadcast capability plus global IPv4 and the exclusions above
        # identify suitable local segments without depending on that field.
        if 'BROADCAST' not in net.get('flags', []):
            continue
        addresses = [f"{a['local']}/{a['prefixlen']}" for a in net.get('addr_info', [])
                     if a.get('family') == 'inet' and a.get('scope') == 'global']
        if addresses:
            found.append({'name': name, 'addresses': addresses})
    return found


def get_interface(name):
    for net in interfaces():
        if net['name'] == name:
            return net
    raise ValueError('La conexión ya no está activa o no es una red local Ethernet o Wi-Fi.')


def parse_arp(text):
    hosts = {}
    for line in text.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 2 or not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', parts[1]):
            continue
        try:
            address = str(ipaddress.IPv4Address(parts[0]))
        except ValueError:
            continue
        mac = parts[1].lower()
        vendor = parts[2] if len(parts) > 2 else ''
        if vendor.startswith('(Unknown)'):
            vendor = 'No identificado'
        hosts[(address, mac)] = {'ip': address, 'mac': mac, 'vendor': vendor}
    return sorted(hosts.values(), key=lambda h: (int(ipaddress.IPv4Address(h['ip'])), h['mac']))


def parse_ports(text):
    root = ET.fromstring(text)
    ports = {int(p.attrib['portid']) for p in root.findall('.//host/ports/port')
             if p.find('state') is not None and p.find('state').get('state') == 'open'}
    return sorted(ports)


def scan(name):
    net = get_interface(name)
    # Bound broadcasts to ordinary LAN sizes, never a /8 or /16 by accident.
    if any(ipaddress.IPv4Interface(a).network.num_addresses > 4096 for a in net['addresses']):
        raise ValueError('La red supera 4096 direcciones. Esta herramienta limita el escaneo a redes /20 o menores.')
    tool = shutil.which('arp-scan')
    if not tool:
        raise ValueError('Falta arp-scan. Instala el paquete arp-scan en Ubuntu.')
    started = time.monotonic()
    result = execute([tool, '--interface=' + name, '--localnet'], timeout=45)
    return {'devices': parse_arp(result.stdout), 'raw': result.stdout,
            'warnings': result.stderr.strip(), 'elapsed': round(time.monotonic() - started, 1)}


def ports(name, address):
    net = get_interface(name)
    host = ipaddress.IPv4Address(address)
    if not any(host in ipaddress.IPv4Interface(a).network for a in net['addresses']):
        raise ValueError('La IP no pertenece a la red local seleccionada.')
    tool = shutil.which('nmap')
    if not tool:
        raise ValueError('Falta nmap. Instala el paquete nmap en Ubuntu.')
    result = execute([tool, '-n', '-sT', '-Pn', '--host-timeout', '20s',
                      '--max-retries', '1', '-p', '80,443,554,8000,8080', '-oX', '-', str(host)], timeout=30)
    parsed = ET.fromstring(result.stdout)
    if parsed.find('.//host/ports') is None:
        raise ValueError('La comprobación no devolvió puertos; puede haber agotado el tiempo de espera.')
    return {'ip': str(host), 'ports': parse_ports(result.stdout)}


def traffic_snapshot(name):
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,32}', name):
        raise ValueError('Conexión no válida.')
    base = Path('/sys/class/net') / name
    keys = ['rx_bytes', 'tx_bytes', 'rx_packets', 'tx_packets',
            'rx_errors', 'tx_errors', 'rx_dropped', 'tx_dropped']
    values = {key: int((base / 'statistics' / key).read_text().strip()) for key in keys}
    values['timestamp'] = time.monotonic()
    try:
        speed = int((base / 'speed').read_text().strip())
        values['speed_mbps'] = speed if speed > 0 else None
    except (OSError, ValueError):
        values['speed_mbps'] = None
    return values


def stream_traffic(name):
    get_interface(name)
    # One unprivileged process per active view, no service or packet capture.
    while True:
        print(json.dumps(traffic_snapshot(name)), flush=True)
        time.sleep(1)


class NoCameraRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


class CameraDigest(urllib.request.HTTPDigestAuthHandler):
    def retry_http_digest_auth(self,req,auth):
        if getattr(self,'attempts',0)>=1:return None
        self.attempts=getattr(self,'attempts',0)+1
        return super().retry_http_digest_auth(req,auth)


def camera_target(name,address):
    net=get_interface(name)
    host=ipaddress.IPv4Address(address)
    if not any(host in ipaddress.IPv4Interface(a).network and host not in (ipaddress.IPv4Interface(a).network.network_address,ipaddress.IPv4Interface(a).network.broadcast_address,ipaddress.IPv4Interface(a).ip) for a in net['addresses']):
        raise ValueError('Selecciona un equipo de la red local, distinto del Gateway.')
    return str(host)


def camera_options(data):
    scheme=data.get('scheme','http');port=data.get('port',80)
    if scheme not in ('http','https') or type(port) is not int or not 1<=port<=65535:
        raise ValueError('Protocolo o puerto no válido.')
    return scheme,port


def onvif_request(username=None,password=None):
    security=''
    if username is not None:
        nonce=os.urandom(20)
        created=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        digest=base64.b64encode(hashlib.sha1(nonce+created.encode()+password.encode()).digest()).decode()
        security='<s:Header><wsse:Security xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd" xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"><wsse:UsernameToken><wsse:Username>'+escape(username)+'</wsse:Username><wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">'+digest+'</wsse:Password><wsse:Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">'+base64.b64encode(nonce).decode()+'</wsse:Nonce><wsu:Created>'+created+'</wsu:Created></wsse:UsernameToken></wsse:Security></s:Header>'
    return ('<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'+security+'<s:Body><GetDeviceInformation xmlns="http://www.onvif.org/ver10/device/wsdl"/></s:Body></s:Envelope>').encode()


def camera_http(url,body=None,credentials=None):
    handlers=[urllib.request.ProxyHandler({}),NoCameraRedirect()]
    if credentials:
        manager=urllib.request.HTTPPasswordMgrWithDefaultRealm()
        manager.add_password(None,url,*credentials)
        handlers.append(CameraDigest(manager))
        # Basic is sent only after the camera explicitly challenges it.
        handlers.append(urllib.request.HTTPBasicAuthHandler(manager))
    request=urllib.request.Request(url,data=body)
    if body is not None:request.add_header('Content-Type','application/soap+xml; charset=utf-8; action="http://www.onvif.org/ver10/device/wsdl/GetDeviceInformation"')
    try:
        with urllib.request.build_opener(*handlers).open(request,timeout=5) as response:
            return response.status,response.read(65536)
    except urllib.error.HTTPError as error:
        try:return error.code,error.read(65536)
        finally:error.close()


def soap_result(body):
    try:
        root=ET.fromstring(body)
        tags={node.tag for node in root.iter()}
        if '{http://www.onvif.org/ver10/device/wsdl}GetDeviceInformationResponse' in tags and not any(tag.endswith('}Fault') for tag in tags):return 'success'
        if any(tag.endswith('}Fault') for tag in tags) and any((node.text or '').split(':')[-1].strip() in ('NotAuthorized','FailedAuthentication') for node in root.iter()):return 'denied'
    except ET.ParseError:pass
    return 'unknown'


def camera_auth(name,address,data):
    host=camera_target(name,address);scheme,port=camera_options(data)
    username,password=data.get('username'),data.get('password')
    mode=data.get('mode','onvif')
    if mode not in ('onvif','web') or not all(isinstance(v,str) and 0<len(v)<=1024 and not any(c in v for c in '\r\n\x00') for v in (username,password)):
        raise ValueError('Introduce usuario y contraseña válidos. No se guardarán.')
    url=f'{scheme}://{host}:{port}'+('/onvif/device_service' if mode=='onvif' else '/')
    def result(status,detail):return {'status':status,'detail':detail}
    try:
        code,body=camera_http(url,onvif_request() if mode=='onvif' else None)
        rejected=code==401 or (mode=='onvif' and soap_result(body)=='denied')
        if not rejected:
            return result('unknown','El servicio no exigió una autenticación compatible. Una página de acceso o una respuesta pública no valida la contraseña. Prueba el acceso web por SSH.')
        code,body=camera_http(url,onvif_request(username,password) if mode=='onvif' else None,(username,password))
        if code==401 or (mode=='onvif' and soap_result(body)=='denied'):
            return result('rejected','Autenticación rechazada. Revisa credenciales, permisos ONVIF y hora de la cámara; evita repetir pruebas para no bloquear la cuenta.')
        if code==200 and (mode=='web' or soap_result(body)=='success'):
            return result('accepted','Credenciales aceptadas por '+('ONVIF' if mode=='onvif' else 'autenticación HTTP')+'. No confirma RTSP ni transmisión de video.')
        return result('unknown','Respuesta sin confirmación de autenticación. Revisa protocolo, puerto y permisos; los accesos web por formulario no se validan automáticamente.')
    except (OSError,urllib.error.URLError,ValueError):
        return result('unknown','No se completó la prueba. Revisa conectividad, puerto y certificado HTTPS. No se desactiva la verificación de certificados.')


def web_tunnel(name,address,data):
    host=camera_target(name,address);scheme,port=camera_options(data)
    user=data.get('ssh_user','ubuntu');local=data.get('local_port',18080)
    if not isinstance(user,str) or not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}',user) or type(local) is not int or not 1024<=local<=65535:
        raise ValueError('Usuario SSH o puerto local no válido.')
    try:admin=str(ipaddress.IPv4Address(json.loads(Path('/etc/vsaas-gateway/config.json').read_text())['vpn_admin_ip']))
    except (OSError,ValueError,KeyError,TypeError):raise ValueError('Falta la IP de administración en el perfil del Gateway.') from None
    command=f'ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -L 127.0.0.1:{local}:{host}:{port} {user}@{admin}'
    return {'command':command,'url':f'{scheme}://127.0.0.1:{local}','detail':'Ejecuta este comando en PowerShell o una terminal de tu computadora con la VPN conectada. Usa la contraseña de Ubuntu, no la de la cámara. Mantén esa terminal abierta y abre el enlace. Ctrl+C cierra el túnel. Requiere SSH instalado en el Gateway y reenvío TCP permitido. Algunas cámaras con redirecciones o direcciones absolutas pueden no funcionar a través de este túnel.'}


def main(argv):
    if argv == ['interfaces']:
        return {'interfaces': interfaces()}
    if os.geteuid() != 0:
        raise ValueError('Activa el acceso administrativo de Cockpit para ejecutar el escaneo.')
    if len(argv) == 2 and argv[0] == 'scan':
        return scan(argv[1])
    if len(argv) == 3 and argv[0] == 'ports':
        return ports(argv[1], argv[2])
    if len(argv)==3 and argv[0] in ('camera-auth','web-tunnel'):
        data=json.loads(sys.stdin.read(8193))
        if not isinstance(data,dict):raise ValueError('Opciones no válidas.')
        return (camera_auth if argv[0]=='camera-auth' else web_tunnel)(argv[1],argv[2],data)
    raise ValueError('Acción no válida.')


if __name__ == '__main__':
    try:
        if len(sys.argv) == 3 and sys.argv[1] == 'traffic-stream':
            stream_traffic(sys.argv[2])
        else:
            print(json.dumps(main(sys.argv[1:]), ensure_ascii=False))
    except BrokenPipeError:
        # Cockpit closed the view or stopped monitoring.
        sys.exit(0)
    except subprocess.TimeoutExpired:
        print('Se agotó el tiempo del escaneo. Revisa la conexión e inténtalo de nuevo.', file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        print((exc.stderr or str(exc)).strip(), file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
