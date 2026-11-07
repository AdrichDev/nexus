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

Y la COLA de SEC-10 (task T18c, ver `odd/tasks/security-audit-remediation.md`),
que es la deriva que quedó alrededor de `esc()`:

  4. `frontend/js/**` no puede tener una segunda implementación de escape.
     `command.js` tenía `esc2`, copia a mano del `esc()` VIEJO (sin comillas).
     Se borró: el módulo ya importa `esc` de `core/dom.js`. Aquí se pinea que
     no vuelva a aparecer ninguna (`esc2` ni ninguna otra copia), con registro
     explícito de las dos copias que SÍ tienen que existir porque no pueden
     importar módulos (`mobile.html` y el wizard `setup.html`), cada una
     comparada carácter a carácter con `esc()` ejecutando las dos.
  5. `frontend/setup.html` pintaba `href="${r.download}"` y `${r.out}` /
     `${r.error}` en crudo. Ahora escapa, y además solo convierte en enlace
     `http:`/`https:`: un `javascript:` del backend no puede quedar clicable en
     el asistente de primer arranque, donde la CSP mantiene
     `script-src 'unsafe-inline'`.
  6. `frontend/js/ui/widgets.js` interpola `name`/`val`/`delta`/`lbl` sin
     escapar. Ahora escapa todo sin cambiar NI UN BYTE lo que pinta en las
     cuatro llamadas reales del HUD (la prueba compara la implementación
     anterior, copiada aquí como fixture, contra la nueva).
  7. Todo `href="${...}"` de `frontend/**` pasa por un escape, o está en el
     registro de los dos `linkify` (donde el valor ya viene escapado).

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
- `ui/widgets.js` se IMPORTA tal cual y se compara contra las cuatro llamadas
  reales del HUD; el bloque de escape del wizard se extrae de `setup.html`
  entre dos marcadores (`INICIO/FIN bloque de escape del wizard`) y se ejecuta
  con `new Function`, con el mismo tratamiento: si los marcadores desaparecen,
  rojo.
- Los ratchets estructurales leen los ficheros SIN comentarios: explicar en un
  comentario qué había antes (`esc2`, `href="${r.download}"`) no puede disparar
  la prueba de que ya no está.
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
WIDGETS_JS = ROOT / "frontend" / "js" / "ui" / "widgets.js"
COMMAND_JS = ROOT / "frontend" / "js" / "command.js"
SETUP_HTML = ROOT / "frontend" / "setup.html"

# Los marcadores del bloque del wizard que se extrae y se ejecuta (los pone
# `frontend/setup.html`; si se renombran, esta suite se pone roja a propósito).
WIZARD_INI = "INICIO bloque de escape del wizard"
WIZARD_FIN = "FIN bloque de escape del wizard"

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

const [domPath, reelsPath, widgetsPath, setupPath, mobilePath] = process.argv.slice(2);
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

// ---- las copias de esc() que NO pueden importar módulos ----------------------
// Las tres funciones se ejecutan de verdad: si una copia se desvía de esc(),
// sale aquí. Vectores compartidos con las pruebas de widgets y del wizard.
const VECTORES = ['', null, undefined, 'normal', 'di "hola"', "es 'tuyo'",
                  '&<>"\'', '<script>alert(1)</script>',
                  'a" onmouseover="alert(1)', 'ñandú — «tilde» 7'];

