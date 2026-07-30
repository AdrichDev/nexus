# -*- coding: utf-8 -*-
"""Tests de las specs v20 — contra el CÓDIGO REAL del disco.

Cubren:
  M8  contexto multi-turno (backend/core/context.py + integración en brain)
  M4  cadenas secuenciales (_split_chain en brain: «y luego», «después»…)
  M6  revisión semanal (backend/core/review.py + intent weekly del coach)
  M7  perfil del operador + consolidación nocturna (backend/core/profile.py
      + intent profile de memory_graph)
  M9  panel HOY (briefing.today_payload + /api/today + vista del HUD)

Ejecutar:  python tests/test_specs_v20.py    (desde la carpeta nexus)
"""
import ast
import asyncio
import datetime as dt
import importlib.util
import json
import os
import re
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ══════════════ M8: contexto multi-turno ══════════════

def test_context_note_y_resolve():
    import backend.core.context as cx
    cx.clear()
    # sin contexto → no resuelve nada
    check(cx.resolve("abre el segundo") is None, "sin contexto → None")
    # lista numerada tipo chrome
    cx.note_reply("chrome", "tabs", "🌐 3 pestañas abiertas:\n  1. YouTube - vídeos  ·  youtube.com\n  2. Gmail  ·  mail.google.com\n  3. Marca  ·  marca.com")
    check(cx.resolve("resume la segunda") == "resume la pestaña 2", "chrome: resume la segunda")
    check(cx.resolve("cierra la 3") == "cierra la pestaña 3", "chrome: cierra la 3")
    check(cx.resolve("cambia a la primera") == "cambia a la pestaña 1", "chrome: cambia a la primera")
    check(cx.resolve("resume el último") == "resume la pestaña 3", "chrome: el último → nº mayor")
    # no interferir si ya nombra su dominio o la frase es larga
    check(cx.resolve("resume la pestaña 2") is None, "ya dice 'pestaña' → no toca")
    check(cx.resolve("x" * 80 + " el segundo") is None, "frase larga → no toca")
    # contactos (viñetas → orden implícito)
    cx.note_reply("telefono", "list_contacts",
                  "📇 Mi agenda (2):\n  • Mamá → +34612345678\n  • Rubén → +34699112233")
    check(cx.resolve("llama al segundo") == "llama a Rubén", "telefono: llama al segundo")
    check(cx.resolve("borra el segundo") is None, "telefono: verbo no soportado → None")
    # informes
    cx.note_reply("research", "history",
                  "📚 Informes:\n  • proveedores-china-2026 — 20/07\n  • mercado-calcetines — 24/07")
    check(cx.resolve("abre el segundo") == "abre el informe de mercado-calcetines",
          "research: abre el segundo")
    # vigilancias (#N)
    cx.note_reply("vigilancias", "list",
                  "👁 Vigilando 2:\n  🌐 #1 web: https://a.com\n  💶 #2 precio: https://b.com")
    check(cx.resolve("borra la segunda") == "borra la vigilancia 2", "vigilancias: borra la 2ª")
    # hermes
    cx.note_reply("hermes", "hermes_resultado",
                  "🪽 Encargos:\n  ✔ #1 «investiga» (hecho)\n  ⏳ #2 «compara» — en ello")
    check(cx.resolve("el segundo") == "resultado del encargo 2", "hermes: el segundo")
    # tablero: sustitución del ordinal por el título
    cx.note_reply("tasks_board", "show",
                  "▸ PENDIENTES (2)\n  1. comprar tela\n  2. llamar al proveedor")
    check(cx.resolve("mueve la segunda a en progreso") == "mueve llamar al proveedor a en progreso",
          "tablero: ordinal → título en la frase")
    # TTL caducado
    cx._state_for("pc")["ts"] = time.time() - 9999
    check(cx.resolve("el segundo") is None, "contexto caducado → None")
    cx.clear()


