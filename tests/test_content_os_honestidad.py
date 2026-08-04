# -*- coding: utf-8 -*-
"""CONTENT OS — HONESTIDAD (entrega A: procedencia, generador y enrutado).

EL INCIDENTE (01/08/2026). Al auditar Content OS se vio que la skill contestaba
esto EN EL CHAT cuando no había token de Instagram:

    📊 Instagram (ejemplo — conecta tu cuenta en ⚙ para datos reales):
    • Seguidores: 12.840 (+3,2% 30 días)
    • Alcance mensual: 184,2K (+18,4%)
    • Retención media Reels: 48,6%
    • Señal: el gancho de 'resultado visible' va por encima de tu mediana en 4
      de 8 reels. Repítelo cambiando el tema.

Lo grave no son las cifras: es la ÚLTIMA LÍNEA. Es una conclusión estadística
—una mediana que nadie ha calculado, sobre 8 reels que no existen— presentada
como hallazgo. La coletilla «(ejemplo…)» no salva nada: el resto del texto la
contradice, y sale por el canal donde el usuario más habla.

Es exactamente el mismo fallo que motivó la REGLA INVIOLABLE de
`backend/core/llm.py`, pero cometido por NOSOTROS en código, no por el modelo.

Lo que se comprueba aquí es lo que se puede romper sin darse cuenta:
  · que ninguna cifra viaje sin decir de dónde sale (`procedencia.dato`),
  · que los datos de demostración vivan aparte y etiquetados,
  · que los umbrales y textos salgan de config/umbrales.json y no del código,
  · que el validador determinista tumbe «48,6 %» y deje pasar «3 golpes»,
  · que `generate()` no publique una cifra que el modelo se haya inventado,
  · que la respuesta del chat ya no mienta,
  · que `inspire` no descargue contenido ajeno por ningún camino,
  · y que «cómo va el instagram» llegue a quien sabe contestarlo.

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_content_os_honestidad.py
"""
import ast
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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


if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Arenero: ni data/contentos.json ni data/inspiration ni los ajustes REALES del
# usuario se tocan. config/umbrales.json sí se copia tal cual, porque parte de
# lo que se prueba es que el archivo de verdad trae la sección y sirve.
_SAND = Path(tempfile.mkdtemp(prefix="nexus_cos_"))
(_SAND / "data").mkdir()
(_SAND / "config").mkdir()
(_SAND / "config" / "settings.json").write_text(json.dumps({
    "setup_done": True, "llm_provider": "mock", "operator_name": "Operador"}),
    encoding="utf-8")
shutil.copy(ROOT / "config" / "umbrales.json", _SAND / "config" / "umbrales.json")
os.environ["NEXUS_DATA_DIR"] = str(_SAND / "data")
os.environ["NEXUS_CONFIG_DIR"] = str(_SAND / "config")

import importlib.util                                              # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "cosskill", ROOT / "skills" / "content_os" / "skill.py")
co = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(co)

from backend.core.comun.config import settings                           # noqa: E402
from backend.core.skills_loader import load_skills, route          # noqa: E402
from _frontend_js import js_hud  # el HUD entero, no solo command.js

CTX = {"settings": settings, "graph": None, "pg": None, "bus": None}
SKILL_PY = (ROOT / "skills" / "content_os" / "skill.py").read_text(encoding="utf-8")


def run(c):
    return asyncio.new_event_loop().run_until_complete(c)


class _GrafoFalso:
    """El grafo real escribe notas en disco; aquí solo hace falta que exista."""

    def __init__(self):
        self.notas = []

    def write_note(self, titulo, cuerpo):
        self.notas.append((titulo, cuerpo))

    def search(self, q, n=3):
        return []


