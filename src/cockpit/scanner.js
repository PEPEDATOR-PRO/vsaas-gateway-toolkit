/* Uses Cockpit's authenticated bridge. No separate HTTP API or daemon. */
"use strict";
const $ = id => document.getElementById(id);
const state = {devices: [], iface: "", lastScan: "", busy: false, checking: new Set()};
const serviceLabels = {80:"HTTP",443:"HTTPS",554:"RTSP",8000:"TCP 8000",8080:"HTTP alternativo"};

function run(args, privileged = false) {
  return cockpit.spawn(["/usr/bin/python3", "/usr/local/libexec/gateway-scanner.py", ...args], {
    superuser: privileged ? "require" : undefined, err: "message", environ: ["LC_ALL=C"]
  }).then(text => JSON.parse(text));
}
function errorMessage(err) {
  if (err.problem === "access-denied") return "Activa el acceso administrativo en Cockpit y vuelve a intentarlo.";
  return err.message || String(err);
}
function showError(err) { $("error").textContent = errorMessage(err); $("error").hidden = false; }
function controls(busy) {
  state.busy = busy;
  $("scan").disabled = busy || !$("interface").value;
  $("reload").disabled = busy;
  $("interface").disabled = busy || !$("interface").value;
  $("scan").textContent = busy ? "Buscando…" : "Buscar equipos";
}
async function loadInterfaces() {
  $("error").hidden = true;
  controls(true);
  try {
    const data = await run(["interfaces"]);
    $("interface").replaceChildren();
    for (const net of data.interfaces) {
      const option = document.createElement("option");
      option.value = net.name;
      option.textContent = `${net.name} · ${net.addresses.join(", ")}`;
      $("interface").append(option);
    }
    if (data.interfaces.some(net => net.name === "eth0")) $("interface").value = "eth0";
    $("status").textContent = data.interfaces.length ? "Listo para buscar equipos en la conexión seleccionada." : "No hay conexiones locales activas con dirección IPv4.";
  } catch (err) { showError(err); $("status").textContent = "No se pudieron cargar las conexiones."; }
  finally { controls(false); }
}
function cell(row, text) { const td = document.createElement("td"); td.textContent = text; row.append(td); return td; }
function render() {
  const query = $("filter").value.trim().toLowerCase();
  const shown = state.devices.filter(d => `${d.ip} ${d.mac} ${d.vendor}`.toLowerCase().includes(query));
  $("rows").replaceChildren();
  $("count").textContent = query ? `${shown.length} de ${state.devices.length} equipos` : `${state.devices.length} equipos`;
  $("export").disabled = !state.devices.length;
  if (!shown.length) {
    const tr = document.createElement("tr"); const td = cell(tr, query ? "No hay coincidencias." : "No se encontraron equipos en el último escaneo.");
    td.colSpan = 4; td.className = "empty"; $("rows").append(tr); return;
  }
  for (const device of shown) {
    const tr = document.createElement("tr");
    cell(tr, device.ip); cell(tr, device.mac); cell(tr, device.vendor || "No identificado");
    const services = cell(tr, "");
    if (device.ports) {
      const label = document.createElement("span"); label.className = "ports";
      label.textContent = device.ports.length ? device.ports.map(p => `${p} · ${serviceLabels[p] || "TCP"}`).join(" / ") : "Sin puertos abiertos en la prueba";
      services.append(label);
    }
    const button = document.createElement("button"); button.className = "secondary";
    button.textContent = state.checking.has(device.ip) ? "Comprobando…" : "Comprobar servicios";
    button.disabled = state.busy || state.checking.size > 0;
    button.addEventListener("click", () => checkPorts(device)); services.append(button);
    $("rows").append(tr);
  }
}
async function scan() {
  const iface = $("interface").value;
  if (!iface || state.busy || state.checking.size) return;
  $("error").hidden = true; controls(true); render();
  $("status").textContent = `Buscando equipos en ${iface}…`;
  try {
    const data = await run(["scan", iface], true);
    state.devices = data.devices; state.iface = iface;
    state.lastScan = new Date().toLocaleString("es-MX");
    $("time").textContent = `Último escaneo: ${state.lastScan}`;
    $("raw").textContent = data.raw + (data.warnings ? "\n\nAvisos:\n" + data.warnings : "");
    $("status").textContent = `${data.devices.length} equipos encontrados en ${iface} · ${data.elapsed}s. Los resultados son del último escaneo.`;
  } catch (err) {
    showError(err); $("status").textContent = "El escaneo no terminó. Se conservan los resultados anteriores, si los hay.";
  } finally { controls(false); render(); }
}
async function checkPorts(device) {
  state.checking.add(device.ip); $("error").hidden = true; $("scan").disabled = true; $("reload").disabled = true; render();
  try { const result = await run(["ports", state.iface, device.ip], true); device.ports = result.ports; }
  catch (err) { showError(err); }
  finally { state.checking.delete(device.ip); controls(false); render(); }
}
function csvValue(value) {
  let text = String(value ?? "");
  if (/^[=+@\-\t\r]/.test(text)) text = "'" + text;
  return '"' + text.replaceAll('"','""') + '"';
}
function exportCsv() {
  const rows = [["IP","MAC","Fabricante","Puertos TCP abiertos","Interfaz","Escaneado"]];
  for (const d of state.devices) rows.push([d.ip,d.mac,d.vendor,d.ports ? d.ports.join(" ") : "No comprobados",state.iface,state.lastScan]);
  const blob = new Blob(["\ufeff" + rows.map(row => row.map(csvValue).join(",")).join("\r\n")], {type:"text/csv;charset=utf-8"});
  const url = URL.createObjectURL(blob); const a = document.createElement("a");
  a.href = url; a.download = `equipos-${state.iface}-${new Date().toISOString().slice(0,10)}.csv`; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$("scan").addEventListener("click", scan);
$("reload").addEventListener("click", loadInterfaces);
$("filter").addEventListener("input", render);
$("export").addEventListener("click", exportCsv);
loadInterfaces();
