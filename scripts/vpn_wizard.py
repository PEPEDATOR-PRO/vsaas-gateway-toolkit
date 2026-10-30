"""Ask only for device identity/subnet; the shell installer reads the PSK."""
import ipaddress
import json
from pathlib import Path
try:
    from .profile import validate_profile
except ImportError:
    from profile import validate_profile

CENTRAL_SERVER='35.161.111.223'
CENTRAL_SUBNET='172.31.0.0/17'


def configure(path,write=True):
    path=Path(path)
    if path.exists():
        data=json.loads(path.read_text(encoding='utf-8'))
    else:
        data=json.loads((Path(__file__).resolve().parents[1]/'config/equipo.example.json').read_text(encoding='utf-8'))
    identifier=input('Leftid de este Gateway (sin @): ').strip()
    subnet=ipaddress.IPv4Network(input('Subred asignada en FortiGate (ejemplo: 10.254.0.0/29): ').strip(),strict=True)
    if subnet.prefixlen>30:
        raise ValueError('La subred debe disponer de direcciones de host: /30 o una red mayor.')
    data.update(vpn_id=identifier,vpn_local_subnet=str(subnet),
                vpn_admin_ip=str(subnet.network_address+1),
                vpn_server=CENTRAL_SERVER,vpn_remote_subnet=CENTRAL_SUBNET)
    validate_profile(data)
    if write:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    print('IP de administración automática: '+data['vpn_admin_ip'])
    print('FortiGate: '+CENTRAL_SERVER+' · Red central: '+CENTRAL_SUBNET)
    return data
