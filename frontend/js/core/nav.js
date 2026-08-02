/* ==========================================================
   nexus — cambiar de vista sin importar el router.
   El router monta TODAS las vistas, asi que cualquiera que lo
   importe para pedir un cambio de pantalla crea un ciclo. Aqui
   solo hay un hueco: el router deja su funcion al arrancar y los
   demas piden el cambio a ciegas.
   ========================================================== */

let ir = () => {};

/**
 * El router registra aqui su render(). Se llama una vez, al arrancar.
 * @param {(view: string) => void} fn
 */
export function onNavigate(fn) { ir = fn; }

/** Pide cambiar a una vista. Si el router aun no ha arrancado, no hace nada. */
export function go(view) { ir(view); }
