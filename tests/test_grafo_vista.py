# -*- coding: utf-8 -*-
"""La vista de nodos: zoom, límites del arrastre y árbol de carpetas.

Sin navegador no se puede comprobar de verdad, así que esta suite lee el código
de la vista y del CSS y verifica las decisiones que arreglan cada fallo. La
comprobación viva la hace la e2e con Chromium.

Lo que cubre, y por qué existe cada cosa (03/08/2026, todo pedido por Adrián):

  * ZOOM con Ctrl + rueda. Antes no había ninguno.
  * EL ARRASTRE A LOS BORDES COMPRIMÍA Y APILABA EL GRAFO. Los nodos se
    posicionaban en coordenadas de pantalla y el arrastre las escribía sin
    límite: al llevar un nodo contra un borde se salía del contenedor, el
    contenedor crecía, `clientWidth` cambiaba, y al volver a montar todo se
    recolocaba sobre un tamaño distinto. Ahora hay un MUNDO de tamaño fijo, la
    ventana recorta (`overflow:hidden`) y el nodo se acota al mundo.
  * LAS NOTAS DE UNA MISMA CARPETA SE ENLAZAN SOLAS, con su carpeta y entre sí.
  * DISTRIBUCIÓN TIPO OBSIDIAN: árbol de carpetas a la izquierda, grafo a la
    derecha.

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_grafo_vista.py
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("NEXUS_DATA_DIR", tempfile.mkdtemp(prefix="nexus_grafovista_"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                          # noqa: BLE001
    pass

_fail: list[str] = []
_pass = 0


def check(cond, msg: str) -> bool:
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  ✖", msg)
    return bool(cond)


JS = (ROOT / "frontend" / "js" / "views" / "knowledge.js").read_text(encoding="utf-8")
SPA = (ROOT / "frontend" / "js" / "command.js").read_text(encoding="utf-8")
CSS = (ROOT / "frontend" / "css" / "command.css").read_text(encoding="utf-8")

print("== 1) Ctrl + rueda acerca y aleja ==")

check("addEventListener('wheel'" in JS, "la vista no escucha la rueda del ratón")
check("e.ctrlKey" in JS,
      "el zoom no exige Ctrl: la rueda a secas tiene que seguir moviendo la página")
check("passive: false" in JS,
      "sin passive:false el navegador ignora el preventDefault y la página hace zoom ella")
check("e.preventDefault()" in JS, "el zoom no evita el comportamiento por defecto")
check(re.search(r"ZOOM_MIN\s*=\s*[\d.]+\s*,\s*ZOOM_MAX\s*=\s*[\d.]+", JS) is not None,
      "el zoom no tiene tope: se puede alejar hasta perder el grafo o acercar hasta un píxel")
check("knZoom" in JS and "z / antes" in JS,
      "el zoom no mantiene quieto el punto bajo el cursor, que es lo que lo hace usable")
check("kn-zoom" in SPA and "data-z=\"fit\"" in SPA,
      "faltan los botones de zoom y el de ajustar a la pantalla")

print("== 2) arrastrar a un borde ya no descoloca el grafo ==")

check(re.search(r"WORLD\s*=\s*\{\s*w:\s*\d+", JS) is not None,
      "no hay un MUNDO de tamaño fijo: si el lienzo depende del contenedor, "
      "arrastrar contra un borde vuelve a recolocarlo todo")
check("Math.min(WORLD.w - m, Math.max(m," in JS,
      "el nodo arrastrado no se acota al mundo: puede irse fuera")
check("knDrag.sz / 2" in JS,
      "el límite no tiene en cuenta el radio del nodo y se corta por la mitad")
check(re.search(r"#kn-stage\{[^}]*overflow:hidden", CSS) is not None,
      "el escenario no recorta: un nodo fuera puede estirar el contenedor")
check("+ knView.x) / knView.z" in JS,
      "el arrastre no convierte de pantalla a mundo, así que con zoom el nodo "
      "salta a otro sitio")
check("knLimitaVista" in JS, "la cámara puede salirse del mundo y dejarte mirando al vacío")

print("== 3) lo de la misma carpeta va junto ==")

MEM = (ROOT / "backend" / "core" / "memory.py").read_text(encoding="utf-8")
check("_carpeta_de" in MEM, "el grafo no sabe de qué carpeta viene cada nota")
check("dominio:" in MEM and "Carpeta:" in MEM,
      "solo se reconoce un formato de procedencia; hay notas de las dos épocas")
check("_MALLA_MAX_CARPETA" in MEM,
      "la malla entre hermanas no tiene tope y crece al cuadrado: con 30 notas "
      "serían 435 líneas y no se vería nada")
check('"carpetas": carpetas' in MEM and '"raiz"' in MEM,
      "el grafo no publica las carpetas, así que el árbol no puede pintarse")

print("== 4) distribución tipo Obsidian ==")

check("kn-split" in SPA and "kn-tree" in SPA,
      "no hay panel de carpetas a la izquierda")
check(re.search(r"#kn-split\{[^}]*display:flex", CSS) is not None,
      "el panel y el grafo no están uno al lado del otro")
check("knPintaArbol" in JS, "el árbol no se rellena con nada")
check(".kn-file" in CSS and "--c" in CSS,
      "los archivos del árbol no llevan color, y era parte de lo pedido")
check("mouseenter" in JS and "knCentraEn" in JS,
      "el árbol no está conectado al grafo: pasar el ratón debería resaltar y "
      "pulsar debería centrar")

print("== 5) MEMORIA: es el grafo que se mira de verdad ==")

# El primer intento se hizo sobre «Nodos de conocimiento», que es otra pantalla.
# El grafo que Adrián usa está en MEMORIA (#mem-graph), y es el que tenía el
# fallo de apilarse contra los bordes.
check("mem-split" in SPA and "mem-tree" in SPA,
      "Memoria no tiene el árbol de carpetas a la izquierda")
check("mem-zoom" in SPA and "mem-zlabel" in SPA, "Memoria no tiene control de zoom")
check("pintaArbolMemoria" in SPA, "el árbol de Memoria no se rellena")
check("if (!ev.ctrlKey) return;" in SPA,
      "el zoom de Memoria no exige Ctrl, o directamente no existe")
check(re.search(r"const MW = \d+, MH = \d+", SPA) is not None,
      "el grafo de Memoria no tiene MUNDO propio: sin él, arrastrar contra un "
      "borde vuelve a apilar los nodos")
check("Math.min(MW - 24, n.x + dx)" in SPA,
      "el arrastre de Memoria sigue recortando contra la VENTANA en vez de "
      "contra el mundo, que es justo lo que apilaba")
check("(ev.clientX - r.left) / z + ox" in SPA,
      "Memoria no convierte de pantalla a mundo: con zoom, el nodo salta")
check(re.search(r"#mem-graph-wrap\{[^}]*overflow:hidden", CSS) is not None,
      "el grafo de Memoria no recorta y puede estirar el panel")
check("g.carpetas" in SPA and "g.raiz" in SPA,
      "Memoria no usa las carpetas del backend, así que no agrupa por carpeta madre")

print("== 6) el grafo real trae carpetas y enlaces de hermanas ==")

from backend.core import memory as M                       # noqa: E402

MEMDIR = M.MEMORY_DIR
(MEMDIR / "documentos" / "proyecto-x").mkdir(parents=True, exist_ok=True)
for i in (1, 2, 3):
    (MEMDIR / "documentos" / "proyecto-x" / f"nota{i}.md").write_text(
        f"---\ndominio: proyecto-x\n---\n# nota{i}\ntexto\n", encoding="utf-8")

g = M.graph.graph()
check("proyecto-x" in g.get("raiz", []), "la carpeta no aparece como raíz")
for i in (1, 2, 3):
    check(g["carpetas"].get(f"nota{i}") == "proyecto-x",
          f"nota{i} no queda asignada a su carpeta")
aristas = {tuple(sorted(e)) for e in g["edges"]}
for a, b in (("nota1", "nota2"), ("nota1", "nota3"), ("nota2", "nota3")):
    check(tuple(sorted((a, b))) in aristas,
          f"«{a}» y «{b}» son de la misma carpeta y no están enlazadas")
for i in (1, 2, 3):
    check(tuple(sorted((f"nota{i}", "proyecto-x"))) in aristas,
          f"nota{i} no cuelga de su carpeta madre")

print(f"\n{'#' * 54}\ntest_grafo_vista: {_pass} OK, {len(_fail)} fallos")
for m in _fail:
    print("  -", m)
sys.exit(1 if _fail else 0)
