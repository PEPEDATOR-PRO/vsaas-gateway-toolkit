"use strict";
const by=id=>document.getElementById(id);
let request=null,generation=0;
function hide(){generation++;const process=request;request=null;if(process)process.close("terminated");by("refresh").disabled=false;}
async function refresh(){
 if(request||document.hidden||cockpit.hidden)return;
 const id=++generation;by("refresh").disabled=true;by("open").hidden=true;by("status").textContent="Consultando el colector…";
 try{
  request=cockpit.spawn(["/usr/local/bin/vsaas-eventos","estado","--json"],{superuser:"require",err:"message"});
  const data=JSON.parse(await request);if(id!==generation)return;
  by("container").textContent=data.state||"Sin confirmar";by("health").textContent=data.health||"Sin confirmar";by("response").textContent=data.responds?"Responde":"Sin respuesta confirmada";by("restarts").textContent=data.restarts??"—";
  const healthy=data.responds&&data.state==="running"&&data.health!=="unhealthy";
  by("badge").textContent=!data.installed?"No instalado":healthy?"En ejecución":"Revisar";by("badge").className=healthy?"ok":"warning";
  // The URL comes from a locally validated profile, never from camera metadata.
  if(typeof data.url==="string"&&/^http:\/\/(?:\d{1,3}\.){3}\d{1,3}:8081$/.test(data.url)){
   by("open").href=data.url;by("open").hidden=false;
  }
  by("status").textContent=data.installed?"Consulta terminada. Abre el panel para revisar cámaras, eventos y almacenamiento.":"Instala el módulo opcional: sudo python3 scripts/install.py eventos";
 }catch(error){if(id===generation){by("badge").textContent="Sin confirmar";by("badge").className="warning";by("status").textContent=error.problem==="access-denied"?"Activa el acceso administrativo de Cockpit y vuelve a consultar.":"No se pudo consultar el colector. Comprueba que el módulo eventos esté instalado.";}}
 finally{if(id===generation){request=null;by("refresh").disabled=false;}}
}
by("refresh").addEventListener("click",refresh);
cockpit.addEventListener("visibilitychange",()=>{if(cockpit.hidden)hide();});
document.addEventListener("visibilitychange",()=>{if(document.hidden)hide();});window.addEventListener("pagehide",hide);
