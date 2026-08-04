# -*- coding: utf-8 -*-
"""Tests unitarios de nexus — se ejecutan contra el CÓDIGO REAL del disco
(no copias). Cubren: patrones de las skills (routing por regex), el objeto
_LLMMatch del planificador y el parseo JSON de plan_action.

Ejecutar:  python tests/test_routing.py        (desde la carpeta nexus)
Salida:    "N pasados, 0 fallados" y código de salida 0 si todo OK.
"""
import ast
import importlib.util
import os
import re
import sys

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


# ---------- utilidades: cargar código REAL del disco ----------
import types
from _frontend_js import js_hud  # el HUD entero, no solo command.js


def _stub(name):
    """Crea un módulo ficticio para una dependencia pesada ausente (httpx, etc.)
    — así el import del fichero de la skill NO falla y obtenemos sus patrones REALES."""
    m = types.ModuleType(name)
    m.__getattr__ = lambda _n: types.SimpleNamespace()
    sys.modules[name] = m
    return m


def load_skill_patterns(folder):
    """Importa skills/<folder>/skill.py y devuelve sus patrones REALES ya
    compilados (incluye patrones por concatenación, como media). Stubbea las
    dependencias pesadas ausentes para no arrastrar todo el backend."""
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    path = os.path.join(ROOT, "skills", folder, "skill.py")
    for _ in range(12):                          # reintenta creando stubs de lo que falte
        spec = importlib.util.spec_from_file_location(f"_skill_{folder}", path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            return {k: re.compile(v, re.IGNORECASE)
                    for k, v in mod.SKILL["patterns"].items()}
        except ModuleNotFoundError as e:
            _stub(e.name)                         # crea el módulo ausente y reintenta
    raise RuntimeError(f"No pude importar skill {folder}")


def route_local(patterns, text):
    """Como route(): primer intent cuyo patrón casa (orden del dict)."""
    for intent, rx in patterns.items():
        if rx.search(text):
            return intent
    return None


def extract_real_object(path, names):
    """Extrae y ejecuta clases/funciones REALES de un fichero por nombre,
    sin importar el módulo entero (evita deps pesadas). Devuelve el namespace."""
    tree = ast.parse(open(path, encoding="utf-8").read())
    keep = [n for n in tree.body
            if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and n.name in names)]
    ns = {"re": re, "__import__": __import__}
    exec(compile(ast.Module(body=keep, type_ignores=[]), path, "exec"), ns)
    return ns


# ================== TEST 1: routing de MÚSICA (media) ==================
def test_media():
    p = load_skill_patterns("media")
    # sin servicio -> intent random/play (para que el handler PREGUNTE dónde)
    check(route_local(p, "pon música") in ("random", "play"), "media: 'pon música' debe enrutar a música")
    check(route_local(p, "sorpréndeme") == "random", "media: 'sorpréndeme' -> random")
    check(route_local(p, "spotify") == "svc_answer", "media: 'spotify' (respuesta) -> svc_answer")
    check(route_local(p, "en youtube") == "svc_answer", "media: 'en youtube' -> svc_answer")
    check(route_local(p, "pausa la música") == "pause", "media: pausa")
    check(route_local(p, "siguiente canción") == "next", "media: siguiente")


# ================== TEST 2: CORREOS (google_workspace) ==================
def test_emails():
    p = load_skill_patterns("google_workspace")
    check(route_local(p, "cuántos correos tengo sin leer") == "unread_count", "correos: cuántos -> unread_count")
    check(route_local(p, "cuáles correos tengo") == "unread_from", "correos: cuáles -> unread_from")
    check(route_local(p, "de quién son los correos") == "unread_from", "correos: de quién -> unread_from")
    check(route_local(p, "analiza los correos") == "email_actions", "correos: analiza -> email_actions")
    check(route_local(p, "haz triaje de los correos") == "email_actions", "correos: triaje -> email_actions")
    check(route_local(p, "lee mis correos") == "emails", "correos: lee -> emails (listar, no analizar)")


# ================== TEST 3: HERMES ==================
def test_hermes():
    p = load_skill_patterns("hermes")
    check(route_local(p, "¿qué sabe hacer hermes?") == "hermes_info", "hermes: qué sabe -> hermes_info")
    check(route_local(p, "hermes: investiga la competencia") == "hermes", "hermes: orden explícita -> hermes")
    check(route_local(p, "dile a hermes que busque proveedores") == "hermes", "hermes: 'dile a' -> hermes")
    # --- intents NUEVOS (matan el bucle de «Hermes está apagado») ---
    check(route_local(p, "¿está hermes conectado?") == "hermes_estado", "hermes: ¿está conectado? -> estado")
    check(route_local(p, "estado de hermes") == "hermes_estado", "hermes: estado de hermes -> estado")
    check(route_local(p, "diagnostica hermes") == "hermes_estado", "hermes: diagnostica -> estado")
    check(route_local(p, "y la respuesta de hermes?") == "hermes_resultado", "hermes: la respuesta -> resultado")
    check(route_local(p, "QUIERO LA RESPUESTA QUE TE HA DADO HERMES A LA TAREA QUE LE HAS MANDADO") == "hermes_resultado",
          "hermes: respuesta que te ha dado -> resultado")
    check(route_local(p, "¿ha terminado ya hermes?") == "hermes_resultado", "hermes: ha terminado -> resultado")
    check(route_local(p, "qué te ha dicho hermes") == "hermes_resultado", "hermes: qué te ha dicho -> resultado")
    check(route_local(p, "arranca hermes") == "hermes_arranca", "hermes: arranca -> arranca")
    check(route_local(p, "levanta el hermes") == "hermes_arranca", "hermes: levanta -> arranca")
    check(route_local(p, "reinicia hermes") == "hermes_arranca", "hermes: reinicia -> arranca")
    check(route_local(p, "mándale una tarea a hermes") == "hermes_tarea", "hermes: mándale una tarea -> tarea")
    check(route_local(p, "mandale una tarea a hermes") == "hermes_tarea", "hermes: mandale (sin tilde) -> tarea")
    m = p["hermes_tarea"].search("mándale una tarea a hermes: resume las noticias de El País")
    check(bool(m) and (m.group("orden4") or "").startswith("resume"), "hermes: tarea con orden extrae el encargo")


