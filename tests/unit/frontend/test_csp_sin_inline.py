# -*- coding: utf-8 -*-
"""NI UN MANEJADOR EN LÍNEA NI UN `<script>` EN LÍNEA — SEC-10 / P2-11 (T18b).

T18 dejó la CSP del HUD a medias a propósito: `script-src 'self'
'unsafe-inline'`. Esa palabra es la que hace que un `onerror=` o un `<script>`
inyectado por un `innerHTML` sin escapar SÍ se ejecute: mientras esté, la
cabecera cierra el enmarcado (clickjacking) y los orígenes remotos, pero NO
cierra XSS por HTML inyectado.

Lo que obligaba a `'unsafe-inline'` eran 21 manejadores en atributo (4 en
`index.html`: `onload`/`onerror` de los dos logos; 17 en `setup.html`: 14
`onclick` de la navegación, 2 `oninput`, 1 `onchange`) y 2 bloques `<script>`
sin `src` (`mobile.html` y el asistente `setup.html`). Además de los atributos,
cualquier plantilla de `frontend/js/**` que pinte `onclick="…"` cuenta igual:
también la ejecuta el navegador bajo `'unsafe-inline'`.

Este es el cierre (T18b): cada manejador se pasa a `addEventListener` en un
módulo, los dos bloques en línea pasan a ficheros `.js` servidos desde
`/static/`, y la cabecera deja de necesitar `'unsafe-inline'` PARA SCRIPTS.
`style-src` sigue con `'unsafe-inline'`: los `style="…"` en atributo son otro
trabajo (T18b los deja fuera de alcance a propósito) y se dice aquí para que
nadie crea que esta suite prueba lo que no prueba.

QUÉ SE COMPRUEBA

  a) Ni un atributo `on…=` en `frontend/*.html` ni en el HTML que construyen
     las plantillas de `frontend/js/**` (las asignaciones de propiedad
     `el.onclick = fn` SÍ son válidas y no se marcan: no son HTML).
  b) Ni un `<script>` sin `src` en los documentos que sirve el backend.
  c) La CSP que SIRVE `backend/app.py` (`/`, `/setup`, `/m`, en proceso con
     `httpx.ASGITransport`, que NO ejecuta `lifespan`) lleva `script-src 'self'`
     sin `'unsafe-inline'`.
  d) Cada manejador que estaba en línea sigue cableado: su elemento sigue en el
     documento y el módulo escucha ESE evento llamando a ESA función. La tabla
     `MANEJADORES` es el inventario de partida, escrito a mano para que quitarlo
     o moverlo se vea en el diff.

CÓMO, Y QUÉ NO PRUEBA

- (a), (b) y (d) son lectura del fuente: evidencia S.
- (c) es una petición EN PROCESO: sin uvicorn, sin puertos, sin micrófono y sin
  Telegram; config y datos en carpetas de usar y tirar ANTES de importar.
- El cableado de `js/setup.js` se EJECUTA con `node` sobre un DOM de mentira
  mínimo: se dispara el clic delegado de un botón `data-go` y se comprueba que
  el paso correspondiente queda encendido. Sin `node` esa parte se SALTА con un
  aviso explícito (un verde sin node no prueba el cableado).
- NO se abre un navegador: que Chromium pinte y responda al ratón es lo que mide
  el e2e, que corre en el equipo del dueño (arranca uvicorn). Aquí no se finge.

Ejecutar:  .venv\\Scripts\\python.exe tests\\unit\\frontend\\test_csp_sin_inline.py
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                              # noqa: BLE001
    pass

# ANTES de importar backend: ni config/settings.json ni config/secrets.json del
# operador se leen ni se escriben desde aquí.
_CFG = tempfile.mkdtemp(prefix="nexus_csp_cfg_")
_DATA = tempfile.mkdtemp(prefix="nexus_csp_data_")
os.environ["NEXUS_CONFIG_DIR"] = _CFG
os.environ["NEXUS_DATA_DIR"] = _DATA
os.environ["NEXUS_DOTENV"] = "0"

import httpx                                                    # noqa: E402

import backend.app as servidor                                  # noqa: E402

_fail: list[str] = []
_pass = 0
_saltos: list[str] = []


def check(cond, msg: str) -> bool:
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  ✖", msg)
    return bool(cond)


FRONTEND = ROOT / "frontend"
DOCUMENTOS = ("index.html", "mobile.html", "setup.html")
HUD = "127.0.0.1:8177"

# El nombre del evento y la función de un manejador en línea, en los documentos
# y en lo que metan en un `innerHTML`. `on[a-z]+=` a secas es lo que miraba el
# inventario de T18, y sigue siendo lo correcto para HTML.
_ATRIBUTO_EN_LINEA = re.compile(r"\son[a-z]+\s*=")

# En JavaScript la misma cadena puede ser un atributo de una plantilla (mal) o
# una ASIGNACIÓN DE PROPIEDAD (bien: `el.onclick = fn`, `ws.onopen = fn`, que es
# el API del DOM y no ejecuta HTML). Se distingue por lo que hay delante: una
# asignación a propiedad siempre lleva `.` o `]` delante del nombre.
_EVENTOS = ("click|dblclick|auxclick|contextmenu|input|change|submit|reset|"
            "load|error|abort|keydown|keyup|keypress|blur|focus|focusin|focusout|"
            "mouseover|mouseout|mouseenter|mouseleave|mousedown|mouseup|mousemove|"
            "touchstart|touchend|touchmove|pointerdown|pointerup|dragstart|dragover|"
            "dragleave|drop|scroll|wheel|play|pause|ended|select|toggle")
_MANEJADOR_EN_CADENA = re.compile(rf"(?<![.\w$])on(?:{_EVENTOS})\s*=")

# Cada manejador que estaba EN LÍNEA, y dónde vive ahora. Las cuatro columnas son
# la prueba: el elemento sigue en el documento, y el módulo escucha ESE evento
# llamando a ESA función. El inventario de partida está en el docstring.
MANEJADORES = (
    # (documento, marca que debe seguir en el HTML, módulo, evento, qué llama)
    ("index.html", 'class="boot-logo-img"', "js/logos.js", "load", "alCargar"),
    ("index.html", 'class="boot-logo-img"', "js/logos.js", "error", "alFallar"),
    ("index.html", 'class="brand-logo-img"', "js/logos.js", "load", "alCargar"),
    ("index.html", 'class="brand-logo-img"', "js/logos.js", "error", "alFallar"),
    ("setup.html", 'id="f-sysname"', "js/setup.js", "input", "onSysName"),
    ("setup.html", 'id="f-syslogo-file"', "js/setup.js", "change", "onLogoPick"),
    ("setup.html", 'data-go="', "js/setup.js", "click", "go(+b.dataset.go)"),
)

# Lo que el teclado/ratón llamaba en la navegación del asistente, valor a valor:
# 14 `onclick="go(n)"`, dos por paso (ATRÁS y SIGUIENTE) salvo el primero y el
# último. Si alguien cambia un destino, se ve aquí.
NAVEGACION = (1, 0, 2, 1, 3, 2, 4, 3, 5, 4, 6, 5, 7, 6)


def _documentos() -> list[Path]:
    return sorted(FRONTEND.glob("*.html"))


def _modulos_js() -> list[Path]:
    return sorted((FRONTEND / "js").rglob("*.js"))


def _sin_comentarios_html(texto: str) -> str:
    """El documento sin comentarios: explicar qué había antes no cuenta como
    tenerlo. Los `<script src>` y el marcado se quedan."""
    return re.sub(r"<!--(?:.|\n)*?-->", " ", texto)


def _sin_comentarios_js(texto: str) -> str:
    """El CÓDIGO: sin comentarios de bloque ni líneas que empiecen por `//`."""
    texto = re.sub(r"/\*(?:.|\n)*?\*/", " ", texto)
    return re.sub(r"(?m)^\s*//[^\n]*$", " ", texto)


def _csv_csp(csp: str) -> dict[str, list[str]]:
    directivas: dict[str, list[str]] = {}
    for trozo in csp.split(";"):
        piezas = trozo.split()
        if piezas:
            directivas[piezas[0]] = piezas[1:]
    return directivas


# ══════════════════════════════════════════════════════════════════════════════
#  a) Ni un atributo `on…=`, ni en el HTML ni en el HTML que pintan los módulos
# ══════════════════════════════════════════════════════════════════════════════
def pruebas_sin_manejadores_en_linea() -> None:
    print("== a) ni un manejador en atributo en frontend/*.html ==")
    total = 0
    for doc in _documentos():
        texto = _sin_comentarios_html(doc.read_text(encoding="utf-8"))
        hallados = [m.group(0).strip() for m in _ATRIBUTO_EN_LINEA.finditer(texto)]
        total += len(hallados)
        check(not hallados,
              f"{doc.name} todavía tiene {len(hallados)} manejadores en línea "
              f"({', '.join(sorted(set(hallados))[:6])}): páspalos a addEventListener "
              "en su módulo de frontend/js")
    check(total == 0, f"quedan {total} manejadores en línea en los tres documentos (deben ser 0)")

    print("== a) ni una plantilla de frontend/js pinta un manejador en atributo ==")
    for mod in _modulos_js():
        if mod.name.endswith(".min.js"):                # qrcode: librería de terceros
            continue
        texto = _sin_comentarios_js(mod.read_text(encoding="utf-8"))
        hallados = [m.group(0).strip() for m in _MANEJADOR_EN_CADENA.finditer(texto)]
        rel = mod.relative_to(ROOT).as_posix()
        check(not hallados,
              f"{rel} mete {len(hallados)} manejador(es) en HTML "
              f"({', '.join(sorted(set(hallados))[:6])}): una plantilla también "
              "necesita 'unsafe-inline'. Usa addEventListener o un data-action")


# ══════════════════════════════════════════════════════════════════════════════
#  b) Ni un `<script>` sin `src` en los documentos servidos
# ══════════════════════════════════════════════════════════════════════════════
_SIN_SRC = re.compile(r"<script(?![^>]*\bsrc\s*=)[^>]*>")


def pruebas_sin_script_en_linea() -> None:
    print("== b) ni un <script> sin src en los documentos ==")
    total = 0
    for doc in _documentos():
        texto = _sin_comentarios_html(doc.read_text(encoding="utf-8"))
        bloques = _SIN_SRC.findall(texto)
        total += len(bloques)
        check(not bloques,
              f"{doc.name} tiene {len(bloques)} bloque(s) <script> en línea "
              f"({', '.join(bloques[:3])}): el código va a un fichero de "
              "frontend/js y el documento lo carga con src")
    check(total == 0, f"quedan {total} bloques <script> en línea (deben ser 0)")


def _antes(texto: str, primero: str, segundo: str) -> bool:
    """`primero` aparece antes que `segundo` (y los dos aparecen)."""
    a, b = texto.find(primero), texto.find(segundo)
    return 0 <= a < b


def pruebas_carga_de_los_modulos() -> None:
    """El código movido tiene que seguir cargándose, y en el mismo orden."""
    print("== b) cada documento carga su módulo con src ==")
    index = (FRONTEND / "index.html").read_text(encoding="utf-8")
    setup = (FRONTEND / "setup.html").read_text(encoding="utf-8")
    mobile = (FRONTEND / "mobile.html").read_text(encoding="utf-8")
    # `logos.js` es CLÁSICO y va en el <head>: un módulo va diferido y llegaría
    # después de que el logo ya hubiera cargado (el onload no se repetiría).
    check(re.search(r"<script\s+src=\"/static/js/logos\.js\"", index) is not None,
          "index.html no carga /static/js/logos.js como script clásico")
    check(_antes(index, "/static/js/logos.js", 'class="boot-logo-img"'),
          "logos.js se carga DESPUÉS del primer logo: el onload/onerror se perdería")
    check(re.search(r"<script\s+type=\"module\"\s+src=\"/static/js/setup\.js\"", setup) is not None,
          "setup.html no carga /static/js/setup.js como módulo")
    check(re.search(r"<script\s+src=\"/static/js/mobile\.js\"", mobile) is not None,
          "mobile.html no carga /static/js/mobile.js")
    # Orden: reactor.js sigue antes que el script del móvil (dibuja el canvas).
    check(_antes(mobile, "/static/js/reactor.js", "/static/js/mobile.js"),
          "mobile.html carga mobile.js antes que reactor.js: cambia el orden de arranque")
    for doc, rel in ((index, "js/logos.js"), (setup, "js/setup.js"), (mobile, "js/mobile.js")):
        check((FRONTEND / rel).is_file(), f"el documento apunta a {rel} y ese fichero no existe")


# ══════════════════════════════════════════════════════════════════════════════
#  d) Cada manejador que estaba en línea sigue cableado
# ══════════════════════════════════════════════════════════════════════════════
def pruebas_manejadores_cableados() -> None:
    print("== d) los 21 manejadores siguen cableados, uno por uno ==")
    documentos = {n: (FRONTEND / n).read_text(encoding="utf-8") for n in DOCUMENTOS}
    for doc, marca, modulo, evento, llama in MANEJADORES:
        check(marca in documentos[doc],
              f"{doc} ya no tiene el elemento «{marca}» que llevaba el manejador en línea")
        ruta = FRONTEND / modulo
        if not check(ruta.is_file(), f"falta {modulo}: el manejador de {doc} se queda sin cablear"):
            continue
        texto = _sin_comentarios_js(ruta.read_text(encoding="utf-8"))
        # La llamada tiene que estar en el MISMO cableado, no en cualquier parte
        # del fichero: se mira la ventana que sigue a `addEventListener('evento'`.
        ventanas = [texto[i:i + 220]
                    for i in (m.start() for m in re.finditer(
                        rf"addEventListener\(\s*['\"]{evento}['\"]", texto))]
        check(ventanas, f"{modulo} no escucha «{evento}» (lo hacía {doc} en línea)")
        check(any(llama in v for v in ventanas),
              f"{modulo} escucha «{evento}» pero no llama a «{llama}» "
              f"(ventanas: {[v[:80] for v in ventanas]})")

    print("== d) la navegación del asistente conserva sus 14 destinos ==")
    setup = documentos["setup.html"]
    destinos = [int(n) for n in re.findall(r'\sdata-go="(\d+)"', setup)]
    check(sorted(destinos) == sorted(NAVEGACION),
          f"los botones del asistente ya no llevan los 14 data-go esperados: {destinos}")


# ══════════════════════════════════════════════════════════════════════════════
#  c) La CSP que sirve app.py, en proceso
# ══════════════════════════════════════════════════════════════════════════════
def _cliente() -> httpx.AsyncClient:
    """Cliente ASGI en proceso, desde el propio equipo (peer de loopback)."""
    transporte = httpx.ASGITransport(app=servidor.app, client=("127.0.0.1", 4321))
    return httpx.AsyncClient(transport=transporte, base_url=f"http://{HUD}")


async def pruebas_csp() -> None:
    print("== c) la CSP servida ya no necesita 'unsafe-inline' para scripts ==")
    async with _cliente() as c:
        for ruta in ("/", "/setup", "/m"):
            r = await c.get(ruta, headers={"host": HUD})
            check(r.status_code == 200, f"{ruta} responde 200 (vino {r.status_code})")
            csp = r.headers.get("content-security-policy") or ""
            directivas = _csv_csp(csp)
            script = directivas.get("script-src") or []
            check(script == ["'self'"],
                  f"{ruta}: script-src debería ser exactamente 'self' y es {script}")
            check("'unsafe-inline'" not in script,
                  f"{ruta}: script-src sigue con 'unsafe-inline' ({script})")
            check("'unsafe-eval'" not in script and "'strict-dynamic'" not in script,
                  f"{ruta}: script-src se ha abierto por otro lado ({script})")
            check(not re.search(r"'(?:nonce|sha256|sha384|sha512)-", csp),
                  f"{ruta}: no hay nonces/hashes en esta cabecera y no deben aparecer "
                  "sin un motivo escrito (no queda ningún script en línea)")
            # La razón de que esto NO se toque, pinchada a propósito: los
            # `style="…"` en atributo son otro trabajo. Si alguien los quita,
            # este caso se pone rojo y la decisión se toma aquí, no de tapadillo.
            estilo = directivas.get("style-src") or []
            check("'unsafe-inline'" in estilo,
                  f"{ruta}: style-src ya no lleva 'unsafe-inline' ({estilo}); los "
                  "`style=\"…\"` en atributo siguen en el HUD (fuera del alcance de "
                  "T18b), así que cambia este caso a la vez que ellos")
            check("frame-ancestors" in directivas and directivas["frame-ancestors"] == ["'none'"],
                  f"{ruta}: frame-ancestors 'none' se ha perdido")
            check(r.headers.get("x-frame-options") == "DENY",
                  f"{ruta}: X-Frame-Options: DENY se ha perdido")

        # PRESERVE: los estáticos no llevan CSP y la API sigue siendo JSON.
        r = await c.get("/static/js/setup.js", headers={"host": HUD})
        check(r.status_code == 200, f"/static/js/setup.js se sirve (vino {r.status_code})")
        check(r.headers.get("content-security-policy") is None,
              "la CSP sigue siendo una cabecera de documento, no de estático")
        r = await c.get("/api/link/status", headers={"host": HUD})
        check(r.status_code == 200 and isinstance(r.json(), dict),
              "la API sigue devolviendo JSON")
        check(r.headers.get("content-security-policy") is None,
              "el JSON no lleva CSP")


# ══════════════════════════════════════════════════════════════════════════════
#  El cableado del asistente, ejecutado en un DOM de mentira (node)
# ══════════════════════════════════════════════════════════════════════════════
_SHIM_JS = r"""
// DOM de mentira: lo justo para que js/setup.js arranque. No hay navegador.
const pasos = Array.from({ length: 8 }, (_, i) => {
  const clases = new Set();
  return { dataset: { s: String(i) }, classList: {
    add: (c) => clases.add(c), remove: (c) => clases.delete(c),
    contains: (c) => clases.has(c),
    toggle: (c, on) => { if (on) clases.add(c); else clases.delete(c); return !!on; },
    _clases: clases } };
});
const nodos = Array.from({ length: 8 }, (_, i) => {
  const clases = new Set();
  return { dataset: { i: String(i) }, classList: {
    add: (c) => clases.add(c), remove: (c) => clases.delete(c),
    contains: (c) => clases.has(c),
    toggle: (c, on) => { if (on) clases.add(c); else clases.delete(c); return !!on; },
    _clases: clases } };
});
const oyentes = { document: {}, elementos: [] };
const documento = {
  readyState: 'complete',
  addEventListener: (ev, fn) => { (oyentes.document[ev] = oyentes.document[ev] || []).push(fn); },
  querySelector: (sel) => ({
    innerHTML: '', value: '', checked: false, textContent: '', src: '', disabled: false,
    style: {},
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    addEventListener: (ev, fn) => oyentes.elementos.push([sel, ev, fn]),
    querySelectorAll: () => [],
  }),
  querySelectorAll: (sel) => (sel === '.step' ? pasos : sel === '#steps b' ? nodos : []),
  createElement: () => ({ style: {}, classList: { add() {} }, appendChild() {} }),
  getElementById: (id) => documento.querySelector('#' + id),
};
const ventana = { scrollTo: () => {}, addEventListener: () => {} };
globalThis.document = documento;
globalThis.window = ventana;
globalThis.location = { href: '', search: '', protocol: 'http:', host: '127.0.0.1:8177' };
// `navigator` es de solo lectura en node 22: se sustituye con defineProperty.
Object.defineProperty(globalThis, 'navigator', {
  value: { userAgent: 'node' }, configurable: true, writable: true,
});
// La llamada al backend se queda colgada A PROPÓSITO: así no toca el DOM.
globalThis.fetch = () => new Promise(() => {});
globalThis.FileReader = class { readAsDataURL() {} };
globalThis.Image = class {};

