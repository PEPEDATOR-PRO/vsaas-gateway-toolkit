import base64
import copy
import hashlib
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import requests
from defusedxml.ElementTree import fromstring
from requests.auth import HTTPDigestAuth

NS = {
    's': 'http://www.w3.org/2003/05/soap-envelope',
    'a': 'http://www.w3.org/2005/08/addressing',
    'tds': 'http://www.onvif.org/ver10/device/wsdl',
    'tt': 'http://www.onvif.org/ver10/schema',
    'tev': 'http://www.onvif.org/ver10/events/wsdl',
    'trt': 'http://www.onvif.org/ver10/media/wsdl',
    'tr2': 'http://www.onvif.org/ver20/media/wsdl',
    'tan': 'http://www.onvif.org/ver20/analytics/wsdl',
    'wsnt': 'http://docs.oasis-open.org/wsn/b-2',
    'wsse': 'http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd',
    'wsu': 'http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd',
}
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)


class OnvifHTTPError(ValueError):
    def __init__(self, status_code, operation):
        self.status_code = status_code
        self.operation = operation
        super().__init__(f'HTTP {status_code} al ejecutar {operation}')


def element(parent, name, text=None, **attributes):
    prefix, local = name.split(':')
    node = ET.SubElement(parent, '{' + NS[prefix] + '}' + local, attributes)
    node.text = text
    return node


def parse_events(raw):
    root = fromstring(raw)
    output = []
    for notification in root.iter('{' + NS['wsnt'] + '}NotificationMessage'):
        message = notification.find('.//tt:Message', NS)
        groups = {}
        if message is not None:
            for group in message:
                items = []
                for item in group:
                    items.append({'tag': item.tag, 'attributes': dict(item.attrib),
                                  'xml': ET.tostring(item, encoding='unicode')})
                groups[group.tag.rsplit('}', 1)[-1]] = items
        output.append({'topic': notification.findtext('wsnt:Topic', default='unknown', namespaces=NS).strip(),
                       'source_time': message.get('UtcTime') if message is not None else None,
                       'metadata': {'attributes': dict(message.attrib) if message is not None else {},
                                    'groups': groups,
                                    'notification_xml': ET.tostring(notification, encoding='unicode')}})
    return output


