# -*- coding: utf-8 -*-
"""El frontend es un arbol de modulos ES: esta suite comprueba que encaja.

Por que existe. Al partir command.js (3.624 lineas) en modulos, un simbolo que
se usa pero no se importa NO da error al cargar: revienta en tiempo de ejecucion
la primera vez que se pinta esa vista. Paso de verdad —`$$ is not defined` en la
vista Reels— y solo lo cazo la e2e, que tarda dos minutos y necesita Chromium.
Esto tarda un segundo y no necesita navegador.

Lo que comprueba:
  1) Todo simbolo exportado por otro modulo y usado en un fichero esta importado.
  2) Todo import apunta a un fichero que existe y que exporta ese simbolo.
  3) index.html carga command.js como modulo (si no, los import son un error).
  4) Ningun fichero del arbol se queda huerfano, sin que nadie lo importe.

Ejecutar:  .venv\\Scripts\\python.exe tests\\unit\\frontend\\test_modules.py
"""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
JS = ROOT / "frontend" / "js"
CONFIG_PY = ROOT / "backend" / "core" / "comun" / "config.py"

# Scripts clasicos: dejan su API en window y NO son modulos. Se quedan fuera.
CLASICOS = {"qrcode.min.js", "reactor.js", "charts.js"}

_fail: list[str] = []
_saltos: list[str] = []          # avisos de lo que NO se ha podido probar
_pass = 0

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                          # noqa: BLE001
    pass


def check(cond, msg: str) -> bool:
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  ✖", msg)
    return bool(cond)


def modulos() -> list[Path]:
    return sorted(f for f in JS.rglob("*.js") if f.name not in CLASICOS)


def exportados(txt: str) -> set[str]:
    """Nombres que el fichero exporta (function, const/let, y listas {a, b})."""
    fuera = set(re.findall(r"export\s+(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", txt))
    fuera |= set(re.findall(r"export\s+(?:const|let|var)\s+([A-Za-z_$][\w$]*)", txt))
    for grupo in re.findall(r"export\s*\{([^}]*)\}", txt):
        fuera |= {n.strip().split()[-1] for n in grupo.split(",") if n.strip()}
    return fuera


def lineas_import(txt: str) -> list[tuple[set[str], str]]:
    """[(simbolos, ruta)] de cada import. Tolera CRLF y varias lineas."""
    out = []
    for grupo, ruta in re.findall(r"import\s*\{([^}]*)\}\s*from\s*['\"]([^'\"]+)['\"]", txt):
        simbolos = {n.strip().split()[-1] for n in grupo.split(",") if n.strip()}
        out.append((simbolos, ruta))
    return out


def sin_imports(txt: str) -> str:
    """El cuerpo real: sin imports, sin comentarios y sin cadenas.

    Los comentarios importan: `ui/widgets.js` documenta «Lo cablea wireNs()» y
    eso no es usar wireNs. Sin quitarlos, el comprobador exige un import que
    nadie necesita.
    """
    txt = re.sub(r"import\s*\{[^}]*\}\s*from\s*['\"][^'\"]+['\"]\s*;?", "", txt)
    txt = re.sub(r"/\*(?:.|\n)*?\*/", " ", txt)            # comentarios de bloque
    txt = re.sub(r"^\s*//[^\n]*", " ", txt, flags=re.M)    # y de linea entera
    # Las plantillas `...` NO se quitan: dentro de un ${...} hay llamadas de
    # verdad —`${esc(x)}`, `${qc(...)}`— y ahi es donde vive casi todo el HTML.
    return txt


print("== 1) cada modulo declara lo que usa ==")

TODOS = modulos()
EXPORTA: dict[Path, set[str]] = {f: exportados(f.read_text(encoding="utf-8")) for f in TODOS}
# simbolo -> fichero que lo exporta (si dos lo exportan, se avisa)
DUENYO: dict[str, Path] = {}
for f, ss in EXPORTA.items():
    for s in ss:
        check(s not in DUENYO,
              f"«{s}» lo exportan dos modulos: {DUENYO.get(s, '')} y {f.name}")
        DUENYO[s] = f

