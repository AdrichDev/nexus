# -*- coding: utf-8 -*-
"""ESC() TAMBIÉN ESCAPA COMILLAS, Y EL HUD NO SE DEJA ENMARCAR — SEC-10 / P2-11.

Auditoría de seguridad, SEC-10 (roadmap P2-11, task T18). Dos cierres y un
detalle:

  1. `esc()` (frontend/js/core/dom.js) escapaba `& < >` y dejaba pasar `"` y
     `'`. En texto no se nota, pero en cuanto `esc()` se usa DENTRO de un
     atributo —`href="${esc(x)}"`— la comilla del dato cierra el atributo y lo
     que venga detrás se ejecuta como HTML. Es el caso de la permalink de
     `frontend/js/views/reels.js`. Ahora `esc()` también escapa `"` y `'` a
     `&#34;` y `&#39;`, que el navegador decodifica igual en texto y dentro de un
     atributo, así que no cambia nada de lo que se ve.
  2. `esc()` no viaja sola: `linkify()` y `mdToHtml()` la usan. Si `esc()`
     escapa primero las comillas, la regex de URL de `linkify` (que se cortaba
     en `"`) dejaba de cortarse, y `https://x/seguido-de-una-comilla` se comía
     la entidad dentro del `href`. Esta suite fija las dos cosas: se sigue
     enlazando la URL limpia y `javascript:` sigue sin ser un enlace.
  3. El HTML que sirve el backend (`/`, `/m`, `/setup`) lleva
     `Content-Security-Policy` con `frame-ancestors 'none'` y
     `X-Frame-Options: DENY`: el HUD deja de poder meterse en un iframe ajeno
     (clickjacking). El `Cache-Control: no-store` del HUD NO se toca.

CÓMO SE PRUEBA, Y QUÉ NO PRUEBA

- El JavaScript se EJECUTA con `node` (ESM, sin navegador ni DOM): se importa
  `frontend/js/core/dom.js` de verdad y se compara la salida exacta en Python.
  Si `node` no está en el PATH esa parte se SALTА con un aviso explícito (una
  suite verde sin node NO es prueba del escape); las cabeceras se prueban
  igual.
- El trozo de `reels.js` que pinta la ficha del reel se extrae del fichero tal
  cual y se evalúa con un `box` de mentira, para meterle comillas en el pie, en
  la permalink y en los contadores. Si ese trozo se mueve o se renombra, esta
  suite se pone roja: es a propósito.
- Las cabeceras van EN PROCESO (httpx.ASGITransport, que NO ejecuta `lifespan`):
  ni uvicorn, ni puertos, ni micrófono, ni Telegram. La configuración y los
  datos se apuntan a carpetas de usar y tirar ANTES de importar el backend.

Ejecutar:  .venv\\Scripts\\python.exe tests\\unit\\frontend\\test_escapes_y_cabeceras.py
"""
from __future__ import annotations

import asyncio
import html
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
_CFG = tempfile.mkdtemp(prefix="nexus_escapes_cfg_")
_DATA = tempfile.mkdtemp(prefix="nexus_escapes_data_")
os.environ["NEXUS_CONFIG_DIR"] = _CFG
os.environ["NEXUS_DATA_DIR"] = _DATA

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


DOM_JS = ROOT / "frontend" / "js" / "core" / "dom.js"
REELS_JS = ROOT / "frontend" / "js" / "views" / "reels.js"
MOBILE_HTML = ROOT / "frontend" / "mobile.html"

# Las DOS comillas tienen que salir escapadas, y como entidad con nombre (no
# `&quot;`): `&#34;`/`&#39;` son las que estaban en el informe de la auditoría.
COMILLA = "&#34;"
APOS = "&#39;"

PAYLOAD = 'x" onmouseover="alert(1)'

