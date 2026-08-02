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
/* ---------------------------------------------------------------- el MUNDO
   El grafo vive en un lienzo de coordenadas propio (el «mundo»), más grande que
   la ventana, y lo que se ve es una cámara encima: `knView` guarda el zoom y el
   desplazamiento.

   Antes no había mundo: los nodos se posicionaban en coordenadas de pantalla y
   el arrastre las escribía sin límite. Al llevar un nodo contra un borde se
   salía del contenedor, el contenedor crecía, `clientWidth` cambiaba y en el
   siguiente montaje TODO se recolocaba sobre un tamaño distinto: el grafo se
   comprimía y los nodos se apilaban. Con un mundo de tamaño fijo eso no puede
   pasar — el borde de la ventana ya no es el borde de nada. */
const WORLD = { w: 2400, h: 1700 };
const ZOOM_MIN = 0.25, ZOOM_MAX = 3;
let knView = { z: 1, x: 0, y: 0 };          // zoom y esquina superior izquierda
let knPan = null;                            // arrastre del fondo
let knByName = {};                           // nombre de nota → nodo

function knAplicaVista() {
  const world = $('#kn-world');
  if (!world) return;
  world.style.transform = `translate(${-knView.x}px, ${-knView.y}px) scale(${knView.z})`;
  const lbl = $('#kn-zlabel');
  if (lbl) lbl.textContent = Math.round(knView.z * 100) + '%';
}

/** Acerca o aleja manteniendo quieto el punto de pantalla (px, py). */
function knZoom(factor, px, py) {
  const stage = $('#kn-stage');
  if (!stage) return;
  const r = stage.getBoundingClientRect();
  const sx = (px ?? r.width / 2), sy = (py ?? r.height / 2);
  const antes = knView.z;
  const z = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, antes * factor));
  if (z === antes) return;
  // el punto del mundo bajo el cursor no se mueve
  knView.x = (knView.x + sx) * (z / antes) - sx;
  knView.y = (knView.y + sy) * (z / antes) - sy;
  knView.z = z;
  knLimitaVista();
  knAplicaVista();
}

/** La cámara no puede salirse del mundo: si no, se ve el vacío y uno se pierde. */
function knLimitaVista() {
  const stage = $('#kn-stage');
  if (!stage) return;
  const vw = stage.clientWidth, vh = stage.clientHeight;
  const maxX = Math.max(0, WORLD.w * knView.z - vw);
  const maxY = Math.max(0, WORLD.h * knView.z - vh);
  knView.x = Math.min(maxX, Math.max(0, knView.x));
  knView.y = Math.min(maxY, Math.max(0, knView.y));
}

/** Encaja todo el grafo en la ventana y lo centra. */
function knAjustar() {
  const stage = $('#kn-stage');
  if (!stage || !knNodes.length) return;
  // Se encuadra TODO, núcleo incluido. Antes se excluía el núcleo para que las
  // 32 skills no comieran la vista; sin skills eso ya no hace falta, y dejarlo
  // fuera descolocaba el centro del grafo.
  const xs = knNodes.map((n) => n.x), ys = knNodes.map((n) => n.y);
  const x0 = Math.min(...xs) - 80, x1 = Math.max(...xs) + 80;
  const y0 = Math.min(...ys) - 80, y1 = Math.max(...ys) + 80;
  // SUELO del ajuste automático: por debajo de aquí no se lee nada, y se
  // prefiere dejar algo fuera —para eso está arrastrar el fondo—. El zoom
  // MANUAL sí puede bajar hasta ZOOM_MIN: ahí lo pides tú.
  const AJUSTE_MIN = 0.5;
  const z = Math.min(ZOOM_MAX, Math.max(AJUSTE_MIN,
    Math.min(stage.clientWidth / (x1 - x0), stage.clientHeight / (y1 - y0))));
  knView.z = z;
  knView.x = (x0 + x1) / 2 * z - stage.clientWidth / 2;
  knView.y = (y0 + y1) / 2 * z - stage.clientHeight / 2;
  knLimitaVista();
  knAplicaVista();
}

