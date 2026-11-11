#!/usr/bin/env python3
"""Install optional outbound health agent. Never enable reporting implicitly."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import socket

ROOT = Path(__file__).resolve().parents[1]
LIBEXEC = Path('/usr/local/libexec')
PORTAL = Path('/usr/local/share/cockpit/gateway_telemetria')
CONFIG = Path('/etc/vsaas-gateway/telemetria.json')
UNITS = Path('/etc/systemd/system')


def install():
    if getattr(os, 'geteuid', lambda: -1)() != 0 or not sys.platform.startswith('linux'):
        raise ValueError('Ejecuta con sudo en Ubuntu Linux.')
    if not shutil.which('cockpit-bridge'):
        raise ValueError('Instala Cockpit antes de agregar Telemetría de salud.')
    source = ROOT / 'src/telemetria'
    target = LIBEXEC / 'vsaas-telemetria'
    target.mkdir(mode=0o755, parents=True, exist_ok=True)
    for name in ('agent.py', 'common.py'):
        shutil.copyfile(source / name, target / name)
        (target / name).chmod(0o644)
    shutil.copyfile(ROOT / 'src/cockpit/vxg-health.py', LIBEXEC / 'vsaas-telemetry-health.py')
    (LIBEXEC / 'vsaas-telemetry-health.py').chmod(0o644)
    if not CONFIG.exists():
        CONFIG.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        config = dict(device_id=str(uuid.uuid4()), name=socket.gethostname(), interval=30, enabled=False, destinations=[])
        # Exclusive creation ensures a concurrent install cannot replace keys.
        with CONFIG.open('x', encoding='utf-8') as output:
            json.dump(config, output)
    CONFIG.chmod(0o600)
    PORTAL.mkdir(mode=0o755, parents=True, exist_ok=True)
    for name in ('index.html', 'manifest.json', 'agent-ui.js', 'style.css'):
        shutil.copyfile(source / name, PORTAL / name)
        (PORTAL / name).chmod(0o644)
    UNITS.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source / 'vsaas-telemetria.service', UNITS / 'vsaas-telemetria.service')
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', 'vsaas-telemetria.service'], check=True)
    subprocess.run(['systemctl', 'restart', 'vsaas-telemetria.service'], check=True)
    print('Instalado: Cockpit → Herramientas → Telemetría de salud. Cierra sesión y vuelve a entrar.')
    print('En una instalación nueva el envío queda desactivado y sin destinos. Las actualizaciones conservan tu configuración.')


if __name__ == '__main__':
    try:
        install()
    except (ValueError, OSError) as error:
        raise SystemExit(str(error))
