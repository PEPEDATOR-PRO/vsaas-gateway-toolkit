#!/usr/bin/env python3
"""Local management for the optional collector; no credentials in status."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import urllib.request
import urllib.error

TARGET=Path('/opt/vsaas-gateway/eventos')
PROJECT='vsaas_eventos'


def compose():
    return ['docker','compose','--env-file',str(TARGET/'.env'),'-f',str(TARGET/'compose.yaml'),'-p',PROJECT]


def run(args,timeout=15):
    return subprocess.run(args,text=True,capture_output=True,timeout=timeout,check=True).stdout


def status():
    result={'installed':False,'state':'unknown','health':'unknown','restarts':None,'url':None,'responds':False}
    if not (TARGET/'settings.json').is_file():return result
    config=json.loads((TARGET/'settings.json').read_text())
    address=str(ipaddress.IPv4Address(config['vpn_admin_ip']))
    result.update(installed=True,url='http://'+address+':8081')
    try:
        ids=run(['docker','ps','-aq','--filter','label=com.docker.compose.project='+PROJECT,'--filter','label=com.docker.compose.service=collector']).split()
        if ids:
            data=json.loads(run(['docker','inspect',ids[0]]))[0]
            state=data.get('State',{})
            result.update(state=state.get('Status','unknown'),health=state.get('Health',{}).get('Status','not-configured'),restarts=data.get('RestartCount',0))
        else:result['state']='not-found'
    except (subprocess.SubprocessError,OSError,ValueError,KeyError,IndexError):
        result['detail']='No se pudo consultar Docker.'
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('http://127.0.0.1:8081/health',timeout=3) as response:
            result['responds']=response.status==200 and json.loads(response.read(4096))=={'status':'ok'}
    except (OSError,ValueError,urllib.error.URLError):pass
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['estado','iniciar','detener','logs','llave','llave-consulta'])
    parser.add_argument('--json',action='store_true')
    args=parser.parse_args()
    if getattr(os,'geteuid',lambda:-1)()!=0:raise SystemExit('Ejecuta con sudo en Ubuntu.')
    if args.action=='estado':
        result=status()
        if args.json:print(json.dumps(result,ensure_ascii=False))
        else:
            print('Colector instalado: '+('sí' if result['installed'] else 'no'))
            print('Contenedor: '+result['state']+' · Salud Docker: '+result['health'])
            print('Respuesta local: '+('correcta' if result['responds'] else 'sin confirmar'))
            if result['url']:print('Panel por VPN: '+result['url'])
            print('El estado HTTP no confirma recepción de eventos de las cámaras.')
    elif args.action in ('llave','llave-consulta'):
        filename='admin.token' if args.action=='llave' else 'viewer.token'
        # Only an explicit privileged action reads a key. Status never does.
        subprocess.run(compose()+['exec','-T','collector','cat','/data/'+filename],check=True,timeout=10)
        print()
    elif args.action=='iniciar':
        subprocess.run(compose()+['up','-d','--no-build','--wait','--wait-timeout','120'],check=True,timeout=150)
    elif args.action=='detener':
        subprocess.run(compose()+['stop','--timeout','75'],check=True,timeout=90)
    else:subprocess.run(compose()+['logs','--tail','80','collector'],check=True,timeout=15)


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,subprocess.SubprocessError):raise SystemExit('No se completó la operación del colector. Revisa el módulo y el servicio vsaas-eventos.')
