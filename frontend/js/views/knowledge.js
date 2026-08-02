/* ==========================================================
   nexus — NODOS DE CONOCIMIENTO: el grafo arrastrable y las
   ventanitas flotantes que abren una nota o el SKILL.md de un
   modulo. Los colores salen de agrupar por componente conexa,
   asi que lo relacionado sale del mismo color sin configurarlo.
   ========================================================== */
import { $, $$, esc, api, flash, mdToHtml } from '../core/dom.js';
import { state } from '../core/state.js';
import { CATALOG } from '../core/catalog.js';
import { nsBtn } from '../ui/widgets.js';
import { go } from '../core/nav.js';
import { send } from '../core/orders.js';

/* ---------------- Nodos de conocimiento (grafo arrastrable) ---------------- */
let knRaf = 0, knDrag = null, knStageEl = null, knNodes = [];
/* GRUPOS de memoria: las notas enlazadas entre sí ([[wikilinks]]) forman un
   grupo que comparte COLOR y se mueve EN BLOQUE. Se calcula con union-find
   sobre el grafo y el resultado se comparte entre las vistas Memoria y Nodos. */
const GROUP_PALETTE = ['#22d3ee', '#7cf6c0', '#ff7ac0', '#ffd23a', '#c77dff', '#4d9bff',
  '#ff5e5e', '#59ff9c', '#ffb14d', '#4dffd8', '#f97316', '#a3e635'];