# La cabecera, carácter a carácter. Copiada del código a propósito: si alguien
# la cambia, el cambio se ve aquí y se discute, no se cuela.
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; "
       "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "connect-src 'self' ws: wss:; frame-ancestors 'none'; "
       "base-uri 'none'; form-action 'self'; object-src 'none'")

HUD = "127.0.0.1:8177"


# ══════════════════════════════════════════════════════════════════════════════
#  Arranque del JavaScript de verdad (node, sin navegador)
# ══════════════════════════════════════════════════════════════════════════════
_SCRIPT_JS = r"""
const { pathToFileURL } = await import('node:url');
const fs = await import('node:fs');

const [domPath, reelsPath] = process.argv.slice(2);
const { esc, linkify, mdToHtml } = await import(pathToFileURL(domPath).href);

const attr = (v) => `<a href="${esc(v)}">x</a>`;
const payload = 'x" onmouseover="alert(1)';

const salida = {
  escComilla: esc('di "hola"'),
  escApostrofo: esc("es 'tuyo'"),
  escTodo: esc('&<>"\''),
  escNulo: esc(null),
  escIndefinido: esc(undefined),
  escNumero: esc(7),
  attrPayload: attr(payload),
  attrComillas: (attr(payload).match(/"/g) || []).length,
  linkSuelta: linkify('mira https://ejemplo.com/a-b_c'),
  linkSeguidaDeComilla: linkify('https://ejemplo.com/x"'),
  linkComillaAntes: linkify('dijo "https://ejemplo.com/x" y nada'),
  linkVarias: linkify('https://a.example/1 y https://b.example/2?x=1&y=2'),
  linkJavascript: linkify('javascript:alert(1)'),
  linkJavascriptConHttp: linkify('javascript:alert("https://ejemplo.com")'),
  mdNormal: mdToHtml('# Titulo\n## Sub\n**fuerte**\n`codigo`\n- uno'),
  mdComillas: mdToHtml('linea <x> "y" y \'z\''),
};

// ---- reels.js: la ficha del reel, sin navegador -------------------------------
const src = fs.readFileSync(reelsPath, 'utf8');
const arranque = 'box.innerHTML = reels.map(';
const cierre = "}).join('');";
const desde = src.indexOf(arranque);
const hasta = src.indexOf(cierre, desde);
if (desde < 0 || hasta < 0) {
  salida.reelsError = 'no encuentro el trozo que pinta la ficha del reel en reels.js';
} else {
  const trozo = src.slice(desde, hasta + cierre.length);
  const box = {};
  const reels = [{
    reel: { caption: 'pie con "comillas" y <b>etiqueta</b>',
            permalink: 'https://insta.example/p/x"y',
            cuando: '2026-01-01', tipo: 'REEL' },
    resumen: { alcance: 1000, comentarios: '2" onmouseover="alert(1)',
               leads: '3" onmouseover="alert(1)',
               con_contenido: '4" onmouseover="alert(1)', cuadra: true },
    odio: { n: '5" onmouseover="alert(1)' },
    secciones: [],
  }];
  const igSec = () => '';
  const igEngancha = () => {};
  const pinta = new Function('box', 'reels', 'esc', 'igSec', 'igEngancha', trozo);
  pinta(box, reels, esc, igSec, igEngancha);
  salida.reelsHtml = box.innerHTML;
}
console.log(JSON.stringify(salida));
"""


def _node() -> str | None:
    return shutil.which("node")


