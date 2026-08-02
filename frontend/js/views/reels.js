/* ==========================================================
   nexus — vista REELS: el analisis de Instagram y la competencia.
   Cada cifra sale con su origen y su metodo; los bloques se pliegan.
   No consulta a Instagram: pinta lo que devuelve /api/reels.
   ========================================================== */
import { $, $$, esc, api } from '../core/dom.js';

/* ═══ REELS · el analisis, no el informe ═══════════════════════════════════
   El .md sirve para archivar. Para MIRARLO hace falta otra cosa: cada bloque
   con su color, plegado por defecto, y —lo importante— cada cifra con SU
   origen y SU calculo a la vista. Un numero que no dice de donde sale es un
   numero que hay que creerse, y de esos ya hay bastantes en Instagram.
   Mismo lenguaje visual que Content OS: color y tamano marcan la jerarquia,
   nunca el grosor de la letra. ════════════════════════════════════════════ */
const IG_SECS = {
  numeros:      { c: '#22e6ff', ic: '◑', t: 'Los números' },
  // competencia
  tabla:        { c: '#22e6ff', ic: '⇋', t: 'Cara a cara' },
  brechas:      { c: '#ff9f45', ic: '△', t: 'Dónde estás por debajo' },
  cuentas:      { c: '#b06cff', ic: '◍', t: 'Qué publica cada una' },
  limites:      { c: '#ff4d6d', ic: '⊘', t: 'Lo que NO se puede ver' },
  descubrimiento: { c: '#3ee98a', ic: '⌕', t: 'Cómo se han encontrado' },
  reparto:      { c: '#b06cff', ic: '▦', t: 'De dónde sale cada comentario' },
  leads:        { c: '#3ee98a', ic: '◆', t: 'Leads' },
  conversion:   { c: '#00e5a0', ic: '⇉', t: 'Conversión' },
  sentimiento:  { c: '#ffd23a', ic: '◕', t: 'Sentimiento' },
  dudas:        { c: '#ff6ec7', ic: '❓', t: 'Lo que más preguntan' },
  objeciones:   { c: '#ff9f45', ic: '⚑', t: 'Objeciones (que son señal)' },
  cola:         { c: '#5b8cff', ic: '▶', t: 'Qué grabar, por orden' },
  retencion:    { c: '#ff4d6d', ic: '◔', t: 'Retención de vídeo' },
  distribucion: { c: '#c6ff3a', ic: '◎', t: 'Distribución' },
  benchmark:    { c: '#a0f0ff', ic: '⇅', t: 'Comparado con tus reels anteriores' },
  ideas:        { c: '#d78bff', ic: '✦', t: 'Ideas del modelo' },
};
// De inicio se abren las tres que contestan «¿ha ido bien?» — el resto, a un clic.
const IG_ABIERTAS_INI = ['numeros', 'leads', 'cola', 'tabla', 'brechas'];
function igAbierta(id) {
  const g = localStorage.getItem('ig_open_' + id);
  return g === null ? IG_ABIERTAS_INI.includes(id) : g === '1';
}
function igSec(id, titulo, n, cuerpo, metodo) {
  const s = IG_SECS[id] || { c: '#8aa0b3', ic: '·', t: titulo }, ab = igAbierta(id);
  return `<section class="cos-sec ig-sec${ab ? ' abierta' : ''}" data-sec="${id}" style="--cos:${s.c}">
    <button class="cos-sec-h" type="button" aria-expanded="${ab}" data-toggle="${id}">
      <span class="cos-sec-ic">${s.ic}</span>
      <span class="cos-sec-t">${esc(titulo || s.t)}</span>
      ${n != null ? `<span class="cos-sec-n">${n}</span>` : ''}
      <span class="cos-sec-ch" aria-hidden="true">⌄</span>
    </button>
    <div class="cos-sec-b">
      ${metodo ? `<p class="ig-metodo"><span>cómo se calcula</span>${esc(metodo)}</p>` : ''}
      ${cuerpo}
    </div>
  </section>`;
}