export let memGroupColor = {};                      // nota → color de su grupo
export function computeMemGroups(names, edges) {
  const idx = Object.fromEntries(names.map((n, i) => [n, i]));
  const parent = names.map((_, i) => i);
  const find = (a) => (parent[a] === a ? a : (parent[a] = find(parent[a])));
  (edges || []).forEach(([a, b]) => {
    if (idx[a] != null && idx[b] != null) parent[find(idx[a])] = find(idx[b]);
  });
  const comps = {};
  names.forEach((n, i) => { const r = find(i); (comps[r] = comps[r] || []).push(n); });
  // orden estable (por su primer miembro alfabético) → mismos colores siempre
  const ordered = Object.values(comps).sort(
    (A, B) => A.slice().sort()[0].localeCompare(B.slice().sort()[0]));
  memGroupColor = {}; const groupOf = {};
  ordered.forEach((members, gi) => {
    const col = GROUP_PALETTE[gi % GROUP_PALETTE.length];
    members.forEach((m) => { memGroupColor[m] = col; groupOf[m] = gi; });
  });
  return groupOf;
}
function knNoteColor(nm) {
  const l = nm.toLowerCase();
  if (l.startsWith('doc')) return '#4dd8ff';
  if (l.includes('objetiv')) return '#ffb14d';
  if (l.includes('conocimiento') || l.includes('procedim')) return '#7cf6c0';
  if (l.includes('idea')) return '#ff7ac0';
  if (l.includes('factura') || l.includes('cliente')) return '#ffe74d';
  return '#9d7dff';
}
export function mountKnowledge() {
  cancelAnimationFrame(knRaf);
  const stage = $('#kn-stage'), links = $('#kn-links');
  knStageEl = stage;
  const dpr = window.devicePixelRatio || 1;
  const W = stage.clientWidth, H = stage.clientHeight;
  links.width = W * dpr; links.height = H * dpr; links.style.width = W + 'px'; links.style.height = H + 'px';
  const ctx = links.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  stage.querySelectorAll('.knode').forEach((e) => e.remove());
  const cx = W / 2, cy = H / 2, nodes = [], byKey = {};
  knNodes = nodes;
  let edges = [];
  const place = (data) => {
    const el = document.createElement('div');
    el.className = 'knode' + (data.core ? ' core' : '') + (data.note ? ' note' : '');
    el.style.setProperty('--c', data.color);
    const sz = data.core ? 90 : data.note ? 34 : 56;
    el.style.width = el.style.height = sz + 'px';
    el.innerHTML = `<span>${esc(data.label)}</span>`;
    stage.appendChild(el);
    const n = Object.assign({ el, sz, x: data.x0 ?? cx, y: data.y0 ?? cy, vx: 0, vy: 0, moved: false }, data);
    nodes.push(n); if (data.key) byKey[data.key] = n;
    el.addEventListener('mousedown', (e) => { e.preventDefault(); knDrag = n; n.moved = false; n._sx = e.clientX; n._sy = e.clientY; });
    el.addEventListener('click', () => {
      if (n.moved) return;
      if (n.core) return openNode('__core__');
      if (n.note) return openNote(n.raw);
      return openNode(n.folder);
    });
    return n;
  };
  const core = place({ core: 1, key: 'nexus', label: 'nexus', color: '#22d3ee', x0: cx, y0: cy });
  core.fixed = true;
  const keys = Object.keys(CATALOG), R = Math.min(W, H) * 0.30;
  keys.forEach((k, i) => { const a = i / keys.length * Math.PI * 2 - Math.PI / 2;
    place({ folder: k, key: 'skill:' + k, label: CATALOG[k].label, color: CATALOG[k].color,
      x0: cx + Math.cos(a) * R * 1.3, y0: cy + Math.sin(a) * R }); });
  api('/api/graph').then((g) => {
    const gn = (g?.nodes || []), ge = (g?.edges || []);
    const groupOf = computeMemGroups(gn, ge);   // notas enlazadas = mismo color/grupo
    const notes = gn.slice(0, 26), R2 = Math.min(W, H) * 0.44;
    notes.forEach((nm, i) => { const a = i / Math.max(1, notes.length) * Math.PI * 2 + 0.4;
      place({ note: 1, key: 'note:' + nm, raw: nm, group: groupOf[nm],
        label: nm.length > 13 ? nm.slice(0, 12) + '…' : nm,
        color: memGroupColor[nm] || knNoteColor(nm),
        x0: cx + Math.cos(a) * R2 * 1.3, y0: cy + Math.sin(a) * R2 }); });
    edges = ge.map(([f, t]) => [byKey['note:' + f], byKey['note:' + t]]).filter(([a, b]) => a && b);
  });
  // Nodos QUIETOS: se quedan donde están; solo se mueven si los arrastras.
  // El bucle solo redibuja las líneas y coloca los nodos (sin física ni deriva).
  function frame() {
    ctx.clearRect(0, 0, W, H);
    const coreN = nodes.find((n) => n.core); if (coreN) { coreN.x = cx; coreN.y = cy; }
    for (const n of nodes) { if (n.core) continue;
      ctx.strokeStyle = n.color + (n.note ? '22' : '38'); ctx.lineWidth = n.note ? 1 : 1.5;
      ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(n.x, n.y); ctx.stroke(); }
    ctx.lineWidth = 1.2;
    for (const [a, b] of edges) { ctx.strokeStyle = (a.color || '#7cf6c0') + '66';
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke(); }
    for (const n of nodes) { n.el.style.left = (n.x - n.sz / 2) + 'px'; n.el.style.top = (n.y - n.sz / 2) + 'px'; }
    knRaf = requestAnimationFrame(frame);
  }
  frame();
}
// arrastre global de nodos
document.addEventListener('mousemove', (e) => {
  if (!knDrag || !knStageEl) return;
  const r = knStageEl.getBoundingClientRect();
  if (Math.hypot(e.clientX - knDrag._sx, e.clientY - knDrag._sy) > 4) knDrag.moved = true;
  const nx = e.clientX - r.left, ny = e.clientY - r.top;
  // En «Nodos de conocimiento» cada nodo se mueve INDIVIDUALMENTE (no en bloque).
  // (El movimiento en bloque por grupo se mantiene en la vista Memoria.)
  knDrag.x = nx; knDrag.y = ny; knDrag.x0 = nx; knDrag.y0 = ny; knDrag.vx = 0; knDrag.vy = 0;
});
document.addEventListener('mouseup', () => {
  if (knDrag) { knDrag.x0 = knDrag.x; knDrag.y0 = knDrag.y; }   // se queda donde lo sueltas
  knDrag = null;
});
/* ============ MINI-VENTANAS flotantes (nodos de conocimiento y memoria) ============
   Cada nodo se abre en su propia ventanita con ✕; puedes abrir varias a la vez
   y van RELLENANDO la pantalla en rejilla (cuando se llena, en cascada).
   Se arrastran desde su cabecera y el clic las trae al frente. Sobreviven al
   cambiar de vista, así puedes comparar nodos de memoria y de conocimiento. */
