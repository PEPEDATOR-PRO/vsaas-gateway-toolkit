#!/usr/bin/env python3
"""Read-only, bounded local VXG diagnostics. Emits no credentials or raw logs."""
import concurrent.futures
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request

PROJECT = 'camera_agent_gateway'
try:
    configured=json.loads(Path('/etc/vsaas-gateway/config.json').read_text()).get('compose_project',PROJECT)
    if re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}',configured):
        PROJECT=configured
except (OSError,ValueError,TypeError):
    pass

# Runs via docker exec, never imports Django or invokes management commands.
INSIDE = r'''
import collections, glob, json, os, pathlib, re, sqlite3, urllib.parse
out={'proxy_processes':0,'python_processes':0,'proxy_tcp443':None,'database':None,'logs':{'files_sampled':0,'events':{}},'notes':[]}
inodes=set(); readable=True
for entry in pathlib.Path('/proc').iterdir():
    if not entry.name.isdigit(): continue
    try:
        comm=(entry/'comm').read_text().strip()
        if comm.startswith('python'): out['python_processes']+=1
        if not comm.startswith('vxg-proxy-cli'): continue
        out['proxy_processes']+=1
        try:
            for fd in (entry/'fd').iterdir():
                try:
                    match=re.fullmatch(r'socket:\[(\d+)\]',os.readlink(fd))
                    if match: inodes.add(match.group(1))
                except OSError: pass
        except OSError: readable=False
    except OSError: pass
try:
    connections=0
    for source in ['/proc/net/tcp','/proc/net/tcp6']:
        try: lines=pathlib.Path(source).read_text().splitlines()[1:]
        except FileNotFoundError: continue
        for line in lines:
            parts=line.split()
            if len(parts)>9 and parts[3]=='01' and parts[9] in inodes and int(parts[2].split(':')[-1],16)==443:
                connections+=1
    if readable: out['proxy_tcp443']=connections
except (OSError,ValueError): pass

paths=[]
for folder in ['/vol/data','/code/server','/code']:
    for pattern in ['*.sqlite3','*.sqlite','*.db']:
        paths+=glob.glob(folder+'/'+pattern)
for filename in dict.fromkeys(paths):
    try:
        resolved=str(pathlib.Path(filename).resolve())
        db=sqlite3.connect('file:'+urllib.parse.quote(resolved,safe='/')+'?mode=ro',uri=True,timeout=1)
        db.execute('PRAGMA query_only=ON')
        for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            if not re.fullmatch(r'[A-Za-z0-9_]+',table) or 'camera' not in table.lower(): continue
            columns={row[1] for row in db.execute('PRAGMA table_info("'+table+'")')}
            if not {'ip','is_active'}<=columns: continue
            total,active=db.execute('SELECT COUNT(*),COALESCE(SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END),0) FROM "'+table+'"').fetchone()
            out['database']={'path':resolved,'camera_total':total,'camera_enabled':active,'readable':True}
            break
        db.close()
        if out['database']: break
    except (OSError,sqlite3.Error):
        out['notes'].append('No se pudo leer una base candidata en modo de solo lectura.')

patterns={
 'auth':r'AUTH_FAILED|authentication failed|unauthori[sz]ed|CONN_CONFLICT|check login and password',
 'disconnect':r'websocket.{0,35}(?:closed|disconnected)|connection (?:lost|refused)|reconnect',
 'error':r'\bERROR\b|\[\s*ERR\s*\]|Traceback|segmentation fault|out of memory',
 'established':r'websocket_callback:\s*established'
}
events=collections.Counter()
files=[]
for folder in ['/var/log/server','/var/log/cameras']:
    for pattern in ['*.log','*/*.log']:
        files+=glob.glob(folder+'/'+pattern)
try: files=sorted(set(files),key=os.path.getmtime,reverse=True)[:8]
except OSError: files=[]
for filename in files:
    try:
        with open(filename,'rb') as f:
            f.seek(0,2); size=f.tell(); f.seek(max(0,size-32768)); text=f.read(32768).decode('utf-8','replace')
        out['logs']['files_sampled']+=1
        for category,pattern in patterns.items(): events[category]+=len(re.findall(pattern,text,re.I))
    except OSError: pass
out['logs']['events']=dict(events)
print(json.dumps(out))
'''


def run(args, timeout=8, input_text=None):
    return subprocess.run(args, input=input_text, text=True, capture_output=True,
                          timeout=timeout, check=True, env={**os.environ, 'LC_ALL': 'C'}).stdout


def check(key, label, status, detail):
    return {'key': key, 'label': label, 'status': status, 'detail': detail}


