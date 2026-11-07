# -*- coding: utf-8 -*-
"""Auditoría de la skill MEDIA/MÚSICA: activación con frases naturales, enrutado
real, fronteras con domotica/system_pc/hermes/tools/tasks_board y honestidad
cuando no hay teclas multimedia.

No reproduce nada, no abre navegadores, no envía teclas y no escribe en data/:
`_open_url`, `_send_media_key`, el historial y el DJ del LLM son dobles.

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_skill_media.py
"""
from __future__ import annotations

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
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


from backend.core.aplicacion import skills_loader as sl  # noqa: E402

print("== 1) carga con el cargador real ==")
REG = sl.load_skills()
SK = REG.get("media")
check(SK is not None and SK.status != "error",
      f"media no carga: {SK.description if SK else 'no registrada'}")
MOD = SK.module if SK else None
check(MOD is not None and hasattr(MOD, "handle"), "media no expone handle()")
for i in ("pause", "next", "prev", "stop_music", "svc_answer", "random", "play"):
    check(i in (SK.patterns if SK else {}), f"falta el intent «{i}»")

print("== 2) activación con frases naturales (tildes, enclíticos, sinónimos) ==")
ACTIVAN = {
    "pause": ["pausa", "pausa la música", "pausa la canción", "páusame la música",
              "pausala", "reanuda", "reanúdala", "dale al play", "quita la pausa",
              "sigue con la música"],
    "next": ["siguiente canción", "pon otra canción", "salta la canción",
             "sáltame esta canción", "sáltate esta", "pon la siguiente",
             "pasa de canción", "cambia de canción"],
    "prev": ["canción anterior", "pon la canción anterior", "vuelve a la anterior",
             "repíteme la canción", "ponla otra vez", "canción de antes"],
    "stop_music": ["para la música", "quita la música", "apaga la música",
                   "quítame la música", "párame la música", "fuera música",
                   "detén la música"],
    "random": ["pon algo", "ponme algo", "pon música", "pon una canción",
               "sorpréndeme", "pon algo al azar", "pon algo de rock",
               "pon una canción de Quevedo", "ponme una musiquita",
               "quiero escuchar algo de jazz", "me apetece algo de música tranquila",
               "reprodúceme algo", "pon lo que quieras"],
    "play": ["pon Bohemian Rhapsody", "ponme Bohemian Rhapsody",
             "reproduce Shape of You", "reprodúceme Shape of You",
             "pon La Raja de tu Falda en spotify", "pon Columbia en itunes",
             "quiero oír la canción Thunderstruck", "pon la canción Despechá"],
}
for intent, frases in ACTIVAN.items():
    for f in frases:
        r = sl.route(f)
        got = f"{r[0].folder}.{r[1]}" if r else "(nada)"
        check(got == f"media.{intent}", f"«{f}» → {got} (esperado media.{intent})")

print("== 3) fronteras: «pon …» que NO es música ==")
AJENAS = {
    "pon el volumen al 50": "system_pc",
    "ponme el volumen al 50": "system_pc",
    "pon la tele": "domotica",
    "ponme la tele": "domotica",
    "pon la luz del salón": "domotica",
    "ponme hermes en marcha": "hermes",
    "ponme una alarma a las 8": "tools",
    "pon una tarea nueva": "tasks_board",
    "pon en marcha el docker": "autoprovision",
}
for frase, duenno in AJENAS.items():
    r = sl.route(frase)
    got = r[0].folder if r else "(nada)"
    check(got == duenno, f"«{frase}» → {got} (esperado {duenno}, no media)")


class _Settings(dict):
    def get(self, k, d=None):
        return dict.get(self, k, d)


class _Bus:
    async def emit(self, *a, **k):
        return None


CTX = {"settings": _Settings({"music_service": "youtube"}), "bus": _Bus(), "channel": "test"}

# Dobles: ni navegador, ni teclas, ni escritura en data/, ni LLM.
_abiertas, _teclas = [], []
MOD._open_url = lambda url: (_abiertas.append(url) or True)
MOD._send_media_key = lambda kind: (_teclas.append(kind) or True)
MOD._hist_load = lambda: []
MOD._hist_add = lambda song: None


async def _dj(ctx, seed=""):
    return f"Artista - Canción ({seed})" if seed else "Artista - Canción"


MOD._pick_random_song = _dj


async def _yt(query, ctx):
    _abiertas.append("yt:" + query)
    return f"Reproduciendo «{query}» en YouTube ▶"


MOD._youtube_play = _yt

print("== 4) controles: sin teclas multimedia lo dice, no finge que sonó ==")
MOD._send_media_key = lambda kind: False
for intent in ("pause", "next", "prev", "stop_music"):
    r = asyncio.run(MOD.handle(intent, "pausa", None, CTX))
    check("⚠" in r["reply"] and "teclas multimedia" in r["reply"],
          f"{intent} sin teclas no avisa de que no ha podido")
    check("Traceback" not in r["reply"], f"{intent} suelta traceback")
MOD._send_media_key = lambda kind: (_teclas.append(kind) or True)
r = asyncio.run(MOD.handle("next", "siguiente canción", None, CTX))
check(_teclas[-1] == "next", "«siguiente canción» no manda la tecla next")

print("== 5) sin servicio dicho, pregunta en vez de decidir por su cuenta ==")
_abiertas.clear()
m = SK.patterns["play"].search("pon Bohemian Rhapsody")
r = asyncio.run(MOD.handle("play", "pon Bohemian Rhapsody", m, CTX))
check("Spotify o YouTube" in r["reply"], "no pregunta dónde poner la canción")
check(not _abiertas, "ha abierto algo antes de saber dónde ponerlo")