def test_context_anti_secuestro():
    """Revisión opus: frases cotidianas con ordinal NO deben secuestrarse."""
    import backend.core.context as cx
    cx.clear()
    cx.note_reply("chrome", "tabs", "1. YouTube · yt.com\n2. Gmail · mail.com\n3. Marca · marca.com")
    for frase in ["pon la primera de Bad Bunny", "abre el segundo cajón",
                  "ponme la tercera canción", "dame el primero que veas",
                  "reproduce la primera lista", "resume la 99"]:
        check(cx.resolve(frase) is None, f"anti-secuestro chrome: «{frase}» → None")
    cx.note_reply("hermes", "hermes_resultado", "✔ #1 «a»\n⏳ #2 «b»")
    check(cx.resolve("pon la primera de Bad Bunny") is None, "anti-secuestro hermes")
    check(cx.resolve("dame la 8") is None, "hermes: fuera de rango → None")
    cx.note_reply("tasks_board", "show", "1. comprar leche\n2. llamar proveedor")
    check(cx.resolve("pon la primera de Bad Bunny") is None, "anti-secuestro tablero")
    check(cx.resolve("mueve la segunda a en progreso") == "mueve llamar proveedor a en progreso",
          "tablero: la referencia legítima sigue funcionando")
    # aislamiento por canal (revisión opus): la lista del PC no vale para telegram
    check(cx.resolve("cierra la 2", channel="telegram") is None,
          "canal: telegram no hereda el contexto del PC")
    cx.note_reply("chrome", "tabs", "1. A · a.com\n2. B · b.com", channel="telegram")
    check(cx.resolve("cierra la 2", channel="telegram") == "cierra la pestaña 2",
          "canal: telegram resuelve contra SU lista")
    cx.clear()


def test_board_sello_completado():
    """Revisión opus: la revisión semanal cuenta por fecha de COMPLETADO."""
    import backend.core.board as board
    import datetime as _dt
    import json as _json, tempfile as _tf
    from pathlib import Path as _P
    tmpb = _P(_tf.mkdtemp()) / "board.json"
    tmpb.write_text(_json.dumps([{"id": "x1", "title": "tarea antigua",
                                  "state": "pendiente", "created": "2026-06-01",
                                  "due": None, "priority": "media"}]), encoding="utf-8")
    old_bf = board.BOARD_FILE
    board.BOARD_FILE = tmpb
    try:
        t = board.move_task("tarea antigua", "completada")
        check(t and t.get("completed") == _dt.date.today().isoformat(),
              "move_task a completada sella la fecha")
        import backend.core.review as review
        old_dd = review.DATA_DIR
        review.DATA_DIR = tmpb.parent
        try:
            txt = review.build_weekly_review(_dt.date.today())
            check("Completadas: 1" in txt,
                  "review cuenta la completada ESTA semana aunque sea vieja")
        finally:
            review.DATA_DIR = old_dd
    finally:
        board.BOARD_FILE = old_bf


def test_context_integrado_en_brain():
    src = open(os.path.join(ROOT, "backend", "core", "brain.py"), encoding="utf-8").read()
    check("_mturn.resolve" in src, "brain: llama a context.resolve antes del router")
    check("_mturn.note_reply" in src, "brain: registra las listas de las skills")


# ══════════════ M4: cadenas secuenciales ══════════════

def _brain_ns(names):
    """Extrae funciones/constantes REALES de brain.py sin importar el módulo."""
    tree = ast.parse(open(os.path.join(ROOT, "backend", "core", "brain.py"),
                          encoding="utf-8").read())
    keep = []
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names:
            keep.append(n)
        if isinstance(n, ast.Assign) and any(getattr(t, "id", "") in names
                                             for t in n.targets):
            keep.append(n)
    ns = {"re": re, "__import__": __import__}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "brain.py", "exec"), ns)
    return ns


