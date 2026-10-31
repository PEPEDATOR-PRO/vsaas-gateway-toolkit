const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const{chromium}=require('playwright');
const mock=`window.trafficStarts=0;window.healthQueries=0;window.closedReaders=0;window.jumped=null;const listeners=[];
window.cockpit={hidden:false,addEventListener:(event,fn)=>listeners.push(fn),jump:path=>window.jumped=path,setHidden(value){this.hidden=value;listeners.forEach(fn=>fn());},spawn(args,options){
 if(args.includes('interfaces'))return Promise.resolve(JSON.stringify({interfaces:[{name:'eth0',addresses:['192.168.1.10/24']}]}));
 if(args.includes('/usr/local/libexec/vxg-health.py')){window.healthQueries++;return Promise.resolve(JSON.stringify({vpn:{status:'critical'},local_status:'ok',checked_at:new Date().toISOString(),containers:[{service:'app',state:'running',health:'healthy'}],web:{valid:true,latency_ms:8},internal:{database:{camera_total:0,camera_enabled:0}}}));}
 window.trafficStarts++;let reject,timer,i=0,rx=0,tx=0;const p=new Promise((resolve,r)=>reject=r);
 p.stream=fn=>{timer=setInterval(()=>{rx+=(8+Math.sin(i/4)*2)*1e6/8;tx+=(21+Math.sin(i/7)*6)*1e6/8;fn(JSON.stringify({timestamp:i++,rx_bytes:rx,tx_bytes:tx})+'\\n');},15);};
 p.close=()=>{clearInterval(timer);window.closedReaders++;reject({problem:'terminated'});};return p;
}};`;
const html=`<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><script src="../base1/cockpit.js"></script><link rel="stylesheet" href="../gateway_scanner/overview-cards.css"><script defer src="../gateway_scanner/overview-cards.js"></script><style>
body{margin:0;background:#262626;color:#fff;font:15px system-ui}#overview{padding:24px}.host{font-size:21px;margin:0 0 35px}.host small{font-size:14px;font-weight:400}.ct-system-overview{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}.native{border:1px solid #4c4c4c;border-radius:16px;padding:22px;min-height:280px}.native h2{font-size:22px;margin:0 0 24px}.native p{font-size:13px;border-bottom:1px solid #454545;padding-bottom:12px}.native a{color:#8bc1f7}@media(max-width:1100px){.ct-system-overview{grid-template-columns:1fr 1fr}}@media(max-width:650px){.ct-system-overview{grid-template-columns:1fr}.native{min-height:150px}}
</style></head><body><div id="overview"><h1 class="host">ubuntu <small>ejecutando Ubuntu 26.10</small></h1><div class="ct-system-overview"><section class="native"><h2>Salud</h2><a>1 servicio ha fallado</a></section><section class="native"><h2>Uso</h2><p>CPU · 0% de 4 núcleos</p><p>Memoria · 0.87 / 7.7 GiB</p></section><section class="native"><h2>Información del sistema</h2><p>Activo desde · hace 20 horas</p></section><section class="native"><h2>Configuración</h2><p>Nombre del anfitrión · ubuntu</p><p>Hora del sistema</p></section></div></div></body></html>`;
const server=http.createServer((req,res)=>{
 if(req.url==='/base1/cockpit.js'){res.setHeader('Content-Type','text/javascript');res.end(mock);return;}
 if(req.url==='/system/index.html'){res.setHeader('Content-Type','text/html');res.end(html);return;}
 const file=path.basename(req.url);if(!['overview-cards.js','overview-cards.css'].includes(file)){res.writeHead(404);res.end();return;}
 res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':'text/css');res.end(fs.readFileSync(path.join(__dirname,file)));
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({...(process.env.PLAYWRIGHT_EXECUTABLE_PATH ? {executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH} : {}),headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1000},colorScheme:'dark'});const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:'+server.address().port+'/system/index.html');await page.waitForFunction(()=>!document.querySelector('#vsaas-interface').disabled);
  assert.equal(await page.locator('.native').count(),4);assert.equal(await page.locator('.vsaas-summary-card').count(),2);
  assert.equal(await page.evaluate(()=>trafficStarts),0);assert.equal(await page.evaluate(()=>healthQueries),0);
  await page.click('#vsaas-health-refresh');await page.waitForFunction(()=>!document.querySelector('#vsaas-health-refresh').disabled);
  assert.equal(await page.locator('#vsaas-app').textContent(),'En ejecución');
  assert.equal(await page.locator('#vsaas-vpn').textContent(),'Desconectada');
  assert.equal(await page.locator('#vsaas-cameras').textContent(),'0 / 0');assert.match(await page.locator('#vsaas-overview-health').innerText(),/video sin confirmar/);
  await page.click('#vsaas-traffic-toggle');await page.waitForFunction(()=>document.querySelector('#vsaas-line-rx').getAttribute('points').split(' ').length>=50);
  assert.equal(await page.locator('#vsaas-traffic-badge').textContent(),'En vivo');
  assert.equal(await page.locator('.vsaas-chart-grid').count(),1);assert.match(await page.locator('#vsaas-chart-ceiling').textContent(),/Mb\/s/);assert.match(await page.locator('.vsaas-chart-times').innerText(),/60 s/);
  assert.ok((await page.locator('#vsaas-area-rx').getAttribute('points')).length>10);
  assert.notEqual(await page.locator('.vsaas-chart').evaluate(e=>getComputedStyle(e).backgroundColor),await page.locator('#vsaas-overview-traffic').evaluate(e=>getComputedStyle(e).backgroundColor));
  await page.screenshot({path:path.join(__dirname,'revision','overview-desktop.png'),fullPage:true});
  await page.click('#vsaas-traffic-toggle');const frozen=await page.locator('#vsaas-rx').textContent();await page.waitForTimeout(50);assert.equal(await page.locator('#vsaas-rx').textContent(),frozen);
  await page.evaluate(()=>document.querySelector('#vsaas-overview-health').remove());await page.waitForFunction(()=>document.querySelector('#vsaas-overview-health'));
  assert.equal(await page.locator('.vsaas-summary-card').count(),2);assert.equal(await page.locator('.native').count(),4);
  await page.click('#vsaas-traffic-toggle');await page.evaluate(()=>cockpit.setHidden(true));assert.equal(await page.locator('#vsaas-traffic-badge').textContent(),'Detenido');assert.equal(await page.evaluate(()=>closedReaders),2);
  await page.evaluate(()=>cockpit.setHidden(false));assert.equal(await page.evaluate(()=>trafficStarts),2);
  await page.setViewportSize({width:430,height:960});await page.screenshot({path:path.join(__dirname,'revision','overview-mobile.png'),fullPage:true});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.getByRole('button',{name:'Ver detalle',exact:true}).click();assert.equal(await page.evaluate(()=>jumped),'/gateway_scanner/health');
  assert.deepEqual(errors,[]);console.log('Overview UI OK: native cards preserved, no automatic probes, health summary, manual traffic, stop, native rerender, hidden stop, navigation, responsive layout.');
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
