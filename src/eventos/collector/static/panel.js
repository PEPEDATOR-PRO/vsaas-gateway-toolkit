'use strict';
const $ = selector => document.querySelector(selector);
const message = text => { $('#message').textContent = text; };
const MAX_VISIBLE = 500;
let token = '', names = {}, page = [], selectedEvent = null;
let connected = false, paused = false, initialized = false, lastId = 0, generation = 0;
let pollBusy = false, loadsInFlight = 0, olderBusy = false, lastUpdate = null;
let filters = {camera: '', topic: ''};
let canManage = false;

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
  $('#camera-management').hidden = !canManage;
  $('#access-note').textContent = canManage ? 'Acceso de administración.' : 'Solo consulta · Puedes ver y descargar eventos. La configuración de cámaras está protegida.';
  $('#total').textContent = status.events + ' eventos guardados';
  const disk=status.storage;
  $('#storage-status').textContent=disk?(disk.blocked?'Almacenamiento limitado: hay capturas pendientes. Conservamos el historial. ':'')+'Eventos y base: '+(disk.bytes/1024**2).toFixed(1)+' MiB'+(disk.limit_bytes?' / '+(disk.limit_bytes/1024**2).toFixed(0)+' MiB':'')+'. Libres en disco: '+(disk.free_bytes/1024**3).toFixed(1)+' GiB.':'';
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