def test_split_chain():
    ns = _brain_ns({"_CHAIN_RX", "_split_chain"})
    sc = ns["_split_chain"]
    steps = sc("investiga los precios del algodón y luego crea la tarea comprar muestras "
               "y después envía un whatsapp a Rubén diciendo listo")
    check(len(steps) == 3, f"cadena de 3 pasos (obtuve {len(steps)}: {steps})")
    check(steps[0].startswith("investiga") and steps[2].startswith("envía"),
          "cadena: pasos en orden")
    check(sc("pon rock y jazz") == [], "'y' a secas NO parte")
    check(sc("investiga el mercado de tela y algodón") == [], "sin conector → no hay cadena")
    check(sc("haz una captura, luego apaga la música") != [], "', luego' sí parte")
    src = open(os.path.join(ROOT, "backend", "core", "brain.py"), encoding="utf-8").read()
    check("_chain_job" in src and 'kind="cadena"' in src,
          "brain: la cadena corre como trabajo numerado en 2º plano")


# ══════════════ M6: revisión semanal ══════════════

def test_review():
    import backend.core.board as board
    import backend.core.review as review
    now = dt.datetime(2026, 7, 26, 19, 30)          # domingo
    check(review.review_due(now, True, 6, "19:00", "") is True, "due: domingo tarde → sí")
    check(review.review_due(now, True, 6, "19:00", "2026-W30") is False, "due: ya enviada esta semana")
    check(review.review_due(now, True, 5, "19:00", "") is False, "due: no es el día → no")
    check(review.review_due(now, False, 6, "19:00", "") is False, "due: desactivada → no")
    check(review.review_due(now, True, 6, "mal", "") is False, "due: hora inválida → no")
    # build con tablero temporal
    tmpb = Path(tempfile.mkdtemp()) / "board.json"
    today = dt.date(2026, 7, 26)
    tmpb.write_text(json.dumps([
        {"id": "a", "title": "vieja estancada", "state": "pendiente",
         "created": "2026-06-01", "due": None, "priority": "media"},
        {"id": "b", "title": "hecha esta semana", "state": "completada",
         "created": "2026-07-22", "due": None, "priority": "media"},
        {"id": "c", "title": "vencida", "state": "pendiente",
         "created": "2026-07-20", "due": "2026-07-23", "priority": "alta"},
    ]), encoding="utf-8")
    old_bf = board.BOARD_FILE
    board.BOARD_FILE = tmpb
    old_dd = review.DATA_DIR
    review.DATA_DIR = tmpb.parent
    try:
        txt = review.build_weekly_review(today)
        check("REVISIÓN SEMANAL" in txt, "review: cabecera")
        check("vieja estancada" in txt and "🪦" in txt, "review: detecta la tarea muerta +14 días")
        check("vencida" in txt and "🔴" in txt, "review: detecta la vencida")
        check("Completadas: 1" in txt, "review: cuenta las completadas de la semana")
    finally:
        board.BOARD_FILE = old_bf
        review.DATA_DIR = old_dd
    sch = open(os.path.join(ROOT, "backend", "core", "scheduler.py"), encoding="utf-8").read()
    check("review.maybe_send" in sch, "scheduler: engancha la revisión semanal")


# ══════════════ M7: perfil + consolidación ══════════════

