#!/usr/bin/env python3
"""Reversible overlay for the installed Cockpit system package. Linux only."""
import datetime
import gzip
import json
import os
from pathlib import Path
import shutil

OVERLAY=Path('/usr/local/share/cockpit/vsaas_system')
RESOURCES=Path('/usr/local/share/cockpit/gateway_scanner')
BACKUPS=Path('/var/backups')
MARKER='.vsaas-overview-overlay'


def source_package():
    for candidate in [Path('/usr/share/cockpit/systemd'),Path('/usr/share/cockpit/system')]:
        manifest=candidate/'manifest.json'
        if manifest.is_file():
            data=json.loads(manifest.read_text())
            if data.get('name',candidate.name)=='system':
                return candidate,data
    raise RuntimeError('No se encontró el paquete system de Cockpit. No se cambió la vista global.')


def read_index(source):
    for filename in ['index.html','index.html.gz']:
        p=source/filename
        if p.is_file():
            return gzip.decompress(p.read_bytes()).decode('utf-8') if filename.endswith('.gz') else p.read_text()
    raise RuntimeError('No se encontró index.html de Cockpit. No se cambió la vista global.')


def inject_html(html):
    if 'base1/cockpit.js' not in html or 'id="overview"' not in html:
        raise RuntimeError('Esta versión de la vista global no coincide con la adaptación. No se cambió la vista global.')
    if '</head>' not in html:
        raise RuntimeError('Cabecera de la vista global no reconocida.')
    additions='\n<link rel="stylesheet" href="../gateway_scanner/overview-cards.css">\n<script defer src="../gateway_scanner/overview-cards.js"></script>\n'
    return html.replace('</head>',additions+'</head>',1)


def install():
    source,manifest=source_package()
    html=inject_html(read_index(source))
    for resource in ['overview-cards.js','overview-cards.css']:
        if not (RESOURCES/resource).is_file():
            raise RuntimeError('Falta el recurso '+resource+'. No se cambió la vista global.')
    if OVERLAY.exists() and not (OVERLAY/MARKER).is_file():
        raise RuntimeError('Ya existe una adaptación ajena en '+str(OVERLAY)+'. No se modificó.')
    saved=None
    if OVERLAY.exists():
        saved=BACKUPS/('vsaas-overview-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        saved.mkdir(mode=0o700,parents=True)
        OVERLAY.rename(saved/'vsaas_system')
    try:
        OVERLAY.mkdir(mode=0o755,parents=True)
        for entry in source.iterdir():
            if entry.name in ('manifest.json','manifest.json.gz') or entry.name.startswith('index.html'):
                continue
            (OVERLAY/entry.name).symlink_to(entry,target_is_directory=entry.is_dir())
        manifest['name']='system'
        manifest['priority']=max(100,int(manifest.get('priority',0))+1)
        (OVERLAY/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        (OVERLAY/'index.html').write_text(html)
        (OVERLAY/MARKER).write_text('v1\n')
        print('Tarjetas añadidas a la vista global mediante una adaptación local reversible.')
        print('Cierra sesión en Cockpit y vuelve a entrar. No reinicies Docker ni la VPN.')
        print('Tras actualizar Cockpit, vuelve a ejecutar este instalador si hace falta.')
        print('Para retirar la adaptación, mueve /usr/local/share/cockpit/vsaas_system fuera de /usr/local/share/cockpit y vuelve a iniciar sesión.')
        if saved:print('Respaldo de la adaptación anterior: '+str(saved))
    except Exception:
        # All paths below are fixed and owned by this installer.
        # Move the incomplete overlay aside rather than delete anything.
        if OVERLAY.exists():
            failed=BACKUPS/('vsaas-overview-incomplete-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
            OVERLAY.rename(failed)
        if saved:(saved/'vsaas_system').rename(OVERLAY)
        raise


if __name__=='__main__':
    if os.geteuid()!=0:raise SystemExit('Ejecuta el instalador con sudo.')
    install()