// Cada metrica con su procedencia: sin esto son cifras que hay que creerse.
function igFilasNumeros(filas) {
  return `<div class="ig-kpis">${filas.map((f) => `
    <div class="ig-kpi">
      <div class="ig-kpi-top">
        <span class="ig-kpi-n">${esc(String(f.valor_txt))}</span>
        <span class="ig-kpi-m">${esc(f.metrica)}</span>
      </div>
      ${f.pista || f.lectura ? `<div class="ig-kpi-l">${esc([f.pista, f.lectura].filter(Boolean).join(' · '))}</div>` : ''}
      <div class="ig-fuente"><span>de dónde sale</span>${esc(f.origen)}${f.como ? `<em>${esc(f.como)}</em>` : ''}</div>
    </div>`).join('')}</div>`;
}

function igReparto(sec) {
  const max = Math.max(1, ...sec.cestas.map((x) => x.n));
  return `<div class="ig-cestas">${sec.cestas.map((x) => `
    <div class="ig-cesta">
      <div class="ig-cesta-h"><span class="ig-cesta-t">${esc(x.cesta)}</span><span class="ig-cesta-n">${x.n}</span></div>
      <div class="ig-barra"><i style="width:${Math.round(x.n / max * 100)}%"></i></div>
      <div class="ig-cesta-q">${esc(x.que_es)}</div>
    </div>`).join('')}
    <div class="ig-suma ${sec.cuadra ? 'ok' : 'mal'}">
      ${sec.cuadra
        ? `✔ ${sec.suma} de ${sec.total}: la suma cuadra`
        : `✖ ${sec.suma} de ${sec.total} — descuadran ${sec.descuadre}, y se dice`}
    </div></div>`;
}

function igLeads(sec) {
  const chips = [
    ['Personas distintas', sec.unicos],
    ['Comentarios con la palabra', sec.cta_totales],
    ['La escribieron mal', sec.con_errata],
    ['Rescatados por tolerar erratas', (sec.tasa_variantes || 0) + ' %'],
  ];
  let hueco = '';
  if (sec.hueco != null) {
    hueco = sec.hueco > 0
      ? `<div class="ig-aviso mal">Quedan ${sec.hueco} sin atender: son leads que pidieron algo y no lo han recibido.</div>`
      : (sec.hueco === 0
        ? `<div class="ig-aviso ok">Atendidos todos: ${sec.atendidos} de ${sec.unicos}.</div>`
        : `<div class="ig-aviso">Hay ${Math.abs(sec.hueco)} respuestas de más que personas: repasa si se duplicaron.</div>`);
  } else {
    hueco = `<div class="ig-aviso">Cuántos recibieron respuesta: no consta. Apúntalo y aquí sale el hueco.</div>`;
  }
  return `<div class="ig-chips">${chips.map(([k, v]) => `<div class="ig-chip"><b>${esc(String(v))}</b><span>${esc(k)}</span></div>`).join('')}</div>
    ${hueco}
    ${sec.calientes && sec.calientes.length ? `<div class="ig-sub">Leads calientes (intención de negocio, más allá del imán)</div>
      ${sec.calientes.map((x) => `<div class="ig-cita"><span>@${esc(x.usuario || '')}</span>${esc(x.comentario || '')}<em>${esc(x.motivo || '')}</em></div>`).join('')}` : ''}
    ${sec.muestra && sec.muestra.length ? `<div class="ig-sub">Quiénes son</div><div class="ig-tags">${sec.muestra.map((x) => `<span class="ig-tag${x.typo ? ' typo' : ''}" title="${x.typo ? 'lo escribió mal y se ha recogido igual' : 'lo escribió bien'}">@${esc(x.usuario || '')} · ${esc(x.escrito_como || '')}</span>`).join('')}</div>` : ''}`;
}

function igConversion(sec) {
  const pasos = (sec.filas || []).map((f) => `
    <div class="ig-paso">
      <span class="ig-paso-t">${esc(f.paso)}</span>
      <span class="ig-paso-v">${f.valor}</span>
      <span class="ig-paso-r">${f.tasa != null ? f.tasa + ' %' : '—'}</span>
    </div>`).join('');
  const faltan = (sec.faltan || []).map((x) => `<li>${esc(x.que)} <em>${esc(x.de_donde)}</em></li>`).join('');
  return `${pasos ? `<div class="ig-embudo">${pasos}</div>` : ''}
    ${sec.tasa_global != null ? `<div class="ig-aviso ok">De cada 100 leads, ${sec.tasa_global} acaban comprando.</div>` : ''}
    ${faltan ? `<div class="ig-sub">Falta por registrar — y por eso NO se estima</div><ul class="ig-faltan">${faltan}</ul>` : ''}
    <p class="ig-nota">${esc(sec.nota || '')}</p>`;
}

