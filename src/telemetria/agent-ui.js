"use strict";
const by=id=>document.getElementById(id),el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
let config=null,process=null,generation=0;
function saveMessage(text){by("status").textContent=text;by("save-status").textContent=text;}
function field(parent,label,value,type="text"){const wrap=el("label",label),input=el("input");input.type=type;if(type==="checkbox")input.checked=value;else input.value=value||"";if(type==="password")input.autocomplete="new-password";wrap.append(input);parent.append(wrap);return input;}
function addDestination(dest={id:crypto.randomUUID(),name:"",url:"",enabled:true}){
 const row=el("div");row.className="destination";row.dataset.id=dest.id;
 const name=field(row,"Nombre del destino",dest.name);name.dataset.field="name";name.required=true;name.maxLength=80;
 const url=field(row,"URL (protocolo, IP/host, puerto y path)",dest.url,"url");url.dataset.field="url";url.required=true;
 const source=field(row,"IP de origen opcional (si la ruta IPsec requiere la IP VPN de este Gateway)",dest.source_ip||"");source.dataset.field="source_ip";
 const token=field(row,"","","password");token.dataset.field="token";
 const tokenHint=el("span");token.parentNode.prepend(tokenHint);
 const updateHint=()=>{const retained=dest.has_token&&url.value.trim()===dest.url;token.required=!retained;token.minLength=24;tokenHint.textContent=retained?"Llave guardada · deja vacío para conservarla":"Llave de envío del equipo · requerida (no es la llave administrativa del panel)";};
 updateHint();url.addEventListener("input",updateHint);
 const enabled=field(row,"Enviar a este destino",dest.enabled,"checkbox");enabled.dataset.field="enabled";
 const remove=el("button","Eliminar destino");remove.type="button";remove.className="secondary";remove.addEventListener("click",()=>row.remove());row.append(remove);by("destinations").append(row);
}
function hide(){generation++;if(process)process.close("terminated");process=null;by("load").disabled=false;by("save").disabled=false;document.querySelectorAll('input[type="password"]').forEach(n=>n.value="");}
async function command(action,input){const proc=cockpit.spawn(["/usr/bin/python3","/usr/local/libexec/vsaas-telemetria/agent.py",action],{superuser:"require",err:"message"});process=proc;if(input!==undefined)proc.input(JSON.stringify(input));return await proc;}
async function load(){if(process||document.hidden||cockpit.hidden)return;const id=++generation;by("load").disabled=true;try{const data=JSON.parse(await command("config"));if(id!==generation)return;config=data.config;by("identity").textContent=config.device_id;by("name").value=config.name;by("interval").value=config.interval;by("enabled").checked=config.enabled;by("destinations").replaceChildren();config.destinations.forEach(addDestination);by("settings").hidden=false;
 const status=data.status;by("delivery").textContent=status.checked_at?"Último ciclo: "+new Date(status.checked_at*1000).toLocaleString()+"\n"+((status.deliveries||[]).length?(status.deliveries||[]).map(d=>{const dest=config.destinations.find(n=>n.id===d.id);return (dest?.name||d.id)+": "+(d.ok?"Recibido por HTTP "+d.http:"Sin entrega confirmada"+(d.http?" · HTTP "+d.http+(d.http===401?" · revisa el registro del equipo y su llave de envío":""):""));}).join("\n"):!config.enabled?"Envío periódico desactivado.":!config.destinations.some(d=>d.enabled)?"Sin destinos activos.":"Aún sin entregas registradas. Espera el siguiente ciclo y vuelve a consultar."):"Aún no hay un ciclo registrado.";
 by("status").textContent="Configuración consultada. El servicio inicia desactivado hasta que guardes su activación.";
 }catch(e){if(id===generation)by("status").textContent=e.problem==="access-denied"?"Activa el acceso administrativo.":"No se pudo consultar. Instala el módulo telemetria y vuelve a intentar.";}finally{if(id===generation){process=null;by("load").disabled=false;}}}
by("settings").addEventListener("invalid",()=>saveMessage("No se guardó: revisa los campos requeridos. Para un destino nuevo registra primero el equipo en el colector y pega su llave de envío."),true);
by("settings").addEventListener("submit",async e=>{e.preventDefault();if(process||!config)return;const id=++generation;by("save").disabled=true;saveMessage("Guardando configuración…");
 try{const destinations=[...by("destinations").children].map(row=>{const d={id:row.dataset.id};for(const key of ["name","url","source_ip","token","enabled"]){const input=row.querySelector(`[data-field="${key}"]`);d[key]=key==="enabled"?input.checked:input.value.trim();}return d;});await command("save",{device_id:config.device_id,name:by("name").value.trim(),interval:Number(by("interval").value),enabled:by("enabled").checked,destinations});if(id!==generation)return;
 document.querySelectorAll('input[type="password"]').forEach(n=>n.value="");
 saveMessage("Guardado. Verificando la configuración almacenada…");
 try{const verified=JSON.parse(await command("config"));if(id!==generation)return;config=verified.config;by("destinations").replaceChildren();config.destinations.forEach(addDestination);saveMessage("Guardado y verificado. La llave se retira de pantalla y queda almacenada en el Gateway. Esto aún no confirma la entrega; consulta el último ciclo.");}
 catch(error){if(id===generation)saveMessage("El Gateway confirmó el guardado, pero no se pudo releer. Pulsa Consultar configuración para verificarlo.");}
 }catch(e){if(id===generation)saveMessage("No se guardó: "+(e.message||String(e)));}finally{if(id===generation){process=null;by("save").disabled=false;}}});
by("load").addEventListener("click",load);by("add").addEventListener("click",()=>{if(by("destinations").children.length<8)addDestination();else by("status").textContent="Máximo ocho destinos.";});cockpit.addEventListener("visibilitychange",()=>{if(cockpit.hidden)hide();});document.addEventListener("visibilitychange",()=>{if(document.hidden)hide();});window.addEventListener("pagehide",hide);