for f in TODOS:
    txt = f.read_text(encoding="utf-8")
    cuerpo = sin_imports(txt)
    ya = set()
    for simbolos, _ruta in lineas_import(txt):
        ya |= simbolos
    propios = EXPORTA[f] | set(re.findall(r"(?:function|const|let|var)\s+([A-Za-z_$][\w$]*)", cuerpo))
    for simbolo, duenyo in DUENYO.items():
        if duenyo == f or simbolo in ya or simbolo in propios:
            continue
        # `state.x` y `CATALOG[x]` no llevan parentesis; el resto son funciones.
        patron = (r"(?<![\w$.])" + re.escape(simbolo)
                  + (r"\s*[\(\[\.]" if simbolo not in ("state",) else r"\b"))
        if re.search(patron, cuerpo):
            check(False, f"{f.name} usa «{simbolo}» y no lo importa "
                         f"(lo exporta {duenyo.name})")

print("== 2) los imports apuntan a algo que existe y exporta eso ==")
for f in TODOS:
    txt = f.read_text(encoding="utf-8")
    for simbolos, ruta in lineas_import(txt):
        destino = (f.parent / ruta).resolve()
        if not check(destino.exists(), f"{f.name} importa de «{ruta}», que no existe"):
            continue
        fuera = EXPORTA.get(destino, exportados(destino.read_text(encoding="utf-8")))
        for s in simbolos:
            check(s in fuera, f"{f.name} importa «{s}» de {destino.name}, "
                              "que no lo exporta")

print("== 3) index.html carga el punto de entrada como modulo ==")
html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
check(re.search(r'<script\s+type="module"\s+src="/static/js/command\.js"', html) is not None,
      "index.html no carga command.js con type=\"module\": los import serian un error")
check("command.js?v=" not in html,
      "index.html sigue con ?v=NN en command.js; /static ya va con Cache-Control: no-store "
      "y la query no se propaga a los import de un modulo")

print("== 4) no hay modulos huerfanos ==")
ENTRADA = {"command.js"}
importados_por_alguien: set[Path] = set()
for f in TODOS:
    for _s, ruta in lineas_import(f.read_text(encoding="utf-8")):
        destino = (f.parent / ruta).resolve()
        if destino.exists():
            importados_por_alguien.add(destino)
for f in TODOS:
    if f.name in ENTRADA:
        continue
    check(f.resolve() in importados_por_alguien,
          f"{f.relative_to(ROOT)} no lo importa nadie: o sobra, o falta cablearlo")

# ═══════════════════════════════════════════════════════════════════════════════
# 5) GUARDAS DEL PANEL ⚙ (T31): pintarlas y guardarlas sin ensanchar permisos
# ═══════════════════════════════════════════════════════════════════════════════
# Por qué esto vive aquí y no en una e2e: el bug que cierra T31 no se ve. En
# `guardar()`, `perm_files: $('#m-permfiles') ? $('#m-permfiles').value : 'todo'`
# convertía un panel a medio pintar en el permiso MÁS AMPLIO que existe, y lo
# mandaba al backend en silencio. Un panel incompleto no puede ensanchar nada:
# si el control no está, la clave NO viaja. Eso es lo que se prueba, ejecutando
# el JavaScript de verdad con `node` (sin navegador).
#
# Si `node` no está en el PATH se dice con el mismo aviso honesto que usa
# `test_escapes_y_cabeceras.py` («SIN NODE»): una suite verde sin node NO es
# prueba de que el panel guarde bien.

print("== 5) guardas del panel ⚙: pintar y guardar sin ensanchar permisos ==")

# Claves que gobiernan permisos o consentimientos. Ninguna puede leerse ni
# escribirse fuera del bloque de guardas: una segunda lectura es una segunda
# oportunidad de poner un valor por defecto que ensanche.
CLAVES_GUARDAS = ("perm_files", "perm_folders", "perm_hardware",
                  "backup_destino_extra",
                  "permitir_fallback_nube", "permitir_delegacion_nube")

# El secreto del fixture: si aparece en el HTML que produce el HUD, el HUD lo
# habría recibido. Es de mentira, pero con la forma exacta de una clave real.
SECRETO = "sk-live-ABCDEF0123456789"

