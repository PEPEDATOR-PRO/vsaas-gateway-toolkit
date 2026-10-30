"""Device settings only. Credentials are deliberately not supported here."""
import ipaddress
import json
from pathlib import Path
import re

FIELDS={'vpn_id','vpn_local_subnet','vpn_admin_ip','vpn_server','vpn_remote_subnet','lan_interface','compose_project','overview_overlay'}


def load_profile(path,ready=True):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    return validate_profile(data,ready)


def validate_profile(data,ready=True):
    if not isinstance(data,dict):raise ValueError('La configuración debe ser un objeto JSON.')
    if set(data)!=FIELDS:raise ValueError('Faltan campos o hay campos no admitidos. No guardes contraseñas, PSK o tokens en el perfil.')
    for key in FIELDS-{'overview_overlay'}:
        if not isinstance(data[key],str):raise ValueError('Campo no textual: '+key)
    if type(data['overview_overlay']) is not bool:raise ValueError('overview_overlay debe ser true o false.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',data['vpn_id']):raise ValueError('vpn_id no válido; no incluyas @.')
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,32}',data['lan_interface']):raise ValueError('Interfaz no válida.')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}',data['compose_project']):raise ValueError('Proyecto Compose no válido.')
    local=ipaddress.IPv4Network(data['vpn_local_subnet'],strict=True)
    remote=ipaddress.IPv4Network(data['vpn_remote_subnet'],strict=True)
    admin=ipaddress.IPv4Address(data['vpn_admin_ip'])
    ipaddress.IPv4Address(data['vpn_server'])
    if admin not in local or admin in (local.network_address,local.broadcast_address):raise ValueError('La IP de administración debe ser un host válido de la subred local.')
    if local.overlaps(remote):raise ValueError('Las subredes VPN se superponen.')
    if ready and (data['vpn_id'].startswith('CAMBIAR') or data['vpn_server']=='203.0.113.10'):
        raise ValueError('Sustituye los datos de ejemplo por los valores autorizados en FortiGate.')
    return data