// ---- widgets.js: mismo HTML en las llamadas reales, y a prueba de datos -----
// Implementación ANTERIOR (fixture copiado de widgets.js antes de T18c). No se
// lee de git: vive aquí para que la comparación no dependa de la historia.
const viejo = (() => {
  const v = {};
  v.ovCard = (ic, name, sub, on) =>
    '<div class="ov-card"><div class="ov-ic">' + ic + '</div><div><b>' + name + '</b>'
    + '<small>' + esc(sub) + '</small></div>'
    + '<span class="st ' + (on ? 'on' : 'off') + '">' + (on ? 'ON' : 'OFF') + '</span></div>';
  const GCOL = { cpu: '#22e6ff', ram: '#4d9bff', disk: '#ffd23a', gpu: '#4dff9e' };
  v.gauge = (k, label) =>
    '<div class="gauge"><div class="ring" id="g-' + k + '" style="--gc:' + (GCOL[k] || '#22d3ee') + '">'
    + '<b id="gv-' + k + '" style="color:' + (GCOL[k] || '#eaf6ff') + '">0%</b></div>'
    + '<div class="glabel">' + label + '</div></div>';
  v.kpi = (lbl, val, delta, cy) =>
    '<div class="kpi"><div class="lbl">' + lbl + '</div>'
    + '<div class="val ' + (cy ? 'cy' : '') + '">' + val + '</div>'
    + '<div class="delta">' + delta + '</div></div>';
  v.qc = (i, label, cmd, isPrompt, view) =>
    '<div class="qc" data-cmd="' + (cmd ? esc(cmd) : '') + '" data-prompt="'
    + (isPrompt ? 1 : '') + '" data-view="' + (view || '') + '"><i>' + i + '</i> '
    + label + '</div>';
  v.nsBtn = (label, cmd, isP, view) =>
    '<button class="ns-act" data-cmd="' + (cmd ? esc(cmd) : '') + '" data-p="'
    + (isP ? 1 : '') + '" data-v="' + (view || '') + '">▸ ' + esc(label) + '</button>';
  return v;
})();

try {
  const W = await import(pathToFileURL(widgetsPath).href);
  // Cada pareja es UNA llamada real del HUD (las de command.js, buscadas con
  // grep): la de antes contra la de ahora. Tienen que salir idénticas.
  const parejas = [
    ['ovCard núcleo', viejo.ovCard('◈', 'Núcleo IA', 'gemini', true),
     W.ovCard('◈', 'Núcleo IA', 'gemini', true)],
    ['ovCard memoria', viejo.ovCard('▣', 'Memoria', '12 notas', true),
     W.ovCard('▣', 'Memoria', '12 notas', true)],
    ['ovCard voz', viejo.ovCard('🎙', 'Voz', 'edge-tts', true),
     W.ovCard('🎙', 'Voz', 'edge-tts', true)],
    ['ovCard habilidades', viejo.ovCard('⚙', 'Habilidades', '7 activas', true),
     W.ovCard('⚙', 'Habilidades', '7 activas', true)],
    ['kpi interacciones',
     viejo.kpi('Interacciones', '<span id="kpi-inter">3</span>', 'sesión'),
     W.kpi('Interacciones', 3, 'sesión', 0, 'kpi-inter')],
    ['kpi habilidades', viejo.kpi('Habilidades', '7', 'activas', 1),
     W.kpi('Habilidades', '7', 'activas', 1)],
    ['kpi memoria',
     viejo.kpi('Memoria', '<span id="kpi-notes">12</span>', 'notas'),
     W.kpi('Memoria', 12, 'notas', 0, 'kpi-notes')],
    ['kpi procesos',
     viejo.kpi('Procesos', '<span id="kpi-procs">—</span>', 'sistema'),
     W.kpi('Procesos', '—', 'sistema', 0, 'kpi-procs')],
    // nsBtn lo llama views/knowledge.js (con `null` de comando y de vista).
    ['nsBtn ver memoria', viejo.nsBtn('Ver memoria', null, 0, 'memory'),
     W.nsBtn('Ver memoria', null, 0, 'memory')],
    ['nsBtn estado del equipo', viejo.nsBtn('Estado del equipo', null, 0, 'hardware'),
     W.nsBtn('Estado del equipo', null, 0, 'hardware')],
    ['nsBtn preguntar', viejo.nsBtn('Preguntar sobre esto', 'qué recuerdas de X'),
     W.nsBtn('Preguntar sobre esto', 'qué recuerdas de X')],
  ];
  salida.widgetsParejas = parejas;
  // Y con datos hostiles dentro: nada puede salirse del texto ni del atributo.
  salida.widgetsInyectado = {
    ovCard: W.ovCard('◈', 'x" onmouseover="alert(1)', "y' onclick='alert(1)", true),
    kpiTexto: W.kpi('a"b', 'c<d>"e"', "f'g'", 0),
    kpiId: W.kpi('l', 'v', 'd', 0, 'id" onload="alert(1)'),
    gauge: W.gauge('cpu"><script>alert(1)</script>', 'lab"el'),
    qc: W.qc('i"><b>', 'la"bel', 'cmd"x', false, 'vi"ew'),
    nsBtn: W.nsBtn('et"iqueta', 'cmd"x', false, 'vi"ew'),
  };
} catch (e) {
  salida.widgetsError = String((e && e.message) || e);
}

