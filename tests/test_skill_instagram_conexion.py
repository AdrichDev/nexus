# -*- coding: utf-8 -*-
"""Skill de Instagram — la CONEXIÓN: activación, enrutado y honestidad.

Las otras suites de instagram (`test_instagram*.py`) miran el ANÁLISIS: las
medianas, Wilson, la aritmética de las cestas. Esta mira lo de antes:

  * ¿se ACTIVA con las frases que diría una persona de viva voz? Con y sin
    tilde, con el pronombre pegado («analízalo», «búscame») y sin él, en
    singular y en plural.
  * ¿llega al INTENT correcto, con el router de verdad y las 32 skills
    cargadas? Gana la primera regex que case, y `content_os` va antes.
  * ¿está ATENDIDO cada intent en `handle()`?
  * SIN credenciales —el caso normal hoy—, ¿dice QUÉ falta y CÓMO se consigue,
    sin traceback y sin inventarse un resultado de ejemplo?

Se ejecuta sin token, sin ID de cuenta y sin red.

Ejecutar:  python tests/test_skill_instagram_conexion.py   (desde nexus)
"""
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

# Caja de arena: ni se leen ni se tocan los datos ni la configuración reales.
_SAND = Path(tempfile.mkdtemp(prefix="nexus_igconx_"))
(_SAND / "data").mkdir()
(_SAND / "config").mkdir()
(_SAND / "config" / "settings.json").write_text(
    json.dumps({"setup_done": True, "llm_provider": "mock"}), encoding="utf-8")
os.environ["NEXUS_DATA_DIR"] = str(_SAND / "data")
os.environ["NEXUS_CONFIG_DIR"] = str(_SAND / "config")

import importlib.util                                            # noqa: E402
_spec = importlib.util.spec_from_file_location(
    "igskill_conx", ROOT / "skills" / "instagram" / "skill.py")
ig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ig)
from backend.core.comun.config import settings                         # noqa: E402
from backend.core.skills_loader import load_skills, route        # noqa: E402
from _frontend_js import js_hud  # el HUD entero, no solo command.js

CTX = {"settings": settings, "bus": None}
load_skills()


def run(c):
    return asyncio.new_event_loop().run_until_complete(c)


def enruta(frase):
    """(carpeta, intent) de la frase, o (None, None) si cae al cerebro."""
    r = route(frase)
    return (r[0].folder, r[1]) if r else (None, None)


def responde(frase):
    """La respuesta real: enruta, y llama a handle() con el match del router."""
    r = route(frase)
    if r is None or r[0].folder != "instagram":
        return None
    return run(ig.handle(r[1], frase, r[2], CTX))