ARNES = r'''
import { pathToFileURL } from 'node:url';
import fs from 'node:fs';

const bloque = fs.readFileSync(process.argv[2], 'utf8');
const { esc } = await import(pathToFileURL(process.argv[3]).href);
const SECRETO = 'sk-live-ABCDEF0123456789';

const G = new Function('esc', bloque + `
  return { GUARDAS_PANEL, payloadGuardas, avisoAccesoArchivos, seccionPermisos,
           textoCodigoTelegram, vincularTelegram, textoSecretosIlegibles,
           htmlPresupuesto };`)(esc);

const out = {};

// 1) sin NINGÚN control en el DOM no se manda ni una guarda
out.sinControles = G.payloadGuardas(() => null);

// 2) con todos los controles
const todos = { 'm-permfiles': 'todo', 'm-permfolders': 'C:\\A\n\n  C:\\B  ',
                'm-hw': false, 'm-backupextra': 'D:\\Copias\\nexus',
                'm-nubefb': true, 'm-nubedel': false };
out.conTodos = G.payloadGuardas((id) => (id in todos ? todos[id] : null));

// 3) con uno ausente: el resto entra, ese NO
const parcial = Object.assign({}, todos);
delete parcial['m-nubedel'];
out.parcial = G.payloadGuardas((id) => (id in parcial ? parcial[id] : null));
out.parcialSinPermisos = G.payloadGuardas((id) => (id === 'm-op' ? 'Ana' : null));
// T31b: sin la caja del destino extra, esa clave NO viaja (no se inventa «sin copia»)
const sinBackup = Object.assign({}, todos);
delete sinBackup['m-backupextra'];
out.sinBackup = G.payloadGuardas((id) => (id in sinBackup ? sinBackup[id] : null));

// 4) la sección: valores de fábrica (config vacía) y en «todo»
out.permisosFabrica = G.seccionPermisos({});
out.permisosTodo = G.seccionPermisos({ perm_files: 'todo' });
out.permisosCarpetas = G.seccionPermisos({ perm_files: 'carpetas' });
out.permisosSandbox = G.seccionPermisos({ perm_files: 'sandbox' });
// PRESERVE: los tres controles de siempre siguen ahí y siguen leyendo su valor
out.permisosComoSiempre = G.seccionPermisos(
  { perm_files: 'carpetas', perm_hardware: false, perm_folders: ['C:\\\\MisDocs'] });
// T31b: la caja del destino extra se pinta con el valor guardado (y vacía de fábrica)
out.permisosBackup = G.seccionPermisos({ backup_destino_extra: 'D:\\Copias\\nexus' });
out.avisoTodo = G.avisoAccesoArchivos('todo');
out.avisoCarpetas = G.avisoAccesoArchivos('carpetas');
out.avisoSandbox = G.avisoAccesoArchivos('sandbox');

// 5) Telegram: UNA petición por clic
let pedidas = 0;
const pintado = [];
const ok = await G.vincularTelegram(
  async () => { pedidas += 1; return { codigo: 'ABCD2345', ttl_segundos: 600 }; },
  (html, mal) => pintado.push({ html, mal }));
out.tgPedidas = pedidas;
out.tgOk = ok;
out.tgPintado = pintado[pintado.length - 1].html;
out.tgMarcado = pintado[pintado.length - 1].mal === true;

let pedidasMal = 0;
const pintadoMal = [];
const okMal = await G.vincularTelegram(
  async () => { pedidasMal += 1; return { error: 'solo en este equipo' }; },
  (html, mal) => pintadoMal.push({ html, mal }));
out.tgPedidasError = pedidasMal;
out.tgOkError = okMal;
out.tgPintadoError = pintadoMal[pintadoMal.length - 1].html;
out.tgErrorMarcado = pintadoMal[pintadoMal.length - 1].mal === true;

// 6) presupuesto y claves ilegibles, con fixture HOSTIL (lleva un secreto dentro)
out.presupuesto = G.htmlPresupuesto({
  dia: '2026-01-01', llamadas: 37, caracteres: 120456,
  limites: { llamadas: 400, caracteres: 5000000, incluye_locales: false },
  agotado: false, por_proveedor: { openai: { llamadas: 30 }, ollama: { llamadas: 7 } },
  delegaciones: { gemini: 3 }, delegaciones_total: 3, tokens_reales: ['openai'] });
out.presupuestoAgotado = G.htmlPresupuesto({ llamadas: 400, caracteres: 9,
  limites: { llamadas: 400, caracteres: 5000000 }, agotado: true,
  tokens_reales: [], delegaciones: {}, delegaciones_total: 0 });
out.presupuestoHostil = G.htmlPresupuesto({ llamadas: 1, caracteres: 2,
  limites: { llamadas: 400, caracteres: 5000000 }, agotado: false,
  tokens_reales: [SECRETO, 'dpapi:v1:' + SECRETO],
  delegaciones: {}, delegaciones_total: 0, por_proveedor: {} });
out.presupuestoNada = G.htmlPresupuesto(null);
out.secretos = G.textoSecretosIlegibles(['openai_api_key', 'dpapi:v1:' + SECRETO, SECRETO]);
out.secretosVacio = G.textoSecretosIlegibles([]);
out.secretosNoLista = G.textoSecretosIlegibles(null);

console.log(JSON.stringify(out));
'''


