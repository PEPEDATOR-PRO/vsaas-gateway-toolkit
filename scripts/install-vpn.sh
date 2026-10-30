#!/usr/bin/env bash
# VPN de administracion para un Gateway Ubuntu nuevo.
# Los parámetros se reciben del perfil validado por scripts/install.py.
: "${VPN_ID:?Falta VPN_ID. Usa scripts/install.py vpn --config config/equipo.json.}"
: "${VPN_RED_LOCAL:?Falta la subred local VPN.}"
: "${VPN_IP_ADMIN:?Falta la IP de administración VPN.}"
: "${VPN_SERVIDOR:?Falta el servidor VPN.}"
: "${VPN_RED_REMOTA:?Falta la red central VPN.}"

set -euo pipefail
if [ "$EUID" -ne 0 ]; then
    echo 'Ejecutar con: sudo bash configurar-vpn-gateway.sh'
    exit 1
fi
if command -v ipsec >/dev/null 2>&1; then
    echo 'Hay otro cliente IPsec. Revisar la instalacion antes de continuar.'
    exit 1
fi
if ! [[ "$VPN_ID" =~ ^[A-Za-z0-9_-]+$ ]]; then
    echo 'Identificador no valido. Usar letras, numeros, guion o guion bajo.'
    exit 1
fi
python3 - "$VPN_RED_LOCAL" "$VPN_IP_ADMIN" "$VPN_SERVIDOR" "$VPN_RED_REMOTA" <<'PY'
import ipaddress, sys
local = ipaddress.IPv4Network(sys.argv[1], strict=True)
admin = ipaddress.IPv4Address(sys.argv[2])
ipaddress.IPv4Address(sys.argv[3])
remote = ipaddress.IPv4Network(sys.argv[4], strict=True)
if admin not in local or admin in (local.network_address, local.broadcast_address):
    raise SystemExit('La IP de administracion debe ser un host valido de la red local.')
if local.overlaps(remote):
    raise SystemExit('Las redes local y remota se superponen.')
PY

printf 'ID: %s\nRed local: %s\nIP de administracion: %s\nServidor: %s\nRed central: %s\n' \
    "$VPN_ID" "$VPN_RED_LOCAL" "$VPN_IP_ADMIN" "$VPN_SERVIDOR" "$VPN_RED_REMOTA"
read -r -p 'Datos unicos y autorizados en FortiGate. Escribe SI para continuar: ' vpn_confirm </dev/tty
[ "$vpn_confirm" = 'SI' ] || exit 1
read -r -s -p 'Clave compartida de este identificador: ' vpn_key </dev/tty
printf '\n' >/dev/tty
[ -n "$vpn_key" ] || { echo 'Clave vacia. Cancelado.'; exit 1; }

apt-get update
apt-get install -y charon-systemd strongswan-swanctl
install -d -m 755 /etc/swanctl/conf.d /etc/systemd/system/strongswan.service.d
vpn_stamp=$(date +%Y%m%d-%H%M%S)
for vpn_file in /etc/swanctl/conf.d/gateway.conf \
    /etc/swanctl/conf.d/gateway-secret.conf \
    /etc/systemd/system/strongswan.service.d/gateway.conf; do
    if [ -f "$vpn_file" ]; then
        cp -p "$vpn_file" "${vpn_file}.bak-${vpn_stamp}"
    fi
done

cat > /etc/swanctl/conf.d/gateway.conf <<EOF
connections {
    gateway {
        version = 1
        aggressive = yes
        local_addrs = %any
        remote_addrs = $VPN_SERVIDOR
        proposals = aes256-sha256-modp1536
        encap = yes
        keyingtries = 0
        dpd_delay = 30s
        dpd_timeout = 120s
        reauth_time = 0s
        rekey_time = 23h
        over_time = 1h
        rand_time = 0s
        local {
            auth = psk
            id = @$VPN_ID
        }
        remote {
            auth = psk
            id = %any
        }
        children {
            administracion {
                local_ts = $VPN_RED_LOCAL
                remote_ts = $VPN_RED_REMOTA
                mode = tunnel
                esp_proposals = aes256-sha1-modp1536
                life_time = 8h
                rekey_time = 7h
                rand_time = 0s
                start_action = start
                dpd_action = restart
                close_action = start
            }
        }
    }
}
EOF

vpn_hex=$(printf '%s' "$vpn_key" | od -An -v -tx1 | tr -d ' \n')
(
    umask 077
    printf 'secrets {\n    ike-gateway {\n        id = @%s\n        secret = 0x%s\n    }\n}\n' \
        "$VPN_ID" "$vpn_hex" > /etc/swanctl/conf.d/gateway-secret.conf
)
chmod 600 /etc/swanctl/conf.d/gateway-secret.conf
unset vpn_key vpn_hex

cat > /etc/systemd/system/strongswan.service.d/gateway.conf <<EOF
[Unit]
Wants=network-online.target
After=network-online.target

[Service]
ExecStartPre=/usr/bin/env ip address replace $VPN_IP_ADMIN/32 dev lo
Restart=on-failure
RestartSec=10s
EOF

systemctl daemon-reload
systemctl enable strongswan
systemctl restart strongswan
echo 'Configuracion aplicada. Esto no confirma que el tunel haya conectado.'
echo 'Ejecutar: sudo swanctl --list-sas'
echo 'Y: sudo journalctl -u strongswan -n 60 --no-pager'
printf 'Con FortiClient conectado, probar: http://%s\n' "$VPN_IP_ADMIN"