# ══════════════ 1. El sobre de procedencia ══════════════
def test_sobre():
    print("· ninguna cifra viaja suelta: la fábrica exige un origen válido")
    from backend.core.comun import procedencia as pr

    d = pr.dato(12840, pr.MEDIDO, periodo="30 días", delta=3.2)
    check(d["valor"] == 12840 and d["origen"] == pr.MEDIDO,
          "dato() devuelve valor y origen")
    check(d["periodo"] == "30 días" and d["delta"] == 3.2,
          "y arrastra periodo y delta dentro del mismo sobre")
    check(set(d) == {"valor", "origen", "periodo", "delta", "n", "aviso"},
          f"con la forma exacta del contrato (vi {sorted(d)})")

    # Un origen mal escrito es una cifra sin procedencia disfrazada de cifra con
    # procedencia: es peor que no tener sobre. Falla en el sitio, no río abajo.
    for malo in ("estimado", "MEDIDO", "", None, "demostracion"):
        try:
            pr.dato(1, malo)
            check(False, f"origen {malo!r} tendría que lanzar ValueError")
        except ValueError:
            _ok = True
            check(True, f"origen {malo!r} lanza ValueError")

    check(pr.dato(None, pr.SIN_DATOS, aviso="la Graph API no lo da")["valor"] is None,
          "un KPI sin dato se puede expresar: valor None con su motivo")
    check(pr.ORIGENES == (pr.MEDIDO, pr.DEMOSTRACION, pr.SIN_DATOS),
          "y solo hay tres orígenes posibles, no una lista abierta")


# ══════════════ 2. Umbrales fuera del código ══════════════
def test_umbrales():
    print("· los números y los textos salen de config/umbrales.json")
    from backend.core.comun import procedencia as pr

    datos = json.loads((ROOT / "config" / "umbrales.json").read_text(encoding="utf-8"))
    sec = datos.get("content_os") or {}
    check(bool(sec), "config/umbrales.json tiene la sección «content_os»")
    check("_que_es" in sec or "_lee_esto" in sec, "y explicada, como el resto del archivo")
    check(isinstance(sec.get("n_minimo"), int), "con n_minimo entero")
    check(isinstance((sec.get("validador") or {}).get("magnitud_minima"), (int, float)),
          "y validador.magnitud_minima")
    check(isinstance(sec.get("textos"), dict) and bool(sec["textos"]),
          "y los textos de estado vacío, que hoy están a fuego en el código")

    u = pr.umbrales()
    check(u["n_minimo"] == sec["n_minimo"], "el lector devuelve lo que pone el archivo")

    # «Cambia un número, cambia la lectura» tiene que ser verdad, no un eslogan.
    normal = pr.sin_cifras_inventadas("hazlo en 3 golpes", ())
    estricto = pr.sin_cifras_inventadas("hazlo en 3 golpes", (),
                                        umbrales=pr.umbrales({"validador": {"magnitud_minima": 2}}))
    check(normal is True and estricto is False,
          "bajar validador.magnitud_minima cambia el veredicto sin tocar código")

    # Una política que se relaja sola cuando falta el archivo no es una política.
    import backend.core.comun.procedencia as _pr
    orig = _pr.CONFIG_DIR
    try:
        _pr.CONFIG_DIR = ROOT / "no-existe-esta-carpeta"
        _pr._cache_umbrales = None
        v = _pr._carga_umbrales_content_os()
        check(v["validador"]["magnitud_minima"] == _pr._RESERVA["validador"]["magnitud_minima"],
              "sin archivo se usa la reserva, no se abre la mano")
    finally:
        _pr.CONFIG_DIR = orig
        _pr._cache_umbrales = None


# ══════════════ 3. La demo, aparte y etiquetada ══════════════
def test_demo():
    print("· los datos de demostración viven en su propio módulo y se declaran")
    from backend.core import contentos_demo
    from backend.core.comun import procedencia as pr

    m = contentos_demo.metricas()
    check(m.get("origen") == pr.DEMOSTRACION,
          "metricas() estampa origen=demostración en el propio retorno")
    check(m.get("real") is False, "y sigue diciendo real=False, como antes")
    check(len(m.get("posts") or []) > 0 and m.get("followers"),
          "con el mismo contenido que tenía _demo_metrics()")

    # El criterio que hace posible «un día esto se borra de un tirón»: los
    # números de mentira no pueden seguir viviendo en el módulo de verdad.
    texto = (ROOT / "backend" / "core" / "contentos.py").read_text(encoding="utf-8")
    for literal in ("12840", "184200", "marca.personal"):
        check(literal not in texto,
              f"el literal de demostración {literal!r} ya no está en contentos.py")