function igSentimiento(sec) {
  return `<div class="ig-sent">${sec.categorias.map((c) => `
    <div class="ig-sent-f">
      <span class="ig-sent-t">${esc(c.categoria)}</span>
      <div class="ig-barra"><i style="width:${Math.max(2, Math.round(c.pct))}%"></i></div>
      <span class="ig-sent-p">${c.pct} %</span>
      <span class="ig-sent-b">n=${c.n} · entre ${c.banda[0]} y ${c.banda[1]}</span>
    </div>`).join('')}</div>
    ${sec.aviso ? `<div class="ig-aviso">${esc(sec.aviso)}</div>` : `<div class="ig-aviso ok">Muestra suficiente (n=${sec.muestra}): los porcentajes aguantan.</div>`}`;
}

function igDudas(sec) {
  return sec.grupos.map((g, i) => `<article class="cos-cal-item ig-duda" data-item="${i}">
    <button class="cos-cal-h" type="button" aria-expanded="false">
      <span class="cos-cal-n">${g.veces}×</span>
      <span class="cos-cal-tit">${esc(g.ejemplo)}</span>
      <span class="cos-cal-ch" aria-hidden="true">⌄</span>
    </button>
    <div class="cos-cal-d">
      ${(g.otros || []).map((o) => `<div class="ig-otra">${esc(o)}</div>`).join('')}
      <div class="ig-tags">${(g.usuarios || []).map((u) => `<span class="ig-tag">@${esc(u)}</span>`).join('')}</div>
    </div></article>`).join('');
}

function igObjeciones(sec) {
  return sec.tipos.map((o) => `<div class="ig-obj">
    <div class="ig-obj-h"><span class="ig-obj-t">${esc(o.tipo)}</span><span class="ig-obj-n">${o.veces}×</span></div>
    <div class="ig-obj-l">${esc(o.lectura)}</div>
    ${(o.ejemplos || []).map((e) => `<div class="ig-cita">${esc(e)}</div>`).join('')}
    <div class="ig-tags">${(o.usuarios || []).map((u) => `<span class="ig-tag">@${esc(u)}</span>`).join('')}</div>
  </div>`).join('');
}

function igCola(sec) {
  return sec.ideas.map((idea, i) => `<article class="cos-cal-item ig-idea" data-item="${i}">
    <button class="cos-cal-h" type="button" aria-expanded="false">
      <span class="cos-cal-n">${String(i + 1).padStart(2, '0')}</span>
      <span class="cos-cal-tit">${esc(idea.titulo)}</span>
      <span class="cos-cal-tipo">prioridad ${idea.prioridad}</span>
      <span class="cos-cal-ch" aria-hidden="true">⌄</span>
    </button>
    <div class="cos-cal-d">
      <div class="cos-campo"><span>Gancho</span>${esc(idea.gancho)}</div>
      <div class="cos-campo"><span>Por qué</span>${esc(idea.por_que)}</div>
      <div class="cos-campo"><span>Responde a</span>${(idea.responde_a || []).map((r) => esc(r)).join(' / ')}</div>
      <div class="cos-campo"><span>Lo piden</span>${(idea.usuarios || []).map((u) => '@' + esc(u)).join(', ') || '—'}</div>
    </div></article>`).join('');
}

function igBloqueApi(sec) {
  const hay = (sec.hay || []).map((x) => `<div class="ig-dato"><span>${esc(x.que)}</span><b>${esc(String(x.valor))}</b></div>`).join('');
  const faltan = (sec.faltan || []).map((x) => `<li>${esc(x)}</li>`).join('');
  return `${hay || '<div class="ig-aviso">La API no ha dado ninguna cifra de este bloque.</div>'}
    ${sec.porcentaje_visto != null ? `<div class="ig-aviso ok">Visto de media: ${sec.porcentaje_visto} % del vídeo.</div>` : ''}
    ${faltan ? `<div class="ig-sub">No consta</div><ul class="ig-faltan">${faltan}</ul>` : ''}
    <p class="ig-nota">${esc(sec.nota || '')}</p>`;
}

