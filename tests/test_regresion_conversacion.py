# -*- coding: utf-8 -*-
"""Las frases que fallaron usando nexus, todas juntas y para siempre.

POR QUÉ ESTE FICHERO EXISTE (03/08/2026). En una tarde de uso real salieron once
fallos. La suite estaba entera en verde mientras tanto. Ninguno era exótico: eran
las frases con las que se habla todos los días.

Y hubo uno que enseña más que los demás. `test_lo_prometido` comprueba que cada
frase que promete un SKILL.md llega a su skill, y decía que sí. Era verdad… del
ROUTER. Pero entre que llega un mensaje y se consulta el router hay varios
atajos —charla, queja, memoria— y uno se quedaba todo lo que empezaba por
«apunta». El router ni se ejecutaba.

    Una prueba que mira un escalón por debajo de donde está el fallo
    lo declara arreglado.

Así que esta no pregunta al router: pregunta a `brain.quien_atiende()`, que es la
decisión de verdad, con los atajos por delante y en su orden.

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_regresion_conversacion.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.core.aplicacion import brain  # noqa: E402
from backend.core.aplicacion.skills_loader import load_skills               # noqa: E402

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


def atiende(frase: str) -> str:
    return brain.quien_atiende(frase)


# ═══════════ 1) LAS FRASES DE AQUELLA TARDE ═══════════
# Cada línea es algo que Adrián escribió o dictó, con quién TIENE que quedárselo.
# Se comprueba la decisión del cerebro entero, no la del router.
print("== 1) las frases que fallaron aquel día llegan a su sitio ==")

REALES = [
    # — la tele: actuaba sobre la que no era, o preguntaba dos veces —
    ("apaga la tele",                              "skill:domotica/tv_off"),
    ("enciende la tv de la habitación",            "skill:domotica/tv_on"),
    ("apaga la tv del salón",                      "skill:domotica/tv_off"),
    ("te he dicho que apagues la tele del salón",  "skill:domotica/tv_off"),

    # — el volumen: adivinaba destino, y «quitar el silencio» silenciaba —
    ("sube el volumen",                            "skill:system_pc/volume_ask"),
    ("sube el volumen del pc",                     "skill:system_pc/volume"),
    ("sube el volumen de spotify",                 "skill:system_pc/volume_app"),
    ("sube el volumen de la tele",                 "skill:domotica/tv_volume"),
    ("quítale el silencio",                        "skill:system_pc/volume_ask"),
    ("quítale el silencio al pc",                  "skill:system_pc/volume"),
    ("silencia",                                   "skill:system_pc/volume_ask"),

    # — el calendario: no borraba por fecha, y «apunta» se lo comía la memoria —
    ("borra los eventos del día 5",                "skill:google_workspace/delete_event"),
    ("borra los del día 5",                        "skill:google_workspace/delete_event"),
    ("borra lo que haya el día 5 y día 9",         "skill:google_workspace/delete_event"),
    ("borra también la del día nueve",             "skill:google_workspace/delete_event"),
    ("te he dicho que borres los del día 5",       "skill:google_workspace/delete_event"),
    ("apunta la mentoría el jueves a las 18",      "skill:tasks_board/create"),
    ("apunta el evento Feria del libro del 5 al 9", "skill:google_workspace/create_event"),

    # — las órdenes que no llegaban a nadie —
    ("busca información sobre python",             "skill:ai_media/web_search"),
    ("crea una tarea",                             "skill:tasks_board/create"),

    # — y lo que NO debe cambiar de dueño —
    ("apunta que me gusta el café solo",           "memoria"),
    ("recuerda que el wifi de casa es lento",      "memoria"),
    ("no te he dicho que leas los correos",        "queja"),
    ("hola",                                       "charla"),
    ("gracias",                                    "charla"),
]

for frase, esperado in REALES:
    real = atiende(frase)
    check(real == esperado,
          f"«{frase}» la atiende {real}, y tiene que atenderla {esperado}")


# ═══════════ 2) LO QUE NO PUEDE ROBARSE ═══════════
print("== 2) los arreglos no le han quitado el trabajo a nadie ==")

INTOCABLES = [
    ("borra la tarea 3",              "skill:tasks_board/delete"),
    ("borra las tareas completadas",  "skill:tasks_board/clear"),
    ("borra el archivo tmp.txt",      "skill:files/trash"),
    ("dame ideas para el regalo de mi madre", None),      # NO memory_graph
    ("qué sabes de mí",               "skill:memory_graph/list_knowledge"),
    ("qué sabes de mí ahora",         "skill:memory_graph/list_knowledge"),
    # Escribiendo deprisa se pierde la tilde, y sin ella «de mi ahora» acababa
    # en `recall`, que contestaba con la base de datos entera sobre un tema
    # llamado «mi ahora». Un puñado de palabras nunca son sustantivo poseído.
    ("que sabes de mi ahora",         "skill:memory_graph/list_knowledge"),
    ("que sabes de mi exactamente",   "skill:memory_graph/list_knowledge"),
    ("que sabes de mi y de mi familia", "skill:memory_graph/list_knowledge"),
]
for frase, esperado in INTOCABLES:
    real = atiende(frase)
    if esperado is None:
        check(real != "skill:memory_graph/list_knowledge",
              f"«{frase}» vuelve a caer en memory_graph ({real})")
    else:
        check(real == esperado, f"«{frase}» la atiende {real}, esperaba {esperado}")


# ═══════════ 3) UNA PREGUNTA ABIERTA NO CONTAMINA LO SIGUIENTE ═══════════
print("== 3) una pregunta sin contestar caduca y no se pega a lo que venga ==")

# REGRESIÓN PROPIA (03/08/2026). Al hacer que «¿cuál? A o B» → «la de arriba»
# funcionara, la pregunta se quedaba viva y se pegaba a TODO lo que llegaba
# después: «hola» y «dame ideas para el regalo de mi madre» acabaron contestando
# «¿Cuál? A o B». Lo cazó un barrido contra nexus de verdad, no la suite.
from backend.core.comun import context as ctxt  # noqa: E402

CONTAMINABLES = ["hola", "gracias", "dame ideas para el regalo de mi madre",
                 "qué hora es", "cuántos correos tengo"]
for frase in CONTAMINABLES:
    ctxt.note_pregunta("apaga la tele", "pc")
    quien = atiende(frase)
    check(not quien.startswith("skill:domotica"),
          f"con una pregunta de la tele abierta, «{frase}» acaba en domotica ({quien})")
ctxt.olvida_pregunta("pc")

# Y el pegado sigue existiendo para lo que SÍ es una respuesta: corto, sin dueño
# propio y sin ser un saludo.
SRC_B = (ROOT / "backend" / "core" / "aplicacion" / "brain.py").read_text(encoding="utf-8")
i = SRC_B.find("pregunta_pendiente(channel)")
bloque = SRC_B[max(0, i - 400):i + 900]
check("olvida_pregunta" in bloque,
      "la pregunta no se descarta tras el mensaje siguiente: volverá a contaminar")
check("_SMALLTALK_RX" in bloque, "un saludo puede colarse como respuesta")
check(re.search(r"len\(text\.split\(\)\)\s*<=\s*[1-5]\b", bloque) is not None,
      "no se exige que la respuesta sea corta: una frase larga no es un «cuál»")


# ═══════════ 4) LOS ATAJOS DECLARADOS SON LOS QUE HAY ═══════════
print("== 3) si aparece un atajo nuevo antes del router, esta prueba se entera ==")

# `quien_atiende` refleja el orden de `process`. Si alguien mete otro atajo antes
# del router y no lo añade aquí, esta prueba vuelve a mirar un escalón por debajo
# del fallo — que es exactamente cómo se coló el de «apunta».
SRC = (ROOT / "backend" / "core" / "aplicacion" / "brain.py").read_text(encoding="utf-8")
cuerpo = SRC[SRC.find("def quien_atiende"):SRC.find("\ndef ", SRC.find("def quien_atiende") + 10)]
for guarda in ("_SMALLTALK_RX", "_NO_ACCION_RX", "es_memoria_explicita",
               "_META_QUEJA_RX", "route("):
    check(guarda in cuerpo, f"quien_atiende ya no consulta {guarda}")

# Y los atajos que `process` aplica ANTES de enrutar están todos nombrados aquí.
antes_del_router = SRC[:SRC.find("routed = None if _no_accion else route(text)")]
for guarda in ("_SMALLTALK_RX", "_NO_ACCION_RX", "es_memoria_explicita"):
    check(guarda in antes_del_router,
          f"{guarda} ya no se aplica antes del router: revisa quien_atiende")


print(f"\n{'#' * 54}\ntest_regresion_conversacion: {_pass} OK, {len(_fail)} fallos")
for m in _fail:
    print("  -", m)
sys.exit(1 if _fail else 0)