def summarize(container):
    state = container.get('State', {})
    health = state.get('Health', {})
    labels = container.get('Config', {}).get('Labels') or {}
    return {'id': container['Id'][:12], 'name': container['Name'].lstrip('/'),
            'service': labels.get('com.docker.compose.service', ''),
            'image': container.get('Config', {}).get('Image', ''),
            'state': state.get('Status', 'unknown'), 'health': health.get('Status', 'not-configured'),
            'health_failures': health.get('FailingStreak', 0),
            'restarts': container.get('RestartCount', 0), 'oom': state.get('OOMKilled', False),
            'started': state.get('StartedAt'), 'restart_policy': container.get('HostConfig', {}).get('RestartPolicy', {}).get('Name', ''),
            'stats': None}


def host_resources():
    memory = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        fields = line.split()
        if len(fields) >= 2:
            memory[fields[0].rstrip(':')] = int(fields[1])*1024
    total, available = memory.get('MemTotal', 0), memory.get('MemAvailable', 0)
    disk = shutil.disk_usage('/var/lib/docker' if Path('/var/lib/docker').exists() else '/')
    return {'ram_total': total, 'ram_available': available,
            'ram_used_percent': round((1-available/total)*100, 1) if total else None,
            'disk_total': disk.total, 'disk_free': disk.free,
            'disk_used_percent': round(disk.used/disk.total*100, 1),
            'uptime_seconds': float(Path('/proc/uptime').read_text().split()[0])}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_probe(url, css=False):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    started = time.monotonic()
    try:
        with opener.open(url, timeout=3) as response:
            body = response.read(524288 if css else 32768)
            result = {'code': response.status, 'bytes': len(body), 'latency_ms': round((time.monotonic()-started)*1000), 'type': response.headers.get('Content-Type', '')}
            if css:
                result['valid'] = response.status == 200 and bool(body.strip()) and 'text/css' in result['type'].lower()
            else:
                result['valid'] = response.status == 200 and b'uplink' in body.lower()
            return result
    except urllib.error.HTTPError as exc:
        return {'code': exc.code, 'valid': False, 'bytes': 0, 'latency_ms': round((time.monotonic()-started)*1000)}
    except (OSError, urllib.error.URLError):
        return {'code': None, 'valid': False, 'bytes': 0, 'latency_ms': None}


def local_url(nginx):
    bindings = nginx.get('NetworkSettings', {}).get('Ports', {}).get('80/tcp') or []
    for binding in bindings:
        address, port = binding.get('HostIp', ''), binding.get('HostPort', '')
        if port.isdigit() and ':' not in address:
            address = '127.0.0.1' if address in ('', '0.0.0.0') else address
            return f'http://{address}:{port}'
    if nginx.get('HostConfig', {}).get('NetworkMode') == 'host':
        return 'http://127.0.0.1'
    return None


def container_checks(containers):
    checks = []
    for role, label in [('app', 'Aplicación VXG'), ('nginx', 'Nginx')]:
        matches = [c for c in containers if c['service'] == role]
        if not matches:
            checks.append(check(role, label, 'critical', 'No se encontró el contenedor esperado.'))
        for c in matches:
            if c['state'] != 'running':
                status, detail = 'critical', 'Contenedor '+c['state']
            elif c['health'] == 'unhealthy':
                status, detail = 'critical', 'Docker informa unhealthy; '+str(c['health_failures'])+' fallos consecutivos.'
            elif c['health'] == 'starting':
                status, detail = 'warning', 'Contenedor en marcha; chequeo de salud en inicio.'
            else:
                status, detail = 'ok', 'En ejecución'+(' · healthcheck healthy.' if c['health']=='healthy' else ' · sin HEALTHCHECK configurado.')
            checks.append(check(role, label, status, detail))
            if c['oom']:
                checks.append(check(role+'-oom', 'Memoria de '+label, 'warning', 'Docker registra una terminación por falta de memoria. No confirma un fallo actual.'))
            if c['restart_policy'] in ('', 'no'):
                checks.append(check(role+'-policy', 'Arranque de '+label, 'warning', 'Sin política de reinicio automático en Docker.'))
    return checks


def persistent_path(filename, mounts):
    for mount in mounts:
        if mount.get('Type') not in ('volume', 'bind'):
            continue
        dest = mount.get('Destination','').rstrip('/')
        if dest and (filename == dest or filename.startswith(dest+'/')):
            return True
    return False


def raw_sections(text):
    """Yield balanced VICI sections, without exporting raw diagnostic text."""
    stack=[]
    for match in re.finditer(r'([A-Za-z0-9_.-]+)\s*\{|\}',text):
        if match.group(1):
            stack.append((match.group(1),match.end()))
        elif stack:
            name,start=stack.pop()
            yield name,text[start:match.start()]


