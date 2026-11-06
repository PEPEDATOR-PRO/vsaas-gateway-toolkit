// Exercise the client state machine without contacting cameras or a browser.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Element {
  constructor() { this.children=[]; this.dataset={}; this.attributes={}; this.value=''; this.scrollTop=0; this.hidden=false; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children=[...nodes]; }
  add(node) { this.append(node); }
  setAttribute(name,value) { this.attributes[name]=value; }
  querySelectorAll(selector) { return this.children.filter(node => selector === '.event-item' && node.className === 'event-item'); }
  get scrollHeight() { return this.children.length * 90; }
}
const event = id => ({id,camera_id:'one',received_at:'2026-10-15T12:00:00Z',source_time:null,transport:'onvif',topic:'Motion',metadata:{id,notification_xml:'<message>'+id+'</message>'}});
function setup(initial) {
  const elements = new Map(), requests = [], timers = [];
  const get = selector => { if(!elements.has(selector)) elements.set(selector,new Element()); return elements.get(selector); };
  get('#mode').value='onvif'; get('#camera-protocol').value='http'; get('#token').value='test-token';
  let database=[...initial], customFetch=null;
  const normalFetch=async url=>{
    requests.push(url);
    if(url==='/api/status') return {ok:true,json:async()=>({events:database.length,cameras:[{id:'one',name:'Entrada',mode:'onvif',status:'conectada'}]})};
    const query=new URL(url,'http://test').searchParams;
    let rows=database.filter(e=>e.id>Number(query.get('after_id')||0));
    if(query.has('before_id'))rows=rows.filter(e=>e.id<Number(query.get('before_id')));
    if(query.has('topic'))rows=rows.filter(e=>e.topic.includes(query.get('topic')));
    rows.sort((a,b)=>query.get('order')==='desc'?b.id-a.id:a.id-b.id);
    return {ok:true,json:async()=>rows.slice(0,Number(query.get('limit')))};
  };
  const context=vm.createContext({
    document:{querySelector:get,createElement:()=>new Element()},
    Option:function(text,value){this.textContent=text;this.value=value;},
    fetch:(...args)=>(customFetch||normalFetch)(...args),
    URLSearchParams,URL,Blob,console, setInterval:(fn,delay)=>timers.push({fn,delay}),setTimeout:()=>{},
    confirm:()=>false
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../collector/static/panel.js'),'utf8'),context);
  return {context,get,requests,timers, add:e=>database.push(e), setFetch:fn=>{customFetch=fn;},
    state:()=>JSON.parse(vm.runInContext('JSON.stringify({ids:page.map(e=>e.id),selected:selectedEvent?.id,lastId,paused})',context))};
}
const settle=()=>new Promise(resolve=>setImmediate(resolve));

test('capability lookup is on demand, prevents duplicates, and ignores closed results',async()=>{
  const app=setup([]);await app.get('#connect').onclick();
  assert.equal(app.requests.filter(url=>url.includes('/capabilities')).length,0);
  let complete, calls=0;
  app.setFetch(async()=>{calls++;return new Promise(resolve=>{complete=resolve;});});
  const pending=app.context.inspectCapabilities({id:'one',name:'Entrada'});
  assert.equal(app.get('#capabilities-panel').hidden,false);
  assert.match(app.get('#capabilities-status').textContent,/Consultando/);
  await app.context.inspectCapabilities({id:'one',name:'Entrada'});assert.equal(calls,1);
  app.get('#capabilities-close').onclick();
  complete({ok:true,json:async()=>({})});await pending;
  assert.equal(app.get('#capabilities-panel').hidden,true);
  assert.equal(vm.runInContext('capabilityReport',app.context),null);
});

test('capability failure explains the error and allows retry',async()=>{
  const app=setup([]);
  app.setFetch(async()=>({ok:false,json:async()=>({detail:'Sin conexión'})}));
  await app.context.inspectCapabilities({id:'one',name:'Entrada'});
  assert.match(app.get('#capabilities-status').textContent,/Sin conexión/);
  assert.equal(app.get('#capabilities-download').hidden,true);
  assert.equal(vm.runInContext('capabilityBusy.size',app.context),0);
});

test('simplified WiseAI JSON preserves synthetic attributes, repeated values and original record',()=>{
  const sample=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/wiseai.json'),'utf8'));
  const app=setup([]);
  const before=JSON.stringify(sample);
  app.context.sample=sample;
  const result=JSON.parse(vm.runInContext('JSON.stringify(simplifyEvent(sample))',app.context));
  const object=result.objetos[0];
  assert.equal(object.tipo,'persona');
  assert.equal(object.confianza,0.58);
  assert.equal(object.gorra,false);
  assert.equal(object.ropa_superior_color,'negro');
  assert(!JSON.stringify(result).includes('frame_xml'));
  assert.equal(JSON.stringify(sample),before);
});

test('new arrivals appear first; selecting pins detail; pause catches up on resume',async()=>{
  const app=setup([event(1),event(2)]);
  await app.get('#connect').onclick();
  assert.deepEqual(app.state().ids,[2,1]);
  app.get('#events').children[1].onclick();
  assert.equal(app.state().selected,1);
  app.add(event(3)); await app.context.pollEvents();
  assert.deepEqual(app.state().ids,[3,2,1]);
  assert.equal(app.state().selected,1);
  assert.match(app.get('#detail-xml').textContent,/>1</);
  app.get('#pause').onclick();
  app.add(event(4)); await app.context.pollEvents();
  assert.deepEqual(app.state().ids,[3,2,1]);
  assert.equal(app.get('#pause').textContent,'Reanudar vista');
  app.get('#pause').onclick(); await settle();
  assert.deepEqual(app.state().ids,[4,3,2,1]);
  assert.equal(app.state().selected,1);
  assert(app.timers.some(timer=>timer.delay===1000));
});

test('pausing discards an in-flight response without advancing the live cursor',async()=>{
  const app=setup([event(1)]); await app.get('#connect').onclick();
  let complete;
  app.setFetch(()=>new Promise(resolve=>{complete=resolve;}));
  const inFlight=app.context.pollEvents();
  app.get('#pause').onclick();
  complete({ok:true,json:async()=>[event(2)]}); await inFlight;
  assert.deepEqual(app.state().ids,[1]); assert.equal(app.state().lastId,1);
  app.setFetch(null); app.add(event(2));
  app.get('#pause').onclick(); await settle();
  assert.deepEqual(app.state().ids,[2,1]); assert.equal(app.state().lastId,2);
});

test('history pauses the list; visible window is bounded and selected detail survives',async()=>{
  const app=setup(Array.from({length:150},(_,i)=>event(i+1)));
  await app.get('#connect').onclick();
  assert.equal(app.state().ids.length,100);
  await app.get('#older').onclick();
  assert.equal(app.state().paused,true); assert.equal(app.state().ids.length,150);
  app.get('#events').children.at(-1).onclick();
  assert.equal(app.state().selected,1);
  app.context.mergeEvents(Array.from({length:600},(_,i)=>event(i+151)));
  assert.equal(app.state().ids.length,500); assert.equal(app.state().ids[0],750);
  assert.equal(app.state().selected,1);
  assert.equal(app.get('#older').disabled,true);
});

test('typed filters do not change the live cursor until applied; errors recover',async()=>{
  const app=setup([event(1)]); await app.get('#connect').onclick();
  app.get('#topic').value='Vehicle';
  app.add(event(2)); await app.context.pollEvents();
  assert(!app.requests.at(-1).includes('topic='));
  app.setFetch(async()=>{throw Error('offline');}); await app.context.pollEvents();
  assert.equal(app.get('#feed-error').hidden,false);
  app.setFetch(null); await app.context.pollEvents();
  assert.equal(app.get('#feed-error').hidden,true);
  await app.get('#load').onclick();
  assert.deepEqual(app.state().ids,[]); assert(app.requests.at(-1).includes('topic=Vehicle'));
});

test('viewer access hides camera management while preserving the live feed',async()=>{
  const app=setup([event(1)]);
  app.setFetch(async url=>({ok:true,json:async()=>url==='/api/status'
    ? {events:1,access_role:'viewer',cameras:[{id:'one',name:'Entrada',mode:'onvif',status:'conectada'}]}
    : [event(1)]}));
  await app.get('#connect').onclick();
  assert.equal(app.get('#camera-management').hidden,true);
  assert.equal(app.get('#cameras').children[0].children.at(-1).children.length,0);
  assert.deepEqual(app.state().ids,[1]);
  assert.equal(app.get('#pause').disabled,false);
  assert.match(app.get('#access-note').textContent,/Solo consulta/);
});

test('NVR metadata frames show object attributes and frame XML in the detail pane',async()=>{
  const frame={...event(1),transport:'rtsp_metadata',topic:'ONVIF/VideoAnalytics/Objects',
    metadata:{objects:[{object_id:'7',classes:[{type:'Human',likelihood:'0.98'}]}],frame_xml:'<Frame><Object ObjectId="7"/></Frame>'}};
  const app=setup([frame]);await app.get('#connect').onclick();
  assert.match(app.get('#detail-metadata').textContent,/persona/);
  assert(!app.get('#detail-metadata').textContent.includes('frame_xml'));
  assert.match(app.get('#detail-xml').textContent,/ObjectId="7"/);
  assert.equal(app.get('#xml-section').hidden,false);
});

test('forwarding form sends configured JSON destination and clears bearer input',async()=>{
  const app=setup([]);let saved;
  app.setFetch(async(url,options)=>({ok:true,json:async()=>{
    if(url==='/api/status')return {events:0,access_role:'admin',cameras:[]};
    if(url==='/api/forwarding'){if(options?.method==='PUT')saved=JSON.parse(options.body);return {enabled:false,pending:0,sent:0,dropped:0};}
    return [];
  }}));
  await app.get('#connect').onclick();
  app.get('#forward-scheme').value='https';app.get('#forward-host').value='receiver.example.invalid';app.get('#forward-port').value='9443';app.get('#forward-path').value='/ingest/events';app.get('#forward-token').value='synthetic-bearer';app.get('#forward-enabled').checked=true;
  await app.get('#forwarding-form').onsubmit({preventDefault(){}});
  assert.equal(saved.host,'receiver.example.invalid');assert.equal(saved.port,9443);assert.equal(saved.path,'/ingest/events');assert.equal(saved.enabled,true);assert.equal(app.get('#forward-token').value,'');
});
