import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import install_vxg as vxg


class VxgInstallTests(unittest.TestCase):
    def test_environment_file_is_read_as_data(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'example.env';p.write_text('VALUE=$(not-a-command)\n')
            self.assertEqual(vxg.read_env(p)['VALUE'],'$(not-a-command)')

    def test_runtime_environment_excludes_registry_credentials(self):
        settings={key:'example-value' for key in vxg.PUBLIC}
        settings.update(GITLAB_REGISTRY_USER='example-user',GITLAB_REGISTRY_TOKEN='dummy-registry-token')
        result=vxg.app_environment(settings,'192.0.2.10','dummy-admin-password','1.0.16-arm64')
        self.assertNotIn('GITLAB_REGISTRY_TOKEN',result);self.assertNotIn('GITLAB_REGISTRY_USER',result)
        self.assertNotIn('dummy-registry-token',json.dumps(result))
        self.assertEqual(result['SECRET_KEY'],result['DJANGO_SECRET_KEY'])

    def test_dollar_and_hash_are_literal_in_env_file(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'example.env';p.write_text(vxg.env_text({'PASSWORD':'Example$Password#2026'}))
            self.assertEqual(vxg.read_env(p)['PASSWORD'],'Example$Password#2026')
            self.assertIn("='",p.read_text())

    def test_unsupported_env_characters_are_rejected(self):
        for value in ["quote'",'slash\\','line\nbreak']:
            with self.assertRaises(ValueError):vxg.env_text({'PASSWORD':value})

    def test_architecture_selects_pinned_image(self):
        self.assertEqual(vxg.image_version('aarch64'),'1.0.16-arm64')
        self.assertEqual(vxg.image_version('x86_64'),'1.0.16-x64')
        with self.assertRaises(ValueError):vxg.image_version('armv7l')

    def test_existing_stack_is_not_replaced(self):
        with patch.object(vxg.shutil,'which',return_value='/usr/bin/docker'),patch.object(vxg,'command') as command,patch.object(vxg.subprocess,'check_output',return_value='existing-id'),patch.object(vxg.getpass,'getpass') as prompt:
            with self.assertRaises(ValueError):vxg.install()
            prompt.assert_not_called();self.assertEqual(command.call_count,1)

    def test_registry_token_is_stdin_only_and_temporary_auth_is_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);target=root/'deployment';credentials=root/'private.env'
            credentials.write_text('GITLAB_REGISTRY_USER=example-user\nGITLAB_REGISTRY_TOKEN=dummy-registry-token\n')
            calls=[]
            def run(args,**kwargs):
                calls.append((args,kwargs))
                if args[1]=='login':self.assertFalse(target.exists())
                return subprocess.CompletedProcess(args,0,stdout='',stderr='')
            def output(args,**kwargs):
                if args[0]=='ip':return json.dumps([{'prefsrc':'192.0.2.10'}])
                return ''
            captured=io.StringIO()
            with patch.object(vxg,'TARGET',target),patch.object(vxg.shutil,'which',return_value='/usr/bin/docker'),patch.object(vxg.os,'uname',create=True,return_value=SimpleNamespace(machine='aarch64')),patch.object(vxg.subprocess,'run',side_effect=run),patch.object(vxg.subprocess,'check_output',side_effect=output),patch.object(vxg.getpass,'getpass',side_effect=['dummy-admin-password','dummy-admin-password']),contextlib.redirect_stdout(captured):
                vxg.install(credentials)
            login=next(item for item in calls if item[0][1]=='login')
            self.assertEqual(login[1]['input'],'dummy-registry-token\n')
            self.assertNotIn('dummy-registry-token',str(login[0]))
            self.assertFalse(Path(login[1]['env']['DOCKER_CONFIG']).exists())
            self.assertNotIn('dummy-registry-token',(target/'.env').read_text())
            self.assertNotIn('GITLAB_REGISTRY_TOKEN',(target/'.env').read_text())
            self.assertNotIn('dummy-admin-password',captured.getvalue())
            self.assertNotIn('dummy-registry-token',captured.getvalue())


if __name__=='__main__':unittest.main()
