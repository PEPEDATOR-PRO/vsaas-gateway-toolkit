const fs=require('node:fs');
const path=require('node:path');
const {spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'..');
const directory=path.join(root,'src','cockpit');
fs.mkdirSync(path.join(directory,'revision'),{recursive:true});
for(const test of ['test_ui.cjs','test_traffic.cjs','test_health_ui.cjs','test_overview_ui.cjs','../cockpit-eventos/test_ui.cjs']){
  const result=spawnSync(process.execPath,[path.join(directory,test)],{cwd:root,stdio:'inherit'});
  if(result.status!==0)process.exit(result.status||1);
}
const events=spawnSync(process.execPath,['--test',path.join(root,'src/eventos/tests/panel.test.cjs')],{cwd:root,stdio:'inherit'});
if(events.status!==0)process.exit(events.status||1);
const forwarding=spawnSync(process.execPath,[path.join(root,'src/eventos/tests/forwarding_ui.cjs')],{cwd:root,stdio:'inherit'});
if(forwarding.status!==0)process.exit(forwarding.status||1);
