"use strict";
const by=id=>document.getElementById(id),el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
let key="",timer=null,busy=false,controller=null;
const fmt=value=>value===null||value===undefined?"Sin confirmar":new Intl.NumberFormat("es-MX",{maximumFractionDigits:1}).format(value);
const level=value=>({ok:"Correcto local",warning:"Revisar",critical:"Fallo local",unknown:"Sin confirmar"}[value]||"Sin confirmar");
async function api(path,data){const response=await fetch(path,{method:data?"POST":"GET",headers:{Authorization:"Bearer "+key,...(data?{"Content-Type":"application/json"}:{})},...(data?{body:JSON.stringify(data)}:{}),signal:controller?.signal});const result=await response.json();if(!response.ok){if(response.status===401)logout();throw new Error(result.error||"No se completó la solicitud.");}return result;}
function row(dl,label,value){const div=el("div");div.append(el("dt",label),el("dd",String(value)));dl.append(div);}
function showKey(result){by("new-key").textContent="Equipo: "+result.id+"\nLlave de envío (cópiala ahora en el destino de Cockpit):\n"+result.token;by("new-key").hidden=false;}
function render(data){
 by("summary").textContent=`${data.devices.filter(d=>d.state==="online").length} con reportes · ${data.devices.filter(d=>d.state==="offline").length} sin reportes · ${data.devices.length} registrados`;
 const editing=by("devices").contains(document.activeElement)&&document.activeElement.matches("input");
 if(!editing){by("devices").replaceChildren();
 for(const d of data.devices){const card=el("article",undefined,"device"),head=el("div",undefined,"heading");head.append(el("h2",d.name),el("span",{online:"Con reportes",offline:"Sin reportes · revisar",pending:"Esperando primer reporte"}[d.state],"badge "+d.state));card.append(head);
 const report=d.report,details=el("dl");if(report){const stats=el("div",undefined,"stats"+(d.state!=="online"?" stale":""));for(const [label,value]of [["CPU",report.cpu_percent],["Memoria",report.ram_percent],["Disco",report.disk_percent]]){const box=el("div",undefined,"stat");box.append(el("span",label),el("strong",value==null?"—":fmt(value)+" %"));stats.append(box);}card.append(stats);
 row(details,"Salud Vsaas",level(report.health.vsaas));row(details,"VPN",level(report.health.vpn));row(details,"Cámaras configuradas / habilitadas",fmt(report.health.cameras_configured)+" / "+fmt(report.health.cameras_enabled));row(details,"Contenedores activos / detectados",fmt(report.health.containers_running)+" / "+fmt(report.health.containers_total));row(details,"Temperatura",fmt(report.temperature_c)+(report.temperature_c==null?"":" °C"));row(details,"Tiempo encendido",fmt(report.uptime_seconds/3600)+" h");
 for(const net of report.network){row(details,net.name,net.addresses.join(", "));row(details,net.name+" · recepción / envío",fmt(net.rx_mbps)+" / "+fmt(net.tx_mbps)+" Mb/s");}
 }else card.append(el("p","Todavía no se ha recibido un reporte de este equipo."));
 row(details,"Última recepción",d.received_at?new Date(d.received_at*1000).toLocaleString():"Nunca");row(details,"Tiempo sin reportes",fmt(d.age_seconds)+" s");row(details,"ID",d.id);card.append(details);
 const actions=el("div",undefined,"actions"),timeout=el("input");timeout.type="number";timeout.min="60";timeout.max="86400";timeout.value=d.timeout;timeout.setAttribute("aria-label","Tiempo de alerta de "+d.name);timeout.className="threshold";
 const save=el("button","Guardar umbral","secondary");save.addEventListener("click",async()=>{try{await api('/api/device-settings',{id:d.id,name:d.name,timeout:Number(timeout.value)});by("message").textContent="Umbral actualizado.";await refresh();}catch(e){by("message").textContent=e.message;}});
 const rotate=el("button","Renovar llave","secondary");rotate.addEventListener("click",async()=>{if(!confirm("La llave anterior dejará de funcionar. Deberás actualizar este destino en el Gateway. ¿Continuar?"))return;try{showKey(await api('/api/rotate',{id:d.id}));by("new-key").scrollIntoView();}catch(e){by("message").textContent=e.message;}});actions.append(timeout,save,rotate);card.append(actions);by("devices").append(card);
 }
 }
 by("alerts").replaceChildren();for(const a of data.alerts){const tr=el("tr");for(const text of [new Date(a.at*1000).toLocaleString(),a.name,{offline:"Sin reportes",recovered:"Reportes recuperados",first_report:"Primer reporte recibido"}[a.state]||a.state])tr.append(el("td",text));by("alerts").append(tr);}
 by("storage").textContent=`Base: ${fmt(data.database_bytes/1024/1024)} MiB · ${data.samples} muestras · retención: hasta 7 días o 10 000 muestras totales y 1 000 avisos; máximo de base 256 MiB más diario temporal.`;
}
async function refresh(){if(!key||busy||document.hidden)return;busy=true;controller=new AbortController();try{render(await api('/api/status'));by("message").textContent="Actualizado: "+new Date().toLocaleTimeString();}catch(e){if(e.name!=="AbortError")by("message").textContent="El colector no responde: "+e.message+" Los estados mostrados no están actualizados.";}finally{busy=false;controller=null;}}
function stop(){clearInterval(timer);timer=null;if(controller)controller.abort();}
function start(){stop();if(key&&!document.hidden){refresh();timer=setInterval(refresh,5000);}}
function logout(){stop();key="";by("panel").hidden=true;by("login").hidden=false;by("devices").replaceChildren();by("alerts").replaceChildren();by("new-key").textContent="";by("new-key").hidden=true;}
by("login-form").addEventListener("submit",async e=>{e.preventDefault();key=by("admin-key").value;by("admin-key").value="";try{render(await api('/api/status'));by("login").hidden=true;by("panel").hidden=false;start();}catch(err){by("message").textContent=err.message;}});
by("register").addEventListener("submit",async e=>{e.preventDefault();try{showKey(await api('/api/devices',{id:by("device-id").value.trim(),name:by("device-name").value.trim(),timeout:Number(by("device-timeout").value)}));await refresh();}catch(err){by("message").textContent=err.message;}});
by("refresh").addEventListener("click",refresh);by("logout").addEventListener("click",logout);document.addEventListener("visibilitychange",()=>document.hidden?stop():start());window.addEventListener("pagehide",stop);
