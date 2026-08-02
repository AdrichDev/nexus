/* ==========================================================
   nexus — vista CASA / Dispositivos.
   Tres solapas: los tuyos, los detectados y todo lo que hay en la
   red. Enciende, apaga y controla via Home Assistant o por IP.
   El mando completo se abre SOLO con el boton, nada oculto.
   ========================================================== */
import { $, $$, esc, api } from '../core/dom.js';
import { state } from '../core/state.js';

/* ---------------- CASA · Dispositivos (Mis dispositivos / Detectados / En la red) ----------------
   UI según el mockup aprobado por Adri: una acción clara por tarjeta (+ Añadir / ★ / ⏻),
   nombre EDITABLE (para que la voz lo entienda), chatarra técnica (IP·MAC) tras un
   interruptor, y NADA de doble-clic oculto. «Detectados» = controlable aún sin añadir;
   «En la red» = informativo y plegado. Mis dispositivos PERSISTEN en settings (my_devices). */
let _devList = [];            // dispositivos del último escaneo (índice → objeto)
let _devOpen = null;          // dispositivo cuyo panel de control está abierto
let _devScanning = false;
let _devTech = false;         // interruptor «detalles técnicos (IP · MAC)»
try { _devTech = localStorage.getItem('wbk_devtech') === '1'; } catch (e) { /* webview sin storage */ }

