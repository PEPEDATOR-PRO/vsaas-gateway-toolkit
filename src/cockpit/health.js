"use strict";
const get=id=>document.getElementById(id);
let lastData=null,busy=false,timer=null,request=null;
const labels={ok:"Correcto",warning:"Atención",critical:"Fallo",unknown:"Sin confirmar"};
function element(tag,text,className){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node;}
function size(bytes){if(!Number.isFinite(bytes))return"—";const units=["B","KB","MB","GB","TB"];let i=0;while(bytes>=1000&&i<units.length-1){bytes/=1000;i++;}return new Intl.NumberFormat("es-MX",{maximumFractionDigits:1}).format(bytes)+" "+units[i];}
function pair(list,label,value){const row=element("div");row.append(element("dt",label),element("dd",value));list.append(row);}
function render(data){
 const previous=lastData;lastData=data;
 const changes=new Map();for(const c of data.containers){const old=previous?.containers.find(o=>o.id===c.id);if(old&&c.restarts>old.restarts)changes.set(c.id,c.restarts-old.restarts);}
 const state=data.local_status==="ok"&&changes.size?"warning":data.local_status;
 get("summary").className="summary "+state;
 get("summary-title").textContent={ok:"Comprobaciones locales correctas",warning:"Hay puntos que requieren revisión",critical:"Se detectó un fallo local",unknown:"Diagnóstico local incompleto"}[state];
 get("summary-detail").textContent="VXG Cloud y video extremo a extremo siguen sin confirmar. Consulta el detalle de cada señal.";
 const app=data.containers.find(c=>c.service==="app");
 get("app").textContent=app?.state==="running"?"En ejecución":app?.state||"No encontrado";
 get("app-detail").textContent=app?"Salud Docker: "+app.health:"Revisar el stack de VXG";
 get("web").textContent=data.web?.valid?"Responde":data.web?"Revisar":"Sin confirmar";
 get("web-detail").textContent=data.web?.code?`HTTP ${data.web.code} · ${data.web.latency_ms??"—"} ms`:"No hay respuesta confirmada";
 const inside=data.internal;
 get("proxy").textContent=inside?String(inside.proxy_processes):"—";
 get("proxy-detail").textContent=inside?`${inside.proxy_tcp443??"—"} sockets TCP 443 · nube sin confirmar`:"No se pudo consultar la aplicación";
 get("cameras").textContent=inside?.database?String(inside.database.camera_total):"—";
 get("cameras-detail").textContent=inside?.database?`${inside.database.camera_enabled} habilitadas · video sin confirmar`:"Modelo de SQLite no confirmado";
 const rows=get("containers");rows.replaceChildren();
 for(const c of data.containers){
  const row=element("tr"),name=element("td");name.append(element("strong",c.service||c.name),element("small",c.name),element("small",c.image));row.append(name);
  const status=element("td",c.state);status.append(element("small","Healthcheck: "+c.health));row.append(status);
  row.append(element("td",c.stats?.CPUPerc||"—"),element("td",c.stats?.MemUsage||"—"));
  const restarts=element("td",String(c.restarts));if(changes.has(c.id))restarts.append(element("span",`+${changes.get(c.id)} desde la consulta anterior`,"changed"));row.append(restarts);rows.append(row);
 }
 if(!data.containers.length){const row=element("tr"),cell=element("td","No se encontraron contenedores VXG.","empty");cell.colSpan=5;row.append(cell);rows.append(row);}
 get("checks").replaceChildren();for(const c of data.checks){const row=element("div",undefined,"check-row");row.append(element("span",labels[c.status]||c.status,"pill "+c.status),element("span",c.label,"check-label"),element("span",c.detail,"check-detail"));get("checks").append(row);}
 const host=get("resources");host.replaceChildren();if(data.host){pair(host,"RAM utilizada",data.host.ram_used_percent+"%");pair(host,"RAM disponible",size(data.host.ram_available));pair(host,"Disco utilizado",data.host.disk_used_percent+"%");pair(host,"Disco disponible",size(data.host.disk_free));pair(host,"Tiempo de Ubuntu activo",Math.floor(data.host.uptime_seconds/3600)+" h");}else pair(host,"Recursos","Sin consultar");
 const logs=get("logs");logs.replaceChildren();pair(logs,"Archivos muestreados",String(inside?.logs?.files_sampled??"—"));
 const events=inside?.logs?.events||{},hasLogs=(inside?.logs?.files_sampled||0)>0;for(const [key,label]of [["auth","Señales de autenticación"],["disconnect","Señales de reconexión"],["error","Señales de error"],["established","Mensajes de WebSocket establecido"]])pair(logs,label,hasLogs?String(events[key]??0):"Sin muestra");
 get("notes").textContent=[...(data.notes||[]),...(inside?.notes||[])].join(" ");
 get("timestamp").textContent="Consulta: "+new Date(data.checked_at).toLocaleString("es-MX");get("export").disabled=false;
}
function visible(){return !document.hidden&&!cockpit.hidden;}
function schedule(){clearTimeout(timer);timer=null;if(get("auto").checked&&visible())timer=setTimeout(refresh,30000);}
async function refresh(){
 if(busy||!visible())return;busy=true;clearTimeout(timer);get("refresh").disabled=true;get("refresh").textContent="Comprobando…";get("error").hidden=true;get("status").textContent="Consultando Docker y comprobaciones locales. Puede tardar unos segundos…";
 try{
  const proc=cockpit.spawn(["/usr/bin/python3","/usr/local/libexec/vxg-health.py"],{superuser:"require",err:"message",environ:["LC_ALL=C"]});request=proc;
  const text=await proc;render(JSON.parse(text));get("status").textContent="Consulta terminada. No se modificó ni reinició ningún servicio.";
 }catch(err){get("error").hidden=false;get("error").textContent=err.problem==="access-denied"?"Activa el acceso administrativo de Cockpit y vuelve a comprobar.":err.message||String(err);get("status").textContent="No se completó la consulta. Los resultados anteriores pueden estar desactualizados.";}
 finally{request=null;busy=false;get("refresh").disabled=false;get("refresh").textContent="Comprobar ahora";schedule();}
}
function pause(){clearTimeout(timer);timer=null;get("auto").checked=false;if(request){const proc=request;request=null;proc.close("terminated");}}
get("refresh").addEventListener("click",refresh);get("auto").addEventListener("change",()=>{if(get("auto").checked)refresh();else{clearTimeout(timer);timer=null;}});
get("export").addEventListener("click",()=>{if(!lastData)return;const blob=new Blob([JSON.stringify(lastData,null,2)],{type:"application/json"});const url=URL.createObjectURL(blob),a=element("a");a.href=url;a.download="salud-vxg-"+new Date().toISOString().slice(0,10)+".json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
cockpit.addEventListener("visibilitychange",()=>{if(cockpit.hidden)pause();});document.addEventListener("visibilitychange",()=>{if(document.hidden)pause();});window.addEventListener("pagehide",pause);