export function mountKnowledge() {
  cancelAnimationFrame(knRaf);
  const stage = $('#kn-stage'), world = $('#kn-world'), links = $('#kn-links');
  if (!stage || !world || !links) return;
  knStageEl = stage;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const W = WORLD.w, H = WORLD.h;
  world.style.width = W + 'px'; world.style.height = H + 'px';
  links.width = W * dpr; links.height = H * dpr;
  links.style.width = W + 'px'; links.style.height = H + 'px';
  const ctx = links.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  world.querySelectorAll('.knode').forEach((e) => e.remove());
  const cx = W / 2, cy = H / 2, nodes = [], byKey = {};
  knNodes = nodes; knByName = {};
  let edges = [];
  const place = (data) => {
    const el = document.createElement('div');
    el.className = 'knode' + (data.core ? ' core' : '')
      + (data.note ? ' note' : '') + (data.carpeta ? ' carpeta' : '');
    el.style.setProperty('--c', data.color);
    const sz = data.core ? 90 : data.carpeta ? 66 : data.note ? 38 : 56;
    el.style.width = el.style.height = sz + 'px';
    el.innerHTML = `<span>${esc(data.label)}</span>`;
    world.appendChild(el);
    const n = Object.assign({ el, sz, x: data.x0 ?? cx, y: data.y0 ?? cy, moved: false }, data);
    nodes.push(n);
    if (data.key) byKey[data.key] = n;
    if (data.raw) knByName[data.raw] = n;
    el.addEventListener('mousedown', (e) => {
      e.preventDefault(); e.stopPropagation();          // no arrastra el fondo
      knDrag = n; n.moved = false; n._sx = e.clientX; n._sy = e.clientY;
    });
    el.addEventListener('click', () => {
      if (n.moved) return;
      if (n.core) return openNode('__core__');
      if (n.note) return openNote(n.raw);
      if (n.carpeta) return;                             // la carpeta solo agrupa
      return openNode(n.folder);
    });
    return n;
  };
  // EL SISTEMA EN EL CENTRO, y todo lo demás colgando de él. El nombre no está
  // escrito a fuego: quien instale esto puede llamarlo como quiera, y aquí se
  // lee de la configuración.
  const core = place({ core: 1, key: 'nexus', label: sysName(), color: '#22d3ee',
    x0: cx, y0: cy });
  core.fixed = true;
  // Aquí NO van las skills. Tenían su propia órbita de 32 nodos y no aportaban
  // nada: para eso está la sección «Habilidades», que las lista con su
  // descripción y sus acciones. Esta pantalla es la del CONOCIMIENTO.
  api('/api/graph').then((g) => {
    const gn = (g?.nodes || []), ge = (g?.edges || []);
    const carpetas = g?.carpetas || {}, raices = g?.raiz || [];
    const groupOf = computeMemGroups(gn, ge);   // enlazadas o de la misma carpeta = mismo color
    // Las carpetas se colocan en su propia órbita, y sus archivos EN RACIMO
    // alrededor de la suya: así se ve de un vistazo qué depende de qué.
    // El panel es APAISADO (mas ancho que alto), asi que los anillos son elipses:
    // repartir en circulo dejaba la mitad de los nodos fuera de la ventana por
    // arriba y por abajo mientras sobraba sitio a los lados.
    const R3 = Math.min(W, H) * 0.17;      // carpetas: primer anillo tras el núcleo
    const AY = 0.62;                        // achatamiento vertical
    const centroCarpeta = {};
    raices.forEach((c, i) => {
      const a = i / Math.max(1, raices.length) * Math.PI * 2 - Math.PI / 2;
      const x0 = cx + Math.cos(a) * R3 * 1.6, y0 = cy + Math.sin(a) * R3 * AY * 1.6;
      centroCarpeta[c] = { x0, y0 };
      place({ carpeta: 1, key: 'note:' + c, raw: c, group: groupOf[c],
        label: c.length > 16 ? c.slice(0, 15) + '…' : c,
        color: memGroupColor[c] || '#7cf6c0', x0, y0 });
    });
    const sueltas = gn.filter((n) => !raices.includes(n));
    const porCarpeta = {};
    sueltas.forEach((n) => { (porCarpeta[carpetas[n] || ''] = porCarpeta[carpetas[n] || ''] || []).push(n); });
    Object.entries(porCarpeta).forEach(([c, miembros]) => {
      const base = centroCarpeta[c] || { x0: cx, y0: cy };
      // Las de una carpeta, en racimo alrededor de ella. Las sueltas, en un
      // anillo más lejos: cuelgan del núcleo, no de ninguna carpeta.
      const rad = c ? 165 : Math.min(W, H) * 0.30;
      miembros.forEach((nm, i) => {
        const a = i / Math.max(1, miembros.length) * Math.PI * 2 + (c ? 0.2 : 0.4);
        place({ note: 1, key: 'note:' + nm, raw: nm, group: groupOf[nm],
          label: nm.length > 15 ? nm.slice(0, 14) + '…' : nm,
          color: memGroupColor[nm] || knNoteColor(nm),
          x0: (c ? base.x0 : cx) + Math.cos(a) * rad * (c ? 1 : 1.6),
          y0: (c ? base.y0 : cy) + Math.sin(a) * rad * (c ? 1 : AY * 1.6) });
      });
    });
    edges = ge.map(([f, t]) => [byKey['note:' + f], byKey['note:' + t]])
      .filter(([a, b]) => a && b && a !== b);
    // TODO CUELGA DEL NÚCLEO. Las carpetas se enganchan a él directamente; las
    // notas sueltas —las que no son de ninguna carpeta— también, porque si no
    // quedarían flotando sin explicar de dónde salen.
    raices.forEach((c) => { const n = byKey['note:' + c]; if (n) edges.push([core, n]); });
    (porCarpeta[''] || []).forEach((nm) => {
      const n = byKey['note:' + nm]; if (n) edges.push([core, n]);
    });
    knPintaArbol(raices, porCarpeta, carpetas);
    knAjustar();
  });
  // Nodos QUIETOS: se quedan donde están; solo se mueven si los arrastras.
  function frame() {
    ctx.clearRect(0, 0, W, H);
    // El núcleo se queda quieto en el centro: es el ancla de todo lo demás.
    const coreN = nodes.find((n) => n.core); if (coreN) { coreN.x = cx; coreN.y = cy; }
    ctx.lineWidth = 1.2;
    for (const [a, b] of edges) {
      ctx.strokeStyle = (a.color || '#7cf6c0') + (a.hl || b.hl ? 'cc' : '55');
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    }
    for (const n of nodes) {
      n.el.style.left = (n.x - n.sz / 2) + 'px';
      n.el.style.top = (n.y - n.sz / 2) + 'px';
    }
    knRaf = requestAnimationFrame(frame);
  }
  frame();
  knAplicaVista();

  // ---- zoom con Ctrl + rueda, y con los botones ----
  stage.addEventListener('wheel', (e) => {
    if (!e.ctrlKey) return;                    // sin Ctrl, la rueda es de la página
    e.preventDefault();
    const r = stage.getBoundingClientRect();
    knZoom(e.deltaY < 0 ? 1.12 : 1 / 1.12, e.clientX - r.left, e.clientY - r.top);
  }, { passive: false });
  $('#kn-zoom')?.addEventListener('click', (e) => {
    const b = e.target.closest('.kn-zbtn'); if (!b) return;
    if (b.dataset.z === 'fit') return knAjustar();
    knZoom(b.dataset.z === 'in' ? 1.25 : 1 / 1.25);
  });
  // ---- arrastrar el FONDO para moverse por el mundo ----
  stage.addEventListener('mousedown', (e) => {
    if (e.target.closest('.knode') || e.target.closest('#kn-zoom')) return;
    knPan = { x: e.clientX, y: e.clientY, vx: knView.x, vy: knView.y };
    stage.classList.add('panning');
  });
}

