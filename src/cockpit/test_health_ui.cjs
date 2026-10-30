const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const{chromium}=require('playwright');
const fixture={checked_at:'2026-10-30T18:00:00Z',local_status:'warning',cloud:'not-confirmed',containers:[
 {id:'app1',service:'app',name:'camera_agent_gateway-app-1',image:'uplink-gateway:1.0.16-arm64',state:'running',health:'healthy',restarts:0,stats:{CPUPerc:'0.28%',MemUsage:'83 MiB / 7.7 GiB'}},
 {id:'nginx1',service:'nginx',name:'camera_agent_gateway-nginx-1',image:'uplink-gateway-nginx:1.0.16-arm64',state:'running',health:'not-configured',restarts:0,stats:{CPUPerc:'0.01%',MemUsage:'4 MiB / 7.7 GiB'}}],
 web:{valid:true,code:200,latency_ms:8},internal:{proxy_processes:1,proxy_tcp443:1,database:{camera_total:0,camera_enabled:0},logs:{files_sampled:2,events:{auth:0,error:0,disconnect:2,established:1}},notes:[]},
 checks:[{label:'Aplicación VXG',status:'ok',detail:'En ejecución · healthcheck healthy.'},{label:'Nginx',status:'ok',detail:'En ejecución · sin HEALTHCHECK configurado.'},{label:'Interfaz VXG',status:'ok',detail:'HTTP 200 · 8 ms'},{label:'Estilos de la interfaz',status:'ok',detail:'HTTP 200 · 2834 bytes'},{label:'Procesos Uplink',status:'ok',detail:'1 proceso vxg-proxy-client. Esto no confirma conexión con la nube.'},{label:'Transporte de los proxies',status:'ok',detail:'1 conexión TCP 443 establecida del proxy. No confirma WebSocket ni video.'},{label:'Persistencia de SQLite',status:'warning',detail:'Ejemplo de advertencia para revisar la persistencia antes de recrear el contenedor.'}],
 host:{ram_used_percent:11.2,ram_available:6900000000,disk_used_percent:21.6,disk_free:42000000000,uptime_seconds:9200},notes:[]};
const mock=`const listeners=[];window.checks=0;window.failHealth=false;window.data=${JSON.stringify(fixture)};window.cockpit={hidden:false,addEventListener:(name,fn)=>listeners.push(fn),setHidden(value){this.hidden=value;listeners.forEach(fn=>fn());},spawn(args,opts){window.checks++;window.lastOptions=opts;const p=new Promise((resolve,reject)=>setTimeout(()=>window.failHealth?reject({problem:'access-denied'}):resolve(JSON.stringify(window.data)),40));p.close=()=>{};return p;}};`;
const server=http.createServer((req,res)=>{
 if(req.url==='/base1/cockpit.js'){res.setHeader('Content-Type','text/javascript');res.end(mock);return;}
 const file=path.basename(req.url.split('?')[0]);if(!['health.html','health.js','health.css','scanner.css'].includes(file)){res.writeHead(404);res.end();return;}
 res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(path.join(__dirname,file)));
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({...(process.env.PLAYWRIGHT_EXECUTABLE_PATH ? {executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH} : {}),headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1320,height:1050}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:'+server.address().port+'/gateway_scanner/health.html');
  assert.equal(await page.evaluate(()=>checks),0);assert.equal(await page.locator('#auto').isChecked(),false);
  await page.click('#refresh');await page.waitForFunction(()=>!document.querySelector('#export').disabled);
  assert.equal(await page.evaluate(()=>lastOptions.superuser),'require');assert.equal(await page.locator('#proxy').textContent(),'1');
  assert.match(await page.locator('#cloud').textContent(),/sin confirmar/);assert.equal(await page.locator('#containers tr').count(),2);
  await page.screenshot({path:path.join(__dirname,'revision','health-desktop.png'),fullPage:true});
  await page.evaluate(()=>{window.data.containers[0].restarts=1;});await page.click('#refresh');await page.waitForFunction(()=>document.querySelector('.changed'));
  assert.match(await page.locator('.changed').textContent(),/\+1/);
  await page.check('#auto');await page.evaluate(()=>cockpit.setHidden(true));assert.equal(await page.locator('#auto').isChecked(),false);
  await page.evaluate(()=>{cockpit.setHidden(false);window.failHealth=true;});await page.waitForFunction(()=>!document.querySelector('#refresh').disabled);
  await page.click('#refresh');await page.waitForFunction(()=>!document.querySelector('#error').hidden);assert.match(await page.locator('#error').innerText(),/administrativo/);
  await page.setViewportSize({width:430,height:960});await page.screenshot({path:path.join(__dirname,'revision','health-mobile.png'),fullPage:true});
  assert.deepEqual(errors,[]);console.log('Health UI OK: no initial polling, admin access, summary, cloud unknown, containers, restart deltas, visibility stops updates, access failure.');
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