const myDevices = () => (state.config && Array.isArray(state.config.my_devices)) ? state.config.my_devices : [];
const devKey = (d) => d.entity_id || ((d.mac || '').toUpperCase()) || d.ip || (d.name || '');
async function saveMyDevices(list) {
  state.config.my_devices = list;
  await api('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ my_devices: list }) });
}
function mineEntry(key) { return myDevices().find((m) => m.key === key); }
async function addToMine(d) {
  if (!d || mineEntry(devKey(d))) return;
  const list = myDevices().slice();
  list.push({ key: devKey(d), name: d.name || d.type || 'Dispositivo', icon: d.icon || '📟',
              kind: d.kind || 'other', brand: d.brand || '', ip: d.ip || '', mac: d.mac || '',
              entity_id: d.entity_id || '', domain: d.domain || '' });
  await saveMyDevices(list);
  devToast(`★ «${(d.name || d.type)}» añadido a Mis dispositivos — nexus ya lo controla por voz.`);
  renderDevGrid(_devList);
}
async function removeFromMine(key, name) {
  await saveMyDevices(myDevices().filter((m) => m.key !== key));
  devToast(`Quitado de Mis dispositivos: «${name || key}». Sigue en Detectados si el escáner lo ve.`);
  renderDevGrid(_devList);
}
function devToast(txt) { const el = $('#dev-msg'); if (el) { el.textContent = txt; el.classList.add('show'); clearTimeout(el._t); el._t = setTimeout(() => el.classList.remove('show'), 6000); } }

export function mountHome() {
  const btn = $('#dev-scan');
  if (btn && !btn._w) { btn._w = 1; btn.addEventListener('click', scanDevices); }
  const cl = $('#dev-mclose');
  if (cl && !cl._w) { cl._w = 1; cl.addEventListener('click', closeDevModal); }
  const md = $('#dev-modal');
  if (md && !md._w) { md._w = 1; md.addEventListener('click', (e) => { if (e.target === md) closeDevModal(); }); }
  const tg = $('#dev-tech-toggle');
  if (tg) {
    tg.checked = _devTech;
    if (!tg._w) { tg._w = 1; tg.addEventListener('change', () => { _devTech = tg.checked; try { localStorage.setItem('wbk_devtech', _devTech ? '1' : '0'); } catch (e) { /* */ } renderDevGrid(_devList); }); }
  }
  renderHA();                                        // panel de Home Assistant (luces/enchufes)
  if (state.devices) renderDevGrid(state.devices);   // pinta lo último escaneado
  else scanDevices();                                // primera vez: rastrea solo
}

/* ---- Home Assistant: instalar / conectar / estado ---- */
async function renderHA() {
  const box = $('#dev-ha'); if (!box) return;
  box.innerHTML = '<div class="ha-card"><span class="dots">comprobando Home Assistant</span></div>';
  let s = null;
  try { s = await api('/api/home/ha_status'); } catch (e) { /* */ }
  if (!s) { box.innerHTML = ''; return; }
  const connected = s.running && s.has_token;
  if (connected) {
    box.innerHTML = `<div class="ha-card ok">
      <span class="ha-ic">🏠</span>
      <div class="ha-tx"><b>Home Assistant conectado ✓</b><span>${s.entities} ${s.entities === 1 ? 'aparato controlable' : 'aparatos controlables'} · ${esc(s.url)}</span></div>
      <button class="ha-btn ghost" id="ha-add">+ Añadir aparatos</button>
      <button class="ha-btn ghost" id="ha-open">Abrir</button>
      <button class="ha-btn ghost" id="ha-edit">Reconfigurar</button></div>`;
    $('#ha-add')?.addEventListener('click', () => openHAPath('/config/integrations/dashboard'));
    $('#ha-open')?.addEventListener('click', () => openHAPath(''));
    $('#ha-edit')?.addEventListener('click', () => renderHAForm(s));
    return;
  }
  if (s.running && !s.has_token) { renderHAForm(s, 'running'); return; }
  // no está en marcha
  box.innerHTML = `<div class="ha-card warn">
    <span class="ha-ic">💡</span>
    <div class="ha-tx"><b>Las luces y enchufes necesitan Home Assistant</b>
      <span>Es el mando universal de la domótica (gratis). Las TVs ya funcionan sin él.</span></div>
    ${s.docker
      ? '<button class="ha-btn" id="ha-install">⬇ Instalar Home Assistant</button>'
      : '<a class="ha-btn" href="https://www.docker.com/products/docker-desktop/" target="_blank">Instalar Docker</a>'}
    <button class="ha-btn ghost" id="ha-manual">Ya lo tengo</button></div>
    <div id="ha-out" class="ha-out"></div>`;
  $('#ha-install')?.addEventListener('click', installHA);
  $('#ha-manual')?.addEventListener('click', () => renderHAForm(s, 'manual'));
}
// Abre una URL (o una sub-ruta de HA) en el navegador real del PC.
function haBase() {
  const v = ($('#ha-url')?.value || '').trim() || (state.config && state.config.homeassistant_url) || 'http://localhost:8123';
  return v.replace(/\/+$/, '');
}
async function openHAPath(path) {
  const url = haBase() + (path || '');
  try { await api('/api/open_url', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url }) }); } catch (e) { /* */ }
}
// ASISTENTE GUIADO (3 pasos) — claro y a prueba de perderse.
function renderHAForm(s, mode) {
  const box = $('#dev-ha'); if (!box) return;
  box.innerHTML = `<div class="ha-wiz">
    <div class="ha-wiz-head"><span class="ha-ic">🏠</span>
      <div><b>Conectar Home Assistant</b><span>Es el mando universal de tus luces, enchufes y persianas. Sigue estos 3 pasos — te llevo de la mano.</span></div>
    </div>

    <div class="ha-step">
      <div class="ha-num">1</div>
      <div class="ha-body">
        <b>Abre Home Assistant y añade tus aparatos</b>
        <p>Se abre en tu navegador. Ve a <b>Ajustes → Dispositivos y servicios → Añadir integración</b> y busca tu marca (Philips Hue, Tuya, Shelly, Sonoff, Xiaomi…). Muchos se detectan solos.</p>
        <div class="ha-row">
          <button class="ha-btn" id="ha-open-dev">↗ Abrir «Añadir integración»</button>
          <button class="ha-btn ghost" id="ha-open-home">Abrir Home Assistant</button>
        </div>
      </div>
    </div>

    <div class="ha-step">
      <div class="ha-num">2</div>
      <div class="ha-body">
        <b>Crea un «token de acceso de larga duración»</b>
        <p>Es la llave para que nexus controle HA. En Home Assistant: pincha en <b>tu nombre</b> (abajo a la izquierda) → pestaña <b>Seguridad</b> → baja del todo hasta <b>«Tokens de acceso de larga duración»</b> → <b>Crear token</b> → ponle un nombre (p. ej. nexus) → <b>cópialo</b> (solo se muestra una vez).</p>
        <div class="ha-row"><button class="ha-btn ghost" id="ha-open-prof">↗ Abrir mi perfil (Seguridad)</button></div>
      </div>
    </div>

    <div class="ha-step">
      <div class="ha-num">3</div>
      <div class="ha-body">
        <b>Pega el token aquí</b>
        <label class="ha-lbl">Dirección de Home Assistant</label>
        <input id="ha-url" class="ha-in" placeholder="http://localhost:8123" value="${esc((s && s.url) || 'http://localhost:8123')}">
        <label class="ha-lbl">Token de acceso de larga duración</label>
        <textarea id="ha-token" class="ha-in" rows="3" placeholder="pega aquí el token largo que copiaste" autocomplete="off"></textarea>
        <div class="ha-row">
          <button class="ha-btn" id="ha-save">Conectar</button>
          <button class="ha-btn ghost" id="ha-cancel">Cancelar</button>
        </div>
        <div id="ha-msg" class="ha-out"></div>
      </div>
    </div>
  </div>`;
  $('#ha-open-home')?.addEventListener('click', () => openHAPath(''));
  $('#ha-open-dev')?.addEventListener('click', () => openHAPath('/config/integrations/dashboard'));
  $('#ha-open-prof')?.addEventListener('click', () => openHAPath('/profile/security'));
  $('#ha-cancel')?.addEventListener('click', renderHA);
  $('#ha-save')?.addEventListener('click', saveHAConn);
}
async function openHA() { return openHAPath(''); }
async function installHA() {
  const btn = $('#ha-install'), out = $('#ha-out');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Instalando… (descarga la 1ª vez, puede tardar unos minutos)'; }
  if (out) out.textContent = 'Levantando Home Assistant en Docker…';
  let res = null;
  try { res = await api('/api/home/install_ha', { method: 'POST' }); } catch (e) { /* */ }
  if (!res || !res.ok) {
    if (out) out.textContent = (res && (res.error || res.out)) || 'No pude instalar Home Assistant. ¿Docker Desktop está abierto?';
    if (btn) { btn.disabled = false; btn.textContent = '⬇ Reintentar instalación'; }
    return;
  }
  if (out) out.textContent = '✓ Home Assistant levantado. Ábrelo para crear tu usuario y tus aparatos, luego pega el token.';
  setTimeout(() => renderHAForm({ url: res.url || 'http://localhost:8123' }, 'running'), 1200);
}
async function saveHAConn() {
  const url = ($('#ha-url')?.value || '').trim() || 'http://localhost:8123';
  const token = ($('#ha-token')?.value || '').trim();
  const msg = $('#ha-msg'), btn = $('#ha-save');
  if (msg) { msg.className = 'ha-out'; }
  if (!token) { if (msg) { msg.className = 'ha-out err'; msg.textContent = 'Falta el token (paso 2). Cópialo de tu perfil de HA → Seguridad.'; } return; }
  if (btn) { btn.disabled = true; }
  if (msg) msg.textContent = '⏳ probando la conexión…';
  // 1) PROBAR antes de guardar → feedback exacto de qué falla
  let t = null;
  try { t = await api('/api/home/ha_test', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url, token }) }); } catch (e) { /* */ }
  if (btn) { btn.disabled = false; }
  if (!t || !t.reachable) {
    if (msg) { msg.className = 'ha-out err'; msg.textContent = '✕ ' + ((t && t.error) || `No llego a Home Assistant en ${url}. Comprueba que está encendido y la dirección (por defecto http://localhost:8123).`); }
    return;
  }
  if (!t.token_valid) {
    if (msg) { msg.className = 'ha-out err'; msg.textContent = '✕ ' + (t.error || 'El token no es válido. Crea uno nuevo en tu perfil de HA (Seguridad) y pégalo entero.'); }
    return;
  }
  // 2) todo OK → guardar de verdad
  try {
    await api('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ homeassistant_url: url }) });
    await api('/api/secrets', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ homeassistant_token: token }) });
  } catch (e) { /* */ }
  if (msg) {
    msg.className = 'ha-out ok';
    msg.textContent = t.controllable
      ? `✓ ¡Conectado! ${t.controllable} aparatos controlables (de ${t.entities} entidades). Rastreando…`
      : `✓ Conectado, pero HA aún no tiene aparatos controlables. Vuelve al paso 1 y añade tus integraciones (luces, enchufes…).`;
  }
  state.devices = null;
  setTimeout(() => { renderHA(); scanDevices(); }, 700);
}