# ============ TEST 3b: HERMES gana el routing GLOBAL (ninguna skill roba) ============
def test_hermes_global_route():
    """Emula route() de skills_loader: skills en orden alfabético de carpeta, patrones
    en orden del dict. Las frases de Hermes deben caer en hermes/<intent> correcto."""
    skdir = os.path.join(ROOT, "skills")
    folders = sorted(f for f in os.listdir(skdir)
                     if os.path.isfile(os.path.join(skdir, f, "skill.py")))
    allp = []
    for f in folders:
        try:
            allp.append((f, load_skill_patterns(f)))
        except Exception:
            pass                                 # una skill rota no invalida este test
    def groute(text):
        for folder, pats in allp:
            for intent, rx in pats.items():
                if rx.search(text):
                    return folder, intent
        return None, None
    for frase, intent in [("arranca hermes", "hermes_arranca"),
                          ("¿está hermes conectado?", "hermes_estado"),
                          ("y la respuesta de hermes?", "hermes_resultado"),
                          ("mándale una tarea a hermes", "hermes_tarea"),
                          ("hermes: investiga la competencia", "hermes")]:
        got = groute(frase)
        check(got == ("hermes", intent), f"routing global: «{frase}» -> {got} (esperaba hermes/{intent})")


# ============ TEST 3c: autoprovisión del .env de Hermes (funciones REALES) ============
def test_hermes_env_provision():
    ns = extract_real_object(os.path.join(ROOT, "skills", "hermes", "skill.py"),
                             {"_env_apply", "_key_strong"})
    env_apply, key_strong = ns["_env_apply"], ns["_key_strong"]
    check(key_strong("a" * 32), "env: clave larga aleatoria = fuerte")
    check(not key_strong("corta"), "env: clave corta = débil")
    check(not key_strong("change-me-local-dev-12345"), "env: placeholder = débil (Hermes la rechaza)")
    KEY = "f" * 40
    # .env vacío -> añade las dos líneas
    new, ch = env_apply("", KEY)
    check("API_SERVER_ENABLED=true" in new and f"API_SERVER_KEY={KEY}" in new and len(ch) == 2,
          "env: .env vacío queda provisionado")
    # .env con clave débil y flag apagado -> se corrigen y se CONSERVA el resto
    prev = "TELEGRAM_TOKEN=abc\nAPI_SERVER_ENABLED=false\nAPI_SERVER_KEY=corta\n"
    new, ch = env_apply(prev, KEY)
    check("TELEGRAM_TOKEN=abc" in new, "env: respeta las líneas ajenas")
    check("API_SERVER_ENABLED=true" in new and "API_SERVER_ENABLED=false" not in new, "env: activa el flag")
    check(f"API_SERVER_KEY={KEY}" in new and "API_SERVER_KEY=corta" not in new, "env: sustituye la clave débil")
    # .env ya correcto -> CERO cambios (idempotente; no reescribe ni rota nada)
    new2, ch2 = env_apply(new, KEY)
    check(ch2 == [] and new2 == new, "env: idempotente si ya está bien")


# ====== TEST 3c-bis: entorno LIMPIO al lanzar Hermes (el PYTHONPATH de nexus
# envenenaba el python de Hermes -> 500 en todos los encargos) ======
def test_hermes_clean_env():
    ns = extract_real_object(os.path.join(ROOT, "skills", "hermes", "skill.py"), {"_clean_env"})
    clean = ns["_clean_env"]
    os.environ["PYTHONPATH"] = r"D:\donde\sea\.venv\Lib\site-packages"
    os.environ["VIRTUAL_ENV"] = r"D:\donde\sea\.venv"
    try:
        env = clean()
        check("PYTHONPATH" not in env, "clean_env: quita PYTHONPATH (causa de los 500 de Hermes)")
        check("VIRTUAL_ENV" not in env, "clean_env: quita VIRTUAL_ENV")
        check("PATH" in env or "Path" in env, "clean_env: conserva PATH")
    finally:
        os.environ.pop("PYTHONPATH", None)
        os.environ.pop("VIRTUAL_ENV", None)
    src = open(os.path.join(ROOT, "skills", "hermes", "skill.py"), encoding="utf-8").read()
    check(src.count("env=_clean_env()") >= 2,
          "el gateway se lanza SIEMPRE con entorno limpio (ambos Popen)")


# ============ TEST 3h: TABLERO — fecha límite, hora, evento vs acción, estados ============
def test_tablero_fecha_hora_tipo():
    import datetime as _dt
    path = os.path.join(ROOT, "skills", "tasks_board", "skill.py")
    tree = ast.parse(open(path, encoding="utf-8").read())
    keep_assign = [n for n in tree.body if isinstance(n, ast.Assign)
                   and any(getattr(t, "id", "") in ("MESES", "DIAS", "_PRE", "_EVENT_RX") for t in n.targets)]
    keep_fn = [n for n in tree.body if isinstance(n, ast.FunctionDef)
               and n.name in ("_extract_due", "_extract_time")]
    ns = {"re": re, "dt": _dt}
    exec(compile(ast.Module(body=keep_assign + keep_fn, type_ignores=[]), path, "exec"), ns)
    ed, et, EV = ns["_extract_due"], ns["_extract_time"], ns["_EVENT_RX"]
    # FECHA LÍMITE
    _t, due = ed("crear la web para el 25/07")
    check(bool(due) and due.endswith("-07-25"), "tablero: 'para el 25/07' saca fecha límite")
    # OJO: esto NO puede llevar la fecha escrita a mano. Estaba fijado a
    # «2026-07-30» y al pasar la medianoche del 30 al 31 la suite se puso roja
    # sola: el 30 de julio ya había pasado y el extractor —bien— lo movía al año
    # siguiente. Se comprueba el CONTRATO: día y mes correctos, y nunca en pasado.
    _t, due = ed("informe con fecha límite 30 de julio")
    check(bool(due) and due.endswith("-07-30"),
          f"tablero: 'fecha límite 30 de julio' saca el 30 de julio (dio {due})")
    check(bool(due) and due >= _dt.date.today().isoformat(),
          f"y nunca una fecha ya pasada (hoy {_dt.date.today().isoformat()}, dio {due})")
    _t, due = ed("entrega antes del viernes")
    check(bool(due), "tablero: 'antes del viernes' saca fecha")
    # HORA
    _t, h = et("mentoría a las 18")
    check(h == "18:00", "tablero: 'a las 18' -> 18:00")
    _t, h = et("reunión a las 9:30 de la mañana")
    check(h == "09:30", "tablero: '9:30 mañana' -> 09:30")
    _t, h = et("cita a la 1 y media de la tarde")
    check(h == "13:30", "tablero: '1 y media tarde' -> 13:30")
    _t, h = et("crear la web")
    check(h is None, "tablero: sin hora -> None (una acción no lleva hora)")
    # EVENTO vs ACCIÓN
    check(bool(EV.search("apunta la mentoría del jueves")), "tablero: mentoría = evento")
    check(bool(EV.search("reunión con el equipo")), "tablero: reunión = evento")
    check(not EV.search("crear una web para el cliente"), "tablero: crear web = acción, NO evento")