def _corre_node(scratch: Path) -> dict | None:
    """Ejecuta el arranque JS y devuelve su JSON. None si no hay node."""
    fichero = scratch / "arranque.mjs"
    fichero.write_text(_SCRIPT_JS, encoding="utf-8")
    proc = subprocess.run(
        [_node(), str(fichero), str(DOM_JS), str(REELS_JS)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60,
    )
    if proc.returncode != 0:
        print("  ✖ node falló al ejecutar dom.js / reels.js")
        print("    " + (proc.stderr or "").strip()[:2000])
        return None
    return json.loads(proc.stdout.strip().splitlines()[-1])


def pruebas_js() -> None:
    print("== esc() / linkify() / mdToHtml() de verdad (node, sin navegador) ==")
    if _node() is None:
        # Sin node no se puede EJECUTAR el JavaScript. Se dice y se sigue con el
        # resto; aquí no se finge un verde.
        aviso = "SIN NODE: no se ha ejecutado el JS (esc/linkify/mdToHtml/reels)"
        _saltos.append(aviso)
        print("  ⚠ " + aviso)
        fuente = DOM_JS.read_text(encoding="utf-8")
        check('/[&<>"\']/g' in fuente and "&#34;" in fuente and "&#39;" in fuente,
              "el fuente de esc() mete \" y ' en el mapa de escapes "
              "(solo estructura: sin node no se prueba la salida)")
        return

    with tempfile.TemporaryDirectory(prefix="nexus_escapes_js_") as tmp:
        out = _corre_node(Path(tmp))
    if out is None:
        check(False, "el arnés de node no ha podido ejecutar el JS del HUD")
        return

    # ---- esc(): las dos comillas, sin tocar lo que ya hacía ------------------
    check(out["escComilla"] == f"di {COMILLA}hola{COMILLA}",
          f'esc() escapa la comilla doble: {out["escComilla"]!r}')
    check(out["escApostrofo"] == f"es {APOS}tuyo{APOS}",
          f"esc() escapa la comilla simple: {out['escApostrofo']!r}")
    check(out["escTodo"] == f"&amp;&lt;&gt;{COMILLA}{APOS}",
          f"esc() sigue escapando & < > y añade las dos comillas: {out['escTodo']!r}")
    check(out["escNulo"] == "" and out["escIndefinido"] == "",
          "esc() de null/undefined sigue siendo cadena vacía")
    check(out["escNumero"] == "7", "esc() de un número sigue devolviendo el número en texto")
    # Por qué esto NO cambia lo que se ve: la entidad la decodifica el navegador
    # igual en texto que dentro de un atributo. El mismo mecanismo, comprobado.
    check(html.unescape(COMILLA) == '"' and html.unescape(APOS) == "'",
          "las entidades que emite esc() se decodifican a la comilla original en texto y en atributo")

    # ---- el payload no puede salirse del atributo ---------------------------
    check(out["attrComillas"] == 2,
          f'href="${{esc(payload)}}" no puede romper el atributo (comillas en el HTML: {out["attrComillas"]})')
    check(' onmouseover="' not in out["attrPayload"],
          "el payload no deja un manejador onmouseover= vivo dentro del atributo")
    check(out["attrPayload"] ==
          f'<a href="x{COMILLA} onmouseover={COMILLA}alert(1)">x</a>',
          f"el atributo queda escapado: {out['attrPayload']!r}")

    # ---- linkify(): sigue enlazando, y la comilla ya no ensucia el href -----
    check('<a href="https://ejemplo.com/a-b_c"' in out["linkSuelta"],
          "linkify() sigue convirtiendo una URL suelta en enlace")
    check('href="https://ejemplo.com/x"' in out["linkSeguidaDeComilla"],
          f'la URL seguida de una comilla deja el href limpio: {out["linkSeguidaDeComilla"]!r}')
    check('href="https://ejemplo.com/x"' in out["linkComillaAntes"],
          "una URL entre comillas se enlaza igual")
    check('href="https://a.example/1"' in out["linkVarias"]
          and 'href="https://b.example/2?x=1&amp;y=2"' in out["linkVarias"],
          f"dos URL con query siguen enlazándose enteras: {out['linkVarias']!r}")
    check("<a " not in out["linkJavascript"],
          "javascript: sigue SIN convertirse en enlace")
    check('href="javascript:' not in out["linkJavascriptConHttp"],
          "javascript: con una URL dentro tampoco se enlaza como javascript:")

    # ---- mdToHtml(): escapa primero y formatea después ---------------------
    check(out["mdNormal"] ==
          '<h3>Titulo</h3><br><h4>Sub</h4><br><b>fuerte</b><br><code>codigo</code><br>• uno',
          f"mdToHtml() no cambia con el markdown normal: {out['mdNormal']!r}")
    check(out["mdComillas"] == f"linea &lt;x&gt; {COMILLA}y{COMILLA} y {APOS}z{APOS}",
          f"mdToHtml() escapa comillas y angulos antes de formatear: {out['mdComillas']!r}")

    # ---- reels.js: el pie, la permalink y los contadores -------------------
    print("== reels.js: la ficha del reel con comillas dentro ==")
    pintado = out.get("reelsHtml") or ""
    check(bool(pintado), "se ha podido pintar la ficha del reel: " + out.get("reelsError", ""))
    if pintado:
        check(f'<a href="https://insta.example/p/x{COMILLA}y" target="_blank" rel="noopener">' in pintado,
              "la permalink con comilla queda escapada dentro del href")
        check(' onmouseover="' not in pintado,
              "ningún dato del servidor deja un onmouseover= vivo en el HTML pintado")
        check(pintado.count('"') % 2 == 0,
              "el HTML pintado tiene las comillas de atributo balanceadas")
        check(f'<b>2{COMILLA} onmouseover={COMILLA}alert(1)</b>' in pintado,
              "res.comentarios sale escapado (como su hermano res.alcance)")
        check(f'<b>3{COMILLA} onmouseover={COMILLA}alert(1)</b>' in pintado,
              "res.leads sale escapado")
        check(f'<b>4{COMILLA} onmouseover={COMILLA}alert(1)</b>' in pintado,
              "res.con_contenido sale escapado")
        check(f'5{COMILLA} onmouseover={COMILLA}alert(1) comentario(s) de odio' in pintado,
              "r.odio.n sale escapado")
        check(f'pie con {COMILLA}comillas{COMILLA} y &lt;b&gt;etiqueta&lt;/b&gt;' in pintado,
              "el pie del reel queda escapado con & y < de antes y comillas nuevas")


# ══════════════════════════════════════════════════════════════════════════════
#  Cabeceras del HUD, en proceso
# ══════════════════════════════════════════════════════════════════════════════
APP = servidor.app


def _cliente() -> httpx.AsyncClient:
    """Cliente ASGI en proceso, desde el propio equipo (peer de loopback)."""
    transporte = httpx.ASGITransport(app=APP, client=("127.0.0.1", 4321))
    return httpx.AsyncClient(transport=transporte, base_url=f"http://{HUD}")


async def _cabeceras() -> None:
    print("== CSP y X-Frame-Options en el HTML del HUD (en proceso) ==")
    async with _cliente() as c:
        for ruta in ("/", "/setup", "/m"):
            r = await c.get(ruta, headers={"host": HUD})
            check(r.status_code == 200, f"{ruta} responde 200 (vino {r.status_code})")
            check(r.headers.get("content-security-policy") == CSP,
                  f"{ruta} lleva la CSP exacta: {r.headers.get('content-security-policy')!r}")
            check("frame-ancestors 'none'" in (r.headers.get("content-security-policy") or ""),
                  f"{ruta} prohíbe enmarcar (frame-ancestors 'none')")
            check(r.headers.get("x-frame-options") == "DENY",
                  f"{ruta} lleva X-Frame-Options: DENY para los motores viejos "
                  f"({r.headers.get('x-frame-options')!r})")
            check("text/html" in (r.headers.get("content-type") or ""),
                  f"{ruta} se sirve como documento HTML")

        # PRESERVE: la caché del HUD no se toca (el incidente del HUD viejo).
        r = await c.get("/static/js/command.js", headers={"host": HUD})
        check(r.status_code == 200, "command.js se sirve (200)")
        check(r.headers.get("cache-control") == "no-store, must-revalidate",
              f"command.js sigue con Cache-Control: no-store, must-revalidate "
              f"({r.headers.get('cache-control')!r})")
        check(r.headers.get("pragma") == "no-cache", "command.js sigue con Pragma: no-cache")
        check(r.headers.get("content-security-policy") is None,
              "la CSP no se pega a los estáticos: es una cabecera de documento")

        # Sin regresión: una ruta JSON sigue funcionando y no es un documento.
        r = await c.get("/api/link/status", headers={"host": HUD})
        check(r.status_code == 200, f"/api/link/status responde 200 (vino {r.status_code})")
        cuerpo = r.json()
        check(isinstance(cuerpo, dict), "la API sigue devolviendo JSON")
        check(r.headers.get("content-security-policy") is None,
              "el JSON no lleva CSP: la CSP gobierna documentos, no cargas útiles")
        check(r.headers.get("x-frame-options") is None,
              "el JSON no lleva X-Frame-Options (no se enmarca un JSON)")


# ══════════════════════════════════════════════════════════════════════════════
#  Estructura: los duplicados a mano de esc() no se quedan atrás
# ══════════════════════════════════════════════════════════════════════════════
def pruebas_duplicados() -> None:
    print("== los escapes copiados a mano en mobile.html ==")
    mobile = MOBILE_HTML.read_text(encoding="utf-8")
    check(re.search(r"\[&<>\"'\]/g", mobile) is not None
          and "'&#34;'" in mobile and "'&#39;'" in mobile,
          "escH de mobile.html escapa las dos comillas igual que esc()")
    check('/(https?:\\/\\/(?:&amp;|[^\\s<>"\'«»)&])+)/g' in mobile,
          "el linkify de mobile.html corta la URL en la entidad, como el de dom.js")
    check('<a href="\' + escH(u) +' in mobile,
          "el enlace «Reabrir» de mobile.html escapa la URL del servidor")
    check('href="\' + u + \'"' not in mobile,
          "y ya no queda ningún href construido con el dato en crudo")


def pruebas_inventario_inline() -> None:
    """El comentario de `_CSP_HUD` justifica `'unsafe-inline'` con números.

    Si esos números cambian (por ejemplo al hacer T18b, que los quita), esta
    comprobación se pone roja para que el comentario y la cabecera se actualicen
    a la vez. Un comentario que miente sobre por qué la CSP es débil es peor que
    no tener comentario.
    """
    print("== inventario de lo que obliga a 'unsafe-inline' ==")
    manejadores = 0
    bloques = 0
    for nombre in ("index.html", "mobile.html", "setup.html"):
        texto = (ROOT / "frontend" / nombre).read_text(encoding="utf-8")
        manejadores += len(re.findall(
            r"\son(?:click|load|error|input|change|submit)=", texto))
        bloques += len(re.findall(r"<script\s*>", texto))
    check(manejadores == 21,
          f"hay 21 manejadores en línea en el HUD (encontrados {manejadores}); "
          "si ya no son esos, T18b está hecho y toca quitar 'unsafe-inline'")
    check(bloques == 2,
          f"hay 2 bloques <script> en línea (encontrados {bloques})")


def main() -> None:
    pruebas_js()
    asyncio.run(_cabeceras())
    pruebas_duplicados()
    pruebas_inventario_inline()


try:
    main()
except Exception as exc:                                       # noqa: BLE001
    _fail.append(f"la suite se rompió: {exc!r}")
    import traceback
    traceback.print_exc()
finally:
    for carpeta in (_CFG, _DATA):
        shutil.rmtree(carpeta, ignore_errors=True)

print(f"\n{'#' * 54}\ntest_escapes_y_cabeceras: {_pass} OK, {len(_fail)} fallos")
for aviso in _saltos:
    print("  ⚠", aviso)
for m in _fail:
    print("  -", m)
sys.exit(1 if _fail else 0)
