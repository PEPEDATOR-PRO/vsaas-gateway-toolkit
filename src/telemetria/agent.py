#!/usr/bin/env python3
"""Opt-in outbound health telemetry. No packet capture, no offline backlog."""
import argparse
import concurrent.futures
import datetime as dt
import json
import http.client
import ipaddress
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import urllib.parse
from common import atomic, clean_report, device_id, endpoint, MAX_BODY

CONFIG = Path('/etc/vsaas-gateway/telemetria.json')
STATE = Path('/var/lib/vsaas-telemetria/status.json')
HEALTH = '/usr/local/libexec/vsaas-telemetry-health.py'


def initial():
    return {'device_id': str(uuid.uuid4()), 'name': socket.gethostname(), 'interval': 30, 'enabled': False, 'destinations': []}


def validate(config, old=None):
    if not isinstance(config, dict):
        raise ValueError('Configuración no válida.')
    identity = device_id(config.get('device_id'))
    if old and identity != old['device_id']:
        raise ValueError('No se puede cambiar el identificador del equipo.')
    name = config.get('name', '')
    interval = config.get('interval')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 128 or isinstance(interval, bool) or not isinstance(interval, int) or not 30 <= interval <= 3600 or not isinstance(config.get('enabled'), bool):
        raise ValueError('Nombre, intervalo (30–3600 s) o activación no válidos.')
    destinations = config.get('destinations')
    if not isinstance(destinations, list) or len(destinations) > 8:
        raise ValueError('Se admiten hasta ocho destinos.')
    result = {k: config[k] for k in ('device_id', 'name', 'interval', 'enabled')}
    result['destinations'] = []
    previous = {d['id']: d for d in (old or {}).get('destinations', [])}
    seen = set()
    for dest in destinations:
        key = device_id(dest.get('id'))
        url = endpoint(dest.get('url'))
        token = dest.get('token', '')
        if not token and key in previous and previous[key]['url'] == url:
            token = previous[key]['token']
        if not isinstance(token, str) or not 24 <= len(token) <= 256 or not token.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in token):
            raise ValueError('Introduce la llave del colector; al cambiar la URL hay que introducirla de nuevo.')
        label = dest.get('name', '')
        if not isinstance(label, str) or not 1 <= len(label) <= 80 or not isinstance(dest.get('enabled'), bool) or key in seen:
            raise ValueError('Nombre, activación o identificador de destino no válidos.')
        seen.add(key)
        source_ip = dest.get('source_ip', '')
        if source_ip:
            source_ip = str(ipaddress.IPv4Address(source_ip))
        result['destinations'].append(dict(id=key, name=label, url=url, token=token, enabled=dest['enabled'], source_ip=source_ip))
    return result


def public_config(config):
    return {**config, 'destinations': [{k: v for k, v in d.items() if k != 'token'} | {'has_token': bool(d['token'])} for d in config['destinations']]}