const salida = {};
try {
  const { pathToFileURL } = await import('node:url');
  await import(pathToFileURL(process.argv[2]).href);
  // Se lee DESPUÉS del import. Antes de ejecutarse el módulo, `oyentes.document`
  // está vacío POR DEFINICIÓN: calcularlo en el literal de arriba hacía que esta
  // comprobación no pudiera pasar nunca, con ningún cableado (fallo del arnés,
  // no del código). La afirmación del lado de Python es la misma: UN clic
  // delegado en el documento, y que sea de tipo 'click'.
  salida.oyentesDocumento = Object.keys(oyentes.document).sort();
  // El arranque pinta el paso 0.
  salida.pasoInicial = pasos.map((p) => p.classList.contains('on'));
  // Un clic en el botón «SIGUIENTE» del paso 0 → data-go="1"... y uno a 3.
  const clics = oyentes.document.click || [];
  salida.oyentesClick = clics.length;
  if (clics.length) {
    clics[0]({ target: { closest: () => ({ dataset: { go: '3' } }) } });
    salida.trasClic3 = pasos.map((p) => p.classList.contains('on'));
    clics[0]({ target: { closest: () => null } });   // clic en el fondo: no navega
    salida.trasClicFuera = pasos.map((p) => p.classList.contains('on'));
    clics[0]({ target: {} });                          // sin `closest`: no revienta
    salida.trasClicRaro = pasos.map((p) => p.classList.contains('on'));
  }
  salida.escuchas = oyentes.elementos.map(([sel, ev]) => `${sel} ${ev}`);
} catch (e) {
  salida.error = String((e && e.stack) || e);
}
console.log(JSON.stringify(salida));
"""


def _node() -> str | None:
    return shutil.which("node")


def _shim(scratch: Path) -> dict | None:
    fichero = scratch / "shim.mjs"
    fichero.write_text(_SHIM_JS, encoding="utf-8")
    proc = subprocess.run(
        [_node(), str(fichero), str(FRONTEND / "js" / "setup.js")],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    if proc.returncode != 0:
        print("  ✖ node falló al ejecutar js/setup.js")
        print("    " + ((proc.stderr or "").strip()[:1500]))
        return None
    return json.loads(proc.stdout.strip().splitlines()[-1])


def pruebas_cableado_ejecutado(scratch: Path) -> None:
    print("== el cableado del asistente, ejecutado (node, DOM de mentira) ==")
    if _node() is None:
        aviso = ("SIN NODE: no se ha ejecutado js/setup.js; el clic delegado de la "
                 "navegación queda SIN PROBAR (solo se comprueba leyendo el fuente)")
        _saltos.append(aviso)
        print("  ⚠ " + aviso)
        return
    out = _shim(scratch)
    if not check(out is not None, "el shim no devolvió nada: js/setup.js no arranca solo"):
        return
    if "error" in out:
        check(False, f"js/setup.js no arranca en el DOM de mentira: {out['error'][:400]}")
        return
    check(out.get("oyentesDocumento") == ["click"],
          f"setup.js no deja UN clic delegado en el documento: {out.get('oyentesDocumento')}")
    check(out.get("pasoInicial") == [True] + [False] * 7,
          f"el asistente no arranca en el paso 0: {out.get('pasoInicial')}")
    check(out.get("trasClic3") == [False] * 3 + [True] + [False] * 4,
          f"el clic en un botón data-go=3 no enciende el paso 3: {out.get('trasClic3')}")
    check(out.get("trasClicFuera") == out.get("trasClic3"),
          f"un clic fuera de la navegación mueve el paso: {out.get('trasClicFuera')}")
    check(out.get("trasClicRaro") == out.get("trasClic3"),
          f"un clic sin `closest` rompe o navega: {out.get('trasClicRaro')}")
    escuchas = out.get("escuchas") or []
    for sel, ev in (("#f-sysname", "input"), ("#f-syslogo-file", "change")):
        check(f"{sel} {ev}" in escuchas,
              f"setup.js no escucha «{ev}» en {sel}: {escuchas}")


def main() -> None:
    pruebas_sin_manejadores_en_linea()
    pruebas_sin_script_en_linea()
    pruebas_carga_de_los_modulos()
    pruebas_manejadores_cableados()
    asyncio.run(pruebas_csp())
    scratch = Path(tempfile.mkdtemp(prefix="nexus_csp_shim_"))
    try:
        pruebas_cableado_ejecutado(scratch)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


try:
    main()
except Exception as exc:                                       # noqa: BLE001
    _fail.append(f"la suite se rompió: {exc!r}")
    import traceback
    traceback.print_exc()
finally:
    for carpeta in (_CFG, _DATA):
        shutil.rmtree(carpeta, ignore_errors=True)

print(f"\n{'#' * 54}\ntest_csp_sin_inline: {_pass} OK, {len(_fail)} fallos")
for aviso in _saltos:
    print("  ⚠", aviso)
for m in _fail:
    print("  -", m)
sys.exit(1 if _fail else 0)
