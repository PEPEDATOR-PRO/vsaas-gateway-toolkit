#!/usr/bin/env python3
"""Bounded 24-hour telemetry using only stdlib and existing local probes."""
import argparse
import concurrent.futures
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tarfile
import time

STATE=Path('/var/lib/vsaas-observacion/actual.json')
LOGROOT=Path('/var/log/vsaas-observacion')
HEALTH=Path('/usr/local/libexec/vsaas-observacion-health.py')
LIMIT=128*1024*1024
RESERVE=1024*1024
STOP=False


def utc():return dt.datetime.now(dt.timezone.utc).isoformat()


def atomic_json(path,data):
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temporary.replace(path)


def read_state():
    config=json.loads(STATE.read_text())
    directory=Path(config['directory']).resolve()
    if directory.parent!=LOGROOT.resolve():raise ValueError('Ruta de registros fuera del directorio de observación.')
    return config,directory


def prepare(interface,hours):
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,32}',interface) or not (Path('/sys/class/net')/interface/'statistics').is_dir():
        raise ValueError('Interfaz de red no válida o no disponible.')
    if not HEALTH.is_file():raise ValueError('Primero instala Salud Vsaas; falta el lector local de salud.')
    if STATE.exists():
        old,directory=read_state()
        summary=directory/'resumen.json'
        if old['end_epoch']>time.time() and summary.exists() and json.loads(summary.read_text()).get('status')=='running':
            raise ValueError('Ya hay una prueba en curso. No se sustituyeron sus registros.')
    if shutil.disk_usage('/var/log').free<512*1024*1024:
        raise ValueError('Hay menos de 512 MiB libres en /var/log. Libera espacio antes de iniciar.')
    LOGROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    STATE.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    name=dt.datetime.now(dt.timezone.utc).strftime('sesion-%Y%m%dT%H%M%S-%fZ')
    directory=LOGROOT/name;directory.mkdir(mode=0o700)
    start=time.time()
    config={'directory':str(directory),'interface':interface,'start_epoch':start,'end_epoch':start+hours*3600,
            'network_interval_s':5,'health_interval_s':60,'limit_bytes':LIMIT,'hours':hours}
    atomic_json(STATE,config)
    atomic_json(directory/'sesion.json',config)
    initial=summary_base(config);atomic_json(directory/'resumen.json',initial)
    print('Sesión preparada en '+str(directory))
    print('Fin programado: '+dt.datetime.fromtimestamp(config['end_epoch']).astimezone().isoformat())


def summary_base(config):
    return {'status':'prepared','started_at':dt.datetime.fromtimestamp(config['start_epoch'],dt.timezone.utc).isoformat(),
            'scheduled_end':dt.datetime.fromtimestamp(config['end_epoch'],dt.timezone.utc).isoformat(),
            'interface':config['interface'],'network_samples':0,'measured_seconds':0,'rx_bytes':0,'tx_bytes':0,
            'rx_peak_mbps':0,'tx_peak_mbps':0,'host_cpu_sum':0,'host_cpu_samples':0,'host_cpu_peak_pct':0,
            'monitor_cpu_seconds':0,'monitor_memory_peak_bytes':0,'monitor_anonymous_peak_bytes':0,
            'ram_peak_used_pct':0,'health_samples':0,'health_states':{},'health_errors':0,'probe_duration_sum_s':0,'probe_duration_peak_s':0,
            'container_cpu':{},'camera_enabled_last':None,'notes':[
                'No se guarda video ni paquetes de red. Se leen contadores del puerto.',
                'El consumo del monitor incluye su grupo de procesos y caché de archivos; las consultas ejecutadas dentro de Docker se contabilizan en los contenedores, no en ese grupo.',
                'La CPU de Docker puede superar 100% cuando usa varios núcleos. La CPU de Ubuntu y del monitor aquí se expresa respecto a toda la capacidad del equipo.',
                'Los cambios de carga no prueban causalidad. Una comparación de impacto requiere otra prueba comparable sin el recopilador.',
                'Los eventos de salud son observaciones periódicas, no una medición continua de disponibilidad de video.'
            ]}


