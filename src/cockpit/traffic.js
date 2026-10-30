"use strict";
const el = id => document.getElementById(id);
const monitor = {process:null, previous:null, samples:[], rx:0, tx:0, rxPeak:0, txPeak:0, duration:0, buffer:"", runId:0};
const fmt = new Intl.NumberFormat("es-MX",{maximumFractionDigits:2,minimumFractionDigits:2});
const SVG = "http://www.w3.org/2000/svg";
function amount(bytes) {
  if (bytes < 1000) return `${Math.round(bytes)} B`;
  const units=["KB","MB","GB","TB"];let value=bytes/1000,index=0;
  while(value>=1000 && index<units.length-1){value/=1000;index++;}
  return `${fmt.format(value)} ${units[index]}`;
}
function setError(err) {el("error").textContent=err.message || String(err);el("error").hidden=false;}
function draw() {
  const points=monitor.samples;
  const max=Math.max(1,...points.flatMap(p=>[p.rx,p.tx]))*1.15;
  const scale=Math.ceil(max*10)/10;
  const left=65,right=1010,top=24,bottom=250,width=right-left,height=bottom-top;
  const group=el("axes");group.replaceChildren();
  function node(tag,attrs,text){const n=document.createElementNS(SVG,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;group.append(n);}
  for(let i=0;i<=4;i++){
    const y=top+i*height/4;
    node("line",{x1:left,y1:y,x2:right,y2:y,class:"grid"});
    node("text",{x:left-12,y:y+4,"text-anchor":"end"},fmt.format(scale*(1-i/4)));
  }
  node("text",{x:left-12,y:12,"text-anchor":"end"},"Mb/s");
  for(let i=0;i<=4;i++)node("text",{x:left+i*width/4,y:277,"text-anchor":i===4?"end":"middle"},i===4?"Ahora":`${120-i*30} s`);
  const last=points.length?points[points.length-1].time:0;
  for(const dir of ["rx","tx"]){
    const coords=points.map(p=>[right-(last-p.time)/120*width,bottom-p[dir]/scale*height]);
    el(`${dir}-line`).setAttribute("points",coords.map(p=>p.join(",")).join(" "));
    el(`${dir}-area`).setAttribute("points",coords.length?`${coords[0][0]},${bottom} `+coords.map(p=>p.join(",")).join(" ")+` ${coords[coords.length-1][0]},${bottom}`:"");
  }
  el("chart-empty").textContent=points.length?"":"Pulsa Iniciar monitor para ver el tráfico";
}
function reset() {
  monitor.previous=null;monitor.samples=[];monitor.rx=0;monitor.tx=0;monitor.rxPeak=0;monitor.txPeak=0;monitor.duration=0;monitor.buffer="";
  for(const key of ["rx-rate","tx-rate","rx-peak","tx-peak","session-volume"])el(key).textContent="—";
  el("session-rx").textContent="↓ —";el("session-tx").textContent="↑ —";el("session-length").textContent="Sesión sin iniciar";draw();
}
function update(sample) {
  for(const key of ["timestamp","rx_bytes","tx_bytes"])if(!Number.isFinite(sample[key]))throw new Error("Lectura de red no válida.");
  el("link-speed").textContent=sample.speed_mbps?`${el("interface").value} · enlace de ${sample.speed_mbps} Mb/s`:`${el("interface").value} · velocidad de enlace no disponible`;
  const previous=monitor.previous;monitor.previous=sample;
  if(!previous)return;
  const dt=sample.timestamp-previous.timestamp;
  if(dt<=0)return;
  const rx=Math.max(0,sample.rx_bytes-previous.rx_bytes),tx=Math.max(0,sample.tx_bytes-previous.tx_bytes);
  const rxRate=rx*8/dt/1e6,txRate=tx*8/dt/1e6;
  monitor.rx+=rx;monitor.tx+=tx;monitor.duration+=dt;
  monitor.rxPeak=Math.max(monitor.rxPeak,rxRate);monitor.txPeak=Math.max(monitor.txPeak,txRate);
  monitor.samples.push({time:sample.timestamp,rx:rxRate,tx:txRate});
  monitor.samples=monitor.samples.filter(p=>sample.timestamp-p.time<=120).slice(-121);
  el("rx-rate").textContent=fmt.format(rxRate);el("tx-rate").textContent=fmt.format(txRate);
  el("rx-peak").textContent=fmt.format(monitor.rxPeak)+" Mb/s";el("tx-peak").textContent=fmt.format(monitor.txPeak)+" Mb/s";
  el("session-volume").textContent=amount(monitor.rx+monitor.tx);
  el("session-rx").textContent="↓ "+amount(monitor.rx);el("session-tx").textContent="↑ "+amount(monitor.tx);
  const seconds=Math.floor(monitor.duration);el("session-length").textContent=`Sesión ${Math.floor(seconds/60)} min ${seconds%60} s`;
  el("status").textContent=`Midiendo ${el("interface").value} · actualización cada segundo.`;draw();
}
function controls(running) {
  el("interface").disabled=running || !el("interface").value;
  el("start").disabled=running || !el("interface").value;el("stop").disabled=!running;el("clear").disabled=running;
  el("badge").textContent=running?"En vivo":"Detenido";el("badge").classList.toggle("active",running);
}
function stop(message="Monitor detenido. Las últimas lecturas quedan en pantalla.") {
  const process=monitor.process;monitor.process=null;monitor.runId++;monitor.buffer="";
  if(process)process.close("terminated");
  controls(false);if(message)el("status").textContent=message;
}
function start() {
  if(monitor.process || !el("interface").value)return;
  if(document.hidden || cockpit.hidden)return;
  reset();el("error").hidden=true;controls(true);
  el("status").textContent="Preparando la primera lectura…";
  const id=++monitor.runId;
  const process=cockpit.spawn(["/usr/bin/python3","-u","/usr/local/libexec/gateway-scanner.py","traffic-stream",el("interface").value],{err:"message",environ:["LC_ALL=C"]});
  monitor.process=process;
  process.stream(chunk=>{
    if(id!==monitor.runId)return;
    monitor.buffer+=chunk;
    if(monitor.buffer.length>65536){stop();setError(new Error("La lectura de red excedió el tamaño esperado."));return;}
    let newline;
    try {while((newline=monitor.buffer.indexOf("\n"))>=0){const line=monitor.buffer.slice(0,newline);monitor.buffer=monitor.buffer.slice(newline+1);if(line.trim())update(JSON.parse(line));}}
    catch(err){stop("No se pudo interpretar la lectura del puerto.");setError(err);}
  });
  process.then(()=>{if(id===monitor.runId)stop("La medición terminó. Pulsa Iniciar monitor para repetirla.");},err=>{
    if(id!==monitor.runId)return;
    stop("La medición se interrumpió. Revisa que el puerto siga conectado.");setError(err);
  });
}
async function load() {
  draw();
  try{
    const text=await cockpit.spawn(["/usr/bin/python3","/usr/local/libexec/gateway-scanner.py","interfaces"],{err:"message"});
    const data=JSON.parse(text);el("interface").replaceChildren();
    for(const net of data.interfaces){const option=document.createElement("option");option.value=net.name;option.textContent=`${net.name} · ${net.addresses.join(", ")}`;el("interface").append(option);}
    if(data.interfaces.some(net=>net.name==="eth0"))el("interface").value="eth0";
    controls(false);
    if(!data.interfaces.length)el("status").textContent="No hay conexiones locales activas con IPv4. Recarga el panel después de conectar la red.";
    else el("link-speed").textContent=`${el("interface").value} · monitor apagado`;
  }catch(err){setError(err);controls(false);}
}
el("start").addEventListener("click",start);el("stop").addEventListener("click",()=>stop());
el("clear").addEventListener("click",()=>{reset();el("status").textContent="Gráfica limpia. Pulsa Iniciar monitor para medir.";});
el("interface").addEventListener("change",()=>{reset();el("link-speed").textContent=el("interface").value+" · monitor apagado";});
document.addEventListener("visibilitychange",()=>{if(document.hidden && monitor.process)stop("Monitor detenido al ocultar el panel. Pulsa Iniciar monitor para continuar.");});
cockpit.addEventListener("visibilitychange",()=>{if(cockpit.hidden && monitor.process)stop("Monitor detenido al salir del panel. Pulsa Iniciar monitor para continuar.");});
window.addEventListener("pagehide",()=>stop());
load();
