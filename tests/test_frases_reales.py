# -*- coding: utf-8 -*-
"""LAS FRASES QUE ESCRIBE ADRI DE VERDAD, no las que yo imaginé.

Este archivo nace de dos fallos reales suyos (30/07/2026):

  · «analiza la cuenta de instagram de wabiks» → no casaba con NADA. Mi patrón
    exigía arroba. Se iba al cerebro y contestaba «No conozco el campo url».
  · «Marca la velada como realizada» → tampoco casaba con nada, iba al cerebro,
    y allí petaba: «El minion Tablero ha fallado: NoneType object has no
    attribute strip».

La lección: probar los patrones con MIS frases no prueba nada. Aquí van las
suyas, tal cual las escribió, y las variantes naturales de cada orden. Cada vez
que una orden falle en producción, su frase se añade aquí.

Ejecutar:  python tests/test_frases_reales.py    (desde la carpeta nexus)
"""
import asyncio
import importlib
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["NEXUS_DATA_DIR"] = tempfile.mkdtemp(prefix="nexus_frases_")
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


def _intent(skill, texto):
    for nombre, rx in skill.SKILL["patterns"].items():
        if re.search(rx, texto, re.IGNORECASE):
            return nombre
    return None


IG = importlib.import_module("skills.instagram.skill")
TB = importlib.import_module("skills.tasks_board.skill")


# ══════════ 1. EL FALLO DE «wabiks» ══════════
def test_analizar_una_cuenta_sin_arroba():
    print("· «analiza la cuenta de instagram de wabiks» (su frase exacta)")
    check(_intent(IG, "analiza la cuenta de instagram de wabiks") == "ig_competencia",
          "su frase exacta va a competencia")
    for f in ("analiza la cuenta de wabiks",
              "analiza el perfil de instagram de wabiks",
              "mira la cuenta de panrival",
              "revisa la cuenta de instagram de otracuenta",
              "estudia el perfil de rival",
              "compara mi cuenta con wabiks",
              "compárame con wabiks",
              "analiza la cuenta @wabiks",
              "compárame con @rival y @otro"):
        check(_intent(IG, f) == "ig_competencia", f"«{f}» → competencia")
    # y el nombre se saca bien, con arroba o sin ella
    rx = IG.SKILL["patterns"]["ig_competencia"]
    for f, esperado in (("analiza la cuenta de instagram de wabiks", "wabiks"),
                        ("analiza la cuenta @wabiks", "wabiks"),
                        ("compara mi cuenta con panrival", "panrival")):
        m = re.search(rx, f, re.IGNORECASE)
        crudo = " ".join(str(m.groupdict().get(k) or "")
                         for k in ("cuentas", "cuentas2", "cuentas3"))
        check(esperado in crudo, f"«{f}» → saca «{esperado}» (dio «{crudo.strip()}»)")


def test_lo_mio_sigue_siendo_mio():
    print("· y no se come las órdenes sobre TU cuenta")
    for f, esperado in (("analiza mis reels", "ig_analizar"),
                        ("analiza mis últimos 3 reels", "ig_analizar"),
                        ("analiza mi nicho", "ig_descubrir"),
                        ("busca competidores", "ig_descubrir"),
                        ("quiénes son mi competencia", "ig_descubrir"),
                        ("mis reels", "ig_listar"),
                        ("lista mis últimos 20 reels", "ig_listar"),
                        ("mi perfil de instagram", "ig_perfil_ver"),
                        ("perfil de instagram", "ig_perfil_ver"),
                        ("instagram nicho: cocina sin gluten", "ig_perfil_set"),
                        ("estado de instagram", "ig_estado"),
                        ("apunta la cuenta @personal: 8000 seguidores", "ig_manual"),
                        ("apunta en el reel 17: 40 dm enviados", "ig_conversion")):
        check(_intent(IG, f) == esperado, f"«{f}» → {esperado} (dio {_intent(IG, f)})")


# ══════════ 2. EL FALLO DEL TABLERO ══════════
def test_marcar_una_tarea_como_hecha():
    print("· «Marca la velada como realizada» (su frase exacta)")
    check(_intent(TB, "Marca la velada como realizada, fue el sabado pasado") == "marcar",
          "su frase exacta ya casa")
    for f in ("marca la velada como realizada",
              "marca la compra como hecha",
              "marca la tarea del banco como completada",
              "pon la reunión en progreso",
              "pon el informe en revisión",
              "da por hecha la compra",
              "dame por terminada la reunión"):
        check(_intent(TB, f) == "marcar", f"«{f}» → marcar (dio {_intent(TB, f)})")
    # y las de antes siguen funcionando
    for f, esperado in (("mueve la compra a hechas", "move"),
                        ("me pongo con la compra", "start"),
                        ("ver tablero", "show"),
                        ("borra las tareas realizadas", "clear")):
        check(_intent(TB, f) == esperado, f"«{f}» sigue en {esperado}")