def aggregate(summary,record):
    if record['kind']=='network':
        summary['network_samples']+=1
        summary['rx_bytes']+=record.get('rx_delta_bytes',0);summary['tx_bytes']+=record.get('tx_delta_bytes',0)
        summary['measured_seconds']+=record.get('elapsed_s',0)
        for direction in ['rx','tx']:
            summary[direction+'_peak_mbps']=max(summary[direction+'_peak_mbps'],record.get(direction+'_mbps') or 0)
        cpu=record.get('host_cpu_pct')
        if cpu is not None:
            summary['host_cpu_sum']+=cpu;summary['host_cpu_samples']+=1
            summary['host_cpu_peak_pct']=max(summary['host_cpu_peak_pct'],cpu)
        summary['monitor_cpu_seconds']+=record.get('monitor_cpu_delta_s',0)
        summary['monitor_memory_peak_bytes']=max(summary['monitor_memory_peak_bytes'],record.get('monitor_memory_peak_bytes') or 0)
        summary['monitor_anonymous_peak_bytes']=max(summary['monitor_anonymous_peak_bytes'],record.get('monitor_memory_anonymous_bytes') or 0)
        summary['ram_peak_used_pct']=max(summary['ram_peak_used_pct'],record.get('ram_used_pct') or 0)
        if record.get('temperature_c') is not None:
            summary['temperature_peak_c']=max(summary.get('temperature_peak_c',0),record['temperature_c'])
        for key in ['rx_dropped','tx_dropped','rx_errors','tx_errors']:
            delta=record.get(key+'_delta')
            if delta is not None:summary[key+'_total']=summary.get(key+'_total',0)+delta
    elif record['kind']=='health':
        summary['health_samples']+=1;data=record['data'];status=data.get('local_status','unknown')
        summary['probe_duration_sum_s']+=record.get('probe_duration_s',0)
        summary['probe_duration_peak_s']=max(summary['probe_duration_peak_s'],record.get('probe_duration_s',0))
        summary['health_states'][status]=summary['health_states'].get(status,0)+1
        for container in data.get('containers',[]):
            values=summary['container_cpu'].setdefault(container['name'],{'sum_pct':0,'samples':0,'peak_pct':0,'restarts_first':container['restarts'],'restarts_last':container['restarts'],'instance_id':container.get('id'),'instance_changes':0})
            if values['instance_id']!=container.get('id'):
                values['instance_changes']+=1;values['instance_id']=container.get('id')
            values['restarts_last']=container['restarts']
            try:cpu=float((container.get('stats') or {})['CPUPerc'].rstrip('%'))
            except (KeyError,TypeError,ValueError):continue
            values['sum_pct']+=cpu;values['samples']+=1;values['peak_pct']=max(values['peak_pct'],cpu)
        camera=((data.get('internal') or {}).get('database') or {}).get('camera_enabled')
        summary['camera_enabled_last']=camera
    elif record['kind']=='health-error':summary['health_errors']+=1


class Writer:
    def __init__(self,directory,limit):
        self.directory=directory;self.limit=limit
        self.bytes=sum(p.stat().st_size for p in directory.iterdir() if p.is_file() and p.name.endswith('.jsonl'))
    def write(self,name,record):
        content=(json.dumps(record,ensure_ascii=False,separators=(',',':'))+'\n').encode('utf-8')
        if self.bytes+len(content)>self.limit-RESERVE:raise OverflowError('Límite de registros alcanzado.')
        if shutil.disk_usage(self.directory).free<512*1024*1024:raise OverflowError('Quedan menos de 512 MiB libres.')
        with (self.directory/name).open('ab') as stream:stream.write(content)
        self.bytes+=len(content)