def vpn_sas(text):
    result={'ike_established':False,'child_installed':False,'uptime_seconds':None,
            'rx_bytes':0,'tx_bytes':0,'rx_packets':0,'tx_packets':0}
    def number(body,key):
        value=re.search(r'(?<![\w-])'+re.escape(key)+r'=(\d+)(?=\s|$)',body)
        return int(value.group(1)) if value else None
    for name,body in raw_sections(text):
        if name!='gateway':continue
        header=body.split('child-sas',1)[0]
        if not re.search(r'\bstate=ESTABLISHED\b',header):continue
        result['ike_established']=True
        result['uptime_seconds']=number(header,'established')
        for _,child in raw_sections(body):
            if not re.search(r'\bname=administracion(?=\s|$)',child) or not re.search(r'\bstate=INSTALLED\b',child):continue
            # Ignore enclosing child-sas section; count only the individual SA.
            if '{' in child:continue
            result['child_installed']=True
            for output,key in [('rx_bytes','bytes-in'),('tx_bytes','bytes-out'),('rx_packets','packets-in'),('tx_packets','packets-out')]:
                value=number(child,key)
                if value is not None:result[output]+=value
    return result


def vpn_health():
    result={'status':'unknown','service':'unknown','detail':'No se pudo consultar la VPN de administración.'}
    if not Path('/etc/swanctl/conf.d/gateway.conf').exists():
        result['detail']='No se encontró la configuración VPN del toolkit.'
        return result
    try:
        service=run(['systemctl','show','strongswan.service','--property=ActiveState','--value'],3).strip()
        result['service']=service if service in ('active','inactive','failed','activating','deactivating') else 'unknown'
        if result['service'] in ('inactive','failed'):
            result.update(status='critical',detail='El servicio strongSwan está detenido o falló.')
            return result
        swanctl=shutil.which('swanctl')
        if not swanctl:return result
        text=run([swanctl,'--list-sas','--ike','gateway','--raw'],4)
        if text.count('{')!=text.count('}'):return result
        if text.strip() and not re.search(r'list-sa (?:event|reply)\s*\{',text):return result
        result.update(vpn_sas(text))
        if result['ike_established'] and result['child_installed']:
            result.update(status='ok',detail='IKE establecido y túnel de administración instalado. No confirma acceso desde FortiClient.')
        elif result['ike_established']:
            result.update(status='warning',detail='IKE establecido; falta un túnel de administración instalado.')
        else:
            result.update(status='critical',detail='No hay una sesión IKE establecida para gateway.')
    except (subprocess.SubprocessError,OSError,ValueError):
        pass
    return result


