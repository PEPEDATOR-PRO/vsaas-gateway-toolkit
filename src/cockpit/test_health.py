import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch, MagicMock

spec=importlib.util.spec_from_file_location('health',Path(__file__).with_name('vxg-health.py'))
health=importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)


def raw(service, status='running', native=None):
    obj={'Id':service+'123456789012345', 'Name':'/camera_agent_gateway-'+service+'-1',
         'Config':{'Image':'vxg/'+service+':1.0.16','Labels':{'com.docker.compose.service':service},'Env':['TOKEN=never-return-this']},
         'State':{'Status':status,'Running':status=='running','StartedAt':'2026-10-30T00:00:00Z','OOMKilled':False},
         'HostConfig':{'RestartPolicy':{'Name':'unless-stopped'}},'RestartCount':0,
         'Mounts':[{'Destination':'/vol/data','Type':'volume'}],
         'NetworkSettings':{'Ports':{'80/tcp':[{'HostIp':'0.0.0.0','HostPort':'80'}]}}}
    if native:obj['State']['Health']={'Status':native,'FailingStreak':3,'Log':[{'Output':'SECRET'}]}
    return obj


class HealthTests(unittest.TestCase):
    def test_credentials_and_health_output_are_not_returned(self):
        obj=health.summarize(raw('app',native='unhealthy'))
        text=json.dumps(obj)
        self.assertNotIn('never-return-this',text)
        self.assertNotIn('SECRET',text)
        self.assertNotIn('Env',obj)

    def test_unhealthy_is_critical_even_if_running(self):
        checks=health.container_checks([health.summarize(raw('app',native='unhealthy')),health.summarize(raw('nginx'))])
        self.assertEqual(checks[0]['status'],'critical')

    def test_missing_nginx_is_critical(self):
        checks=health.container_checks([health.summarize(raw('app'))])
        self.assertTrue(any(c['key']=='nginx' and c['status']=='critical' for c in checks))

    def test_unknown_checks_do_not_become_healthy(self):
        self.assertEqual(health.finish({'checks':[{'status':'unknown'}]})['local_status'],'unknown')

    def test_local_probe_uses_published_port_not_container_port(self):
        self.assertEqual(health.local_url(raw('nginx')),'http://127.0.0.1:80')

    def test_css_probe_rejects_html_and_empty_css(self):
        for body,mime in [(b'<html>error</html>','text/html'),(b'','text/css')]:
            response=MagicMock();response.__enter__.return_value=response
            response.status=200;response.read.return_value=body;response.headers={'Content-Type':mime}
            opener=MagicMock();opener.open.return_value=response
            with patch.object(health.urllib.request,'build_opener',return_value=opener):
                self.assertFalse(health.http_probe('http://127.0.0.1/static/css/styles.css',True)['valid'])

    def test_snapshot_has_no_cloud_online_claim_and_detects_persistence(self):
        containers=[raw('app'),raw('nginx')]
        inside={'proxy_processes':1,'python_processes':2,'proxy_tcp443':1,
                'database':{'path':'/vol/data/db.sqlite3','camera_total':0,'camera_enabled':0},
                'logs':{'files_sampled':1,'events':{'established':1}},'notes':[]}
        def mock_run(args,*unused):
            if args[1]=='ps':return 'app123\nnginx123\n'
            if args[1]=='inspect':return json.dumps(containers)
            if args[1]=='exec':return json.dumps(inside)
            if args[1]=='stats':return '\n'.join(json.dumps({'Name':c['Name'].lstrip('/'),'CPUPerc':'0.2%','MemUsage':'32MiB / 7GiB'}) for c in containers)
            raise AssertionError(args)
        host={'ram_used_percent':11,'disk_used_percent':20,'ram_total':8000000000,'ram_available':7000000000,'disk_total':100000000000,'disk_free':80000000000,'uptime_seconds':5000}
        with patch.object(health.shutil,'which',return_value='/usr/bin/docker'),patch.object(health,'run',side_effect=mock_run),patch.object(health,'host_resources',return_value=host),patch.object(health,'http_probe',return_value={'valid':True,'code':200,'latency_ms':5,'bytes':2834}):
            report=health.collect()
        self.assertEqual(report['cloud'],'not-confirmed')
        self.assertEqual(report['local_status'],'ok')
        self.assertTrue(report['internal']['database']['persistent_mount'])
        self.assertNotIn('never-return-this',json.dumps(report))

    def test_container_inspection_program_compiles(self):
        compile(health.INSIDE,'container-inspection','exec')

    def test_persistence_handles_file_bind_mount_and_excludes_tmpfs(self):
        self.assertTrue(health.persistent_path('/code/db.sqlite3',[{'Type':'bind','Destination':'/code/db.sqlite3'}]))
        self.assertFalse(health.persistent_path('/vol/data/db.sqlite3',[{'Type':'tmpfs','Destination':'/vol/data'}]))
        self.assertFalse(health.persistent_path('/vol/data-old/db.sqlite3',[{'Type':'volume','Destination':'/vol/data'}]))


if __name__=='__main__':unittest.main()
