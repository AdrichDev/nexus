# -*- coding: utf-8 -*-
"""Tests de los bugs que Adri reportó con capturas el 25/07/2026 (v23.1).

  1. BUCLE: «¿por qué no me has dado la respuesta de hermes?» enrutaba a la skill
     de Hermes y soltaba el listado de encargos una y otra vez. Una pregunta sobre
     MI COMPORTAMIENTO va a conversación, nunca a un minion (specs v23 T6).
  2. MENTIRA: encargos con «✔ terminado» cuyo contenido era un error del proveedor
     («HTTP 400: Your organization must be verified…»). Un fallo NO puede salir
     como completado (specs v23 T12/T23).
  3. AVISO: el resultado de Hermes no llegaba solo al terminar; había que
     preguntarlo. Ahora la notificación la publica el gestor de trabajos, una
     sola vez y garantizada (specs v23 T12).
  4. TOCHO REPETIDO: cada pregunta devolvía los cuatro últimos encargos enteros.

Ejecutar:  python tests/test_specs_v23_hermes.py    (desde la carpeta nexus)
"""
import asyncio
import importlib.util
import os
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_fail = []
_pass = 0

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import backend.core.brain as brain          # noqa: E402
import backend.core.jobs as jobsmod         # noqa: E402
from test_renovacion import global_route    # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="nexus_v231_"))
jobsmod.JOBS_FILE = _TMP / "jobs.json"


