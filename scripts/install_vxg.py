#!/usr/bin/env python3
"""Fresh VXG deployment using reviewed Compose and local-only credentials."""
import argparse
import getpass
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/'vendor/vxg-gateway/1.0.16'
TARGET=Path('/opt/vsaas-gateway/vxg/1.0.16')
PUBLIC={'GITLAB_REGISTRY_HOST','UPLINK_GATEWAY_IMAGE_REPOSITORY','UPLINK_GATEWAY_NGINX_IMAGE_REPOSITORY','VXG_API_HOST'}


def read_env(path):
    data={}
    for number,line in enumerate(Path(path).read_text(encoding='utf-8-sig').splitlines(),1):
        line=line.strip()
        if not line or line.startswith('#'):continue
        match=re.fullmatch(r'(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)',line)
        if not match:raise ValueError('Formato .env no admitido en línea '+str(number)+'. No se ejecutó su contenido.')
        key,value=match.groups()
        if key in data:raise ValueError('Clave repetida en .env: '+key)
        value=value.strip()
        if len(value)>=2 and value[0]==value[-1] and value[0] in ['\"',"'"]:value=value[1:-1]
        data[key]=value
    return data


def env_text(values):
    lines=[]
    for key,value in values.items():
        if not re.fullmatch(r'[A-Z_][A-Z0-9_]*',key):raise ValueError('Nombre de variable no válido.')
        # Literal quoting prevents $ or # from being interpreted by Compose.
        if any(c in value for c in ["'",'\\','\n','\r','\x00']):
            raise ValueError('El campo '+key+' no admite comillas simples, barras invertidas ni saltos de línea.')
        lines.append(key+"='"+value+"'")
    return '\n'.join(lines)+'\n'


def image_version(architecture):
    name={'aarch64':'arm64','arm64':'arm64','x86_64':'x64','amd64':'x64'}.get(architecture)
    if not name:raise ValueError('Arquitectura no admitida: '+architecture)
    value=(PACKAGE/('camera_agent_gateway_'+name+'.version')).read_text().strip()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',value):raise ValueError('Versión de imagen no válida.')
    return value


def app_environment(settings,host,password,version):
    # The registry username/token are intentionally excluded from app.env.
    result={key:settings[key] for key in PUBLIC-{'GITLAB_REGISTRY_HOST'}}
    django=secrets.token_urlsafe(64)
    result.update(HOST_IP=host,DJANGO_SECRET_KEY=django,SECRET_KEY=django,
                  DJANGO_SUPERUSER_USERNAME='admin',DJANGO_SUPERUSER_PASSWORD=password,
                  DJANGO_SUPERUSER_EMAIL='',CAMERA_AGENT_GATEWAY_VERSION=version)
    return result


def command(args,**kwargs):
    return subprocess.run(args,check=True,**kwargs)


def install(credentials=None,project='camera_agent_gateway'):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}',project):raise ValueError('Proyecto Compose no válido.')
    if not shutil.which('docker'):raise ValueError('Instala Docker antes de VXG.')
    command(['docker','compose','version'],stdout=subprocess.DEVNULL)
    existing=subprocess.check_output(['docker','ps','-aq','--filter','label=com.docker.compose.project='+project],text=True).strip()
    if existing or TARGET.exists():
        raise ValueError('Ya existe un despliegue o un directorio de VXG. Este módulo es para un equipo nuevo; no sustituyó datos ni contenedores.')
    settings=read_env(PACKAGE/'.env.example')
    private=read_env(credentials) if credentials else {}
    for key in PUBLIC:
        if private.get(key):settings[key]=private[key]
    for key in PUBLIC:
        if not settings.get(key):raise ValueError('Falta configuración del proveedor: '+key)
    if not re.fullmatch(r'[A-Za-z0-9.-]+(?::[0-9]{1,5})?',settings['GITLAB_REGISTRY_HOST']):raise ValueError('Host del registro no válido.')
    username=private.get('GITLAB_REGISTRY_USER') or input('Usuario del registro VXG: ').strip()
    token=private.get('GITLAB_REGISTRY_TOKEN') or getpass.getpass('Token del registro VXG: ')
    if not username or not token:raise ValueError('Faltan credenciales de descarga del proveedor.')
    password=getpass.getpass('Nueva contraseña del administrador VXG (mínimo 12 caracteres): ')
    if len(password)<12 or password!=getpass.getpass('Repite la contraseña: '):raise ValueError('La contraseña no coincide o tiene menos de 12 caracteres.')
    routing=json.loads(subprocess.check_output(['ip','-j','-4','route','get','1.1.1.1'],text=True))
    host=str(ipaddress.IPv4Address(routing[0]['prefsrc']))
    version=image_version(os.uname().machine)
    application=app_environment(settings,host,password,version)
    text=env_text(application)
    compose=['docker','compose','--env-file',str(TARGET/'.env'),'-f',str(TARGET/'docker-compose.yml'),'-p',project]
    environment={**os.environ,**application}
    for key in ['GITLAB_REGISTRY_USER','GITLAB_REGISTRY_TOKEN','DOCKER_AUTH_CONFIG']:
        environment.pop(key,None)
    try:
        with tempfile.TemporaryDirectory(prefix='vsaas-registry-') as temporary:
            pull_env={**environment,'DOCKER_CONFIG':temporary}
            result=subprocess.run(['docker','login',settings['GITLAB_REGISTRY_HOST'],'--username',username,'--password-stdin'],input=token+'\n',text=True,capture_output=True,env=pull_env)
            if result.returncode:raise ValueError('No se pudo autenticar en el registro. Revisa las credenciales del proveedor; su salida no se imprimió.')
            TARGET.mkdir(mode=0o700,parents=True)
            (TARGET/'.env').write_text(text,encoding='utf-8');(TARGET/'.env').chmod(0o600)
            shutil.copyfile(PACKAGE/'docker-compose.yml',TARGET/'docker-compose.yml')
            print('Descargando las imágenes VXG '+version+'…',flush=True)
            command(compose+['pull'],env=pull_env)
        command(compose+['up','-d'],env=environment)
        command(compose+['ps'],env=environment)
    except Exception:
        print('La instalación no terminó. No se eliminaron volúmenes.',flush=True)
        if TARGET.exists():print('Se conservó el directorio privado para diagnóstico.',flush=True)
        raise
    print('VXG iniciado. Abre http://'+host+' con usuario admin y la contraseña que elegiste.')
    print('Comprueba arranque, cámaras y nube antes de declarar el servicio operativo.')
    print('Directorio de despliegue: '+str(TARGET))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--registry-env');parser.add_argument('--project',default='camera_agent_gateway')
    args=parser.parse_args()
    if getattr(os,'geteuid',lambda:-1)()!=0:raise SystemExit('Ejecuta con sudo en Ubuntu.')
    try:install(args.registry_env,args.project)
    except (ValueError,OSError,subprocess.CalledProcessError) as exc:raise SystemExit(str(exc))


if __name__=='__main__':main()
