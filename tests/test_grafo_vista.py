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
# La rueda a secas TAMBIÉN hace zoom, que es lo que hace Obsidian. Se podía
# exigir Ctrl mientras la pantalla scrolleaba; ahora el panel ocupa el alto y no
# scrollea, así que la rueda no le hace falta a la página.
check("e.preventDefault()" in JS and "'wheel'" in JS,
      "la rueda no hace zoom sobre el grafo")
check("Ctrl + rueda" in SPA,
      "la ayuda ya no menciona Ctrl + rueda, que es lo que se pidió y sigue valiendo")
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

MEM = (ROOT / "backend" / "core" / "dominio" / "memory.py").read_text(encoding="utf-8")
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

print("== 5) UNA sola pantalla de nodos, y sin skills ==")

# Había DOS grafos: «Nodos de conocimiento» (nexus + las 32 skills + notas) y
# «Memoria» (solo notas), cada uno con su motor. Adrián: las skills no aportan
# nada ahí porque ya tienen su sección «Habilidades». Se queda una pantalla.
HTML = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
check('data-view="knowledge"' not in HTML,
      "sigue habiendo dos entradas de nodos en el menú")
check("views.knowledge" not in SPA, "la vista duplicada sigue definida")
check("Nodos de conocimiento</span></a>" in HTML,
      "la entrada del menú no se llama «Nodos de conocimiento»")
check("CATALOG[k].label" not in JS,
      "el grafo sigue pintando las 32 skills: eso es la sección Habilidades")
check("mem-graph" not in SPA,
      "queda el canvas viejo de Memoria; el motor tiene que ser uno solo")
check("await mountKnowledge()" in SPA,
      "la pantalla no usa el motor de nodos (arrastrables, con ventanitas)")

print("== 6) el sistema en el centro y todo colgando de él ==")

check("label: sysName()" in JS,
      "el nodo central no lleva el nombre del sistema")
check("function sysName" in JS and "assistant_name" in JS,
      "el nombre está escrito a fuego: quien instale esto puede llamarlo de otra manera")
check("edges.push([core, n])" in JS,
      "las carpetas no cuelgan del núcleo")
check("porCarpeta['']" in JS or 'porCarpeta[""]' in JS,
      "las notas sueltas no se enganchan a nada y quedan flotando")

print("== 7) el árbol se pliega y se despliega ==")

check("knPlegadas" in JS, "no hay estado de plegado")
check("kn-tw" in JS and "data-fold" in JS,
      "no hay triángulo de plegar, o no es zona propia (pulsarlo abriría la nota)")
check("e.stopPropagation()" in JS,
      "el clic del triángulo se propaga y abre la nota además de plegar")
check(re.search(r"\.kn-folder\.plegada[^{]*\{[^}]*display:none", CSS) is not None,
      "plegar una carpeta no oculta sus archivos")
check("kn-raiz" in JS and ".kn-raiz" in CSS,
      "no hay nodo raíz en el árbol: tiene que salir el sistema y de él las carpetas")

print("== 8) el grafo se mueve como el de Obsidian ==")

# Adrián: «lo siento muy estático, quiero un funcionamiento literalmente
# idéntico al de Obsidian». Lo era: los nodos se colocaban en anillos calculados
# y ahí se quedaban; al arrastrar uno, los demás ni se enteraban. Obsidian usa
# una simulación de fuerzas continua (el modelo de d3-force) y expone CUATRO
# palancas, con estos rangos exactos.
check("function knPaso" in JS, "no hay simulación: el grafo sigue siendo un dibujo fijo")
check("alphaDecay" in JS and "alphaTarget" in JS,
      "sin alpha no hay enfriamiento: o tiembla para siempre o no se mueve nunca")
check("friccion" in JS, "sin rozamiento los nodos oscilan y no se asientan")
for f, rango in (("centro", (0, 1)), ("repulsion", (0, 20)),
                 ("enlace", (0, 1)), ("distancia", (30, 500))):
    check(f in JS, f"falta la fuerza «{f}», que Obsidian sí ajusta")
    check(f'data-f="{f}"' in SPA, f"la fuerza «{f}» no tiene control en la interfaz")
check('min="0" max="20"' in SPA and 'min="30" max="500"' in SPA,
      "los rangos de los controles no son los de Obsidian (repulsión 0-20, distancia 30-500)")
check("FUERZAS_DEF = { centro: 0.5, repulsion: 10, enlace: 1, distancia: 250 }" in JS,
      "los valores por defecto no son los de Obsidian (0.5 / 10 / 1 / 250)")

# El gesto de arrastrar es lo que distingue un grafo vivo de un dibujo:
# se CLAVA el nodo al cursor (fx/fy), se RECALIENTA la simulación, y al soltar
# se DESCLAVA para que el grafo se recoloque solo.
check("n.fx = n.x; n.fy = n.y" in JS, "agarrar un nodo no lo clava al cursor")
check("knAgita" in JS, "arrastrar no recalienta la simulación: los vecinos no reaccionarían")
check("knDrag.fx = null" in JS,
      "al soltar el nodo se queda clavado; en Obsidian vuelve a la física")
check("if (n.fx != null)" in JS,
      "la simulación no respeta los nodos agarrados y pelearía con el cursor")

# Y el resaltado al pasar el ratón, que es de lo primero que se nota.
check("mouseenter" in JS and "vecino" in JS,
      "pasar el ratón no enciende los vecinos ni apaga el resto")

print("== 9) el grafo real trae carpetas y enlaces de hermanas ==")

from backend.core.dominio import memory as M  # noqa: E402

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
