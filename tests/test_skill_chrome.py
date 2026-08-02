# -*- coding: utf-8 -*-
"""Auditoría de la skill CHROME: activación con frases naturales, enrutado real,
y que cerrar o cambiar de pestaña nunca acierte por casualidad.

No arranca Chrome ni habla con el puerto 9222: `_tabs` y `_cdp_action` son
dobles con una lista de pestañas inventada y un registro de lo que se pidió.

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_skill_chrome.py
"""
from __future__ import annotations

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_fail, _pass = [], 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  ✖ " + msg)


from backend.core import skills_loader as sl                 # noqa: E402

print("== 1) carga con el cargador real ==")
REG = sl.load_skills()
SK = REG.get("chrome")
check(SK is not None and SK.status != "error",
      f"chrome no carga: {SK.description if SK else 'no registrada'}")
MOD = SK.module if SK else None
check(MOD is not None and hasattr(MOD, "handle"), "chrome no expone handle()")
for i in ("connect", "close", "switch", "open", "read", "tabs"):
    check(i in (SK.patterns if SK else {}), f"falta el intent «{i}»")

print("== 2) activación con frases naturales (tildes, enclíticos, sinónimos) ==")
ACTIVAN = {
    "connect": ["conecta con chrome", "conéctate con chrome", "conéctame con chrome",
                "vincula chrome", "vincúlame chrome", "arranca chrome",
                "arráncame chrome", "lanza chrome", "reinicia chrome",
                "chrome en modo nexus", "estado de chrome"],
    "tabs": ["qué pestañas tengo abiertas", "cuántas pestañas tengo",
             "muéstrame las pestañas", "enséñame las pestañas", "lístame las pestañas",
             "dame mis pestañas", "mis pestañas", "pestañas abiertas",
             "qué tengo abierto en chrome"],
    "read": ["resume la pestaña 2", "resúmeme la pestaña 2", "lee la pestaña de youtube",
             "léeme la pestaña de youtube", "analiza la pestaña 3",
             "explícame la pestaña 1", "traduce la pestaña 2", "de qué va la pestaña 2",
             "qué estoy viendo en chrome", "resúmeme la web abierta",
             "analiza lo que ves en la página de chrome", "lee la página actual"],
    "switch": ["cambia a la pestaña de gmail", "cámbiame a la pestaña de gmail",
               "vete a la pestaña de gmail", "ve a la pestaña 2",
               "salta a la pestaña de youtube", "activa la pestaña de gmail"],
    "open": ["abre una pestaña con el tiempo en madrid", "ábreme una pestaña con el tiempo",
             "abre una nueva pestaña", "abre marca.com en chrome",
             "ábreme marca.com en chrome", "abre google en el navegador"],
    "close": ["cierra la pestaña de twitter", "cierra la pestaña 2",
              "ciérrame la pestaña 2"],
}
for intent, frases in ACTIVAN.items():
    for f in frases:
        r = sl.route(f)
        got = f"{r[0].folder}.{r[1]}" if r else "(nada)"
        check(got == f"chrome.{intent}", f"«{f}» → {got} (esperado chrome.{intent})")

TABS = [{"id": "A", "title": "YouTube — vídeos", "url": "https://youtube.com/"},
        {"id": "B", "title": "Gmail", "url": "https://mail.google.com/"},
        {"id": "C", "title": "Marca", "url": "https://marca.com/"}]
_acciones = []


async def _tabs_ok():
    return list(TABS)


async def _tabs_none():
    return None


async def _accion(path):
    _acciones.append(path)
    return True


MOD._cdp_action = _accion
CTX = {"settings": {}, "channel": "test"}


def run(intent, texto):
    m = SK.patterns[intent].search(texto)
    return asyncio.run(MOD.handle(intent, texto, m, CTX))


print("== 3) sin Chrome vinculado, explica cómo vincularlo ==")
MOD._tabs = _tabs_none
r = run("tabs", "qué pestañas tengo abiertas")
check("modo nexus" in r["reply"] and "conecta con chrome" in r["reply"],
      "sin vínculo no explica el «modo nexus»")
check("Traceback" not in r["reply"], "sin vínculo suelta traceback")

MOD._tabs = _tabs_ok

print("== 4) listado de pestañas: lo que hay, sin inventar ==")
r = run("tabs", "qué pestañas tengo abiertas")
check("3 pestaña" in r["reply"], "no cuenta bien las pestañas")
check(all(t["title"] in r["reply"] for t in TABS), "se deja títulos por el camino")
check(len(r.get("data") or []) == 3, "no devuelve los datos de las pestañas")

print("== 5) cerrar: si el selector no encaja, NO cierra la primera ==")
_acciones.clear()
r = run("close", "cierra la pestaña de twitter")
check(not _acciones, "ha cerrado una pestaña que nadie pidió cerrar")
check("No he cerrado ninguna" in r["reply"], "no deja claro que no cerró nada")
check("Gmail" in r["reply"], "no enseña las pestañas para elegir")

_acciones.clear()
r = run("close", "cierra la pestaña 2")
check(_acciones == ["/json/close/B"], f"«cierra la pestaña 2» cerró {_acciones}")

_acciones.clear()
r = run("close", "cierra la pestaña 9")
check(not _acciones, "un número fuera de rango cierra otra pestaña")

print("== 6) cambiar: mismo criterio, nada de aciertos por casualidad ==")
_acciones.clear()
r = run("switch", "cambia a la pestaña de linkedin")
check(not _acciones, "ha cambiado a una pestaña que no se pidió")
check("No tengo ninguna pestaña que encaje" in r["reply"], "no dice que no encaja")

_acciones.clear()
run("switch", "cambia a la pestaña de gmail")
check(_acciones == ["/json/activate/B"], f"«pestaña de gmail» activó {_acciones}")

print("== 7) abrir: URL tal cual, texto libre como búsqueda ==")
_acciones.clear()
run("open", "abre marca.com en chrome")
check(_acciones and _acciones[0].endswith("https://marca.com"),
      f"abrir marca.com pidió {_acciones}")
_acciones.clear()
run("open", "abre una pestaña con el tiempo en madrid")
check(_acciones and "google.com/search" in _acciones[0],
      f"el texto libre no fue a buscar: {_acciones}")

print("== 8) leer sin la librería websockets: lo dice, no se inventa la página ==")
_ws = MOD.HAS_WS
MOD.HAS_WS = False
r = run("read", "resume la pestaña 1")
check("websockets" in r["reply"], "sin websockets no explica qué falta")
check("YouTube" in r["reply"], "sin websockets ni siquiera dice de qué pestaña habla")
MOD.HAS_WS = _ws

print("== 9) SKILL.md coherente con lo que hace ==")
doc = SK.doc or ""
check("9222" in doc, "el SKILL.md no dice el puerto CDP")
check("chrome_nexus" in doc, "el SKILL.md no dice qué perfil usa")
check("Qué NO hace" in doc, "el SKILL.md no dice qué NO hace")
check("no toca nada" in doc, "el SKILL.md no dice qué pasa si la pestaña no encaja")
for propio in ("Adri", "achoz", "C:\\Users"):
    check(propio not in doc, f"el SKILL.md nombra algo del usuario: {propio}")

print(f"\n{'#'*54}\n{_pass} comprobaciones OK, {len(_fail)} fallos")
for m in _fail:
    print("  -", m)
sys.exit(1 if _fail else 0)