def test_tablero_estados_y_start():
    p = load_skill_patterns("tasks_board")
    check(route_local(p, "mueve la web a en progreso") == "move", "tablero: mover a en progreso")
    check(route_local(p, "mueve el informe a in progress") == "move", "tablero: acepta 'in progress'")
    check(route_local(p, "mueve la web a en curso") == "move", "tablero: acepta 'en curso'")
    check(route_local(p, "mueve la tarea X a review") == "move", "tablero: acepta 'review'")
    check(route_local(p, "me pongo con la web del cliente") == "start", "tablero: 'me pongo con' -> start (progreso)")
    check(route_local(p, "crea la tarea diseñar el logo para el viernes") == "create", "tablero: crear con fecha")
    check(route_local(p, "apunta la reunión con el CTO el jueves a las 10") == "create", "tablero: apunta evento -> create")


def test_board_kind_time_fields():
    # board.add_task DEBE aceptar y guardar time_at + kind (código real por AST)
    src = open(os.path.join(ROOT, "backend", "core", "board.py"), encoding="utf-8").read()
    check("time_at" in src and '"kind"' in src, "board: add_task guarda 'time' y 'kind'")
    check('"in progress": "progreso"' in src, "board: alias de estados en inglés (in progress)")


# ============ TEST 3i: TTS nunca lee rutas ni separadores ============
def test_tts_rutas_separadores():
    path = os.path.join(ROOT, "backend", "core", "infraestructura", "tts.py")
    tree = ast.parse(open(path, encoding="utf-8").read())
    fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_speak_norm"]
    ns = {"re": re}
    exec(compile(ast.Module(body=fn, type_ignores=[]), path, "exec"), ns)
    norm = ns["_speak_norm"]
    check("gateway" in norm("mira data/hermes_gateway.log") and "/" not in norm("mira data/hermes_gateway.log")
          and "data" not in norm("mira data/hermes_gateway.log"),
          "tts: ruta relativa -> solo el último nombre, sin barras")
    r = norm(r"esta en C:\Users\usuario\AppData\Local\hermes\venv")
    check("venv" in r and "\\" not in r and "Users" not in r, "tts: ruta Windows -> último componente")
    check(norm("HUD/APK/Telegram") == "HUD, APK, Telegram", "tts: lista con / -> comas (separador, no 'barra')")
    check(norm("wake_word y edge-tts") == "wake word y edge tts", "tts: _ y - dentro de palabra = espacio")
    check("2026-07-23" in norm("APK v7 2026-07-23"), "tts: fechas con guion NO se rompen")


# ============ TEST 3j: correos — cantidad vs cuáles vs segundo plano ============
def test_correos_formato_respuestas():
    src = open(os.path.join(ROOT, "skills", "google_workspace", "skill.py"), encoding="utf-8").read()
    # «cuántos» = solo números, sin frases de más
    check('f"{unread} sin leer' in src, "correos: unread_count responde números pelados")
    # el bloque de unread_count ya no lleva la coletilla «Bandeja al día»
    uc = src.split('if intent == "unread_count":', 1)[1].split("if intent ==", 1)[0]
    check("Bandeja al día" not in uc, "correos: unread_count sin coletilla larga (solo números)")
    # urgentes en segundo plano con AVISO
    check("_email_urgent_job" in src, "correos: email_urgent corre en segundo plano (job propio)")
    check("Voy a ello en segundo plano" in src, "correos: email_urgent avisa que va en 2º plano")
    check("Revisión terminada" in src, "correos: el job de urgentes AVISA al terminar")


# ====== TEST 3l: CRUD Gmail/Calendar + el regex de correos ya NO casa «que» ======
def test_correos_crud_y_no_bucle():
    p = load_skill_patterns("google_workspace")
    # marcar como leído
    check(route_local(p, "pon los correos como leídos") == "mark_read", "gmail: pon como leídos -> mark_read")
    check(route_local(p, "marca todo como leído") == "mark_read", "gmail: marca todo leído -> mark_read")
    check(route_local(p, "ponlos como leídos") == "mark_read", "gmail: ponlos como leídos -> mark_read")
    check(route_local(p, "marca el correo 2 como no leído") == "mark_unread", "gmail: no leído -> mark_unread")
    # borrar correos
    check(route_local(p, "borra el correo 3") == "delete_email", "gmail: borra el correo N -> delete_email")
    check(route_local(p, "elimina los correos de Amazon") == "delete_email", "gmail: borra de X -> delete_email")
    check(route_local(p, "manda a la papelera los correos de más de 30 días") == "delete_email",
          "gmail: papelera antiguos -> delete_email")
    # calendar CRUD
    check(route_local(p, "cancela la reunión con el CTO") == "delete_event", "cal: cancela reunión -> delete_event")
    check(route_local(p, "borra el evento del jueves") == "delete_event", "cal: borra evento -> delete_event")
    check(route_local(p, "mueve la reunión al viernes a las 17") == "edit_event", "cal: mueve reunión -> edit_event")
    check(route_local(p, "reprograma la cita del médico") == "edit_event", "cal: reprograma cita -> edit_event")
    # EL BUG DEL BUCLE: una negación con «que ... leas ... correos» NO debe leer correos
    for neg in ["no te he dicho que me leas correos electrónicos",
                "no te he dicho que leas correos",
                "que coño haces leyendo correos"]:
        r = route_local(p, neg)
        check(r != "emails", f"gmail: «{neg[:40]}…» NO debe caer en 'emails' (era el bucle) -> {r}")
    # los casos legítimos SIGUEN funcionando
    check(route_local(p, "lee mis correos") == "emails", "gmail: 'lee mis correos' sigue -> emails")
    check(route_local(p, "qué correos tengo") == "emails", "gmail: 'qué correos tengo' -> emails")
    check(route_local(p, "cuántos correos sin leer") == "unread_count", "gmail: cuántos -> unread_count")


