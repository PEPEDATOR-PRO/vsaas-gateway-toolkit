/* Local overview adaptation. Uses the Cockpit instance already loaded by Overview. */
(() => {
  "use strict";
  const state={healthBusy:false,process:null,runId:0,buffer:"",previous:null,points:[],mounted:false};
  const by=id=>document.getElementById(id);
  const number=new Intl.NumberFormat("es-MX",{maximumFractionDigits:2,minimumFractionDigits:2});
  function make(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
  function button(text,id,action,secondary=false){const b=make("button",text,"vsaas-button"+(secondary?" vsaas-secondary":""));b.type="button";if(id)b.id=id;b.addEventListener("click",action);return b;}
  function valueRow(parent,label,id,initial="—"){const row=make("div",undefined,"vsaas-data-row");row.append(make("span",label));const value=make("strong",initial);value.id=id;row.append(value);parent.append(row);}
  function detailButton(text,path){return button(text,null,()=>cockpit.jump(path),true);}
  function buildCards(){
    const health=make("section",undefined,"vsaas-summary-card");health.id="vsaas-overview-health";health.setAttribute("aria-label","Resumen Salud Vsaas");
    const head=make("div",undefined,"vsaas-card-heading");head.append(make("h2","Salud Vsaas"));const badge=make("span","Sin comprobar","vsaas-badge");badge.id="vsaas-health-badge";head.append(badge);health.append(head);
    const data=make("div",undefined,"vsaas-health-data");
    valueRow(data,"Aplicación","vsaas-app");valueRow(data,"Interfaz web","vsaas-web");valueRow(data,"Cámaras configuradas / habilitadas","vsaas-cameras");
    health.append(data);const hint=make("p","VXG Cloud y video sin confirmar.","vsaas-note");health.append(hint);
    const actions=make("div",undefined,"vsaas-actions");actions.append(button("Actualizar resumen","vsaas-health-refresh",refreshHealth),detailButton("Ver detalle","/gateway_scanner/health"));health.append(actions);
    const status=make("p","Consulta bajo demanda · sin comprobar","vsaas-card-status");status.id="vsaas-health-status";status.setAttribute("role","status");health.append(status);

    const traffic=make("section",undefined,"vsaas-summary-card");traffic.id="vsaas-overview-traffic";traffic.setAttribute("aria-label","Resumen Tráfico de red");
    const heading=make("div",undefined,"vsaas-card-heading");heading.append(make("h2","Tráfico de red"));const trafficBadge=make("span","Detenido","vsaas-badge");trafficBadge.id="vsaas-traffic-badge";heading.append(trafficBadge);traffic.append(heading);
    const rates=make("div",undefined,"vsaas-rates");for(const[key,label]of [["rx","↓ Recepción"],["tx","↑ Envío"]]){const box=make("div");box.append(make("span",label,"vsaas-direction "+key));const strong=make("strong","—");strong.id="vsaas-"+key;box.append(strong,make("small","Mb/s"));rates.append(box);}traffic.append(rates);
    const ns="http://www.w3.org/2000/svg",svg=document.createElementNS(ns,"svg");svg.id="vsaas-sparkline";svg.setAttribute("viewBox","0 0 600 65");svg.setAttribute("role","img");svg.setAttribute("aria-label","Recepción y envío de los últimos 60 segundos");
    for(const key of ["rx","tx"]){const line=document.createElementNS(ns,"polyline");line.id="vsaas-line-"+key;line.setAttribute("class",key);svg.append(line);}traffic.append(svg);
    const network=make("div",undefined,"vsaas-network-controls");const select=document.createElement("select");select.id="vsaas-interface";select.setAttribute("aria-label","Puerto de red del resumen");select.disabled=true;network.append(select,button("Iniciar","vsaas-traffic-toggle",()=>state.process?stopTraffic():startTraffic()),detailButton("Ver gráfica","/gateway_scanner/traffic"));traffic.append(network);
    const trafficStatus=make("p","Monitor apagado · una muestra por segundo al activarlo","vsaas-card-status");trafficStatus.id="vsaas-traffic-status";trafficStatus.setAttribute("role","status");traffic.append(trafficStatus);
    return[health,traffic];
  }
  async function refreshHealth(){
    if(state.healthBusy)return;state.healthBusy=true;by("vsaas-health-refresh").disabled=true;
    by("vsaas-health-status").textContent="Consultando el estado local…";
    try{
      const output=await cockpit.spawn(["/usr/bin/python3","/usr/local/libexec/vxg-health.py"],{superuser:"require",err:"message"});
      const data=JSON.parse(output),badge=by("vsaas-health-badge");
      badge.textContent={ok:"Local correcto",warning:"Revisar",critical:"Fallo local",unknown:"Incompleto"}[data.local_status]||"Sin confirmar";badge.className="vsaas-badge "+data.local_status;
      const app=data.containers.find(c=>c.service==="app");by("vsaas-app").textContent=app?.state==="running"?(app.health==="unhealthy"?"Healthcheck con fallos":"En ejecución"):(app?.state||"No encontrada");
      by("vsaas-web").textContent=data.web?.valid?`Responde · ${data.web.latency_ms} ms`:"Sin respuesta confirmada";
      const db=data.internal?.database;by("vsaas-cameras").textContent=db?`${db.camera_total} / ${db.camera_enabled}`:"Sin confirmar";
      by("vsaas-health-status").textContent="Consulta: "+new Date(data.checked_at).toLocaleTimeString("es-MX")+" · abre el detalle para revisar las señales.";
    }catch(err){by("vsaas-health-status").textContent=err.problem==="access-denied"?"Activa el acceso administrativo y vuelve a actualizar.":"No se completó la consulta. "+(err.message||String(err));by("vsaas-health-badge").textContent="Desactualizado";by("vsaas-health-badge").className="vsaas-badge unknown";}
    finally{state.healthBusy=false;by("vsaas-health-refresh").disabled=false;}
  }
  async function interfaces(){
    try{
      const data=JSON.parse(await cockpit.spawn(["/usr/bin/python3","/usr/local/libexec/gateway-scanner.py","interfaces"],{err:"message"}));
      const select=by("vsaas-interface");select.replaceChildren();for(const net of data.interfaces){const option=make("option",`${net.name} · ${net.addresses.join(", ")}`);option.value=net.name;select.append(option);}
      if(data.interfaces.some(net=>net.name==="eth0"))select.value="eth0";
      select.disabled=!data.interfaces.length;by("vsaas-traffic-toggle").disabled=!data.interfaces.length;
      if(!data.interfaces.length)by("vsaas-traffic-status").textContent="Sin conexiones locales activas con IPv4.";
    }catch(err){by("vsaas-traffic-toggle").disabled=true;by("vsaas-traffic-status").textContent="No se pudieron consultar las conexiones. Abre Tráfico de red para revisarlas.";}
  }
  function graph(sample){
    if(![sample.timestamp,sample.rx_bytes,sample.tx_bytes].every(Number.isFinite))throw new Error("Lectura no válida");
    const previous=state.previous;state.previous=sample;if(!previous)return;
    const elapsed=sample.timestamp-previous.timestamp;if(elapsed<=0)return;
    const rx=Math.max(0,sample.rx_bytes-previous.rx_bytes)*8/elapsed/1e6,tx=Math.max(0,sample.tx_bytes-previous.tx_bytes)*8/elapsed/1e6;
    by("vsaas-rx").textContent=number.format(rx);by("vsaas-tx").textContent=number.format(tx);
    state.points.push({time:sample.timestamp,rx,tx});state.points=state.points.filter(p=>sample.timestamp-p.time<=60).slice(-61);
    const max=Math.max(1,...state.points.flatMap(p=>[p.rx,p.tx]))*1.1;
    for(const key of ["rx","tx"])by("vsaas-line-"+key).setAttribute("points",state.points.map(p=>`${598-(sample.timestamp-p.time)*596/60},${62-p[key]/max*58}`).join(" "));
    by("vsaas-traffic-status").textContent=by("vsaas-interface").value+" · últimos 60 s · tráfico total del puerto";
  }
  function stopTraffic(message="Detenido · se conservan las últimas lecturas"){
    const proc=state.process;state.process=null;state.runId++;state.buffer="";if(proc)proc.close("terminated");
    by("vsaas-traffic-toggle").textContent="Iniciar";by("vsaas-interface").disabled=!by("vsaas-interface").value;by("vsaas-traffic-badge").textContent="Detenido";by("vsaas-traffic-badge").className="vsaas-badge";by("vsaas-traffic-status").textContent=message;
  }
  function startTraffic(){
    if(state.process||!by("vsaas-interface").value||document.hidden||cockpit.hidden)return;
    state.previous=null;state.points=[];state.buffer="";by("vsaas-rx").textContent="—";by("vsaas-tx").textContent="—";for(const key of ["rx","tx"])by("vsaas-line-"+key).setAttribute("points","");
    const id=++state.runId,proc=cockpit.spawn(["/usr/bin/python3","-u","/usr/local/libexec/gateway-scanner.py","traffic-stream",by("vsaas-interface").value],{err:"message"});state.process=proc;
    by("vsaas-traffic-toggle").textContent="Detener";by("vsaas-interface").disabled=true;by("vsaas-traffic-badge").textContent="En vivo";by("vsaas-traffic-badge").className="vsaas-badge ok";by("vsaas-traffic-status").textContent="Preparando primera lectura…";
    proc.stream(chunk=>{if(id!==state.runId)return;state.buffer+=chunk;if(state.buffer.length>65536){stopTraffic("Lectura inesperada; vuelve a iniciar.");return;}let pos;try{while((pos=state.buffer.indexOf("\n"))>=0){const line=state.buffer.slice(0,pos);state.buffer=state.buffer.slice(pos+1);if(line.trim())graph(JSON.parse(line));}}catch(err){stopTraffic("No se pudo interpretar el tráfico.");}});
    proc.then(()=>{if(id===state.runId)stopTraffic("La medición terminó.");},()=>{if(id===state.runId)stopTraffic("Se interrumpió la medición; comprueba la conexión.");});
  }
  let cards;
  function mount(){
    const gallery=document.querySelector(".ct-system-overview");if(!gallery)return;
    if(!cards)cards=buildCards();
    for(const card of cards)if(!card.isConnected)gallery.append(card);
    if(!state.mounted){state.mounted=true;interfaces();}
  }
  function init(){
    if(typeof cockpit==="undefined")return;
    const root=document.getElementById("overview");if(!root)return;
    new MutationObserver(()=>{if(!cards?.every(c=>c.isConnected))mount();}).observe(root,{childList:true,subtree:true});mount();
    function hidden(){if((document.hidden||cockpit.hidden)&&state.process)stopTraffic("Detenido al salir de la vista global · pulsa Iniciar para continuar");}
    cockpit.addEventListener("visibilitychange",hidden);document.addEventListener("visibilitychange",hidden);window.addEventListener("pagehide",()=>{if(state.process)stopTraffic();});
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);else init();
})();