def test_profile_build():
    # v21 (fix a la queja de Adri: «quién soy» daba una ficha de estadísticas
    # robótica — tono/estilo, temas recurrentes, contadores de tareas/contactos/
    # informes...). build_profile() ahora es una respuesta CORTA y NATURAL: solo
    # confirma quién eres y, si acaso, un apunte breve de lo aprendido — NADA de
    # contadores ni de cabeceras/viñetas markdown crudas.
    import backend.core.profile as prof
    import backend.core.selflearn as selflearn

    class _FakeSettings:
        def __init__(self, name):
            self._name = name

        def get(self, key, default=None):
            return self._name if key == "operator_name" else default

    old_settings, old_op = prof.settings, selflearn.operator_profile
    try:
        # 1) nombre + perfil aprendido (markdown con cabeceras **X** y viñetas,
        # tal cual lo destila selflearn.retrain) -> prosa corrida, sin ficha.
        prof.settings = _FakeSettings("Adri")
        selflearn.operator_profile = lambda: (
            "**Tono y estilo**\n- Directo, sin rodeos, tutea\n\n"
            "**Temas y proyectos recurrentes**\n- NEXUS y la agencia\n\n"
            "**Preferencias y cosas a evitar**\n- Odia el relleno")
        txt = prof.build_profile()
        check("Adri" in txt, "perfil natural: menciona el nombre")
        check("**" not in txt, "perfil natural: sin cabeceras markdown crudas")
        check("Tono y estilo" not in txt and "Temas y proyectos recurrentes" not in txt,
              "perfil natural: sin las etiquetas de sección tal cual")
        check("\n-" not in txt and "\n•" not in txt,
              "perfil natural: sin viñetas sueltas (es prosa corrida)")
        check(not any(m in txt for m in
                     ("Agenda:", "Vigilancias activas:", "Encargos a Hermes:",
                      "Informes generados:", "Memoria en grafo:", "Tablero:")),
              "perfil natural: NO es una ficha de estadísticas (sin contadores)")
        check(len(txt) < 320, "perfil natural: respuesta corta, no un informe")
        check("🧬" not in txt, "perfil natural: sin la cabecera vieja de ficha")

        # 2) nombre configurado, SIN perfil aprendido todavía -> breve y amable,
        # no un hueco ni un error.
        selflearn.operator_profile = lambda: ""
        txt2 = prof.build_profile()
        check("Adri" in txt2, "perfil sin aprendizaje: menciona el nombre igual")
        check(len(txt2) < 220, "perfil sin aprendizaje: sigue siendo breve")

        # 3) sin nombre configurado y sin perfil -> no revienta, respuesta breve
        prof.settings = _FakeSettings("")
        txt3 = prof.build_profile()
        check(isinstance(txt3, str) and len(txt3) > 0, "perfil vacío: no revienta")
        check(len(txt3) < 220, "perfil vacío: sigue siendo breve")

        # 4) selflearn.operator_profile() falla (excepción) -> no rompe build_profile
        def _boom():
            raise RuntimeError("db offline")
        selflearn.operator_profile = _boom
        prof.settings = _FakeSettings("Adri")
        txt4 = prof.build_profile()
        check(isinstance(txt4, str) and "Adri" in txt4,
              "perfil: si selflearn falla, sigue respondiendo sin reventar")
    finally:
        prof.settings = old_settings
        selflearn.operator_profile = old_op


def test_perfil_natural_helper():
    # _perfil_natural() es la que limpia el markdown; se prueba aislada.
    import backend.core.profile as prof
    limpio = prof._perfil_natural("**Tono**\n- muy directo\n\n**Temas**\n- NEXUS")
    check("**" not in limpio, "_perfil_natural: quita cabeceras **")
    check("- " not in limpio, "_perfil_natural: quita viñetas")
    check("directo" in limpio and "NEXUS" in limpio,
          "_perfil_natural: conserva el contenido")
    check(prof._perfil_natural("") == "", "_perfil_natural: vacío -> vacío")
    check(prof._perfil_natural(None) == "", "_perfil_natural: None -> vacío (no revienta)")
    largo = "**X**\n- " + ("palabra " * 200)
    check(len(prof._perfil_natural(largo)) <= 260, "_perfil_natural: respeta el tope de longitud")

    # (hallazgo de la revisión opus) la negrita DENTRO de una frase — una
    # expresión citada o una palabra realzada — se DESENNEGRECE, no se borra:
    # antes el regex de cabecera se comía también el contenido de "**...**"
    # a mitad de frase y perdía justo lo importante (el propio dato aprendido).
    md = ('**Atajos y formas propias de pedir cosas**\n'
          '- **"está todo arrancado"**: quiere saber si los servicios están levantados\n'
          '- Prefiere respuestas **cortas** y directas\n')
    limpio2 = prof._perfil_natural(md)
    check('está todo arrancado' in limpio2,
          "_perfil_natural: conserva una expresión citada en negrita (no la borra)")
    check("cortas" in limpio2 and "directas" in limpio2,
          "_perfil_natural: conserva una palabra en negrita a mitad de frase")
    check("Atajos y formas propias de pedir cosas" not in limpio2,
          "_perfil_natural: la cabecera de sección (sin contenido propio) sí se descarta")
    check("**" not in limpio2, "_perfil_natural: sin marcadores ** sueltos en el resultado")

    # cabecera + contenido en la MISMA línea -> se queda el contenido, no la etiqueta
    limpio3 = prof._perfil_natural("**Tono y estilo**: cercano y directo, tutea siempre")
    check("cercano y directo" in limpio3, "_perfil_natural: cabecera+contenido en una línea conserva el contenido")
    check("Tono y estilo" not in limpio3, "_perfil_natural: cabecera+contenido en una línea descarta la etiqueta")

    # (hallazgo QA sonnet) negrita que ABRE la línea SIN guión de viñeta
    # delante («**Odia**...», sin «- »): el regex de viñeta [\-•*] también
    # casa con UN solo «*», así que si se aplicaba ANTES de desenvolver la
    # negrita se comía el primer «*» del «**» y dejaba un «*Odia**» roto sin
    # desenvolver. Tiene que salir «Odia» limpio, sin asteriscos sueltos.
    limpio4 = prof._perfil_natural(
        "**Preferencias y cosas a evitar**\n**Odia** que le interrumpan en reuniones\n")
    check("Odia que le interrumpan en reuniones" in limpio4,
          "_perfil_natural: negrita sin guión delante se desenvuelve entera, sin restos")
    check("*" not in limpio4, "_perfil_natural: ni un asterisco suelto en el resultado")

    # truncado por longitud: no debe partir una palabra por la mitad
    largo2 = "palabra_entera " * 40
    cortado = prof._perfil_natural(largo2, max_chars=50)
    check(cortado.endswith("…"), "_perfil_natural: marca con … cuando trunca")
    resto = cortado[:-1].strip()   # quita el "…" final
    check(resto == "" or resto.split(" ")[-1] == "palabra_entera",
          "_perfil_natural: el corte no deja una palabra partida a medias")


