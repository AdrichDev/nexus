# -*- coding: utf-8 -*-
"""Todo lo que un SKILL.md promete en su lista de activacion, llega.

`SKILL.md` es lo que lee el agente para decidir. Si ahi pone que «pon el brillo
al 80» funciona y ninguna regex lo caza, la frase acaba en el planificador del
cerebro — que es donde se inventa cosas. La regla del proyecto es clara: cada
vez que una frase normal acaba en el planificador, es un bug.

Esta suite recorre los 32 SKILL.md, saca las ordenes de sus listas de
activacion (las viñetas que empiezan por «) y comprueba que TODAS caen en
alguna skill.

EL EXTRACTOR YA NO VIVE AQUI (004, bloque B). Bajo a produccion como
`reglas.corpus_prometido()`, porque la puerta de «no robo» del aprendizaje mide
contra ese mismo corpus y se ejecuta en la maquina del usuario, donde no hay
`tests/`. Un extractor aqui y otro alli podrian discrepar sin que nadie se
enterase; con uno solo, el corpus que valida las reglas sale de los mismos bytes
que se distribuyen.

Asi aparecio el brillo: `media/SKILL.md` llevaba tiempo diciendo «pon el brillo
al 80 → Sistema/PC» y Sistema/PC no tenia nada de brillo.

No comprueba a QUE skill van: una orden puede estar documentada en dos sitios a
proposito (las fronteras se explican en los dos lados). Comprueba que llegan.

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_lo_prometido.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("NEXUS_DATA_DIR", tempfile.mkdtemp(prefix="nexus_prometido_"))

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


print("== lo que los SKILL.md prometen, llega a una skill ==")

from backend.core.aplicacion import skills_loader as sl  # noqa: E402
from backend.core.dominio import reglas                  # noqa: E402


def ordenes_prometidas() -> list[tuple[str, str]]:
    """[(skill, orden)] sacadas de las listas de activacion de cada SKILL.md.

    Un envoltorio del extractor de produccion, no una copia: si el de produccion
    dejara de ver una vinneta, esta suite lo diria en la misma pasada."""
    return reglas.corpus_prometido(con_origen=True)


sl.load_skills()
PROMETIDAS = ordenes_prometidas()

check(len(PROMETIDAS) > 200,
      f"solo se han encontrado {len(PROMETIDAS)} ordenes en los SKILL.md: "
      "¿ha cambiado el formato de las listas de activacion?")

vistas = set()
for skill, orden in PROMETIDAS:
    if orden in vistas:
        continue
    vistas.add(orden)
    r = sl.route(orden)
    check(r is not None,
          f"{skill}/SKILL.md promete «{orden}» y no la caza ninguna regex: "
          "acaba en el planificador, que es donde se inventa cosas")

print(f"\n{'#' * 54}\ntest_lo_prometido: {_pass} OK, {len(_fail)} fallos "
      f"({len(vistas)} ordenes distintas)")
for m in _fail:
    print("  -", m)
sys.exit(1 if _fail else 0)
