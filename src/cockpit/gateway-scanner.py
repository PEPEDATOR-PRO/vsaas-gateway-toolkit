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


def main(argv):
    if argv == ['interfaces']:
        return {'interfaces': interfaces()}
    if os.geteuid() != 0:
        raise ValueError('Activa el acceso administrativo de Cockpit para ejecutar el escaneo.')
    if len(argv) == 2 and argv[0] == 'scan':
        return scan(argv[1])
    if len(argv) == 3 and argv[0] == 'ports':
        return ports(argv[1], argv[2])
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
