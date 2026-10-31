#!/usr/bin/env python3
"""Explicit, modular installation for a configured Ubuntu device."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
try:
    from .profile import load_profile
except ImportError:
    from profile import load_profile

ROOT=Path(__file__).resolve().parents[1]
CONFIG_DIR=Path('/etc/vsaas-gateway')
MODULES=['vxg','vpn','ssh','cockpit','paneles','resumen','observacion','todo']


def plan(module,profile):
    if module=='todo':return ['vpn','ssh','cockpit','paneles']+(['resumen'] if profile['overview_overlay'] else [])
    return [module]


def main():
    parser=argparse.ArgumentParser(description='Instalación modular Vsaas Gateway')
    parser.add_argument('module',choices=MODULES)
    parser.add_argument('--config',default=str(ROOT/'config/equipo.json'))
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--interactive',action='store_true',help='Configurar VPN solicitando leftid, subred y PSK local')
    parser.add_argument('--vxg-env',help='Archivo local privado de credenciales del proveedor para el módulo vxg')
    args=parser.parse_args()
    if args.interactive and args.module!='vpn':parser.error('--interactive solo se utiliza con vpn')
    if args.module=='vxg':
        project='camera_agent_gateway'
        if Path(args.config).is_file():project=load_profile(args.config,ready=False)['compose_project']
        if args.dry_run:
            print('Simulación: VXG 1.0.16; credenciales locales; proyecto '+project+'. No se ejecutó Docker ni se leyó el archivo privado.')
            return
        command=[sys.executable,str(ROOT/'scripts/install_vxg.py'),'--project',project]
        if args.vxg_env:command+=['--registry-env',args.vxg_env]
        subprocess.run(command,check=True)
        return
    interactive=args.module=='vpn' and (args.interactive or not Path(args.config).is_file())
    if interactive:
        if not args.dry_run and (getattr(os,'geteuid',lambda:-1)()!=0 or not sys.platform.startswith('linux')):
            raise SystemExit('Ejecuta con sudo en Ubuntu.')
        try:
            from .vpn_wizard import configure
        except ImportError:
            from vpn_wizard import configure
        profile=configure(args.config,write=not args.dry_run)
    else:
        profile=load_profile(args.config,ready=not args.dry_run)
    modules=plan(args.module,profile)
    print('Módulos: '+', '.join(modules),flush=True)
    print('Equipo: '+profile['vpn_id']+' · IP de administración: '+profile['vpn_admin_ip'],flush=True)
    if args.dry_run:
        print('Simulación: no se ejecutó ningún instalador ni se escribió configuración del sistema.')
        return
    if getattr(os,'geteuid',lambda:-1)()!=0:raise SystemExit('Ejecuta con sudo en Ubuntu.')
    if not sys.platform.startswith('linux'):raise SystemExit('La instalación debe ejecutarse en Ubuntu Linux.')
    subprocess.run([sys.executable,str(ROOT/'tools/build.py')],check=True)
    config_dir=CONFIG_DIR;config_dir.mkdir(mode=0o755,parents=True,exist_ok=True)
    (config_dir/'config.json').write_text(json.dumps(profile,indent=2)+'\n')
    env={**os.environ,'VPN_ID':profile['vpn_id'],'VPN_RED_LOCAL':profile['vpn_local_subnet'],
         'VPN_IP_ADMIN':profile['vpn_admin_ip'],'VPN_SERVIDOR':profile['vpn_server'],
         'VPN_RED_REMOTA':profile['vpn_remote_subnet'],'LAN_INTERFACE':profile['lan_interface']}
    env['VPN_INTERACTIVE_VALIDATED']='1' if interactive else '0'
    for module in modules:
        print('Instalando '+module+'…',flush=True)
        if module=='vpn':command=['bash',str(ROOT/'scripts/install-vpn.sh')]
        elif module in ['ssh','cockpit']:command=['bash',str(ROOT/'scripts/install-access.sh'),module]
        elif module=='paneles':command=['bash',str(ROOT/'dist/instalar-escaner-cockpit.sh')]
        elif module=='resumen':command=['bash',str(ROOT/'dist/instalar-resumen-general.sh')]
        else:command=['bash',str(ROOT/'dist/instalar-observacion-vsaas-24h.sh')]
        subprocess.run(command,env=env,check=True)
    print('Instalación aplicada. Completa las comprobaciones de docs/INSTALACION.md.')


if __name__=='__main__':
    try:main()
    except (ValueError,FileNotFoundError) as exc:raise SystemExit(str(exc))
