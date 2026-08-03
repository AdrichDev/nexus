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
from _frontend_js import js_hud  # el HUD entero, no solo command.js

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
    js = js_hud()
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

    # Y lo que quedó abierto tapando lo de «que»: la frase se queda en UNA sola
    # palabra, «ves», y el filtro de «más de la mitad» ya no filtra nada, porque
    # una de una es el 100%. Con eso volvió a colarse un documento entero —el
    # SKILL.md de Gmail, por «el mismo número que ves en tu app de Gmail»—.
    check(rag._palabras_de_busqueda("Que es lo que ves") == [],
          "una palabra suelta y corta no da para buscar")
    check(rag._palabras_de_busqueda("que sabes de wabiksco") == ["wabiksco"],
          "pero una palabra suelta que SÍ distingue, sí")

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


# ══════════ EL FALLO DE «[ALERTA]» (31/07/2026) ══════════
# Diálogo real. nexus lista los correos; entre ellos «[ALERTA] Plugin nuevo no
# presente en el baseline». Adri pide analizarlos y nexus contesta «ninguno
# parece urgente». Dos bugs encadenados:
#
#   1. «No los leas analizalos» no casaba con NINGÚN patrón (todos exigían la
#      palabra «correos»), así que iba al planificador, que le repitió la frase.
#   2. Los 30 no-leídos se mandaban al modelo en una sola tirada de 22.000
#      caracteres. Ollama corta a 4096 tokens, el modelo devolvía prosa en vez
#      de JSON, el parser devolvía [] y el código lo leía como «cero urgentes».
def test_analizalos_a_secas_no_se_va_al_planificador():
    print("· «No los leas analizalos» (su frase exacta, sin la palabra «correos»)")
    GW = importlib.import_module("skills.google_workspace.skill")
    for frase in ("No los leas analizalos en segundo plano",
                  "No los leas analizalos",
                  "analizalos",
                  "analízamelos"):
        check(_intent(GW, frase) == "email_actions_pron",
              f"«{frase}» llega a la skill de correo y no al cerebro")
    # …pero sin robarle «analiza» a quien le toca.
    check(_intent(GW, "analiza las fotos de instagram") != "email_actions_pron",
          "y no se queda con lo de Instagram")
    check(_intent(GW, "analizalos a fondo y hazme un informe") != "email_actions_pron",
          "ni con una frase larga que empiece igual")


def test_un_asunto_con_alerta_sale_urgente_diga_lo_que_diga_el_modelo():
    print("· «[ALERTA] Plugin nuevo no presente en el baseline» tiene que salir urgente")
    GW = importlib.import_module("skills.google_workspace.skill")
    alerta = {"from": "Alertas Seguridad",
              "subject": "[ALERTA] Plugin nuevo no presente en el baseline en Menopausia Activa",
              "body": "Se detectaron plugins NUEVOS. Revisa si son intrusion."}
    check(GW._marca_urgente(alerta) == "[alerta]", "la marca salta por el asunto")
    check(GW._marca_urgente({"from": "n8n.io", "subject": "n8n v3 is coming soon",
                             "body": "x"}) == "", "y un boletín normal no la dispara")
    # Sin tildes ni mayúsculas: da igual cómo se escriba.
    check(GW._marca_urgente({"from": "x", "subject": "[CRÍTICO] disco lleno"}) != "",
          "«[CRÍTICO]» con tilde y en mayúsculas también salta")
    # Las marcas viven en config/umbrales.json, NO a fuego en el código.
    import json
    umb = json.loads((ROOT / "config" / "umbrales.json").read_text(encoding="utf-8"))
    check("[alerta]" in (umb.get("correos") or {}).get("marcas_urgentes", []),
          "y están en config/umbrales.json, que es donde se tocan")


