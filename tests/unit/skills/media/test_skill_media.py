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
_OPEN_URL_REAL = MOD._open_url if MOD else None    # la de verdad: la última sección la restaura
_YOUTUBE_PLAY_REAL = MOD._youtube_play if MOD else None
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

print("== 11) Spotify: los ficheros de estado respetan NEXUS_CONFIG_DIR (T36) ==")
# T36, hallazgo de T13: `spotify.py` construía sus rutas como `ROOT / "config"`
# en vez de con `CONFIG_DIR`, así que IGNORABA `NEXUS_CONFIG_DIR` y escribía en
# el `config/` del repositorio incluso dentro de las pruebas. Aquí se ejecuta el
# módulo en un PROCESO aparte —la única forma de que `CONFIG_DIR` se lea ya con
# la variable puesta— y se mira DÓNDE caen sus rutas.
#
# El guion hijo NO escribe si las rutas se le escapan de la carpeta de usar y
# tirar: así el rojo de esta prueba (si alguien vuelve a `ROOT / "config"`) no
# deja un `spotify_token.json` falso en el config/ del operador. Del config/
# real solo se listan NOMBRES, antes y después: nunca se lee su contenido.
import json as _json2
import re as _re
import subprocess as _subprocess

_SPOTIFY_FUENTE = (_Path(ROOT) / "backend" / "core" / "infraestructura" /
                   "spotify.py").read_text(encoding="utf-8")
check('ROOT / "config"' not in _SPOTIFY_FUENTE,
      "spotify.py vuelve a montar sus rutas con ROOT + config: ignora NEXUS_CONFIG_DIR")
check("CONFIG_DIR" in _SPOTIFY_FUENTE,
      "spotify.py no usa CONFIG_DIR para sus dos ficheros de estado")

_GUION_T36 = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])          # la raíz del repo, explícita
from backend.core.comun.config import CONFIG_DIR, ROOT
from backend.core.infraestructura import spotify

tmp = Path(sys.argv[1]).resolve()

def dentro(p):
    try:
        Path(p).resolve().relative_to(tmp)
        return True
    except ValueError:
        return False

salida = {"config_dir": str(CONFIG_DIR), "root": str(ROOT),
          "token": str(spotify.TOKEN_FILE), "pendiente": str(spotify.PENDING_FILE),
          "circuito": "", "escrituras": [],
          "existe_token": False, "existe_pendiente": False}
if not (dentro(spotify.TOKEN_FILE) and dentro(spotify.PENDING_FILE)):
    salida["circuito"] = "las rutas se salen de NEXUS_CONFIG_DIR: no escribo nada"
else:
    spotify._save_token({"refresh_token": "de-prueba", "access_token": "x"})
    spotify.auth_url()          # escribe el `state` pendiente
    salida["escrituras"] = sorted(p.name for p in tmp.iterdir())
    salida["existe_token"] = spotify.TOKEN_FILE.exists()
    salida["existe_pendiente"] = spotify.PENDING_FILE.exists()