def test_consolidacion():
    import backend.core.memory as mem
    import backend.core.profile as prof
    tmp = Path(tempfile.mkdtemp())
    daily = tmp / "daily"
    daily.mkdir(parents=True)
    old_daily, old_memdir = mem.DAILY_DIR, mem.MEMORY_DIR
    mem.DAILY_DIR = daily
    mem.MEMORY_DIR = tmp
    ayer = (dt.datetime(2026, 7, 24, 5, 0) - dt.timedelta(days=1)).date()
    f = daily / f"{ayer.isoformat()}.md"
    try:
        now = dt.datetime(2026, 7, 24, 5, 0)
        check(prof.consolidation_pending(now) is False, "consolidación: sin diario → no")
        f.write_text("## Registro\n" + ("línea de conversación con datos. " * 20),
                     encoding="utf-8")
        check(prof.consolidation_pending(now) is True, "consolidación: diario fresco → sí")
        check(prof.consolidation_pending(dt.datetime(2026, 7, 24, 2, 0)) is False,
              "consolidación: antes de las 4h → no")
        # LLM falso
        import backend.core.llm as llm

        async def fake_ask(prompt, context=None, system=None):
            return "- decisión A\n- pendiente B", "mock"
        old_ask = llm.ask_llm
        llm.ask_llm = fake_ask
        try:
            ok = asyncio.run(prof.consolidate_daily(now))
        finally:
            llm.ask_llm = old_ask
        check(ok is True, "consolidación: ejecuta y devuelve True")
        check("<!--consolidado-->" in f.read_text(encoding="utf-8"),
              "consolidación: el diario queda marcado")
        notes = list(tmp.glob("resumen*.md"))
        check(len(notes) == 1 and "decisión A" in notes[0].read_text(encoding="utf-8"),
              "consolidación: nota resumen escrita")
        check(prof.consolidation_pending(now) is False,
              "consolidación: marcado → no repite")
    finally:
        mem.DAILY_DIR = old_daily
        mem.MEMORY_DIR = old_memdir
    sch = open(os.path.join(ROOT, "backend", "core", "scheduler.py"), encoding="utf-8").read()
    check("consolidate_daily" in sch, "scheduler: engancha la consolidación nocturna")


# ══════════════ M9: panel HOY ══════════════

