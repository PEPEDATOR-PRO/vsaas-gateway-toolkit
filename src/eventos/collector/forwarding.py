"""Persisted outbound JSON queue. Only an administrator-configured destination is used."""
import json
import re
import threading
import uuid
import requests


def validate(config):
    scheme=config.get('scheme','https');host=config.get('host','');path=config.get('path','/')
    if not isinstance(host,str):raise ValueError('Host inválido.')
    host=host.strip()
    port=config.get('port',443)
    if scheme not in ('http','https') or type(port) is not int or not 1<=port<=65535:raise ValueError('Protocolo o puerto inválido.')
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?',host):raise ValueError('Introduce solo una IPv4 o un host, sin protocolo, puerto ni credenciales.')
    if not isinstance(path,str) or not path.startswith('/') or path.startswith('//') or (any(ord(c)<32 for c in path) or '#' in path) or len(path)>2048:raise ValueError('Path inválido; debe comenzar con /.')
    token=config.get('token','')
    if not isinstance(token,str) or len(token)>4096 or any(c in token for c in '\r\n'):raise ValueError('Token inválido.')
    return {'enabled':config.get('enabled') is True,'scheme':scheme,'host':host,'port':port,'path':path,'token':token}


class Forwarder:
    def __init__(self,store):
        self.store=store;self.stop=threading.Event();self.thread=None;self.lock=threading.Lock()
        with store.connect() as db:
            db.execute("INSERT OR IGNORE INTO delivery_settings VALUES('instance',?)",(uuid.uuid4().hex,))

    def value(self,key,default=''):
        with self.store.connect() as db:
            row=db.execute('SELECT value FROM delivery_settings WHERE key=?',(key,)).fetchone()
        return row[0] if row else default

    def config(self,secret=False):
        result=json.loads(self.value('destination','{"enabled":false}'))
        encrypted=result.pop('token_cipher','')
        result['has_token']=bool(encrypted)
        if secret:result['token']=self.store.cipher.decrypt(encrypted.encode()).decode() if encrypted else ''
        return result

    def configure(self,data):
        result=validate(data)
        with self.lock:
            old=self.config(secret=True)
            token=result.pop('token')
            same_origin=all(old.get(key)==result.get(key) for key in ('scheme','host','port'))
            if not token and not data.get('clear_token') and same_origin:token=old.get('token','')
            result['token_cipher']=self.store.cipher.encrypt(token.encode()).decode() if token else ''
            with self.store.connect() as db:
                db.execute("INSERT INTO delivery_settings VALUES('destination',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(result),))
        return self.status()

    def status(self):
        result=self.config()
        result.update(pending=self.store.count(),sent=int(self.value('sent','0')),dropped=int(self.value('dropped','0')),last_result=self.value('last_result','Sin envíos'),last_success=self.value('last_success',''))
        return result

    def post(self,config,payload):
        headers={'Content-Type':'application/json','Idempotency-Key':payload['event_id']}
        if config.get('token'):headers['Authorization']='Bearer '+config['token']
        with requests.Session() as session:
            session.trust_env=False
            response=session.post(f"{config['scheme']}://{config['host']}:{config['port']}{config['path']}",json=payload,headers=headers,timeout=(3,7),allow_redirects=False,stream=True)
            try:return response.status_code
            finally:response.close()

    def test(self):
        config=self.config(secret=True)
        if not config.get('host'):raise ValueError('Guarda primero el destino.')
        try:code=self.post(config,{'event_id':'test-'+uuid.uuid4().hex,'type':'connection_test','test':True})
        except requests.RequestException:return {'ok':False,'detail':'No se pudo conectar. Revisa ruta, DNS, TLS y puerto.'}
        return {'ok':200<=code<300,'detail':'Respuesta HTTP '+str(code)+'. La prueba no retira eventos de la cola.'}

    def once(self):
        with self.lock:
            config=self.config(secret=True)
            if not config.get('enabled'):return None
            with self.store.write_lock:
                rows=self.store.events(limit=1,include_raw=False)
                if not rows:return None
                event=rows[0];self.store.inflight_event=event['id']
            try:return self.deliver(config,event)
            finally:
                with self.store.write_lock:self.store.inflight_event=None

    def deliver(self,config,event):
        identifier=self.value('instance')+':'+str(event['id'])
        payload={'event_id':identifier,'type':'camera_event','event':event}
        try:code=self.post(config,payload);ok=200<=code<300;detail='HTTP '+str(code)
        except (requests.RequestException,ValueError):ok=False;detail='Fallo de conexión, DNS, TLS o formato JSON; pendiente de reintento.'
        with self.store.write_lock,self.store.connect() as db:
            db.execute("INSERT INTO delivery_settings VALUES('last_result',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(detail,))
            if ok:
                db.execute('DELETE FROM events WHERE id=?',(event['id'],))
                db.execute("INSERT INTO delivery_settings VALUES('sent','1') ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1")
                from .storage import now
                db.execute("INSERT INTO delivery_settings VALUES('last_success',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(now(),))
        return ok

    def start(self):
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()

    def run(self):
        delay=1
        while not self.stop.is_set():
            try:result=self.once()
            except Exception:result=False
            if result is True:delay=0.02
            elif result is False:delay=min(60,max(1,delay*2))
            else:delay=1
            self.stop.wait(delay)

    def close(self):
        self.stop.set()
        if self.thread:self.thread.join(timeout=12)