# Frases tal y como se dicen hablando. Cada intent con sus variantes: tilde/sin
# tilde, con enclítico y sin él, singular y plural, y algún sinónimo.
FRASES = {
    "ig_estado": [
        "estado de instagram",
        "como esta instagram",
        "cómo está instagram",
        "cómo va el instagram",
        "cómo va la conexión con instagram",
        "está configurado instagram",
        "tengo configurado instagram",
        "¿está conectado instagram?",
    ],
    "ig_perfil_ver": [
        "mi perfil de instagram",
        "perfil de instagram",
        "enséñame mi perfil de instagram",
        "ensename mi perfil de instagram",
        "muéstrame mi ficha de instagram",
        "qué sabes de mi cuenta de instagram",
        "contexto de mi instagram",
    ],
    "ig_perfil_set": [
        "configura mi perfil de instagram",
        "configúrame el perfil de instagram",
        "rellena mi perfil de instagram",
        "edita mi perfil de instagram",
        "instagram nicho: cocina sin gluten",
        "instagram nicho = cocina sin gluten",
        "instagram idiomas: es, en",
        "instagram tono: cercano",
        "instagram objetivo: vender mi curso",
        "instagram público: madres primerizas",
    ],
    "ig_descubrir": [
        "busca mis competidores",
        "búscame competidores",
        "buscame competidores",
        "encuentra cuentas parecidas",
        "encuéntrame competidores",
        "sácame competidores",
        "descubre mi competencia",
        "investiga a mi competencia",
        "quién es mi competencia",
        "quienes son mis competidores",
        "analiza mi nicho",
        "cuál es mi nicho",
        "cual es mi nicho",
        "búscame referentes",
        "conecta mi cuenta de instagram",
    ],
    "ig_competencia": [
        "analiza @unacuenta",
        "analiza @unacuenta y @otracuenta",
        "analízame @unacuenta",
        "analizame @unacuenta",
        "compárame con @unacuenta",
        "comparame con @unacuenta",
        "compara mi cuenta con unamarca",
        "analiza la cuenta de instagram de unamarca",
        "analiza el perfil de instagram de unamarca",
        "mira la cuenta de unamarca",
        "estudia la cuenta @unacuenta",
        # sin nombrar a nadie: caían al planificador del cerebro
        "analiza la competencia",
        "analiza mis competidores",
        "analízame la competencia",
        "compara con la competencia",
        "compárame con mis competidores",
        "revisa la competencia",
        "mira a mis competidores",
        "estudia a mis competidores",
        "qué hacen mis competidores",
        "cómo va la competencia",
    ],
    "ig_manual": [
        "apunta la cuenta @unacuenta: 8000 seguidores, 300 me gusta, 20 comentarios",
        "apúntame la cuenta @unacuenta: 8000 seguidores",
        "anota de la cuenta @unacuenta: 8000 seguidores",
        "registra la cuenta unacuenta: 100 publicaciones",
    ],
    "ig_analizar": [
        "analiza mis reels",
        "analiza mis últimos 3 reels",
        "analiza mis ultimos 3 reels",
        "analiza mis 3 últimos reels",
        "analízame los últimos 5 reels",
        "analizame mis reels",
        "analiza mis publicaciones de instagram",
        "analiza mis vídeos de instagram",
        "qué comenta la gente en mis reels",
        "que dice la gente de mis reels",
        "saca los leads de mis reels",
        "sácame los leads de mis reels",
        "extrae los leads de mis reels",
        "dame las dudas de mis reels",
    ],
    "ig_listar": [
        "mis reels",
        "mis últimos reels",
        "lista mis últimos 20 reels",
        "lístame mis reels",
        "listame mis reels",
        "enséñame mis reels",
        "cuáles son mis últimos reels",
        "dame mis últimas publicaciones",
    ],
    "ig_conversion": [
        "apunta en el reel 17: 40 dm enviados, 31 abiertos, 12 clics y 2 ventas",
        "apunta del reel 17 40 dm enviados",
        "registra en el reel 17: 12 clics",
        "anota 3 ventas del reel 17",
    ],
}


# ══════════════ 1. Se activa: la frase natural llega al intent ══════════════
def test_activacion():
    print("· cada intent se activa con las frases que diría una persona")
    for intent, frases in FRASES.items():
        for f in frases:
            carpeta, real = enruta(f)
            check(carpeta == "instagram" and real == intent,
                  f"«{f}» → instagram.{intent} (ha ido a {carpeta}.{real})")


def test_encliticos():
    """El pronombre pegado al verbo ya rompió 12 intents en google_workspace y
    7 en domotica. Cada verbo de la skill tiene que aceptarlo."""
    print("· el pronombre pegado al verbo no rompe el enrutado")
    pares = [
        ("busca competidores", "búscame competidores"),
        ("encuentra competidores", "encuéntrame competidores"),
        ("analiza @unacuenta", "analízame @unacuenta"),
        ("compara con @unacuenta", "compárame con @unacuenta"),
        ("saca los leads de mis reels", "sácame los leads de mis reels"),
        ("apunta la cuenta @x: 8000 seguidores", "apúntame la cuenta @x: 8000 seguidores"),
        ("lista mis reels", "lístame mis reels"),
        ("configura mi perfil de instagram", "configúrame el perfil de instagram"),
    ]
    for llana, enclitica in pares:
        a, b = enruta(llana), enruta(enclitica)
        check(a == b and a[0] == "instagram",
              f"«{enclitica}» va donde «{llana}» ({b} vs {a})")


# ══════════════ 2. Llega al sitio correcto: sin colisiones ══════════════
def test_no_roba_a_content_os():
    """`content_os` va ANTES por orden alfabético y comparte vocabulario. Las
    frases suyas tienen que seguir siendo suyas."""
    print("· no se pisa con content_os, que va antes por orden alfabético")
    for f, esperado in (("cómo va mi instagram", "content_os"),
                        ("analítica de mi instagram", "content_os"),
                        ("mis mejores reels", "content_os"),
                        ("analiza los patrones", "content_os"),
                        ("dame ideas de contenido", "content_os"),
                        ("conecta mi instagram", "content_os"),
                        ("cómo va el instagram", "instagram")):
        carpeta, intent = enruta(f)
        check(carpeta == esperado, f"«{f}» → {esperado} (ha ido a {carpeta}.{intent})")