# ══════════════ 4. El validador determinista ══════════════
def test_validador():
    print("· el validador tumba la cifra inventada y deja trabajar al resto")
    from backend.core.comun import procedencia as pr

    check(pr.sin_cifras_inventadas("tus reels tienen 48,6 % de retención", ()) is False,
          "«48,6 % de retención» se rechaza (decimal + porcentaje, sin fundamento)")
    check(pr.sin_cifras_inventadas("3 golpes y un CTA", ()) is True,
          "«3 golpes y un CTA» pasa: un entero pequeño no es una métrica")
    check(pr.sin_cifras_inventadas("GANCHO de 2 segundos, 3 golpes, CTA", ()) is True,
          "la estructura de un guion pasa entera")
    check(pr.sin_cifras_inventadas("ganaste 12.840 seguidores", ()) is False,
          "un separador de millares delata una métrica inventada")
    check(pr.sin_cifras_inventadas("el alcance subió un 18,4%", ()) is False,
          "y un porcentaje con decimal, también")
    check(pr.sin_cifras_inventadas("tienes 184.200 de alcance", (184200,)) is True,
          "pero si la cifra SÍ venía en los datos de entrada, pasa")
    check(pr.sin_cifras_inventadas("retención del 48,6 %", (48.6,)) is True,
          "aunque lleve decimal y porcentaje: lo que manda es de dónde sale")

    malas = pr.cifras_no_fundamentadas("48,6 % sobre 12.840 seguidores", ())
    check(len(malas) == 2, f"y se puede decir CUÁLES sobran (vi {malas})")


# ══════════════ 5. La regla inviolable llega al generador ══════════════
def test_regla():
    print("· la REGLA INVIOLABLE sigue viajando aunque se pase un system a medida")
    from backend.core.infraestructura import llm

    check(isinstance(getattr(llm, "REGLA_CONTENT_OS", None), str)
          and "DATOS" in llm.REGLA_CONTENT_OS,
          "llm.py exporta REGLA_CONTENT_OS y habla del bloque DATOS")

    # La regresión que rompería todo en silencio: alguien mueve el `base =
    # system or SYSTEM_PROMPT` por debajo de la regla y los prompts a medida
    # (los de Content OS) dejan de heredarla sin que falle nada.
    msgs = llm._build_messages("lo que sea", system="soy un system a medida")
    sistema = msgs[0]["content"]
    check(msgs[0]["role"] == "system", "el primer mensaje sigue siendo el system")
    check("soy un system a medida" in sistema, "que respeta el system recibido")
    check("REGLA INVIOLABLE" in sistema,
          "y le concatena la REGLA INVIOLABLE igualmente")
    check("TAMPOCO TE INVENTAS LO QUE ERES" in sistema,
          "y su segunda mitad")


def test_generate_real():
    print("· generate() no publica una cifra que el modelo se haya inventado")
    from backend.core import contentos
    import backend.core.infraestructura.llm as llm

    visto = {}
    original = llm.ask_llm

    async def _falso_mentiroso(user_text, context=None, system=None):
        visto["system"] = system or ""
        visto["user"] = user_text
        return ("Tus reels tienen 48,6 % de retención y 12.840 seguidores.", "mock")

    async def _falso_honesto(user_text, context=None, system=None):
        visto["system"] = system or ""
        return ("GANCHO: el error que te cuesta 2 horas. Desarrollo en 3 golpes. CTA.", "mock")

    try:
        llm.ask_llm = _falso_mentiroso
        texto = run(contentos.generate("script", "automatización"))
        check("48,6" not in texto and "12.840" not in texto,
              f"la cifra inventada no llega al usuario (vi {texto[:60]!r})")
        check("DATOS" in visto.get("system", ""),
              "y el system que se le manda al modelo lleva el bloque DATOS")

        # Y tampoco se guarda: una idea inventada en disco es peor que en pantalla.
        antes = json.loads((_SAND / "data" / "contentos.json").read_text(encoding="utf-8")
                           ) if (_SAND / "data" / "contentos.json").exists() else {}
        run(contentos.generate("idea", "automatización"))
        despues = json.loads((_SAND / "data" / "contentos.json").read_text(encoding="utf-8")
                             ) if (_SAND / "data" / "contentos.json").exists() else {}
        nuevas = [i for i in (despues.get("ideas") or []) if i not in (antes.get("ideas") or [])]
        check(all("48,6" not in str(i) for i in nuevas),
              "la idea con cifra inventada no se guarda en data/contentos.json")

        llm.ask_llm = _falso_honesto
        limpio = run(contentos.generate("script", "automatización"))
        check("3 golpes" in limpio,
              "y un guion sin cifras raras sale INTACTO (el validador no censura de más)")
    finally:
        llm.ask_llm = original