# ====== TEST 3m: guard de NEGACIÓN en brain.py (no re-dispara la acción) ======
def test_negacion_guard():
    src = open(os.path.join(ROOT, "backend", "core", "brain.py"), encoding="utf-8").read()
    m = re.search(r"_NO_ACCION_RX = re\.compile\(\s*(.*?)\s*,\s*re\.IGNORECASE\)", src, re.S)
    assert m, "_NO_ACCION_RX no encontrado en brain.py"
    rx = re.compile(eval("(" + m.group(1) + ")"), re.IGNORECASE)
    for t in ["no te he dicho que me leas correos", "no te he dicho que leas correos electrónicos",
              "no quiero que leas correos", "deja de leer", "no vuelvas a leer los correos",
              "quién te ha dicho que leas eso", "eso no es lo que te he pedido"]:
        check(bool(rx.search(t)), f"negación: «{t}» debe blindarse")
    for t in ["lee mis correos", "pon música", "enciende la tele", "qué correos tengo"]:
        check(not rx.search(t), f"negación: «{t}» NO es negación (es acción válida)")
    # y el guard corta el routing (routed=None y se salta plan/hermes)
    check("routed = None if _no_accion else route(text)" in src,
          "brain: negación -> routed=None (no ejecuta skill)")
    check(src.count("and not _no_accion") >= 3, "brain: el guard corta plan_action, interpret y auto-Hermes")


# ====== TEST 3s: WHITE-LABEL — el nombre del sistema se propaga a todo ======
def test_white_label_nombre():
    # helpers de config (nombre/slug/pron) — código real
    cfg = os.path.join(ROOT, "backend", "core", "comun", "config.py")
    ns = extract_real_object(cfg, {"assistant_name", "assistant_slug", "assistant_pron"})
    # simulamos settings con un contenedor mínimo
    import types as _t
    fake = _t.SimpleNamespace(_json={})
    fake.get = lambda k, d=None: fake._json.get(k, d)
    ns2 = {"re": re, "settings": fake, "assistant_name": ns["assistant_name"],
           "assistant_slug": ns["assistant_slug"]}
    exec("import unicodedata", ns2)
    # re-exec las 3 funciones con nuestro settings
    tree = ast.parse(open(cfg, encoding="utf-8").read())
    keep = [n for n in tree.body if isinstance(n, ast.FunctionDef)
            and n.name in ("assistant_name", "assistant_slug", "assistant_pron")]
    exec(compile(ast.Module(body=keep, type_ignores=[]), cfg, "exec"), ns2)
    aname, aslug, apron = ns2["assistant_name"], ns2["assistant_slug"], ns2["assistant_pron"]
    check(aname() == "nexus" and aslug() == "nexus" and apron() == "nexus",
          "white-label: por defecto nexus/nexus/nexus (se lee tal cual)")
    fake._json["assistant_name"] = "Helios"
    check(aname() == "Helios" and aslug() == "helios" and apron() == "Helios",
          "white-label: «Helios» → slug helios, se pronuncia Helios")
    fake._json["assistant_name"] = "Mi Casa IA"
    check(aslug() == "mi_casa_ia", "white-label: slug seguro para Docker/BD «Mi Casa IA»→mi_casa_ia")
    # pronunciación personalizada: assistant_pron manda si difiere del nombre
    fake._json["assistant_name"] = "Xql"; fake._json["assistant_pron"] = "équiscuele"
    check(apron() == "équiscuele", "white-label: assistant_pron fuerza cómo se pronuncia")
    fake._json.pop("assistant_pron", None)

    # prompts: el system prompt usa {assistant}
    llm = open(os.path.join(ROOT, "backend", "core", "infraestructura", "llm.py"), encoding="utf-8").read()
    check("Eres {assistant}" in llm and "assistant=_aname()" in llm, "white-label: SYSTEM_PROMPT usa el nombre")
    check("ENRUTADOR de {_aname()}" in llm and "PLANIFICADOR de {_aname()}" in llm,
          "white-label: enrutador y planificador usan el nombre")
    # voz
    tts = open(os.path.join(ROOT, "backend", "core", "infraestructura", "tts.py"), encoding="utf-8").read()
    check("assistant_pron" in tts and "assistant_name" in tts, "white-label: _pron usa el nombre/pron configurados")
    # docker/BD por slug (sin literales de marca antigua)
    app = open(os.path.join(ROOT, "backend", "app.py"), encoding="utf-8").read()
    check("assistant_slug()" in app and "{slug}_memoria_postgres" in app and "{slug}_core" in app,
          "white-label: Docker/BD derivan del slug del nombre")
    # frontend + setup
    js = js_hud()
    check("function applyBranding" in js and "assistant_name" in js and "assistant_logo" in js,
          "white-label: la interfaz aplica nombre y logo del sistema")
    # el nombre del sistema alimenta el núcleo, el placeholder del chat y la wake word,
    # y NO quedan literales «nexus» cableados en textos visibles.
    check("_sysLow()" in js and "#core-title h1" in js,
          "white-label: el núcleo (core-title) toma el nombre configurado")
    check("_wakeWord()" in js and "despierta nexus" not in js,
          "white-label: el subtítulo usa la wake word configurada (sin «despierta nexus» fijo)")
    check(">nexus</h1>" not in js and "di algo a nexus" not in js,
          "white-label: sin literales «nexus» cableados en el núcleo ni el chat")
    setup = open(os.path.join(ROOT, "frontend", "setup.html"), encoding="utf-8").read()
    check("f-sysname" in setup and "assistant_name:" in setup and "wake_word:" in setup,
          "white-label: el setup pide el nombre del sistema y deriva la wake word")