async function scanDevices() {
  if (_devScanning) return;
  _devScanning = true;
  const btn = $('#dev-scan'), radar = $('#dev-radar'), grid = $('#dev-grid');
  if (btn) { btn.disabled = true; btn.textContent = '◎ Buscando…'; }
  if (radar) radar.classList.remove('hidden');
  if (grid && !state.devices) grid.innerHTML = '';
  let res = null;
  try { res = await api('/api/home/scan', { method: 'POST' }); } catch (e) { /* */ }
  if (radar) radar.classList.add('hidden');
  if (btn) { btn.disabled = false; btn.textContent = '◎ Buscar dispositivos'; }
  _devScanning = false;
  if (!res || !res.devices) {
    if (grid) grid.innerHTML = '<div class="empty">No pude rastrear la red ahora mismo. Reintenta en unos segundos.</div>';
    return;
  }
  state.devices = res.devices;
  renderDevGrid(res.devices);
}

function _devSub(d) {
  // Subtítulo LIMPIO: tipo/estado. La chatarra técnica (IP · MAC) solo con el interruptor.
  const parts = [];
  if (d.kind === 'ha') {
    parts.push(d.state ? (d.on ? 'encendida' : (d.state === 'off' ? 'apagada' : d.state)) : 'Home Assistant');
  } else {
    if (d.type && d.type !== d.name) parts.push(d.type);
    // Estado HONESTO de una TV: solo decimos «encendida» si TÚ la encendiste.
    // Si no, «en red» (visible) o «no responde» — nunca fingimos que está on.
    if (d.on === true) parts.push('encendida');
    else if (d.live === false) parts.push('no responde ahora');
    else parts.push('en red · estado no confirmado');
  }
  if (_devTech) {
    if (d.ip) parts.push(d.ip);
    if (d.mac) parts.push(d.mac);
  }
  return parts.map(esc).join(' · ');
}

