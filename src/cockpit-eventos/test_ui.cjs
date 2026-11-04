const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const{chromium}=require('playwright');
const mock=`const listeners=[];window.queries=0;window.fail=false;window.cockpit={hidden:false,addEventListener:(e,f)=>listeners.push(f),setHidden(v){this.hidden=v;listeners.forEach(f=>f());},spawn(args,options){window.queries++;window.options=options;window.args=args;let reject;const p=new Promise((resolve,r)=>{reject=r;setTimeout(()=>window.fail?r({problem:'access-denied'}):resolve(JSON.stringify({installed:true,state:'running',health:'healthy',restarts:0,responds:true,url:'http://192.0.2.10:8081'})),30);});p.close=()=>reject({problem:'terminated'});return p;}};`;
const server=http.createServer((req,res)=>{
 if(req.url==='/base1/cockpit.js'){res.setHeader('Content-Type','text/javascript');res.end(mock);return;}
 const file=path.basename(req.url.split('?')[0]);if(!['index.html','eventos.js','eventos.css'].includes(file)){res.writeHead(404);res.end();return;}
 res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(path.join(__dirname,file)));
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({...(process.env.PLAYWRIGHT_EXECUTABLE_PATH?{executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH}:{}),headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1280,height:1000},colorScheme:'dark'}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:'+server.address().port+'/gateway_eventos/index.html');assert.equal(await page.evaluate(()=>queries),0);
  await page.click('#refresh');await page.waitForFunction(()=>!document.querySelector('#refresh').disabled);
  assert.equal(await page.locator('#badge').textContent(),'En ejecución');assert.equal(await page.locator('#open').getAttribute('href'),'http://192.0.2.10:8081');assert.equal(await page.evaluate(()=>options.superuser),'require');
  assert.deepEqual(await page.evaluate(()=>args),['/usr/local/bin/vsaas-eventos','estado','--json']);
  const revision=path.join(__dirname,'revision');fs.mkdirSync(revision,{recursive:true});await page.screenshot({path:path.join(revision,'eventos-desktop.png'),fullPage:true});
  await page.setViewportSize({width:430,height:930});await page.screenshot({path:path.join(revision,'eventos-mobile.png'),fullPage:true});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.evaluate(()=>{window.fail=true;});await page.click('#refresh');await page.waitForFunction(()=>!document.querySelector('#refresh').disabled);assert.match(await page.locator('#status').textContent(),/administrativo/);
  assert.equal(await page.locator('#open').isHidden(),true);assert.deepEqual(errors,[]);console.log('Events portal UI OK: on demand, privileges, safe URL, no key query, access failure and mobile.');
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
