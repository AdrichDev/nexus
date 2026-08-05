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

import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# AISLAMIENTO. `brain` lee las frases aprendidas de `data/`, asi que sin esto la
# prueba mira los datos REALES de la maquina: pasa o falla segun lo que tenga
# guardado quien la ejecute, y en otra maquina dice otra cosa. Igual que hace
# `test_lo_prometido`, que si lo aislaba.
os.environ.setdefault("NEXUS_DATA_DIR", tempfile.mkdtemp(prefix="nexus_regresion_"))

from backend.core.aplicacion import brain  # noqa: E402
from backend.core.aplicacion.skills_loader import load_skills               # noqa: E402
from backend.core.dominio import reglas                                     # noqa: E402

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


# ═══════════ 1 y 2) LAS FRASES DE AQUELLA TARDE ═══════════
# Cada línea es algo que el dueño escribió o dictó, con quién TIENE que
# quedárselo. Se comprueba la decisión del cerebro entero, no la del router.
#
# LA LISTA YA NO VIVE AQUÍ (004, bloque B). Está en
# `config/corpus_regresion.json`, que sí viaja en el instalador: la puerta de
# «no robo» del aprendizaje mide contra estas frases y se ejecuta en la máquina
# del usuario, donde no hay `tests/`. Con la lista dentro de la suite, esa
# puerta validaría contra menos frases de las que cree.
print("== 1 y 2) las frases que fallaron aquel día llegan a su sitio ==")

CORPUS = reglas.corpus_regresion()
check(len(CORPUS) >= 30,
      f"config/corpus_regresion.json trae solo {len(CORPUS)} frases: "
      "¿se ha quedado sin instalar o ha cambiado el formato?")
check({e.get("bloque") for e in CORPUS} == {1, 2},
      "el corpus de regresión ha perdido uno de los dos bloques")

for entrada in CORPUS:
    frase = entrada["frase"]
    esperado = entrada.get("dueno")
    real = atiende(frase)
    if esperado is None:
        # Un solo caso: «dame ideas…» no tiene dueño fijo, pero NO puede volver
        # a caer en memory_graph.
        prohibido = entrada.get("no_dueno")
        check(real != prohibido, f"«{frase}» vuelve a caer en {prohibido} ({real})")
    else:
        check(real == esperado,
              f"«{frase}» la atiende {real}, y tiene que atenderla {esperado}")


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


# ═══════════ 3 bis) LA CHARLA AGUANTA LAS VARIANTES, Y NO SE PASA ═══════════
# 05/08/2026, medido. «qué tal» y «cómo estás» eran charla; «qué tal estás»,
# «cómo te va», «qué tal todo» y «hola qué tal» acababan en el planificador. La
# causa: `_SMALLTALK_RX` terminaba en `\b[\s!¡.,?¿]*$`, o sea que exigía que la
# frase ENTERA fuese UNA SOLA pieza de charla. A «qué tal estás» le sobraba el
# «estás» y «hola qué tal» son dos piezas.
#
# LAS DOS LISTAS VAN JUNTAS A PROPÓSITO. Este atajo corre ANTES del router: cada
# frase que se queda aquí es una orden que NO se ejecuta. Ensancharlo sin vigilar
# el otro lado convierte un fallo molesto (una charla que no se entiende) en uno
# grave (una orden que se traga un «vale»).
print("== 3 bis) la charla admite variantes y frases encadenadas, sin comerse órdenes ==")

ES_CHARLA = ("qué tal", "cómo estás", "qué tal estás", "cómo te va", "qué tal todo",
             "hola qué tal", "hola, ¿qué tal estás?", "buenas, qué tal",
             "hola", "gracias", "vale", "buenos días", "qué tal andas",
             "cómo lo llevas", "hola buenas")
for frase in ES_CHARLA:
    real = atiende(frase)
    check(real == "charla", f"«{frase}» es charla y la atiende {real}")

# Y ESTAS NO. Cada una lleva delante o dentro una palabra de charla («no», «vale»,
# «sí», «hola», «qué tal», «cómo va») y detrás una ORDEN de verdad.
NO_ES_CHARLA = ("no borres nada", "vale, apaga la tele", "sí, crea la tarea",
                "hola, ábreme chrome", "qué tal va el tablero",
                "cómo va mi instagram", "hola, cuántos correos tengo",
                "gracias, ahora apaga las luces")
for frase in NO_ES_CHARLA:
    real = atiende(frase)
    check(real != "charla",
          f"«{frase}» lleva una orden dentro y el atajo de charla se la ha tragado")


# ═══════════ 4) LOS ATAJOS DECLARADOS SON LOS QUE HAY ═══════════
print("== 3) si aparece un atajo nuevo antes del router, esta prueba se entera ==")

# `quien_atiende` refleja el orden de `process`. Si alguien mete otro atajo antes
# del router y no lo añade aquí, esta prueba vuelve a mirar un escalón por debajo
# del fallo — que es exactamente cómo se coló el de «apunta».
SRC = (ROOT / "backend" / "core" / "aplicacion" / "brain.py").read_text(encoding="utf-8")
cuerpo = SRC[SRC.find("def quien_atiende"):SRC.find("\ndef ", SRC.find("def quien_atiende") + 10)]
for guarda in ("_SMALLTALK_RX", "_NO_ACCION_RX", "es_memoria_explicita",
               "_META_QUEJA_RX", "route(", "_regla_que_casa"):
    check(guarda in cuerpo, f"quien_atiende ya no consulta {guarda}")

# Y el escalón de las reglas aprendidas (004) va DESPUÉS del router y de la
# meta-queja. No es un detalle de estilo: ahí está la garantía de que una regla
# aprendida no puede quitarle una frase a una skill. Si alguien lo sube por
# encima del `route(t)`, el robo pasa de imposible a posible y solo esta línea
# se entera.
check(cuerpo.find("r = route(t)") < cuerpo.find("_regla_que_casa"),
      "las reglas aprendidas se consultan ANTES del router: pueden robar")
check(cuerpo.find("_META_QUEJA_RX") < cuerpo.find("_regla_que_casa"),
      "las reglas aprendidas se consultan antes de la meta-queja")

# Y los atajos que `process` aplica ANTES de enrutar están todos nombrados aquí.
antes_del_router = SRC[:SRC.find("routed = None if _no_accion else route(text)")]
for guarda in ("_SMALLTALK_RX", "_NO_ACCION_RX", "es_memoria_explicita"):
    check(guarda in antes_del_router,
          f"{guarda} ya no se aplica antes del router: revisa quien_atiende")


print(f"\n{'#' * 54}\ntest_regresion_conversacion: {_pass} OK, {len(_fail)} fallos")
for m in _fail:
    print("  -", m)
sys.exit(1 if _fail else 0)