# ══════════════ 6. El chat ya no miente ══════════════
def test_analytics_honesto():
    print("· sin token, «analítica de instagram» dice la verdad")
    m = co.SKILL["patterns"]
    r = run(co.handle("analytics", "analítica de instagram", None, CTX))
    reply = r["reply"]

    for mentira in ("12.840", "184,2K", "48,6", "4 de 8", "mediana"):
        check(mentira not in reply,
              f"la respuesta ya no contiene {mentira!r}")
    check("ejemplo" not in reply.lower(),
          "ni se escuda en la coletilla «(ejemplo…)», que el resto del texto contradecía")
    check("ig_access_token" in reply or "⚙" in reply,
          "y dice qué falta para tener datos de verdad")
    check("instagram" in reply.lower(), "sin dejar de hablar de lo que se le pregunta")


# ══════════════ 7. inspire: nada de scraping ══════════════
def test_inspire_politica():
    print("· inspire explica la política y reencamina a business_discovery")
    r = run(co.handle("inspire", "analiza este reel de @creador https://instagram.com/reel/x",
                      co.SKILL and _match("inspire",
                                          "analiza este reel de @creador https://instagram.com/reel/x"),
                      CTX))
    reply = r["reply"].lower()
    check("business_discovery" in reply or "graph api" in reply,
          "la respuesta cita la vía oficial (Graph API / business_discovery)")
    check("no" in reply and ("descarg" in reply or "scraping" in reply or "transcrib" in reply),
          "y dice explícitamente que no se descarga contenido ajeno")

    # No se crea NADA en data/inspiration: la política es no descargar, no
    # «descargar y avisar».
    insp = Path(co.INSP_DIR)
    check(not insp.exists() or not list(insp.glob("*.json")),
          "y no se ha creado ningún fichero nuevo en data/inspiration/")

    print("· y la vía de descarga está cerrada con llave, no solo sin usar")
    try:
        co._download_and_transcribe("https://instagram.com/reel/x")
        check(False, "_download_and_transcribe tendría que lanzar RuntimeError")
    except RuntimeError as exc:
        check("polít" in str(exc).lower() or "retirada" in str(exc).lower(),
              "_download_and_transcribe falla cerrado explicando el motivo")
    except Exception as exc:
        check(False, f"_download_and_transcribe lanzó {type(exc).__name__}, no RuntimeError")

    # Que NADIE la llame desde el handler: la comprobación de arriba solo cubre
    # el camino que el test recorre; esta cubre todos.
    arbol = ast.parse(SKILL_PY)
    handler = next((n for n in arbol.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.name == "handle"), None)
    check(handler is not None, "skill.py sigue exponiendo handle()")
    # Se busca CUALQUIER mención del nombre, no solo `f(...)`: el código la
    # llamaba como `await asyncio.to_thread(_download_and_transcribe, url)`, o
    # sea pasándola de argumento, que un buscador de llamadas no ve.
    llamadas = [n for n in ast.walk(handler)
                if isinstance(n, ast.Name) and n.id == "_download_and_transcribe"]
    check(not llamadas, f"cero llamadas a _download_and_transcribe desde handle() (vi {len(llamadas)})")
    # Y las herramientas de esa vía ya no se importan siquiera. Se comprueba
    # sobre el AST, no sobre el texto: en el texto quedan (a propósito) los
    # comentarios que explican por qué se retiró, y un buscador de cadenas los
    # confundiría con código vivo.
    importados = {a.name.split(".")[0] for n in ast.walk(arbol)
                  if isinstance(n, ast.Import) for a in n.names}
    importados |= {(n.module or "").split(".")[0] for n in ast.walk(arbol)
                   if isinstance(n, ast.ImportFrom)}
    for herramienta in ("subprocess", "tempfile", "yt_dlp", "faster_whisper"):
        check(herramienta not in importados,
              f"skill.py ya ni importa {herramienta}, que era de la vía de descarga")


def _match(intent, texto):
    import re
    return re.search(co.SKILL["patterns"][intent], texto, re.IGNORECASE)