function igBenchmark(sec) {
  if (!sec.hay) return `<p class="ig-nota">${esc(sec.nota || '')}</p>`;
  return `<div class="ig-bm">${sec.filas.map((f) => `
    <div class="ig-bm-f">
      <span class="ig-bm-t">${esc(f.metrica)}</span>
      <span class="ig-bm-v">${esc(String(f.valor))}</span>
      <span class="ig-bm-m">media ${esc(String(f.media))}</span>
      <span class="ig-bm-d ${f.delta >= 0 ? 'up' : 'dn'}">${f.delta != null ? (f.delta >= 0 ? '▲ ' : '▼ ') + Math.abs(f.delta) + ' %' : '—'}</span>
    </div>`).join('')}</div>
    <p class="ig-nota">Comparado con ${sec.base} reel(s) que ya has analizado.</p>`;
}

function igCuerpo(sec) {
  if (sec.id === 'numeros') return igFilasNumeros(sec.filas);
  if (sec.id === 'reparto') return igReparto(sec);
  if (sec.id === 'leads') return igLeads(sec);
  if (sec.id === 'conversion') return igConversion(sec);
  if (sec.id === 'sentimiento') return igSentimiento(sec);
  if (sec.id === 'dudas') return igDudas(sec);
  if (sec.id === 'objeciones') return igObjeciones(sec);
  if (sec.id === 'cola') return igCola(sec);
  if (sec.id === 'retencion' || sec.id === 'distribucion') return igBloqueApi(sec);
  if (sec.id === 'benchmark') return igBenchmark(sec);
  if (sec.id === 'ideas') return (sec.lista || []).map((x) => `<div class="cos-idea">${esc(x)}</div>`).join('');
  return '';
}

// Comparar cuentas de tamaños distintos exige la misma vara: por eso todo va
// sobre SEGUIDORES, y en mediana. Y lo que la API no deja ver de una cuenta
// ajena se enseña como bloque propio, no se calla.
function igTabla(sec) {
  const cabecera = sec.filas[0].valores.map((v) =>
    `<th class="${v.es_tuya ? 'tuya' : ''}">${v.es_tuya ? 'TÚ · ' : ''}@${esc(v.usuario)}</th>`).join('');
  const filas = sec.filas.map((f) => `<tr>
      <th scope="row">${esc(f.metrica)}${f.unidad ? ` <span>${esc(f.unidad)}</span>` : ''}</th>
      ${f.valores.map((v) => `<td class="${v.es_tuya ? 'tuya' : ''}${v.usuario === f.lider ? ' lider' : ''}">
          ${v.valor == null ? '<em>no consta</em>' : esc(String(v.valor_txt != null ? v.valor_txt : v.valor))}</td>`).join('')}
    </tr>`).join('');
  return `<div class="ig-tabla-wrap"><table class="ig-tabla">
    <thead><tr><th></th>${cabecera}</tr></thead><tbody>${filas}</tbody></table></div>`;
}

function igBrechas(sec) {
  return sec.filas.map((b) => `<div class="ig-brecha ${b.diferencia >= 0 ? 'up' : 'dn'}">
    <div class="ig-brecha-h">
      <span class="ig-brecha-t">${esc(b.que)}</span>
      <span class="ig-brecha-d">${b.diferencia >= 0 ? '▲ +' : '▼ '}${b.diferencia} %</span>
    </div>
    <div class="ig-brecha-c">tú ${esc(String(b.tuyo))} · ellos ${esc(String(b.de_ellos))} — ${esc(b.lectura)}</div>
  </div>`).join('');
}

// 50000 -> «50.000». Una cifra sin separadores no se lee de un vistazo, y de
// eso va toda esta pantalla.
const igNum = (x) => (typeof x === 'number' ? x.toLocaleString('es-ES') : x);

