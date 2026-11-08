/* LOS DOS LOGOS DEL HUD, SIN UN MANEJADOR EN LÍNEA (T18b, SEC-10).
 *
 * `index.html` llevaba cuatro manejadores en atributo —`onload`/`onerror` de
 * los dos logos— y eso obligaba a que la CSP dijera `script-src 'self'
 * 'unsafe-inline'`. Mientras esa palabra esté, un `<img onerror=...>` inyectado
 * por un `innerHTML` sin escapar SÍ se ejecuta: la cabecera cerraba el
 * enmarcado y los orígenes remotos, no el XSS por HTML inyectado.
 *
 * El `load` y el `error` de una imagen NO BURBUJEAN, así que esto no puede ser
 * un listener normal en el documento: van en fase de CAPTURA (`true`), que sí
 * pasa por el documento antes de llegar a la imagen.
 *
 * Y tiene que ser un script CLÁSICO que se cargue en el `<head>`, ANTES de la
 * primera imagen: un módulo va diferido y llegaría cuando el logo ya hubiera
 * cargado (o fallado), y ese `load` no se repite. Si este fichero se mueve al
 * final del documento, el logo de respaldo se queda encima del de verdad.
 *
 * El comportamiento es EXACTAMENTE el que estaba en el atributo, glifo a
 * glifo: al cargar, se oculta el logo vectorial de respaldo que va justo
 * detrás; al fallar, la imagen rota se quita del DOM en vez de dejar el icono
 * de imagen rota.
 */
(function () {
  'use strict';

  // Los dos logos del HUD (`boot` = pantalla de arranque, `brand` = barra
  // lateral). Cualquier otra imagen del documento se queda como está.
  var LOGOS = '.boot-logo-img, .brand-logo-img';

  function esLogo(nodo) {
    return !!(nodo && typeof nodo.matches === 'function' && nodo.matches(LOGOS));
  }

  // onload="this.nextElementSibling.style.display='none'"
  function alCargar(ev) {
    var img = ev.target;
    if (!esLogo(img)) return;
    var respaldo = img.nextElementSibling;
    if (respaldo && respaldo.style) respaldo.style.display = 'none';
  }

  // onerror="this.remove()"
  function alFallar(ev) {
    var img = ev.target;
    if (!esLogo(img)) return;
    if (typeof img.remove === 'function') img.remove();
    else if (img.parentNode) img.parentNode.removeChild(img);
  }

  document.addEventListener('load', alCargar, true);
  document.addEventListener('error', alFallar, true);
})();
