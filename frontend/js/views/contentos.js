/* ==========================================================
   nexus — vista CONTENT OS: plan, ideas, salud, aprendizajes.
   Cada dato lleva marca de origen (medido / demostracion / nada),
   que es lo que impide que el panel finja haber medido algo.
   ========================================================== */
import { $, esc, api } from '../core/dom.js';
import { state } from '../core/state.js';

/* ═══ CONTENT OS ═══════════════════════════════════════════════════════════
   Rediseño (30/07/2026). Estaba TODO del mismo color, con negritas por todas
   partes y las listas abiertas de par en par: un muro gris imposible de leer.
   Ahora cada bloque tiene SU color flúor —el mismo criterio que los iconos del
   sidebar— y todos se pliegan, con el recuento a la vista, para que puedas
   abrir solo lo que estás mirando. Sin <b>: la jerarquía la marcan el color y
   el tamaño, no el grosor. ══════════════════════════════════════════════ */
const COS_SECS = {
  plan:     { c: '#22e6ff', ic: '▤', t: 'Plan de contenido' },
  ideas:    { c: '#b06cff', ic: '✦', t: 'Lluvia de ideas' },
  salud:    { c: '#3ee98a', ic: '◍', t: 'Salud del sistema' },
  aprende:  { c: '#ffd23a', ic: '◈', t: 'Aprendizajes' },
  inspira:  { c: '#ff6ec7', ic: '❋', t: 'Inspiraciones' },
  guion:    { c: '#ff9f45', ic: '▶', t: 'Guion con IA' },
  metricas: { c: '#5b8cff', ic: '◑', t: 'Métricas' },
};
// Qué secciones deja abiertas de inicio (y recuerda lo que tú elijas después).
const COS_ABIERTAS_INI = ['plan', 'ideas'];
function cosAbierta(id) {
  const g = localStorage.getItem('cos_open_' + id);
  return g === null ? COS_ABIERTAS_INI.includes(id) : g === '1';
}
function cosPanel(id, cuerpo, n, extra) {
  const s = COS_SECS[id], ab = cosAbierta(id);
  return `<section class="cos-sec${ab ? ' abierta' : ''}" data-sec="${id}" style="--cos:${s.c}">
    <button class="cos-sec-h" type="button" aria-expanded="${ab}" data-toggle="${id}">
      <span class="cos-sec-ic">${s.ic}</span>
      <span class="cos-sec-t">${s.t}</span>
      ${n != null ? `<span class="cos-sec-n">${n}</span>` : ''}
      ${extra ? `<span class="cos-sec-x">${extra}</span>` : ''}
      <span class="cos-sec-ch" aria-hidden="true">⌄</span>
    </button>
    <div class="cos-sec-b">${cuerpo}</div>
  </section>`;
}

// Vocabulario de Content OS: llega DENTRO del payload (config/umbrales.json).
// El HUD no tiene ni un rótulo de procedencia a fuego.
let COS_VOC = {};

const cosCls = (o) => o === 'medido' ? 'ok' : o === 'demostración' ? 'demo' : 'nada';

/* El chip de procedencia de un bloque entero. El badge de la cabecera no
   bastaba: bastaba con hacer scroll para perderlo de vista y volver a leer
   los KPIs como si fueran tuyos. Va en CADA bloque que enseñe demostración. */
function cosMarca(origen) {
  const et = (COS_VOC.etiquetas || {})[origen];
  const tx = COS_VOC.textos || {};
  return `<span class="cos-marca ${cosCls(origen)}">${esc(et || tx.sin_procedencia || 'sin procedencia')}</span>`;
}

/* EL ÚNICO CAMINO DE UNA CIFRA A LA PANTALLA.

   Si el valor no llega dentro de un sobre `{valor, origen, …}`, esto NO pinta
   el número: pinta «— sin procedencia». Es deliberado y es una red, no un
   adorno. El incidente de 01/08/2026 fue justo esto: números de un dataset de
   mentira pintados igual que los de la Graph API, indistinguibles mirando la
   pantalla. Cualquier fuga futura del contrato se ve aquí en vez de colarse. */
