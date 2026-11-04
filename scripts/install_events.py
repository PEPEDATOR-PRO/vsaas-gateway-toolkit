#!/usr/bin/env python3
"""Deploy only the optional event collector; never operates on VXG volumes."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'src/eventos'
TARGET=Path('/opt/vsaas-gateway/eventos')
LIBEXEC=Path('/usr/local/libexec')
BIN=Path('/usr/local/bin')
UNITS=Path('/etc/systemd/system')
PORTAL=Path('/usr/local/share/cockpit/gateway_eventos')
PROJECT='vsaas_eventos'


def command(args,**kwargs):return subprocess.run(args,check=True,**kwargs)


def admin_address(profile=None,vpn_ip=None):
    values=json.loads(subprocess.check_output(['ip','-j','-4','addr','show','dev','lo'],text=True))
    assigned=[a['local'] for net in values for a in net.get('addr_info',[]) if a.get('family')=='inet' and not ipaddress.IPv4Address(a['local']).is_loopback]
    if vpn_ip:address=str(ipaddress.IPv4Address(vpn_ip))
    elif profile:address=str(ipaddress.IPv4Address(json.loads(Path(profile).read_text())['vpn_admin_ip']))
    elif len(assigned)==1:address=assigned[0]
    else:raise ValueError('No se identificó una sola IP VPN en lo. Indícala con --events-ip en scripts/install.py eventos.')
    if address not in assigned:raise ValueError('La IP de administración debe estar ya asignada a lo por la VPN. No se modificó la red.')
    return address


def install(profile=None,vpn_ip=None):
    address=admin_address(profile,vpn_ip)
    if not shutil.which('docker'):raise ValueError('Instala Docker y Compose antes del colector.')
    command(['docker','compose','version'],stdout=subprocess.DEVNULL)
    if shutil.disk_usage('/var/lib/docker').free<2*1024**3:raise ValueError('Se requieren al menos 2 GiB libres para construir e iniciar el colector.')
    # Binding the VPN address at boot requires the existing strongSwan setup.
    if not shutil.which('swanctl'):raise ValueError('Configura primero la VPN strongSwan de administración.')
    ids=subprocess.check_output(['docker','ps','-aq','--filter','label=com.docker.compose.project='+PROJECT],text=True).strip()
    if ids and not (TARGET/'.toolkit-eventos').is_file():raise ValueError('Ya hay un proyecto vsaas_eventos ajeno a este instalador. No se cambió.')
    if TARGET.exists() and not (TARGET/'.toolkit-eventos').is_file():raise ValueError('El directorio de destino ya existe y no pertenece al módulo.')
    if (TARGET/'settings.json').is_file():
        saved=json.loads((TARGET/'settings.json').read_text())
        if saved.get('vpn_admin_ip')!=address:raise ValueError('La IP VPN cambió. Revisa el despliegue existente antes de modificar su escucha.')
    if not ids:
        for host in ['127.0.0.1',address]:
            with socket.socket() as check:
                check.settimeout(1)
                if check.connect_ex((host,8081))==0:raise ValueError('El puerto 8081 ya está en uso. No se cambió ese servicio.')
    TARGET.mkdir(mode=0o700,parents=True,exist_ok=True)
    (TARGET/'.toolkit-eventos').write_text('v1\n')
    # Stage a complete source tree and build the replacement before touching a running service.
    with tempfile.TemporaryDirectory(prefix='.build-',dir=TARGET) as temporary:
        stage=Path(temporary)
        shutil.copytree(SOURCE/'collector',stage/'collector',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        for name in ['Dockerfile','requirements.txt']:shutil.copyfile(SOURCE/name,stage/name)
        command(['docker','build','-t','vsaas-eventos:local',str(stage)])
        (TARGET/'app').mkdir(exist_ok=True)
        shutil.copytree(stage,TARGET/'app',dirs_exist_ok=True)
    for name in ['compose.yaml']:shutil.copyfile(SOURCE/name,TARGET/name)
    settings=TARGET/'settings.json';settings.write_text(json.dumps({'vpn_admin_ip':address})+'\n');settings.chmod(0o600)
    env=TARGET/'.env'
    if not env.exists():env.write_text('VPN_IP_ADMIN='+address+'\nCOLLECTOR_MAX_DATA_BYTES=2000000000\n')
    env.chmod(0o600)
    (TARGET/'.toolkit-eventos').write_text('v1\n')
    LIBEXEC.mkdir(parents=True,exist_ok=True);BIN.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(SOURCE/'manage.py',LIBEXEC/'vsaas-eventos.py')
    wrapper=BIN/'vsaas-eventos';wrapper.write_text('#!/bin/sh\nexec /usr/bin/python3 /usr/local/libexec/vsaas-eventos.py "$@"\n');wrapper.chmod(0o755)
    UNITS.mkdir(parents=True,exist_ok=True);shutil.copyfile(SOURCE/'vsaas-eventos.service',UNITS/'vsaas-eventos.service')
    PORTAL.mkdir(parents=True,exist_ok=True)
    for name in ['manifest.json','index.html','eventos.js','eventos.css']:shutil.copyfile(ROOT/'src/cockpit-eventos'/name,PORTAL/name)
    command(['systemctl','daemon-reload'])
    command(['systemctl','enable','vsaas-eventos.service'])
    command(['systemctl','restart','vsaas-eventos.service'])
    print('Colector instalado. Panel por VPN: http://'+address+':8081')
    print('En Cockpit cierra sesión y vuelve a entrar: Herramientas → Colector de eventos.')
    print('Llave local de acceso: sudo vsaas-eventos llave')
    print('Las cámaras del Gateway Vsaas no se importan automáticamente; agrégalas en el colector.')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config');parser.add_argument('--vpn-ip');args=parser.parse_args()
    if getattr(os,'geteuid',lambda:-1)()!=0:raise SystemExit('Ejecuta con sudo en Ubuntu.')
    try:install(args.config,args.vpn_ip)
    except ValueError as exc:raise SystemExit(str(exc))
    except (OSError,KeyError,subprocess.SubprocessError):raise SystemExit('No terminó la instalación del colector. No se eliminaron volúmenes. Revisa la salida anterior, Docker y el perfil VPN.')


if __name__=='__main__':main()