// Qué está creando: cómo engancha, cómo escribe, cuándo publica y qué se le
// ha salido de su propia norma. Cada conclusión con su n a la vista: si no
// hay muestra suficiente se dice, no se sienta cátedra con dos publicaciones.
function igRadiografia(r) {
  const g = r.gancho || {}, c = r.caption || {}, rm = r.ritmo || {}, o = r.outliers || {};
  const u = r.unidad || 'reproducciones';
  // Cada bloque dice QUÉ se está midiendo y con qué unidad. Antes salía
  // «pregunta 5× 25.400» a secas: ni qué es «pregunta», ni qué es ese número.
  const fila = (f) => `<div class="ig-hook${f.tipo === g.mejor ? ' gana' : ''}">
      <div class="ig-hook-h">
        <span class="ig-hook-t">${esc(f.tipo)}</span>
        ${f.tipo === g.mejor ? '<span class="ig-hook-gana">lo que mejor le funciona</span>' : ''}
        ${f.concluyente ? '' : '<span class="ig-hook-poco">pocos datos</span>'}
        <span class="ig-hook-n">${f.n} ${f.n === 1 ? 'publicación' : 'publicaciones'} · ${igNum(f.rendimiento)} ${esc(u)} de mediana</span>
      </div>
      <div class="ig-hook-q">${esc(f.que_es || '')}</div>
    </div>`;
  return `<div class="ig-radio">
    <div class="ig-radio-cab">
      <span class="ig-radio-quien">@${esc(r.usuario || '')}</span>
      <span class="ig-radio-meta">${r.publicaciones} publicaciones analizadas · ${esc(r.desde || '')} → ${esc(r.hasta || '')}</span>
    </div>
    ${r.aviso ? `<div class="ig-aviso">${esc(r.aviso)}</div>` : ''}

    <div class="ig-sub">Cómo engancha</div>
    <p class="ig-nota">Qué recurso usa en la PRIMERA línea del pie, que es lo único
      que se lee antes del «… más». Al lado, cuántas veces lo ha usado y cuántas
      ${esc(u)} consigue de mediana con él.</p>
    ${(g.filas || []).map(fila).join('')}
    ${g.nota ? `<p class="ig-nota">${esc(g.nota)}</p>` : ''}
    ${g.palabras_mediana ? `<p class="ig-nota">Sus ganchos tienen ${igNum(g.palabras_mediana)} palabras de mediana.</p>` : ''}

    <div class="ig-sub">Cómo escribe</div>
    <div class="ig-chips">
      <div class="ig-chip"><b>${igNum(c.caracteres_mediana)}</b><span>caracteres por pie</span></div>
      <div class="ig-chip"><b>${igNum(c.hashtags_mediana)}</b><span>hashtags por pie</span></div>
      <div class="ig-chip"><b>${c.pct_con_llamada} %</b><span>de sus pies piden algo</span></div>
    </div>
    <p class="ig-nota">${esc(c.lectura || '')}</p>

    ${rm.hay ? `<div class="ig-sub">Cuándo publica</div>
      <div class="ig-dato"><span>Publicaciones por semana</span><b>${rm.por_semana}</b></div>
      ${rm.mejor_dia ? `<div class="ig-dato"><span>Día con más ${esc(u)} de mediana</span><b>${esc(rm.mejor_dia)}</b></div>` : ''}
      ${(rm.franjas || []).length ? `<div class="ig-dato"><span>Franja con más ${esc(u)} de mediana</span><b>${esc(rm.franjas[0].franja)}</b></div>` : ''}
      ${rm.nota ? `<p class="ig-nota">${esc(rm.nota)}</p>` : ''}` : ''}

    <div class="ig-sub">Lo que se le ha salido de la norma</div>
    <p class="ig-nota">${esc(o.nota || '')}</p>
    ${(o.lista || []).map((x) => `<article class="ig-pico">
        <div class="ig-pico-h">
          <span class="ig-pico-x">${x.multiplicador}× su mediana</span>
          <span class="ig-pico-m">@${esc(r.usuario || '')} · ${esc(x.cuando)} · ${esc(x.formato)}</span>
          ${x.enlace ? `<a href="${esc(x.enlace)}" target="_blank" rel="noopener">ver</a>` : ''}
        </div>
        <div class="ig-pico-cifras">
          <span><b>${igNum(x.rendimiento)}</b> ${esc(x.unidad || u)}</span>
          <span><b>${igNum(x.me_gusta)}</b> me gusta</span>
          <span><b>${igNum(x.comentarios)}</b> comentarios</span>
        </div>
        <div class="ig-pico-g"><span>gancho</span>«${esc(x.gancho)}»
          <em>${(x.tipos_de_gancho || []).map(esc).join(' · ')}</em></div>
      </article>`).join('')}
    ${(o.que_comparten || []).length ? `<p class="ig-nota">Lo que comparten sus picos:
      ${(o.que_comparten || []).map((x) => `${esc(x.tipo)} (${x.veces})`).join(', ')}.</p>` : ''}

    ${(r.angulos || []).length ? `<div class="ig-sub">De qué habla</div>
      <p class="ig-nota">Palabras que repite en sus pies y las ${esc(u)} de mediana
        que consigue cuando habla de eso.</p>
      ${(r.angulos || []).map((a) => `<div class="ig-dato">
          <span>${esc(a.tema)} <i>en ${a.n} ${a.n === 1 ? 'publicación' : 'publicaciones'}</i></span>
          <b>${igNum(a.rendimiento)}</b></div>`).join('')}` : ''}
  </div>`;
}

