import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import install_events as events
import install


class EventsInstallTests(unittest.TestCase):
    def test_explicit_ip_must_already_be_assigned_to_loopback(self):
        addresses=json.dumps([{'addr_info':[{'family':'inet','local':'127.0.0.1'},{'family':'inet','local':'192.0.2.10'}]}])
        with patch.object(events.subprocess,'check_output',return_value=addresses):
            self.assertEqual(events.admin_address(vpn_ip='192.0.2.10'),'192.0.2.10')
            self.assertEqual(events.admin_address(),'192.0.2.10')
            with self.assertRaises(ValueError):events.admin_address(vpn_ip='198.51.100.10')

    def test_dry_run_does_not_require_a_profile_or_call_docker(self):
        with patch.object(install.sys,'argv',['install.py','eventos','--dry-run']),patch.object(install.subprocess,'run') as run,contextlib.redirect_stdout(io.StringIO()):
            install.main()
            run.assert_not_called()

    def test_build_failure_does_not_stop_services_and_can_be_retried(self):
        with tempfile.TemporaryDirectory() as folder,contextlib.ExitStack() as stack:
            base=Path(folder)
            for name,path in [('TARGET',base/'deploy'),('LIBEXEC',base/'libexec'),('BIN',base/'bin'),('UNITS',base/'units'),('PORTAL',base/'portal')]:stack.enter_context(patch.object(events,name,path))
            stack.enter_context(patch.object(events,'admin_address',return_value='192.0.2.10'))
            stack.enter_context(patch.object(events.shutil,'which',return_value='/usr/bin/docker'))
            stack.enter_context(patch.object(events.shutil,'disk_usage',return_value=SimpleNamespace(free=4*1024**3)))
            stack.enter_context(patch.object(events.subprocess,'check_output',return_value=''))
            sock=stack.enter_context(patch.object(events.socket,'socket'));sock.return_value.__enter__.return_value.connect_ex.return_value=1
            calls=[]
            def command(args,**kwargs):
                calls.append(args)
                if args[:2]==['docker','build']:raise subprocess.CalledProcessError(1,args)
            fake=stack.enter_context(patch.object(events,'command',side_effect=command))
            with self.assertRaises(subprocess.CalledProcessError):events.install(vpn_ip='192.0.2.10')
            self.assertTrue((events.TARGET/'.toolkit-eventos').is_file())
            self.assertFalse(any(args[0]=='systemctl' for args in calls))
            fake.side_effect=lambda args,**kwargs:calls.append(args)
            with contextlib.redirect_stdout(io.StringIO()):events.install(vpn_ip='192.0.2.10')
            self.assertTrue((events.PORTAL/'manifest.json').is_file())
            self.assertTrue((events.TARGET/'app/collector/app.py').is_file())
            self.assertFalse((events.TARGET/'app/data').exists())
            self.assertEqual((events.TARGET/'.env').read_text().splitlines()[0],'VPN_IP_ADMIN=192.0.2.10')
            self.assertFalse(any('down' in args or 'rm' in args for args in calls))
            self.assertFalse(any('camera_agent_gateway' in str(args) for args in calls))


class EventsStatusTests(unittest.TestCase):
    def test_status_never_exposes_inspect_environment_or_health_logs(self):
        spec=importlib.util.spec_from_file_location('events_manage',events.SOURCE/'manage.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'settings.json').write_text(json.dumps({'vpn_admin_ip':'192.0.2.10'}))
            data=[{'Config':{'Env':['SECRET=dummy-secret']},'State':{'Status':'running','Health':{'Status':'healthy','Log':[{'Output':'dummy-secret'}]}},'RestartCount':0}]
            with patch.object(module,'TARGET',root),patch.object(module,'run',side_effect=['fake-id',json.dumps(data)]),patch.object(module.urllib.request,'build_opener') as opener:
                response=opener.return_value.open.return_value.__enter__.return_value;response.status=200;response.read.return_value=b'{"status":"ok"}'
                result=module.status()
            self.assertTrue(result['responds'])
            self.assertEqual(result['url'],'http://192.0.2.10:8081')
            self.assertNotIn('dummy-secret',json.dumps(result))


if __name__=='__main__':unittest.main()