def test_no_haber_podido_mirar_no_es_no_hay_nada():
    print("· si el modelo no contesta, NO se dice «ninguno parece urgente»")
    GW = importlib.import_module("skills.google_workspace.skill")

    async def _modelo_mudo(_msgs):          # el modelo devuelve prosa: cero objetos
        return []

    orig = GW._analyze_batch
    GW._analyze_batch = _modelo_mudo
    try:
        msgs = [{"from": f"B{i}", "subject": f"Novedades {i}", "body": "x"} for i in range(5)]
        an, sin = asyncio.run(GW._analyze_emails(msgs))
        check(sin == [0, 1, 2, 3, 4],
              "los 5 se marcan SIN CLASIFICAR en vez de darse por no urgentes")
        # …y la alerta se salva igual, porque la red no depende del modelo.
        msgs.append({"from": "Alertas Seguridad", "subject": "[ALERTA] intrusion", "body": "x"})
        an, sin = asyncio.run(GW._analyze_emails(msgs))
        check(any(a["i"] == 5 and a.get("urgente") for a in an),
              "y la alerta sale urgente aunque el modelo no haya dicho ni mu")
        check(5 not in sin, "sin quedarse en la lista de no clasificados")
    finally:
        GW._analyze_batch = orig


def test_el_analisis_va_por_lotes_y_no_de_una_tirada():
    print("· 30 correos se trocean y los índices no se pisan entre lotes")
    GW = importlib.import_module("skills.google_workspace.skill")
    llamadas = []

    async def _cuenta(msgs):
        llamadas.append(len(msgs))
        return [{"i": i, "urgente": False, "importancia": "baja", "accionable": False,
                 "tarea": "", "fecha": "", "motivo": ""} for i in range(len(msgs))]

    # Se FIJA el tamaño a mano a propósito: si dependiera de `llm_provider`, este
    # test pasaría o fallaría según el modelo que Adri tuviera puesto ese día.
    orig_batch, orig_lote = GW._analyze_batch, GW._por_lote
    GW._analyze_batch, GW._por_lote = _cuenta, lambda: 6
    try:
        msgs = [{"from": f"B{i}", "subject": f"N {i}", "body": "x"} for i in range(30)]
        an, sin = asyncio.run(GW._analyze_emails(msgs))
        check(len(llamadas) == 5, f"30 correos en lotes de 6 = 5 llamadas (fueron {len(llamadas)})")
        check(max(llamadas) <= 6, "ningún lote pasa del tamaño fijado")
        check(len(an) == 30 and not sin, "y se clasifican los 30, con índices GLOBALES")
        check([a["i"] for a in an] == list(range(30)),
              "reindexados bien: el 0 del segundo lote no pisa al 0 del primero")
    finally:
        GW._analyze_batch, GW._por_lote = orig_batch, orig_lote


def test_el_tamano_de_lote_sigue_al_modelo_que_haya_puesto():
    print("· cambiar de modelo cambia el tamaño de lote, sin reiniciar")
    GW = importlib.import_module("skills.google_workspace.skill")
    from backend.core.config import settings

    # Se finge la LECTURA de los ajustes; NO se llama a settings.set(). Un test que
    # escribe en config/settings.json le cambia la configuración a Adri de verdad
    # —y si peta a mitad, se la deja rota. Aprendido a base de dejarle puesto un
    # proveedor llamado «loquesea» (31/07/2026).
    orig_get = settings.get

    def _finge(prov):
        return lambda k, d=None, _p=prov: _p if k == "llm_provider" else orig_get(k, d)

    try:
        # El 6 es de qwen3:8b, que se ahoga con 30 de golpe. Un modelo de nube con
        # ventana grande se los traga en una llamada y no hay que pagar 5 viajes.
        settings.get = _finge("ollama")
        check(GW._por_lote() == 6, "con ollama, lotes cortos (medido con qwen3:8b)")
        for nube in ("openai", "gemini", "anthropic", "cloud"):
            settings.get = _finge(nube)
            check(GW._por_lote() > 6, f"con {nube}, lotes grandes: le cabe de sobra")
        # Un proveedor que no esté en la tabla NO puede quedarse con el número
        # grande por defecto: si no se sabe con qué se habla, se trocea fino.
        settings.get = _finge("un_modelo_que_no_conozco")
        check(GW._por_lote() == GW._CORREOS["por_lote"],
              "y un proveedor desconocido cae al valor prudente, no al optimista")
    finally:
        settings.get = orig_get


