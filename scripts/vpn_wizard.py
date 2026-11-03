"""Ask only for device identity/subnet; the shell installer reads the PSK."""
import ipaddress
import json
from pathlib import Path
try:
    from .profile import validate_profile
except ImportError:
    from profile import validate_profile

CENTRAL_CONFIG=Path(__file__).resolve().parents[1]/'config/vpn-central.json'


def central_settings(profile):
    if CENTRAL_CONFIG.is_file():
        settings=json.loads(CENTRAL_CONFIG.read_text(encoding='utf-8'))
        if not isinstance(settings,dict) or set(settings)!={'vpn_server','vpn_remote_subnet'}:
            raise ValueError('vpn-central.json solo admite vpn_server y vpn_remote_subnet; no guardes claves.')
    else:
        settings={key:profile.get(key) for key in ['vpn_server','vpn_remote_subnet']}
    if not all(isinstance(value,str) for value in settings.values()):
        raise ValueError('El servidor y la red central deben ser texto en config/vpn-central.json.')
    try:
        server=ipaddress.IPv4Address(settings['vpn_server'])
        remote=ipaddress.IPv4Network(settings['vpn_remote_subnet'],strict=True)
    except (ValueError,TypeError):
        raise ValueError('Configura el servidor y la red central en config/vpn-central.json antes de iniciar el asistente.') from None
    examples=[ipaddress.IPv4Network(n) for n in ['192.0.2.0/24','198.51.100.0/24','203.0.113.0/24']]
    if any(server in net for net in examples):
        raise ValueError('Sustituye el servidor ficticio de config/vpn-central.json por el FortiGate de tu organización. Consulta docs/GUIA-COMPLETA.md.')
    return {'vpn_server':str(server),'vpn_remote_subnet':str(remote)}


def configure(path,write=True):
    path=Path(path)
    if path.exists():
        data=json.loads(path.read_text(encoding='utf-8'))
    else:
        data=json.loads((Path(__file__).resolve().parents[1]/'config/equipo.example.json').read_text(encoding='utf-8'))
    central=central_settings(data)
    identifier=input('Leftid de este Gateway (sin @): ').strip()
    subnet=ipaddress.IPv4Network(input('Subred asignada en FortiGate (ejemplo: 10.254.0.0/29): ').strip(),strict=True)
    if subnet.prefixlen>30:
        raise ValueError('La subred debe disponer de direcciones de host: /30 o una red mayor.')
    data.update(vpn_id=identifier,vpn_local_subnet=str(subnet),
                vpn_admin_ip=str(subnet.network_address+1),
                **central)
    validate_profile(data)
    if write:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    print('IP de administración automática: '+data['vpn_admin_ip'])
    print('FortiGate: '+central['vpn_server']+' · Red central: '+central['vpn_remote_subnet'])
    return data
