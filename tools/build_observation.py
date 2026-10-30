from pathlib import Path
repository=Path(__file__).resolve().parents[1]
root=repository/'src'/'observacion'
output=repository/'dist'/'instalar-observacion-vsaas-24h.sh'
output.parent.mkdir(exist_ok=True)
head='''#!/usr/bin/env bash
set -euo pipefail
if [ "$EUID" -ne 0 ]; then
    echo 'Ejecutar: sudo bash instalar-observacion-vsaas-24h.sh'
    exit 1
fi
if systemctl is-active --quiet vsaas-observacion.service; then
    echo 'Ya hay una observacion activa. No se modifico ni reinicio.'
    echo 'Consulta: sudo vsaas-observacion estado'
    exit 0
fi
command -v docker >/dev/null || { echo 'No se encontro Docker.'; exit 1; }
command -v python3 >/dev/null || { echo 'No se encontro Python 3.'; exit 1; }
LAN_INTERFACE="${LAN_INTERFACE:-eth0}"
if ! [[ "$LAN_INTERFACE" =~ ^[A-Za-z0-9_.:-]{1,32}$ ]]; then
    echo 'Nombre de interfaz no valido.'
    exit 1
fi
if [ ! -d "/sys/class/net/$LAN_INTERFACE/statistics" ]; then
    echo 'No se encontro la interfaz seleccionada. Revisa el perfil.'
    exit 1
fi
install -d -m 755 /usr/local/libexec /usr/local/bin
install -d -m 700 /var/lib/vsaas-observacion /var/log/vsaas-observacion
'''
files=[(root/'recopilador.py','/usr/local/libexec/vsaas-observacion.py',644),
       (root.parent/'cockpit'/'vxg-health.py','/usr/local/libexec/vsaas-observacion-health.py',644),
       (root/'vsaas-observacion.service','/etc/systemd/system/vsaas-observacion.service',644)]
parts=[head]
for i,(source,target,mode) in enumerate(files):
    marker=f'VSAAS_OBSERVACION_{i}_END'
    text=source.read_text(encoding='utf-8')
    assert marker not in text
    parts.append(f"cat > '{target}' <<'{marker}'\n{text.rstrip()}\n{marker}\nchmod {mode} '{target}'\n")
parts.append('''cat > /usr/local/bin/vsaas-observacion <<'VSAAS_WRAPPER_END'
#!/bin/sh
exec /usr/bin/python3 /usr/local/libexec/vsaas-observacion.py "$@"
VSAAS_WRAPPER_END
chmod 755 /usr/local/bin/vsaas-observacion
/usr/local/bin/vsaas-observacion preparar --interfaz "$LAN_INTERFACE" --horas 24
systemctl daemon-reload
systemctl enable --now vsaas-observacion.service
echo ''
echo 'Prueba iniciada por 24 horas. Puedes cerrar Cockpit y SSH.'
echo 'Trafico y recursos: cada 5 segundos. Salud: cada 60 segundos.'
echo 'Limite de registros: 128 MiB por prueba. Memoria maxima del grupo: 192 MiB.'
echo 'Se detiene al finalizar; los registros se conservan.'
echo 'Estado: sudo vsaas-observacion estado'
echo 'Servicio: sudo systemctl status vsaas-observacion --no-pager'
echo 'Detener antes: sudo systemctl stop vsaas-observacion'
echo 'Exportar al terminar: sudo vsaas-observacion exportar'
''')
output.write_bytes(''.join(parts).encode('utf-8'))
print(output)