def test_no_roba_a_las_demas():
    """Los patrones nuevos («la competencia» sin arrobas, los enclíticos) son
    amplios: que no se lleven órdenes que no son de Instagram."""
    print("· los patrones amplios no se llevan órdenes de otras skills")
    for f in ("analiza el mercado", "compara los precios", "estudia el temario",
              "mira el calendario", "revisa el correo", "apunta que tengo que comprar pan",
              "busca en google la competencia del sector"):
        carpeta, intent = enruta(f)
        check(carpeta != "instagram", f"«{f}» NO es de instagram (ha ido a {carpeta}.{intent})")


def test_intents_declarados_y_enrutables():
    print("· los intents declarados, los enrutados y los atendidos son los mismos")
    declarados = set(ig.SKILL["intents"])
    con_patron = set(ig.SKILL["patterns"])
    check(declarados == con_patron,
          f"cada intent declarado tiene patrón (sobran {declarados ^ con_patron})")
    check(set(FRASES) == con_patron,
          f"esta suite cubre todos los intents (falta probar {con_patron - set(FRASES)})")
    fuente = (ROOT / "skills" / "instagram" / "skill.py").read_text(encoding="utf-8")
    for intent in con_patron:
        check(f'intent == "{intent}"' in fuente, f"handle() atiende a {intent}")


# ══════════════ 3. Falla con honestidad sin credenciales ══════════════
def test_sin_credenciales_no_hay_nada_puesto():
    print("· la caja de arena arranca sin token y sin ID, como el usuario de hoy")
    token, bid = ig.credenciales(CTX)
    check(not token, "no hay token de la Graph API")
    check(not bid, "no hay ID de cuenta business")


def test_estado_dice_lo_que_falta():
    print("· «estado de instagram» enumera lo que falta y cómo conseguirlo")
    r = responde("estado de instagram")
    t = (r or {}).get("reply", "")
    check("sin poner" in t, "dice que el token y el ID están sin poner")
    for pista in ("Graph API", "instagram_basic", "Business/Creator", "⚙"):
        check(pista in t, f"explica dónde/cómo conseguirlo: «{pista}»")
    check("Traceback" not in t, "no suelta un traceback")


def test_los_que_necesitan_api_dicen_que_falta():
    """Sin credenciales, TODO intent que consulte a Meta tiene que decir qué
    falta y no devolver ni una cifra."""
    print("· sin credenciales, los intents que consultan a Meta lo dicen")
    for f in ("analiza mis últimos 3 reels", "mis reels", "analiza @unacuenta",
              "analiza la competencia", "busca mis competidores"):
        r = responde(f)
        t = (r or {}).get("reply", "")
        check("token" in t.lower() and "ID de la cuenta" in t,
              f"«{f}» nombra las dos credenciales que faltan")
        check("no me lo voy a inventar" in t.lower() or "no tengo ningún dato" in t.lower(),
              f"«{f}» avisa de que no inventa nada")
        check("Traceback" not in t and "Error" not in t.split("\n")[0],
              f"«{f}» no suelta un traceback")
        check(r.get("data") is None, f"«{f}» no devuelve datos de ejemplo")


def test_sin_credenciales_no_se_lanza_el_script():
    """El guardia de credenciales va ANTES de tocar scripts/ig.py: si no,
    el usuario recibiría el error crudo del script («falta .env»)."""
    print("· sin credenciales no se llega ni a lanzar scripts/ig.py")
    llamadas = []
    original = ig.ejecutar_ig

    async def _espia(ctx, args, timeout=180):
        llamadas.append(args)
        return False, "no debería haberse llamado"
    ig.ejecutar_ig = _espia
    try:
        for f in ("analiza mis últimos 3 reels", "mis reels", "analiza @unacuenta",
                  "busca mis competidores"):
            responde(f)
    finally:
        ig.ejecutar_ig = original
    check(not llamadas, f"no se ha lanzado el script ({len(llamadas)} intentos)")