def _defaults(*claves: str) -> dict:
    """Los valores de `DEFAULTS` de `backend/core/comun/config.py`, sin importar
    el backend (importarlo carga dotenv y rutas del operador). Se lee el AST y
    solo se evalúan los literales que se piden: el dict tiene llamadas dentro."""
    for node in ast.parse(CONFIG_PY.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "DEFAULTS"
                                                for t in node.targets):
            out = {}
            for k, v in zip(node.value.keys, node.value.values):
                nombre = getattr(k, "value", None)
                if nombre in claves:
                    try:
                        out[nombre] = ast.literal_eval(v)
                    except ValueError:
                        pass
            return out
    return {}


def _marcado(html: str, cid: str):
    """¿Sale ese checkbox marcado? None si el control no está en el HTML."""
    m = re.search(r'<input[^>]*id="' + re.escape(cid) + r'"[^>]*>', html)
    return None if not m else ("checked" in m.group(0))


def _opcion(html: str, cid: str):
    """La opción marcada del `<select id="cid">` (None si no hay ninguna)."""
    m = re.search(r'<select id="' + re.escape(cid) + r'"[^>]*>(.*?)</select>',
                  html, re.S)
    if not m:
        return None
    o = re.search(r"<option selected>([^<]*)</option>", m.group(1))
    return o.group(1).strip() if o else None


def _corre_arnes(bloque: str, tmp: Path):
    """Ejecuta el bloque de guardas con node. None si no hay node o revienta."""
    node = shutil.which("node")
    if node is None:
        return None
    (tmp / "bloque.js").write_text(bloque, encoding="utf-8")
    (tmp / "arnes.mjs").write_text(ARNES, encoding="utf-8")
    r = subprocess.run([node, str(tmp / "arnes.mjs"), str(tmp / "bloque.js"),
                        str(JS / "core" / "dom.js")],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=90)
    if r.returncode != 0:
        print("  ✖ node no ha podido ejecutar el bloque de guardas de command.js")
        print((r.stderr or r.stdout or "")[:2000])
        return None
    return json.loads(r.stdout.strip().splitlines()[-1])


class _Temporal:
    """Carpeta de usar y tirar FUERA del árbol del repo, que se borra al salir."""

    def __enter__(self) -> Path:
        self.d = Path(tempfile.mkdtemp(prefix="nexus-guardas-"))
        return self.d

    def __exit__(self, *_exc) -> None:
        shutil.rmtree(self.d, ignore_errors=True)


