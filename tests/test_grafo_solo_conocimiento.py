# -*- coding: utf-8 -*-
"""En el grafo de conocimiento solo hay conocimiento.

INCIDENTE (03/08/2026), y Adrián lo dijo varias veces antes de que yo mirara
donde tocaba: «me salen un montón de nodos que no tendrían que estar ahí, prueba
de ello que sigue estando un archivo que se llama CV AMOROSO ADRI».

Yo había borrado las filas de Postgres y daba el trabajo por hecho. El grafo NO
sale de Postgres: `NoteGraph.graph()` recorre `data/memory/` con `rglob()`. Y la
papelera vive DENTRO de esa carpeta, así que retirar una nota la movía a
`papelera/` y el grafo la seguía leyendo desde ahí. De 93 nodos pintados, 22 eran
conocimiento: 59 papelera y 12 diario.

Tres agujeros, y cada uno tapaba al siguiente:

  1. `graph()` no excluía NADA. `search()` excluía `daily/` y nada más, así que
     una nota retirada seguía contestando a «qué recuerdas de…».
  2. El diario NO vive en `daily/`: `profile.py` lo escribe en la RAÍZ como
     `diario-AAAA-MM-DD.md`. Excluir la carpeta nunca lo excluyó a él.
  3. Y aun excluyendo el fichero, el diario VOLVÍA como nodo virtual: cada
     `resumen AAAA-MM-DD` enlaza a su `[[diario-…]]`, y un enlace a algo que no
     existe crea un hub. Entraba por la puerta de atrás.

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_grafo_solo_conocimiento.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["NEXUS_DATA_DIR"] = tempfile.mkdtemp(prefix="nexus_grafo_")

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


from backend.core.dominio import memory as M  # noqa: E402

MEM = M.MEMORY_DIR
MEM.mkdir(parents=True, exist_ok=True)


def escribe(rel: str, texto: str) -> None:
    p = MEM / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(texto, encoding="utf-8")


print("== 1) lo retirado a la papelera desaparece del grafo y de las búsquedas ==")

escribe("doc Wabiks manual.md", "# Wabiks\nEl manual de contenido.\n")
escribe("papelera/lote-x/doc CV AMOROSO ADRI completo.md",
        "# doc CV AMOROSO ADRI completo\nCarpeta: 20. FP DAM Euroformac\nCurriculum.\n")
escribe("papelera/lote-x/doc BOOTCAMP CIBERSEGURIDAD.md",
        "# doc BOOTCAMP CIBERSEGURIDAD\nTemario del bootcamp.\n")

g = M.graph.graph()
for prohibido in ("doc CV AMOROSO ADRI completo", "doc BOOTCAMP CIBERSEGURIDAD"):
    check(prohibido not in g["nodes"],
          f"«{prohibido}» está en la PAPELERA y el grafo lo sigue pintando")
check("doc Wabiks manual" in g["nodes"],
      "se ha llevado por delante una nota que sí es conocimiento")

for q in ("amoroso", "bootcamp", "euroformac"):
    check(M.graph.search(q, limit=5) == [],
          f"«{q}» está retirado y la búsqueda lo sigue devolviendo")

print("== 2) el diario es log, viva donde viva ==")

escribe("diario-2026-07-30.md", "# diario-2026-07-30\n- **17:17** Adri dice algo.\n")
escribe("daily/2026-07-18.md", "# 2026-07-18\n- **18:44** Adri dice otra cosa.\n")
escribe("resumen 2026-07-30.md",
        "# resumen 2026-07-30\nLo importante del día.\n\nEnlaces: [[diario-2026-07-30]]\n")

g = M.graph.graph()
check("diario-2026-07-30" not in g["nodes"],
      "el diario sigue en el grafo: no vive en daily/, sino en la RAÍZ como "
      "«diario-AAAA-MM-DD.md», así que excluir la carpeta no basta")
check("2026-07-18" not in g["nodes"], "una nota de daily/ sigue en el grafo")
check("resumen 2026-07-30" in g["nodes"],
      "el resumen SÍ es conocimiento —es la destilación de lo que pasó— y ha "
      "desaparecido")

print("== 3) un enlace no puede resucitar lo excluido ==")

# El resumen enlaza a su diario. Un enlace a algo que no existe como nota crea un
# hub virtual, y por ahí volvía el diario aunque su fichero estuviera excluido.
check("diario-2026-07-30" not in g["nodes"],
      "el diario vuelve como NODO VIRTUAL a través del enlace del resumen")
check(all(not str(b).lower().startswith("diario-") for _a, b in g["edges"]),
      "quedan aristas apuntando al diario, y cada una puede recrear el nodo")

print("== 4) la regla está en un solo sitio y se puede leer ==")

check(hasattr(M, "_fuera_del_conocimiento"),
      "no existe _fuera_del_conocimiento: la regla vuelve a estar repartida")
check(hasattr(M, "_excluido_por_nombre"),
      "no existe _excluido_por_nombre, que es la que aplica también a los enlaces")
src = (ROOT / "backend" / "core" / "dominio" / "memory.py").read_text(encoding="utf-8")
check(src.count("_fuera_del_conocimiento(path)") >= 2,
      "la exclusión debe aplicarse en graph() Y en search(): si solo está en una, "
      "lo retirado desaparece de la vista pero sigue contestando (o al revés)")

print(f"\n{'#' * 54}\ntest_grafo_solo_conocimiento: {_pass} OK, {len(_fail)} fallos")
for m in _fail:
    print("  -", m)
sys.exit(1 if _fail else 0)
