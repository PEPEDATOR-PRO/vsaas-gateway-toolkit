const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const mock=`window.trafficStarts=0;window.trafficClosed=0;window.noPrivileges=true;
const visibilityListeners=[];
window.cockpit={hidden:false,addEventListener:(name,callback)=>visibilityListeners.push(callback),
setHidden(value){this.hidden=value;visibilityListeners.forEach(callback=>callback());},
spawn(args,options){
  if(args.includes('interfaces'))return Promise.resolve(JSON.stringify({interfaces:[{name:'eth0',addresses:['192.168.1.10/24']},{name:'wlan0',addresses:['192.168.60.10/24']}]}));
  window.trafficStarts++;if(options.superuser)window.noPrivileges=false;
  let rejectProcess,timer,count=0,rx=1000000,tx=2000000;
  const process=new Promise((resolve,reject)=>rejectProcess=reject);
  process.stream=callback=>{timer=setInterval(()=>{
    const rxRate=10+Math.sin(count/9)*4+(count%30>22?5:0),txRate=22+Math.sin(count/12)*7;
    rx+=Math.round(rxRate*1000000/8);tx+=Math.round(txRate*1000000/8);
    const text=JSON.stringify({timestamp:count++,rx_bytes:rx,tx_bytes:tx,speed_mbps:1000})+'\\n';
    const split=Math.floor(text.length/2);callback(text.slice(0,split));callback(text.slice(split));
  },12);};
  process.close=()=>{clearInterval(timer);window.trafficClosed++;rejectProcess({problem:'terminated'});};
  return process;
}};`;
const server=http.createServer((req,res)=>{
  if(req.url==='/base1/cockpit.js'){res.setHeader('Content-Type','text/javascript');res.end(mock);return;}
  const name=path.basename(req.url.split('?')[0]);
  if(!['traffic.html','traffic.js','traffic.css','scanner.css'].includes(name)){res.writeHead(404);res.end();return;}
  res.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html');
  res.end(fs.readFileSync(path.join(__dirname,name)));
});
(async()=>{
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const browser=await chromium.launch({...(process.env.PLAYWRIGHT_EXECUTABLE_PATH ? {executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH} : {}),headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1280,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://127.0.0.1:'+server.address().port+'/gateway_scanner/traffic.html');
    await page.waitForFunction(()=>!document.querySelector('#start').disabled);
    assert.equal(await page.evaluate(()=>trafficStarts),0);
    assert.equal(await page.locator('#badge').textContent(),'Detenido');
    await page.click('#start');
    await page.waitForFunction(()=>document.querySelector('#session-length').textContent.includes('1 min'));
    assert.equal(await page.locator('#badge').textContent(),'En vivo');
    assert.equal(await page.locator('#interface').isDisabled(),true);
    assert.ok(Number((await page.locator('#rx-rate').textContent()).replaceAll(',',''))>0);
    assert.ok((await page.locator('#rx-line').getAttribute('points')).length>20);
    assert.equal(await page.evaluate(()=>noPrivileges),true);
    await page.screenshot({path:path.join(__dirname,'revision','traffic-desktop.png'),fullPage:true});
    await page.click('#stop');
    assert.equal(await page.locator('#badge').textContent(),'Detenido');
    const frozen=await page.locator('#rx-rate').textContent();
    await page.waitForTimeout(80);assert.equal(await page.locator('#rx-rate').textContent(),frozen);
    assert.equal(await page.evaluate(()=>trafficClosed),1);
    await page.click('#clear');assert.equal(await page.locator('#rx-rate').textContent(),'—');
    await page.click('#start');await page.waitForFunction(()=>document.querySelector('#rx-rate').textContent!=='—');
    await page.evaluate(()=>cockpit.setHidden(true));
    assert.equal(await page.locator('#badge').textContent(),'Detenido');
    assert.equal(await page.evaluate(()=>trafficClosed),2);
    await page.evaluate(()=>cockpit.setHidden(false));assert.equal(await page.evaluate(()=>trafficStarts),2);
    await page.setViewportSize({width:430,height:960});
    await page.screenshot({path:path.join(__dirname,'revision','traffic-mobile.png'),fullPage:true});
    await page.evaluate(()=>{
      reset();
      update({timestamp:100,rx_bytes:1000000,tx_bytes:2000000});
      update({timestamp:102,rx_bytes:2000000,tx_bytes:2500000});
    });
    assert.equal(await page.locator('#rx-rate').textContent(),'4.00');
    assert.equal(await page.locator('#tx-rate').textContent(),'2.00');
    assert.equal(await page.locator('#session-volume').textContent(),'1.50 MB');
    await page.evaluate(()=>update({timestamp:103,rx_bytes:100,tx_bytes:200}));
    assert.equal(await page.locator('#rx-rate').textContent(),'0.00');
    await page.evaluate(()=>{for(let i=0;i<200;i++)update({timestamp:104+i,rx_bytes:200+i*10,tx_bytes:300+i*10});});
    assert.ok(await page.evaluate(()=>monitor.samples.length<=121));
    assert.deepEqual(errors,[]);
    console.log('Traffic UI OK: off by default, stream framing, live graph, no root, stop, freeze, reset, hidden panel stops and never auto-resumes, exact bitrates and volumes, counter reset, bounded history.');
  }finally{await browser.close();server.close();}
})().catch(err=>{console.error(err);server.close();process.exitCode=1;});