class OnvifClient:
    def __init__(self, camera):
        self.camera = camera
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.auth = HTTPDigestAuth(camera['username'], camera['password'])
        self.reference_parameters = []
        self.offset = camera.get('clock_offset_seconds', 0)

    def call(self, url, action, body_name, fields=(), reference=False, timeout=(8, 40)):
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('La cámara devolvió una dirección ONVIF inválida')
        envelope = ET.Element('{' + NS['s'] + '}Envelope')
        header = element(envelope, 's:Header')
        element(header, 'a:Action', action)
        element(header, 'a:To', url)
        element(header, 'a:MessageID', 'urn:uuid:' + str(uuid.uuid4()))
        element(element(header, 'a:ReplyTo'), 'a:Address', NS['a'] + '/anonymous')
        if reference:
            for parameter in self.reference_parameters:
                clone = copy.deepcopy(parameter)
                clone.set('{' + NS['a'] + '}IsReferenceParameter', 'true')
                header.append(clone)
        security = element(header, 'wsse:Security')
        security.set('{' + NS['s'] + '}mustUnderstand', 'true')
        token = element(security, 'wsse:UsernameToken')
        created = (datetime.now(timezone.utc) + timedelta(seconds=self.offset)).strftime('%Y-%m-%dT%H:%M:%SZ')
        nonce = os.urandom(20)
        digest = base64.b64encode(hashlib.sha1(nonce + created.encode() + self.camera['password'].encode()).digest()).decode()
        element(token, 'wsse:Username', self.camera['username'])
        element(token, 'wsse:Password', digest, Type='http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest')
        element(token, 'wsse:Nonce', base64.b64encode(nonce).decode(), EncodingType='http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary')
        element(token, 'wsu:Created', created)
        body = element(element(envelope, 's:Body'), body_name)
        for name, value in fields:
            element(body, name, value)
        with self.session.post(url, data=ET.tostring(envelope, encoding='utf-8', xml_declaration=True),
                               headers={'Content-Type': f'application/soap+xml; charset=utf-8; action="{action}"'},
                               timeout=timeout, verify=self.camera['verify_tls'],
                               allow_redirects=False, stream=True) as response:
            chunks, length = [], 0
            for chunk in response.iter_content(65536):
                length += len(chunk)
                if length > 8 * 1024 * 1024:
                    raise ValueError('Respuesta ONVIF superior a 8 MB')
                chunks.append(chunk)
            raw = b''.join(chunks)
            if 300 <= response.status_code < 400:
                raise ValueError('ONVIF redirigió la solicitud; configura la URL final')
            # Preserve the status and operation without exposing credentials or response bodies.
            if response.status_code >= 400:
                # Parse valid SOAP faults below, but retain HTTP errors for non-SOAP bodies.
                try:
                    fault_root = fromstring(raw)
                    has_fault = fault_root.find('.//s:Fault', NS) is not None
                except Exception:
                    has_fault = False
                if not has_fault:
                    raise OnvifHTTPError(response.status_code, body_name.split(':', 1)[-1])
            # Fault content may contain credentials; expose only the reason code.
            try:
                root = fromstring(raw)
            except Exception:
                response.raise_for_status()
                raise ValueError('La cámara no respondió con XML ONVIF') from None
            fault = root.find('.//s:Fault', NS)
            if fault is not None:
                code = fault.findtext('.//s:Subcode/s:Value', namespaces=NS) or 'SOAP Fault'
                raise ValueError('Error ONVIF: ' + code[:120])
            response.raise_for_status()
            return root, raw

    def discover(self):
        root, _ = self.call(self.camera['device_url'], NS['tds'] + '/GetCapabilities',
                            'tds:GetCapabilities', [('tds:Category', 'Events')])
        url = root.findtext('.//tt:Events/tt:XAddr', namespaces=NS)
        if not url:
            raise ValueError('El equipo no anuncia un servicio de eventos ONVIF')
        return url

    def subscribe(self, event_url):
        root, _ = self.call(event_url, NS['tev'] + '/EventPortType/CreatePullPointSubscriptionRequest',
                            'tev:CreatePullPointSubscription', [('tev:InitialTerminationTime', 'PT120S')])
        ref = root.find('.//wsnt:SubscriptionReference', NS)
        # ONVIF defines SubscriptionReference in the tev namespace.
        if ref is None:
            ref = root.find('.//tev:SubscriptionReference', NS)
        if ref is None:
            raise ValueError('No se recibió una suscripción ONVIF')
        url = ref.findtext('a:Address', namespaces=NS)
        if not url:
            raise ValueError('Suscripción sin dirección de consulta')
        params = ref.find('a:ReferenceParameters', NS)
        self.reference_parameters = list(params) if params is not None else []
        return url, self.deadline(root)

    @staticmethod
    def deadline(root):
        current = next((n.text for n in root.iter() if n.tag.endswith('}CurrentTime')), None)
        termination = next((n.text for n in root.iter() if n.tag.endswith('}TerminationTime')), None)
        if not current or not termination:
            raise ValueError('Suscripción ONVIF sin tiempo de expiración')
        lifetime = (datetime.fromisoformat(termination.replace('Z', '+00:00')) -
                    datetime.fromisoformat(current.replace('Z', '+00:00'))).total_seconds()
        if lifetime <= 0:
            raise ValueError('La cámara devolvió una suscripción vencida')
        return time.monotonic() + lifetime

    def renew(self, url):
        root, _ = self.call(url, 'http://docs.oasis-open.org/wsn/bw-2/SubscriptionManager/RenewRequest',
                            'wsnt:Renew', [('wsnt:TerminationTime', 'PT120S')], reference=True)
        return self.deadline(root)

    def pull(self, url, seconds=20):
        _, raw = self.call(url, NS['tev'] + '/PullPointSubscription/PullMessagesRequest',
                           'tev:PullMessages', [('tev:Timeout', f'PT{seconds}S'), ('tev:MessageLimit', '100')], reference=True)
        return raw, parse_events(raw)

    def unsubscribe(self, url):
        self.call(url, 'http://docs.oasis-open.org/wsn/bw-2/SubscriptionManager/UnsubscribeRequest',
                  'wsnt:Unsubscribe', reference=True)