let _mwZ = 300, _mwCount = 0, _mwDrag = null;
function miniWinLayer() {
  let c = $('#mini-wins');
  if (!c) { c = document.createElement('div'); c.id = 'mini-wins'; $('#main').appendChild(c); }
  return c;
}
function openMiniWin(id, title, color, loadingHtml) {
  const layer = miniWinLayer();
  const prev = layer.querySelector(`.mini-win[data-mwid="${CSS.escape(id)}"]`);
  if (prev) {                                  // ya abierta → al frente y un destello
    prev.style.zIndex = ++_mwZ;
    prev.classList.remove('flash'); void prev.offsetWidth; prev.classList.add('flash');
    return null;
  }
  const w = document.createElement('div');
  w.className = 'mini-win'; w.dataset.mwid = id;
  w.style.setProperty('--c', color || '#22d3ee');
  // posición ALEATORIA dentro del área útil: cada ventana cae donde quiere
  // y la pantalla se va llenando de forma orgánica (luego las arrastras).
  const area = $('#main').getBoundingClientRect();
  const MW = 324, MH = 300, X0 = 18, Y0 = 62;
  const maxX = Math.max(X0, area.width - MW - 22);
  const maxY = Math.max(Y0, area.height - MH - 46);
  _mwCount++;
  w.style.left = Math.round(X0 + Math.random() * (maxX - X0)) + 'px';
  w.style.top = Math.round(Y0 + Math.random() * (maxY - Y0)) + 'px';
  w.style.zIndex = ++_mwZ;
  w.innerHTML = `<div class="mw-head"><span class="mw-title">${esc(title)}</span>
      <button class="mw-close" title="Cerrar">✕</button></div>
    <div class="mw-body">${loadingHtml || '<div class="empty"><span class="dots">cargando</span></div>'}</div>`;
  layer.appendChild(w);
  w.querySelector('.mw-close').addEventListener('click', (e) => { e.stopPropagation(); w.remove(); });
  w.addEventListener('mousedown', () => { w.style.zIndex = ++_mwZ; });
  const head = w.querySelector('.mw-head');
  head.addEventListener('mousedown', (e) => {
    if (e.target.classList.contains('mw-close')) return;
    const r = w.getBoundingClientRect();
    _mwDrag = { w, dx: e.clientX - r.left, dy: e.clientY - r.top };
    e.preventDefault();
  });
  return w.querySelector('.mw-body');
}
document.addEventListener('mousemove', (e) => {
  if (!_mwDrag) return;
  const a = $('#main').getBoundingClientRect();
  _mwDrag.w.style.left = Math.max(0, Math.min(a.width - 60, e.clientX - a.left - _mwDrag.dx)) + 'px';
  _mwDrag.w.style.top = Math.max(0, Math.min(a.height - 40, e.clientY - a.top - _mwDrag.dy)) + 'px';
});
document.addEventListener('mouseup', () => { _mwDrag = null; });
export function closeTopMiniWin() {
  const wins = $$('#mini-wins .mini-win');
  if (!wins.length) return false;
  wins.sort((a, b) => (+b.style.zIndex || 0) - (+a.style.zIndex || 0))[0].remove();
  return true;
}