def cpu():
    fields = [int(v) for v in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
    return [sum(fields), fields[3] + fields[4]]


def snapshot(config, previous):
    now = time.monotonic()
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    old = previous.get('sample', {}) if previous.get('sample', {}).get('boot_id') == boot else {}
    current_cpu = cpu()
    total = current_cpu[0] - old.get('cpu', current_cpu)[0]
    idle = current_cpu[1] - old.get('cpu', current_cpu)[1]
    mem = {line.split(':')[0]: int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines() if len(line.split()) > 1}
    disk = shutil.disk_usage('/')
    temperature = None
    try:
        temperature = int(Path('/sys/class/thermal/thermal_zone0/temp').read_text()) / 1000
    except (OSError, ValueError):
        pass
    network, counters = [], {}
    try:
        nets = json.loads(subprocess.run(['ip', '-j', '-4', 'addr', 'show', 'up'], check=True, capture_output=True, text=True, timeout=4).stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        nets = []
    elapsed = now - old.get('monotonic', now)
    for net in nets[:16]:
        name = net.get('ifname', '')
        if not name or name == 'lo' or name.startswith(('docker', 'veth', 'br-', 'tun', 'tap', 'xfrm', 'ipsec')):
            continue
        addresses = [f"{a['local']}/{a['prefixlen']}" for a in net.get('addr_info', []) if a.get('family') == 'inet' and a.get('scope') == 'global']
        if not addresses:
            continue
        item = {'name': name, 'addresses': addresses[:16]}
        for key in ('rx', 'tx'):
            try:
                value = int((Path('/sys/class/net') / name / 'statistics' / (key + '_bytes')).read_text())
                item[key + '_bytes'] = value
                before = old.get('counters', {}).get(name, {}).get(key)
                item[key + '_mbps'] = round((value - before) * 8 / elapsed / 1e6, 3) if before is not None and value >= before and elapsed > 0 else None
                counters.setdefault(name, {})[key] = value
            except (OSError, ValueError):
                pass
        network.append(item)
    health = {}
    try:
        raw = subprocess.run([sys.executable, HEALTH], check=True, capture_output=True, text=True, timeout=20).stdout
        data = json.loads(raw)
        db = (data.get('internal') or {}).get('database') or {}
        containers = data.get('containers', [])
        health = {'vsaas': data.get('local_status', 'unknown'), 'vpn': (data.get('vpn') or {}).get('status', 'unknown'),
                  'cameras_configured': db.get('camera_total'), 'cameras_enabled': db.get('camera_enabled'),
                  'containers_running': sum(c.get('state') == 'running' for c in containers), 'containers_total': len(containers)}
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    report = clean_report({'schema': 1, 'device_id': config['device_id'], 'name': config['name'], 'hostname': socket.gethostname(),
                          'sent_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'boot_id': boot,
                          'cpu_percent': round(max(0, min(100, (1 - idle / total) * 100)), 2) if total > 0 else None,
                          'ram_percent': round((1 - mem['MemAvailable'] / mem['MemTotal']) * 100, 2),
                          'disk_percent': round(disk.used / disk.total * 100, 2), 'temperature_c': temperature,
                          'uptime_seconds': float(Path('/proc/uptime').read_text().split()[0]), 'network': network, 'health': health})
    sample = dict(boot_id=boot, cpu=current_cpu, monotonic=now, counters=counters)
    return report, sample


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def source_address(destination):
    if destination.get('source_ip'):
        return (destination['source_ip'], 0)
    try:
        profile = json.loads(CONFIG.with_name('config.json').read_text())
        remote = ipaddress.ip_network(profile['vpn_remote_subnet'])
        host = urllib.parse.urlsplit(destination['url']).hostname
        addresses = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
        if addresses and all(ipaddress.ip_address(a[4][0]) in remote for a in addresses):
            return (str(ipaddress.IPv4Address(profile['vpn_admin_ip'])), 0)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def deliver(destination, report):
    started = time.monotonic()
    result = {'id': destination['id'], 'ok': False}
    source = source_address(destination)

    class SourceHTTP(urllib.request.HTTPHandler):
        def http_open(self, request):
            return self.do_open(lambda host, **kw: http.client.HTTPConnection(host, source_address=source, **kw), request)

    class SourceHTTPS(urllib.request.HTTPSHandler):
        def https_open(self, request):
            return self.do_open(lambda host, **kw: http.client.HTTPSConnection(host, source_address=source, **kw), request, context=self._context)

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(), SourceHTTP(), SourceHTTPS())
    request = urllib.request.Request(destination['url'], json.dumps(report, allow_nan=False).encode(),
                                     headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + destination['token']}, method='POST')
    try:
        with opener.open(request, timeout=5) as response:
            result.update(ok=200 <= response.status < 300, http=response.status)
    except urllib.error.HTTPError as error:
        result['http'] = error.code
    except (OSError, ValueError):
        result['error'] = 'No se pudo contactar el destino o verificar su certificado.'
    result['latency_ms'] = round((time.monotonic() - started) * 1000)
    return result


def run_once(config, previous):
    if not config['enabled'] or not any(d['enabled'] for d in config['destinations']):
        return {'enabled': config['enabled'], 'checked_at': time.time(), 'deliveries': []}
    report, sample = snapshot(config, previous)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        deliveries = list(pool.map(lambda d: deliver(d, report), [d for d in config['destinations'] if d['enabled']]))
    return {'enabled': True, 'checked_at': time.time(), 'deliveries': deliveries, 'sample': sample}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['config', 'save', 'run'])
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Activa el acceso administrativo o ejecuta con sudo.')
    if args.action == 'config':
        config = json.loads(CONFIG.read_text())
        status = json.loads(STATE.read_text()) if STATE.exists() else {}
        status.pop('sample', None)
        print(json.dumps({'config': public_config(config), 'status': status}))
    elif args.action == 'save':
        raw = sys.stdin.read(MAX_BODY + 1)
        if len(raw) > MAX_BODY:
            raise ValueError('Configuración demasiado grande.')
        config = validate(json.loads(raw), json.loads(CONFIG.read_text()))
        atomic(CONFIG, config)
        print(json.dumps({'ok': True}))
    else:
        while True:
            started = time.monotonic()
            try:
                config = validate(json.loads(CONFIG.read_text()))
                previous = json.loads(STATE.read_text()) if STATE.exists() else {}
                atomic(STATE, run_once(config, previous))
                interval = config['interval']
            except (OSError, ValueError, KeyError) as error:
                print('No se pudo completar la telemetría; revisa la configuración local.', flush=True)
                interval = 30
            time.sleep(max(1, interval - (time.monotonic() - started)))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        raise SystemExit(str(error))