function cosDato(s, fmt, sufijo) {
  const tx = COS_VOC.textos || {}, et = COS_VOC.etiquetas || {};
  if (!s || typeof s !== 'object' || !et[s.origen]) {
    return { v: '—', cls: 'nada', et: tx.sin_procedencia || 'sin procedencia',
             aviso: '', delta: null, periodo: '' };
  }
  const vacio = (s.valor === null || s.valor === undefined);
  return {
    v: vacio ? '—' : ((fmt ? fmt(s.valor) : String(s.valor)) + (sufijo || '')),
    cls: cosCls(s.origen), et: et[s.origen], aviso: s.aviso || '',
    delta: vacio ? null : s.delta, periodo: s.periodo || '',
  };
}

export async function mountContentOS() {
  const box = $('#cos'); if (!box) return;
  const d = await api('/api/contentos');
  if (!d) { box.innerHTML = '<div class="empty">No he podido cargar Content OS.</div>'; return; }
  const k = d.kpis || {}, na = d.next_action || {}, ev = d.evidence || {};
  COS_VOC = d.vocabulario || {};
  const vac = d.vacios || {};
  // Los deltas ya no se pintan aquí: viajan DENTRO del sobre y los pinta
  // `cosKpi()`, que sabe callarse cuando no hay con qué comparar. Antes, el
  // delta de alcance caía a cero y se pintaba «▲ 0 %» en verde: una medida.
  const confCls = { 'consistente': 'c', 'prometedora': 'p', 'observación': 'o' };

  // ── Plan: cada publicación se abre para ver su ficha ──────────────────
  const cal = (d.calendar || []).map((p, i) => `<article class="cos-cal-item" data-item="${i}">
      <button class="cos-cal-h" type="button" aria-expanded="false">
        <span class="cos-cal-n">${String(p.n).padStart(2, '0')}</span>
        <span class="cos-cal-tit">${esc(p.title)}</span>
        <span class="cos-cal-tipo">${esc(p.type)}</span>
        <span class="cos-est cos-est-${(p.status || '').toLowerCase().normalize('NFD').replace(/[^a-z]/g, '')}">${esc(p.status)}</span>
        <span class="cos-cal-ch" aria-hidden="true">⌄</span>
      </button>
      <div class="cos-cal-d">
        <div class="cos-campo"><span>Cuándo</span>${esc(p.when || '—')}</div>
        <div class="cos-campo"><span>Formato</span>${esc(p.type || '—')}</div>
        <div class="cos-campo"><span>Estado</span>${esc(p.status || '—')}</div>
        ${p.note ? `<div class="cos-campo"><span>Nota</span>${esc(p.note)}</div>` : ''}
      </div>
    </article>`).join('') || `<div class="empty">${esc(vac.calendar || '—')}</div>`;

  const ideas = (d.ideas || []).map((i) => `<div class="cos-idea">${esc(i)}</div>`).join('')
    || `<div class="empty">${esc(vac.ideas || '—')}</div>`;
  const insp = (d.inspirations || []).map((i) =>
    `<div class="cos-insp"><span class="cos-insp-src">${esc(i.src || '')}</span>
      <span class="cos-insp-n">${esc(i.note || '')}</span></div>`).join('')
    || `<div class="empty">${esc(vac.inspirations || '—')}</div>`;
  // Un apunte se pinta como apunte: sin punto de color de confianza y con el
  // rótulo «apunte tuyo, sin evidencia». Antes, un `confCls[l.conf] || 'o'`
  // le ponía «observación» a cualquier cosa que no trajera etiqueta.
  const learn = (d.learnings || []).map((l) =>
    `<div class="cos-learn ${l.conf ? (confCls[l.conf] || 'o') : 'apunte'}"><span class="cos-dot"></span>
      <div class="cos-learn-t">${esc(l.text)}<em>${esc(l.conf || l.etiqueta || '')}</em></div></div>`).join('')
    || `<div class="empty">${esc(vac.learnings || '—')}</div>`;
  const best = (d.best || []).map((b) => `<div class="cos-rank up">▲ <span class="cos-rank-n">${esc(b.name)}</span><span>${b.eng}</span></div>`).join('');
  const worst = (d.worst || []).map((b) => `<div class="cos-rank dn">▼ <span class="cos-rank-n">${esc(b.name)}</span><span>${b.eng}</span></div>`).join('');

  box.innerHTML = `
    <div class="cos-head">
      <div><div class="cos-hello">Hola, ${esc(d.username || d.operator || '')}.</div>
        <div class="cos-sub">Content OS · Inteligencia de Instagram</div></div>
      <span class="cos-conn ${d.connected ? 'ok' : 'demo'}">${d.connected ? '● Instagram conectado' : '○ demo (conecta IG en ⚙ → APIS)'}</span>
    </div>
    <div class="cos-next">
      <div class="cos-next-ic">✦</div>
      <div class="cos-next-body">
        <div class="cos-tag">${esc(na.signal || 'Señal')} ${cosMarca(na.origen)}</div>
        <h3>${esc(na.title || '')}</h3><p>${esc(na.detail || '')}</p>
        <span class="cos-mini">${na.analyzed || 0} publicaciones analizadas</span>
      </div>
    </div>
    <div class="cos-bloque-m">Cifras del panel: ${cosMarca(d.modo)}</div>
    <div class="cos-kpis">
      ${cosKpi('Seguidores', k.followers, fmtN)}
      ${cosKpi('Alcance mensual', k.reach_month, fmtN)}
      ${cosKpi('Retención media', k.retention, null, '%')}
      ${cosKpi('Publicaciones', k.media_count, fmtN)}
    </div>
    <div class="cos-secs">
      ${cosPanel('plan', `<div class="cos-cal">${cal}</div>`, (d.calendar || []).length)}
      ${cosPanel('ideas', `<div class="cos-gen"><input id="cos-idea-in" placeholder="tema (opcional)…"><button id="cos-idea-btn">✦ Generar idea IA</button></div>
        <div id="cos-ideas" class="cos-ideas">${ideas}</div>`, (d.ideas || []).length)}
      ${cosPanel('aprende', `<div class="cos-learns">${learn}</div>`, (d.learnings || []).length,
        ev.complete_pct == null ? `${ev.apuntes || 0} apuntes, sin evidencia`
          : `${ev.complete_pct}% de datos`)}
      ${cosPanel('inspira', `<div class="cos-insps">${insp}</div>`, (d.inspirations || []).length)}
      ${cosPanel('guion', `<div class="cos-gen"><input id="cos-script-in" placeholder="tema del reel…"><button id="cos-script-btn">▶ Generar guion</button></div>
        <div id="cos-script" class="cos-script"></div>`, null)}
      ${cosPanel('salud', `<div class="cos-health">
          <!-- El 0 de --p es la LONGITUD del arco cuando no hay nada que dibujar,
               no un porcentaje: el número que se lee es «—», y el anillo va gris. -->
          <div class="cos-ring ${ev.complete_pct == null ? 'nada' : ''}" style="--p:${ev.complete_pct == null ? 0 : ev.complete_pct}"><b>${ev.complete_pct == null ? '—' : ev.complete_pct + '%'}</b><small>datos</small></div>
          <div class="cos-ev">
            <div><span class="cos-dot c"></span>${ev.consistent || 0} consistentes</div>
            <div><span class="cos-dot p"></span>${ev.promising || 0} prometedoras</div>
            <div><span class="cos-dot o"></span>${ev.observations || 0} observaciones</div>
            <div><span class="cos-dot"></span>${ev.apuntes || 0} apuntes tuyos, sin evidencia</div>
          </div>
        </div>
        <div class="cos-mini">${esc(ev.unidad || '')}: ${ev.n || 0}${ev.suficiente ? '' : ' ⚠'}</div>
        ${ev.aviso ? `<div class="cos-aviso">${esc(ev.aviso)}</div>` : ''}`, null)}
      ${cosPanel('metricas', `<div class="cos-bloque-m">Gráficas y ranking: ${cosMarca(d.modo)}</div>
        <div class="cos-charts">
        ${cosChart('Seguidores (30 días)', 'ch-foll')}
        ${cosChart('Alcance por publicación', 'ch-reach')}
        ${cosChart('Rendimiento vs. mediana', 'ch-dev')}
        ${cosChart('Mezcla de contenido', 'ch-pie')}
        ${cosChart('Hora de publicación vs. engagement', 'ch-scatter')}
        <div class="panel cos-chart"><h2>Mejores y peores</h2>
          <div class="cos-bloque-m">${cosMarca(d.modo)}</div>
          <div class="cos-ranks">${best}${worst}</div></div>
      </div>`, null, cosMarca(d.modo))}
    </div>`;

  // ── plegar / desplegar, y que lo recuerde ─────────────────────────────
  box.querySelectorAll('.cos-sec-h').forEach((b) => b.addEventListener('click', () => {
    const sec = b.closest('.cos-sec'), id = b.dataset.toggle;
    const ab = sec.classList.toggle('abierta');
    b.setAttribute('aria-expanded', String(ab));
    localStorage.setItem('cos_open_' + id, ab ? '1' : '0');
    if (ab && id === 'metricas') requestAnimationFrame(pintaGraficos);
  }));
  box.querySelectorAll('.cos-cal-h').forEach((b) => b.addEventListener('click', () => {
    const it = b.closest('.cos-cal-item');
    const ab = it.classList.toggle('abierta');
    b.setAttribute('aria-expanded', String(ab));
  }));

  // Los gráficos se pintan cuando su sección está VISIBLE: dibujar sobre un
  // canvas plegado (ancho 0) sale en blanco.
  function pintaGraficos() {
    const C = window.WABIKS_CHARTS, ch = d.charts || {};
    if (!C || !$('#ch-foll')) return;
    try {
      C.line($('#ch-foll'), ch.followers || {});
      C.bars($('#ch-reach'), ch.reach || {});
      C.deviation($('#ch-dev'), ch.deviation || []);
      C.pie($('#ch-pie'), ch.pie || []);
      C.scatter($('#ch-scatter'), ch.scatter || [], { xlabel: 'hora del día' });
    } catch (e) { /* noop */ }
  }
  if (cosAbierta('metricas')) requestAnimationFrame(pintaGraficos);
  // generar idea
  $('#cos-idea-btn').addEventListener('click', async () => {
    const btn = $('#cos-idea-btn'); btn.disabled = true; btn.textContent = '…pensando';
    const r = await api('/api/contentos/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind: 'idea', topic: $('#cos-idea-in').value }) });
    if (r && r.text) $('#cos-ideas').insertAdjacentHTML('afterbegin', `<div class="cos-idea nueva">${esc(r.text)}</div>`);
    btn.disabled = false; btn.textContent = '✦ Generar idea IA'; $('#cos-idea-in').value = '';
  });
  // generar guion
  $('#cos-script-btn').addEventListener('click', async () => {
    const btn = $('#cos-script-btn'), out = $('#cos-script');
    btn.disabled = true; btn.textContent = '…escribiendo'; out.textContent = '';
    const r = await api('/api/contentos/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind: 'script', topic: $('#cos-script-in').value }) });
    out.textContent = (r && r.text) || 'No pude generar el guion.';
    btn.disabled = false; btn.textContent = '▶ Generar guion';
  });
}
/* Una tarjeta de KPI recibe el SOBRE entero, no un número ya cocinado. Así el
   rótulo de procedencia y el motivo de un dato que falta viajan pegados a la
   cifra y no hay forma de pintar uno sin el otro. */
function cosKpi(lbl, sobre, fmt, sufijo) {
  const s = cosDato(sobre, fmt, sufijo);
  const d = (s.delta === null || s.delta === undefined || isNaN(s.delta)) ? ''
    : `<span class="cos-delta ${s.delta >= 0 ? 'up' : 'dn'}">${s.delta >= 0 ? '▲' : '▼'} ${Math.abs(s.delta)}%</span> `;
  return `<div class="cos-kpi ${s.cls}">
    <div class="cos-kpi-l">${lbl}</div>
    <div class="cos-kpi-v">${s.v}</div>
    <div class="cos-kpi-d">${d}<span class="cos-marca ${s.cls}">${esc(s.et)}</span></div>
    ${(s.aviso || s.periodo) ? `<div class="cos-kpi-av">${esc(s.aviso || s.periodo)}</div>` : ''}
  </div>`;
}
const cosChart = (title, id) => `<div class="panel cos-chart"><h2>${title}</h2><canvas id="${id}"></canvas></div>`;
const fmtN = (n) => { n = Number(n) || 0; return n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'K' : String(n); };