print(json.dumps(salida))
'''

_CONFIG_REAL = _Path(ROOT) / "config"
_NOMBRES_ANTES = (sorted(p.name for p in _CONFIG_REAL.iterdir())
                  if _CONFIG_REAL.is_dir() else [])
_COBIJA = _Path(_tempfile.mkdtemp(prefix="nexus_spotify_cfg_"))
_COBIJA_DATOS = _Path(_tempfile.mkdtemp(prefix="nexus_spotify_data_"))
try:
    _guion = _COBIJA_DATOS / "guion_t36.py"
    _guion.write_text(_GUION_T36, encoding="utf-8")
    _entorno = dict(os.environ)
    _entorno["NEXUS_CONFIG_DIR"] = str(_COBIJA)
    _entorno["NEXUS_DATA_DIR"] = str(_COBIJA_DATOS)
    _entorno["PYTHONIOENCODING"] = "utf-8"
    _proc = _subprocess.run([sys.executable, str(_guion), str(_COBIJA), ROOT], cwd=ROOT,
                            env=_entorno, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=120)
    check(_proc.returncode == 0,
          "el módulo de Spotify no arranca con NEXUS_CONFIG_DIR: "
          + (_proc.stderr or "").strip()[-400:])
    _salida: dict = {}
    if _proc.returncode == 0:
        _salida = _json2.loads((_proc.stdout or "{}").strip().splitlines()[-1])
    check(_salida.get("config_dir") == str(_COBIJA),
          f"CONFIG_DIR no apunta a NEXUS_CONFIG_DIR: {_salida.get('config_dir')!r}")
    check(str(_salida.get("token", "")).startswith(str(_COBIJA)),
          f"TOKEN_FILE se sale de NEXUS_CONFIG_DIR: {_salida.get('token')!r}")
    check(str(_salida.get("pendiente", "")).startswith(str(_COBIJA)),
          f"PENDING_FILE se sale de NEXUS_CONFIG_DIR: {_salida.get('pendiente')!r}")
    check(_salida.get("circuito") == "",
          f"no se escribió nada: {_salida.get('circuito')!r}")
    check(_salida.get("escrituras") == ["spotify_pending.json", "spotify_token.json"],
          f"los dos ficheros de estado no caen en la carpeta de usar y tirar: "
          f"{_salida.get('escrituras')!r}")
    check(_salida.get("existe_pendiente") is True and _salida.get("existe_token") is True,
          "el token y el `state` pendiente no se han escrito donde toca")
    _NOMBRES_DESPUES = (sorted(p.name for p in _CONFIG_REAL.iterdir())
                        if _CONFIG_REAL.is_dir() else [])
    check(_NOMBRES_ANTES == _NOMBRES_DESPUES,
          "escribir el token de Spotify ha tocado el config/ del repositorio: "
          f"{sorted(set(_NOMBRES_DESPUES) - set(_NOMBRES_ANTES))}")
finally:
    _shutil.rmtree(_COBIJA, ignore_errors=True)
    _shutil.rmtree(_COBIJA_DATOS, ignore_errors=True)

print("== 12) el navegador solo recibe URLs que construye la propia skill (T20b) ==")
# SEC-11 cerró lo que nexus PIDE; esto es lo que nexus manda ABRIR al navegador
# del operador. En media `_open_url` es el ÚNICO sitio que llama a
# `webbrowser.open`, y todas sus URLs las arma el módulo: el equipo y el esquema
# son literales (`https://www.youtube.com/…`, `https://music.apple.com/…`,
# `spotify.auth_url()`) y lo que viene del texto va por `quote_plus` dentro de la
# consulta. Por eso aquí no se mete la guarda de destino —una consulta DNS por
# cada «pon música», y sin conexión dejaría de poner música— sino que se FIJA
# con pruebas: si alguien pasa texto crudo a `_open_url`, esto se pone rojo.
import types as _types                                       # noqa: E402
from pathlib import Path as _Path                            # noqa: E402
from urllib.parse import urlsplit as _urlsplit               # noqa: E402

_fuente = (_Path(ROOT) / "skills" / "media" / "skill.py").read_text(encoding="utf-8")
check(_fuente.count("webbrowser.open(") == 1,
      "media llama a `webbrowser.open` en más de un sitio: el destino ya no lo decide un solo embudo")
check("webbrowser.open(url)" in _fuente,
      "el ÚNICO `webbrowser.open` de media ya no es el de `_open_url(url)`")


class _RespuestaHttp:
    def __init__(self, texto):
        self.text = texto


class _ClienteHttp:
    """httpx de mentira: la búsqueda de YouTube no sale a la red."""

    def __init__(self, texto):
        self.texto = texto

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def get(self, _url, **_kw):
        return _RespuestaHttp(self.texto)


_nav_real = MOD.webbrowser.open
_httpx_real = MOD.httpx
_web: list = []
MOD._open_url = _OPEN_URL_REAL                     # la de verdad, no el doble de arriba
MOD.webbrowser.open = lambda url, *_a, **_k: (_web.append(url) or True)
try:
    MOD._apple_play("Rosalía")
    check(_web == ["https://music.apple.com/es/search?term=Rosal%C3%ADa"],
          f"Apple Music ya no abre la misma URL: {_web}")

    MOD.httpx = _types.SimpleNamespace(
        AsyncClient=lambda **_kw: _ClienteHttp('{"videoId":"dQw4w9WgXcQ"}'))
    _web.clear()
    _r = asyncio.run(_YOUTUBE_PLAY_REAL("lofi", CTX))
    check(_web == ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
          f"YouTube con vídeo encontrado abre otra cosa: {_web}")
    check("Reproduciendo" in _r, f"y la respuesta deja de decirlo: {_r!r}")

    MOD.httpx = _types.SimpleNamespace(AsyncClient=lambda **_kw: _ClienteHttp("nada"))
    _web.clear()
    _r = asyncio.run(_YOUTUBE_PLAY_REAL("lofi", CTX))
    check(_web == ["https://www.youtube.com/results?search_query=lofi"],
          f"YouTube sin vídeo abre otra cosa: {_web}")

    check({_urlsplit(u).hostname for u in _web}
          <= {"www.youtube.com", "music.apple.com", "accounts.spotify.com",
              "open.spotify.com"},
          f"media ha abierto un equipo que no fija él mismo: {_web}")
finally:
    MOD._open_url = lambda url: (_abiertas.append(url) or True)   # el doble de siempre
    MOD.webbrowser.open = _nav_real
    MOD.httpx = _httpx_real

print(f"\n{'#'*54}\n{_pass} comprobaciones OK, {len(_fail)} fallos")
for m in _fail:
    print("  -", m)
sys.exit(1 if _fail else 0)
