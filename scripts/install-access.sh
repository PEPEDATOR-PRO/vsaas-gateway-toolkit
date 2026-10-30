#!/usr/bin/env bash
set -euo pipefail
if [ "$EUID" -ne 0 ]; then echo 'Ejecutar desde scripts/install.py con sudo.'; exit 1; fi
case "${1:-}" in
  ssh)
    apt-get update
    apt-get install --no-install-recommends -y openssh-server
    systemctl enable --now ssh.socket
    ;;
  cockpit)
    : "${VPN_IP_ADMIN:?Falta la IP de administración del perfil.}"
    apt-get update
    apt-get install --no-install-recommends -y cockpit-ws cockpit-system cockpit-bridge nmap arp-scan htop
    install -d -m 755 /etc/systemd/system/cockpit.socket.d
    if [ -f /etc/systemd/system/cockpit.socket.d/listen.conf ]; then
      cp -p /etc/systemd/system/cockpit.socket.d/listen.conf "/etc/systemd/system/cockpit.socket.d/listen.conf.bak-$(date +%Y%m%d-%H%M%S)"
    fi
    cat > /etc/systemd/system/cockpit.socket.d/listen.conf <<EOF
[Socket]
ListenStream=
ListenStream=$VPN_IP_ADMIN:9090
FreeBind=yes
EOF
    systemctl daemon-reload
    systemctl enable --now cockpit.socket
    systemctl restart cockpit.socket
    printf 'Panel: https://%s:9090\n' "$VPN_IP_ADMIN"
    ;;
  *) echo 'Módulo esperado: ssh o cockpit'; exit 1 ;;
esac