// Botón de ACCIÓN principal por tarjeta: uno solo, claro, según el aparato.
function _mainAction(d) {
  if (d.kind === 'ha') {
    if (d.domain === 'cover') return d.on ? { a: 'off', t: '⬇ Cerrar', c: 'bad' } : { a: 'on', t: '⬆ Abrir', c: 'good' };
    if (d.domain === 'scene' || d.domain === 'script') return { a: 'on', t: '▸ Activar', c: 'good' };
    return d.on ? { a: 'off', t: '⭘ Apagar', c: 'bad' } : { a: 'on', t: '⏻ Encender', c: 'good' };
  }
  return d.on ? { a: 'off', t: '⭘ Apagar', c: 'bad' } : { a: 'on', t: '⏻ Encender', c: 'good' };
}

// Punto de estado HONESTO: verde = ENCENDIDO de verdad. Para una TV solo lo
// sabemos si TÚ la has encendido en esta sesión (d.on===true); estar «en red»
// o «guardada» NO es estar encendida (bug: salía verde solo por añadirla).
function _stateDot(d) {
  if (d.kind === 'ha') return `<span class="dev-state ${d.on ? 'on' : 'off'}"></span>`;
  if (d.on === true) return '<span class="dev-state on"></span>';       // encendida (confirmado por ti)
  if (d.live !== false) return '<span class="dev-state net"></span>';   // en la red, estado desconocido
  return '<span class="dev-state off"></span>';                          // guardada, no responde ahora
}
function mineCardHtml(d, i) {
  const act = _mainAction(d);
  const muteBtn = d.kind !== 'ha' ? `<button class="dev-mini" data-i="${i}" data-a="mute" title="Silenciar">🔇</button>` : '';
  const offline = (d.live === false && d.kind !== 'ha') ? ' offline' : '';
  return `<div class="dev-card mine${offline}" data-idx="${i}">
    <div class="dev-ic">${esc(d.icon || '📟')}${_stateDot(d)}</div>
    <div class="dev-meta">
      <b class="dev-name" data-i="${i}">${esc(d.name || d.type || 'Dispositivo')}</b>
      <button class="dev-mini dev-edit" data-i="${i}" title="Renombrar (la voz usará este nombre)">✎</button>
      <span class="dev-sub">${_devSub(d)}</span>
    </div>
    <div class="dev-actions">
      <button class="dev-act ${act.c}" data-i="${i}" data-a="${act.a}">${act.t}</button>
      ${muteBtn}
      <button class="dev-mini star on" data-i="${i}" data-a="unstar" title="Quitar de Mis dispositivos">★</button>
      <button class="dev-mini" data-i="${i}" data-a="remote" title="Mando completo">🎛</button>
    </div>
  </div>`;
}
function detCardHtml(d, i) {
  return `<div class="dev-card det" data-idx="${i}">
    <div class="dev-ic">${esc(d.icon || '📟')}</div>
    <div class="dev-meta"><b>${esc(d.name || d.type || 'Dispositivo')}</b>
      <span class="dev-sub">${_devSub(d)}</span></div>
    <div class="dev-actions">
      <button class="dev-act good" data-i="${i}" data-a="add">＋ Añadir</button>
      <button class="dev-mini" data-i="${i}" data-a="remote" title="Probar el mando">🎛</button>
    </div>
  </div>`;
}
function netCardHtml(d, i) {
  return `<div class="dev-card info" data-idx="${i}" data-a="info" tabindex="0">
    <div class="dev-ic">${esc(d.icon || '📟')}</div>
    <div class="dev-meta"><b>${esc(d.name || d.type || 'Dispositivo')}</b>
      <span class="dev-sub">${_devSub(d)}</span></div>
    <span class="dev-go">ficha ▸</span>
  </div>`;
}