/** Nombre del sistema. No se escribe a fuego: quien instale esto lo llama como quiera. */
function sysName() {
  const c = state.config || {};
  return ((c.assistant_name || 'nexus').trim()) || 'nexus';
}

/** Qué carpetas están plegadas. Se recuerda entre recargas de la vista. */
const knPlegadas = new Set();

/**
 * El árbol de la izquierda, como el de cualquier proyecto: la RAÍZ es el
 * sistema, de ella cuelgan las carpetas, y de cada carpeta sus archivos.
 * Las carpetas se pliegan y despliegan con un clic en su triángulo.
 */
function knPintaArbol(raices, porCarpeta, carpetas) {
  const tree = $('#kn-tree');
  if (!tree) return;
  const item = (nm, color) =>
    `<div class="kn-file" data-note="${esc(nm)}" style="--c:${color}">
       <i></i><span>${esc(nm)}</span></div>`;
  const rama = (nombre, color, hijos, conNodo) => {
    const abierta = !knPlegadas.has(nombre);
    return `<div class="kn-folder${abierta ? '' : ' plegada'}" style="--c:${color}">
        <div class="kn-fname"${conNodo ? ` data-note="${esc(nombre)}"` : ''}>
          <span class="kn-tw" data-fold="${esc(nombre)}">${abierta ? '▾' : '▸'}</span>
          <span class="kn-fl">${esc(nombre)}</span> <b>${hijos.length}</b>
        </div>
        <div class="kn-hijos">${hijos.map((n) => item(n, memGroupColor[n] || knNoteColor(n))).join('')}</div>
      </div>`;
  };
  const sueltas = porCarpeta[''] || [];
  const total = raices.reduce((n, c) => n + (porCarpeta[c] || []).length, 0) + sueltas.length;
  let dentro = raices.map((c) => rama(c, memGroupColor[c] || '#7cf6c0', porCarpeta[c] || [], true)).join('');
  if (sueltas.length) dentro += rama('sin carpeta', '#8aa0b3', sueltas, false);

  // La raíz: el propio sistema. Todo el conocimiento cuelga de él, igual que en
  // el grafo de la derecha.
  const raizAbierta = !knPlegadas.has('__raiz__');
  tree.innerHTML = total || raices.length
    ? `<div class="kn-raiz${raizAbierta ? '' : ' plegada'}">
         <div class="kn-rname">
           <span class="kn-tw" data-fold="__raiz__">${raizAbierta ? '▾' : '▸'}</span>
           <span class="kn-fl">${esc(sysName())}</span> <b>${total}</b>
         </div>
         <div class="kn-hijos">${dentro}</div>
       </div>`
    : '<div class="empty">Todavía no hay nada en la memoria.</div>';

  // Plegar y desplegar. El triángulo es SUYO: pulsarlo no abre la nota.
  tree.querySelectorAll('[data-fold]').forEach((tw) => {
    tw.addEventListener('click', (e) => {
      e.stopPropagation();
      const k = tw.dataset.fold;
      if (knPlegadas.has(k)) knPlegadas.delete(k); else knPlegadas.add(k);
      knPintaArbol(raices, porCarpeta, carpetas);
    });
  });
  // Pasar el ratón resalta el nodo en el grafo; pulsar lo abre y lo centra.
  tree.querySelectorAll('[data-note]').forEach((el) => {
    const nombre = el.dataset.note;
    el.addEventListener('mouseenter', () => { const n = knByName[nombre]; if (n) { n.hl = 1; n.el.classList.add('hl'); } });
    el.addEventListener('mouseleave', () => { const n = knByName[nombre]; if (n) { n.hl = 0; n.el.classList.remove('hl'); } });
    el.addEventListener('click', () => {
      const n = knByName[nombre];
      if (n) knCentraEn(n);
      if (n && !n.carpeta) openNote(nombre);
    });
  });
}