// ---- setup.html: el wizard escapa y valida el esquema del enlace ------------
try {
  const src = fs.readFileSync(setupPath, 'utf8');
  const i = src.indexOf('INICIO bloque de escape del wizard');
  const f = src.indexOf('FIN bloque de escape del wizard');
  if (i < 0 || f < 0 || f < i) {
    salida.wizardError = 'no encuentro el bloque de escape del wizard en setup.html';
  } else {
    const bloque = src.slice(src.indexOf('\n', i) + 1, src.lastIndexOf('\n', f));
    const fab = new Function(bloque
      + '\nreturn { html: _escapeHtml, url: _urlSegura, docker: htmlDocker };');
    const w = fab();
    // La copia del wizard contra esc(), valor a valor.
    salida.wizardEsc = VECTORES.map((v) => [String(v), w.html(v), esc(v)]);
    salida.wizardUrl = ['javascript:alert(1)', 'JaVaScRiPt:alert(1)',
                        ' JAVAscript:alert(1)', 'data:text/html,<script>x</script>',
                        'file:///C:/Windows/System32', 'vbscript:msgbox(1)',
                        'https://download.docker.com/win/stable/Docker.exe',
                        'HTTP://ejemplo.example/x', '', null].map((u) => [String(u), w.url(u)]);
    salida.wizardDocker = {
      payload: w.docker({ ok: false, error: '✕ "><script>alert(1)</script>',
                          out: '<img src=x onerror=alert(1)>', download: '' }),
      javascript: w.docker({ ok: false, error: 'x', out: 'y',
                             download: 'javascript:alert(1)' }),
      data: w.docker({ ok: false, error: 'x', out: 'y',
                       download: 'data:text/html,<script>alert(1)</script>' }),
      comilla: w.docker({ ok: false, error: 'x', out: 'y',
                          download: 'https://download.docker.com/x" onmouseover="alert(1)' }),
      normal: w.docker({ ok: false, error: 'boom', out: 'paso 1',
                         download: 'https://download.docker.com/win/stable/Docker.exe' }),
      sinDescarga: w.docker({ ok: false, error: 'boom', out: 'paso 1' }),
      ok: w.docker({ ok: true }),
      vacio: w.docker({ ok: false }),
    };
  }
} catch (e) {
  salida.wizardError = String((e && e.message) || e);
}

