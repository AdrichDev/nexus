/* ==========================================================
   nexus — utilidades de DOM y red.
   Sin estado propio y sin depender de ninguna vista: es la hoja
   del árbol de imports, así que puede importarla cualquiera.
   ========================================================== */

/** Primer elemento que casa con el selector. */
export const $ = (s, r = document) => r.querySelector(s);

/** Todos los elementos que casan, ya como array. */
export const $$ = (s, r = document) => [...r.querySelectorAll(s)];

/** Escapa lo que va a inyectarse como HTML. */
export const esc = (s) => String(s == null ? '' : s)
  .replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));

/** Texto de la IA → HTML con las URLs clicables (se abren en el navegador del PC). */
export const linkify = (s) => esc(s).replace(/(https?:\/\/[^\s<>"«»)]+)/g,
  (u) => `<a href="${u}" class="ext" title="Abrir en el navegador">${u}</a>`);

/** GET/POST a la API que nunca lanza: devuelve null si algo falla. */
export const api = (p, o) => fetch(p, o).then((r) => r.json()).catch(() => null);

/** Destello cian de «recibido» sobre un elemento. */
export function flash(el) {
  el.style.background = 'rgba(34,211,238,.2)';
  setTimeout(() => { el.style.background = ''; }, 400);
}

/** Markdown mínimo → HTML. Escapa primero: el texto viene del modelo. */
export function mdToHtml(md) {
  return esc(md)
    .replace(/^#### (.+)$/gm, '<h5>$1</h5>')
    .replace(/^### (.+)$/gm, '<h5>$1</h5>')
    .replace(/^## (.+)$/gm, '<h4>$1</h4>')
    .replace(/^# (.+)$/gm, '<h3>$1</h3>')
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/^- (.+)$/gm, '• $1')
    .replace(/\n/g, '<br>');
}
