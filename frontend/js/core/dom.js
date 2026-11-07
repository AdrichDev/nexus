/* ==========================================================
   nexus — utilidades de DOM y red.
   Sin estado propio y sin depender de ninguna vista: es la hoja
   del árbol de imports, así que puede importarla cualquiera.
   ========================================================== */

/** Primer elemento que casa con el selector. */
export const $ = (s, r = document) => r.querySelector(s);

/** Todos los elementos que casan, ya como array. */
export const $$ = (s, r = document) => [...r.querySelectorAll(s)];

/* Escapa lo que va a inyectarse como HTML **o dentro de un atributo**.
   SEC-10 (roadmap P2-11): antes solo escapaba `& < >`. En texto daba igual,
   pero `esc()` se usa dentro de atributos (`href="${esc(x)}"`, como la
   permalink de Reels): ahí una comilla del dato CERRABA el atributo y lo que
   viniera detrás se ejecutaba como HTML. Ahora también escapa `"` y `'` a
   `&#34;` y `&#39;`, que el navegador decodifica igual en texto y dentro de un
   atributo, así que no cambia nada de lo que se ve: la entidad la resuelve el
   navegador al pintar, no nosotros. */
export const esc = (s) => String(s == null ? '' : s)
  .replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;',
                                  '"': '&#34;', "'": '&#39;' }[c]));

/* Texto de la IA → HTML con las URLs clicables (se abren en el navegador del PC).
   Ojo con el orden: se escapa PRIMERO (como siempre), así que la comilla del
   texto ya es `&#34;` cuando llega aquí. La clase de la URL corta en `&` salvo
   `&amp;` — una entidad a medias (`&#34;`, `&#39;`) no puede colarse dentro del
   `href` y una query con `&` sí sigue entrando entera (`&amp;` se decodifica a
   `&` al pintar). */
export const linkify = (s) => esc(s).replace(/(https?:\/\/(?:&amp;|[^\s<>"'«»)&])+)/g,
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