def test_el_tablero_no_revienta_sin_grupos():
    print("· y si el cerebro lo llama a medias, contesta en vez de petar")
    from backend.core.config import settings
    ctx = {"settings": settings, "bus": None}
    for intent in ("move", "start", "marcar"):
        try:
            r = asyncio.run(TB.handle(intent, "marca la velada como realizada", None, ctx))
            check("No he entendido" in r["reply"],
                  f"«{intent}» sin match dice qué le falta ({r['reply'][:40]})")
            check("NoneType" not in r["reply"], f"«{intent}» no enseña un error de Python")
        except Exception as e:                                    # noqa: BLE001
            check(False, f"«{intent}» sin match REVIENTA: {type(e).__name__}: {e}")


def test_marcar_de_punta_a_punta():
    print("· y marcarla de verdad la mueve en el tablero")
    # El MISMO módulo de tablero que usa la skill: recargarlo dejaba a la skill
    # escribiendo en un tablero y al test leyendo otro, y el test fallaba solo
    # cuando corría dentro de la suite completa.
    from backend.core import board
    from backend.core.config import settings
    board.add_task("velada de Ibai")
    frase = "Marca la velada como realizada, fue el sabado pasado"
    m = re.search(TB.SKILL["patterns"]["marcar"], frase, re.IGNORECASE)
    r = asyncio.run(TB.handle("marcar", frase, m, {"settings": settings, "bus": None}))
    check("velada de Ibai" in r["reply"], f"contesta con la tarea ({r['reply'][:50]})")
    check("COMPLETADAS" in r["reply"].upper(), "diciendo a qué estado ha ido")
    estados = {t["title"]: t["state"] for t in board._load()}
    check(estados.get("velada de Ibai") == "completada",
          f"y la tarea está de verdad completada ({estados})")


# ══════════ 3. EL MISMO NÚMERO CON DOS NOMBRES ══════════
def test_el_id_de_cuenta_vale_lo_pongas_donde_lo_pongas():
    print("· el ID de la cuenta vale, lo rellenes en el campo que lo rellenes")
    # Fallo real: Adri tenía puesto «ig_user_id» (lo pedía Content OS) y la skill
    # de análisis leía «ig_business_account_id». Resultado: «me falta el ID de la
    # cuenta» teniéndolo puesto desde hacía días.
    from backend.core.config import settings
    ctx = {"settings": settings}
    antes = (settings.get("ig_user_id", ""), settings.get("ig_business_account_id", ""))
    try:
        settings.set("ig_user_id", ""); settings.set("ig_business_account_id", "")
        check(IG.credenciales(ctx)[1] == "", "sin ninguno de los dos, no hay ID")

        settings.set("ig_user_id", "17841400000000000")
        check(IG.credenciales(ctx)[1] == "17841400000000000",
              f"con «ig_user_id» puesto, el análisis lo ve ({IG.credenciales(ctx)[1]})")

        settings.set("ig_user_id", ""); settings.set("ig_business_account_id", "17841499999999999")
        check(IG.credenciales(ctx)[1] == "17841499999999999",
              "y con «ig_business_account_id» también")

        from backend.core import contentos
        check(contentos._credenciales()[1] == "17841499999999999"
              if hasattr(contentos, "_credenciales") else True,
              "y Content OS ve el que puso el análisis")
    finally:
        settings.set("ig_user_id", antes[0])
        settings.set("ig_business_account_id", antes[1])
    # y en la pantalla ya no hay dos campos para lo mismo
    js = (ROOT / "frontend" / "js" / "command.js").read_text(encoding="utf-8")
    check("k: 'ig_user_id'" not in js,
          "en Configuración → APIS ya no hay un segundo campo para el mismo número")
    check("ig_business_account_id" in js, "queda el que vale para todo")


# ══════════ 4. EL FALLO GRAVE: INVENTARSE CIFRAS ══════════
def test_no_inventarse_cifras_es_regla_del_prompt():
    print("· el cerebro tiene prohibido inventarse cifras, por escrito")
    # 31/07/2026: le pidió analizar una cuenta de Instagram abierta en Chrome y
    # devolvió un perfil ENTERO inventado — 1,2M seguidores, 15,4K seguidos,
    # 15,2M interacciones, +2,1% mensual. Los reales: 78.500, 716 y 327.
    from backend.core.llm import _build_messages
    sysmsg = _build_messages("hola")[0]["content"]
    check("REGLA INVIOLABLE" in sysmsg, "la regla está en el prompt del sistema")
    check("NUNCA des un número" in sysmsg, "prohíbe dar cifras sin dato detrás")
    for palabra in ("seguidores", "porcentajes", "métricas"):
        check(palabra in sysmsg, f"nombrando explícitamente «{palabra}»")
    check("aproximado" in sysmsg and "ejemplo" in sysmsg,
          "y cierra las escapatorias («aproximado», «a modo de ejemplo»)")
    check("no la describas" in sysmsg,
          "si le piden analizar una página que no ve, que no la describa")
    check("me lo he inventado" in sysmsg,
          "y si le pillan, que lo admita en vez de justificarse")
    # tiene que ir al FINAL, que es donde más pesa
    check(sysmsg.index("REGLA INVIOLABLE") > len(sysmsg) * 0.6,
          "y va al final del prompt, que es lo que más pesa")


