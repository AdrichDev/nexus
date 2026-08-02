# -*- coding: utf-8 -*-
"""Tests unitarios de la renovación 2026-07-24 — contra el CÓDIGO REAL del disco.

Cubren lo añadido/cambiado ese día:
  * skill chrome (CDP): enrutado de sus intents y selección de pestaña (_pick)
  * tablero: «show» en lenguaje natural sin pisar los intents específicos
  * hermes: encargos NUMERADOS (#1, #2…), consulta por número y su enrutado
  * jobs: numeración correlativa de la multitarea
  * skills renovadas a mano (comms, games, datos, research, mcp_hands,
    autoprovision): frases nuevas y anti-robo en el router global

Ejecutar:  python tests/test_renovacion.py     (desde la carpeta nexus)
Salida:    "N pasados, 0 fallados" y código de salida 0 si todo OK.
"""
import asyncio
import importlib.util
import os
import re
import sys
import tempfile
import time
import types

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


# ---------- utilidades: cargar skills REALES con stubs de deps pesadas ----------
def _stub(name):
    m = types.ModuleType(name)
    m.__getattr__ = lambda _n: types.SimpleNamespace()
    sys.modules[name] = m
    return m


def load_skill_module(folder):
    """Importa skills/<folder>/skill.py con stubs para dependencias ausentes."""
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    path = os.path.join(ROOT, "skills", folder, "skill.py")
    for _ in range(15):
        spec = importlib.util.spec_from_file_location(f"_ren_{folder}", path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            return mod
        except ModuleNotFoundError as e:
            _stub(e.name)
    raise RuntimeError(f"No pude importar skill {folder}")


def load_patterns(folder):
    mod = load_skill_module(folder)
    return {k: re.compile(v, re.IGNORECASE) for k, v in mod.SKILL["patterns"].items()}


_ALL = {}


def global_route(text):
    """Router global REAL: skills en orden alfabético, intents en orden de dict."""
    if not _ALL:
        skdir = os.path.join(ROOT, "skills")
        for folder in sorted(os.listdir(skdir)):
            if os.path.isfile(os.path.join(skdir, folder, "skill.py")):
                _ALL[folder] = load_patterns(folder)
    for folder, pats in _ALL.items():
        for intent, rx in pats.items():
            if rx.search(text):
                return folder, intent
    return None, None


# ================== 1) CHROME: enrutado de sus intents ==================
def test_chrome_routing():
    for t, intent in [("conecta con chrome", "connect"),
                      ("estado de chrome", "connect"),
                      ("qué pestañas tengo abiertas", "tabs"),
                      ("qué tengo abierto en el navegador", "tabs"),
                      ("resume la pestaña 2", "read"),
                      ("lee la pestaña de youtube", "read"),
                      ("qué estoy viendo en chrome", "read"),
                      ("cambia a la pestaña de gmail", "switch"),
                      ("abre marca.com en chrome", "open"),
                      ("abre una pestaña con el tiempo en madrid", "open"),
                      ("cierra la pestaña de twitter", "close")]:
        f, i = global_route(t)
        check((f, i) == ("chrome", intent), f"chrome: '{t}' -> {f}/{i} (esperaba chrome/{intent})")
    # anti-robo: chrome NO debe capturar órdenes de otros dominios
    for t, skill in [("abre el correo número 2", "google_workspace"),
                     ("resume el documento C:\\docs\\plan.txt", "files"),
                     ("abre steam", "games")]:
        f, _i = global_route(t)
        check(f == skill, f"chrome anti-robo: '{t}' -> {f} (esperaba {skill})")


# ================== 2) CHROME: selección de pestaña (_pick) ==================
def test_chrome_pick():
    ch = load_skill_module("chrome")
    tabs = [{"id": "a", "title": "YouTube - vídeos", "url": "https://youtube.com"},
            {"id": "b", "title": "Gmail", "url": "https://mail.google.com"},
            {"id": "c", "title": "Marca", "url": "https://marca.com"}]
    check(ch._pick(tabs, "2")["id"] == "b", "_pick: por número (2) -> segunda pestaña")
    check(ch._pick(tabs, "de gmail")["id"] == "b", "_pick: por término 'gmail'")
    check(ch._pick(tabs, "marca")["id"] == "c", "_pick: por término 'marca'")
    check(ch._pick(tabs, "")["id"] == "a", "_pick: sin selector -> primera")
    check(ch._pick(tabs, "99")["id"] == "a", "_pick: número fuera de rango -> primera")


# ================== 3) TABLERO: show natural sin pisar intents ==================
def test_tablero_show_natural():
    p = load_patterns("tasks_board")
    check(list(p.keys())[-1] == "show", "tablero: 'show' debe ser el ÚLTIMO intent del dict")

    def route_local(text):
        for intent, rx in p.items():
            if rx.search(text):
                return intent
        return None
    for t in ["ver tablero", "qué tareas tengo", "mis tareas", "muéstrame las tareas",
              "tareas", "lista de tareas", "qué tengo pendiente", "cómo van mis tareas"]:
        check(route_local(t) == "show", f"tablero show: '{t}'")
    for t, intent in [("crea la tarea comprar tela para el viernes", "create"),
                      ("mueve comprar tela a en progreso", "move"),
                      ("qué tareas van retrasadas", "late"),
                      ("organiza mis tareas por urgencia", "organize"),
                      ("borra todas las tareas", "clear"),
                      ("borra la tarea comprar tela", "delete")]:
        check(route_local(t) == intent, f"tablero: '{t}' -> {intent} (no debe caer en show)")
    # global: «tareas de google» sigue siendo de google_workspace
    f, _ = global_route("tareas de google")
    check(f == "google_workspace", "global: 'tareas de google' -> google_workspace")


# ================== 4) HERMES: encargos numerados ==================
def test_hermes_numeracion():
    h = load_skill_module("hermes")
    # DATA_DIR temporal para no tocar el registro real
    tmp = tempfile.mkdtemp()
    import pathlib
    cfg = types.ModuleType("backend.core.config")
    cfg.DATA_DIR = pathlib.Path(tmp)
    old = sys.modules.get("backend.core.config")
    sys.modules["backend.core.config"] = cfg
    try:
        j1, n1 = h._reg_add("investiga precios de tela", "pc")
        j2, n2 = h._reg_add("compara proveedores", "pc")
        check((n1, n2) == (1, 2), f"numeración correlativa: {n1},{n2} (esperaba 1,2)")
        h._reg_set(j1, estado="hecho", resultado="Informe listo: 3 proveedores.",
                   t1=time.time())
        r = asyncio.run(h._resultado({}, "resultado del encargo 1"))
        check("#1" in r["reply"] and "Informe listo" in r["reply"],
              "consulta por número: el #1 devuelve SU resultado")
        r2 = asyncio.run(h._resultado({}, "resultado del encargo 9"))
        check("#9" in r2["reply"] and "No tengo" in r2["reply"],
              "consulta por número inexistente: aviso claro")
        r3 = asyncio.run(h._resultado({}, "¿y la respuesta de hermes?"))
        check("#2" in r3["reply"], "listado general: los encargos salen con su número")
    finally:
        if old is not None:
            sys.modules["backend.core.config"] = old
        else:
            sys.modules.pop("backend.core.config", None)


def test_hermes_encargo_por_numero_routing():
    for t in ["resultado del encargo 3", "cómo va el encargo 2", "estado del encargo 5"]:
        f, i = global_route(t)
        check((f, i) == ("hermes", "hermes_resultado"),
              f"routing: '{t}' -> {f}/{i} (esperaba hermes/hermes_resultado)")
    # el ancla «encargo» no roba las frases del tablero
    f, i = global_route("qué tareas tengo")
    check((f, i) == ("tasks_board", "show"), "'qué tareas tengo' sigue siendo del tablero")


# ================== 5) JOBS: multitarea numerada ==================
def test_jobs_numerados():
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    import backend.core.jobs as jm

    class _DummyBus:
        async def emit(self, *a, **k):
            pass

    old_bus = jm.bus
    jm.bus = _DummyBus()
    # v23: el gestor PERSISTE en data/jobs.json y continúa la numeración entre
    # arranques; para probar la numeración se le da un fichero limpio.
    import tempfile as _tf
    from pathlib import Path as _P
    old_file = jm.JOBS_FILE
    jm.JOBS_FILE = _P(_tf.mkdtemp(prefix="nexus_jobs_")) / "jobs.json"
    try:
        async def scenario():
            mgr = jm.JobManager(max_concurrent=2)

            async def work():
                return {"reply": "hecho"}
            j1 = await mgr.submit("uno", work)
            j2 = await mgr.submit("dos", work)
            for _ in range(50):
                await asyncio.sleep(0.02)
                snap = {j["id"]: j for j in mgr.snapshot()}
                if all(snap[j]["status"] == "completed" for j in (j1, j2)):
                    break
            return {j["id"]: j for j in mgr.snapshot()}, j1, j2
        snap, j1, j2 = asyncio.run(scenario())
        check(snap[j1].get("num") == 1 and snap[j2].get("num") == 2,
              f"jobs: números correlativos 1,2 (obtuve {snap[j1].get('num')},{snap[j2].get('num')})")
        check(snap[j1]["status"] == "completed" and snap[j1]["result"] == "hecho",
              "jobs: el trabajo termina y guarda el resultado (estado 'completed', v23)")
    finally:
        jm.bus = old_bus
        jm.JOBS_FILE = old_file


# ================== 6) SKILLS RENOVADAS A MANO: frases y anti-robo ==================
def test_renovadas_routing():
    casos = [
        ("ver mensajes", "comms", "inbox"),
        ("qué mensajes tengo", "comms", "inbox"),
        ("captura de tareas", "comms", "capture"),
        ("saca tareas de mis mensajes", "comms", "capture"),
        ("envía un mensaje a Ana diciendo que llego tarde", "comms", "send"),
        ("estado del bot", "comms", "bot"),
        ("quiero jugar a Rust", "games", "play"),
        ("échate una partida a Valorant", "games", "play"),
        ("instala Rust en steam", "games", "install"),
        ("valida Rust en steam", "games", "update"),
        ("qué manos tienes", "mcp_hands", "list"),
        ("recarga los conectores", "mcp_hands", "reload"),
        ("conéctate a la base de datos postgresql://u:p@h/db", "datos", "connect"),
        ("qué tablas hay", "datos", "tables"),
        ("consulta: SELECT * FROM ventas", "datos", "query"),
        ("dashboard de la tabla ventas", "datos", "dashboard"),
        ("investiga el mercado de camisetas y hazme un informe", "research", "research"),
        ("hazme un informe sobre el mercado textil", "research", "research"),
        ("tendencias de moda deportiva", "research", "trends"),
        ("cómo van mis gastos", "research", "economy"),
        ("revisa tu infraestructura", "autoprovision", "diagnose"),
        ("levanta docker", "autoprovision", "docker_up"),
        ("prepara el modelo llama3.1", "autoprovision", "model_ensure"),
    ]
    for t, skill, intent in casos:
        f, i = global_route(t)
        check((f, i) == (skill, intent), f"renovadas: '{t}' -> {f}/{i} (esperaba {skill}/{intent})")
    # anti-robo global de las renovadas
    for t, skill in [("qué tiempo hace en Madrid", "clima"),
                     ("lee mis correos", "google_workspace"),
                     ("pon música de rock", "media"),
                     ("enciende la luz del salón", "domotica"),
                     ("haz una captura de pantalla", "system_pc"),
                     ("recuerda que el proveedor se llama Chen", "memory_graph")]:
        f, _ = global_route(t)
        check(f == skill, f"anti-robo: '{t}' -> {f} (esperaba {skill})")


# ================== 7) TELÉFONO: agenda + llamadas + whatsapp móvil ==================
def test_telefono_agenda():
    tel = load_skill_module("telefono")
    tmp = tempfile.mkdtemp()
    import pathlib
    cfg = types.ModuleType("backend.core.config")
    cfg.DATA_DIR = pathlib.Path(tmp)
    old = sys.modules.get("backend.core.config")
    sys.modules["backend.core.config"] = cfg
    try:
        check(tel.normalize_number("612 34 56 78") == "+34612345678",
              "normalize: 9 dígitos → +34612345678")
        check(tel.normalize_number("+44 7911 123456") == "+447911123456",
              "normalize: prefijo internacional se respeta")
        check(tel.normalize_number("0034612345678") == "+34612345678",
              "normalize: 00 → +")
        agenda = {"Inés": "+34612345678", "Ana": "+34699112233"}
        tel._save_contacts(agenda)
        check(tel.resolve_contact("ines") == ("Inés", "+34612345678"),
              "resolve: 'ines' sin tilde encuentra a «Inés»")
        check(tel.resolve_contact("ana")[1] == "+34699112233",
              "resolve: 'ana' encuentra a Ana")
        check(tel.resolve_contact("desconocido") == ("", ""),
              "resolve: desconocido devuelve vacío")
    finally:
        if old is not None:
            sys.modules["backend.core.config"] = old
        else:
            sys.modules.pop("backend.core.config", None)


def test_telefono_routing():
    for t, intent in [("llama a mamá", "llamar"),
                      ("llama a 612 345 678", "llamar"),
                      ("marca el 611223344", "llamar"),
                      ("telefonea a Ana", "llamar"),
                      ("apunta el teléfono de mamá 612 345 678", "save_contact"),
                      ("guarda el número de Ana: 699112233", "save_contact"),
                      ("el teléfono de la nave es 916001122", "save_contact"),
                      ("mis contactos", "list_contacts"),
                      ("qué teléfonos tienes", "list_contacts"),
                      ("borra el contacto de mamá", "del_contact"),
                      ("puedes hacer llamadas", "info")]:
        f, i = global_route(t)
        check((f, i) == ("telefono", intent), f"telefono: '{t}' -> {f}/{i} (esperaba telefono/{intent})")
    # whatsapp sigue entrando por n8n_flows (que decide: webhook o móvil)
    f, i = global_route("envía un whatsapp a mamá diciendo que llego en 10 minutos")
    check((f, i) == ("n8n_flows", "whatsapp"), f"whatsapp: -> {f}/{i} (esperaba n8n_flows/whatsapp)")
    # anti-robo: guardar contacto no pisa memoria ni tablero
    for t, skill in [("recuerda que el proveedor se llama Chen", "memory_graph"),
                     ("crea la tarea llamar al proveedor", "tasks_board"),
                     ("pon música de rock", "media")]:
        f, _ = global_route(t)
        check(f == skill, f"telefono anti-robo: '{t}' -> {f} (esperaba {skill})")


def test_mobile_html_phone_events():
    src = open(os.path.join(ROOT, "frontend", "mobile.html"), encoding="utf-8").read()
    check("type === 'call'" in src, "mobile.html: maneja el evento 'call'")
    check("type === 'whatsapp'" in src, "mobile.html: maneja el evento 'whatsapp'")
    check("wa.me" in src, "mobile.html: construye enlaces wa.me")
    check("tel:" in src, "mobile.html: marca con tel:")


if __name__ == "__main__":
    tests = [test_chrome_routing, test_chrome_pick, test_tablero_show_natural,
             test_hermes_numeracion, test_hermes_encargo_por_numero_routing,
             test_jobs_numerados, test_renovadas_routing,
             test_telefono_agenda, test_telefono_routing, test_mobile_html_phone_events]
    for t in tests:
        print(f"· {t.__name__}")
        try:
            t()
        except Exception as e:
            _fail.append(f"{t.__name__} EXCEPCIÓN: {type(e).__name__}: {e}")
            print("  EXCEPCIÓN:", e)
    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    sys.exit(1 if _fail else 0)