def test_cerrar_y_abrir_son_ordenes_de_pc(load_skills=None):
    """02/08/2026. «Nexus, cierra esto» tiene que cerrarlo, no preguntar ni
    razonar. Y «ábreme la web de X» vale para CUALQUIER web, no para una lista.

    Lo que fallaba: «cierra chrome», «cierra spotify», «cierra el navegador» y
    «cierra la calculadora» no casaban con ningún patrón y acababan en el
    planificador. «abre marca.com» lo cogía open_app e intentaba lanzar un
    programa llamado «marca.com». Y «ponme la web del as» se lo llevaba la
    música, porque media va antes por orden alfabético.
    """
    from backend.core import skills_loader as sl
    sl.load_skills()

    for frase in ("cierra chrome", "ciérrame chrome", "cierra el chrome",
                  "cierra spotify", "cierra discord", "termina spotify",
                  "cierra el navegador", "cierra la calculadora"):
        r = sl.route(frase)
        check(bool(r) and r[0].folder == "system_pc" and r[1] == "kill",
              f"«{frase}» va a " + (f"{r[0].folder}/{r[1]}" if r else "el planificador"))

    for frase in ("ábreme la web de marca", "ponme la web del as", "abre marca.com",
                  "ábreme marca.com", "abre www.marca.com", "entra en la web de marca",
                  "métete en elmundo.es", "abre la página de renfe"):
        r = sl.route(frase)
        check(bool(r) and r[0].folder == "system_pc" and r[1] == "open_web",
              f"«{frase}» va a " + (f"{r[0].folder}/{r[1]}" if r else "el planificador"))

    # Y la música sigue siendo música: el arreglo de «la web» no se la come.
    for frase, dueno in (("pon despacito", "media"), ("pon la canción despacito", "media"),
                         ("pon música", "media"), ("pon netflix en la tele", "domotica")):
        r = sl.route(frase)
        check(bool(r) and r[0].folder == dueno,
              f"«{frase}» es de {dueno} y va a " + (f"{r[0].folder}" if r else "el planificador"))


def test_pedir_ideas_y_mirar_la_competencia(load_skills=None):
    """02/08/2026. «Aportar ideas» es la mitad del producto y casi ninguna de
    sus frases llegaba: las resolvía el planificador.

    De doce formas naturales de pedir ideas, ocho caían al planificador —«dame
    ideas», «proponme ideas», «lluvia de ideas», «qué publico esta semana»—
    porque el patrón exigía decir «ideas DE CONTENIDO» o «PARA INSTAGRAM». Lo
    mismo con los guiones: el tema era obligatorio, así que «hazme un guion»
    no existía.

    Y en competencia faltaban dos formas: «qué HACE mi competencia» (el patrón
    solo aceptaba el plural «hacen») y «compara MI CUENTA CON la competencia»
    (lo interpuesto rompía la frase).

    El límite: pedir ideas a secas es pedir ideas DE CONTENIDO, pero «dame
    ideas de cena» no lo es. Por eso el complemento, si lo hay, tiene que ser
    del dominio.
    """
    from backend.core import skills_loader as sl
    sl.load_skills()

    def ruta(f):
        r = sl.route(f)
        return f"{r[0].folder}/{r[1]}" if r else None

    for frase in ("dame ideas", "dame más ideas", "proponme ideas", "propón ideas",
                  "sugiéreme ideas", "quiero ideas", "necesito ideas",
                  "lluvia de ideas", "ideas para reels", "ideas de contenido",
                  "dame ideas de contenido", "dame ideas para instagram",
                  "sugiéreme contenido", "qué publico", "qué publico esta semana",
                  "qué subo hoy", "qué cuelgo mañana", "qué puedo publicar"):
        check(ruta(frase) == "content_os/ideas", f"«{frase}» va a {ruta(frase)}")

    for frase in ("dame guiones", "hazme un guion", "escríbeme un guion",
                  "necesito guiones", "quiero un guion", "crea un guion de reel",
                  "genérame un guion sobre gatos"):
        check(ruta(frase) == "content_os/script", f"«{frase}» va a {ruta(frase)}")

    # Pedir ideas de algo que NO es contenido no es cosa de Content OS.
    for frase in ("dame ideas de cena", "ideas de cena", "ideas para el regalo"):
        check(ruta(frase) != "content_os/ideas",
              f"«{frase}» no es contenido y se lo queda Content OS")

    for frase in ("analiza la competencia", "mira la competencia",
                  "compara mi cuenta con la competencia", "compárame con la competencia",
                  "qué hace mi competencia", "qué hacen mis competidores",
                  "cómo le va a la competencia", "analiza a mi competencia"):
        check(ruta(frase) == "instagram/ig_competencia", f"«{frase}» va a {ruta(frase)}")

    for frase in ("descubre competencia", "búscame competencia", "busca competidores"):
        check(ruta(frase) == "instagram/ig_descubrir", f"«{frase}» va a {ruta(frase)}")


