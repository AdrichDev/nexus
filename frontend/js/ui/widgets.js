/* ==========================================================
   nexus — piezas de HTML que se repiten en varias vistas.
   Todas devuelven una cadena; ninguna toca el DOM ni el estado.
   ========================================================== */
import { esc } from '../core/dom.js';

/** Tarjeta de la rejilla de resumen: icono, nombre, subtítulo y piloto ON/OFF. */
export const ovCard = (ic, name, sub, on) =>
  `<div class="ov-card"><div class="ov-ic">${ic}</div><div><b>${name}</b>`
  + `<small>${esc(sub)}</small></div>`
  + `<span class="st ${on ? 'on' : 'off'}">${on ? 'ON' : 'OFF'}</span></div>`;

/** Color de cada aguja. Fuera de aquí no lo necesita nadie. */
const GCOL = { cpu: '#22e6ff', ram: '#4d9bff', disk: '#ffd23a', gpu: '#4dff9e' };

/** Aguja circular de porcentaje. El valor lo escribe luego updateMetrics(). */
export const gauge = (k, label) =>
  `<div class="gauge"><div class="ring" id="g-${k}" style="--gc:${GCOL[k] || '#22d3ee'}">`
  + `<b id="gv-${k}" style="color:${GCOL[k] || '#eaf6ff'}">0%</b></div>`
  + `<div class="glabel">${label}</div></div>`;

/** Cifra grande con etiqueta y variación. */
export const kpi = (lbl, val, delta, cy) =>
  `<div class="kpi"><div class="lbl">${lbl}</div>`
  + `<div class="val ${cy ? 'cy' : ''}">${val}</div><div class="delta">${delta}</div></div>`;

/** Chip de acción rápida. El clic lo recoge la delegación del router. */
export const qc = (i, label, cmd, isPrompt, view) =>
  `<div class="qc" data-cmd="${cmd ? esc(cmd) : ''}" data-prompt="${isPrompt ? 1 : ''}" `
  + `data-view="${view || ''}"><i>${i}</i> ${label}</div>`;

/** Botón de acción del panel lateral de nodo. Lo cablea wireNs(). */
export const nsBtn = (label, cmd, isP, view) =>
  `<button class="ns-act" data-cmd="${cmd ? esc(cmd) : ''}" data-p="${isP ? 1 : ''}" `
  + `data-v="${view || ''}">▸ ${esc(label)}</button>`;

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
