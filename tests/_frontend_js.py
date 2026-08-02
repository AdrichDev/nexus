# -*- coding: utf-8 -*-
"""El JavaScript del HUD, entero, como si siguiera siendo un solo fichero.

Muchas suites comprueban el frontend leyendo `frontend/js/command.js` y
buscando dentro un trozo de codigo. Eso funcionaba cuando TODO vivia en un
fichero de 3.624 lineas. Al partirlo en modulos (Fase 2), catorce
comprobaciones se pusieron rojas sin que nada dejara de funcionar: el codigo
seguia ahi, solo que en `views/devices.js`.

Apuntar cada test al modulo nuevo lo arreglaria hoy y lo volveria a romper en
el proximo corte. Asi que en vez de eso se lee el arbol entero: lo que se
comprueba es que el HUD hace tal cosa, no en que fichero la hace.

Uso:
    from _frontend_js import js_hud
    js = js_hud()
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_DIR = ROOT / "frontend" / "js"

# Bibliotecas de terceros: no son nuestras y meten miles de lineas minificadas
# que solo sirven para provocar coincidencias falsas.
VENDOR = {"qrcode.min.js"}


def ficheros_hud() -> list[Path]:
    """Los modulos del HUD, en orden estable, sin las bibliotecas de terceros."""
    return sorted(f for f in JS_DIR.rglob("*.js") if f.name not in VENDOR)


def js_hud() -> str:
    """Todo el JavaScript propio del HUD concatenado, con separadores."""
    partes = []
    for f in ficheros_hud():
        partes.append(f"\n/* ==== {f.relative_to(JS_DIR).as_posix()} ==== */\n")
        partes.append(f.read_text(encoding="utf-8"))
    return "".join(partes)
