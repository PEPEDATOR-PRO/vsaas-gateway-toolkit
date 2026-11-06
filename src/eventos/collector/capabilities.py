"""Read-only, on-demand capability inspection; never changes camera rules."""
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import requests

from .onvif import NS, OnvifClient, OnvifHTTPError


def local(tag):
    return tag.rsplit('}', 1)[-1]


def xml_fields(root):
    """Keep namespace-qualified paths so vendor attributes remain distinguishable."""
    result = set()
    def walk(node, path):
        path = path + '/' + node.tag
        if len(node) == 0 or (node.text and node.text.strip()):
            result.add(path)
        result.update(path + '/@' + key for key in node.attrib)
        for child in node:
            walk(child, path)
    walk(root, '')
    return sorted(result)[:500]


def observed_fields(events):
    fields = set()
    def walk(value, path, depth=0):
        if depth > 20 or len(fields) >= 500:
            return
        if isinstance(value, dict):
            if isinstance(value.get('tag'), str):
                path += '/' + value['tag']
            for key, child in value.items():
                if key.endswith('_xml') or key == 'xml':
                    continue
                here = path + '.' + key if path else key
                if key in ('Name', 'name') and isinstance(child, str):
                    fields.add(path + '[' + child[:120] + ']')
                walk(child, here, depth + 1)
        elif isinstance(value, list):
            for child in value[:100]:
                walk(child, path + '[]', depth + 1)
        else:
            fields.add(path)
    for event in events:
        walk(event.get('metadata', {}), 'metadata')
    return sorted(fields)[:500]


