# -*- coding: utf-8 -*-
"""«Apunta» no siempre significa «guarda esto en tu memoria».

INCIDENTE (03/08/2026). Probando el calendario salió que «apunta un evento el
jueves a las 10» contestaba «Apuntado y guardado en tu memoria». Tirando del hilo
resultó que le pasaba a TODAS las frases con «apunta»:

    apunta la mentoría el jueves a las 18        → memoria (debía ir al tablero)
    apunta el evento Feria del libro del 5 al 9  → memoria (debía ir a Calendar)
    apúntame la clase de inglés el martes a las 5 → memoria (debía ir al tablero)

CAUSA. `brain` tiene un atajo para guardar hechos —«recuerda que…», «apunta
que…»— que corre ANTES del router. Su «que» era OPCIONAL, así que se tragaba
cualquier frase que empezara por «apunta».

POR QUÉ NO LO VIO NADIE. `test_lo_prometido` comprueba que cada frase del
SKILL.md llega a su skill, y decía que sí… porque pregunta al ROUTER. Y el
router ni se ejecutaba: el atajo respondía antes. Una prueba que mira un
escalón por debajo de donde está el fallo lo declara arreglado.

LA REGLA. Las separa el CONECTOR. «apunta QUE me gusta el café» es un hecho;
«apunta la reunión del jueves» es una cita. Sin «que», «lo de» o «esto:», manda
la skill que sepa atenderlo; y si no hay ninguna, se guarda como siempre.

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_apunta_no_es_siempre_memoria.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.core.aplicacion import brain  # noqa: E402
from backend.core.aplicacion.skills_loader import load_skills, route       # noqa: E402

load_skills()

_pass = 0
_fail: list[str] = []


def check(cond, msg: str) -> bool:
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print(f"  FALLO: {msg}")
    return bool(cond)


# ============ 1) CON CONECTOR ES UN HECHO ==================================
print("== 1) «apunta QUE …» sigue siendo memoria ==")

for frase in ("apunta que me gusta el café solo",
              "recuerda que el wifi de casa es lento",
              "memoriza que la clave del router es la de siempre",
              "apunta lo de la boda",
              "no olvides que hay que pagar la comunidad"):
    check(brain.es_memoria_explicita(frase),
          f"deja de guardar un hecho explícito: «{frase}»")


# ============ 2) SIN CONECTOR MANDA LA SKILL ===============================
print("== 2) «apunta la reunión del jueves» es una cita, no un recuerdo ==")

CON_DUENO = [
    "apunta la mentoría el jueves a las 18",
    "apúntame la clase de inglés el martes a las 5",
    "apunta el evento Feria del libro del 5 al 9",
    "apunta la reunión con el gestor el jueves a las 10",
]
for frase in CON_DUENO:
    check(route(frase) is not None, f"«{frase}» ya no llega a ninguna skill")
    check(not brain.es_memoria_explicita(frase),
          f"la memoria se queda una orden que tiene dueño: «{frase}»")


# ============ 3) SIN CONECTOR Y SIN DUEÑO, SE GUARDA ========================
print("== 3) si no hay skill que lo atienda, se guarda como siempre ==")

# El arreglo no puede dejar frases huérfanas: lo que antes se guardaba y no
# tiene otro sitio, se sigue guardando. (Todo lo que empieza por «apunta» sin
# conector se lo queda la skill de notas, que es su sitio; el respaldo se ve con
# los otros verbos.)
HUERFANAS = ("ten en cuenta el ruido del vecino por las noches",
             "memoriza mi talla de camisa la 42",
             "guárdame el código del portal 4581",
             "no olvides mi alergia al polen")
for frase in HUERFANAS:
    check(route(frase) is None,
          f"«{frase}» ya tiene dueño; hace falta otro ejemplo sin él")
    check(brain.es_memoria_explicita(frase),
          f"se pierde una frase que antes se guardaba: «{frase}»")


# ============ 4) EL CONECTOR ESTÁ EN EL PATRÓN =============================
print("== 4) el patrón captura el conector, que es lo que decide ==")

m = brain._REMEMBER_RX.match("apunta que me gusta el café")
check(m is not None and m.group("con"), "el patrón no captura el conector «que»")
m2 = brain._REMEMBER_RX.match("apunta la reunión del jueves")
check(m2 is not None and not m2.group("con"),
      "el patrón ve un conector donde no lo hay")


print(f"\n{'#' * 54}\ntest_apunta_no_es_siempre_memoria: {_pass} OK, {len(_fail)} fallos")
for m in _fail:
    print("  -", m)
sys.exit(1 if _fail else 0)