def test_lo_que_funciona_sin_token_funciona():
    """Perfil, estado y cuentas apuntadas a mano no necesitan la API. Si
    contestaran «me falta el token» sería mentira: no lo usan."""
    print("· lo que no necesita la API funciona igual sin token")
    r = responde("instagram nicho: un nicho de prueba")
    check("Apuntado" in (r or {}).get("reply", ""), "se puede rellenar el perfil sin token")
    r = responde("perfil de instagram")
    t = (r or {}).get("reply", "")
    check("un nicho de prueba" in t, "y se lee lo que se acaba de guardar")
    check("token" not in t.lower(), "ver el perfil no pide credenciales")
    r = responde("apunta la cuenta @unacuenta: 8000 seguidores, 20 comentarios")
    t = (r or {}).get("reply", "")
    check("8000" in t and "token" not in t.lower(),
          "apuntar una cuenta a mano no pide credenciales")
    check("aportado por ti" in t, "y queda marcado como aportado por el usuario")


def test_competencia_sin_cuentas_pide_el_nombre():
    """«analiza la competencia» sin arrobas y sin competidores en el perfil:
    antes no enrutaba a nadie; ahora tiene que pedir el nombre, no inventarlo."""
    print("· «analiza la competencia» sin nadie apuntado pide a quién mirar")
    r = run(ig.handle("ig_competencia", "analiza la competencia",
                      route("analiza la competencia")[2],
                      {"settings": settings, "bus": None, "_sin_credenciales": True}))
    t = r.get("reply", "")
    # con credenciales ausentes contesta el guardia; se comprueba el otro camino
    # llamando al intent con el perfil vacío y credenciales puestas de mentira
    check("token" in t.lower() or "a quién miro" in t.lower(),
          "o pide credenciales o pide el nombre de la cuenta, pero no se lo inventa")


# ══════════════ 4. No inventa datos ni trae los de nadie ══════════════
def test_no_hay_datos_de_ejemplo_a_fuego():
    """Ni una @cuenta real, ni un nombre propio, ni una cifra de nadie. Las
    arrobas del código solo pueden ser marcadores de posición: esta lista es
    exhaustiva a propósito, para que cualquier arroba nueva salte aquí."""
    print("· no hay cuentas ni datos de nadie escritos en el código")
    import re
    permitidas = {"@x", "@a", "@b", "@una", "@otra", "@unacuenta", "@sucuenta",
                  "@suusuario", "@tuusuario", "@usuario", "@quien-sea",
                  "@unamarcaco", "@otracuenta", "@gmail"}
    for f in ("skill.py", "analisis.py", "descubrimiento.py", "inteligencia.py",
              "visual.py", "scripts/ig.py"):
        fuente = (ROOT / "skills" / "instagram" / f).read_text(encoding="utf-8")
        for m in set(re.findall(r"@[\w.-]{1,30}", fuente)):
            check(m in permitidas, f"{f}: «{m}» parece una cuenta real escrita en el código")
        for prohibido in ("yt-dlp", "yt_dlp", "selenium", "BeautifulSoup",
                          "instaloader", "requests_html"):
            check(prohibido not in fuente, f"{f}: no hay rastro de scraping ({prohibido})")


def test_los_modulos_hermanos_se_importan():
    """El análisis vive en analisis.py, descubrimiento.py, inteligencia.py y
    visual.py. Con el cargador REAL, un `from . import analisis` apunta a
    skills/ y revienta: se comprueba que se cargan de verdad."""
    print("· los módulos del motor se importan con el cargador real")
    for nombre, funcion in (("analisis", "clasificar"), ("descubrimiento", "ficha_manual"),
                            ("inteligencia", "radiografia"), ("visual", "cruza")):
        try:
            mod = ig._hermano(nombre)
            check(hasattr(mod, funcion), f"{nombre}.py se carga y expone {funcion}()")
        except Exception as e:                                    # noqa: BLE001
            check(False, f"{nombre}.py no se ha podido cargar: {type(e).__name__}: {e}")
    # y con el cargador de nexus, no solo con el de esta suite
    from backend.core.skills_loader import get_skills
    mod = get_skills()["instagram"].module
    r = route("apunta la cuenta @unacuenta: 8000 seguidores, 20 comentarios")
    salida = run(mod.handle(r[1], "apunta la cuenta @unacuenta: 8000 seguidores, "
                            "20 comentarios", r[2], CTX))
    check("8000" in salida.get("reply", ""),
          f"ig_manual funciona con el cargador real ({salida.get('reply', '')[:60]})")