# ══════════════ 8. El material heredado se avisa, no se borra ══════════════
def test_aviso_heredado():
    print("· lo ya transcrito se puede seguir leyendo, pero avisando de su origen")
    import backend.core.infraestructura.llm as llm

    aviso = co._aviso_origen()
    check(isinstance(aviso, str) and len(aviso) > 20, "existe _aviso_origen()")
    check("hered" in aviso.lower(), "y dice que el material es heredado")

    tmp = Path(tempfile.mkdtemp(prefix="nexus_insp_"))
    (tmp / "creador-1.json").write_text(json.dumps(
        {"creator": "creador", "url": "u", "transcript": "un texto cualquiera"},
        ensure_ascii=False), encoding="utf-8")
    tmp_scripts = Path(tempfile.mkdtemp(prefix="nexus_scr_"))
    insp_orig, scr_orig, ask_orig = co.INSP_DIR, co.SCRIPTS_DIR, llm.ask_llm

    async def _falso(user_text, context=None, system=None):
        return ("análisis de mentira", "mock")

    try:
        co.INSP_DIR, co.SCRIPTS_DIR, llm.ask_llm = tmp, tmp_scripts, _falso
        g = _GrafoFalso()
        ctx = {**CTX, "graph": g, "pg": None}
        r = run(co.handle("patterns", "analiza los patrones", None, ctx))
        check(aviso in r["reply"], "«analiza los patrones» antepone el aviso de origen")
        r2 = run(co.handle("script", "genera un guion sobre automatización",
                           _match("script", "genera un guion sobre automatización"), ctx))
        check(aviso in r2["reply"], "«genera un guion sobre X» también, si tira de ese material")
    finally:
        co.INSP_DIR, co.SCRIPTS_DIR, llm.ask_llm = insp_orig, scr_orig, ask_orig
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(tmp_scripts, ignore_errors=True)


# ══════ 8 bis. Y NADA lo borra: el material heredado no se purga de tapadillo ══════
def test_no_borra_heredado():
    print("· ningún intent de Content OS borra lo que hay en data/inspiration/")
    import backend.core.infraestructura.llm as llm

    # Aquí vivía un `check(not path.exists() or True, …)`: `X or True` es cierto
    # pase lo que pase, o sea que la ÚNICA comprobación que amparaba «no borrar
    # datos del usuario sin confirmación» no podía fallar nunca. Si alguien
    # metía un rmtree en un intent, la suite seguía verde.
    # Esto de aquí sí falla: se siembra material heredado en un arenero, se
    # pasan TODOS los intents de la skill por encima y se exige que la carpeta
    # quede exactamente igual —ni un fichero menos, ni uno más.
    tmp = Path(tempfile.mkdtemp(prefix="nexus_insp_borra_"))
    tmp_scripts = Path(tempfile.mkdtemp(prefix="nexus_scr_borra_"))
    heredado = tmp / "creador-1.json"
    heredado.write_text(json.dumps(
        {"creator": "creador", "url": "u", "transcript": "un texto heredado"},
        ensure_ascii=False), encoding="utf-8")
    antes = {p.name for p in tmp.iterdir()}
    insp_orig, scr_orig, ask_orig = co.INSP_DIR, co.SCRIPTS_DIR, llm.ask_llm

    async def _falso(user_text, context=None, system=None):
        return ("texto de mentira", "mock")

    # Todos los intents de la skill, más una orden que no reconoce: el borrado
    # accidental se cuela igual de bien por la rama que nadie mira.
    ordenes = [
        ("connect", "conecta mi instagram"),
        ("analytics", "analítica de instagram"),
        ("best", "mis mejores reels"),
        ("inspire", "analiza este reel de @creador https://instagram.com/reel/x"),
        ("patterns", "analiza los patrones"),
        ("script", "genera un guion sobre automatización"),
        ("ideas", "dame ideas de reels"),
        ("desconocida", "haz algo que no existe"),
    ]
    sigue, despues, contenido = False, set(), ""
    try:
        co.INSP_DIR, co.SCRIPTS_DIR, llm.ask_llm = tmp, tmp_scripts, _falso
        ctx = {**CTX, "graph": _GrafoFalso(), "pg": None}
        for intent, frase in ordenes:
            m = _match(intent, frase) if intent in co.SKILL["patterns"] else None
            run(co.handle(intent, frase, m, ctx))
        sigue = heredado.exists()
        contenido = heredado.read_text(encoding="utf-8") if sigue else ""
        despues = {p.name for p in tmp.iterdir()} if tmp.exists() else set()
    finally:
        co.INSP_DIR, co.SCRIPTS_DIR, llm.ask_llm = insp_orig, scr_orig, ask_orig
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(tmp_scripts, ignore_errors=True)

    check(sigue, "un intent de Content OS ha BORRADO el material heredado de "
                 "data/inspiration/ sin pedir confirmación")
    check(despues == antes,
          f"data/inspiration/ ha cambiado de contenido al pasar los intents: "
          f"{sorted(antes)} → {sorted(despues)}")
    check("un texto heredado" in contenido,
          "el fichero heredado sigue ahí, pero alguien le ha cambiado el contenido")


