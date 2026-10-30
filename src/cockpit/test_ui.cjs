const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const mock = `window.cockpit = {spawn(args, options) {
  window.lastCall = {args, options};
  return new Promise((resolve, reject) => setTimeout(() => {
    const action = args[2];
    if (action === 'interfaces') return resolve(JSON.stringify({interfaces:[{name:'eth0',addresses:['192.168.1.10/24']},{name:'wlan0',addresses:['192.168.60.10/24']}]}));
    if (window.failScan) return reject({problem:'access-denied'});
    if (action === 'scan') return resolve(JSON.stringify({devices:[
      {ip:'192.168.1.1',mac:'10:20:30:40:50:60',vendor:'Router de la red'},
      {ip:'192.168.1.20',mac:'aa:bb:cc:dd:ee:ff',vendor:'No identificado'},
      {ip:'192.168.1.42',mac:'12:34:56:78:90:ab',vendor:'Fabricante de prueba'},
      {ip:'192.168.1.100',mac:'ab:cd:ef:12:34:56',vendor:'<img src=x onerror=alert(1)>'}
    ],raw:'Salida de ejemplo para verificar la interfaz',warnings:'',elapsed:1.8}));
    if (action === 'ports') return resolve(JSON.stringify({ports:[80,554]}));
    reject(new Error('Unknown action'));
  }, 80));
}};`;
const server = http.createServer((req,res) => {
  if (req.url === '/base1/cockpit.js') {res.setHeader('Content-Type','text/javascript');res.end(mock);return;}
  const name = path.basename(req.url.split('?')[0]);
  const allowed = ['index.html','scanner.js','scanner.css'];
  if (!allowed.includes(name)) {res.writeHead(404);res.end();return;}
  res.setHeader('Content-Type', name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html');
  res.end(fs.readFileSync(path.join(__dirname, name)));
});
(async () => {
  await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
  const browser = await chromium.launch({...(process.env.PLAYWRIGHT_EXECUTABLE_PATH ? {executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH} : {}),headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1280,height:940}, acceptDownloads:true});
    const errors=[]; page.on('pageerror',err=>errors.push(err.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/gateway_scanner/index.html`);
    await page.waitForFunction(() => !document.querySelector('#scan').disabled);
    assert.equal(await page.locator('#interface').inputValue(),'eth0');
    await page.click('#scan');
    await page.waitForFunction(() => document.querySelector('#count').textContent === '4 equipos');
    assert.equal(await page.locator('#rows tr').count(),4);
    assert.equal(await page.locator('#rows img').count(),0);
    assert.equal(await page.evaluate(()=>window.lastCall.options.superuser),'require');
    await page.locator('#rows button').nth(1).click();
    await page.waitForFunction(() => document.querySelector('.ports')?.textContent.includes('554'));
    await page.fill('#filter','192.168.1.20');
    assert.equal(await page.locator('#rows tr').count(),1);
    assert.match(await page.locator('#rows').innerText(),/RTSP/);
    const downloadPromise = page.waitForEvent('download'); await page.click('#export');
    const download = await downloadPromise;
    const csv = fs.readFileSync(await download.path(),'utf8');
    assert.match(csv,/192\.168\.1\.100/);
    await page.fill('#filter','');
    fs.mkdirSync(path.join(__dirname,'revision'),{recursive:true});
    await page.screenshot({path:path.join(__dirname,'revision','scanner-desktop.png'),fullPage:true});
    await page.setViewportSize({width:430,height:930});
    await page.screenshot({path:path.join(__dirname,'revision','scanner-mobile.png'),fullPage:true});
    await page.evaluate(()=>window.failScan=true); await page.click('#scan');
    await page.waitForFunction(() => !document.querySelector('#error').hidden);
    assert.match(await page.locator('#error').innerText(),/acceso administrativo/);
    assert.equal(await page.locator('#rows tr').count(),4);
    assert.equal(await page.locator('#scan').isEnabled(),true);
    assert.deepEqual(errors,[]);
    console.log('UI OK: interfaces, scan, privileges, filtering, ports, CSV, escaping, failure recovery, desktop and mobile.');
  } finally { await browser.close(); server.close(); }
})().catch(err=>{console.error(err);server.close();process.exitCode=1;});