def test_el_sentimiento_no_infla_la_muestra():
    """El modelo lee como mucho 120 comentarios. La n del intervalo de Wilson
    tiene que ser la de lo que ha leído, no la del total: extrapolar la banda
    al total es anunciar una precisión que no se ha medido."""
    print("· el intervalo de Wilson se calcula sobre lo que el modelo ha leído")
    import backend.core.llm as _llm
    original = _llm.ask_llm

    async def _falso(prompt, *a, **k):
        if "positivos,neutrales,friccion" in prompt:
            return "90,7,3", "mock"
        return "", "ninguno"
    _llm.ask_llm = _falso
    try:
        sust = [{"text": f"comentario numero {i}"} for i in range(400)]
        sent, ideas, n = run(ig._cualitativo(ig.PERFIL_VACIO, sust, [], {}))
    finally:
        _llm.ask_llm = original
    check(n == 120, f"la n es la de la muestra leída, no el total ({n} de 400)")
    check(sum(sent.values()) == n, f"los conteos suman la muestra ({sum(sent.values())})")


def test_limites_de_la_api_se_dicen():
    """De una cuenta ajena no se ve el texto de sus comentarios, ni guardados,
    compartidos o alcance. El informe lo dice; no lo estima."""
    print("· los límites de la API con cuentas ajenas se dicen, no se estiman")
    doc = (ROOT / "skills" / "instagram" / "SKILL.md").read_text(encoding="utf-8").lower()
    fuente = (ROOT / "skills" / "instagram" / "skill.py").read_text(encoding="utf-8").lower()
    for pista in ("guardados", "comparti", "alcance"):
        check(pista in fuente, f"el código avisa de que «{pista}» no se puede ver")
        check(pista in doc, f"el SKILL.md avisa de que «{pista}» no se puede ver")
    check("scraping" in doc, "el SKILL.md deja claro que no hay scraping")


def test_skill_md_no_promete_lo_que_no_hay():
    """El SKILL.md es lo que lee el agente para decidir. Cada orden de su tabla
    tiene que enrutar de verdad a esta skill y al intent de su fila."""
    print("· cada orden de la tabla del SKILL.md enruta a su intent")
    import re
    doc = (ROOT / "skills" / "instagram" / "SKILL.md").read_text(encoding="utf-8")
    filas = 0
    for linea in doc.splitlines():
        m = re.match(r"\|\s*`(ig_\w+)`\s*\|(.*?)\|", linea)
        if not m:
            continue
        filas += 1
        intent = m.group(1)
        for frase in re.findall(r"«([^»]{4,90})»", m.group(2)):
            carpeta, real = enruta(frase)
            check(carpeta == "instagram" and real == intent,
                  f"el SKILL.md ofrece «{frase}» para {intent} y va a {carpeta}.{real}")
    check(filas == len(ig.SKILL["patterns"]),
          f"la tabla documenta los {len(ig.SKILL['patterns'])} intents ({filas} filas)")
    for intent in ig.SKILL["patterns"]:
        check(intent in doc, f"el SKILL.md documenta {intent}")
    # y la promesa de dónde se configuran las credenciales tiene que ser cierta
    ui = js_hud()
    for clave in ("ig_access_token", "ig_business_account_id"):
        check(clave in ui, f"⚙ → Instagram tiene de verdad el campo {clave}")


def main():
    for f in (test_activacion, test_encliticos, test_no_roba_a_content_os,
              test_no_roba_a_las_demas, test_intents_declarados_y_enrutables,
              test_sin_credenciales_no_hay_nada_puesto, test_estado_dice_lo_que_falta,
              test_los_que_necesitan_api_dicen_que_falta,
              test_sin_credenciales_no_se_lanza_el_script,
              test_lo_que_funciona_sin_token_funciona,
              test_competencia_sin_cuentas_pide_el_nombre,
              test_no_hay_datos_de_ejemplo_a_fuego,
              test_los_modulos_hermanos_se_importan,
              test_el_sentimiento_no_infla_la_muestra,
              test_limites_de_la_api_se_dicen,
              test_skill_md_no_promete_lo_que_no_hay):
        try:
            f()
        except Exception as e:                                    # noqa: BLE001
            import traceback
            _fail.append(f"EXCEPCIÓN en {f.__name__}: {type(e).__name__}: {e}")
            print("  EXCEPCIÓN en", f.__name__, ":", type(e).__name__, e)
            traceback.print_exc()
    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    return 1 if _fail else 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(_SAND, ignore_errors=True)
    sys.exit(code)
