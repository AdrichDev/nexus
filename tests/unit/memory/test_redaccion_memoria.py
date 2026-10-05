# -*- coding: utf-8 -*-
"""Los puntos de escritura de memoria NO guardan secretos en claro.

Cubre: Postgres (`pg.remember`), RAG (`rag.add`, camino Postgres y almacén local),
memoria operativa (`opmem.remember`), puente Engram (`save`) y notas
(`graph.write_note`, `graph.append_daily`). Todo con dobles: ninguna escritura
real, ni BD, ni red, ni data/ de producción. Nivel M.

Ejecutar: python tests/unit/memory/test_redaccion_memoria.py
"""
import asyncio
import importlib
import os
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
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
        print("  FALLO:", msg)


mem = importlib.import_module("backend.core.dominio.memory")
rag = importlib.import_module("backend.core.dominio.rag")
opmem = importlib.import_module("backend.core.dominio.opmem")
bridge = importlib.import_module("backend.core.infraestructura.engram_bridge")
secretos = importlib.import_module("backend.core.comun.secretos")

SECRETO = "Sup3rSecreta99xyz"
TEXTO = f"nota de prueba password={SECRETO} y nada más"
OCULTO = secretos.OCULTO


def test_pg_remember_redacta():
    capturado = []
    pg = mem.pg
    orig = (pg._rows, pg._embed, pg._indice_huella_existe)
    try:
        pg._rows = lambda sql, params=(): (capturado.append((sql, params)) or [])
        pg._embed = lambda c: capturado.append(("embed", (c,))) or None
        pg._indice_huella_existe = lambda: False
        pg.remember(TEXTO, kind="note")
    finally:
        pg._rows, pg._embed, pg._indice_huella_existe = orig
    vistos = " ".join(str(p) for _s, ps in capturado for p in (ps if isinstance(ps, (list, tuple)) else (ps,)))
    check(SECRETO not in vistos, "pg.remember: el secreto no llega a la BD ni al embedding")
    check(OCULTO in vistos and "nota de prueba" in vistos, "pg.remember: se guarda el resto del texto con la marca")


def test_rag_add_redacta_en_postgres_y_local():
    guardado = []

    class FakePg:
        def remember(self, text, kind="note", tags=None, **kw):
            guardado.append(text)
            return {"id": 1, "duplicado": False}

    orig = rag._pg
    try:
        rag._pg = lambda: FakePg()
        asyncio.run(rag.add(TEXTO, kind="fact"))
    finally:
        rag._pg = orig
    check(guardado and SECRETO not in guardado[0] and OCULTO in guardado[0],
          "rag.add (camino Postgres): redacta antes de guardar")

    local = []
    o_pg, o_load, o_append, o_embed = rag._pg, rag._load, rag._append, rag.embed

    async def _sin_vec(_t):
        return None

    try:
        rag._pg = lambda: None
        rag._load = lambda: []
        rag._append = lambda rec: local.append(rec)
        rag.embed = _sin_vec
        asyncio.run(rag.add(TEXTO, kind="knowledge"))
    finally:
        rag._pg, rag._load, rag._append, rag.embed = o_pg, o_load, o_append, o_embed
    check(local and SECRETO not in str(local[0]) and OCULTO in local[0]["text"],
          "rag.add (almacén local): redacta antes de guardar")


def test_opmem_remember_redacta():
    guardados = []
    o_load, o_save = opmem._load, opmem._save
    try:
        opmem._load = lambda: []
        opmem._save = lambda items: guardados.append(items)
        rec = opmem.remember(f"siempre usa la clave password={SECRETO} al desplegar")
    finally:
        opmem._load, opmem._save = o_load, o_save
    check(rec and SECRETO not in str(rec) and OCULTO in rec.get("text", ""),
          "opmem.remember: la regla guardada no lleva el secreto")
    check(guardados and SECRETO not in str(guardados), "opmem.remember: lo persistido no lleva el secreto")


def test_engram_save_redacta():
    enviados = []

    class _Resp:
        status_code = 201

        def json(self):
            return {"id": 7}

    async def _up(_ctx):
        return True

    async def _sesion(_url):
        return None

    async def _post(url, json=None, timeout=8):
        enviados.append(json)
        return _Resp()

    o = (bridge.ensure_up, bridge._ensure_session, bridge._http_post, bridge._base_url)
    try:
        bridge.ensure_up, bridge._ensure_session, bridge._http_post = _up, _sesion, _post
        bridge._base_url = lambda ctx: "http://127.0.0.1:0"
        asyncio.run(bridge.save(None, f"clave password={SECRETO}", TEXTO))
    finally:
        bridge.ensure_up, bridge._ensure_session, bridge._http_post, bridge._base_url = o
    check(enviados and SECRETO not in str(enviados), "engram save: ni el título ni el contenido llevan el secreto")
    check(enviados and OCULTO in enviados[0]["content"], "engram save: el contenido lleva la marca")


def test_notas_redactan():
    tmp = Path(tempfile.mkdtemp(prefix="nexus_redaccion_notas_test_"))
    o_mem, o_daily = mem.MEMORY_DIR, mem.DAILY_DIR
    try:
        mem.MEMORY_DIR = tmp
        mem.DAILY_DIR = tmp / "daily"
        mem.DAILY_DIR.mkdir(parents=True, exist_ok=True)
        mem.graph.write_note("nota secreta", TEXTO)
        mem.graph.append_daily(TEXTO)
        todo = "".join(f.read_text(encoding="utf-8") for f in tmp.rglob("*.md"))
    finally:
        mem.MEMORY_DIR, mem.DAILY_DIR = o_mem, o_daily
    check(SECRETO not in todo, "graph.write_note / append_daily: ningún secreto en las notas")
    check(OCULTO in todo and "nota de prueba" in todo, "notas: se conserva el texto con la marca")


def test_recuerda_avisa_cuando_oculta_un_secreto():
    brain = importlib.import_module("backend.core.aplicacion.brain")
    guardado = []

    async def _add(text, kind="knowledge", meta=None, dedup=True):
        guardado.append(text)
        return True

    orig = rag.add
    try:
        rag.add = _add
        r = asyncio.run(brain.process(f"recuerda que mi password={SECRETO} sirve para el servidor"))
        r_ok = asyncio.run(brain.process("recuerda que mi color favorito es el azul"))
    finally:
        rag.add = orig
    check(SECRETO not in r["reply"], "recuerda: la respuesta no repite el secreto")
    check(guardado and SECRETO not in guardado[0], "recuerda: al RAG llega el hecho sin el secreto")
    check("oculta" in r["reply"].lower() and "secreto" in r["reply"].lower(),
          "recuerda: la respuesta avisa de que se ocultó un secreto")
    check("oculta" not in r_ok["reply"].lower(), "recuerda: sin secretos, la respuesta no cambia")


if __name__ == "__main__":
    for name, t in sorted(globals().items()):
        if name.startswith("test_") and callable(t):
            print(f"-- {t.__name__}")
            try:
                t()
            except Exception as exc:                          # noqa: BLE001
                _fail.append(f"{t.__name__}: EXCEPCIÓN {type(exc).__name__}: {exc}")
                print("  EXCEPCIÓN:", exc)
    print(f"\n{_pass} OK, {len(_fail)} fallo(s)")
    if _fail:
        for f in _fail:
            print(" -", f)
        sys.exit(1)