function renderDevGrid(devices) {
  const grid = $('#dev-grid'); if (!grid) return;
  devices = Array.isArray(devices) ? devices : [];
  // Mis dispositivos: lo guardado, ENRIQUECIDO con lo que vea el escáner ahora.
  const byKey = {};
  devices.forEach((d) => { byKey[devKey(d)] = d; });
  const mine = myDevices().map((m) => {
    const live = byKey[m.key];
    if (live) { if (m.name && !live.entity_id) live.name = m.name; return live; }
    // guardado pero no visto ahora: tarjeta igualmente (TV con MAC enciende por WoL)
    return { ...m, controllable: true, live: false, on: false, type: m.kind === 'ha' ? 'Home Assistant' : 'guardado', services: [] };
  });
  const mineKeys = new Set(myDevices().map((m) => m.key));
  const det = [], net = [];
  devices.forEach((d) => {
    if (mineKeys.has(devKey(d))) return;
    (d.controllable ? det : net).push(d);
  });
  _devList = mine.concat(det, net);
  const idx = (d) => _devList.indexOf(d);
  const dc = $('#dev-count');
  if (dc) dc.textContent = `${devices.length} en la red · ${devices.filter((d) => d.controllable).length} controlables`;
  let html = `<div class="dev-sech mine">★ MIS DISPOSITIVOS (${mine.length})</div>`;
  html += mine.length
    ? `<div class="dev-row">${mine.map((d) => mineCardHtml(d, idx(d))).join('')}</div>`
    : '<div class="dev-empty">Aún no tienes dispositivos guardados. Añade abajo los que uses (＋) y nexus los recordará y los manejará por voz.</div>';
  html += `<div class="dev-sech det">◎ DETECTADOS · LISTOS PARA AÑADIR</div>`;
  html += det.length
    ? `<div class="dev-row">${det.map((d) => detCardHtml(d, idx(d))).join('')}</div>`
    : '<div class="dev-empty ok">Todo lo controlable ya está en tus dispositivos ✓</div>';
  html += `<details class="dev-net"><summary>📡 EN LA RED (${net.length}) — solo informativo</summary>
    <div class="dev-row">${net.map((d) => netCardHtml(d, idx(d))).join('')}</div></details>`;
  grid.innerHTML = html;
  // UN SOLO listener DELEGADO en el contenedor, enganchado UNA vez para toda la
  // vida del grid. Antes se añadía un listener por botón EN CADA render y, como
  // el grid se repinta al añadir/controlar, el mismo clic se disparaba DOS veces
  // la primera vez (el bug de «lo hace dos veces»). La delegación no se acumula.
  if (!grid._deleg) {
    grid._deleg = 1;
    grid.addEventListener('click', (ev) => {
      const edit = ev.target.closest('.dev-edit');
      if (edit) { ev.stopPropagation(); startRename(+edit.dataset.i); return; }
      const el = ev.target.closest('[data-a]');
      if (!el || !grid.contains(el)) return;
      ev.stopPropagation();
      const d = _devList[+(el.dataset.i ?? el.dataset.idx)];
      if (!d) return;
      const a = el.dataset.a;
      if (a === 'add') addToMine(d);
      else if (a === 'unstar') removeFromMine(devKey(d), d.name);
      else if (a === 'remote') openDevControl(d);
      else if (a === 'info') infoDevControl(d);
      else controlDevice(d, a, el);
    });
  }
}

