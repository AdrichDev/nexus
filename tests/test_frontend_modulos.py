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

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_frontend_modulos.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "frontend" / "js"

# Scripts clasicos: dejan su API en window y NO son modulos. Se quedan fuera.
CLASICOS = {"qrcode.min.js", "reactor.js", "charts.js"}

_fail: list[str] = []
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
    """El cuerpo del fichero sin las lineas de import (para no contarlas como uso)."""
    return re.sub(r"import\s*\{[^}]*\}\s*from\s*['\"][^'\"]+['\"]\s*;?", "", txt)


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

print(f"\n{'#' * 54}\ntest_frontend_modulos: {_pass} OK, {len(_fail)} fallos")
for m in _fail:
    print("  -", m)
sys.exit(1 if _fail else 0)
