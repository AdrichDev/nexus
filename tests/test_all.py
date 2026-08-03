# -*- coding: utf-8 -*-
"""Suite AMPLIA de tests unitarios de nexus — contra el CÓDIGO REAL del disco.
Cubre: routing de TODAS las skills + colisiones entre skills, planificador
(_LLMMatch), anti-eco, delegación a Hermes, helpers de TTS, domótica, memoria.

Ejecutar:  python tests/test_all.py       (desde la carpeta nexus)
"""
import importlib
import importlib.util
import os
import re
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_fail, _pass = [], 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


# -------- import resiliente: stubbea deps pesadas ausentes y reintenta --------
class _U:
    """Mock universal: invocable, encadenable, indexable e iterable — para que el
    import de un módulo real que USA una dependencia stubbeada no reviente."""
    def __call__(self, *a, **k):
        return _U()
    def __getattr__(self, _n):
        return _U()
    def __getitem__(self, _k):
        return _U()
    def __iter__(self):
        return iter(())


def _stub(name):
    m = types.ModuleType(name)
    m.__getattr__ = lambda _n: _U()
    sys.modules[name] = m


def _import_retry(loader):
    for _ in range(25):
        try:
            return loader()
        except ModuleNotFoundError as e:
            _stub(e.name)
    return loader()  # que reviente con el error real si no es un módulo ausente