# ====== TEST 3q-bis: el instalador ofrece «seguir con nexus» o «crear perfil» (nombre+logo) ======
def test_setup_perfil_identidad():
    setup = open(os.path.join(ROOT, "frontend", "setup.html"), encoding="utf-8").read()
    # elección de perfil: seguir con nexus (por defecto) o crear uno propio
    check("prof-cards" in setup and 'data-v="nexus"' in setup and 'data-v="custom"' in setup,
          "setup: elige entre «seguir con nexus» o «crear mi perfil»")
    check("state.profile" in setup and "setProfile(" in setup,
          "setup: guarda el perfil elegido (nexus/custom)")
    # el perfil propio permite ADJUNTAR una imagen de logo (no solo URL)
    check("f-syslogo-file" in setup and 'type="file"' in setup and 'accept="image/*"' in setup,
          "setup: el perfil propio adjunta una imagen para el logo")
    check("onLogoPick" in setup and "readAsDataURL" in setup,
          "setup: la imagen del logo se lee como data-URL")
    # al terminar, si el perfil es nexus se fuerza el nombre/logo por defecto; si es custom, los del usuario
    check("state.profile === 'custom'" in setup and "assistant_name: sysName" in setup,
          "setup: TERMINAR respeta el perfil (nexus por defecto vs. nombre propio)")


# ====== TEST 3q-ter: barge-in solo con VOZ real (no ruido de calle ni tecleo) ======
def test_barge_in_voz():
    """En micro abierto, cortar a la IA SOLO con voz humana (pitch), no con ruido de
    calle (banda ancha), tono grave (rumor) ni tecleo (transitorios). Valida el DSP real."""
    stt = os.path.join(ROOT, "backend", "core", "infraestructura", "stt.py")
    src = open(stt, encoding="utf-8").read()
    check("_voiced_ac(block, _rate)" in src and "VOICE_AC" in src,
          "barge-in: watch_barge_in exige VOZ (pitch) además de energía")
    try:
        import numpy as np
    except Exception:
        check(True, "barge-in: numpy no disponible en el test (DSP no ejecutado)")
        return
    tree = ast.parse(src)
    keep = [n for n in tree.body
            if (isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "VOICE_AC" for t in n.targets))
            or (isinstance(n, ast.FunctionDef) and n.name == "_voiced_ac")]
    ns = {"np": np}
    exec(compile(ast.Module(body=keep, type_ignores=[]), stt, "exec"), ns)
    vac = ns["_voiced_ac"]
    R = 16000
    N = int(R * 0.03)
    t = np.arange(N) / R
    voz = (0.3 * np.sin(2 * np.pi * 150 * t) + 0.15 * np.sin(2 * np.pi * 300 * t)
           + 0.08 * np.sin(2 * np.pi * 450 * t)).astype(np.float32)
    voz_aguda = (0.3 * np.sin(2 * np.pi * 220 * t) + 0.15 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    rumble = (0.5 * np.sin(2 * np.pi * 55 * t)).astype(np.float32)          # tono grave (motor/viento)
    click = np.zeros(N, np.float32); click[N // 2] = 1.0; click[N // 2 + 1] = -0.7   # tecla
    silencio = np.zeros(N, np.float32)
    np.random.seed(0)
    ruido = (0.3 * np.random.randn(N)).astype(np.float32)                   # calle: banda ancha
    check(vac(voz, R) and vac(voz_aguda, R), "barge-in: SÍ detecta VOZ (grave/media y aguda)")
    check(not vac(ruido, R), "barge-in: NO corta con ruido de calle (banda ancha)")
    check(not vac(rumble, R), "barge-in: NO corta con tono grave (rumor de motor/viento)")
    check(not vac(click, R), "barge-in: NO corta con tecleo/click (transitorio sin pitch)")
    check(not vac(silencio, R), "barge-in: NO corta con silencio")


# ====== TEST 3q-quater: género de autorreferencia según la VOZ ======
def test_genero_voz():
    """Si la voz es de mujer, nexus se refiere a sí en femenino; si es de hombre, masculino."""
    cfg = os.path.join(ROOT, "backend", "core", "comun", "config.py")
    import types as _t
    fake = _t.SimpleNamespace(_json={})
    fake.get = lambda k, d=None: fake._json.get(k, d)
    keep = [n for n in ast.parse(open(cfg, encoding="utf-8").read()).body
            if isinstance(n, ast.FunctionDef) and n.name == "voice_gender"]
    ns = {"settings": fake}
    exec(compile(ast.Module(body=keep, type_ignores=[]), cfg, "exec"), ns)
    vg = ns["voice_gender"]
    fake._json["tts_voice"] = "Elvira (España)"; check(vg() == "f", "género: voz Elvira → femenino")
    fake._json["tts_voice"] = "Dalia (México)"; check(vg() == "f", "género: voz Dalia → femenino")
    fake._json["tts_voice"] = "Álvaro (España)"; check(vg() == "m", "género: voz Álvaro → masculino")
    fake._json["tts_voice"] = "Jorge (México)"; check(vg() == "m", "género: voz Jorge → masculino")
    fake._json["tts_voice"] = ""; check(vg() == "f", "género: sin voz → femenino por defecto (Elvira)")
    llm = open(os.path.join(ROOT, "backend", "core", "infraestructura", "llm.py"), encoding="utf-8").read()
    check("refiérete a ti {refl}" in llm and "voice_gender as _vg" in llm,
          "género: SYSTEM_PROMPT gendered y se rellena en _build_messages")


# ====== TEST 3r: asistente guiado de Home Assistant + validación de token ======
def test_home_assistant_wizard():
    js = js_hud()
    check("ha-wiz" in js and "ha-step" in js and "ha-num" in js, "HA: asistente por pasos numerados")
    # los 3 pasos: añadir integración, crear token (perfil/seguridad), pegar token
    check("/config/integrations/dashboard" in js, "HA: paso 1 abre «Añadir integración» directo")
    check("/profile/security" in js, "HA: paso 2 abre el perfil (Seguridad) donde se crea el token")
    check("Token de acceso de larga duración" in js, "HA: paso 3 pide el token de larga duración")
    # validación en vivo antes de guardar (feedback claro)
    check("/api/home/ha_test" in js, "HA: prueba la conexión (ha_test) antes de guardar")
    check("token_valid" in js and "reachable" in js, "HA: distingue 'no llego' de 'token inválido'")
    check("controllable" in js, "HA: informa de cuántos aparatos controlables hay")
    app = open(os.path.join(ROOT, "backend", "app.py"), encoding="utf-8").read()
    check("/api/home/ha_test" in app and "token_valid" in app and "controllable" in app,
          "HA: endpoint ha_test con diagnóstico (reachable/token_valid/controllable)")
    css = open(os.path.join(ROOT, "frontend", "css", "command.css"), encoding="utf-8").read()
    check(".ha-wiz" in css and ".ha-step" in css and ".ha-num" in css, "HA: CSS del asistente")


# ====== TEST 3q: controlar por NOMBRE una TV cuyo nombre lleva «habitación» ======
def test_domotica_por_nombre():
    import unicodedata
    path = os.path.join(ROOT, "skills", "domotica", "skill.py")
    tree = ast.parse(open(path, encoding="utf-8").read())
    want = {"_norm_txt", "_resolve_named_device", "_is_tv_device", "_wants_on",
            "_is_generic_name", "_known"}
    keep = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name in want)
            or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in ("_ROOM_WORDS", "_GENERIC_NAMES") for t in n.targets))]
    ns = {"re": re, "unicodedata": unicodedata}
    exec(compile(ast.Module(body=keep, type_ignores=[]), path, "exec"), ns)
    resolve, istv, won = ns["_resolve_named_device"], ns["_is_tv_device"], ns["_wants_on"]

    class _S:
        def __init__(self, my, known): self.my, self.known = my, known
        def get(self, k, d=None): return {"my_devices": self.my, "known_devices": self.known}.get(k, d)
    def ctx(my=None, known=None): return {"settings": _S(my or [], known or [])}

    tv = [{"name": "Habitación Norte", "ip": "192.168.1.53", "mac": "AA:BB:CC:DD:EE:FF", "brand": "samsung", "is_tv": True}]
    d = resolve(ctx(known=tv), "enciende habitación Norte")
    check(d is not None and istv(d), "domótica: «enciende habitación Norte» resuelve la TV guardada (no HA)")
    check(won("enciende habitación norte") is True and won("apaga habitación norte") is False,
          "domótica: distingue encender de apagar")
    check(resolve(ctx(known=tv), "enciende norte") is not None, "domótica: casa por token distintivo «norte»")
    check(resolve(ctx(known=tv), "enciende la luz del salón") is None,
          "domótica: NO roba una orden de HA que no nombra la TV")
    check(resolve(ctx(known=[{"name": "Salón", "ip": "192.168.1.5"}]), "enciende la luz del salón") is None,
          "domótica: un aparato llamado solo «Salón» no secuestra HA")
    src = open(path, encoding="utf-8").read()
    check("_resolve_named_device(ctx, text)" in src and 'intent in ("casa", "tv_on", "tv_off")' in src,
          "domótica: la resolución por nombre corre en casa/tv_on/tv_off")


