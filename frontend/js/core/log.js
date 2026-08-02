/* ==========================================================
   nexus — el registro que ve el Monitor del sistema.
   Vive aparte del router a proposito: cualquier modulo puede
   escribir en el sin importar la vista, y la vista se suscribe
   a que la repinten. Sin esto, todo el que quiera escribir una
   linea de log tendria que importar el router, y el router
   importa a todo el mundo.
   ========================================================== */
import { state } from './state.js';

let repinta = () => {};

/**
 * Quien pinta el log se registra aqui. Lo llama el router al arrancar.
 * @param {() => void} fn
 */
export function onLogPainted(fn) { repinta = fn; }

/** Anota una linea. Se guardan las ultimas 200. */
export function pushLog(level, msg) {
  state.logs.push({ t: new Date().toTimeString().slice(0, 8), level, msg });
  state.logs = state.logs.slice(-200);
  repinta();
}