def host_cpu():
    fields=[int(value) for value in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
    return sum(fields),fields[3]+fields[4]


def memory_used():
    values={line.split(':')[0]:int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines() if len(line.split())>=2}
    return round((1-values['MemAvailable']/values['MemTotal'])*100,2)


def cgroup_path():
    for line in Path('/proc/self/cgroup').read_text().splitlines():
        if line.startswith('0::'):
            return Path('/sys/fs/cgroup')/line[3:].lstrip('/')
    return None


def monitor_usage(group):
    if not group:return {}
    result={}
    try:
        cpu=dict(line.split() for line in (group/'cpu.stat').read_text().splitlines())
        result['cpu_seconds']=int(cpu['usage_usec'])/1e6
        result['memory_bytes']=int((group/'memory.current').read_text())
        result['memory_peak_bytes']=int((group/'memory.peak').read_text())
        memory=dict(line.split() for line in (group/'memory.stat').read_text().splitlines())
        result['anonymous_bytes']=int(memory.get('anon',0))
    except (OSError,ValueError,KeyError):pass
    return result


def network_bytes(interface):
    base=Path('/sys/class/net')/interface/'statistics'
    return int((base/'rx_bytes').read_text()),int((base/'tx_bytes').read_text())


def extra_network(interface):
    result={}
    for key in ['rx_dropped','tx_dropped','rx_errors','tx_errors']:
        try:result[key]=int((Path('/sys/class/net')/interface/'statistics'/key).read_text())
        except (OSError,ValueError):pass
    return result


def temperature():
    try:return round(int(Path('/sys/class/thermal/thermal_zone0/temp').read_text())/1000,1)
    except (OSError,ValueError):return None


def rate_record(previous,current):
    elapsed=current['mono']-previous['mono'] if previous else 0
    record={'kind':'network','time':utc(),'elapsed_s':round(elapsed,4),'rx_delta_bytes':0,'tx_delta_bytes':0,
            'rx_mbps':None,'tx_mbps':None,'host_cpu_pct':None}
    if previous and elapsed>0:
        for key in ['rx','tx']:
            delta=max(0,current[key]-previous[key]);record[key+'_delta_bytes']=delta
            record[key+'_mbps']=round(delta*8/elapsed/1e6,5)
        total=current['cpu'][0]-previous['cpu'][0];idle=current['cpu'][1]-previous['cpu'][1]
        if total>0:record['host_cpu_pct']=round(min(100,max(0,(1-idle/total)*100)),3)
    old_cpu=previous.get('monitor',{}).get('cpu_seconds',0) if previous else current['monitor'].get('cpu_seconds',0)
    usage=current['monitor'];record['monitor_cpu_delta_s']=max(0,usage.get('cpu_seconds',0)-old_cpu)
    record['monitor_memory_bytes']=usage.get('memory_bytes');record['monitor_memory_peak_bytes']=usage.get('memory_peak_bytes')
    record['monitor_memory_anonymous_bytes']=usage.get('anonymous_bytes');record['ram_used_pct']=current['ram']
    record['temperature_c']=current.get('temperature')
    for key,value in current.get('extra',{}).items():
        old=(previous or {}).get('extra',{}).get(key)
        record[key+'_delta']=max(0,value-old) if old is not None else None
    return record


def health_snapshot():
    started=time.monotonic()
    result=subprocess.run(['/usr/bin/python3',str(HEALTH)],text=True,capture_output=True,timeout=25,check=True)
    data=json.loads(result.stdout)
    # The installed health helper already emits a whitelist without raw logs or credentials.
    return {'kind':'health','time':utc(),'probe_duration_s':round(time.monotonic()-started,3),'data':data}


def write_summary(directory,summary,config):
    summary['updated_at']=utc()
    measured=summary['measured_seconds'];cores=os.cpu_count() or 1
    summary['host_cpu_average_pct']=round(summary['host_cpu_sum']/summary['host_cpu_samples'],3) if summary['host_cpu_samples'] else None
    summary['monitor_cpu_average_pct_host']=round(summary['monitor_cpu_seconds']/measured/cores*100,4) if measured else None
    summary['rx_average_mbps']=round(summary['rx_bytes']*8/measured/1e6,4) if measured else None
    summary['tx_average_mbps']=round(summary['tx_bytes']*8/measured/1e6,4) if measured else None
    summary['log_bytes']=sum(p.stat().st_size for p in directory.iterdir() if p.is_file() and p.name.endswith('.jsonl'))
    summary['estimated_log_bytes_24h']=round(summary['log_bytes']/measured*86400) if measured>=60 else None
    summary['health_probe_average_s']=round(summary['probe_duration_sum_s']/summary['health_samples'],3) if summary['health_samples'] else None
    summary['record_limit_bytes']=config['limit_bytes']
    for values in summary['container_cpu'].values():
        values['average_pct']=round(values['sum_pct']/values['samples'],3) if values['samples'] else None
    atomic_json(directory/'resumen.json',summary)


def restore_summary(config,directory):
    summary=summary_base(config)
    for filename in ['trafico-recursos.jsonl','salud.jsonl']:
        if (directory/filename).exists():
            with (directory/filename).open(encoding='utf-8') as stream:
                for line in stream:
                    try:aggregate(summary,json.loads(line))
                    except (ValueError,KeyError,TypeError):pass
    return summary


def collect():
    global STOP
    config,directory=read_state()
    if time.time()>=config['end_epoch']:
        saved=json.loads((directory/'resumen.json').read_text())
        if saved.get('status') in ('running','prepared'):
            summary=restore_summary(config,directory);summary['status']='completed-after-offline';summary['finished_at']=utc()
            summary['notes'].append('La ventana terminó mientras el recopilador estaba inactivo. El tiempo medido puede ser menor que 24 horas.')
            write_summary(directory,summary,config)
        print('La ventana de 24 horas ya terminó. No se inicia otra prueba automáticamente.');return
    writer=Writer(directory,config['limit_bytes']);summary=restore_summary(config,directory);summary['status']='running'
    write_summary(directory,summary,config)
    def stop(signum,frame):
        global STOP
        STOP=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    group=cgroup_path();previous=None;future=None;next_health=time.monotonic();next_summary=time.monotonic()+60
    deadline=time.monotonic()+min(config['hours']*3600,config['end_epoch']-time.time())
    reason='completed';pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        while not STOP and time.time()<config['end_epoch'] and time.monotonic()<deadline:
            tick=time.monotonic()
            try:
                rx,tx=network_bytes(config['interface']);current={'mono':tick,'rx':rx,'tx':tx,'cpu':host_cpu(),'ram':memory_used(),'monitor':monitor_usage(group),'extra':extra_network(config['interface']),'temperature':temperature()}
                record=rate_record(previous,current);previous=current
                writer.write('trafico-recursos.jsonl',record);aggregate(summary,record)
            except OSError:
                previous=None;writer.write('eventos.jsonl',{'kind':'network-error','time':utc(),'message':'No se pudo leer la interfaz; se volverá a intentar.'})
            if future and future.done():
                try:record=future.result()
                except Exception:record={'kind':'health-error','time':utc(),'message':'Falló la consulta de salud o superó 25 segundos; no se guardó su salida.'}
                writer.write('salud.jsonl',record);aggregate(summary,record);future=None
            if not future and tick>=next_health:
                future=pool.submit(health_snapshot);next_health=tick+config['health_interval_s']
            if tick>=next_summary:
                write_summary(directory,summary,config);next_summary=tick+60
            delay=max(0,min(config['network_interval_s']-(time.monotonic()-tick),deadline-time.monotonic()))
            if delay:time.sleep(delay)
        if STOP:reason='stopped-manually'
    except OverflowError as exc:
        reason='storage-limit';summary['stop_detail']=str(exc)
    finally:
        if future:
            try:
                record=future.result(timeout=27)
                if reason!='storage-limit':writer.write('salud.jsonl',record);aggregate(summary,record)
            except Exception:pass
        pool.shutdown(wait=True)
        summary['status']=reason;summary['finished_at']=utc();write_summary(directory,summary,config)
        print('Observación finalizada: '+reason+' · '+str(summary['log_bytes'])+' bytes de registros JSONL.')


def status():
    config,directory=read_state();summary=json.loads((directory/'resumen.json').read_text())
    remaining=max(0,int(config['end_epoch']-time.time()))
    print('Estado del informe: '+summary['status'])
    print('Inicio UTC: '+summary['started_at']);print('Fin programado UTC: '+summary['scheduled_end'])
    print('Tiempo restante de la ventana: '+str(dt.timedelta(seconds=remaining)))
    print('Interfaz: '+config['interface']);print('Muestras tráfico: '+str(summary['network_samples'])+' · Salud: '+str(summary['health_samples']))
    print('CPU media monitor sobre capacidad total: '+str(summary.get('monitor_cpu_average_pct_host'))+'%')
    print('Pico RAM grupo monitor (incluye caché): '+str(round(summary['monitor_memory_peak_bytes']/1024**2,2))+' MiB')
    print('Pico memoria anónima observado: '+str(round(summary['monitor_anonymous_peak_bytes']/1024**2,2))+' MiB')
    sizes=sum(p.stat().st_size for p in directory.iterdir() if p.is_file())
    print('Archivos de la prueba: '+str(sizes)+' bytes · '+str(round(sizes/1024**2,2))+' MiB')
    if summary.get('estimated_log_bytes_24h') is not None:
        print('Proyeccion de JSONL a 24 h segun ritmo observado: '+str(round(summary['estimated_log_bytes_24h']/1024**2,2))+' MiB')
    print('Duracion media de consulta de salud: '+str(summary.get('health_probe_average_s'))+' s (no es CPU)')
    if summary.get('temperature_peak_c') is not None:print('Temperatura maxima observada: '+str(summary['temperature_peak_c'])+' C')
    print('Directorio: '+str(directory));print('Último informe: '+summary.get('updated_at','—'))
    print('Confirma también el servicio con: systemctl status vsaas-observacion --no-pager')


def export():
    import pwd
    _,directory=read_state()
    account=pwd.getpwnam(os.environ.get('SUDO_USER','root'))
    target=Path(account.pw_dir)/(directory.name+'-vsaas.tar.gz')
    if target.exists():raise ValueError('El archivo de exportación ya existe: '+str(target))
    with tarfile.open(target,'w:gz') as archive:archive.add(directory,arcname=directory.name)
    os.chown(target,account.pw_uid,account.pw_gid);target.chmod(0o600)
    print('Informe exportado: '+str(target));print('Tamaño comprimido: '+str(target.stat().st_size)+' bytes')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['preparar','ejecutar','estado','exportar']);parser.add_argument('--interfaz',default='eth0');parser.add_argument('--horas',type=float,default=24)
    args=parser.parse_args()
    if os.geteuid()!=0:raise SystemExit('Ejecuta con sudo.')
    if args.action=='preparar':
        if not 0<args.horas<=24:raise ValueError('La duración debe ser mayor que cero y no exceder 24 horas.')
        prepare(args.interfaz,args.horas)
    elif args.action=='ejecutar':collect()
    elif args.action=='estado':status()
    else:export()


if __name__=='__main__':main()