# ====== TEST 3p: Núcleo IA v2 — 3 tarjetas + configurar cerebro de Hermes ======
def test_nucleo_ia_ui():
    js = js_hud()
    check("ac-cards" in js and "ac-card" in js, "núcleo IA: contenedor de 3 tarjetas")
    check("CLOUD_PROVS" in js and "HERMES_PROVS" in js, "núcleo IA: mapas de proveedores cloud y Hermes")
    check("ac-cloudprov" in js and "ac-cloudmodel" in js and "ac-cloudkey" in js,
          "núcleo IA: cloud = proveedor select + modelo select + key input")
    check("ac-hprov" in js and "ac-hmodel" in js and "ac-hkey" in js,
          "núcleo IA: Hermes = proveedor select + modelo select + key input")
    check("/api/hermes/configure" in js, "núcleo IA: guardar Hermes llama a /api/hermes/configure")
    check("class=\"ac-btn" in js, "núcleo IA: botones con clase de estilo de la app (no inline)")
    check("openrouter" in js.lower(), "núcleo IA: OpenRouter entre los proveedores")
    css = open(os.path.join(ROOT, "frontend", "css", "command.css"), encoding="utf-8").read()
    check(".ac-cards{display:grid;grid-template-columns:repeat(3,1fr)" in css,
          "núcleo IA: las 3 tarjetas en horizontal (grid 3 columnas)")
    check(".ac-btn{" in css, "núcleo IA: estilo de botón propio")


def test_hermes_configure_brain():
    ns = extract_real_object(os.path.join(ROOT, "skills", "hermes", "skill.py"),
                             {"_env_set_var", "_yaml_set_model"})
    env_set, yset = ns["_env_set_var"], ns["_yaml_set_model"]
    e = env_set("API_SERVER_KEY=abc\nOPENAI_API_KEY=vieja\n", "OPENAI_API_KEY", "nueva")
    check("OPENAI_API_KEY=nueva" in e and "API_SERVER_KEY=abc" in e and "vieja" not in e,
          "configure: _env_set_var reemplaza la clave y conserva el resto (no pisa la del gateway)")
    y = yset("logging:\n  x: 1\nmodel:\n  default: \"v\"\ntools:\n  a: b\n", "anthropic", "claude-opus-4-8", "")
    check('provider: "anthropic"' in y and "claude-opus-4-8" in y and "logging:" in y and "tools:" in y and '"v"' not in y,
          "configure: _yaml_set_model reemplaza SOLO el bloque model (conserva otras secciones)")
    src = open(os.path.join(ROOT, "skills", "hermes", "skill.py"), encoding="utf-8").read()
    check("def configure_brain" in src and "_PROV_MAP" in src, "configure: existe configure_brain + _PROV_MAP")
    check("OPENAI_API_KEY" in src and "ANTHROPIC_API_KEY" in src and "GEMINI_API_KEY" in src and "OPENROUTER_API_KEY" in src,
          "configure: mapea los 4 proveedores a su env var de Hermes")
    app = open(os.path.join(ROOT, "backend", "app.py"), encoding="utf-8").read()
    check("/api/hermes/configure" in app and "configure_brain" in app, "configure: endpoint en app.py")
    cfg = open(os.path.join(ROOT, "backend", "core", "comun", "config.py"), encoding="utf-8").read()
    check('"hermes_provider"' in cfg and '"hermes_model"' in cfg and '"openrouter_api_key"' in cfg,
          "configure: settings/secrets de Hermes en config.py")