# ══════════════ 9. Colisión de enrutado ══════════════
def test_enrutado():
    print("· «cómo va el instagram» llega a quien sabe contestarlo")
    load_skills()

    # skills_loader recorre las carpetas por orden ALFABÉTICO y gana la primera
    # regex que case, con rx.search SIN anclar: «content_os» va antes que
    # «instagram» y se tragaba ig_estado. Auditado en design.md, decisión 7.
    r = route("cómo va el instagram")
    check(r is not None, "«cómo va el instagram» casa con alguna skill")
    if r:
        check((r[0].folder, r[1]) == ("instagram", "ig_estado"),
              f"y llega a instagram/ig_estado (vi {r[0].folder}/{r[1]})")

    r = route("cómo va mi instagram")
    check(r is not None and r[0].folder == "content_os" and r[1] == "analytics",
          "«cómo va MI instagram» sigue siendo la analítica de Content OS")

    r = route("analítica de instagram")
    check(r is not None and (r[0].folder, r[1]) == ("content_os", "analytics"),
          "«analítica de instagram» no se mueve de sitio")

    # Ninguna frase puede quedarse sin dueño: sin regex que case, la orden cae
    # al planificador del cerebro, que es justo donde se inventa cosas.
    for frase in ("cómo va el instagram", "cómo va mi instagram",
                  "cómo va mi cuenta de instagram", "estado de instagram",
                  "analiza este reel de @creador https://instagram.com/reel/x",
                  "dame ideas de reels", "analiza los patrones"):
        check(route(frase) is not None, f"«{frase}» no se cae al planificador")


# ══════════════ 10. El contrato del payload (entrega B) ══════════════
# Claves cuyo número NO necesita sobre: contadores de evidencia, posiciones del
# calendario y las series que se le pasan tal cual a `charts.js` para dibujar.
# Es una lista BLANCA explícita y corta a propósito: todo lo que no esté aquí y
# sea un número tiene que traer su procedencia o no viaja.
_LIBRES = {"analyzed", "n", "consistent", "promising", "observations", "apuntes",
           "complete_pct", "eng", "likes", "comments", "hour", "reach",
           "median", "median_eng", "value", "x", "y"}


def _numeros_sueltos(nodo, ruta="payload"):
    """Todo número del payload que NO viaje dentro de un sobre `dato`."""
    fuera = []
    if isinstance(nodo, dict):
        if "origen" in nodo and "valor" in nodo:
            return fuera                # es un sobre: su interior es legítimo
        for k, v in nodo.items():
            if k == "charts" or k in _LIBRES:
                continue
            fuera += _numeros_sueltos(v, f"{ruta}.{k}")
    elif isinstance(nodo, list):
        for i, v in enumerate(nodo):
            fuera += _numeros_sueltos(v, f"{ruta}[{i}]")
    elif isinstance(nodo, (int, float)) and not isinstance(nodo, bool):
        fuera.append(f"{ruta} = {nodo}")
    return fuera


def test_dashboard_contrato():
    print("· el payload de /api/contentos: ninguna cifra viaja fuera de un sobre")
    from backend.core import contentos
    from backend.core.comun import procedencia

    d = run(contentos.dashboard())
    k = d.get("kpis") or {}

    sueltos = _numeros_sueltos(d)
    check(not sueltos, f"números sin procedencia en el payload: {sueltos[:4]}")

    for campo in ("followers", "reach_month", "media_count", "retention"):
        s = k.get(campo)
        check(isinstance(s, dict) and s.get("origen") in procedencia.ORIGENES,
              f"kpis.{campo} no viaja en un sobre con origen válido: {s!r}")

    # La tarjeta que era ficción entera: no existe ninguna entidad Experiment en
    # el proyecto, así que el KPI desaparece, no se queda en «—».
    check("experiments" not in k, "la tarjeta «Experimentos» sigue en el payload")

    ret = k.get("retention") if isinstance(k.get("retention"), dict) else {}
    check(ret.get("origen") == procedencia.SIN_DATOS,
          "la retención se sigue presentando como algo calculado")
    check(ret.get("valor") is None, f"la retención trae un valor: {ret.get('valor')!r}")
    check(bool(ret.get("aviso")), "la retención no dice POR QUÉ no se puede calcular")

    # Sin credenciales configuradas (el estado real de hoy) nada puede decir «medido».
    for campo, s in k.items():
        check(not isinstance(s, dict) or s.get("origen") != procedencia.MEDIDO,
              f"kpis.{campo} se declara medido sin cuenta conectada")
    check(d.get("modo") == procedencia.DEMOSTRACION, "el payload no declara su modo")
    voc = d.get("vocabulario") or {}
    check(bool(voc.get("textos")) and bool(voc.get("etiquetas")),
          "el payload no lleva los textos de umbrales.json: el HUD los tendría a fuego")
    check(bool(d.get("vacios", {}).get("ideas")),
          "las secciones vacías no traen su texto «Todavía no hay…»")