cmd_txt = (JS / "command.js").read_text(encoding="utf-8")
m_ini = re.search(r"^\s*/\* =+ INICIO bloque de guardas", cmd_txt, re.M)
m_fin = re.search(r"^\s*/\* =+ FIN bloque de guardas", cmd_txt, re.M)
bloque = ""
if check(m_ini is not None and m_fin is not None and m_ini.end() < m_fin.start(),
         "command.js no tiene el bloque de guardas entre sus marcadores INICIO/FIN "
         "(la suite extrae ese trozo tal cual para ejecutarlo)"):
    # desde el final de la LÍNEA del marcador: lo que queda de ese comentario no
    # es JavaScript válido si se cuela en el trozo.
    bloque = cmd_txt[cmd_txt.index("\n", m_ini.end()) + 1:m_fin.start()]

# La guarda vieja: un panel a medio pintar empujaba el modo MÁS permisivo.
check("$('#m-permfiles') ? $('#m-permfiles').value : 'todo'" not in cmd_txt,
      "sigue el fallback de la línea 2061: sin el control, perm_files se ponía en «todo»")
check("...payloadGuardas(" in cmd_txt,
      "guardar() no usa payloadGuardas(): las guardas se leen a mano otra vez")

# Y el trinquete: fuera del bloque no se lee ni se escribe ninguna de las claves
# de guarda. Una segunda lectura es otra oportunidad de ensanchar en silencio.
if m_ini is not None and m_fin is not None:
    fuera = cmd_txt[:m_ini.start()] + cmd_txt[m_fin.end():]
    for clave in CLAVES_GUARDAS:
        check(f"'{clave}'" not in fuera,
              f"«{clave}» vuelve a leerse/escribirse fuera del bloque de guardas: "
              "su valor por defecto deja de estar en un solo sitio")

# El endpoint del código de vinculación REGENERA el código en cada GET, así que
# pedirlo sin que el dueño lo pida invalida el que tenga en la mano. Esta
# comprobación es a propósito ESTRUCTURAL (grep sobre el fichero SIN comentarios:
# explicar en un comentario que el endpoint regenera el código no puede contar
# como llamarlo), y lo dice: lo que se pinea es que se nombre UNA vez y que esa
# vez sea el manejador del clic.
def _sin_comentarios(js: str) -> str:
    js = re.sub(r"/\*(?:.|\n)*?\*/", " ", js)
    js = re.sub(r"^\s*//[^\n]*", " ", js, flags=re.M)
    return js


cmd_codigo = _sin_comentarios(cmd_txt)
lineas_tg = [ln for ln in cmd_codigo.splitlines() if "/api/telegram/link" in ln]
check(len(lineas_tg) == 1,
      f"command.js nombra /api/telegram/link {len(lineas_tg)} veces: solo puede "
      "nombrarse en el manejador del clic (cada GET invalida el código anterior)")
if lineas_tg:
    _idx = cmd_codigo.splitlines().index(lineas_tg[0])
    _antes = "\n".join(cmd_codigo.splitlines()[max(0, _idx - 8):_idx + 1])
    check("addEventListener('click'" in _antes and "vincularTelegram" in _antes,
          "la única mención de /api/telegram/link no está dentro del manejador del "
          "clic: alguien la llama desde un refresco, un arranque o un temporizador")
check(not re.search(r"set(?:Interval|Timeout)\([^)]*telegram", cmd_codigo, re.I),
      "hay un temporizador pidiendo el código de Telegram: cada tick anula el anterior")

with _Temporal() as tmp:
    res = _corre_arnes(bloque, tmp)

if res is None:
    # Mismo patrón honesto que test_escapes_y_cabeceras.py: sin node no se
    # EJECUTA el JavaScript, así que se dice en voz alta y se comprueba solo la
    # estructura. Una suite verde sin node NO es prueba de que el panel guarde
    # bien, y esto lo deja escrito en la salida.
    aviso = ("SIN NODE: no se ha ejecutado el bloque de guardas de command.js "
             "(construir el payload, pintar el panel y el código de Telegram), y "
             "eso es justo lo que prueba esta parte")
    _saltos.append(aviso)
    print("  ⚠ " + aviso)
    check("function payloadGuardas" in bloque and ": 'todo'" not in bloque,
          "el bloque no declara payloadGuardas, o lleva un valor por defecto que "
          "ensancha (solo estructura: sin node no se ejecuta)")
    check('id="m-nubefb"' in bloque and "permitir_fallback_nube === true" in bloque,
          "la casilla de la reserva de nube no está, o su defecto no es FALSE")
    check('id="m-nubedel"' in bloque and "permitir_delegacion_nube !== false" in bloque,
          "la casilla de la delegación no está, o su defecto no es TRUE")
    check('id="m-backupextra"' in bloque and "backup_destino_extra" in bloque,
          "la caja del destino de la copia (T31b) no está en el bloque de guardas")
    check("async function vincularTelegram" in bloque,
          "no hay manejador del código de Telegram en el bloque")