def collect():
    result = {'checked_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'containers': [], 'checks': [],
              'internal': None, 'host': None, 'web': None, 'css': None,
              'cloud': 'not-confirmed', 'version': '1.0', 'notes': []}
    result['vpn']=vpn_health()
    result['checks'].append(check('vpn','VPN de administración',result['vpn']['status'],result['vpn']['detail']))
    docker = shutil.which('docker')
    if not docker:
        result['checks'].append(check('docker', 'Docker', 'critical', 'No se encontró Docker.'))
        return finish(result)
    try:
        ids = run([docker, 'ps', '-aq', '--filter', 'label=com.docker.compose.project='+PROJECT]).split()
        if not ids:
            result['checks'].append(check('docker', 'Stack VXG', 'critical', 'No hay contenedores con el proyecto Compose '+PROJECT+'.'))
            return finish(result)
        raw = json.loads(run([docker, 'inspect', *ids[:32]]))
        result['containers'] = [summarize(c) for c in raw]
        result['checks'] += container_checks(result['containers'])
    except (subprocess.SubprocessError, ValueError, OSError):
        result['checks'].append(check('docker', 'Docker', 'critical', 'No se pudo consultar Docker. Comprueba el servicio y el acceso administrativo.'))
        return finish(result)

    app = next((c for c in raw if (c.get('Config', {}).get('Labels') or {}).get('com.docker.compose.service') == 'app' and c.get('State', {}).get('Running')), None)
    nginx = next((c for c in raw if (c.get('Config', {}).get('Labels') or {}).get('com.docker.compose.service') == 'nginx' and c.get('State', {}).get('Running')), None)
    # Independent probes have bounded timeouts and may run concurrently.
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {}
        active = [c['id'] for c in result['containers'] if c['state']=='running']
        if active:
            jobs['stats'] = pool.submit(run, [docker, 'stats', '--no-stream', '--format', '{{json .}}', *active], 8)
        if app:
            jobs['internal'] = pool.submit(run, [docker, 'exec', '-i', app['Id'], 'python', '-'], 12, INSIDE)
        origin = local_url(nginx) if nginx else None
        if origin:
            jobs['web'] = pool.submit(http_probe, origin+'/login/')
            jobs['css'] = pool.submit(http_probe, origin+'/static/css/styles.css', True)
        for key, future in jobs.items():
            try:
                value = future.result()
                if key == 'stats':
                    stats = [json.loads(line) for line in value.splitlines() if line.strip()]
                    for c in result['containers']:
                        s = next((s for s in stats if s.get('Name')==c['name']), None)
                        if s:
                            c['stats'] = {name: s.get(name) for name in ['CPUPerc','MemUsage','MemPerc','NetIO','BlockIO','PIDs']}
                else:
                    result[key] = json.loads(value) if key == 'internal' else value
            except (subprocess.SubprocessError, ValueError, OSError):
                result['notes'].append('No se pudo completar la consulta '+key+'.')
                if key=='stats':
                    result['checks'].append(check('stats','Consumo de contenedores','unknown','No se pudo completar la lectura de recursos de Docker.'))

    for key, label in [('web','Interfaz VXG'),('css','Estilos de la interfaz')]:
        probe = result[key]
        if probe is None:
            result['checks'].append(check(key, label, 'unknown', 'No se pudo determinar la dirección HTTP publicada.'))
        elif probe['valid']:
            detail = 'HTTP '+str(probe['code'])+' · '+str(probe['latency_ms'])+' ms'
            if key=='css': detail+=' · '+str(probe['bytes'])+' bytes'
            result['checks'].append(check(key,label,'ok',detail))
        else:
            detail = ('HTTP '+str(probe['code'])) if probe['code'] else 'Sin respuesta HTTP'
            if key=='css': detail+=' · archivo ausente, vacío o con contenido inesperado.'
            else: detail+=' · la página no coincide con el inicio de sesión de Uplink.'
            result['checks'].append(check(key,label,'critical' if key=='web' else 'warning',detail))

    internal = result['internal']
    if internal:
        count = internal.get('proxy_processes',0)
        result['checks'].append(check('proxy','Procesos Uplink','ok' if count else 'critical',str(count)+' procesos vxg-proxy-client. Esto no confirma conexión con la nube.'))
        sockets = internal.get('proxy_tcp443')
        result['checks'].append(check('sockets','Transporte de los proxies','ok' if sockets else ('unknown' if sockets is None else 'warning'),
                                     (str(sockets)+' conexiones TCP 443 establecidas de los proxies.' if sockets is not None else 'No se pudo consultar los sockets de los proxies.')+' No confirma WebSocket ni video.'))
        db = internal.get('database')
        if db:
            db['persistent_mount'] = persistent_path(db['path'], app.get('Mounts',[]))
            result['checks'].append(check('database','Configuración de cámaras','ok','SQLite legible · '+str(db['camera_total'])+' configuradas, '+str(db['camera_enabled'])+' habilitadas. No es un conteo de cámaras online.'))
            result['checks'].append(check('persistence','Persistencia de SQLite','ok' if db['persistent_mount'] else 'warning',
                                         'Base dentro de un montaje persistente.' if db['persistent_mount'] else 'La ruta de SQLite no está cubierta por los montajes detectados; revisar persistencia antes de recrear el contenedor.'))
        else:
            result['checks'].append(check('database','Configuración de cámaras','unknown','No se encontró una tabla de cámaras compatible. No se consultaron credenciales.'))
    else:
        result['checks'].append(check('internal','Inspección interna VXG','unknown','No se pudo consultar procesos, sockets y SQLite de la aplicación.'))
    try:
        host = result['host'] = host_resources()
        for key,label,value in [('ram','Memoria de Ubuntu',host['ram_used_percent']),('disk','Almacenamiento Docker',host['disk_used_percent'])]:
            if value is not None:
                status = 'critical' if value>=95 else ('warning' if value>=85 else 'ok')
                result['checks'].append(check(key,label,status,str(value)+'% utilizado. Umbrales orientativos: atención desde 85%, crítico desde 95%.'))
    except (OSError, ValueError):
        result['notes'].append('No se pudieron consultar los recursos del host.')
        result['checks'].append(check('host','Recursos de Ubuntu','unknown','No se pudo completar la lectura de memoria y almacenamiento.'))
    return finish(result)


def finish(result):
    levels = [c['status'] for c in result['checks']]
    result['local_status'] = 'critical' if 'critical' in levels else ('warning' if 'warning' in levels else ('unknown' if 'unknown' in levels else 'ok'))
    return result


if __name__ == '__main__':
    if os.geteuid()!=0:
        print('Activa el acceso administrativo de Cockpit para consultar Docker.',file=__import__('sys').stderr)
        raise SystemExit(1)
    print(json.dumps(collect(), ensure_ascii=False))