def load_skill(folder):
    path = os.path.join(ROOT, "skills", folder, "skill.py")

    def _do():
        spec = importlib.util.spec_from_file_location(f"_sk_{folder}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    return _import_retry(_do)


def load_core(name):
    return _import_retry(lambda: importlib.import_module(f"backend.core.{name}"))


def patterns(mod):
    return {k: re.compile(v, re.IGNORECASE) for k, v in mod.SKILL["patterns"].items()}


def route_local(pats, text):
    for intent, rx in pats.items():
        if rx.search(text):
            return intent
    return None


# ================== 1) ROUTING por skill ==================
def test_routing_media():
    p = patterns(load_skill("media"))
    for t, exp in [("pon música", ("random", "play")), ("sorpréndeme", ("random",)),
                   ("spotify", ("svc_answer",)), ("en youtube", ("svc_answer",)),
                   ("pausa la música", ("pause",)), ("siguiente canción", ("next",)),
                   ("canción anterior", ("prev",)), ("para la música", ("stop_music",))]:
        check(route_local(p, t) in exp, f"media '{t}' -> {exp}, dio {route_local(p, t)}")


def test_routing_emails():
    p = patterns(load_skill("google_workspace"))
    for t, exp in [("cuántos correos tengo sin leer", "unread_count"),
                   ("cuáles correos tengo", "unread_from"),
                   ("de quién son los correos", "unread_from"),
                   ("analiza los correos", "email_actions"),
                   ("haz triaje de los correos", "email_actions"),
                   ("crea tareas de lo urgente", "email_actions"),
                   ("lee mis correos", "emails"),
                   ("resume mis correos", "summarize_emails"),
                   ("abre el correo 2", "open_email")]:
        check(route_local(p, t) == exp, f"correos '{t}' -> {exp}, dio {route_local(p, t)}")


def test_routing_hermes():
    p = patterns(load_skill("hermes"))
    for t, exp in [("¿qué sabe hacer hermes?", "hermes_info"),
                   ("hermes: investiga la competencia", "hermes"),
                   ("dile a hermes que busque proveedores", "hermes")]:
        check(route_local(p, t) == exp, f"hermes '{t}' -> {exp}, dio {route_local(p, t)}")


def test_routing_memory():
    p = patterns(load_skill("memory_graph"))
    for t, exp in [("qué sabes de mí", "list_knowledge"),
                   ("lista los archivos de conocimiento que tienes sobre mí", "list_knowledge"),
                   ("qué recuerdas de Ana", "recall"),
                   ("recuerda que entrego el jueves", "remember"),
                   ("estado de la memoria", "status")]:
        check(route_local(p, t) == exp, f"memoria '{t}' -> {exp}, dio {route_local(p, t)}")


def test_routing_telefono():
    p = patterns(load_skill("telefono"))
    for t in ["llama a Ana", "llama a 612345678", "marca a casa", "telefonea al gestor"]:
        check(route_local(p, t) == "llamar", f"telefono '{t}' -> llamar, dio {route_local(p, t)}")


def test_routing_domotica():
    p = patterns(load_skill("domotica"))
    for t, exp in [("enciende la tele", "tv_on"), ("apaga la televisión", "tv_off"),
                   ("sube el volumen de la tele", "tv_volume"), ("silencia la tele", "tv_mute"),
                   ("escanea la red", "descubrir"), ("enciende la luz del salón", "casa")]:
        check(route_local(p, t) == exp, f"domotica '{t}' -> {exp}, dio {route_local(p, t)}")


# ================== 2) COLISIONES entre skills (el bug más peligroso) ==================
def test_cross_skill_collisions():
    folders = ["media", "google_workspace", "hermes", "memory_graph", "telefono", "domotica"]
    mods = {f: patterns(load_skill(f)) for f in folders}

    def route_global(text):
        hits = [f for f in folders if route_local(mods[f], text)]
        return hits

    # cada frase debe casar SOLO con la skill esperada (o con ninguna extra)
    casos = [
        ("enciende la tele", ["domotica"]),
        ("pon música de Quevedo en spotify", ["media"]),
        ("llama a Ana", ["telefono"]),
        ("analiza los correos", ["google_workspace"]),
        ("qué sabe hacer hermes", ["hermes"]),
        ("qué sabes de mí", ["memory_graph"]),
        ("cuántos correos tengo", ["google_workspace"]),
    ]
    for t, exp in casos:
        hits = route_global(t)
        check(set(hits) == set(exp), f"colisión '{t}': esperaba {exp}, casó {hits}")


# ================== 3) PLANIFICADOR: _LLMMatch real (brain) ==================
def test_llmmatch_and_gate():
    brain = load_core("brain")
    M = brain._LLMMatch
    m = M("ponme algo tranqui", {"q3": "Quevedo", "svc3": "spotify"})
    check(m.group("q3") == "Quevedo" and m.group(0) == "ponme algo tranqui", "_LLMMatch group")
    check((m.group("nope") or "") == "", "_LLMMatch grupo inexistente")
    check(m.groupdict() == {"q3": "Quevedo", "svc3": "spotify"}, "_LLMMatch groupdict")
    # gate de charla pura
    st = brain._SMALLTALK_RX
    for t in ["hola", "gracias", "vale", "ok", "jajaja", "jejeje", "hasta luego", "sí", "no"]:
        check(bool(st.match(t)), f"smalltalk filtra '{t}'")
    for t in ["pon música", "enciende la tele", "analiza los correos"]:
        check(not st.match(t), f"smalltalk NO filtra acción '{t}'")
    # meta-preguntas
    meta = brain._META_RX
    for t in ["¿me oyes?", "no estás escuchando", "por texto"]:
        check(bool(meta.search(t)), f"meta detecta '{t}'")


# ================== 4) ANTI-ECO real (brain._is_echo) ==================
def test_anti_echo():
    brain = load_core("brain")
    # inyectamos lo que "dijo" nexus en el módulo tts que usa _is_echo
    import backend.core.tts as tts
    tts._SPOKEN.clear()
    import time
    dicho = "De 8 sin leer, 2 urgentes: Google Alerta de seguridad y aviso de facturación"
    tts._SPOKEN.append((time.time(), dicho))
    check(brain._is_echo("de ocho sin leer dos urgente ese"), "anti-eco: eco real detectado")
    check(not brain._is_echo("crea tareas de lo urgente"), "anti-eco: orden legítima NO es eco")
    check(not brain._is_echo("enciende la tele"), "anti-eco: orden corta NO es eco")


# ================== 5) HERMES: should_delegate real ==================
def test_should_delegate():
    h = load_skill("hermes")
    D = ["investiga a fondo la competencia y hazme un informe",
         "entra en la web de amazon y compárame precios",
         "monitoriza el precio en varias tiendas",
         "automatiza la descarga de facturas",
         "hazme un análisis de mercado de calcetines"]
    N = ["enciende la tele", "crea tareas de lo urgente", "qué hora es",
         "cómo estás", "pon música de quevedo", "cuántos correos tengo"]
    for t in D:
        check(h.should_delegate(t), f"should_delegate SÍ: '{t}'")
    for t in N:
        check(not h.should_delegate(t), f"should_delegate NO: '{t}'")
    # helpers de arranque existen y devuelven tipos correctos
    check(isinstance(h._hermes_exe({"settings": types.SimpleNamespace(get=lambda *a: "")}), str),
          "hermes _hermes_exe devuelve str")


# ================== 6) TTS: helpers reales ==================
def test_tts_helpers():
    tts = load_core("tts")
    # _split_sentences: 1ª frase corta separada, resto agrupado (no un solo bloque)
    txt = "Hola Adri. Esto es una segunda frase un poco más larga para el resto. Y una tercera."
    parts = tts._split_sentences(txt)
    check(isinstance(parts, list) and len(parts) >= 1, "tts _split_sentences devuelve lista")
    # normalización de voz: grados
    norm = tts._speak_norm("máx 33°C")
    check("grados" in norm and "°" not in norm, "tts _speak_norm: grados")
    # estimación de segundos > 0
    check(tts._estimate_secs("hola que tal") > 0, "tts _estimate_secs > 0")
    # registro anti-eco
    tts._SPOKEN.clear()
    tts._remember_spoken("prueba de voz")
    check(any("prueba de voz" in x for x in tts.recent_spoken()), "tts recent_spoken registra")


# ================== 7) DOMÓTICA: helpers reales ==================
def test_domotica_helpers():
    d = load_skill("domotica")
    check(d.wake_on_lan("no-es-mac") is False, "wake_on_lan rechaza MAC inválida")
    check(isinstance(d.wake_on_lan("AA:BB:CC:DD:EE:FF"), bool), "wake_on_lan MAC válida -> bool")
    check(isinstance(d._wol_burst("AA:BB:CC:DD:EE:FF", "192.168.1.50"), bool), "_wol_burst -> bool")
    check(d._wol_burst("corta", "") is False, "_wol_burst MAC inválida -> False")
    # detección de TV / marca
    tv = {"ssdp_type": "TV (Samsung)", "vendor": "Samsung", "services": [], "port_type": ""}
    check(d._dev_brand(tv) == "samsung", "_dev_brand samsung")


# ================== 8) MEMORIA: esquema y consultas ==================
def test_memory_schema():
    mem = load_core("memory")
    ddl = mem.PgMemory._DDL
    joined = " ".join(ddl).lower()
    for tabla in ["memories", "reminders", "goals", "goal_steps", "clients", "invoices", "vector"]:
        check(tabla in joined, f"_DDL crea '{tabla}'")
    check(any("all_knowledge" in d for d in dir(mem.PgMemory)), "PgMemory.all_knowledge existe")
    rag = load_core("rag")
    check(isinstance(rag.list_knowledge(5), list), "rag.list_knowledge -> lista")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        print(f"· {t.__name__}")
        try:
            t()
        except Exception as e:
            _fail.append(f"{t.__name__} EXCEPCIÓN: {type(e).__name__}: {e}")
            print("  EXCEPCIÓN:", type(e).__name__, e)
    print(f"\n{'='*54}\n{_pass} pasados, {len(_fail)} fallados")
    if _fail:
        print("\nFALLOS:")
        for f in _fail:
            print("  -", f)
    sys.exit(1 if _fail else 0)