/** Deja un nodo en el centro de la ventana sin cambiar el zoom. */
function knCentraEn(n) {
  const stage = $('#kn-stage');
  if (!stage) return;
  knView.x = n.x * knView.z - stage.clientWidth / 2;
  knView.y = n.y * knView.z - stage.clientHeight / 2;
  knLimitaVista();
  knAplicaVista();
}

// arrastre global: nodos y fondo
document.addEventListener('mousemove', (e) => {
  if (knPan) {
    knView.x = knPan.vx - (e.clientX - knPan.x);
    knView.y = knPan.vy - (e.clientY - knPan.y);
    knLimitaVista(); knAplicaVista();
    return;
  }
  if (!knDrag || !knStageEl) return;
  const r = knStageEl.getBoundingClientRect();
  if (Math.hypot(e.clientX - knDrag._sx, e.clientY - knDrag._sy) > 4) knDrag.moved = true;
  // De pantalla a MUNDO: sin deshacer el zoom, el nodo se iría a otra parte.
  const nx = (e.clientX - r.left + knView.x) / knView.z;
  const ny = (e.clientY - r.top + knView.y) / knView.z;
  // Y acotado al mundo: soltar un nodo fuera era lo que descuadraba el grafo.
  const m = knDrag.sz / 2 + 4;
  knDrag.x = Math.min(WORLD.w - m, Math.max(m, nx));
  knDrag.y = Math.min(WORLD.h - m, Math.max(m, ny));
  knDrag.x0 = knDrag.x; knDrag.y0 = knDrag.y;
});
document.addEventListener('mouseup', () => {
  if (knDrag) { knDrag.x0 = knDrag.x; knDrag.y0 = knDrag.y; }   // se queda donde lo sueltas
  knDrag = null;
  if (knPan) { knPan = null; $('#kn-stage')?.classList.remove('panning'); }
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