def test_crear_tarea_a_secas_y_buscar_informacion(load_skills=None):
    """03/08/2026. Dos órdenes normales que no tenían dueño y acababan en el
    planificador.

    · «crea una tarea» a secas: el patrón exigía cuerpo. Y «crea una tarea
      nueva» SÍ casaba, pero con body="nueva": creaba una tarea titulada
      «nueva». Un falso positivo es peor que no casar.
    · «busca información sobre python»: `web_search` de ai_media exigía decir
      «en internet» o «googlea». Ahora el ancla es el sustantivo.

    El límite del arreglo: buscar información EN UN SITIO CONCRETO no es
    búsqueda web. El lookahead devuelve carpetas, notas y mapas a su dueño.
    """
    import asyncio as _asyncio
    from backend.core import skills_loader as sl
    sl.load_skills()

    def ruta(f):
        r = sl.route(f)
        return f"{r[0].folder}/{r[1]}" if r else None

    for frase in ("crea una tarea", "crea tarea", "créame una tarea",
                  "añade una tarea", "apúntame una tarea", "anótame una tarea",
                  "crea una tarea nueva", "ponme otra tarea"):
        check(ruta(frase) == "tasks_board/create", f"«{frase}» va a {ruta(frase)}")

    # Sin asunto se PREGUNTA: no puede quedar ninguna tarea creada.
    async def _sin_asunto(frase):
        skill, intent, m = sl.route(frase)
        return await skill.module.handle(intent, frase, m, {})

    for frase in ("crea una tarea", "crea una tarea nueva", "ponme otra tarea"):
        out = _asyncio.run(_sin_asunto(frase))
        reply = out.get("reply", "")
        check("¿Tarea de qué?" in reply, f"«{frase}» no pregunta el asunto: {reply[:60]}")
        check("creada" not in reply.lower() and "apuntado" not in reply.lower(),
              f"«{frase}» ha creado una tarea sin asunto: {reply[:60]}")

    # Con asunto se crea, como siempre.
    out = _asyncio.run(_sin_asunto("crea una tarea de comprar pan para el viernes"))
    check("comprar pan" in out.get("reply", ""),
          f"«crea una tarea de comprar pan» ya no crea nada: {out.get('reply', '')[:60]}")

    for frase in ("busca información sobre python", "busca informacion sobre python",
                  "búscame información de la ley de teletrabajo",
                  "busca info sobre la dieta keto", "consulta datos sobre el ibex",
                  "búscame referencias sobre diseño editorial"):
        check(ruta(frase) == "ai_media/web_search", f"«{frase}» va a {ruta(frase)}")

    # Buscar en un sitio concreto NO es búsqueda web: cada uno con su dueño.
    check(ruta("busca facturas en la carpeta documentos") == "files/search",
          f"«busca facturas en la carpeta documentos» va a {ruta('busca facturas en la carpeta documentos')}")
    check(ruta("busca en mis notas lo de pgvector") == "memory_graph/recall",
          f"«busca en mis notas lo de pgvector» va a {ruta('busca en mis notas lo de pgvector')}")
    for frase in ("busca información sobre bares en el mapa",
                  "busca información de pgvector en mis notas",
                  "busca información sobre contratos en la carpeta clientes"):
        check(ruta(frase) != "ai_media/web_search",
              f"«{frase}» se la queda la búsqueda web y no es suya")

    # Y lo que ya funcionaba sigue funcionando.
    for frase, dueno in (("busca en internet quién ganó el mundial", "ai_media/web_search"),
                         ("googlea el precio del oro", "ai_media/web_search"),
                         ("investiga sobre la energía solar", "research/research"),
                         ("busca vuelos a parís", "places/flights"),
                         ("busca restaurantes en el mapa", "places/place_search")):
        check(ruta(frase) == dueno, f"«{frase}» va a {ruta(frase)}, debería ir a {dueno}")


