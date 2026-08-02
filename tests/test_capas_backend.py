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
    }),
    ("aplicacion", {
        "brain", "skills_loader", "scheduler", "background", "jobs",
        "wake", "hotkey", "voice_cycle",
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


def modulos() -> list[str]:
    return sorted(f.stem for f in CORE.glob("*.py") if f.stem != "__init__")


def importa(modulo: str) -> set[str]:
    """Modulos de core que importa este, en cualquiera de las cinco formas."""
    txt = (CORE / f"{modulo}.py").read_text(encoding="utf-8")
    txt = re.sub(r'"""(?:.|\n)*?"""', " ", txt)            # fuera los docstrings
    txt = re.sub(r"#[^\n]*", " ", txt)                     # y los comentarios
    fuera = set()
    for otro in modulos():
        if otro == modulo:
            continue
        if (re.search(rf"from backend\.core import [^\n]*\b{otro}\b", txt)
                or re.search(rf"from backend\.core\.{otro}\b", txt)
                or re.search(rf"import backend\.core\.{otro}\b", txt)
                or re.search(rf"from \.{otro}\b", txt)
                or re.search(rf"from \. import [^\n]*\b{otro}\b", txt)):
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

print(f"\n{'#' * 54}\ntest_capas_backend: {_pass} OK, {len(_fail)} fallos")
for m in _fail:
    print("  -", m)
sys.exit(1 if _fail else 0)
