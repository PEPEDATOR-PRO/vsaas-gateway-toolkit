'use strict';
const $ = selector => document.querySelector(selector);
const message = text => { $('#message').textContent = text; };
const MAX_VISIBLE = 500;
let token = '', names = {}, page = [], selectedEvent = null;
let connected = false, paused = false, initialized = false, lastId = 0, generation = 0;
let pollBusy = false, loadsInFlight = 0, olderBusy = false, lastUpdate = null;
let filters = {camera: '', topic: ''};
let canManage = false;
let forwardingLoaded=false;
const capabilityBusy = new Set();
let capabilityReport = null, capabilityRequest = 0;

function capabilityBlock(title, values, parent = $('#capabilities-result')) {
  const heading = document.createElement('h3'), list = document.createElement('ul');
  heading.textContent = title;
  for (const value of values) {
    const item = document.createElement('li'); item.textContent = value; list.append(item);
  }
  parent.append(heading, list);
}
async function inspectCapabilities(camera) {
  if (capabilityBusy.has(camera.id) || document.hidden) return;
  capabilityBusy.add(camera.id);
  const request = ++capabilityRequest;
  capabilityReport = null;
  $('#capabilities-panel').hidden = false;
  $('#capabilities-download').hidden = true;
  $('#capabilities-result').replaceChildren();
  $('#capabilities-title').textContent = 'Capacidades · ' + camera.name;
  $('#capabilities-status').textContent = 'Consultando al equipo… Puede tardar alrededor de un minuto. El colector continúa recibiendo eventos.';
  $('#capabilities-panel').scrollIntoView?.({behavior: 'smooth', block: 'start'});
  try {
    const report = await api('/api/cameras/' + camera.id + '/capabilities', {method: 'POST'});
    if (request !== capabilityRequest) return;
    capabilityReport = report;
    $('#capabilities-status').textContent = 'Consulta finalizada · ' + new Date(report.checked_at).toLocaleString();
    capabilityBlock('Resumen', report.summary);
    if (Object.keys(report.device).length) capabilityBlock('Equipo', Object.entries(report.device).map(([key, value]) => ({Manufacturer:'Fabricante',Model:'Modelo',FirmwareVersion:'Firmware'}[key] || key) + ': ' + value));
    capabilityBlock('Eventos anunciados por la cámara', report.event_topics.length ? report.event_topics.map(topic => topic.topic + (topic.properties.length ? ' · ' + topic.properties.map(p => p.group + ': ' + p.name + (p.type ? ' (' + p.type + ')' : '')).join(', ') : '')) : ['No confirmados por esta consulta.']);
    capabilityBlock('Campos de metadatos anunciados (muestra ONVIF)', report.metadata_fields.length ? report.metadata_fields : ['No se obtuvo una muestra de campos.']);
    capabilityBlock('Datos realmente recibidos · últimos ' + report.observed.sample_count + ' eventos', [...report.observed.topics.map(t => 'Evento: ' + t), ...report.observed.fields].length ? [...report.observed.topics.map(t => 'Evento: ' + t), ...report.observed.fields] : ['Sin muestras disponibles.']);
    capabilityBlock('Alcance del resultado', report.limitations);
    const heading = document.createElement('h3'); heading.textContent = 'Respuestas de las consultas'; $('#capabilities-result').append(heading);
    for (const query of report.queries) {
      const details = document.createElement('details'), summary = document.createElement('summary'), pre = document.createElement('pre');
      summary.textContent = query.operation + ' · ' + query.status;
      pre.textContent = query.response || query.detail || 'Sin respuesta';
      if (query.truncated) pre.textContent += '\n[Respuesta recortada a 64 KiB]';
      details.append(summary, pre); $('#capabilities-result').append(details);
    }
    $('#capabilities-download').hidden = false;
  } catch (error) {
    if (request === capabilityRequest) $('#capabilities-status').textContent = 'No se pudo completar la consulta: ' + error.message;
  } finally {
    capabilityBusy.delete(camera.id);
  }
}
$('#capabilities-close').onclick = () => { ++capabilityRequest; capabilityReport = null; $('#capabilities-panel').hidden = true; };
$('#capabilities-download').onclick = () => {
  if (!capabilityReport) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(capabilityReport, null, 2)], {type: 'application/json'}));
  const link = document.createElement('a'); link.href = url; link.download = 'capacidades-' + capabilityReport.camera_id + '.json'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};