def test_dame_ideas_no_es_una_pregunta_sobre_mi(load_skills=None):
    """03/08/2026. «dame ideas para el regalo de mi madre» se lo llevaba
    `memory_graph/list_knowledge`, que no tiene nada que ver.

    La causa es una tilde. El patrón ancla en «de mí» (el PRONOMBRE: sobre mi
    persona) pero lo escribe `m[ií]` para tolerar que el usuario no ponga
    tildes. Con eso acepta también el POSESIVO «de mi madre», que es otra
    palabra: «dame» + hasta 45 caracteres + «de mi» casaba con media frase.

    Lo que los separa es la tilde: «mí» solo puede ser el pronombre, y detrás
    puede llevar lo que quiera. Sin tilde decide la gramática, porque el
    posesivo SIEMPRE lleva un sustantivo detrás y el pronombre no lleva nada.

    Dónde acabe la frase después es otra discusión; lo que este test fija es
    que NO es de memory_graph.
    """
    from backend.core import skills_loader as sl
    sl.load_skills()

    def ruta(f):
        r = sl.route(f)
        return f"{r[0].folder}/{r[1]}" if r else None

    # El posesivo NO es una pregunta sobre el usuario.
    for frase in ("dame ideas para el regalo de mi madre",
                  "dame ideas para el cumple de mi hermano",
                  "dame ideas para la cena de mi padre"):
        r = ruta(frase)
        check(r != "memory_graph/list_knowledge",
              f"«{frase}» se lo lleva memory_graph, y es un posesivo, no una "
              f"pregunta sobre el usuario (fue a {r})")

    # Y el pronombre SIGUE siendo de memory_graph: el arreglo no puede
    # llevarse por delante lo que ya funcionaba. Las tres primeras acaban en el
    # pronombre; las demás llevan palabra detrás, que es justo lo que un primer
    # arreglo demasiado bruto («cualquier palabra detrás lo descarta») rompía:
    # «ahora» y «y» no son sustantivos poseídos.
    for frase in ("que sabes de mi",
                  "dame conocimiento sobre mi",
                  "que has aprendido de mi",
                  "qué sabes de mí ahora",
                  "qué sabes sobre mí exactamente",
                  "dame todo lo que sabes de mí y de mi familia",
                  "qué información tienes de mí?"):
        r = ruta(frase)
        check(r == "memory_graph/list_knowledge",
              f"«{frase}» es una pregunta sobre el usuario y debe ir a "
              f"memory_graph/list_knowledge (fue a {r})")


def main() -> int:
    for f in (test_analizar_una_cuenta_sin_arroba, test_lo_mio_sigue_siendo_mio,
              test_cerrar_y_abrir_son_ordenes_de_pc,
              test_pedir_ideas_y_mirar_la_competencia,
              test_crear_tarea_a_secas_y_buscar_informacion,
              test_dame_ideas_no_es_una_pregunta_sobre_mi,
              test_marcar_una_tarea_como_hecha, test_el_tablero_no_revienta_sin_grupos,
              test_marcar_de_punta_a_punta,
              test_el_id_de_cuenta_vale_lo_pongas_donde_lo_pongas,
              test_no_inventarse_cifras_es_regla_del_prompt,
              test_analizar_lo_que_hay_en_chrome_llega_a_chrome,
              test_la_memoria_no_se_cuela,
              test_el_planificador_sabe_que_hace_cada_intent,
              test_analizalos_a_secas_no_se_va_al_planificador,
              test_un_asunto_con_alerta_sale_urgente_diga_lo_que_diga_el_modelo,
              test_no_haber_podido_mirar_no_es_no_hay_nada,
              test_el_analisis_va_por_lotes_y_no_de_una_tirada,
              test_el_tamano_de_lote_sigue_al_modelo_que_haya_puesto):
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