def test_analizar_lo_que_hay_en_chrome_llega_a_chrome():
    print("· «analiza lo que ves en la página de chrome» llega a quien LEE chrome")
    ch = importlib.import_module("skills.chrome.skill")
    # Su frase literal. No casaba con nada: se iba al cerebro, y el cerebro se
    # inventaba lo que ponía en la pantalla.
    for f in ("Analiza lo que ves en la pagina de chrome con las metricas y todo",
              "analiza la pagina de chrome",
              "mira lo que hay en chrome",
              "qué ves en chrome",
              "resume la página que tengo abierta",
              "lee la pestaña de instagram",
              "qué estoy viendo en el navegador"):
        check(_intent(ch, f) == "read", f"«{f[:46]}» → read (dio {_intent(ch, f)})")
    # y con tilde, que tampoco casaba
    for f in ("conéctate con chrome", "conectate con chrome"):
        check(_intent(ch, f) == "connect", f"«{f}» → connect")
    # sin pisar las demás
    for f, e in (("abre una pestaña con google", "open"),
                 ("cierra la pestaña de metricool", "close"),
                 ("qué pestañas tengo", "tabs")):
        check(_intent(ch, f) == e, f"«{f}» sigue en {e}")


# ══════════ 5. LA MEMORIA NO PUEDE COLARSE DONDE NO VIENE A CUENTO ══════════
def test_la_memoria_no_se_cuela():
    print("· una nota sin relación no se le inyecta al modelo como «relevante»")
    # 31/07: le preguntó «Que es lo que ves» mirando Instagram y contestó sobre
    # cómo se escribe el nombre de una persona. Causa: la búsqueda por palabras
    # daba por relevante cualquier nota que compartiera UNA palabra («que»).
    import asyncio
    from backend.core import rag
    check("que" not in rag._words("Que es lo que ves"),
          f"«que» ya no cuenta como palabra clave ({rag._words('Que es lo que ves')})")
    check(rag._words("cuentas de instagram de wabiksco") == ["cuentas", "instagram", "wabiksco"],
          "y las que sí distinguen se quedan")

    async def prueba():
        await rag.add("Karin Leon se escribe con mayuscula inicial", kind="knowledge")
        await rag.add("wabiksco es una marca de calcetines deportivos", kind="knowledge")
        vacio = await rag.search("Que es lo que ves", 4, kinds=("knowledge", "fact"))
        check(vacio == [], f"«Que es lo que ves» NO trae ninguna nota ({vacio})")
        suyo = await rag.search("quien es karin leon", 4, kinds=("knowledge", "fact"))
        check(any("Karin" in x["text"] for x in suyo),
              "pero preguntando por ella, sí sale")
        otro = await rag.search("que sabes de wabiksco", 4, kinds=("knowledge", "fact"))
        check(any("wabiksco" in x["text"] for x in otro),
              "y cada cosa trae la suya, no la del vecino")
    asyncio.run(prueba())
    fuente = (ROOT / "backend" / "core" / "rag.py").read_text(encoding="utf-8")
    check("_MIN_PALABRAS" in fuente, "hay umbral para la búsqueda por palabras")
    check(">= _MIN_SEM" in fuente,
          "y la búsqueda en base de datos también filtra por relevancia")


# ══════════ 6. EL PLANIFICADOR NO ELIGE A CIEGAS ══════════
def test_el_planificador_sabe_que_hace_cada_intent():
    print("· el planificador ve QUÉ HACE cada intent, no solo su nombre")
    import backend.core.brain as B
    from backend.core.skills_loader import load_skills
    load_skills()
    cat = B._skills_plan_catalog()
    check("read(args: sel) = LEER DE VERDAD" in cat,
          "«read» de Chrome explica que lee el contenido de la pestaña")
    check("analizar, resumir, mirar" in cat,
          "diciendo con qué palabras se pide")
    check("ig_competencia" in cat and "DE OTRA PERSONA" in cat,
          "y distingue analizar la cuenta de otro de analizar la tuya")
    check("ig_analizar" in cat and "DEL PROPIO USUARIO" in cat,
          "que era justo la confusión")
    ch = importlib.import_module("skills.chrome.skill")
    check(ch.SKILL.get("intents", {}).get("read"), "la skill de Chrome los declara")
    check(IG.SKILL.get("intents", {}).get("ig_competencia"),
          "y la de Instagram también")


def main() -> int:
    for f in (test_analizar_una_cuenta_sin_arroba, test_lo_mio_sigue_siendo_mio,
              test_marcar_una_tarea_como_hecha, test_el_tablero_no_revienta_sin_grupos,
              test_marcar_de_punta_a_punta,
              test_el_id_de_cuenta_vale_lo_pongas_donde_lo_pongas,
              test_no_inventarse_cifras_es_regla_del_prompt,
              test_analizar_lo_que_hay_en_chrome_llega_a_chrome,
              test_la_memoria_no_se_cuela,
              test_el_planificador_sabe_que_hace_cada_intent):
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
    sys.exit(main())