print("== 6) la respuesta corta de servicio resuelve la petición pendiente ==")
m2 = SK.patterns["svc_answer"].search("en youtube")
r = asyncio.run(MOD.handle("svc_answer", "en youtube", m2, CTX))
check("Bohemian Rhapsody" in r["reply"], "la respuesta «en youtube» pierde la canción")
check(any("Bohemian" in a for a in _abiertas), "no ha lanzado la canción tras responder")

print("== 7) una respuesta de servicio suelta no dispara nada ==")
MOD._PENDING_SVC["intent"] = ""
_abiertas.clear()
r = asyncio.run(MOD.handle("svc_answer", "spotify", m2, CTX))
check("Pídeme una canción" in r["reply"], "una respuesta suelta no se explica")
check(not _abiertas, "una respuesta de servicio suelta ha lanzado música")

print("== 8) el DJ aleatorio no inventa: pide canción real y la marca como al azar ==")
_abiertas.clear()
m3 = SK.patterns["random"].search("pon algo de rock en youtube")
r = asyncio.run(MOD.handle("random", "pon algo de rock en youtube", m3, CTX))
check("🎲" in r["reply"], "no marca que la canción la ha elegido él")
check("rock" in r["reply"], "pierde el filtro pedido («de rock»)")

print("== 9) SKILL.md: dice qué NO hace y a quién le toca ==")
doc = SK.doc or ""
check("Qué NO hace" in doc, "el SKILL.md no dice qué NO hace")
for otro in ("Sistema/PC", "Domótica", "Tablero"):
    check(otro in doc, f"el SKILL.md no deriva a «{otro}»")
check("scraping" not in doc.lower(), "el SKILL.md menciona scraping")

print("== 10) Spotify: el `state` del OAuth es de un solo uso (SEC-15) ==")
# Auditoría del 30/07/2026, roadmap P3-5: el callback aceptaba el `code` sin
# mirar `state`, así que un enlace ajeno podía dejar vinculada la cuenta de
# Spotify de otra persona (login CSRF). Aquí se comprueba la MITAD que vive en
# `spotify.py` (crear, comparar y consumir); la ruta del callback —que exige el
# `state` antes de canjear— se prueba en tests/unit/core/test_errores_api.py,
# donde ya hay un backend en proceso con configuración de usar y tirar.
import json as _json
import shutil as _shutil
import tempfile as _tempfile
import time as _time
import urllib.parse as _urlparse
from pathlib import Path as _Path

from backend.core.infraestructura import spotify as _sp

_CARPETA = _Path(_tempfile.mkdtemp(prefix="nexus_spotify_state_"))
_PENDIENTE_PREVIO, _TOKEN_PREVIO = _sp.PENDING_FILE, _sp.TOKEN_FILE
# Los DOS archivos de estado se apuntan a la carpeta de usar y tirar: ni se lee
# ni se escribe el config/spotify_token.json del operador desde aquí.
_sp.PENDING_FILE = _CARPETA / "spotify_pending.json"
_sp.TOKEN_FILE = _CARPETA / "spotify_token.json"


def _estado_de(url: str) -> str:
    return (_urlparse.parse_qs(_urlparse.urlparse(url).query).get("state") or [""])[0]


try:
    s1 = _estado_de(_sp.auth_url())
    check(bool(s1), "auth_url() no incluye `state`: un callback ajeno se aceptaría")
    check(len(s1) >= 16, f"el `state` es demasiado corto para ser impredecible ({len(s1)} caracteres)")
    check("state=" in _sp.auth_url(), "la URL de autorización no enseña el `state`")
    s2 = _estado_de(_sp.auth_url())
    check(s1 != s2, "dos autorizaciones seguidas usan el MISMO `state`")

    check(_sp.consumir_estado(s2) is True,
          "el `state` recién creado no se acepta: no se podría autorizar nunca")
    check(_sp.consumir_estado(s2) is False, "el `state` vale DOS veces (replay aceptado)")
    check(not _sp.PENDING_FILE.exists(), "el `state` consumido se queda guardado en disco")
    check(_sp.consumir_estado("") is False, "un callback SIN `state` se acepta")
    check(_sp.consumir_estado("inventado") is False, "un `state` inventado se acepta")
    check(not _sp.TOKEN_FILE.exists(),
          "crear o gastar el `state` ha escrito en el token de Spotify")

    # Un intento fallido NO quema el que estaba pendiente: si lo hiciera, cualquiera
    # que mande un callback falso te tumba la autorización en curso.
    s3 = _estado_de(_sp.auth_url())
    check(_sp.consumir_estado("basura") is False, "«basura» se acepta como `state`")
    check(_sp.consumir_estado(s3) is True,
          "un callback con `state` falso ha quemado el bueno (ya no se puede autorizar)")

    # Caducado: un `state` viejo no puede revivir.
    _sp.PENDING_FILE.write_text(_json.dumps({"state": "viejo",
                                             "creado": _time.time() - _sp.TTL_ESTADO - 60}),
                                encoding="utf-8")
    check(_sp.consumir_estado("viejo") is False, "un `state` caducado se acepta")
    check(not _sp.PENDING_FILE.exists(), "el `state` caducado se queda en disco")
finally:
    _sp.PENDING_FILE, _sp.TOKEN_FILE = _PENDIENTE_PREVIO, _TOKEN_PREVIO
    _shutil.rmtree(_CARPETA, ignore_errors=True)

print(f"\n{'#'*54}\n{_pass} comprobaciones OK, {len(_fail)} fallos")
for m in _fail:
    print("  -", m)
sys.exit(1 if _fail else 0)
