const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const{chromium}=require('playwright');
const root=path.resolve(__dirname,'../collector');
const server=http.createServer((req,res)=>{
 const name=path.basename(req.url.split('?')[0]);const file=req.url==='/'?'index.html':name;
 if(!['index.html','panel.js','panel.css'].includes(file)){res.writeHead(404);res.end();return;}
 res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(path.join(root,file==='index.html'?file:'static/'+file)));
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({...(process.env.PLAYWRIGHT_EXECUTABLE_PATH?{executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH}:{}),headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1280,height:1000},colorScheme:'dark'}),errors=[];page.on('pageerror',e=>errors.push(e.message));let saved=null,viewer=false;
  await page.route('**/api/**',async route=>{
   const url=new URL(route.request().url());let body=[];
   if(url.pathname==='/api/status')body={events:0,access_role:viewer?'viewer':'admin',cameras:[],storage:{bytes:4096,limit_bytes:2000000000,free_bytes:4000000000}};
   if(url.pathname==='/api/forwarding'){
    if(route.request().method()==='PUT')saved=route.request().postDataJSON();
    body={enabled:saved?.enabled||false,scheme:saved?.scheme,host:saved?.host,port:saved?.port,path:saved?.path,pending:0,sent:12,dropped:3,last_result:'Sin errores'};
   }
   if(url.pathname==='/api/forwarding/test')body={ok:true,detail:'Respuesta HTTP 204. Prueba recibida.'};
   await route.fulfill({json:body});
  });
  await page.goto('http://127.0.0.1:'+server.address().port+'/');await page.fill('#token','synthetic-admin');await page.click('#connect');await page.waitForFunction(()=>!document.querySelector('#forwarding-form').hidden);
  await page.selectOption('#forward-scheme','http');await page.fill('#forward-host','receiver.example.invalid');await page.fill('#forward-port','9001');await page.fill('#forward-path','/ingest');await page.fill('#forward-token','synthetic-bearer');await page.check('#forward-enabled');
  await page.locator('#forwarding-form button[type=submit],#forwarding-form button:not([type])').click();await page.waitForFunction(()=>document.querySelector('#forwarding-message').textContent.includes('guardada'));
  assert.equal(saved.port,9001);assert.equal(saved.path,'/ingest');assert.equal(saved.enabled,true);assert.equal(await page.locator('#forward-token').inputValue(),'');assert.match(await page.locator('#forwarding-status').textContent(),/Descartados sin enviar: 3/);
  await page.click('#forward-test');await page.waitForFunction(()=>document.querySelector('#forwarding-message').textContent.includes('204'));
  const revision=path.join(__dirname,'revision');fs.mkdirSync(revision,{recursive:true});await page.screenshot({path:path.join(revision,'forwarding-desktop.png'),fullPage:true});await page.setViewportSize({width:430,height:940});await page.screenshot({path:path.join(revision,'forwarding-mobile.png'),fullPage:true});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  viewer=true;await page.click('#connect');await page.waitForFunction(()=>document.querySelector('#forwarding-form').hidden);assert.deepEqual(errors,[]);console.log('Forwarding UI OK: destination fields, explicit enable, bearer cleared, test request, delivery counters, viewer and mobile.');
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