# ══════════════ 11. Instalación limpia: el panel no se inventa el plan ══════════
def test_instalacion_limpia():
    print("· en una instalación limpia el panel dice que no hay nada, no se lo inventa")
    from backend.core import contentos

    # Arenero PROPIO. Las pruebas anteriores ya han escrito en el store del
    # arenero común, y lo que se prueba aquí es justo la PRIMERA vez que se abre
    # el panel en una máquina donde todavía no hay nada del usuario.
    tmp = Path(tempfile.mkdtemp(prefix="nexus_limpio_"))
    store_orig = contentos.STORE
    try:
        contentos.STORE = tmp / "contentos.json"
        d = run(contentos.dashboard())

        # Estas tres secciones eran las únicas que seguían fingiendo: entradas de
        # calendario con hora («Hoy · 19:30») y estado («Listo») presentadas como
        # el plan REAL del usuario, sin marca de origen y sin pasar por cosDato().
        for seccion in ("calendar", "ideas", "inspirations"):
            check(d.get(seccion) == [],
                  f"«{seccion}» llega relleno de semilla en una instalación limpia: "
                  f"{d.get(seccion)!r}")
            check(bool((d.get("vacios") or {}).get(seccion)),
                  f"y sin el texto «Todavía no hay…» de «{seccion}» no hay qué pintar")

        # Y la ficción tampoco se PERSISTE. Ese era el mecanismo exacto por el
        # que el estado vacío honesto no se llegaba a ver nunca: `_load()` la
        # escribía en disco la primera vez y a partir de ahí ya era «tuya».
        crudo = contentos.STORE.read_text(encoding="utf-8")
        for inventado in ("Hoy · 19:30", "@creador.automatiza",
                          "5 flujos de n8n que todo negocio debería tener"):
            check(inventado not in crudo,
                  f"data/contentos.json nace con contenido inventado: {inventado!r}")

        # TRIANGULACIÓN. El vacío tiene que venir de que no hay nada, no de que
        # el payload esté roto: en cuanto el usuario escribe algo suyo, sale.
        mia = "Gancho: esto sí lo ha escrito el usuario"
        contentos.add_item("idea", mia)
        d2 = run(contentos.dashboard())
        check(d2.get("ideas") == [mia],
              f"lo que escribe el usuario no llega al panel: {d2.get('ideas')!r}")
        check(d2.get("calendar") == [] and d2.get("inspirations") == [],
              "y las demás secciones siguen vacías, que es la verdad")
    finally:
        contentos.STORE = store_orig
        shutil.rmtree(tmp, ignore_errors=True)


def test_sin_literales():
    print("· 48.6, 4.1, 18.4 y 3.2 ya no están escritos en contentos.py")
    fuente = (ROOT / "backend" / "core" / "contentos.py").read_text(encoding="utf-8")
    for lit in ("48.6", "4.1", "18.4", "3.2"):
        check(lit not in fuente,
              f"el literal {lit} sigue en backend/core/contentos.py")
    check("experiments" not in fuente,
          "la clave «experiments» sigue en backend/core/contentos.py")