function startRename(i) {
  const d = _devList[i]; if (!d) return;
  const nameEl = document.querySelector(`.dev-name[data-i="${i}"]`); if (!nameEl) return;
  const inp = document.createElement('input');
  inp.className = 'dev-rename'; inp.value = d.name || ''; inp.maxLength = 60;
  nameEl.replaceWith(inp); inp.focus(); inp.select();
  let done = false;
  const save = async () => {
    if (done) return; done = true;
    const name = inp.value.trim();
    if (name && name !== d.name) {
      d.name = name;
      await api('/api/home/rename', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, ip: d.ip || '', mac: d.mac || '', entity_id: d.entity_id || '', brand: d.brand || '' }) });
      const list = myDevices().slice();
      const m = list.find((x) => x.key === devKey(d)); if (m) m.name = name;
      state.config.my_devices = list;
      devToast(`🏷️ Renombrado a «${name}» — di «enciende ${name}» y nexus sabrá cuál es.`);
    }
    renderDevGrid(state.devices || []);
  };
  inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') save(); if (e.key === 'Escape') { done = true; renderDevGrid(state.devices || []); } });
  inp.addEventListener('blur', save);
}

function _controlBody(d, action) {
  return d.kind === 'ha'
    ? { kind: 'ha', action, entity_id: d.entity_id, name: d.name, domain: d.domain }
    : { kind: 'tv', action, ip: d.ip, brand: d.brand, mac: d.mac, name: d.name };
}
let _ctrlBusy = null;              // candado anti-doble-envío (device+acción en curso)
async function controlDevice(d, action, btn) {
  const lock = devKey(d) + ':' + action;
  if (_ctrlBusy === lock) return;   // ya hay un envío idéntico en vuelo → se ignora
  _ctrlBusy = lock;
  if (btn) { btn.disabled = true; btn.dataset.t = btn.textContent; btn.textContent = '⏳'; }
  let res = null;
  try {
    res = await api('/api/home/control', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(_controlBody(d, action)) });
  } catch (e) { /* */ }
  if (btn) { btn.disabled = false; btn.textContent = btn.dataset.t || '⏻'; }
  _ctrlBusy = null;
  devToast((res && res.reply) ? res.reply : 'No hubo respuesta del dispositivo.');
  if (res && res.ok) {
    // v24: manda el estado que DEVUELVE el backend (ya persistido allí); si no
    // viene, se cae al optimista de siempre. Antes el botón se quedaba en
    // «Encender» aunque la orden hubiera ido bien — queja de Adri del 25/07.
    if (res.state === 'on') d.on = true;
    else if (res.state === 'off') d.on = false;
    else if (action === 'on') d.on = true;
    else if (action === 'off') d.on = false;
    // el objeto de la rejilla puede ser otra copia: se sincroniza por clave
    const _k = devKey(d);
    (state.devices || []).forEach((x) => { if (devKey(x) === _k) x.on = d.on; });
    (_devList || []).forEach((x) => { if (devKey(x) === _k) x.on = d.on; });
    if (d.kind !== 'ha') d.controllable = true;   // NO tocamos d.connected: eso es «emparejada», no «encendida»
    if (!mineEntry(devKey(d))) await addToMine(d);   // «añade lo que uses»: si lo usas, se guarda
    renderDevGrid(state.devices || []);
  }
}