// Nodo de MEMORIA → mini-ventana con el contenido de la nota
export async function openNote(name) {
  const color = memGroupColor[name] || knNoteColor(name);
  const body = openMiniWin('note:' + name, '▣ ' + name, color, null);
  if (!body) return;                            // ya estaba abierta
  const d = await api('/api/note?name=' + encodeURIComponent(name));
  const content = (d?.content || '').trim();
  body.innerHTML = `
    <div class="ns-sec"><h4>NODO DE MEMORIA</h4><p>${esc(name)}</p></div>
    <div class="ns-sec"><h4>CONTENIDO</h4><div class="ns-doc">${content ? mdToHtml(content.slice(0, 4000)) : '<p class="empty">Nota vacía o no encontrada.</p>'}</div></div>
    <div class="ns-sec"><h4>ACCIONES</h4><div class="ns-acts">
      ${nsBtn('Preguntar sobre esto', 'qué recuerdas de ' + name)}
      ${nsBtn('Ver memoria', null, 0, 'memory')}
    </div></div>`;
  wireNs(body);
}

// Nodo de CONOCIMIENTO (skill o núcleo) → mini-ventana con su ficha
export async function openNode(folder) {
  const color = folder === '__core__' ? '#22d3ee' : (CATALOG[folder]?.color || '#22d3ee');
  const title = folder === '__core__' ? 'nexus · núcleo' : (CATALOG[folder]?.label || folder);
  const body = openMiniWin('node:' + folder, '◈ ' + title, color, null);
  if (!body) return;
  if (folder === '__core__') {
    body.innerHTML = `
      <div class="ns-sec"><h4>FUNCIÓN</h4><p>Orquestador central. Recibe tus órdenes por voz o texto, decide qué minion las resuelve y coordina la respuesta.</p></div>
      <div class="ns-sec"><h4>ACCIONES</h4><div class="ns-acts">
        ${nsBtn('¿Qué me toca hoy?', 'qué me toca hoy')}${nsBtn('Estado del equipo', null, 0, 'hardware')}
        ${nsBtn('Estado de la memoria', 'estado de la memoria')}${nsBtn('Qué manos tengo', 'qué manos tienes')}
      </div></div>`;
    wireNs(body);
    return;
  }
  const cat = CATALOG[folder];
  const d = await api('/api/skill/' + folder);
  const actions = (cat?.actions || []).map(([l, c, pr]) => nsBtn(l, c, pr)).join('');
  const intents = (d?.intents || []).map((i) => `<span class="ns-chip">${esc(i)}</span>`).join('');
  const docHtml = d?.doc ? mdToHtml(d.doc) : '<p class="empty">Sin SKILL.md.</p>';
  body.innerHTML = `
    <div class="ns-sec"><h4>DESCRIPCIÓN</h4><p>${esc(d?.description || cat?.desc || '')}</p>
      <div class="ns-stat">estado <b>${esc(d?.status || 'ready')}</b> · usos <b>${d?.calls || 0}</b> · ${(d?.intents || []).length} acciones</div></div>
    <div class="ns-sec"><h4>ACCIONES</h4><div class="ns-acts">${actions || '<span class="empty">—</span>'}</div></div>
    <div class="ns-sec"><h4>CAPACIDADES</h4><div class="ns-chips">${intents}</div></div>
    <div class="ns-sec"><h4>MÓDULO · SKILL.md</h4><div class="ns-doc">${docHtml}</div></div>`;
  wireNs(body);
}
export function wireNs(scope) {
  (scope || document).querySelectorAll('.ns-act').forEach((b) => b.addEventListener('click', () => {
    if (b.dataset.v) return go(b.dataset.v);
    const cmd = b.dataset.cmd;
    if (b.dataset.p) { go('chat'); setTimeout(() => { $('#chat-in').value = cmd; $('#chat-in').focus(); }, 50); }
    else { send(cmd); flash(b); }
  }));
}