else:
    # --- el payload: lo que NO está, no viaja ---
    sin = res["sinControles"]
    check(sin == {} or not sin,
          f"sin ningún control, el payload lleva cosas: {sin}")
    for clave in CLAVES_GUARDAS:
        check(clave not in sin, f"sin el control, «{clave}» NO puede ir en el payload")

    todos = res["conTodos"]
    check(todos.get("perm_files") == "todo", f"perm_files no viaja: {todos}")
    check(todos.get("perm_folders") == ["C:\\A", "C:\\B"],
          f"perm_folders no se parte por líneas y se limpia: {todos.get('perm_folders')!r}")
    check(todos.get("perm_hardware") is False, f"perm_hardware no viaja: {todos}")
    check(todos.get("permitir_fallback_nube") is True, f"permitir_fallback_nube no viaja: {todos}")
    check(todos.get("permitir_delegacion_nube") is False, f"permitir_delegacion_nube no viaja: {todos}")

    parcial = res["parcial"]
    check("permitir_delegacion_nube" not in parcial,
          f"el control ausente sigue mandando su clave: {parcial}")
    check(parcial.get("permitir_fallback_nube") is True,
          f"y los que sí están tienen que seguir entrando: {parcial}")
    check(res["parcialSinPermisos"] == {} or not res["parcialSinPermisos"],
          f"sin ningún control de guarda el payload no puede llevar claves: {res['parcialSinPermisos']}")

    # --- T31b: el destino de la copia de TODO `data/` tiene su ⚙ y su regla ---
    check(todos.get("backup_destino_extra") == "D:\\Copias\\nexus",
          f"backup_destino_extra no viaja con su valor: {todos}")
    check("backup_destino_extra" not in res["sinBackup"],
          f"sin la caja del destino extra, su clave NO puede viajar: {res['sinBackup']}")
    check(res["sinBackup"].get("perm_files") == "todo",
          "omitir una guarda no puede llevarse por delante las demás")
    backup = res["permisosBackup"]
    check('id="m-backupextra"' in backup,
          "falta la caja del destino de la copia en PERMISOS (T31b)")
    check("D:\\Copias\\nexus" in backup,
          f"la caja no lleva el valor guardado: {backup[:240]}")
    check("data/" in backup and "TODO" in backup,
          "la explicación no dice que ahí va una copia de TODO `data/`")
    check("mismo disco" in backup,
          "la explicación no avisa de que en el mismo disco no protege de nada")
    _caja = re.search(r'<input[^>]*id="m-backupextra"[^>]*>', res["permisosFabrica"])
    check(_caja is not None and 'value=""' in _caja.group(0),
          f"de fábrica la caja tiene que salir VACÍA (sin segunda copia): {_caja and _caja.group(0)!r}")

    # --- los defaults del panel son los del backend (si no, deriva silenciosa) ---
    d = _defaults(*CLAVES_GUARDAS)
    check(d.get("permitir_fallback_nube") is False,
          "config.py debería traer permitir_fallback_nube en False (la nube no es reserva por defecto)")
    check(d.get("permitir_delegacion_nube") is True,
          "config.py debería traer permitir_delegacion_nube en True (esa nube la eligió el dueño)")
    fabrica = res["permisosFabrica"]
    for clave, cid in (("permitir_fallback_nube", "m-nubefb"),
                       ("permitir_delegacion_nube", "m-nubedel"),
                       ("perm_hardware", "m-hw")):
        if clave not in d:
            continue
        esperado = d[clave] is True
        check(_marcado(fabrica, cid) is esperado,
              f"«{cid}» sale {'marcado' if _marcado(fabrica, cid) else 'sin marcar'} "
              f"con la config vacía, y config.py dice {clave}={d[clave]!r}: el panel "
              "y el backend no pueden discrepar")
    check(_opcion(fabrica, "m-permfiles") == d.get("perm_files"),
          f"el desplegable de archivos arranca en «{_opcion(fabrica, 'm-permfiles')}» "
          f"y config.py dice {d.get('perm_files')!r}")
    check(_marcado(fabrica, "m-nubefb") is False,
          "los dos consentimientos nuevos tienen que estar en el panel")
    # El porqué del defecto encendido, escrito: lo eligió el dueño y la frontera
    # real es el «sí» de cada encargo.
    check("elegiste" in fabrica and "«sí»" in fabrica,
          "la casilla de delegación no explica POR QUÉ viene encendida")
    check("reserva" in fabrica,
          "la casilla de la reserva de nube no dice qué hace")

    # --- el aviso de «todo» aparece SOLO en «todo» ---
    check(res["avisoTodo"].strip() != "", "en modo «todo» no sale ningún aviso")
    check("denegad" in res["avisoTodo"].lower() and "secrets.json" in res["avisoTodo"],
          "el aviso de «todo» tiene que nombrar la lista de credenciales prohibidas")
    check("n8n" in res["avisoTodo"] and "Telegram" in res["avisoTodo"],
          "y decir que cualquier canal que llegue al asistente puede leer documentos")
    check(res["avisoCarpetas"].strip() == "" and res["avisoSandbox"].strip() == "",
          "el aviso de «todo» sale también en otro modo: no avisa de nada")
    check(res["avisoTodo"] in res["permisosTodo"],
          "con perm_files=todo el aviso no está DENTRO del panel")
    check(res["avisoTodo"] not in res["permisosCarpetas"],
          "con perm_files=carpetas el aviso de «todo» sigue pintado")
    check('id="m-permfiles-aviso"' in res["permisosCarpetas"],
          "falta el hueco del aviso: sin él no se puede actualizar al cambiar el desplegable")

    # PRESERVE: `perm_hardware`, `perm_files` y `perm_folders` funcionan como hoy
    antes = res["permisosComoSiempre"]
    for cid in ("m-hw", "m-permfiles", "m-permfolders"):
        check(f'id="{cid}"' in antes, f"ha desaparecido el control de siempre «{cid}»")
    check(_marcado(antes, "m-hw") is False,
          "perm_hardware marcado en la configuración y el panel lo pinta sin marcar")
    check(_opcion(antes, "m-permfiles") == "carpetas",
          f"el desplegable pierde la opción guardada ({_opcion(antes, 'm-permfiles')!r})")
    check("MisDocs" in antes,
          "el textarea de carpetas ya no lleva las carpetas guardadas")

    # --- Telegram: un clic, una petición; y el código se enseña ---
    check(res["tgPedidas"] == 1,
          f"un clic pidió el código {res['tgPedidas']} veces (tiene que ser 1)")
    check(res["tgOk"] is True, "con código, vincularTelegram debería decir que fue bien")
    check("ABCD2345" in res["tgPintado"], f"el código no se enseña: {res['tgPintado']}")
    check("/start" in res["tgPintado"],
          "el texto no dice la forma REAL que acepta el puente («/start <código>» o el código a secas)")
    check("10 min" in res["tgPintado"],
          f"el TTL de la respuesta no se lee: {res['tgPintado']}")
    check("anterior" in res["tgPintado"].lower(),
          "falta que el código anterior deja de valer (el endpoint lo regenera)")
    check(res["tgMarcado"] is False, "el aviso bueno no puede pintarse como error")
    check(res["tgPedidasError"] == 1,
          f"un clic con error pidió el código {res['tgPedidasError']} veces")
    check(res["tgOkError"] is False and res["tgErrorMarcado"] is True,
          "si el endpoint no da código hay que decirlo y marcarlo como error")
    check("ABCD2345" not in res["tgPintadoError"],
          "sin código no puede quedar un código pintado")

    # --- presupuesto y claves ilegibles: ni un secreto en el HTML ---
    presu = res["presupuesto"]
    check("37" in presu and "400" in presu,
          f"el presupuesto no enseña llamadas de hoy y su techo: {presu}")
    check("120.456" in presu or "120456" in presu,
          f"el presupuesto no enseña los caracteres de hoy: {presu}")
    check("openai" in presu, "el presupuesto no dice de qué proveedor con tokens reales")
    check(">3<" in presu, f"el presupuesto no enseña los encargos delegados: {presu}")
    check("techo" in res["presupuestoAgotado"].lower(),
          "con el techo agotado no se avisa en el panel")
    check(res["presupuestoNada"] == "", "sin datos de presupuesto no puede inventarse una línea")
    check("openai_api_key" in res["secretos"],
          f"la advertencia no nombra la clave que no se puede abrir: {res['secretos']}")
    for malo in (SECRETO, "dpapi:"):
        check(malo not in res["secretos"],
              f"la advertencia de claves ilegibles lleva «{malo}»: el HUD no recibe valores")
        check(malo not in res["presupuestoHostil"],
              f"el presupuesto lleva «{malo}» dentro: el HUD no recibe valores")
    check(res["secretosVacio"] == "" and res["secretosNoLista"] == "",
          "sin claves ilegibles no puede haber advertencia")
    check("sk-" not in res["secretos"].replace(SECRETO, ""),
          "queda un prefijo de clave en la advertencia")