/* ---- Mando completo (modal) — se abre SOLO con el botón 🎛, nada oculto ---- */
const _DEV_BTN = (label, action, cls) => `<button class="dev-act ${cls || ''}" data-a="${action}">${label}</button>`;
const _pwBtn = (d) => d.on ? _DEV_BTN('⭘ Apagar', 'off', 'bad') : _DEV_BTN('⏻ Encender', 'on', 'good');
function _devButtons(d) {
  if (d.kind === 'ha') {
    if (d.domain === 'cover') return _DEV_BTN('⬆ Abrir', 'on', 'good') + _DEV_BTN('⬇ Cerrar', 'off', 'bad');
    if (d.domain === 'scene' || d.domain === 'script') return _DEV_BTN('▸ Activar', 'on', 'good');
    return _pwBtn(d);
  }
  return (d.connected
      ? _DEV_BTN('✓ Conectado', 'pair', 'wide connected')
      : _DEV_BTN('🔗 Conectar', 'pair', 'wide'))
    + _pwBtn(d)
    + _DEV_BTN('🔉 Vol -', 'vol_down') + _DEV_BTN('🔊 Vol +', 'vol_up') + _DEV_BTN('🔇 Silenciar', 'mute')
    + _DEV_BTN('⏮ Canal', 'ch_down') + _DEV_BTN('Canal ⏭', 'ch_up');
}
function _renderDevBody(d) {
  $('#dev-mbody').innerHTML = _devButtons(d);
  $('#dev-mbody').querySelectorAll('.dev-act').forEach((b) =>
    b.addEventListener('click', () => sendDevControl(b.dataset.a, b)));
}
function openDevControl(d) {
  _devOpen = d;
  $('#dev-mic').textContent = d.icon || '📟';
  $('#dev-mtitle').textContent = d.name || d.type;
  $('#dev-msub').textContent = d.kind === 'ha'
    ? `${d.type} · Home Assistant`
    : `${d.type}${d.brand && d.brand !== 'generic' ? ' · ' + d.brand : ''}${d.ip ? ' · ' + d.ip : ''}`;
  _renderDevBody(d);
  $('#dev-mmsg').textContent = d.kind === 'ha' ? '' : 'La primera vez, algunas TVs (Samsung) piden permiso en su pantalla: acéptalo.';
  $('#dev-modal').classList.remove('hidden');
}
function infoDevControl(d) {
  // dispositivo no controlable: su ficha (aquí SÍ vive la chatarra técnica completa)
  _devOpen = null;
  $('#dev-mic').textContent = d.icon || '📟';
  $('#dev-mtitle').textContent = d.name || d.type;
  $('#dev-msub').textContent = d.type || '';
  $('#dev-mbody').innerHTML = `<div class="dev-info-rows">
    ${d.ip ? `<div><span>IP</span><b>${esc(d.ip)}</b></div>` : ''}
    ${d.mac ? `<div><span>MAC</span><b>${esc(d.mac)}</b></div>` : ''}
    ${d.vendor ? `<div><span>Fabricante</span><b>${esc(d.vendor)}</b></div>` : ''}
    ${(d.services || []).length ? `<div><span>Servicios</span><b>${esc(d.services.join(', '))}</b></div>` : ''}
  </div>`;
  $('#dev-mmsg').textContent = 'Este aparato solo se lista. Para manejarlo, conéctalo a Home Assistant (arriba).';
  $('#dev-modal').classList.remove('hidden');
}
let _sendBusy = null;             // mismo candado anti-doble-envío en el modal
async function sendDevControl(action, btn) {
  if (!_devOpen) return;
  const d = _devOpen;
  if (action && action.indexOf('brand:') === 0) {
    d.brand = action.split(':')[1]; d.kind = 'tv'; d.controllable = true;
    openDevControl(d); sendDevControl('pair'); return;
  }
  const lock = devKey(d) + ':' + action;
  if (_sendBusy === lock) return;
  _sendBusy = lock;
  const msg = $('#dev-mmsg');
  if (btn) { btn.disabled = true; }
  if (msg) msg.textContent = '⏳ enviando…';
  let res = null;
  try {
    res = await api('/api/home/control', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(_controlBody(d, action)) });
  } catch (e) { /* */ }
  if (btn) btn.disabled = false;
  _sendBusy = null;
  if (msg) msg.textContent = (res && res.reply) ? res.reply : 'No hubo respuesta del dispositivo.';
  if (d.kind === 'ha' && res && res.ok && (action === 'on' || action === 'off')) {
    d.on = (res.state ? res.state === 'on' : action === 'on'); d.state = action;
  }
  if (d.kind !== 'ha' && res && res.ok) {
    // «pair» = emparejar (conectar), NO encender: solo entonces marcamos connected.
    if (action === 'pair') d.connected = true;
    d.controllable = true;
    if (action === 'on') d.on = true;
    else if (action === 'off') d.on = false;
    if (_devOpen === d) _renderDevBody(d);
  }
  if (res && res.ok && !mineEntry(devKey(d))) await addToMine(d);  // lo usas → se guarda
  renderDevGrid(state.devices || []);
}
function closeDevModal() { $('#dev-modal')?.classList.add('hidden'); _devOpen = null; }
