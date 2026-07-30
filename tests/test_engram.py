# -*- coding: utf-8 -*-
"""Tests de la integración con Engram (github.com/Gentleman-Programming/engram) —
memoria de PROYECTO/código, compartida con otras herramientas de IA, pedida
por Adri. Cubre:

  * backend/core/engram_bridge.py: detección del binario, auto-arranque del
    servidor (mismo tratamiento que el gateway de Hermes), y las llamadas
    HTTP de guardar/buscar/contexto/contar — contra un CONTRATO VERIFICADO A
    MANO ejecutando el binario real v1.20.0 en un sandbox (no adivinado):
    POST /sessions, POST /observations, GET /search (devuelve `null` sin
    resultados, ¡no una lista vacía!), GET /context, GET /observations.
  * skills/engram/skill.py: enrutado de las 4 intents (status/save/context/
    search) y que NO colisiona con la memoria PERSONAL (skill Memoria) —
    «recuerda que...», «qué sabes de mí»... deben seguir intactas.

Ejecutar:  python tests/test_engram.py    (desde la carpeta nexus)
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import re
import stat
import sys
import tempfile
import types
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:                      # consola de Windows en cp1252: «✔» reventaba la suite
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
_fail = []
_pass = 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


def _stub(name):
    m = types.ModuleType(name)
    m.__getattr__ = lambda _n: types.SimpleNamespace()
    sys.modules[name] = m
    return m


def load_skill_module(folder):
    path = os.path.join(ROOT, "skills", folder, "skill.py")
    for _ in range(15):
        spec = importlib.util.spec_from_file_location(f"_engramtest_{folder}", path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            return mod
        except ModuleNotFoundError as e:
            _stub(e.name)
    raise RuntimeError(folder)


class _FakeSettings(dict):
    """Settings mínimo: .get(key, default) sobre un dict normal."""
    def get(self, key, default=None):
        return dict.get(self, key, default)


class _FakeResp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or ""

    def json(self):
        return self._payload


# ══════════════════════ backend/core/engram_bridge.py ══════════════════════

def test_engram_exe_deteccion():
    import backend.core.engram_bridge as eng

    # 1) ⚙ engram_exe apuntando a un ejecutable real -> se usa esa ruta
    tmp = Path(tempfile.mkdtemp())
    exe = tmp / "engram"
    exe.write_text("#!/bin/sh\necho fake\n", encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    ctx = {"settings": _FakeSettings({"engram_exe": str(exe)})}
    check(eng._engram_exe(ctx) == str(exe), "engram_exe: usa la ruta de ⚙ si existe")
    check(eng.installed(ctx) is True, "installed: True con ⚙ engram_exe válido")

    # 2) ⚙ engram_exe con una ruta que NO existe -> se ignora, cae a autodetección
    ctx2 = {"settings": _FakeSettings({"engram_exe": "/no/existe/engram"})}
    old_which = eng.shutil.which
    eng.shutil.which = lambda *_a, **_k: None
    old_home = os.path.expanduser
    try:
        os.path.expanduser = lambda p: "/no/existe/home" if p == "~" else old_home(p)
        check(eng.installed(ctx2) is False,
              "installed: False si ni ⚙, ni PATH, ni rutas típicas tienen el binario")
    finally:
        eng.shutil.which = old_which
        os.path.expanduser = old_home

    # 3) autodetección por PATH (shutil.which)
    eng.shutil.which = lambda name, **_k: (str(exe) if "engram" in name else None)
    try:
        ctx3 = {"settings": _FakeSettings({})}
        check(eng.installed(ctx3) is True, "installed: True vía PATH (shutil.which)")
    finally:
        eng.shutil.which = old_which


def test_base_url_y_puerto():
    import backend.core.engram_bridge as eng
    check(eng._base_url({"settings": _FakeSettings({})}) == "http://127.0.0.1:7437",
          "base_url: puerto por defecto 7437")
    check(eng._base_url({"settings": _FakeSettings({"engram_port": 9001})}) == "http://127.0.0.1:9001",
          "base_url: respeta el puerto de ⚙")
    check(eng._base_url({"settings": _FakeSettings({"engram_port": "no-es-un-numero"})})
         == "http://127.0.0.1:7437",
          "base_url: puerto inválido -> cae al de por defecto sin reventar")


def test_alive_cached():
    import backend.core.engram_bridge as eng
    old_alive, old_ts = eng._ALIVE["ok"], eng._ALIVE["ts"]
    old_fn = eng._alive
    calls = {"n": 0}

    async def fake_alive(url):
        calls["n"] += 1
        return True

    async def run():
        eng._ALIVE.update(ok=False, ts=0.0)
        eng._alive = fake_alive
        ctx = {"settings": _FakeSettings({})}
        r1 = await eng.alive_cached(ctx)
        r2 = await eng.alive_cached(ctx)     # dentro de los 60s -> NO debe volver a llamar a _alive
        check(r1 is True and r2 is True, "alive_cached: devuelve True las dos veces")
        check(calls["n"] == 1, "alive_cached: usa la caché de 60s, no pinga dos veces seguidas")

    try:
        asyncio.run(run())
    finally:
        eng._alive = old_fn
        eng._ALIVE.update(ok=old_alive, ts=old_ts)


def test_ensure_up_ya_vivo_no_lanza_nada():
    import backend.core.engram_bridge as eng
    old_ts = eng._ALIVE["ts"]
    old_popen = eng.subprocess.Popen

    def boom(*a, **k):
        raise AssertionError("no debería intentar lanzar el proceso si ya está vivo")

    async def run():
        eng._ALIVE.update(ok=True, ts=__import__("time").monotonic())
        eng.subprocess.Popen = boom
        ctx = {"settings": _FakeSettings({})}
        ok = await eng.ensure_up(ctx)
        check(ok is True, "ensure_up: ya vivo -> True")

    try:
        asyncio.run(run())
    finally:
        eng.subprocess.Popen = old_popen
        eng._ALIVE["ts"] = old_ts


def test_ensure_up_no_instalado():
    import backend.core.engram_bridge as eng
    old_ts, old_which, old_alive = eng._ALIVE["ts"], eng.shutil.which, eng._alive
    old_home = os.path.expanduser

    async def dead(_url):        # /health hermético: nada escuchando (no dependemos de la red real)
        return False

    async def run():
        eng._ALIVE.update(ok=False, ts=0.0)
        eng.shutil.which = lambda *_a, **_k: None
        eng._alive = dead
        # home inexistente: ni ~/.engram/bin ni ~/go/bin tienen un binario real
        # (imprescindible: en la máquina de Adri, tras instalar, SÍ existe ~/.engram/bin)
        os.path.expanduser = lambda p: "/no/existe/home" if p == "~" else old_home(p)
        ctx = {"settings": _FakeSettings({"engram_exe": "/no/existe"})}
        ok = await eng.ensure_up(ctx)
        check(ok is False, "ensure_up: binario no instalado -> False")
        check("no está instalado" in eng._LAST["err"],
              "ensure_up: el error explica que no está instalado")

    try:
        asyncio.run(run())
    finally:
        eng.shutil.which = old_which
        eng._alive = old_alive
        os.path.expanduser = old_home
        eng._ALIVE["ts"] = old_ts


def test_ensure_up_autostart_desactivado():
    import backend.core.engram_bridge as eng
    old_ts, old_alive = eng._ALIVE["ts"], eng._alive
    tmp = Path(tempfile.mkdtemp())
    exe = tmp / "engram"
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)

    async def dead(_url):        # /health hermético: no dependemos de que algo escuche en 7437
        return False

    async def run():
        eng._ALIVE.update(ok=False, ts=0.0)
        eng._alive = dead
        ctx = {"settings": _FakeSettings({"engram_exe": str(exe), "engram_autostart": False})}
        ok = await eng.ensure_up(ctx)
        check(ok is False, "ensure_up: engram_autostart=False -> False")
        check("desactivado" in eng._LAST["err"], "ensure_up: el error explica que está desactivado en ⚙")

    try:
        asyncio.run(run())
    finally:
        eng._alive = old_alive
        eng._ALIVE["ts"] = old_ts


def test_ensure_up_lanza_y_espera_y_no_relanza_en_rafaga():
    import backend.core.engram_bridge as eng
    old_ts, old_launch_ts = eng._ALIVE["ts"], eng._LAUNCH["ts"]
    old_popen, old_sleep, old_alive = eng.subprocess.Popen, eng.asyncio.sleep, eng._alive
    tmp = Path(tempfile.mkdtemp())
    exe = tmp / "engram"
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    popen_calls = {"n": 0}
    alive_calls = {"n": 0}

    class _FakeProc:
        def poll(self):
            return None

    def fake_popen(*a, **k):
        popen_calls["n"] += 1
        return _FakeProc()

    async def fake_sleep(_secs):
        return None

    async def fake_alive(url):
        alive_calls["n"] += 1
        # 1ª llamada (arranque): falla. 2ª llamada (misma espera): ya está viva.
        # Después vuelve a fallar (el servidor «se cae» de nuevo) para que la 2ª
        # llamada a ensure_up() no pueda dar por vivo el server vía alive_cached
        # y así SÍ ejercite de verdad la guarda anti-ráfaga (<45s), no solo la caché.
        return alive_calls["n"] == 2

    async def run():
        eng._ALIVE.update(ok=False, ts=0.0)
        eng._LAUNCH["ts"] = 0.0
        eng.subprocess.Popen = fake_popen
        eng.asyncio.sleep = fake_sleep
        eng._alive = fake_alive
        cfg_dir = tmp / "data"
        cfg_dir.mkdir(exist_ok=True)
        import backend.core.config as cfg
        old_dd = cfg.DATA_DIR
        cfg.DATA_DIR = cfg_dir
        try:
            ctx = {"settings": _FakeSettings({"engram_exe": str(exe)})}
            ok = await eng.ensure_up(ctx)
            check(ok is True, "ensure_up: lanza el proceso y espera hasta que /health responde")
            check(popen_calls["n"] == 1, "ensure_up: lanza el proceso UNA vez")
            # fuerza a re-evaluar alive_cached (si no, el test no probaría nada:
            # con caché viva, ensure_up() ni se acercaría a la guarda anti-ráfaga)
            eng._ALIVE.update(ok=False, ts=0.0)
            calls_before = alive_calls["n"]
            ok2 = await eng.ensure_up(ctx)
            check(ok2 is False,
                  "ensure_up: en ráfaga, con el server caído otra vez, no da falso positivo")
            check(popen_calls["n"] == 1,
                  "ensure_up: NO relanza en ráfaga (<45s desde el último intento)")
            check(alive_calls["n"] == calls_before + 1,
                  "ensure_up: en ráfaga solo repregunta una vez a /health (vía alive_cached), "
                  "no vuelve a esperar 20 s de sondeo")
        finally:
            cfg.DATA_DIR = old_dd

    try:
        asyncio.run(run())
    finally:
        eng.subprocess.Popen = old_popen
        eng.asyncio.sleep = old_sleep
        eng._alive = old_alive
        eng._ALIVE["ts"] = old_ts
        eng._LAUNCH["ts"] = old_launch_ts


def test_save():
    import backend.core.engram_bridge as eng
    old_ensure = eng.ensure_up
    old_post = eng._http_post
    old_ensure_session = eng._ensure_session

    async def ensure_ok(_ctx):
        return True

    async def ensure_fail(_ctx):
        eng._LAST["err"] = "engram no está instalado"
        return False

    async def noop_session(_url):
        return None

    async def run():
        eng.ensure_up = ensure_ok
        eng._ensure_session = noop_session

        # éxito
        async def post_ok(url, json=None, timeout=8):
            check(json["type"] == "decision", "save: manda el tipo pedido")
            check(json["project"] == eng.PROJECT, "save: siempre bajo el proyecto fijo")
            return _FakeResp(201, {"id": 42, "status": "saved"})
        eng._http_post = post_ok
        r = await eng.save({"settings": _FakeSettings({})}, "Título", "Contenido", kind="decision")
        check(r == {"ok": True, "id": 42}, "save: éxito devuelve ok+id")

        # tipo inválido -> cae a 'note'
        async def post_check_note(url, json=None, timeout=8):
            check(json["type"] == "note", "save: tipo desconocido cae a 'note'")
            return _FakeResp(201, {"id": 1})
        eng._http_post = post_check_note
        await eng.save({"settings": _FakeSettings({})}, "T", "C", kind="tipo-inventado")

        # fallo HTTP (p.ej. 404 sesión no encontrada)
        async def post_404(url, json=None, timeout=8):
            return _FakeResp(404, text='{"error":"session not found"}')
        eng._http_post = post_404
        r3 = await eng.save({"settings": _FakeSettings({})}, "T", "C")
        check(r3["ok"] is False and "404" in r3["error"], "save: HTTP 404 -> ok=False con detalle")

        # excepción de red
        async def post_boom(url, json=None, timeout=8):
            raise ConnectionError("no hay conexión")
        eng._http_post = post_boom
        r4 = await eng.save({"settings": _FakeSettings({})}, "T", "C")
        check(r4["ok"] is False and "ConnectionError" in r4["error"],
              "save: excepción de red -> ok=False, nunca lanza")

        # engram no disponible (ensure_up falla) -> ni intenta el POST
        eng.ensure_up = ensure_fail

        async def post_no_deberia_llamarse(*a, **k):
            raise AssertionError("no debería llamar a _http_post si ensure_up falló")
        eng._http_post = post_no_deberia_llamarse
        r5 = await eng.save({"settings": _FakeSettings({})}, "T", "C")
        check(r5["ok"] is False and "no está instalado" in r5["error"],
              "save: ensure_up falla -> ok=False sin tocar la red")

    try:
        asyncio.run(run())
    finally:
        eng.ensure_up = old_ensure
        eng._http_post = old_post
        eng._ensure_session = old_ensure_session


def test_search():
    import backend.core.engram_bridge as eng
    old_ensure, old_get = eng.ensure_up, eng._http_get

    async def ensure_ok(_ctx):
        return True

    async def run():
        eng.ensure_up = ensure_ok

        # query vacía -> [] SIN llamar a la red
        async def get_no_deberia_llamarse(*a, **k):
            raise AssertionError("no debería llamar a _http_get con query vacía")
        eng._http_get = get_no_deberia_llamarse
        r0 = await eng.search({"settings": _FakeSettings({})}, "   ")
        check(r0 == [], "search: query vacía -> [] sin llamar a la red")

        # la API real devuelve `null` (no []) cuando no hay resultados — CASO REAL VERIFICADO
        async def get_null(url, params=None, timeout=8):
            return _FakeResp(200, None)
        eng._http_get = get_null
        r1 = await eng.search({"settings": _FakeSettings({})}, "algo")
        check(r1 == [], "search: `null` de la API (sin resultados) -> [] sin reventar")

        # resultados reales, respeta el límite
        async def get_hits(url, params=None, timeout=8):
            check(params["q"] == "whatsapp", "search: manda la query tal cual")
            return _FakeResp(200, [{"id": i, "title": f"obs {i}"} for i in range(10)])
        eng._http_get = get_hits
        r2 = await eng.search({"settings": _FakeSettings({})}, "whatsapp", limit=3)
        check(len(r2) == 3, "search: respeta el límite pedido")

        # HTTP no-200 -> []
        async def get_500(url, params=None, timeout=8):
            return _FakeResp(500)
        eng._http_get = get_500
        r3 = await eng.search({"settings": _FakeSettings({})}, "algo")
        check(r3 == [], "search: HTTP 500 -> []")

        # ensure_up falla -> [] sin tocar la red
        async def ensure_fail(_ctx):
            return False
        eng.ensure_up = ensure_fail
        eng._http_get = get_no_deberia_llamarse
        r4 = await eng.search({"settings": _FakeSettings({})}, "algo")
        check(r4 == [], "search: engram no disponible -> []")

    try:
        asyncio.run(run())
    finally:
        eng.ensure_up = old_ensure
        eng._http_get = old_get


def test_context():
    import backend.core.engram_bridge as eng
    old_ensure, old_get = eng.ensure_up, eng._http_get

    async def ensure_ok(_ctx):
        return True

    async def run():
        eng.ensure_up = ensure_ok

        async def get_texto(url, params=None, timeout=8):
            return _FakeResp(200, {"context": "## resumen\nalgo pasó"})
        eng._http_get = get_texto
        r1 = await eng.context({"settings": _FakeSettings({})})
        check("algo pasó" in r1, "context: devuelve el texto real")

        async def get_vacio(url, params=None, timeout=8):
            return _FakeResp(200, {"context": ""})
        eng._http_get = get_vacio
        r2 = await eng.context({"settings": _FakeSettings({})})
        check(r2 == "", "context: proyecto sin nada -> ''")

        async def ensure_fail(_ctx):
            return False
        eng.ensure_up = ensure_fail
        r3 = await eng.context({"settings": _FakeSettings({})})
        check(r3 == "", "context: engram no disponible -> ''")

    try:
        asyncio.run(run())
    finally:
        eng.ensure_up = old_ensure
        eng._http_get = old_get


def test_count_no_arranca_el_servidor_solo_para_contar():
    import backend.core.engram_bridge as eng
    old_alive_cached, old_get, old_ensure = eng.alive_cached, eng._http_get, eng.ensure_up

    async def run():
        async def ensure_no_deberia_llamarse(_ctx):
            raise AssertionError("count() no debe llamar a ensure_up (no arranca el servidor solo para contar)")
        eng.ensure_up = ensure_no_deberia_llamarse

        async def alive_false(_ctx):
            return False
        eng.alive_cached = alive_false
        r0 = await eng.count({"settings": _FakeSettings({})})
        check(r0 == 0, "count: si no está vivo (según caché) -> 0, sin arrancarlo")

        async def alive_true(_ctx):
            return True
        eng.alive_cached = alive_true

        async def get_obs(url, params=None, timeout=6):
            return _FakeResp(200, [{"id": 1}, {"id": 2}, {"id": 3}])
        eng._http_get = get_obs
        r1 = await eng.count({"settings": _FakeSettings({})})
        check(r1 == 3, "count: cuenta las observaciones del proyecto")

    try:
        asyncio.run(run())
    finally:
        eng.alive_cached = old_alive_cached
        eng._http_get = old_get
        eng.ensure_up = old_ensure


def test_status_sync_puro():
    import backend.core.engram_bridge as eng
    ctx = {"settings": _FakeSettings({"engram_exe": "/no/existe"})}
    old_which, old_home = eng.shutil.which, os.path.expanduser
    eng.shutil.which = lambda *_a, **_k: None
    os.path.expanduser = lambda p: "/no/existe/home" if p == "~" else old_home(p)
    try:
        info = eng.status_sync(ctx)
        check(set(info.keys()) == {"installed", "exe", "url", "last_error", "alive_cached"},
              "status_sync: forma esperada del dict")
        check(info["installed"] is False, "status_sync: refleja que no está instalado")
    finally:
        eng.shutil.which = old_which
        os.path.expanduser = old_home


# ══════════════════════════ skills/engram/skill.py ══════════════════════════

def test_engram_routing():
    mod = load_skill_module("engram")
    pats = {k: re.compile(v, re.IGNORECASE) for k, v in mod.SKILL["patterns"].items()}

    def route(text):
        for intent, rx in pats.items():
            m = rx.search(text)
            if m:
                return intent, m
        return None, None

    casos = [
        ("recuerda en el proyecto que decidimos usar SQLite en vez de Postgres", "save"),
        ("apunta un bug en el proyecto: el whatsapp fallaba si n8n estaba caído", "save"),
        ("apunta una decisión de arquitectura en el proyecto: X", "save"),
        ("guarda en engram que el módulo de perfil se reescribió", "save"),
        ("anota en el código que hay que revisar los tests", "save"),
        ("apunta en el proyecto nexus que el login falla", "save"),
        ("recuerda en el proyecto de nexus que el login falla", "save"),
        ("recuerda en el proyecto nexus, que el login falla", "save"),
        ("recuerda en el proyecto nexus: que el login falla", "save"),
        ("qué se decidió sobre el whatsapp", "search"),
        ("busca en el proyecto engram", "search"),
        ("busca en el proyecto: whatsapp", "search"),
        ("qué sabe engram sobre el whatsapp", "search"),
        ("qué sabe engram del proyecto", "context"),
        ("qué sabe engram", "context"),
        ("contexto del proyecto", "context"),
        ("contexto del proyecto nexus", "context"),
        ("resumen del proyecto", "context"),
        ("está engram conectado", "status"),
        ("diagnostica engram", "status"),
        ("cómo va engram", "status"),
        ("engram está conectado", "status"),
    ]
    for texto, esperado in casos:
        intent, _m = route(texto)
        check(intent == esperado, f"engram routing: '{texto}' -> {intent} (esperaba {esperado})")

    # tipo capturado correctamente
    _intent, m = route("apunta un bug en el proyecto: se rompe el login")
    check(m.groupdict().get("tipo") == "bug", "engram routing: captura el tipo 'bug'")

    # regresión: nombrar el proyecto ("...proyecto nexus...") NO debe colarse
    # dentro de 'hecho' — 'nexus' aquí es el nombre del proyecto, no parte de
    # lo que hay que guardar (bug real encontrado en revisión: la ancla solo
    # casaba una palabra y "nexus" se quedaba pegado al principio de 'hecho')
    _intent2, m2 = route("apunta en el proyecto nexus que el login falla")
    check(m2.groupdict().get("hecho") == "el login falla",
          f"engram routing: 'proyecto nexus' no debe colar 'nexus' en hecho "
          f"(hecho={m2.groupdict().get('hecho')!r})")

    # regresión (encontrada en QA sonnet): variantes de la misma fuga —
    # "proyecto DE nexus" (posesivo natural) y puntuación ANTES de "que"
    # ("nexus, que..." / "nexus: que...") también deben limpiar 'hecho'.
    for texto_fuga, hecho_esp in (
        ("recuerda en el proyecto de nexus que el login falla", "el login falla"),
        ("guarda en el código de nexus que hay un bug en el login", "hay un bug en el login"),
        ("recuerda en el proyecto nexus, que el login falla", "el login falla"),
        ("recuerda en el proyecto nexus: que el login falla", "el login falla"),
    ):
        _i, mm = route(texto_fuga)
        check(mm is not None and mm.groupdict().get("hecho") == hecho_esp,
              f"engram routing: '{texto_fuga}' -> hecho={mm.groupdict().get('hecho') if mm else None!r} "
              f"(esperaba {hecho_esp!r})")

    # regresión (QA sonnet): "busca en el proyecto: X" con dos puntos, sin
    # espacio extra tras el ancla, debe seguir cayendo en 'search' con q2
    # limpio (antes exigía \s+ literal y no matcheaba nada)
    _i3, m3 = route("busca en el proyecto: whatsapp")
    check(m3 is not None and m3.groupdict().get("q2") == "whatsapp",
          f"engram routing: 'busca en el proyecto: X' -> q2={m3.groupdict().get('q2') if m3 else None!r}")

    check(mod._map_tipo("bug") == "bugfix", "engram: _map_tipo bug -> bugfix")
    check(mod._map_tipo("decisión de arquitectura") == "architecture",
          "engram: _map_tipo decisión de arquitectura -> architecture")
    check(mod._map_tipo("decisión") == "decision", "engram: _map_tipo decisión -> decision")
    check(mod._map_tipo("feature") == "feature", "engram: _map_tipo feature -> feature")
    check(mod._map_tipo("") == "note", "engram: _map_tipo vacío -> note")
    check(mod._map_tipo("cualquier-cosa-rara") == "note", "engram: _map_tipo desconocido -> note")


def test_engram_no_colisiona_con_memoria_personal():
    """Contrato duro: las frases de memoria PERSONAL deben seguir yendo a la
    skill Memoria (memory_graph), NUNCA a engram — son cosas DISTINTAS."""
    skdir = os.path.join(ROOT, "skills")
    all_pats = {}
    for folder in sorted(os.listdir(skdir)):
        if os.path.isfile(os.path.join(skdir, folder, "skill.py")):
            mod = load_skill_module(folder)
            all_pats[folder] = {k: re.compile(v, re.IGNORECASE)
                                for k, v in mod.SKILL["patterns"].items()}

    def global_route(text):
        for folder, pats in all_pats.items():
            for intent, rx in pats.items():
                if rx.search(text):
                    return folder, intent
        return None, None

    personales = [
        ("recuerda que mi madre se llama Pili", "memory_graph", "remember"),
        ("qué sabes de mí", "memory_graph", "list_knowledge"),
        ("mi perfil", "memory_graph", "profile"),
        ("quién soy", "memory_graph", "profile"),
        ("apunta en la memoria que odio el cilantro", "memory_graph", "remember"),
        ("aprende que trabajo en una agencia", "memory_graph", "learn"),
    ]
    for texto, skill_esp, intent_esp in personales:
        f, i = global_route(texto)
        check((f, i) == (skill_esp, intent_esp),
              f"anti-colisión: '{texto}' -> {f}/{i} (esperaba {skill_esp}/{intent_esp}, NO engram)")

    proyecto = [
        ("recuerda en el proyecto que usamos SQLite", "engram", "save"),
        ("está engram conectado", "engram", "status"),
    ]
    for texto, skill_esp, intent_esp in proyecto:
        f, i = global_route(texto)
        check((f, i) == (skill_esp, intent_esp),
              f"routing global: '{texto}' -> {f}/{i} (esperaba {skill_esp}/{intent_esp})")


def test_engram_handle_status():
    mod = load_skill_module("engram")
    import backend.core.engram_bridge as eng
    old_status, old_alive, old_ensure, old_count, old_installed = (
        eng.status_sync, eng.alive_cached, eng.ensure_up, eng.count, eng.installed)

    async def run():
        ctx = {"settings": _FakeSettings({})}

        # no instalado
        eng.installed = lambda _ctx: False
        eng.status_sync = lambda _ctx: {"installed": False, "exe": "", "url": "http://x",
                                        "last_error": "", "alive_cached": False}
        r1 = await mod.handle("status", "está engram conectado", None, ctx)
        check("no está instalado" in r1["reply"], "handle status: no instalado -> lo dice claro")
        check("opcional" in r1["reply"].lower(), "handle status: deja claro que es opcional")

        # instalado y vivo
        eng.installed = lambda _ctx: True
        eng.status_sync = lambda _ctx: {"installed": True, "exe": "/x/engram", "url": "http://127.0.0.1:7437",
                                        "last_error": "", "alive_cached": True}

        async def alive_true(_ctx):
            return True
        eng.alive_cached = alive_true

        async def count5(_ctx):
            return 5
        eng.count = count5
        r2 = await mod.handle("status", "está engram conectado", None, ctx)
        check("conectado" in r2["reply"] and "5" in r2["reply"], "handle status: vivo -> conectado + nº de recuerdos")

        # instalado pero parado, y se consigue levantar
        async def alive_false(_ctx):
            return False
        eng.alive_cached = alive_false

        async def ensure_true(_ctx):
            return True
        eng.ensure_up = ensure_true
        r3 = await mod.handle("status", "está engram conectado", None, ctx)
        check("acabo de arrancar" in r3["reply"], "handle status: parado pero se levanta -> lo dice")

        # instalado pero no se puede levantar
        async def ensure_false(_ctx):
            return False
        eng.ensure_up = ensure_false
        eng.status_sync = lambda _ctx: {"installed": True, "exe": "/x/engram", "url": "http://127.0.0.1:7437",
                                        "last_error": "puerto ocupado", "alive_cached": False}
        r4 = await mod.handle("status", "está engram conectado", None, ctx)
        check("puerto ocupado" in r4["reply"], "handle status: no se puede levantar -> explica el motivo real")

    try:
        asyncio.run(run())
    finally:
        (eng.status_sync, eng.alive_cached, eng.ensure_up, eng.count, eng.installed) = (
            old_status, old_alive, old_ensure, old_count, old_installed)


class _FakeMatch:
    def __init__(self, gd):
        self._gd = gd

    def groupdict(self):
        return dict(self._gd)


def test_engram_handle_save():
    mod = load_skill_module("engram")
    import backend.core.engram_bridge as eng
    old_save = eng.save

    async def run():
        ctx = {"settings": _FakeSettings({})}

        # sin hecho capturado -> pide aclaración, ni intenta guardar
        async def save_no_deberia_llamarse(*a, **k):
            raise AssertionError("no debería llamar a save() sin hecho")
        eng.save = save_no_deberia_llamarse
        r0 = await mod.handle("save", "recuerda en el proyecto que", _FakeMatch({"tipo": None, "hecho": ""}), ctx)
        check("qué apunto" in r0["reply"].lower(), "handle save: hecho vacío -> pide aclaración")

        # éxito
        async def save_ok(_ctx, title, content, kind="note"):
            check(kind == "bugfix", "handle save: traduce 'bug' -> bugfix antes de guardar")
            return {"ok": True, "id": 7}
        eng.save = save_ok
        r1 = await mod.handle("save", "apunta un bug en el proyecto: se rompe el login",
                              _FakeMatch({"tipo": "bug", "hecho": "se rompe el login"}), ctx)
        check("Guardado" in r1["reply"] and "se rompe el login" in r1["reply"],
              "handle save: éxito -> confirma con el contenido guardado")

        # fallo
        async def save_fail(_ctx, title, content, kind="note"):
            return {"ok": False, "error": "engram no está instalado"}
        eng.save = save_fail
        # v23 (T4): si el SERVIDOR de Engram no está disponible, nexus lo guarda
        # igualmente en su memoria operativa local (data/engram_ops.json) y lo dice.
        # Antes contestaba «No pude guardarlo», que era mentira: sí lo aplica.
        r2 = await mod.handle("save", "recuerda en el proyecto que el login se rompe",
                              _FakeMatch({"tipo": None, "hecho": "el login se rompe"}), ctx)
        check("Guardado" in r2["reply"] and "el login se rompe" in r2["reply"],
              "handle save: aunque Engram esté caído, lo guarda en su memoria y lo confirma")
        check("engram no está instalado" in r2["reply"],
              "handle save: y explica el motivo real por el que no se pudo espejar")

    try:
        asyncio.run(run())
    finally:
        eng.save = old_save


def test_engram_handle_search_y_context():
    mod = load_skill_module("engram")
    import backend.core.engram_bridge as eng
    old_search, old_context, old_installed = eng.search, eng.context, eng.installed

    async def run():
        ctx = {"settings": _FakeSettings({})}

        # search sin query -> pide aclaración
        r0 = await mod.handle("search", "busca en el proyecto",
                              _FakeMatch({"q1": None, "q2": "", "q3": None}), ctx)
        check("sobre qué" in r0["reply"].lower(), "handle search: sin query -> pide aclaración")

        # search con resultados
        async def search_hits(_ctx, query, limit=5):
            check(query == "whatsapp", "handle search: pasa la query capturada")
            return [{"type": "bugfix", "title": "Fix WhatsApp", "content": "cae al móvil si falla n8n"}]
        eng.search = search_hits
        r1 = await mod.handle("search", "qué se decidió sobre whatsapp",
                              _FakeMatch({"q1": "whatsapp", "q2": None, "q3": None}), ctx)
        check("Fix WhatsApp" in r1["reply"], "handle search: incluye los resultados encontrados")

        # search sin resultados, engram instalado
        async def search_vacio(_ctx, query, limit=5):
            return []
        eng.search = search_vacio
        eng.installed = lambda _ctx: True
        r2 = await mod.handle("search", "qué se decidió sobre algo",
                              _FakeMatch({"q1": "algo", "q2": None, "q3": None}), ctx)
        check("No encuentro nada" in r2["reply"], "handle search: sin resultados -> lo dice, no inventa nada")

        # context con texto
        async def context_texto(_ctx):
            return "## resumen\nse decidió usar SQLite"
        eng.context = context_texto
        r3 = await mod.handle("context", "contexto del proyecto", None, ctx)
        check("SQLite" in r3["reply"], "handle context: devuelve el resumen real")

        # context vacío, engram instalado
        async def context_vacio(_ctx):
            return ""
        eng.context = context_vacio
        eng.installed = lambda _ctx: True
        r4 = await mod.handle("context", "contexto del proyecto", None, ctx)
        check("todavía no hay nada" in r4["reply"], "handle context: vacío pero instalado -> invita a guardar algo")

        # context vacío, NO instalado
        eng.installed = lambda _ctx: False
        r5 = await mod.handle("context", "contexto del proyecto", None, ctx)
        check("no está instalado" in r5["reply"], "handle context: vacío y no instalado -> lo explica")

    try:
        asyncio.run(run())
    finally:
        eng.search = old_search
        eng.context = old_context
        eng.installed = old_installed


def test_engram_settings_defaults():
    """Contrato: los ajustes nuevos existen con valores razonables por
    defecto (autostart activado, puerto oficial de la herramienta)."""
    import backend.core.config as cfg
    check(cfg.DEFAULTS.get("engram_autostart") is True, "config: engram_autostart=True por defecto")
    check(cfg.DEFAULTS.get("engram_autoinstall") is True, "config: engram_autoinstall=True por defecto")
    check(cfg.DEFAULTS.get("engram_port") == 7437, "config: engram_port=7437 (puerto oficial) por defecto")
    check(cfg.DEFAULTS.get("engram_exe") == "", "config: engram_exe vacío por defecto (autodetección)")


# ══════════════════ instalación del binario (backend/core/engram_bridge.py) ══════════════════

def _make_asset(is_zip, names_and_data):
    """Construye el paquete EN EL FORMATO QUE TOCA en esta plataforma:
    .zip en Windows, .tar.gz en Linux/macOS. Antes se generaba siempre un
    tar.gz y en Windows la instalación fallaba — fallo del test, no del código."""
    return _make_zip(names_and_data) if is_zip else _make_targz(names_and_data)


def _make_targz(names_and_data):
    """tar.gz en memoria con los ficheros dados (para probar _extract_engram sin red)."""
    import io
    import tarfile
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, data in names_and_data:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _make_zip(names_and_data):
    """zip en memoria con los ficheros dados."""
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in names_and_data:
            z.writestr(name, data)
    return buf.getvalue()


def test_engram_plat_asset():
    import backend.core.engram_bridge as eng
    old = eng.sys.platform
    try:
        eng.sys.platform = "win32"
        a, is_zip = eng._plat_asset("1.20.0")
        check(a.startswith("engram_1.20.0_windows_") and a.endswith(".zip") and is_zip,
              f"_plat_asset windows -> zip ({a})")
        eng.sys.platform = "linux"
        a, is_zip = eng._plat_asset("1.20.0")
        check("linux" in a and a.endswith(".tar.gz") and not is_zip, f"_plat_asset linux -> tar.gz ({a})")
        eng.sys.platform = "darwin"
        a, is_zip = eng._plat_asset("1.20.0")
        check("darwin" in a and a.endswith(".tar.gz") and not is_zip, f"_plat_asset darwin -> tar.gz ({a})")
    finally:
        eng.sys.platform = old


def test_engram_sha256_ok():
    import hashlib
    import backend.core.engram_bridge as eng
    blob = b"contenido del binario"
    good = hashlib.sha256(blob).hexdigest()
    asset = "engram_1.20.0_linux_amd64.tar.gz"
    check(eng._sha256_ok(blob, asset, f"{good}  {asset}\n") is True, "sha256: coincide -> True")
    check(eng._sha256_ok(blob, asset, f"deadbeef  {asset}\n") is False, "sha256: no coincide -> False")
    check(eng._sha256_ok(blob, asset, f"{good}  otro_asset.zip\n") is False,
          "sha256: el asset no está en checksums.txt -> False")
    check(eng._sha256_ok(blob, asset, "") is False, "sha256: checksums vacío -> False")


def test_engram_extract():
    import os
    import backend.core.engram_bridge as eng
    tmp = Path(tempfile.mkdtemp())
    # tar.gz (linux/mac): trae el binario + basura que NO debe extraerse como binario
    tgz = _make_targz([("engram", b"BINARIO"), ("README.md", b"x"), ("LICENSE", b"y")])
    dest = eng._extract_engram(tgz, False, str(tmp / "a"))
    check(os.path.exists(dest) and open(dest, "rb").read() == b"BINARIO",
          "_extract_engram tar.gz: saca SOLO el binario engram")
    # zip (windows): el binario puede ir como engram.exe
    zp = _make_zip([("engram.exe", b"WINBIN"), ("README.md", b"x")])
    dest2 = eng._extract_engram(zp, True, str(tmp / "b"))
    check(os.path.exists(dest2) and open(dest2, "rb").read() == b"WINBIN",
          "_extract_engram zip: saca el binario engram.exe")


def test_engram_install_flow():
    import hashlib
    import os
    import backend.core.engram_bridge as eng
    old_exe, old_go, old_dl, old_ver = (eng._engram_exe, eng._go_install,
                                        eng._http_download, eng._latest_version)
    tmp = Path(tempfile.mkdtemp())
    try:
        eng._engram_exe = lambda _ctx: ""                 # fuerza el camino de instalación
        eng._go_install = lambda: ""                      # sin Go -> baja el binario
        eng._latest_version = lambda: "1.20.0"
        eng._managed_dir_test = str(tmp / "bin")
        old_mbd = eng._managed_bin_dir
        eng._managed_bin_dir = lambda: eng._managed_dir_test

        asset, _is_zip = eng._plat_asset("1.20.0")        # .zip en Windows, .tar.gz fuera
        blob = _make_asset(_is_zip, [("engram", b"REALBIN"), ("README.md", b"x")])
        checks = f"{hashlib.sha256(blob).hexdigest()}  {asset}\n"

        def fake_dl(url, timeout=60):
            if url.endswith("checksums.txt"):
                return checks.encode("utf-8")
            return blob
        eng._http_download = fake_dl

        # éxito: descarga + verifica checksum + extrae
        path = eng.install({})
        check(bool(path) and os.path.exists(path) and open(path, "rb").read() == b"REALBIN",
              "install: baja, verifica checksum y extrae el binario")

        # aborta si el checksum NO coincide (no instala nada corrupto)
        tmp2 = str(tmp / "bin2")
        eng._managed_dir_test = tmp2

        def bad_dl(url, timeout=60):
            if url.endswith("checksums.txt"):
                return b"0000  " + asset.encode() + b"\n"
            return blob
        eng._http_download = bad_dl
        eng._engram_exe = lambda _ctx: ""
        path2 = eng.install({})
        check(path2 == "" and not os.path.exists(os.path.join(tmp2, "engram")),
              "install: checksum que no cuadra -> aborta, no deja binario")

        # idempotente: si ya está instalado, devuelve la ruta SIN descargar
        called = {"n": 0}

        def dl_should_not(url, timeout=60):
            called["n"] += 1
            raise AssertionError("no debería descargar si ya está instalado")
        eng._http_download = dl_should_not
        eng._engram_exe = lambda _ctx: "/ya/instalado/engram"
        p3 = eng.install({})
        check(p3 == "/ya/instalado/engram" and called["n"] == 0,
              "install: ya instalado -> devuelve la ruta sin descargar")

        # fallback de versión: si el asset de la última versión falla (404), reintenta
        # con _KNOWN_VERSION
        tmp3 = str(tmp / "bin3")
        eng._managed_dir_test = tmp3
        eng._engram_exe = lambda _ctx: ""
        eng._latest_version = lambda: "9.9.9"          # versión inexistente
        asset_known, _iz = eng._plat_asset(eng._KNOWN_VERSION)
        blob_k = _make_asset(_is_zip, [("engram", b"KNOWNBIN")])
        checks_k = f"{hashlib.sha256(blob_k).hexdigest()}  {asset_known}\n"

        def dl_only_known(url, timeout=60):
            if "/v9.9.9/" in url:
                raise RuntimeError("404 Not Found")     # la versión inventada no existe
            if url.endswith("checksums.txt"):
                return checks_k.encode("utf-8")
            return blob_k
        eng._http_download = dl_only_known
        pf = eng.install({})
        check(bool(pf) and os.path.exists(pf) and open(pf, "rb").read() == b"KNOWNBIN",
              "install: si la última versión falla, cae a _KNOWN_VERSION")

        eng._managed_bin_dir = old_mbd
    finally:
        eng._engram_exe, eng._go_install = old_exe, old_go
        eng._http_download, eng._latest_version = old_dl, old_ver


def test_engram_install_cli_respeta_autoinstall():
    import backend.core.engram_bridge as eng
    import backend.core.config as cfg
    old_install, old_installed = eng.install, eng.installed
    old_get = cfg.settings.get
    try:
        # engram_autoinstall desactivado -> NO instala, sale 0
        called = {"n": 0}

        def install_spy(*a, **k):
            called["n"] += 1
            return ""
        eng.install = install_spy
        eng.installed = lambda _ctx: False
        cfg.settings.get = (lambda key, default=None:
                            False if key == "engram_autoinstall" else old_get(key, default))
        rc = eng.install_cli()
        check(rc == 0 and called["n"] == 0,
              "install_cli: engram_autoinstall=False -> no instala y sale 0")

        # camino POSITIVO: autoinstall activo y no instalado -> SÍ instala
        called["n"] = 0
        cfg.settings.get = (lambda key, default=None:
                            True if key == "engram_autoinstall" else old_get(key, default))

        def install_ok(*a, **k):
            called["n"] += 1
            return "/ruta/engram"
        eng.install = install_ok
        rc2 = eng.install_cli()
        check(rc2 == 0 and called["n"] == 1,
              "install_cli: autoinstall=True y sin instalar -> instala y sale 0")

        # respeta ⚙ engram_exe: installed() debe recibir un ctx CON settings (no {})
        # para que una ruta personalizada cuente como «ya instalado» y no reinstale.
        seen = {"ctx": None}

        def installed_spy(ctx):
            seen["ctx"] = ctx
            return True
        eng.installed = installed_spy
        called["n"] = 0
        eng.install = install_ok
        rc3 = eng.install_cli()
        check(rc3 == 0 and called["n"] == 0, "install_cli: si installed()=True -> no instala")
        check(isinstance(seen["ctx"], dict) and "settings" in seen["ctx"],
              "install_cli: pasa settings reales a installed() (respeta ⚙ engram_exe)")
    finally:
        eng.install, eng.installed = old_install, old_installed
        cfg.settings.get = old_get


def test_engram_maybe_install_background():
    import backend.core.engram_bridge as eng
    old_install, old_installed = eng.install, eng.installed

    async def run():
        called = {"n": 0}

        def install_spy(_ctx):
            called["n"] += 1
            return ""
        eng.install = install_spy

        # ya instalado -> no llama a install
        eng.installed = lambda _ctx: True
        await eng.maybe_install_background({"settings": _FakeSettings({})})
        check(called["n"] == 0, "maybe_install_background: ya instalado -> no instala")

        # no instalado pero autoinstall desactivado -> no llama a install
        eng.installed = lambda _ctx: False
        await eng.maybe_install_background({"settings": _FakeSettings({"engram_autoinstall": False})})
        check(called["n"] == 0, "maybe_install_background: autoinstall=False -> no instala")

        # camino POSITIVO: no instalado + autoinstall activo -> SÍ instala (en un hilo)
        eng.installed = lambda _ctx: False
        await eng.maybe_install_background({"settings": _FakeSettings({"engram_autoinstall": True})})
        check(called["n"] == 1, "maybe_install_background: no instalado + autoinstall -> instala")

    try:
        asyncio.run(run())
    finally:
        eng.install, eng.installed = old_install, old_installed


def test_engram_exe_encuentra_managed_dir():
    """El binario instalado por nexus en ~/.engram/bin debe detectarse."""
    import os
    import backend.core.engram_bridge as eng
    tmp = Path(tempfile.mkdtemp())
    mbd = tmp / ".engram" / "bin"
    mbd.mkdir(parents=True)
    exe = mbd / ("engram.exe" if eng.sys.platform.startswith("win") else "engram")
    exe.write_text("bin", encoding="utf-8")
    old_mbd, old_which = eng._managed_bin_dir, eng.shutil.which
    try:
        eng._managed_bin_dir = lambda: str(mbd)
        eng.shutil.which = lambda _n: None
        found = eng._engram_exe({})
        check(found == str(exe), f"_engram_exe: encuentra el binario en ~/.engram/bin ({found})")
    finally:
        eng._managed_bin_dir, eng.shutil.which = old_mbd, old_which


if __name__ == "__main__":
    tests = [test_engram_exe_deteccion, test_base_url_y_puerto, test_alive_cached,
             test_ensure_up_ya_vivo_no_lanza_nada, test_ensure_up_no_instalado,
             test_ensure_up_autostart_desactivado, test_ensure_up_lanza_y_espera_y_no_relanza_en_rafaga,
             test_save, test_search, test_context, test_count_no_arranca_el_servidor_solo_para_contar,
             test_status_sync_puro, test_engram_routing, test_engram_no_colisiona_con_memoria_personal,
             test_engram_handle_status, test_engram_handle_save, test_engram_handle_search_y_context,
             test_engram_settings_defaults,
             test_engram_plat_asset, test_engram_sha256_ok, test_engram_extract,
             test_engram_install_flow, test_engram_install_cli_respeta_autoinstall,
             test_engram_maybe_install_background, test_engram_exe_encuentra_managed_dir]
    for t in tests:
        print(f"· {t.__name__}")
        try:
            t()
        except Exception as e:
            _fail.append(f"{t.__name__} EXCEPCIÓN: {type(e).__name__}: {e}")
            print("  EXCEPCIÓN:", type(e).__name__, e)
    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    sys.exit(1 if _fail else 0)
