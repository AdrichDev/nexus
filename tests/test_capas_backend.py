# -*- coding: utf-8 -*-
"""Las dependencias de backend/core/ van hacia abajo, nunca hacia arriba.

`core/` son 43 modulos y 15.000 lineas en una carpeta plana. Sin esto, nada
impide que el modulo que habla con la API de Google llame a las reglas del
tablero. El orden esta escrito en backend/core/CAPAS.md; aqui se comprueba.

    aplicacion  →  dominio  →  infraestructura  →  comun

Una capa puede importar de la suya y de las de abajo. De las de arriba no.

Lo que NO hace esta suite: mover ficheros. Las capas son una regla, no una
estructura de carpetas — mover 43 modulos obliga a reescribir los imports de
85 ficheros, y eso se hace por grupos, no de una tirada. Mientras tanto la
regla ya se cumple y se verifica.

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_capas_backend.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "backend" / "core"

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


# De abajo arriba. El indice ES el nivel: 0 no puede depender de 1, 2 ni 3.
CAPAS: list[tuple[str, set[str]]] = [
    ("comun", {
        "config", "events", "audit", "permissions", "confirm", "procedencia",
        "context", "net", "publicvoice",
    }),
    ("infraestructura", {
        "llm", "llm_runtime", "tts", "stt", "remote", "files_io",
        "engram_bridge", "websearch", "telegram_bridge", "spotify", "hardware",
        "app_index",
    }),
    ("dominio", {
        "board", "purga", "contentos", "contentos_demo", "rag", "memory",
        "selflearn", "opmem", "briefing", "profile", "review", "ingesta", "pm",
        "reglas",
    }),
    ("aplicacion", {
        "brain", "skills_loader", "scheduler", "background", "jobs",
        "wake", "hotkey", "voice_cycle", "aprendizaje",
    }),
]

NIVEL = {m: i for i, (_n, ms) in enumerate(CAPAS) for m in ms}
NOMBRE = {i: n for i, (n, _ms) in enumerate(CAPAS)}

# Deuda aceptada: dependencias que hoy van del reves. Cada una esta explicada en
# backend/core/CAPAS.md. Añadir una nueva obliga a tocar este fichero a mano, que
# es justo la friccion que se busca: que se vea.
EXCEPCIONES: set[tuple[str, str]] = {
    ("llm", "llm_runtime"),         # ciclo: el runtime elige modelo, llm pregunta cual
    ("llm", "selflearn"),           # ciclo: selflearn pide al modelo, llm lee lo aprendido
    ("rag", "memory"),              # ciclo: la memoria busca por vectores, el rag escribe
    ("telegram_bridge", "brain"),   # ciclo: el puente entrega al cerebro y este contesta
}


def ruta(modulo: str) -> Path:
    """Donde vive un modulo de core, este suelto o dentro de su capa.

    Fase 3 los va bajando a `backend/core/<capa>/` de grupo en grupo, asi que
    durante la mudanza conviven los dos sitios. Buscar en vez de dar por hecho
    permite mover una capa sin tocar esta prueba."""
    plano = CORE / f"{modulo}.py"
    if plano.exists():
        return plano
    for capa, _mods in CAPAS:
        p = CORE / capa / f"{modulo}.py"
        if p.exists():
            return p
    raise FileNotFoundError(f"no encuentro {modulo} en backend/core")


def capa_por_carpeta(modulo: str) -> str:
    """La capa que dice la CARPETA, o '' si el modulo sigue suelto en core/."""
    p = ruta(modulo)
    return p.parent.name if p.parent != CORE else ""


def modulos() -> list[str]:
    return sorted(f.stem for f in CORE.rglob("*.py") if f.stem != "__init__")


_NOMBRES_CAPA = "|".join(c for c, _m in CAPAS)


def importa(modulo: str) -> set[str]:
    """Modulos de core que importa este, en cualquiera de las formas que se usan.

    OJO A LAS FORMAS RELATIVAS. Al bajar un modulo a su carpeta, sus imports
    ganan un punto (`from ..memory`) y pueden llevar la capa por delante
    (`from ..comun.config`). Un patron que solo conozca `from .memory` deja de
    ver esos imports — y entonces esta prueba no falla: dice que todo esta
    limpio, que es mucho peor. Paso justo eso al mover `infraestructura`: tres
    excepciones aparecieron como «ya no hacen falta» cuando lo unico que habia
    cambiado era la profundidad del import."""
    txt = ruta(modulo).read_text(encoding="utf-8")
    txt = re.sub(r'"""(?:.|\n)*?"""', " ", txt)            # fuera los docstrings
    txt = re.sub(r"#[^\n]*", " ", txt)                     # y los comentarios
    fuera = set()
    for otro in modulos():
        if otro == modulo:
            continue
        if (re.search(rf"from backend\.core import [^\n]*\b{otro}\b", txt)
                or re.search(rf"from backend\.core(?:\.(?:{_NOMBRES_CAPA}))?\.{otro}\b", txt)
                or re.search(rf"from backend\.core\.(?:{_NOMBRES_CAPA}) import [^\n]*\b{otro}\b",
                             txt)
                or re.search(rf"import backend\.core(?:\.(?:{_NOMBRES_CAPA}))?\.{otro}\b", txt)
                # relativos: uno o dos puntos, con o sin la capa delante
                or re.search(rf"from \.{{1,2}}(?:(?:{_NOMBRES_CAPA})\.)?{otro}\b", txt)
                or re.search(rf"from \.{{1,2}}(?:{_NOMBRES_CAPA})? import [^\n]*\b{otro}\b", txt)):
            fuera.add(otro)
    return fuera


print("== 1) todos los modulos tienen capa asignada ==")
MODS = modulos()
for m in MODS:
    check(m in NIVEL,
          f"«{m}» no esta en ninguna capa: clasificalo en tests/test_capas_backend.py "
          "y en backend/core/CAPAS.md")
for m in NIVEL:
    check(m in MODS, f"«{m}» esta clasificado pero ya no existe en backend/core/")

print("== 2) ningun modulo depende de una capa superior ==")
for m in MODS:
    if m not in NIVEL:
        continue
    for otro in sorted(importa(m)):
        if otro not in NIVEL or (m, otro) in EXCEPCIONES:
            continue
        check(NIVEL[otro] <= NIVEL[m],
              f"{NOMBRE[NIVEL[m]]}/{m} importa {NOMBRE[NIVEL[otro]]}/{otro}: "
              "la dependencia va hacia ARRIBA")

print("== 3) la capa comun no depende de nada de core ==")
for m in sorted(CAPAS[0][1] & set(MODS)):
    dentro = importa(m) - {"events"}          # el bus lo usa hasta la propia capa
    check(not (dentro - CAPAS[0][1]),
          f"comun/{m} importa {sorted(dentro - CAPAS[0][1])}, y la capa de abajo "
          "tiene que poder leerse sola")

print("== 4) las excepciones siguen siendo ciertas ==")
for a, b in sorted(EXCEPCIONES):
    if a not in MODS or b not in MODS:
        check(False, f"la excepcion {a} → {b} nombra un modulo que ya no existe")
        continue
    check(b in importa(a),
          f"la excepcion {a} → {b} ya no hace falta: quitala de EXCEPCIONES "
          "y de backend/core/CAPAS.md, que la deuda saldada se borra")

print("== 5) CAPAS.md nombra las mismas capas y las mismas excepciones ==")
doc = (CORE / "CAPAS.md").read_text(encoding="utf-8")
for nombre, _ms in CAPAS:
    check(nombre.replace("comun", "común").replace("aplicacion", "aplicación") in doc.lower()
          or nombre in doc.lower(), f"CAPAS.md no habla de la capa «{nombre}»")
for a, b in sorted(EXCEPCIONES):
    check(a in doc and b in doc,
          f"la excepcion {a} → {b} no esta explicada en backend/core/CAPAS.md")
# Y la TABLA de CAPAS.md nombra los mismos modulos que la lista de aqui, FILA A
# FILA. Sin esto, dar de alta un modulo solo en el test dejaba la suite en verde
# y el documento desactualizado: la capa se leia distinta segun donde se mirase.
#
# OJO A COMO SE COMPRUEBA, QUE AQUI ESTUVO EL FALLO. Antes se buscaba «`modulo`»
# en el DOCUMENTO ENTERO. Pero debajo de la tabla hay prosa explicando las
# colocaciones no obvias, y ahi se nombran `pm`, `reglas` y `aprendizaje` entre
# comillas invertidas. Resultado: quitar cualquiera de esos tres de la TABLA
# dejaba la suite VERDE — la prosa tapaba el hueco. Se comprobo el 05/08/2026
# borrando `reglas` de la fila de dominio: 424 OK, 0 fallos.
#
# Peor todavia: buscando en todo el documento, un modulo listado en la FILA
# EQUIVOCADA tambien pasaba. La tabla dice quien esta en cada capa; si no se lee
# fila a fila, no se esta comprobando la tabla, se esta comprobando que la
# palabra aparece en alguna parte.
def _tabla_capas(texto: str) -> dict[str, set[str]]:
    """Capa → modulos, leidos de las FILAS de la tabla «Quién está en cada capa».

    Solo las filas de la tabla: en cuanto se acaba (primera linea que no empieza
    por «|») se para, para que la prosa de debajo no cuente."""
    fuera: dict[str, set[str]] = {}
    dentro = False
    for linea in texto.splitlines():
        if linea.lstrip().startswith("| Capa "):
            dentro = True
            continue
        if not dentro:
            continue
        if not linea.lstrip().startswith("|"):
            break
        celdas = [c.strip() for c in linea.strip().strip("|").split("|")]
        if len(celdas) < 2:
            continue
        capa = celdas[0].strip("* ").lower()
        capa = capa.replace("común", "comun").replace("aplicación", "aplicacion")
        if capa in ("---", ""):
            continue
        fuera[capa] = set(re.findall(r"`([^`]+)`", celdas[1]))
    return fuera


TABLA = _tabla_capas(doc)
for nombre, mods in CAPAS:
    fila = TABLA.get(nombre)
    if not check(fila is not None,
                 f"la tabla de backend/core/CAPAS.md no tiene fila para la capa «{nombre}»"):
        continue
    for m in sorted(mods):
        check(m in fila,
              f"«{m}» esta en la capa «{nombre}» del test pero NO en la fila de "
              f"«{nombre}» de la tabla de backend/core/CAPAS.md")
    for m in sorted(fila - mods):
        check(False,
              f"la tabla de backend/core/CAPAS.md pone «{m}» en la capa «{nombre}» "
              "y el test no: el documento y la prueba dicen capas distintas")

print("== 6) el modulo que ya vive en su capa esta en la carpeta que le toca ==")

# ESTO ES LO QUE HACE QUE MOVER LOS FICHEROS SIRVA DE ALGO. Hasta ahora la capa
# de un modulo era una lista dentro de esta prueba: se podia leer el fichero sin
# enterarse. Al bajarlo a `backend/core/<capa>/`, la capa se ve abriendo la
# carpeta — y aqui se comprueba que las dos versiones no puedan discrepar.
#
# La mudanza TERMINO: los 42 modulos estan en su capa. Asi que ya no se tolera
# ninguno suelto en `core/` — dejar uno seria volver a la carpeta plana por la
# puerta de atras, y nadie se enteraria hasta tener veinte otra vez.
for capa, mods in CAPAS:
    for m in sorted(mods):
        real = capa_por_carpeta(m)
        check(real != "",
              f"«{m}» sigue suelto en backend/core/: le toca «{capa}/»")
        check(real in ("", capa),
              f"«{m}» esta declarado en «{capa}» pero vive en «backend/core/{real}/»")

# Y ningun modulo nuevo puede quedarse en la raiz de core/ sin capa.
for f in CORE.glob("*.py"):
    check(f.stem == "__init__",
          f"«{f.name}» esta en la raiz de backend/core/: clasificalo en una capa")

# Y ningun modulo se queda fuera de las capas al bajar de carpeta.
for f in CORE.rglob("*.py"):
    if f.stem == "__init__" or f.parent == CORE:
        continue
    check(f.parent.name in {c for c, _m in CAPAS},
          f"«{f.parent.name}/» no es ninguna de las capas declaradas")


print(f"\n{'#' * 54}\ntest_capas_backend: {_pass} OK, {len(_fail)} fallos")
for m in _fail:
    print("  -", m)
sys.exit(1 if _fail else 0)