// Qué sale en las portadas y qué de eso funciona. Si no hay modelo de visión,
// se enseña el motivo: un bloque vacío no lo entiende nadie.
function igVisual(c) {
  const e = c.visual_estado, v = c.visual;
  if (!e && !v) return '';
  if (!v) return `<div class="ig-sub">Qué sale en los vídeos</div>
    <div class="ig-aviso">${esc((e || {}).texto || 'No se han podido mirar las portadas.')}</div>`;
  return `<div class="ig-sub">Qué sale en los vídeos</div>
    <p class="ig-nota">${esc((e || {}).texto || '')}</p>
    <p class="ig-nota">${esc(v.metodo || '')}</p>
    ${(v.bloques || []).map((b) => `<div class="ig-vis">
        <div class="ig-vis-h">
          <span class="ig-vis-t">${esc(b.titulo)}</span>
          ${b.fiabilidad !== 'alta' ? `<span class="ig-vis-f">fiabilidad ${esc(b.fiabilidad)}</span>` : ''}
          ${b.mejor ? `<span class="ig-vis-gana">le funciona: ${esc(b.mejor)}</span>` : ''}
        </div>
        ${b.atributo === 'genero_aparente' ? `<div class="ig-aviso">${esc(v.aviso_genero)}</div>` : ''}
        ${(b.filas || []).map((f) => `<div class="ig-dato">
            <span>${esc(f.valor)} <i>en ${f.n} ${f.n === 1 ? 'publicación' : 'publicaciones'}</i>${
              f.concluyente ? '' : ' <em class="ig-hook-poco">pocos datos</em>'}</span>
            <b>${igNum(f.rendimiento)}${f.vs_mediana != null ? ` · ${f.vs_mediana}× su mediana` : ''}</b>
          </div>`).join('')}
        ${b.nota ? `<p class="ig-nota">${esc(b.nota)}</p>` : ''}
      </div>`).join('')}`;
}

function igCuentas(sec) {
  return sec.cuentas.map((c, i) => `<article class="cos-cal-item ig-cuenta" data-item="${i}">
    <button class="cos-cal-h" type="button" aria-expanded="false">
      <span class="cos-cal-n">@</span>
      <span class="cos-cal-tit">${esc(c.usuario)}</span>
      <span class="cos-cal-tipo">${esc(String(igNum(c.seguidores)))} seguidores</span>
      <span class="cos-cal-ch" aria-hidden="true">⌄</span>
    </button>
    <div class="cos-cal-d">
      ${c.bio ? `<div class="cos-campo"><span>Bio</span>${esc(c.bio)}</div>` : ''}
      <div class="cos-campo"><span>Publica</span>${c.por_semana != null ? c.por_semana + ' veces por semana' : 'no se puede calcular'}</div>
      <div class="cos-campo"><span>Analizadas</span>${c.analizadas} de ${c.publicaciones_totales}</div>
      <div class="ig-sub">Qué formato le funciona</div>
      ${(c.formatos || []).map((f) => `<div class="ig-dato">
          <span>${esc(f.formato)} · ${f.n}</span>
          <b>${f.reproducciones == null ? '—' : esc(String(igNum(f.reproducciones))) + ' repr.'}</b></div>`).join('')}
      <div class="ig-sub">Lo que más le ha funcionado</div>
      ${(c.mejores || []).map((m) => `<div class="ig-cita">
          <span>${esc(m.cuando)} · ${esc(m.formato)} · ${m.reproducciones == null ? igNum(m.me_gusta) + ' me gusta' : igNum(m.reproducciones) + ' reproducciones'}</span>
          ${esc(m.caption)}</div>`).join('')}
      ${c.radiografia ? igRadiografia(c.radiografia) : ''}
      ${igVisual(c)}
    </div></article>`).join('');
}