# ═══════════════════════════════════════════════════════════════════════════════
# 6) VINCULACIÓN: revocar UN móvil desde el HUD (roadmap P3-2)
# ═══════════════════════════════════════════════════════════════════════════════
# Por qué aquí y no en una e2e: lo que hay que garantizar es que el botón exista
# POR DISPOSITIVO en el panel del QR —antes solo había «Desvincular», que mata a
# TODOS— y que el texto no mienta cuando el móvil es «antiguo» (usa el token
# compartido: revocarlo cierra esa credencial para todos los viejos). Y que nadie
# cablee la revocación del móvil en `views/devices.js`, que es la rejilla de
# televisiones y luces: son dos «dispositivos» distintos y confundirlos es la
# clase de error que esta tarea no puede permitirse.
print("== 6) el HUD puede revocar UN móvil, y lo cuenta sin mentir ==")

LINK_JS = (JS / "modals" / "link.js").read_text(encoding="utf-8")
DISPOSITIVOS_JS = (JS / "views" / "devices.js").read_text(encoding="utf-8")

check("/api/link/revoke" in LINK_JS,
      "link.js no llama a /api/link/revoke: no hay forma de revocar un solo móvil")
check("data-revoke=" in LINK_JS,
      "falta el botón por dispositivo en la lista de vinculados (data-revoke)")
