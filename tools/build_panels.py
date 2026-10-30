from pathlib import Path

repository = Path(__file__).resolve().parents[1]
root = repository / 'src' / 'cockpit'
out = repository / 'dist' / 'instalar-escaner-cockpit.sh'
out.parent.mkdir(exist_ok=True)
head = '''#!/usr/bin/env bash
# Escaner visual para Cockpit. No instala demonios ni modifica VPN o Docker.
set -euo pipefail
if [ "$EUID" -ne 0 ]; then
    echo 'Ejecutar: sudo bash instalar-escaner-cockpit.sh'
    exit 1
fi
if ! command -v cockpit-bridge >/dev/null 2>&1; then
    echo 'Instala Cockpit y comprueba que puedes iniciar sesion antes de continuar.'
    exit 1
fi
apt-get update
apt-get install --no-install-recommends -y python3 arp-scan nmap
if [ -d /usr/local/share/cockpit/gateway_scanner ]; then
    backup="/var/backups/gateway-scanner-$(date +%Y%m%d-%H%M%S)"
    install -d -m 700 "$backup"
    cp -a /usr/local/share/cockpit/gateway_scanner "$backup/"
    if [ -f /usr/local/libexec/gateway-scanner.py ]; then
        cp -p /usr/local/libexec/gateway-scanner.py "$backup/"
    fi
    if [ -f /usr/local/libexec/vxg-health.py ]; then
        cp -p /usr/local/libexec/vxg-health.py "$backup/"
    fi
    echo "Copia de la version anterior: $backup"
fi
install -d -m 755 /usr/local/share/cockpit/gateway_scanner /usr/local/libexec
'''
parts = [head]
for index, name in enumerate(['manifest.json','index.html','scanner.css','scanner.js','traffic.html','traffic.css','traffic.js','health.html','health.css','health.js','overview-cards.js','overview-cards.css','gateway-scanner.py','vxg-health.py','install-overview-overlay.py']):
    target = '/usr/local/libexec/'+name if name.endswith('.py') else '/usr/local/share/cockpit/gateway_scanner/' + name
    tag = f'GATEWAY_SCANNER_FILE_{index}_END'
    text = (root/name).read_text(encoding='utf-8')
    assert tag not in text
    parts.append(f"cat > '{target}' <<'{tag}'\n{text.rstrip()}\n{tag}\nchmod 644 '{target}'\n")
parts.append('''python3 -m json.tool /usr/local/share/cockpit/gateway_scanner/manifest.json >/dev/null
echo ''
echo 'Escaner instalado. Cierra sesion en Cockpit y vuelve a entrar.'
echo 'Busca Escaner de red en el menu de herramientas.'
echo 'Busca Trafico de red junto a la vista global. Inicia detenido.'
echo 'Busca Salud Vsaas para consultar el diagnostico local bajo demanda.'
echo 'Activa el acceso administrativo de Cockpit antes de buscar equipos.'
echo 'No hace falta reiniciar Ubuntu, Docker ni la VPN.'
''')
out.write_bytes(''.join(parts).encode('utf-8'))
overview_out=repository/'dist'/'instalar-resumen-general.sh'
overview_out.write_bytes((''.join(parts)+'\npython3 /usr/local/libexec/install-overview-overlay.py\n').encode('utf-8'))
print(out)
print(overview_out)