// ---- mobile.html: su escH (la otra copia que no puede importar) -------------
try {
  const mob = fs.readFileSync(mobilePath, 'utf8');
  const ini = 'const escH = ';
  const fin = '[c]))';
  const a = mob.indexOf(ini);
  const b = mob.indexOf(fin, a);
  if (a < 0 || b < 0) {
    salida.mobileError = 'no encuentro `const escH = ...` en mobile.html';
  } else {
    const expr = mob.slice(a + ini.length, b + fin.length);
    const escH = new Function('return (' + expr + ');')();
    salida.mobileEsc = VECTORES.map((v) => [String(v), escH(v), esc(v)]);
  }
} catch (e) {
  salida.mobileError = String((e && e.message) || e);
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
        [_node(), str(fichero), str(DOM_JS), str(REELS_JS), str(WIDGETS_JS), str(SETUP_HTML),
         str(MOBILE_HTML)],
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
        aviso = ("SIN NODE: no se ha ejecutado el JS (esc/linkify/mdToHtml/reels, "
                 "ui/widgets.js y el bloque de escape del wizard)")
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

    _pruebas_widgets(out)
    _pruebas_wizard(out)
    _pruebas_mobile(out)


# ══════════════════════════════════════════════════════════════════════════════
#  widgets.js: escapa, y las llamadas reales del HUD pintan lo mismo
# ══════════════════════════════════════════════════════════════════════════════
def _pruebas_widgets(out: dict) -> None:
    print("== ui/widgets.js: escapa sin cambiar lo que pinta el HUD ==")
    if not check("widgetsParejas" in out,
                 "no se ha podido ejecutar ui/widgets.js: " + out.get("widgetsError", "")):
        return
    # PRESERVE: las cuatro llamadas reales de command.js, antes contra ahora.
    for nombre, antes, ahora in out["widgetsParejas"]:
        check(antes == ahora,
              f"«{nombre}» pinta distinto después de escapar: {antes!r} != {ahora!r}")
    # Y al revés: con datos hostiles, no queda nada suelto.
    iny = out["widgetsInyectado"]
    for clave, html_pintado in iny.items():
        check('<script>' not in html_pintado and '<img' not in html_pintado,
              f"widgets.{clave} deja pasar una etiqueta del dato: {html_pintado!r}")
        check(' onmouseover="' not in html_pintado and ' onload="' not in html_pintado
              and ' onclick="' not in html_pintado,
              f"widgets.{clave} deja un manejador en línea vivo: {html_pintado!r}")
        check(html_pintado.count('"') % 2 == 0,
              f"widgets.{clave} deja las comillas de atributo descuadradas: {html_pintado!r}")
    check(f'<b>x{COMILLA} onmouseover={COMILLA}alert(1)</b>' in iny["ovCard"],
          f"ovCard escapa el nombre: {iny['ovCard']!r}")
    check(f'<div class="lbl">a{COMILLA}b</div>' in iny["kpiTexto"]
          and f'c&lt;d&gt;{COMILLA}e{COMILLA}' in iny["kpiTexto"]
          and f"f{APOS}g{APOS}" in iny["kpiTexto"],
          f"kpi escapa etiqueta, valor y variación: {iny['kpiTexto']!r}")
    check('id="id' in iny["kpiId"] and f'id="id{COMILLA} onload={COMILLA}alert(1)"' in iny["kpiId"],
          f"el id de kpi sale escapado dentro del atributo: {iny['kpiId']!r}")
    check(f'id="g-cpu{COMILLA}&gt;&lt;script&gt;' in iny["gauge"],
          f"gauge escapa la clave dentro del id: {iny['gauge']!r}")
    check(f'<div class="glabel">lab{COMILLA}el</div>' in iny["gauge"],
          f"gauge escapa la etiqueta: {iny['gauge']!r}")
    check(f'data-view="vi{COMILLA}ew"' in iny["qc"],
          f"qc escapa la vista que va al atributo: {iny['qc']!r}")
    check(f'<i>i{COMILLA}&gt;&lt;b&gt;</i>' in iny["qc"],
          f"qc escapa el icono y la etiqueta: {iny['qc']!r}")
    check('▸ et' in iny["nsBtn"] and f'et{COMILLA}iqueta' in iny["nsBtn"],
          f"nsBtn sigue escapando la etiqueta: {iny['nsBtn']!r}")


# ══════════════════════════════════════════════════════════════════════════════
#  setup.html: el wizard escapa el resultado de Docker y valida el esquema
# ══════════════════════════════════════════════════════════════════════════════
def _pruebas_mobile(out: dict) -> None:
    """La copia de mobile.html, EJECUTADA, contra esc(): misma salida o rojo.

    Es el otro fichero del registro de copias a mano (no puede importar
    módulos). Sin esto, la copia podría desviarse de `esc()` sin que nadie lo
    notara hasta que un dato con comilla aterrizara en su `href` «Reabrir».
    """
    print("== mobile.html: su escH da exactamente lo mismo que esc() ==")
    if not check("mobileEsc" in out,
                 "no se ha podido ejecutar escH de mobile.html: "
                 + out.get("mobileError", "")):
        return
    for texto, suyo, oficial in out["mobileEsc"]:
        check(suyo == oficial,
              f"escH de mobile.html se desvía de esc() en {texto!r}: {suyo!r} != {oficial!r}")


def _pruebas_wizard(out: dict) -> None:
    print("== setup.html: el wizard escapa y no enlaza un `javascript:` ==")
    if not check("wizardEsc" in out,
                 "no se ha podido ejecutar el escape del wizard: "
                 + out.get("wizardError", "")):
        return
    # La copia del wizard, contra esc() de dom.js: valor a valor.
    for texto, suyo, oficial in out["wizardEsc"]:
        check(suyo == oficial,
              f"el escape del wizard se desvía de esc() en {texto!r}: {suyo!r} != {oficial!r}")
    # Esquema: solo http(s) puede llegar a un href.
    for url, limpia in out["wizardUrl"]:
        if re.match(r"(?i)^https?://", url):
            check(limpia == url, f"una URL http(s) legítima se rechaza: {url!r} → {limpia!r}")
        else:
            check(limpia == "", f"«{url}» no es http(s) y sobrevive a _urlSegura: {limpia!r}")
    # PRESERVE: el ramal de éxito es el de siempre, palabra por palabra.
    check("✔ Contenedores creados: BD semántica y n8n en marcha."
          in out["wizardDocker"]["ok"],
          f"el mensaje de éxito cambia: {out['wizardDocker']['ok']!r}")
    # Y el de error: el texto se ve, pero escapado.
    normal = out["wizardDocker"]["normal"]
    check("✕ boom" in normal and "paso 1" in normal,
          f"el error y la salida de Docker se siguen viendo: {normal!r}")
    check('<a href="https://download.docker.com/win/stable/Docker.exe"'
          ' target="_blank" rel="noopener">' in normal,
          f"la descarga legítima sigue siendo un enlace: {normal!r}")
    check("Descarga Docker aquí" in normal, "el texto de la descarga no cambia")
    check("boom" in out["wizardDocker"]["sinDescarga"]
          and "<a " not in out["wizardDocker"]["sinDescarga"],
          "sin `download` no aparece ningún enlace")
    vacio = out["wizardDocker"]["vacio"]
    check("✕" in vacio and "None" not in vacio,
          f"un error vacío no imprime «undefined»/«None»: {vacio!r}")
    # El payload no rompe ni el texto ni el atributo.
    payload = out["wizardDocker"]["payload"]
    check("<script>" not in payload and "<img" not in payload,
          f"el wizard deja pasar etiquetas del backend: {payload!r}")
    check(' onmouseover="' not in payload and ' onerror="' not in payload,
          f"el wizard deja un manejador vivo: {payload!r}")
    check(payload.count('"') % 2 == 0,
          f"el HTML del wizard deja comillas descuadradas: {payload!r}")
    check(f'✕ {COMILLA}&gt;&lt;script&gt;alert(1)&lt;/script&gt;' in payload,
          f"el error del backend sale escapado: {payload!r}")
    # Un `javascript:` (o `data:`) NO queda clicable, pero se sigue leyendo.
    for clave in ("javascript", "data"):
        html_pintado = out["wizardDocker"][clave]
        check("<a " not in html_pintado and "href=" not in html_pintado,
              f"un `{clave}:` del backend se convierte en enlace: {html_pintado!r}")
        check(clave + ":" in html_pintado,
              f"un `{clave}:` rechazado debería verse como texto, no desaparecer: {html_pintado!r}")
    comilla = out["wizardDocker"]["comilla"]
    check(f'href="https://download.docker.com/x{COMILLA} onmouseover={COMILLA}'
          'alert(1)"' in comilla,
          f"la comilla de la URL no rompe el href: {comilla!r}")
    check(comilla.count('"') % 2 == 0,
          f"el href de la descarga deja las comillas descuadradas: {comilla!r}")


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


# ══════════════════════════════════════════════════════════════════════════════
#  Ratchets: ni una segunda implementación de escape, ni un href en crudo
# ══════════════════════════════════════════════════════════════════════════════
# Un escape "a mano" se reconoce por su forma: un `replace` con una clase de
# caracteres que lleva a la vez `&` y `<` (el mapa HTML mínimo). No se busca el
# nombre —`escH`, `_escapeHtml`, el que sea— porque renombrar la copia no la
# arregla: el problema es que exista.
_MAPA_A_MANO = re.compile(r"\.replace\(\s*/\[[^\]]*&[^\]]*<[^\]]*\]/g")

# Las ÚNICAS copias que pueden existir, y por qué. `esc()` vive en
# `frontend/js/core/dom.js`; estas dos páginas se sirven como documento suelto
# con el script EN LÍNEA, así que no pueden importar un módulo ES. Cada copia
# está además comparada EJECUTÁNDOLA contra `esc()` en esta misma suite: el
# registro no es una excusa, es una promesa que se verifica.
_ESCAPES_A_MANO = {
    "frontend/js/core/dom.js": "la fuente de verdad: exporta esc()",
    "frontend/mobile.html": "página sin módulos: su escH, comparado con esc()",
    "frontend/setup.html": "wizard con <script> en línea: su _escapeHtml, comparado con esc()",
}


def _ficheros_frontend() -> list[Path]:
    """Todo el frontend que pinta datos: HTML suelto + el árbol de módulos."""
    fuera = sorted((ROOT / "frontend").glob("*.html"))
    fuera += sorted((ROOT / "frontend" / "js").rglob("*.js"))
    return fuera


def _rel(f: Path) -> str:
    return f.relative_to(ROOT).as_posix()


def _sin_comentarios(texto: str) -> str:
    """El CÓDIGO: sin comentarios de bloque ni líneas que empiecen por `//`.

    Importa: los comentarios de este mismo cambio explican qué había antes
    (`esc2`, `href="${r.download}"`) y un ratchet que se dispare con la
    explicación de lo que arregla obliga a no explicarlo. No se quita el `//`
    que va detrás de código: ahí viven las URL (`https://…`).
    """
    texto = re.sub(r"/\*(?:.|\n)*?\*/", " ", texto)
    return re.sub(r"(?m)^\s*//[^\n]*$", " ", texto)


def pruebas_sin_copias_de_escape() -> None:
    print("== no queda ninguna segunda implementación de esc() a mano ==")
    vistos: dict[str, list[int]] = {}
    for f in _ficheros_frontend():
        texto = _sin_comentarios(f.read_text(encoding="utf-8"))
        for m in _MAPA_A_MANO.finditer(texto):
            vistos.setdefault(_rel(f), []).append(texto.count("\n", 0, m.start()) + 1)
    for rel, lineas in vistos.items():
        check(rel in _ESCAPES_A_MANO,
              f"{rel}:{lineas[0]} tiene un escape copiado a mano; importa esc() "
              "de frontend/js/core/dom.js (o, si la página no puede importar, "
              "añádelo al registro de esta suite con su razón y su prueba)")
    for rel in _ESCAPES_A_MANO:
        check(rel in vistos, f"el registro dice que {rel} tiene un escape a mano y ya no lo tiene")
    # `esc2` no es un escape: es un nombre. Se pinea aparte porque su forma
    # (sin comillas) no la caza el patrón de arriba y fue el bug de T18c.
    for f in _ficheros_frontend():
        texto = _sin_comentarios(f.read_text(encoding="utf-8"))
        check(re.search(r"\besc2\b", texto) is None,
              f"{_rel(f)} vuelve a tener un `esc2`: usa esc() de core/dom.js")


# Un `href` puede escribirse de dos maneras: plantilla o concatenación.
_HREF_PLANTILLA = re.compile(r'href="\$\{([^{}]*)\}"')
_HREF_CONCAT = re.compile(r"""href="'\s*\+\s*(.+?)\s*\+\s*'""")
_ESCAPA = re.compile(r"^(?:esc|escH|_escapeHtml)\s*\(")

# Los dos `linkify` interpolan la URL SIN volver a escapar, y es correcto: `u`
# es el trozo de texto que ya pasó por el escape (dom.js) / `escH` (mobile.html)
# y su regex corta en la entidad `&#34;`, así que dentro del href no puede haber
# ni una comilla cruda. Comprobado en la sección de `linkify` de arriba.
_HREF_CRUDO_JUSTIFICADO = {
    ("frontend/js/core/dom.js", "u"): "linkify: `u` sale del texto YA escapado",
    ("frontend/mobile.html", "u"): "la copia de linkify de mobile.html, misma razón",
}


def pruebas_hrefs_escapados() -> None:
    print("== todo href interpolado pasa por un escape ==")
    vistos: set[tuple[str, str]] = set()
    for f in _ficheros_frontend():
        if f.name.endswith(".min.js"):                 # qrcode: librería de terceros
            continue
        texto = _sin_comentarios(f.read_text(encoding="utf-8"))
        for patron in (_HREF_PLANTILLA, _HREF_CONCAT):
            for m in patron.finditer(texto):
                expr = m.group(1).strip()
                linea = texto.count("\n", 0, m.start()) + 1
                if _ESCAPA.match(expr):
                    continue
                vistos.add((_rel(f), expr))
                check((_rel(f), expr) in _HREF_CRUDO_JUSTIFICADO,
                      f"{_rel(f)}:{linea} mete «{expr}» en un href sin escaparlo")
    for clave in _HREF_CRUDO_JUSTIFICADO:
        check(clave in vistos,
              f"el registro justifica el href crudo «{clave[1]}» de {clave[0]} y ya no existe")


def pruebas_command_sin_esc2() -> None:
    print("== command.js: la vista «Hoy» usa el esc() de verdad ==")
    js = _sin_comentarios(COMMAND_JS.read_text(encoding="utf-8"))
    check("import { $, $$, esc, linkify, api, flash, mdToHtml } from './core/dom.js';" in js,
          "command.js sigue importando esc() de core/dom.js (sin él no hay escape oficial)")
    desde = js.find("async function loadToday()")
    hasta = js.find("views.hardware = () =>", desde)
    check(0 < desde < hasta, "no encuentro la vista «Hoy» (loadToday) en command.js")
    bloque = js[desde:hasta] if 0 < desde < hasta else ""
    # Los datos del servidor que esta vista pinta: cada uno, dentro de esc().
    for expr in ("d.clima", "x.title", "x.due", "j.num", "j.orden",
                 "w.num", "w.tipo", "w.objetivo", "n"):
        check(f"${{esc({expr})}}" in bloque,
              f"la vista «Hoy» pinta «{expr}» sin esc(): «${{esc({expr})}}» no aparece")
    check("esc2" not in bloque, "la vista «Hoy» se ha quedado con su esc2")


def pruebas_wizard_estructura() -> None:
    print("== setup.html: ni un dato del backend en crudo ==")
    html = _sin_comentarios(SETUP_HTML.read_text(encoding="utf-8"))
    for crudo in ('href="${r.download}"', "${r.out || ''}</span>", "${r.error || ''}</span>"):
        check(crudo not in html, f"setup.html sigue con un dato del backend en crudo: {crudo}")
    check("<a href=\"${_escapeHtml(u)}\"" in html,
          "el enlace de descarga del wizard no escapa la URL")
    check("_urlSegura" in html and re.search(r"\^https\?:", html) is not None,
          "el wizard no valida el esquema: solo http(s) puede llegar a un href")
    check("core/dom.js" in SETUP_HTML.read_text(encoding="utf-8"),
          "el wizard no dice que su copia viene de esc() de core/dom.js")


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
    pruebas_sin_copias_de_escape()
    pruebas_hrefs_escapados()
    pruebas_command_sin_esc2()
    pruebas_wizard_estructura()
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