def test_evidencia_y_aprendizajes():
    print("· un apunte no es una evidencia, y un 0 % no es «calidad medida»")
    from backend.core import contentos

    fuente = (ROOT / "backend" / "core" / "contentos.py").read_text(encoding="utf-8")
    # Lo que no puede haber es una ASIGNACIÓN de etiqueta: `"conf": "consistente"`.
    # Leerla (`l.get("conf")`) es legítimo; ponerla a mano sobre un texto que
    # nadie ha medido es justo el incidente.
    check('"conf": "' not in fuente,
          "todavía se teclea a mano una etiqueta de confianza en contentos.py")

    d = run(contentos.dashboard())
    ev = d.get("evidence") or {}
    # Un 0 se lee como «calidad pésima, medida». La verdad es «no medido».
    check(ev.get("complete_pct") is None,
          f"complete_pct vale {ev.get('complete_pct')!r} en vez de None")
    check(ev.get("suficiente") is False, "evidence no dice que la muestra no basta")
    check(bool(ev.get("aviso")), "evidence no explica qué falta para concluir algo")
    check(ev.get("consistent") == 0 and ev.get("promising") == 0,
          "un apunte sin evidencia sigue sumando como conclusión")
    aprend = d.get("learnings") or []
    check(ev.get("apuntes") == len(aprend),
          f"los apuntes de semilla no se cuentan como apuntes ({ev.get('apuntes')})")
    for l in aprend:
        check("conf" not in l, f"aprendizaje sin evidencia con etiqueta de confianza: {l!r}")
        check(l.get("origen") == "apunte_manual", f"aprendizaje sin origen: {l!r}")
        check(bool(l.get("etiqueta")), "el apunte no se rotula con el texto de umbrales.json")

    # Y al revés: con muestra, periodo y método, la etiqueta SÍ se gana.
    contentos.add_item("learning", {
        "text": "Los reels de menos de 20 s se terminan más.", "n": 9,
        "periodo": "junio 2026", "metodo": "mediana de engagement",
        "conf": "consistente"})
    d2 = run(contentos.dashboard())
    con = [l for l in (d2.get("learnings") or []) if l.get("n")]
    check(bool(con) and con[0].get("conf") == "consistente",
          "un aprendizaje CON n, periodo y método pierde su etiqueta")
    check(d2.get("evidence", {}).get("complete_pct") is not None,
          "con evidencia real, complete_pct sigue nulo")


def test_hud_contrato():
    print("· el HUD se niega a pintar lo que no trae sobre")
    js = js_hud()
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "css" / "command.css").read_text(encoding="utf-8")

    check("function cosDato" in js, "no existe cosDato(): el único camino a la pantalla")
    check("sin_procedencia" in js,
          "cosDato() no tiene la red de «— sin procedencia» para un valor sin sobre")
    check("k.experiments" not in js, "el HUD sigue pintando la tarjeta de Experimentos")
    check("(k.retention || 0)" not in js,
          "el HUD sigue pintando la retención como un número")
    check("ev.complete_pct || 0" not in js,
          "el HUD convierte un complete_pct nulo en 0 %: eso es inventarse una medida")
    check("k.followers_delta" not in js and "k.reach_delta" not in js,
          "el HUD sigue leyendo los deltas sueltos que ya no existen")
    check(js.count("cosMarca(") >= 4,
          "el modo demostración no está marcado en CADA bloque, solo en la cabecera")
    # El ?v=NN a mano se retiró en la Fase 2 y NO debe volver. Dos motivos:
    # backend/app.py ya sirve /static con Cache-Control: no-store, así que no
    # cacheaba nada; y command.js es un módulo ES, cuyos import no heredan la
    # query — subir el número habría refrescado la hoja y dejado los módulos
    # viejos, que es peor que no hacer nada porque parece que sí funciona.
    # Se mira solo src= y href=: en los comentarios sí se puede nombrar.
    import re as _re
    con_query = _re.findall(r'(?:src|href)="[^"]*\?v=[^"]*"', html)
    check(not con_query,
          "ha vuelto el cache-busting manual (?v=NN) a frontend/index.html; /static ya "
          "va con Cache-Control: no-store y la query no se propaga a los import")
    check(".cos-marca" in css, "faltan los estilos de la marca de origen")


def main() -> int:
    test_sobre()
    test_umbrales()
    test_demo()
    test_validador()
    test_regla()
    test_generate_real()
    test_analytics_honesto()
    test_inspire_politica()
    test_aviso_heredado()
    test_no_borra_heredado()
    test_enrutado()
    test_dashboard_contrato()
    test_instalacion_limpia()
    test_sin_literales()
    test_evidencia_y_aprendizajes()
    test_hud_contrato()
    print()
    print("=" * 50)
    print(f"{_pass} OK, {len(_fail)} fallo(s)")
    return 1 if _fail else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(_SAND, ignore_errors=True)