def test_today_payload_y_hud():
    import backend.core.config as cfg
    import backend.core.briefing as bf
    tmp = Path(tempfile.mkdtemp())
    old_cfg, old_bf = cfg.DATA_DIR, bf.DATA_DIR
    cfg.DATA_DIR = tmp
    bf.DATA_DIR = tmp
    try:
        (tmp / "hermes_jobs.json").write_text(json.dumps(
            [{"num": 1, "estado": "hecho", "orden": "investiga tela"}]), encoding="utf-8")
        (tmp / "watchers.json").write_text(json.dumps(
            [{"num": 1, "tipo": "web", "objetivo": "https://x.com"}]), encoding="utf-8")
        (tmp / "reports").mkdir()
        (tmp / "reports" / "mercado-tela.md").write_text("# x", encoding="utf-8")
        d = asyncio.run(bf.today_payload())
        check(d["hermes"] and d["hermes"][0]["num"] == 1, "today: encargos presentes")
        check(d["vigilancias"] and d["vigilancias"][0]["tipo"] == "web", "today: vigilancias")
        check(d["informes"] == ["mercado-tela"], "today: informes recientes")
        check("fecha" in d and "tareas" in d and "clima" in d, "today: estructura completa")
    finally:
        cfg.DATA_DIR = old_cfg
        bf.DATA_DIR = old_bf
    app = open(os.path.join(ROOT, "backend", "app.py"), encoding="utf-8").read()
    check('"/api/today"' in app, "app: endpoint /api/today")
    idx = open(os.path.join(ROOT, "frontend", "index.html"), encoding="utf-8").read()
    # v23 (T16): la pantalla «Hoy» se ELIMINA del sidebar — su información se
    # redistribuye (tiempo al header, tareas a Tareas, trabajos a Multitarea).
    # El payload /api/today sigue vivo porque lo usan el móvil y el briefing.
    check('data-view="today"' not in idx, "HUD v23: la entrada «Hoy» ya no está en el nav")
    js_ = open(os.path.join(ROOT, "frontend", "js", "command.js"), encoding="utf-8").read()
    check("if (view === 'today') view = 'command';" in js_,
          "HUD v23: la ruta antigua de «Hoy» redirige, no rompe")
    js = open(os.path.join(ROOT, "frontend", "js", "command.js"), encoding="utf-8").read()
    check("views.today" in js and "loadToday" in js and "/api/today" in js,
          "HUD: vista Hoy con carga desde /api/today")


# ══════════════ Enrutado global de lo nuevo ══════════════

def test_routing_v20():
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    from test_renovacion import global_route
    for t, skill, intent in [
        ("revisión semanal", "coach", "weekly"),
        ("balance de la semana", "coach", "weekly"),
        ("mi perfil", "memory_graph", "profile"),
        ("quién soy", "memory_graph", "profile"),
        ("háblame de mí", "memory_graph", "profile"),
    ]:
        f, i = global_route(t)
        check((f, i) == (skill, intent), f"routing v20: '{t}' -> {f}/{i} (esperaba {skill}/{intent})")
    for t, skill, intent in [
        ("qué sabes de mí", "memory_graph", "list_knowledge"),
        ("qué me toca hoy", "coach", "briefing"),
        ("qué recuerdas de Rubén", "memory_graph", "recall"),
        ("resumen del día", "coach", "briefing"),
    ]:
        f, i = global_route(t)
        check((f, i) == (skill, intent), f"anti-robo v20: '{t}' -> {f}/{i} (esperaba {skill}/{intent})")


if __name__ == "__main__":
    tests = [test_context_note_y_resolve, test_context_anti_secuestro,
             test_board_sello_completado, test_context_integrado_en_brain,
             test_split_chain, test_review, test_profile_build,
             test_perfil_natural_helper, test_consolidacion,
             test_today_payload_y_hud, test_routing_v20]
    for t in tests:
        print(f"· {t.__name__}")
        try:
            t()
        except Exception as e:
            _fail.append(f"{t.__name__} EXCEPCIÓN: {type(e).__name__}: {e}")
            print("  EXCEPCIÓN:", type(e).__name__, e)
    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    sys.exit(1 if _fail else 0)