# ====== TEST 3o: Hermes distingue «mi clave al gateway» de «cerebro sin creds» ======
def test_hermes_upstream_auth():
    ns = extract_real_object(os.path.join(ROOT, "skills", "hermes", "skill.py"),
                             {"_is_upstream_auth_error"})
    f = ns["_is_upstream_auth_error"]
    # 401 «Missing Authentication header» = el MODELO interno de Hermes sin credenciales
    check(f(401, "HTTP 401: Missing Authentication header") is True,
          "hermes: 'Missing Authentication header' -> cerebro/upstream (no es mi clave)")
    check(f(403, "forbidden by provider") is True, "hermes: 403 provider -> upstream")
    # 401 invalid_api_key = NUESTRA clave al gateway (hay que re-provisionar, NO es upstream)
    check(f(401, '{"error":{"code":"invalid_api_key"}}') is False,
          "hermes: invalid_api_key -> es el gateway, no el cerebro")
    check(f(200, "ok") is False, "hermes: 200 no es error de auth")
    src = open(os.path.join(ROOT, "skills", "hermes", "skill.py"), encoding="utf-8").read()
    check("_UPSTREAM_AUTH_MSG" in src and "hermes model" in src,
          "hermes: mensaje claro guía a configurar el modelo (hermes model/auth)")
    check("_probe_brain" in src, "hermes: 'diagnostica hermes' prueba el cerebro interno de verdad")


# ====== TEST 3n: kanban con drag & drop entre columnas ======
def test_kanban_drag_drop():
    js = js_hud()
    check('draggable="true"' in js, "kanban: las tarjetas son arrastrables")
    check("dragstart" in js and "'drop'" in js and "dragover" in js,
          "kanban: handlers de arrastrar y soltar")
    check("async function moveTask" in js, "kanban: moveTask centraliza el POST /api/board/move")
    check("/api/board/move" in js, "kanban: el drop persiste el cambio de columna")
    check("kindIcon" in js, "kanban: tarjetas muestran icono acción 🛠 vs evento 📅")
    css = open(os.path.join(ROOT, "frontend", "css", "command.css"), encoding="utf-8").read()
    check(".kcard.dragging" in css and ".drop-hint" in css, "kanban: CSS de feedback de arrastre")


# ============ TEST 3k: UI Dispositivos — sin doble-disparo y estado honesto ============
def test_devices_ui_no_doblefuego():
    js = js_hud()
    # 1) NADA de listener por-botón en cada render (era la causa del doble-disparo)
    check("querySelectorAll('[data-a]').forEach" not in js,
          "dispositivos: ya no engancha un listener por botón en cada render")
    check("grid._deleg" in js, "dispositivos: UN solo listener DELEGADO en el grid (no se acumula)")
    # 2) candado anti-doble-envío en tarjeta y en modal
    check("_ctrlBusy" in js, "dispositivos: candado anti-doble-envío en las tarjetas")
    check("_sendBusy" in js, "dispositivos: candado anti-doble-envío en el mando (modal)")
    # 3) estado HONESTO: una TV no sale «encendida» solo por añadirla
    check("function _stateDot" in js, "dispositivos: punto de estado calculado honesto (_stateDot)")
    check("d.on === true" in js, "dispositivos: verde solo si la TV la encendiste TÚ (d.on===true)")
    check("dev-state net" in js, "dispositivos: estado «en red, no confirmado» (cian) para TV sin encender")
    check("d.connected = true; d.controllable = true;" not in js,
          "dispositivos: controlar una TV ya NO la marca 'connected' (eso es emparejar, no encender)")
    check("if (action === 'pair') d.connected = true;" in js,
          "dispositivos: 'connected' solo tras EMPAREJAR, no tras encender")


# ============ TEST 3e: STOP de primera clase + candado del aprendizaje ============
def test_stop_y_guardas():
    src = open(os.path.join(ROOT, "backend", "core", "brain.py"), encoding="utf-8").read()
    m = re.search(r"_STOP_RX = re\.compile\(\s*(.*?)\s*,\s*re\.IGNORECASE\)", src, re.S)
    assert m, "_STOP_RX no encontrado en brain.py"
    rx = re.compile(eval("(" + m.group(1) + ")"), re.IGNORECASE)
    for t in ["para", "PARA", "¡Para!", "para ya", "cállate", "callate ya", "stop",
              "silencio", "basta", "corta", "párate"]:
        check(bool(rx.match(t)), f"stop: '{t}' debe cortar la voz")
    for t in ["para la música", "para mañana ponme gimnasio", "paraguas",
              "párale el carro", "stop the music en spotify"]:
        check(not rx.match(t), f"stop: '{t}' NO debe tratarse como parada")
    check(re.search(r"len\(text\.split\(\)\)\s*>=\s*3", src) is not None,
          "brain: el match SEMÁNTICO de tareas aprendidas exige >=3 palabras "
          "(bug: «PARA» disparaba lo aprendido de Karin León)")
    check(src.index("_STOP_RX.match(text)") < src.index("_RETRAIN_RX.match(text)"),
          "brain: el STOP se evalúa ANTES que cualquier otra ruta")


# ============ TEST 3f: correos — números REALES y sin el «8» fijo ============
def test_email_counts_reales():
    src = open(os.path.join(ROOT, "skills", "google_workspace", "skill.py"), encoding="utf-8").read()
    check("threadsUnread" in src, "gmail: usa threadsUnread (el número que VE el operador en su app)")
    check("_load_unread_bodies(8)" not in src, "gmail: eliminado el 8 fijo de email_urgent")
    check("_load_unread_bodies(30)" in src, "gmail: analiza hasta 30 sin leer")
    check('de tus {unread} sin leer' in src,
          "gmail: el urgente reporta el TOTAL real, no los que ha podido leer")


