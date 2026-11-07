/* ==========================================================
   nexus — piezas de HTML que se repiten en varias vistas.
   Todas devuelven una cadena; ninguna toca el DOM ni el estado.
   ========================================================== */
import { esc } from '../core/dom.js';

/* T18c (la cola de SEC-10): aquí se interpolaban datos sin escapar —`name`,
   `val`, `delta`, `lbl`, `ic`, la `view` de un atributo—. Hoy los llamantes
   pasan literales y números, así que no había nada explotable, pero es
   exactamente la deriva que produjo SEC-10: el día que un dato del servidor
   caiga en el sitio equivocado, ya está abierto. Ahora se escapa TODO.
   `val` de kpi() era una ranura de HTML a propósito (el HUD actualiza tres
   cifras en vivo por su `id`), así que el `id` pasa a ser un parámetro: kpi()
   escapa el valor y lo envuelve en su `<span>`. Las cuatro llamadas reales de
   command.js pintan byte a byte lo mismo que antes (lo compara esta rama en
   tests/unit/frontend/test_escapes_y_cabeceras.py). */

/** Tarjeta de la rejilla de resumen: icono, nombre, subtítulo y piloto ON/OFF. */
export const ovCard = (ic, name, sub, on) =>
  `<div class="ov-card"><div class="ov-ic">${esc(ic)}</div><div><b>${esc(name)}</b>`
  + `<small>${esc(sub)}</small></div>`
  + `<span class="st ${on ? 'on' : 'off'}">${on ? 'ON' : 'OFF'}</span></div>`;

/** Color de cada aguja. Fuera de aquí no lo necesita nadie. */
const GCOL = { cpu: '#22e6ff', ram: '#4d9bff', disk: '#ffd23a', gpu: '#4dff9e' };

/** Aguja circular de porcentaje. El valor lo escribe luego updateMetrics(). */
export const gauge = (k, label) =>
  `<div class="gauge"><div class="ring" id="g-${esc(k)}" style="--gc:${GCOL[k] || '#22d3ee'}">`
  + `<b id="gv-${esc(k)}" style="color:${GCOL[k] || '#eaf6ff'}">0%</b></div>`
  + `<div class="glabel">${esc(label)}</div></div>`;

/** Cifra grande con etiqueta y variación. `id` = nodo que updateMetrics() refresca. */
export const kpi = (lbl, val, delta, cy, id) =>
  `<div class="kpi"><div class="lbl">${esc(lbl)}</div>`
  + `<div class="val ${cy ? 'cy' : ''}">`
  + `${id ? `<span id="${esc(id)}">${esc(val)}</span>` : esc(val)}</div>`
  + `<div class="delta">${esc(delta)}</div></div>`;

/** Chip de acción rápida. El clic lo recoge la delegación del router. */
export const qc = (i, label, cmd, isPrompt, view) =>
  `<div class="qc" data-cmd="${esc(cmd)}" data-prompt="${isPrompt ? 1 : ''}" `
  + `data-view="${esc(view)}"><i>${esc(i)}</i> ${esc(label)}</div>`;

/** Botón de acción del panel lateral de nodo. Lo cablea wireNs(). */
export const nsBtn = (label, cmd, isP, view) =>
  `<button class="ns-act" data-cmd="${esc(cmd)}" data-p="${isP ? 1 : ''}" `
  + `data-v="${esc(view)}">▸ ${esc(label)}</button>`;

/**
 * Orbe de carga: 12 puntos en anillo con desfase creciente → onda.
 * @param {boolean} big  radio grande (24 px) en vez del pequeño (10 px)
 */
export function orbHTML(big) {
  const N = 12, R = big ? 24 : 10;
  let dots = '';
  for (let i = 0; i < N; i++) {
    const a = (i / N) * 2 * Math.PI;
    const tx = (Math.cos(a) * R).toFixed(1) + 'px';
    const ty = (Math.sin(a) * R).toFixed(1) + 'px';
    const d = (-(i / N) * 1.1).toFixed(2) + 's';
    dots += `<i style="--tx:${tx};--ty:${ty};animation-delay:${d}"></i>`;
  }
  return `<span class="orb-load${big ? ' big' : ''}"><b></b>${dots}</span>`;
}