function igLimites(sec) {
  return `<div class="ig-limites">${sec.limites.map((l) => `<div class="ig-limite">
    <div class="ig-limite-t">${esc(l.que)}</div>
    <div class="ig-limite-p">${esc(l.por_que)}</div>
    <div class="ig-limite-d">${esc(l.donde)}</div>
  </div>`).join('')}</div>`;
}

// La trazabilidad, también en el descubrimiento: qué nicho se dedujo, qué se
// buscó, cuántas salieron y por qué se cayó cada una. Una lista de
// competidores sin decir de dónde sale es una lista que hay que creerse.
function igDescubrimiento(sec) {
  const d = sec.datos;
  return `<div class="ig-chips">
      <div class="ig-chip"><b>${d.candidatos}</b><span>encontradas</span></div>
      <div class="ig-chip"><b>${d.validados}</b><span>confirmadas por Meta</span></div>
      <div class="ig-chip"><b>${(d.descartados || []).length}</b><span>descartadas</span></div>
    </div>
    <div class="ig-sub">Tu nicho, deducido de lo que publicas</div>
    <div class="ig-tags">${(d.nicho.terminos || []).map((t) => `<span class="ig-tag">${esc(t)}</span>`).join('')}</div>
    <div class="ig-fuente"><span>confianza</span>${esc(d.nicho.confianza)}${
      d.nicho.aviso ? `<em>${esc(d.nicho.aviso)}</em>` : ''}</div>
    <div class="ig-sub">Lo que se ha buscado por internet</div>
    ${(d.consultas || []).map((q) => `<div class="ig-otra">· ${esc(q)}</div>`).join('')}
    ${(d.descartados || []).length ? `<div class="ig-sub">Por qué se ha caído cada una</div>
      ${(d.descartados || []).map((x) => `<div class="ig-cita"><span>@${esc(x.usuario)}</span>${esc(x.motivo)}</div>`).join('')}` : ''}`;
}

function igCuerpoComp(sec) {
  if (sec.id === 'descubrimiento') return igDescubrimiento(sec);
  if (sec.id === 'tabla') return igTabla(sec);
  if (sec.id === 'brechas') return igBrechas(sec);
  if (sec.id === 'cuentas') return igCuentas(sec);
  if (sec.id === 'limites') return igLimites(sec);
  return '';
}

// Los desplegables: cada seccion recuerda si la dejaste abierta, y cada ficha
// (idea, cuenta) se abre sin recordarse, que son de mirar y cerrar.
function igEngancha(box) {
  box.querySelectorAll('.cos-sec-h').forEach((b) => b.addEventListener('click', () => {
    const sec = b.closest('.cos-sec'), id = b.dataset.toggle;
    const ab = sec.classList.toggle('abierta');
    b.setAttribute('aria-expanded', ab ? 'true' : 'false');
    localStorage.setItem('ig_open_' + id, ab ? '1' : '0');
  }));
  box.querySelectorAll('.cos-cal-h').forEach((b) => b.addEventListener('click', () => {
    const it = b.closest('.cos-cal-item');
    const ab = it.classList.toggle('abierta');
    b.setAttribute('aria-expanded', ab ? 'true' : 'false');
  }));
}