def inspect_camera(camera, events, client_factory=OnvifClient):
    report = {'camera_id': camera['id'], 'camera_name': camera['name'],
              'checked_at': datetime.now(timezone.utc).isoformat(),
              'device': {}, 'services': [], 'event_topics': [], 'metadata_fields': [],
              'analytics': [],
              'observed': {'sample_count': len(events),
                           'topics': sorted({e['topic'] for e in events}),
                           'fields': observed_fields(events)},
              'queries': [], 'summary': [], 'limitations': [
                  'Lo anunciado por la cámara no confirma que esté habilitado ni que se haya recibido en vivo.',
                  'Se revisan hasta 100 eventos recientes conservados en la cola, con un máximo de 2 MiB de muestras; se omiten los que excedan el presupuesto. El envío y la retención pueden retirar muestras.',
                  'La consulta genérica usa ONVIF. Las API privadas del fabricante pueden exponer más información.']}
    # Return only sanitized responses, never SOAP request headers or stored credentials.
    secrets = [camera.get(key, '') for key in ('password', 'username', 'webhook_token')]
    def redact(value):
        for secret in sorted(filter(None, secrets), key=len, reverse=True):
            value = value.replace(secret, '[oculto]')
        value = re.sub(r'(?i)(https?|rtsp)://[^\s<>"/]+@', r'\1://[oculto]@', value)
        value = re.sub(r'(?i)([?&](?:token|password|key|secret|auth)=)[^\s<>"&]+', r'\1[oculto]', value)
        return value

    if camera['mode'] != 'onvif':
        report['summary'].append('Cámara HTTP: se describen los campos recibidos; no hay conexión ONVIF configurada para consultar capacidades.')
    else:
        client = client_factory(camera)
        deadline = time.monotonic() + 65

        def query(url, prefix, operation, fields=()):
            entry = {'operation': operation, 'status': 'sin respuesta', 'response': ''}
            report['queries'].append(entry)
            remaining = deadline - time.monotonic()
            if remaining < 1:
                entry['status'] = 'omitida'; entry['detail'] = 'Tiempo máximo de consulta alcanzado.'
                return None
            # Never send saved camera credentials to an unrelated advertised host.
            if urlparse(url).hostname != urlparse(camera['device_url']).hostname:
                entry['status'] = 'omitida'; entry['detail'] = 'El servicio anuncia otro host; revisa la configuración ONVIF del equipo.'
                return None
            action = NS[prefix] + '/' + operation
            if prefix == 'tev':
                action = NS[prefix] + '/EventPortType/' + operation + 'Request'
            try:
                root, _ = client.call(url, action, prefix + ':' + operation, fields,
                                      timeout=(min(3, remaining / 2), min(5, remaining / 2)))
                body = root.find('s:Body', NS)
                if body is None:
                    raise ValueError('Respuesta sin cuerpo SOAP')
                if not any(local(n.tag) == operation + 'Response' for n in body):
                    raise ValueError('Respuesta SOAP distinta de la operación solicitada')
                # Round-trip XML to escape text before removing literal secrets.
                safe = ET.fromstring(ET.tostring(body))
                for node in safe.iter():
                    if any(word in local(node.tag).lower() for word in ('password', 'token', 'secret', 'security')):
                        node.clear(); node.text = '[oculto]'
                    if node.text:
                        node.text = redact(node.text)
                    for key, value in list(node.attrib.items()):
                        node.set(key, redact(value))
                raw = ET.tostring(safe, encoding='unicode')
                entry.update(status='respondió', response=raw[:65536], truncated=len(raw) > 65536)
                return body
            except Exception as exc:
                entry['status'] = 'no confirmada'
                if isinstance(exc, OnvifHTTPError):
                    entry['detail'] = f'HTTP {exc.status_code}. Revisa permisos, compatibilidad y dirección del servicio.'
                elif isinstance(exc, requests.exceptions.SSLError):
                    entry['detail'] = 'No se pudo verificar el certificado HTTPS de la cámara.'
                elif isinstance(exc, requests.exceptions.Timeout):
                    entry['detail'] = 'La cámara no respondió dentro del tiempo de espera.'
                elif isinstance(exc, requests.exceptions.ConnectionError):
                    entry['detail'] = 'No se pudo establecer conexión con el servicio de la cámara.'
                elif 'NotAuthorized' in str(exc):
                    entry['detail'] = 'La cámara rechazó la autorización. Revisa credenciales, permisos y hora del equipo.'
                elif any(code in str(exc) for code in ('ActionNotSupported', 'OptionalActionNotImplemented')):
                    entry['detail'] = 'La cámara indica que no admite esta consulta ONVIF.'
                else:
                    entry['detail'] = 'No se obtuvo una respuesta válida: operación no admitida, error SOAP, conexión, certificado o tiempo agotado.'
                return None

        try:
            device = query(camera['device_url'], 'tds', 'GetDeviceInformation')
            if device is not None:
                report['device'] = {local(n.tag): redact(n.text.strip()) for n in device.iter()
                                    if local(n.tag) in ('Manufacturer', 'Model', 'FirmwareVersion') and n.text}
            caps = query(camera['device_url'], 'tds', 'GetCapabilities', [('tds:Category', 'All')])
            services = {}
            if caps is not None:
                for name, prefix in [('Events', 'tev'), ('Media', 'trt'), ('Analytics', 'tan')]:
                    address = caps.findtext('.//tt:' + name + '/tt:XAddr', namespaces=NS)
                    if address:
                        services[prefix] = address.strip()
            discovered = query(camera['device_url'], 'tds', 'GetServices', [('tds:IncludeCapability', 'false')])
            if discovered is not None:
                for service in discovered.iter():
                    if local(service.tag) != 'Service':
                        continue
                    parts = {local(n.tag): (n.text or '').strip() for n in service}
                    for prefix in ('tev', 'trt', 'tr2', 'tan'):
                        if parts.get('Namespace') == NS[prefix] and parts.get('XAddr'):
                            services[prefix] = parts['XAddr']
            report['services'] = [{'namespace': NS[p], 'address': redact(u)} for p, u in services.items()]
            if 'tev' in services:
                topics = query(services['tev'], 'tev', 'GetEventProperties')
                if topics is not None:
                    def walk(node, path):
                        here = path + '/' + local(node.tag)
                        if any(local(k) == 'topic' and v in ('true', '1') for k, v in node.attrib.items()):
                            descriptors = [{'group': local(group.tag), 'name': n.get('Name', ''),
                                            'type': n.get('Type', '')}
                                           for group in node.iter() if local(group.tag) in ('Source', 'Key', 'Data')
                                           for n in group if local(n.tag).endswith('ItemDescription')]
                            report['event_topics'].append({'topic': here.lstrip('/'), 'properties': descriptors})
                        for child in node:
                            walk(child, here)
                    for node in topics.iter():
                        if local(node.tag) == 'TopicSet':
                            for child in node:
                                walk(child, '')
            if 'tan' in services:
                metadata = query(services['tan'], 'tan', 'GetSupportedMetadata')
                if metadata is not None:
                    report['metadata_fields'] = sorted({path for n in metadata.iter()
                                                       if local(n.tag) in ('SampleFrame', 'Frame')
                                                       for path in xml_fields(n)})[:500]
            configurations = set()
            for prefix in ('trt', 'tr2'):
                if prefix in services:
                    profiles = query(services[prefix], prefix, 'GetProfiles')
                    if profiles is not None:
                        for node in profiles.iter():
                            if local(node.tag) in ('VideoAnalyticsConfiguration', 'Analytics') and node.get('token'):
                                configurations.add(node.get('token'))
            if 'tan' in services:
                for token in sorted(configurations)[:2]:
                    for operation in ('GetSupportedAnalyticsModules', 'GetSupportedRules'):
                        supported = query(services['tan'], 'tan', operation, [('tan:ConfigurationToken', token)])
                        if supported is not None:
                            report['analytics'].extend(sorted({n.get('Name') for n in supported.iter()
                                                               if local(n.tag) in ('AnalyticsModuleDescription', 'RuleDescription') and n.get('Name')}))
                if len(configurations) > 2:
                    report['limitations'].append('Se consultaron reglas y módulos de las primeras dos configuraciones analíticas.')
            if not services:
                report['limitations'].append('No se descubrieron servicios: revisa ONVIF, permisos, dirección y conectividad. Esto no demuestra ausencia de analíticos.')
        finally:
            client.session.close()
        ok = sum(q['status'] == 'respondió' for q in report['queries'])
        report['summary'].extend([
            f'{ok} de {len(report["queries"])} consultas obtuvieron una respuesta válida.',
            f'La cámara anunció {len(report["event_topics"])} tipos de evento y {len(report["metadata_fields"])} campos en muestras de metadatos.',
            'Consulta las respuestas de perfiles para revisar las configuraciones de video, analítica y metadatos que anuncia el equipo.'])
        if report['event_topics']:
            report['summary'].append('Eventos disponibles según el equipo: ' + ', '.join(t['topic'] for t in report['event_topics'][:12]) + '.')
        if report['metadata_fields']:
            labels = sorted({path.rsplit('}', 1)[-1] for path in report['metadata_fields']})
            names = {'Gender': 'sexo estimado', 'Age': 'edad estimada', 'AgeType': 'grupo de edad estimado',
                     'BoundingBox': 'posición del objeto en la imagen', 'ObjectId': 'identificador de seguimiento',
                     'Likelihood': 'confianza de la clasificación', 'Color': 'color', 'ColorString': 'color',
                     'PlateNumber': 'texto de matrícula', 'LicensePlate': 'matrícula', 'VehicleType': 'tipo de vehículo',
                     'Tops': 'ropa superior', 'Bottoms': 'ropa inferior', 'Hat': 'gorra o sombrero',
                     'Bag': 'bolsa', 'Mask': 'mascarilla', 'Glasses': 'lentes'}
            tags = {local(part).lstrip('@') for path in report['metadata_fields'] for part in path.split('/')}
            friendly = sorted({name for tag, name in names.items() if tag in tags})
            report['summary'].append('La muestra de metadatos incluye: ' + ', '.join(friendly or labels[:30]) + '.')
        if report['analytics']:
            report['summary'].append('Reglas y módulos anunciados: ' + ', '.join(sorted(set(report['analytics']))[:20]) + '.')
    report['summary'].append(f'Se revisaron {len(events)} eventos recibidos: {len(report["observed"]["topics"])} tipos y {len(report["observed"]["fields"])} campos observados.')
    if not events:
        report['limitations'].append('Sin muestras en la cola. Activa una regla, provoca una detección y vuelve a consultar.')
    return report