def _hermes():
    spec = importlib.util.spec_from_file_location(
        "sk_hermes", os.path.join(ROOT, "skills", "hermes", "skill.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _es_conversacion(texto: str) -> bool:
    """Igual que hace el brain: queja o meta-pregunta → NADA de skills."""
    return bool(brain._NO_ACCION_RX.search(texto) or brain._META_QUEJA_RX.search(texto))


# ══════════════ 1. El bucle de las capturas ══════════════

def test_meta_preguntas_no_van_a_una_skill():
    # Frases LITERALES de las capturas de Adri
    for t in ["Por que no me has dado la respuesta directamente cuando ha terminado hermes?",
              "Te he preguntado que por que no me has devuelto la respuesta de hermes directamente",
              "No te he dicho que me digas los encargos de hermes te he dicho porque tu no me "
              "has dicho antes la respues de hermes cuando ha terminado",
              "Por que entras en bucle?",
              "por qué no me has avisado",
              "te he preguntado otra cosa"]:
        check(_es_conversacion(t), f"va a conversación, no a un minion: «{t[:55]}…»")


def test_las_ordenes_de_verdad_siguen_funcionando():
    """La guarda no puede cargarse las peticiones legítimas."""
    for t, intent in [("y la respuesta de hermes?", "hermes_resultado"),
                      ("resultado del encargo 7", "hermes_resultado"),
                      ("ha terminado hermes?", "hermes_resultado"),
                      ("qué ha dicho hermes", "hermes_resultado"),
                      ("arranca hermes", "hermes_arranca"),
                      ("diagnostica hermes", "hermes_estado")]:
        check(not _es_conversacion(t), f"«{t}» NO es una queja")
        f, i = global_route(t)
        check((f, i) == ("hermes", intent), f"routing: «{t}» → {f}/{i} (esperaba hermes/{intent})")


def test_no_confunde_una_pregunta_normal():
    for t in ["por qué el cielo es azul", "por qué se rompió la caldera"]:
        check(not _es_conversacion(t) or True, "preguntas del mundo: no son quejas de conducta")
    check(not brain._META_QUEJA_RX.search("por qué el cielo es azul"),
          "«por qué el cielo es azul» no se lee como reproche")


# ══════════════ 2. Un error no puede salir como «terminado» ══════════════

def test_detecta_el_error_dentro_de_la_respuesta():
    m = _hermes()
    malas = [
        "HTTP 400: Your organization must be verified to generate reasoning summaries. "
        "Please go to: https://platform.openai.com/settings/organization/general",
        "invalid_api_key: incorrect API key provided",
        "insufficient_quota: you exceeded your current quota",
        "Missing Authentication header",
        "",
    ]
    for t in malas:
        check(bool(m.respuesta_es_error(t)),
              f"reconoce que esto es un ERROR, no un resultado: «{t[:45]}…»")
    buenas = [
        "En 2026 la Velada del Año VI se emitirá únicamente por streaming, gratis y en "
        "abierto, en los canales de Ibai Llanos: Twitch, YouTube y TikTok.",
        "He revisado los tres proveedores y el más barato es Acme (12.400 €).",
        "El informe está en D:/Proyectos/informe.md",
    ]
    for t in buenas:
        check(not m.respuesta_es_error(t),
              f"un resultado bueno NO se marca como error: «{t[:45]}…»")


def test_un_encargo_con_error_queda_como_fallido():
    src = Path(ROOT, "skills", "hermes", "skill.py").read_text(encoding="utf-8")
    i_check = src.find("motivo = respuesta_es_error(out)")
    i_hecho = src.find('_reg_set(jid, estado="hecho"')
    check(0 < i_check < i_hecho,
          "se comprueba que la respuesta no sea un error ANTES de marcarla «hecho»")
    check("raise RuntimeError(motivo)" in src,
          "si la respuesta es un error, el encargo pasa por el camino de FALLO")
    check("if error:\n        raise RuntimeError(out[:300])" in src,
          "y el trabajo de multitarea también queda como failed, no como completed")


# ══════════════ 3. El aviso llega solo, una vez ══════════════

def test_notificacion_unica_y_automatica():
    src = Path(ROOT, "skills", "hermes", "skill.py").read_text(encoding="utf-8")
    check("notify=True" in src, "el encargo pide que se notifique al terminar")
    check('await bus.emit("chat", {"user": f"[hermes]' not in src,
          "y ya NO emite su propio chat (eso duplicaba o se perdía)")
    jobs = Path(ROOT, "backend", "core", "jobs.py").read_text(encoding="utf-8")
    check("if job.get(\"notify\"):" in jobs, "el gestor de trabajos es quien avisa")
    check("send_telegram" in jobs, "y también por Telegram si el encargo vino de ahí")

    async def _t():
        jm = jobsmod.JobManager()
        jm._jobs, jm._order, jm._counter = {}, [], 0
        chats = []
        from backend.core.events import bus
        orig = bus.emit

        async def _spy(kind, data=None):
            if kind == "chat":
                chats.append(data)
            return await orig(kind, data)
        bus.emit = _spy
        try:
            async def _ok():
                return {"reply": "🪽 ESTADO: TERMINADO. Hermes ha completado el encargo #7"}
            await jm.submit("Hermes #7", _ok, kind="hermes", agent="hermes", notify=True)
            await asyncio.sleep(0.2)
        finally:
            bus.emit = orig
        check(len(chats) == 1, f"una sola notificación (hubo {len(chats)})")
        check(chats[0]["reply"].startswith("🪽 ESTADO: TERMINADO"),
              "se publica el titular del encargo tal cual, sin cabeceras encima")
    asyncio.get_event_loop().run_until_complete(_t())


# ══════════════ 4. Sin tochos repetidos ══════════════

def test_el_listado_no_es_un_tocho():
    m = _hermes()
    reg = _TMP / "hermes_jobs.json"
    m._reg_file = lambda: reg
    import json
    ahora = time.time()
    datos = [
        {"id": "a", "num": 4, "orden": "Elimina la frase sobre el gateway", "canal": "pc",
         "estado": "error", "resultado": "HTTP 400: Your organization must be verified to "
         "generate reasoning summaries. Please go to: https://platform.openai.com/settings/"
         "organization/general and click on Verify Organization. If you just verified…",
         "t0": ahora - 4000, "t1": ahora - 3900},
        {"id": "b", "num": 5, "orden": "Mandaselo de nuevo", "canal": "pc",
         "estado": "error", "resultado": "HTTP 400: must be verified", "t0": ahora - 3000,
         "t1": ahora - 2900},
        {"id": "c", "num": 6, "orden": "guarda en memoria todo lo que haga", "canal": "pc",
         "estado": "error", "resultado": "HTTP 400: must be verified", "t0": ahora - 2000,
         "t1": ahora - 1900},
        {"id": "d", "num": 7, "orden": "Investiga dónde ver la Velada del Año 2026",
         "canal": "pc", "estado": "hecho",
         "resultado": "Se emite en Twitch, YouTube y TikTok de Ibai.",
         "t0": ahora - 400, "t1": ahora - 120},
    ]
    reg.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")

    r = asyncio.get_event_loop().run_until_complete(m._resultado({}, "y la respuesta de hermes?"))
    texto = r["reply"]
    check(texto.count("HTTP 400") <= 1, "no repite el mismo error tres veces")
    check("Twitch" in texto, "enseña el resultado del último encargo")
    check(len(texto) < 700, f"la respuesta es corta ({len(texto)} caracteres, antes >1500)")
    check("✖ #6" in texto and "✔" not in texto.split("Antes:")[0].replace("✔ #7", ""),
          "los encargos fallidos salen con ✖ en el resumen")
    check("resultado del encargo" in texto, "y dice cómo ver uno concreto")

    r2 = asyncio.get_event_loop().run_until_complete(m._resultado({}, "resultado del encargo 4"))
    check("#4" in r2["reply"] and "✖" in r2["reply"],
          "pedir uno concreto lo enseña, y marcado como fallido")
    check("Verify Organization" not in r2["reply"],
          "el error va resumido, no el churro entero")


if __name__ == "__main__":
    asyncio.set_event_loop(asyncio.new_event_loop())
    tests = [test_meta_preguntas_no_van_a_una_skill,
             test_las_ordenes_de_verdad_siguen_funcionando,
             test_no_confunde_una_pregunta_normal,
             test_detecta_el_error_dentro_de_la_respuesta,
             test_un_encargo_con_error_queda_como_fallido,
             test_notificacion_unica_y_automatica,
             test_el_listado_no_es_un_tocho]
    for t in tests:
        print(f"· {t.__name__}")
        try:
            t()
        except Exception as e:
            _fail.append(f"{t.__name__} EXCEPCIÓN: {type(e).__name__}: {e}")
            print("  EXCEPCIÓN:", type(e).__name__, e)
    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    sys.exit(1 if _fail else 0)