async function pintaCompetencia(box) {
  const d = await api('/api/instagram/competencia');
  if (!d) { box.innerHTML = '<div class="empty">No he podido cargar la comparativa.</div>'; return; }
  if (!d.hay) {
    box.innerHTML = `<div class="ig-vacio">
      <div class="ig-vacio-ic">⇋</div>
      <div class="ig-vacio-t">Todavía no has comparado ninguna cuenta</div>
      <div class="ig-vacio-d">${esc(d.texto || '')}</div>
    </div>`;
    return;
  }
  const p = d.panel || {};
  box.innerHTML = `<div class="ig-reel">
    <header class="ig-head">
      <div class="ig-head-m"><span>comparativa del ${esc((d.cuando || '').slice(0, 10))}</span>
        <span class="ig-solo">solo lectura · API oficial, sin scraping</span></div>
    </header>
    ${(p.fallidas || []).length ? `<div class="ig-aviso mal">No se han podido consultar: ${
      (p.fallidas || []).map((f) => '@' + esc(f.usuario)).join(', ')
    }. La API solo deja ver cuentas profesionales públicas.</div>` : ''}
    <div class="cos-secs">${[
      ...(p.descubrimiento ? [{
        id: 'descubrimiento', titulo: 'Cómo se han encontrado',
        n: p.descubrimiento.validados, datos: p.descubrimiento,
        metodo: 'Buscar es amplio y se hace por internet; validar es exacto y lo '
              + 'hace Meta. Ninguna cuenta entra aquí sin que la API la confirme, '
              + 'y la que se cae, se cae diciendo por qué.',
      }] : []),
      ...(p.secciones || []),
    ].map((s) => igSec(s.id, s.titulo, s.n, igCuerpoComp(s), s.metodo)).join('')}</div>
  </div>`;
  igEngancha(box);
}

export async function mountReels() {
  const box = $('#ig'); if (!box) return;
  const activa = localStorage.getItem('ig_tab') || 'mios';
  $$('.ig-tab').forEach((b) => {
    b.classList.toggle('activa', b.dataset.tab === activa);
    b.setAttribute('aria-selected', b.dataset.tab === activa ? 'true' : 'false');
    if (b._wired) return;
    b._wired = 1;
    b.addEventListener('click', () => {
      localStorage.setItem('ig_tab', b.dataset.tab);
      mountReels();
    });
  });
  if (activa === 'competencia') { await pintaCompetencia(box); return; }
  const d = await api('/api/instagram/analisis');
  if (!d) { box.innerHTML = '<div class="empty">No he podido cargar el análisis.</div>'; return; }
  if (!d.hay) {
    box.innerHTML = `<div class="ig-vacio">
      <div class="ig-vacio-ic">◑</div>
      <div class="ig-vacio-t">Todavía no hay análisis</div>
      <div class="ig-vacio-d">${esc(d.texto || '')}</div>
    </div>`;
    return;
  }
  const reels = d.reels || [];
  box.innerHTML = reels.map((r, i) => {
    const res = r.resumen || {};
    return `<div class="ig-reel" data-reel="${i}">
      <header class="ig-head">
        <div class="ig-head-t">${esc(r.reel.caption || r.reel.id || 'Reel')}</div>
        <div class="ig-head-m">
          <span>${esc(r.reel.cuando || '')}</span>
          <span>${esc(r.reel.tipo || '')}</span>
          ${r.reel.permalink ? `<a href="${esc(r.reel.permalink)}" target="_blank" rel="noopener">ver en Instagram</a>` : ''}
          <span class="ig-solo">solo lectura · no se ha tocado la cuenta</span>
        </div>
        <div class="ig-resumen">
          <div class="ig-chip"><b>${esc(String(res.alcance))}</b><span>alcance</span></div>
          <div class="ig-chip"><b>${res.comentarios}</b><span>comentarios</span></div>
          <div class="ig-chip"><b>${res.leads}</b><span>leads</span></div>
          <div class="ig-chip"><b>${res.con_contenido}</b><span>con contenido</span></div>
          <div class="ig-chip ${res.cuadra ? 'ok' : 'mal'}"><b>${res.cuadra ? '✔' : '✖'}</b><span>${res.cuadra ? 'la suma cuadra' : 'no cuadra'}</span></div>
        </div>
        ${r.odio && r.odio.n ? `<div class="ig-aviso mal">${r.odio.n} comentario(s) de odio, contados aparte: no son objeciones.</div>` : ''}
      </header>
      <div class="cos-secs">${(r.secciones || []).map((s) => igSec(s.id, s.titulo, s.n, igCuerpo(s), s.metodo)).join('')}</div>
    </div>`;
  }).join('');

  igEngancha(box);
}