function syncConnection() {
  const onvif = $('#mode').value === 'onvif', https = $('#camera-protocol').value === 'https';
  $('#protocol-field').hidden = !onvif;
  $('#camera-protocol').disabled = !onvif;
  $('#certificate-field').hidden = !onvif || !https;
  $('[name="verify_tls"]').disabled = !onvif || !https;
  $('[name="device_url"]').placeholder = https ? '192.168.1.100:443' : '192.168.1.100:80';
}
$('#camera-protocol').onchange = () => {
  const address = $('[name="device_url"]');
  address.value = address.value.replace(/^https?:\/\//i, $('#camera-protocol').value + '://');
  syncConnection();
};
$('[name="device_url"]').oninput = () => {
  const match = $('[name="device_url"]').value.trim().match(/^(https?):\/\//i);
  if (match) $('#camera-protocol').value = match[1].toLowerCase();
  syncConnection();
};
$('#mode').onchange = syncConnection;
syncConnection();

async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {
    'Content-Type': 'application/json', Authorization: 'Bearer ' + token, ...options.headers
  }});
  if (!response.ok) {
    const error = await response.json();
    throw Error(typeof error.detail === 'string' ? error.detail : JSON.stringify(error.detail));
  }
  return response.json();
}
function feedError(text = '') {
  $('#feed-error').textContent = text;
  $('#feed-error').hidden = !text;
}
function updateLiveStatus() {
  $('#pause').disabled = !connected;
  $('#load').disabled = !connected || loadsInFlight > 0;
  $('#export').disabled = !page.length;
  $('#pause').textContent = paused ? 'Reanudar vista' : 'Pausar vista';
  $('#pause').setAttribute('aria-pressed', String(paused));
  $('#older').disabled = !connected || !page.length || loadsInFlight > 0 || olderBusy || page.length >= MAX_VISIBLE;
  $('#visible-count').textContent = page.length + ' visibles';
  $('#live-status').textContent = !connected ? 'Conecta tu acceso para ver los eventos.'
    : paused ? 'En pausa · El colector sigue guardando eventos.'
    : 'En vivo · Actualización cada segundo' + (lastUpdate ? ' · ' + lastUpdate.toLocaleTimeString() : '');
}
function queryEvents(values = {}) {
  const query = new URLSearchParams({limit: '100', include_raw: 'false', ...values});
  if (filters.camera) query.set('camera_id', filters.camera);
  if (filters.topic) query.set('topic', filters.topic);
  return '/api/events?' + query;
}
function cell(row, value) {
  const td = document.createElement('td'); td.textContent = value ?? '—'; row.append(td); return td;
}
async function refresh() {
  const status = await api('/api/status');
  canManage = status.access_role !== 'viewer';
  if (!canManage) {
    ++capabilityRequest; capabilityReport = null;
    $('#capabilities-panel').hidden = true;
    $('#capabilities-result').replaceChildren();
  }
  $('#camera-management').hidden = !canManage;
  $('#access-note').textContent = canManage ? 'Acceso de administración.' : 'Solo consulta · Puedes ver y descargar eventos. La configuración de cámaras está protegida.';
  $('#total').textContent = status.events + ' eventos en la cola local';
  await refreshForwarding();
  const disk=status.storage;
  $('#storage-status').textContent=disk?(disk.blocked?'Espacio libre insuficiente o lote demasiado grande. ':'')+'Base y diario: '+(disk.bytes/1e6).toFixed(1)+' MB'+(disk.limit_bytes?' · Máximo total: '+(disk.limit_bytes/1e9).toFixed(2)+' GB':'')+(disk.database_limit_bytes?' · Capacidad de base: '+(disk.database_limit_bytes/1e6).toFixed(0)+' MB (resto reservado para recuperación)':'')+' · Libres en disco: '+(disk.free_bytes/1024**3).toFixed(1)+' GiB.':'';
  $('#cameras').replaceChildren();
  const cameraFilter = $('#filter'), previous = cameraFilter.value;
  const available = new Set(status.cameras.map(camera => camera.id));
  cameraFilter.replaceChildren(new Option('Todas las cámaras', '')); names = {};
  for (const camera of status.cameras) {
    names[camera.id] = camera.name;
    cameraFilter.add(new Option(camera.name, camera.id));
    const row = document.createElement('tr'); cell(row, camera.name); cell(row, camera.mode);
    cell(row, camera.status + (camera.last_error ? ' · ' + camera.last_error : ''));
    if (camera.metadata_enabled) {
      const state = document.createElement('small');
      state.textContent = 'Metadatos IA: ' + (camera.metadata_status || 'pendiente')
        + (camera.metadata_last_error ? ' · ' + camera.metadata_last_error : '');
      state.style = 'display:block;margin-top:6px';
      row.children[2].append(state);
    }
    cell(row, camera.last_seen ? new Date(camera.last_seen).toLocaleString() : null);
    const remove = document.createElement('button'); remove.textContent = 'Quitar';
    remove.onclick = async () => {
      if (!confirm('¿Quitar esta cámara? Se conserva el historial.')) return;
      try { await api('/api/cameras/' + camera.id, {method: 'DELETE'}); await refresh(); }
      catch (error) { message(error.message); }
    };
    const actions = cell(row, '');
    if (canManage) {
      const inspect = document.createElement('button');
      inspect.className = 'secondary'; inspect.textContent = capabilityBusy.has(camera.id) ? 'Consultando…' : 'Consultar capacidades';
      inspect.disabled = capabilityBusy.has(camera.id);
      inspect.onclick = async () => {
        inspect.disabled = true; inspect.textContent = 'Consultando…';
        try { await inspectCapabilities(camera); }
        finally { inspect.disabled = false; inspect.textContent = 'Consultar capacidades'; }
      };
      actions.append(inspect);
      if (camera.mode === 'onvif') {
        const metadata = document.createElement('button');
        metadata.className = 'secondary'; metadata.textContent = 'Metadatos IA';
        metadata.onclick = async () => {
          const url = prompt('URL RTSP del mismo equipo para recibir metadatos ONVIF. Deja vacío para desactivar.', camera.metadata_rtsp_url || 'rtsp://' + new URL(camera.device_url).hostname + ':554/LiveChannel/0/media.smp');
          if (url === null) return;
          metadata.disabled = true;
          try {
            await api('/api/cameras/' + camera.id + '/metadata', {method: 'PUT', body: JSON.stringify({metadata_rtsp_url: url})});
            message(url.trim() ? 'Recepción de metadatos activada. Revisa el estado IA/RTSP del equipo.' : 'Recepción de metadatos RTSP desactivada.');
            await refresh();
          } catch (error) { message(error.message); }
          finally { metadata.disabled = false; }
        };
        actions.append(metadata);
      }
      actions.append(remove);
    }
    $('#cameras').append(row);
  }
  if (previous && !available.has(previous)) cameraFilter.add(new Option('Cámara retirada · ' + previous, previous));
  cameraFilter.value = previous;
}
function renderEvents(preserveScroll = true, insertedAtTop = true) {
  const list = $('#events'), oldTop = list.scrollTop, oldHeight = list.scrollHeight;
  list.replaceChildren();
  for (const event of page) {
    const button = document.createElement('button'); button.className = 'event-item';
    button.dataset.eventId = String(event.id);
    button.setAttribute('aria-pressed', String(selectedEvent?.id === event.id));
    const top = document.createElement('span'), id = document.createElement('span'), time = document.createElement('time');
    top.className = 'event-top'; id.textContent = '#' + event.id;
    time.dateTime = event.received_at; time.textContent = new Date(event.received_at).toLocaleString(); top.append(id, time);
    const topic = document.createElement('span'), camera = document.createElement('span');
    topic.className = 'event-topic'; topic.textContent = event.topic;
    camera.className = 'event-camera'; camera.textContent = names[event.camera_id] || event.camera_id;
    button.append(top, topic, camera); button.onclick = () => selectEvent(event); list.append(button);
  }
  if (!page.length) {
    const empty = document.createElement('p'); empty.className = 'empty';
    empty.textContent = 'Sin eventos para este filtro. Los nuevos aparecerán aquí.'; list.append(empty);
  }
  list.scrollTop = preserveScroll && oldTop > 20 ? oldTop + (insertedAtTop ? Math.max(0, list.scrollHeight - oldHeight) : 0) : 0;
  updateLiveStatus();
}
// A compact view only: the database and original XML remain untouched.
function simplifyEvent(event) {
  const meta = event.metadata || {};
  const scalar = value => value === 'true' ? true : value === 'false' ? false : value;
  const attributes = tree => {
    const result = Object.create(null);
    const labels = {Gender: 'sexo', Age: 'edad', AgeType: 'edad', VehicleType: 'tipo_vehiculo',
      PlateNumber: 'matricula', LicensePlate: 'matricula', Plate: 'matricula', Make: 'marca', Model: 'modelo'};
    const translations = {Black: 'negro', White: 'blanco', Red: 'rojo', Blue: 'azul', Green: 'verde',
      Yellow: 'amarillo', Gray: 'gris', Grey: 'gris', Brown: 'cafe', Orange: 'naranja', Purple: 'morado',
      Pink: 'rosa', Female: 'femenino', Male: 'masculino', Long: 'larga', Short: 'corta'};
    const add = (path, value) => {
      const parts = path.split('.'), leaf = parts.at(-1);
      let key = labels[leaf];
      const garment = parts.includes('Tops') ? 'ropa_superior' : parts.includes('Bottoms') ? 'ropa_inferior' : null;
      if (leaf === 'ColorString') key = garment ? garment + '_color' : 'color';
      if (leaf === 'Length' && garment) key = garment + '_largo';
      if (leaf === 'Wear') {
        const accessory = parts.includes('Hat') ? 'gorra' : parts.includes('Bag') ? 'bolsa'
          : parts.includes('Mask') ? 'mascarilla' : parts.includes('Glasses') ? 'lentes' : null;
        key = accessory;
      }
      if (!key || value === '' || value === 'Unknown') return;
      const clean = translations[value] || scalar(value);
      if (!Object.hasOwn(result, key)) result[key] = clean;
      else if (![].concat(result[key]).includes(clean)) result[key] = [].concat(result[key], clean);
    };
    const walk = (node, path) => {
      const tag = (node.tag || '').split('}').pop();
      const here = [...path, tag];
      if (node.text != null && node.text !== '') add(here.join('.'), node.text);
      for (const [key, value] of Object.entries(node.attributes || {})) add([...here, key].join('.'), value);
      for (const child of node.children || []) walk(child, here);
    };
    // Classification, ID and bounding box already have dedicated fields.
    const visit = node => {
      const tag = (node.tag || '').split('}').pop();
      if (['Class', 'Shape'].includes(tag)) return;
      if (['Object', 'Appearance'].includes(tag)) {
        for (const child of node.children || []) visit(child);
      } else walk(node, []);
    };
    if (tree) visit(tree);
    return result;
  };
  const output = {id: event.id, equipo: names[event.camera_id] || event.camera_id,
    fecha: event.source_time || event.received_at, evento: event.topic};
  const channel = meta.rtsp_source?.match(/\/LiveChannel\/(\d+)\//i);
  if (channel) output.canal = Number(channel[1]) + 1;
  if (Array.isArray(meta.objects)) {
    output.evento = 'objetos_detectados';
    output.objetos = meta.objects.map(object => {
      const best = [...(object.classes || [])].sort((a, b) => Number(b.likelihood || 0) - Number(a.likelihood || 0))[0];
      const value = {id: object.object_id};
      if (best) {
        value.tipo = ({Human: 'persona', Person: 'persona', Vehicle: 'vehiculo', Face: 'rostro', LicensePlate: 'matricula'})[best.type] || best.type;
        if (best.likelihood != null && best.likelihood !== '' && Number.isFinite(Number(best.likelihood))) value.confianza = Number(best.likelihood);
      }
      Object.assign(value, attributes(object.details));
      return value;
    });
  } else if (meta.groups) {
    output.datos = Object.fromEntries(Object.entries(meta.groups).map(([group, items]) => [group,
      items.map(item => Object.fromEntries(Object.entries(item.attributes || {}).map(([key, value]) => [key, scalar(value)])))]));
  } else {
    output.datos = Object.fromEntries(Object.entries(meta).filter(([key]) => !['notification_xml', 'frame_xml'].includes(key)));
  }
  return output;
}
function selectEvent(event) {
  selectedEvent = event;
  for (const row of $('#events').querySelectorAll('.event-item')) row.setAttribute('aria-pressed', String(row.dataset.eventId === String(event.id)));
  $('#detail-empty').hidden = true; $('#detail-content').hidden = false; $('#download').hidden = false; $('#download-simple').hidden = false;
  const summary = $('#detail-summary'); summary.replaceChildren();
  for (const [label, value] of [
    ['ID', event.id], ['Cámara', names[event.camera_id] || event.camera_id], ['Evento', event.topic],
    ['Recibido', new Date(event.received_at).toLocaleString()],
    ['Hora de origen', event.source_time || 'No indicada'], ['Transporte', event.transport]
  ]) {
    const dt = document.createElement('dt'), dd = document.createElement('dd');
    dt.textContent = label; dd.textContent = String(value ?? '—'); summary.append(dt, dd);
  }
  const metadata = event.metadata, xml = metadata?.notification_xml || metadata?.frame_xml;
  const formatted = simplifyEvent(event);
  $('#detail-metadata').textContent = JSON.stringify(formatted, null, 2);
  $('#xml-section').hidden = !xml; $('#detail-xml').textContent = xml || '';
}
function clearSelection() {
  selectedEvent = null;
  $('#detail-empty').hidden = false; $('#detail-content').hidden = true; $('#download').hidden = true; $('#download-simple').hidden = true;
}
function mergeEvents(events, keepNewest = true) {
  const unique = new Map(page.map(event => [event.id, event]));
  for (const event of events) unique.set(event.id, event);
  const sorted = [...unique.values()].sort((a, b) => b.id - a.id);
  page = keepNewest ? sorted.slice(0, MAX_VISIBLE) : sorted;
  renderEvents(true, keepNewest);
  // Keep the selected detail pinned while new events arrive, even if its row leaves the window.
  if (!selectedEvent && page.length) selectEvent(page[0]);
}
async function loadLatest() {
  if (!connected) return;
  const version = ++generation; initialized = false;
  filters = {camera: $('#filter').value, topic: $('#topic').value.trim()};
  loadsInFlight++; updateLiveStatus();
  try {
    const events = await api(queryEvents({order: 'desc'}));
    if (version !== generation) return;
    page = events; lastId = events.length ? Math.max(...events.map(event => event.id)) : 0;
    initialized = true; clearSelection(); renderEvents(false);
    if (page.length) selectEvent(page[0]);
    lastUpdate = new Date(); feedError();
  } catch (error) { if (version === generation) feedError(error.message); }
  finally { loadsInFlight--; updateLiveStatus(); }
}
async function pollEvents() {
  if (!connected || paused || document.hidden || pollBusy || loadsInFlight > 0) return;
  if (!initialized) { await loadLatest(); return; }
  pollBusy = true; const version = generation;
  try {
    const events = await api(queryEvents({after_id: String(lastId), order: 'asc'}));
    if (paused || document.hidden || version !== generation) return;
    if (events.length) { lastId = Math.max(lastId, ...events.map(event => event.id)); mergeEvents(events); }
    lastUpdate = new Date(); feedError(); updateLiveStatus();
    // Drain any backlog in ordered batches rather than skipping to the newest ID.
    if (events.length === 100) setTimeout(pollEvents, 50);
  } catch (error) {
    if (version === generation && !paused) feedError('Sin conexión con el colector. Reintentando… ' + error.message);
  } finally { pollBusy = false; }
}
async function loadOlder() {
  if (!connected || olderBusy || loadsInFlight > 0 || !page.length || page.length >= MAX_VISIBLE) return;
  paused = true; generation++; olderBusy = true; updateLiveStatus(); const version = generation;
  try {
    const events = await api(queryEvents({order: 'desc', before_id: String(Math.min(...page.map(event => event.id))),
      limit: String(Math.min(100, MAX_VISIBLE - page.length))}));
    if (version !== generation) return;
    mergeEvents(events, false);
    feedError(events.length ? '' : 'No hay más eventos anteriores para este filtro.');
  } catch (error) { if (version === generation) feedError(error.message); }
  finally { olderBusy = false; updateLiveStatus(); }
}
function download(blob, name) {
  const url = URL.createObjectURL(blob), anchor = document.createElement('a');
  anchor.href = url; anchor.download = name; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$('#download').onclick = async () => {
  if (!selectedEvent) return; const id = selectedEvent.id;
  try {
    const response = await fetch('/api/events/' + id + '/raw', {headers: {Authorization: 'Bearer ' + token}});
    if (!response.ok) throw Error('No se pudo descargar el evento.');
    download(await response.blob(), 'evento-' + id + '.bin');
  } catch (error) { feedError(error.message); }
};
$('#connect').onclick = async () => {
  generation++; token = $('#token').value.trim(); connected = false; updateLiveStatus();
  try { await refresh(); connected = true; paused = false; message('Acceso conectado.'); await loadLatest(); }
  catch (error) { message(error.message); feedError(error.message); }
  updateLiveStatus();
};
$('#pause').onclick = () => { paused = !paused; generation++; updateLiveStatus(); if (!paused) pollEvents(); };
$('#load').onclick = loadLatest;
$('#filter').onchange = loadLatest;
$('#topic').onkeydown = event => { if (event.key === 'Enter') loadLatest(); };
$('#older').onclick = loadOlder;
$('#export').onclick = () => download(new Blob([JSON.stringify(page.map(simplifyEvent), null, 2)], {type: 'application/json'}), 'eventos-simplificados.json');
$('#camera').onsubmit = async event => {
  event.preventDefault();
  try {
    const camera = Object.fromEntries(new FormData(event.target)); camera.device_url = camera.device_url.trim();
    if (camera.mode === 'onvif' && camera.device_url) camera.device_url = $('#camera-protocol').value + '://' + camera.device_url.replace(/^https?:\/\//i, '');
    camera.verify_tls = camera.verify_tls !== 'false';
    const result = await api('/api/cameras', {method: 'POST', body: JSON.stringify(camera)});
    message(result.webhook_token ? 'Cámara guardada. Guarda este token; se muestra una sola vez.\nURL: ' + location.origin + result.webhook_path
      + '\nAuthorization: Bearer ' + result.webhook_token + '\nTambién se acepta X-Camera-Token.' : 'Cámara guardada. Conectando por ONVIF…');
    event.target.password.value = ''; await refresh();
  } catch (error) { message(error.message); }
};
setInterval(pollEvents, 1000);
setInterval(() => { if (connected && !document.hidden) refresh().catch(error => message(error.message)); }, 5000);
updateLiveStatus();

$('#download-simple').onclick = () => {
  if (selectedEvent) download(new Blob([JSON.stringify(simplifyEvent(selectedEvent), null, 2)], {type: 'application/json'}), 'evento-' + selectedEvent.id + '-simple.json');
};

async function refreshForwarding(){
  const data=await api('/api/forwarding');
  $('#forwarding-form').hidden=!canManage;
  $('#forwarding-status').textContent=(data.enabled?'Envío activo':'Envío desactivado')+' · Pendientes: '+(data.pending??0)+' · Entregados: '+(data.sent??0)+' · Descartados sin enviar: '+(data.dropped??0)+' · '+(data.last_result||'Sin envíos')+(data.host?' · Destino: '+data.scheme+'://'+data.host+':'+data.port+data.path:'');
  if(!forwardingLoaded&&data.host){
    $('#forward-scheme').value=data.scheme;$('#forward-host').value=data.host;$('#forward-port').value=data.port;$('#forward-path').value=data.path;$('#forward-enabled').checked=!!data.enabled;
  }
  forwardingLoaded=true;
}
$('#forwarding-form').onsubmit=async event=>{
  event.preventDefault();
  try{
    await api('/api/forwarding',{method:'PUT',body:JSON.stringify({enabled:$('#forward-enabled').checked,scheme:$('#forward-scheme').value,host:$('#forward-host').value,port:Number($('#forward-port').value),path:$('#forward-path').value,token:$('#forward-token').value,clear_token:$('#forward-clear-token').checked})});
    $('#forwarding-message').textContent='Configuración guardada. Los fallos se reintentan automáticamente mientras el envío esté activo.';await refreshForwarding();
  }catch(error){$('#forwarding-message').textContent=error.message;}
  finally{$('#forward-token').value='';$('#forward-clear-token').checked=false;}
};
$('#forward-test').onclick=async()=>{
  $('#forward-test').disabled=true;
  try{const result=await api('/api/forwarding/test',{method:'POST'});$('#forwarding-message').textContent=result.detail;}
  catch(error){$('#forwarding-message').textContent=error.message;}
  finally{$('#forward-test').disabled=false;}
};
$('#forward-scheme').onchange=()=>{$('#forward-port').value=$('#forward-scheme').value==='https'?443:80;};