check("lista.map(fila)" in LINK_JS,
      "el botón de revocar no se pinta POR DISPOSITIVO: tiene que salir de la lista")
check("st.vinculados" in LINK_JS and "_vinculados" in LINK_JS,
      "el HUD no lee `vinculados`: sin eso no ve los móviles apagados ni los antiguos")
check(".antiguo" in LINK_JS and "token COMPARTIDO" in LINK_JS,
      "el texto no distingue el «dispositivo antiguo» ni avisa de que su token es "
      "el compartido (revocarlo cierra la credencial de todos los viejos)")
_tras_revocar = LINK_JS.split("async function revocarDispositivo", 1)
check(len(_tras_revocar) == 2 and "refreshDevices()" in _tras_revocar[1][:1600],
      "revocar no refresca la lista: el móvil seguiría apareciendo como vinculado")
check("/api/link/reset" in LINK_JS,
      "«Desvincular TODO» tiene que seguir existiendo y ser otra acción distinta")
check("/api/link/revoke" not in DISPOSITIVOS_JS and "/api/link/status" not in DISPOSITIVOS_JS,
      "views/devices.js es la rejilla de TVs y luces: la revocación de móviles vive "
      "en modals/link.js, no ahí")

print(f"\n{'#' * 54}\ntest_frontend_modulos: {_pass} OK, {len(_fail)} fallos")
for aviso in _saltos:
    print("  ⚠", aviso)
for m in _fail:
    print("  -", m)
sys.exit(1 if _fail else 0)
