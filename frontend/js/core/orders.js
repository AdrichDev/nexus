/* ==========================================================
   nexus — dar una orden a nexus desde cualquier modulo.
   Tercero y ultimo de los huecos con registro (los otros dos
   son core/nav.js y core/log.js). Enviar una orden toca el
   WebSocket, el chat y el estado de «pensando», que viven en el
   arranque; sin esto, cualquier vista con un boton de accion
   tendria que importar el arranque entero.
   ========================================================== */

let enviar = () => {};

/**
 * El arranque registra aqui su send(). Se llama una vez, al abrir el enlace.
 * @param {(texto: string) => void} fn
 */
export function onSend(fn) { enviar = fn; }

/** Manda una orden a nexus. Si aun no hay enlace, no hace nada. */
export function send(texto) { enviar(texto); }
