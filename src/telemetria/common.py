"""Small shared protocol for gateway health reports (no third-party packages)."""
import ipaddress
import json
import math
from pathlib import Path
import re
import urllib.parse

MAX_BODY = 65536


def device_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{8,64}', value):
        raise ValueError('Identificador de equipo no válido.')
    return value


def endpoint(value):
    if not isinstance(value, str) or len(value) > 1024 or any(ord(c) < 33 for c in value):
        raise ValueError('URL de destino no válida.')
    parts = urllib.parse.urlsplit(value)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('Usa HTTP/HTTPS, host, puerto y path; sin credenciales ni parámetros en la URL.')
    try:
        port = parts.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError()
        host = parts.hostname.encode('idna').decode()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if len(host) > 253 or not all(re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', p) for p in host.rstrip('.').split('.')):
                raise ValueError()
    except ValueError:
        raise ValueError('Host o puerto no válido.') from None
    return value


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
    temporary.chmod(0o600)
    temporary.replace(path)


def number(value, low=0, high=1e20):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('Valor numérico fuera de rango.')
    return value


def clean_report(data):
    """Allowlist telemetry, never persist arbitrary probe output or credentials."""
    if not isinstance(data, dict) or data.get('schema') != 1:
        raise ValueError('Versión de reporte no compatible.')
    out = {'schema': 1, 'device_id': device_id(data.get('device_id'))}
    for key in ('name', 'hostname', 'sent_at', 'boot_id'):
        value = data.get(key, '')
        if not isinstance(value, str) or len(value) > 128:
            raise ValueError('Texto de reporte no válido.')
        out[key] = value
    for key, high in [('cpu_percent', 100), ('ram_percent', 100), ('disk_percent', 100), ('temperature_c', 150), ('uptime_seconds', 1e12)]:
        out[key] = number(data.get(key), -40 if key == 'temperature_c' else 0, high)
    levels = {'ok', 'warning', 'critical', 'unknown'}
    health = data.get('health', {})
    if not isinstance(health, dict):
        raise ValueError('Salud no válida.')
    out['health'] = {k: health.get(k, 'unknown') if health.get(k, 'unknown') in levels else 'unknown' for k in ('vsaas', 'vpn')}
    for key in ('cameras_configured', 'cameras_enabled', 'containers_running', 'containers_total'):
        out['health'][key] = number(health.get(key), 0, 1e7)
    interfaces = data.get('network', [])
    if not isinstance(interfaces, list) or len(interfaces) > 16:
        raise ValueError('Lista de interfaces no válida.')
    out['network'] = []
    for net in interfaces:
        if not isinstance(net, dict) or not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,32}', str(net.get('name', ''))):
            raise ValueError('Interfaz no válida.')
        addresses = net.get('addresses', [])
        if not isinstance(addresses, list) or len(addresses) > 16:
            raise ValueError('Direcciones no válidas.')
        out['network'].append({'name': net['name'], 'addresses': [str(ipaddress.ip_interface(a)) for a in addresses],
                               **{k: number(net.get(k)) for k in ('rx_bytes', 'tx_bytes', 'rx_mbps', 'tx_mbps')}})
    return out