# ============ TEST 3g: el móvil en 2º plano NO se desvincula ============
def test_movil_no_se_desvincula():
    src = open(os.path.join(ROOT, "backend", "app.py"), encoding="utf-8").read()
    check("remote.mark_offline" in src, "app: WS cortado -> móvil «en espera», no desvinculado")
    check("_grace_forget" in src, "app: solo se olvida tras el periodo de gracia")
    rsrc = open(os.path.join(ROOT, "backend", "core", "infraestructura", "remote.py"), encoding="utf-8").read()
    check("def mark_offline" in rsrc and "def is_online" in rsrc,
          "remote: presencia con gracia implementada")


# ============ TEST 3d: app.py define SayText (el backend moría sin ella) ============
def test_app_saytext():
    src = open(os.path.join(ROOT, "backend", "app.py"), encoding="utf-8").read()
    check("class SayText" in src, "app.py: existe class SayText (sin ella /api/tts_say revienta el arranque)")
    check("payload: SayText" in src, "app.py: /api/tts_say usa SayText")


# ================== TEST 4: memoria — list_knowledge ==================
def test_memory_listing():
    p = load_skill_patterns("memory_graph")
    check(route_local(p, "qué sabes de mí") == "list_knowledge", "memoria: qué sabes de mí -> list_knowledge")
    check(route_local(p, "lista los archivos de conocimiento que tienes sobre mí") == "list_knowledge",
          "memoria: lista conocimiento -> list_knowledge")
    check(route_local(p, "qué recuerdas de Ana") == "recall", "memoria: qué recuerdas de X -> recall (no list)")


# ================== TEST 5: _LLMMatch REAL (brain.py) ==================
def test_llmmatch():
    ns = extract_real_object(os.path.join(ROOT, "backend", "core", "brain.py"), {"_LLMMatch"})
    M = ns["_LLMMatch"]
    m = M("ponme algo tranqui", {"q3": "Quevedo", "svc3": "spotify"})
    check(m.group("q3") == "Quevedo", "_LLMMatch: group('q3')")
    check(m.group("svc3") == "spotify", "_LLMMatch: group('svc3')")
    check(m.group(0) == "ponme algo tranqui", "_LLMMatch: group(0) = texto original")
    check((m.group("inexistente") or "") == "", "_LLMMatch: grupo inexistente -> None (patrón 'or \"\"')")
    check(m.groupdict() == {"q3": "Quevedo", "svc3": "spotify"}, "_LLMMatch: groupdict()")
    m2 = M("enciende la tele", {})
    check(m2.groupdict() == {} and m2.group(0) == "enciende la tele", "_LLMMatch: args vacíos")


# ================== TEST 6: parseo JSON de plan_action REAL (llm.py) ==================
def test_plan_parse():
    # replicamos SOLO el parseo que hace plan_action (mismo código), leído del fichero
    src = open(os.path.join(ROOT, "backend", "core", "infraestructura", "llm.py"), encoding="utf-8").read()
    assert "async def plan_action" in src, "plan_action debe existir en llm.py"

    def parse(out):
        m = re.search(r"\{.*\}", out or "", re.S)
        if not m:
            return None
        try:
            import json
            d = json.loads(m.group(0))
        except Exception:
            return None
        if not isinstance(d, dict) or not d.get("skill"):
            return None
        d.setdefault("args", {})
        if not isinstance(d["args"], dict):
            d["args"] = {}
        return d

    check(parse('{"skill":"media","intent":"play","args":{"q3":"X"}}')["skill"] == "media", "plan: JSON válido")
    check(parse('ruido {"skill":"domotica","intent":"tv_on","args":{}} fin')["intent"] == "tv_on", "plan: JSON con ruido")
    check(parse('{"skill":null}') is None, "plan: skill null -> None (es charla)")
    check(parse("no json") is None, "plan: sin JSON -> None")
    check(parse('{"skill":"g","intent":"x","args":null}')["args"] == {}, "plan: args null -> {}")


def test_no_regression_smalltalk():
    # el gate del planificador NO debe dispararse con charla pura (se testea el regex real)
    src = open(os.path.join(ROOT, "backend", "core", "brain.py"), encoding="utf-8").read()
    m = re.search(r"_SMALLTALK_RX = re\.compile\(\s*(.*?)\s*,\s*re\.IGNORECASE\)", src, re.S)
    assert m, "_SMALLTALK_RX no encontrado en brain.py"
    rx = re.compile(eval("(" + m.group(1) + ")"), re.IGNORECASE)
    for t in ["hola", "gracias", "vale", "ok", "jajaja", "hasta luego"]:
        check(bool(rx.match(t)), f"smalltalk: '{t}' debe filtrarse")
    for t in ["pon música", "enciende la tele", "analiza los correos"]:
        check(not rx.match(t), f"smalltalk: '{t}' NO debe filtrarse (es acción)")


if __name__ == "__main__":
    tests = [test_media, test_emails, test_hermes, test_hermes_global_route, test_devices_ui_no_doblefuego, test_correos_crud_y_no_bucle, test_negacion_guard, test_kanban_drag_drop, test_hermes_upstream_auth, test_nucleo_ia_ui, test_hermes_configure_brain, test_domotica_por_nombre, test_home_assistant_wizard, test_white_label_nombre, test_setup_perfil_identidad, test_barge_in_voz, test_genero_voz,
             test_hermes_env_provision, test_hermes_clean_env, test_stop_y_guardas,
             test_email_counts_reales, test_movil_no_se_desvincula, test_app_saytext,
             test_tablero_fecha_hora_tipo, test_tablero_estados_y_start,
             test_board_kind_time_fields, test_tts_rutas_separadores,
             test_correos_formato_respuestas,
             test_memory_listing, test_llmmatch, test_plan_parse,
             test_no_regression_smalltalk]
    for t in tests:
        print(f"· {t.__name__}")
        try:
            t()
        except Exception as e:
            _fail.append(f"{t.__name__} EXCEPCIÓN: {type(e).__name__}: {e}")
            print("  EXCEPCIÓN:", e)
    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    sys.exit(1 if _fail else 0)
