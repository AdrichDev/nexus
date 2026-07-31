# -*- coding: utf-8 -*-
"""EL FLUJO COMPLETO del descubrimiento, ejecutado de verdad.

Los tests de `test_descubrimiento.py` comprueban las PIEZAS. Este comprueba que
la cadena entera funciona: leer tu cuenta → deducir el nicho → buscar por
internet → validar contra Meta → filtrar → guardar → contestarte.

Sin esto, un nombre de variable mal escrito en el orquestador no se ve hasta que
lo lanza el usuario, que es tarde.

Instagram y el buscador se sustituyen por dobles: aquí no se llama a ninguna red.
Lo que se prueba es NUESTRO código, no el de Meta.

Ejecutar:  python tests/test_descubrimiento_flujo.py   (desde la carpeta nexus)
"""
import asyncio
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
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


# ── datos que devolverían Instagram y el buscador ───────────────────────────
MI_CUENTA = {
    "username": "micuenta", "followers_count": 12000, "media_count": 180,
    "biography": "Recetas sin gluten",
    "media": [{"id": str(i), "caption": c, "media_type": "VIDEO",
               "media_product_type": "REELS", "permalink": f"https://ig/{i}",
               "timestamp": f"2026-07-{i+1:02d}T10:00:00+0000",
               "view_count": 9000 + i * 100, "like_count": 400, "comments_count": 30}
              for i, c in enumerate([
                  "Receta de pan sin gluten paso a paso #singluten #celiaquia",
                  "Masa madre sin gluten, mi truco #singluten",
                  "Pan de molde sin gluten para la semana #singluten",
                  "Bizcocho sin gluten esponjoso #reposteria #singluten",
                  "Mi despensa sin gluten: qué compro #singluten"])],
}
RIVAL = {
    "username": "panrival", "followers_count": 40000, "media_count": 300,
    "biography": "Panadería sin gluten y recetas de celiaquía",
    "media": [{"id": f"r{i}", "caption": "pan sin gluten de verdad #singluten",
               "media_type": "VIDEO", "media_product_type": "REELS",
               "permalink": f"https://ig/r{i}",
               "timestamp": f"2026-07-{i+1:02d}T10:00:00+0000",
               "view_count": 25000, "like_count": 1100, "comments_count": 60}
              for i in range(6)],
}
AJENO = {
    "username": "motosclasicas", "followers_count": 30000, "media_count": 900,
    "biography": "Restauración de motos clásicas",
    "media": [{"id": "m1", "caption": "restauramos una bultaco del 74",
               "media_type": "IMAGE", "media_product_type": "FEED",
               "permalink": "https://ig/m1", "timestamp": "2026-07-05T10:00:00+0000",
               "like_count": 500, "comments_count": 12}],
}
RESULTADOS_WEB = [
    {"title": "Las 10 mejores cuentas sin gluten", "url": "https://blog.es/a",
     "snippet": "Sigue a @panrival, es la referencia"},
    {"title": "Cuentas de celiaquía que seguir", "url": "https://otro.es/b",
     "snippet": "instagram.com/panrival y también instagram.com/personal"},
    {"title": "Motor clásico", "url": "https://motor.es/c",
     "snippet": "no te pierdas instagram.com/motosclasicas"},
    {"title": "Ruido", "url": "https://x.es/d",
     "snippet": "escribe a hola@gmail.com o mira instagram.com/p/ABC/"},
]


def _prepara(tmp: Path):
    """Carga la skill con sus datos en una carpeta desechable y con dobles."""
    os.environ["NEXUS_DATA_DIR"] = str(tmp / "data")
    os.environ["NEXUS_CONFIG_DIR"] = str(tmp / "config")
    (tmp / "data").mkdir(parents=True, exist_ok=True)
    (tmp / "config").mkdir(parents=True, exist_ok=True)
    # Se importa como PAQUETE, no como archivo suelto: la skill usa imports
    # relativos («from . import descubrimiento») y cargándola a pelo revientan.
    # Es como la carga el propio nexus, así que aquí se prueba lo mismo que corre.
    for m in [k for k in list(sys.modules)
              if k.startswith("backend.core.config") or k.startswith("skills.instagram")]:
        del sys.modules[m]
    import importlib as _il
    sk = _il.import_module("skills.instagram.skill")

    llamadas = {"ig": [], "web": []}

    async def falso_ig(ctx, args, timeout=180):
        """El doble de scripts/ig.py: escribe lo que escribiría de verdad."""
        llamadas["ig"].append(list(args))
        destino = Path(args[args.index("--out") + 1])
        if args[0] == "perfil":
            destino.write_text(json.dumps(MI_CUENTA), encoding="utf-8")
        elif args[0] == "competencia":
            pedidos = args[1].split(",")
            cuentas = []
            for u in pedidos:
                if u == "panrival":
                    cuentas.append({"usuario": u, "datos": RIVAL})
                elif u == "motosclasicas":
                    cuentas.append({"usuario": u, "datos": AJENO})
                else:
                    cuentas.append({"usuario": u, "datos": {
                        "error": "no se ha podido consultar esa cuenta",
                        "motivos": ["la cuenta no es Business/Creator"]}})
            destino.write_text(json.dumps({"cuentas": cuentas, "propia": MI_CUENTA}),
                               encoding="utf-8")
        return True, ""

    async def falso_buscador(query, n=6):
        llamadas["web"].append(query)
        return RESULTADOS_WEB

    # credenciales de mentira: lo que sustituimos es ig.py entero, así que el
    # token no se usa para nada — pero el control de credenciales sí lo mira.
    sk.credenciales = lambda ctx: ("token-de-prueba", "1234567890")
    sk.ejecutar_ig = falso_ig
    from backend.core import websearch
    websearch.search = falso_buscador
    return sk, llamadas


def _ctx():
    from backend.core.config import settings
    return {"settings": settings, "bus": None, "pg": None, "graph": None,
            "history": [], "channel": "test", "reglas": {}, "request_id": "t"}


# ══════════ 1. LA CADENA ENTERA ══════════
def test_el_flujo_entero_funciona():
    print("· «busca competidores» hace la cadena entera y contesta")
    tmp = Path(tempfile.mkdtemp())
    try:
        sk, llamadas = _prepara(tmp)
        import re
        m = re.search(sk.SKILL["patterns"]["ig_descubrir"], "busca competidores",
                      re.IGNORECASE)
        r = asyncio.run(sk.handle("ig_descubrir", "busca competidores", m, _ctx()))
        texto = r.get("reply", "")

        check("gluten" in texto, f"te dice el nicho que ha deducido ({texto[:80]})")
        check("Meta ha confirmado" in texto, "y cuántas ha confirmado Meta")
        check("@panrival" in texto, "con la cuenta del sector encontrada")
        check("motosclasicas" in texto or "Descartadas" in texto,
              "y las descartadas se nombran")

        # que haya llamado a lo que tenía que llamar, y en orden
        check(llamadas["ig"][0][0] == "perfil", "primero lee TU cuenta")
        check(any(a[0] == "competencia" for a in llamadas["ig"]),
              "y luego valida a los candidatos contra Meta")
        check(len(llamadas["web"]) >= 3,
              f"ha buscado por internet varias veces ({len(llamadas['web'])})")
        check(any("gluten" in q for q in llamadas["web"]),
              f"buscando por tu nicho ({llamadas['web'][:2]})")

        # lo que ha guardado
        comp = tmp / "data" / "instagram" / "competencia.json"
        check(comp.is_file(), "guarda la comparativa para la pestaña")
        pan = json.loads(comp.read_text(encoding="utf-8"))["panel"]
        check(pan["descubrimiento"]["validados"] == 1,
              f"con UNA cuenta validada, no las tres ({pan['descubrimiento']['validados']})")
        motivos = " ".join(x["motivo"] for x in pan["descubrimiento"]["descartados"])
        check("motos" in " ".join(x["usuario"] for x in pan["descubrimiento"]["descartados"]),
              "la de motos se cae")
        check("tema" in motivos, f"por no compartir tema contigo ({motivos[:70]})")
        check("personal" in " ".join(x["usuario"] for x in pan["descubrimiento"]["descartados"]),
              "y la personal también se cae")
        check("API" in motivos, "porque la API no la puede consultar")
        check((tmp / "data" / "instagram" / "nicho.json").is_file(),
              "y guarda el nicho deducido")
        informes = list((tmp / "data" / "instagram" / "informes").glob("*competencia.md"))
        check(informes, "y deja el informe en .md, como manda la casa")
        md = informes[0].read_text(encoding="utf-8")
        check("panrival" in md and "motosclasicas" not in md,
              "en el informe solo entra lo validado y pertinente")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ══════════ 2. LOS QUE PONE ÉL NO SE DESCARTAN ══════════
def test_los_competidores_que_pongo_yo_van_primero():
    print("· los competidores que pones tú no se pierden por el camino")
    tmp = Path(tempfile.mkdtemp())
    try:
        sk, llamadas = _prepara(tmp)
        import re
        # perfil con un competidor puesto a mano
        perfiles = tmp / "data" / "instagram" / "perfiles.json"
        perfiles.parent.mkdir(parents=True, exist_ok=True)
        p = json.loads(json.dumps(sk.PERFIL_VACIO))
        p["id"] = "micuenta"
        p["nicho"] = "cocina sin gluten"
        p["competencia"] = ["@panrival", "otroquenoexiste"]
        perfiles.write_text(json.dumps({"activo": "micuenta",
                                        "perfiles": {"micuenta": p}}), encoding="utf-8")
        m = re.search(sk.SKILL["patterns"]["ig_descubrir"], "busca competidores",
                      re.IGNORECASE)
        asyncio.run(sk.handle("ig_descubrir", "busca competidores", m, _ctx()))
        pedidos = [a[1] for a in llamadas["ig"] if a[0] == "competencia"][0].split(",")
        check(pedidos[0] == "panrival",
              f"el tuyo va el PRIMERO de la cola de validación ({pedidos[:3]})")
        check("otroquenoexiste" in pedidos,
              "y el otro también se intenta, aunque no salga en ninguna web")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ══════════ 3. SIN RESULTADOS, NO SE INVENTA NADA ══════════
def test_sin_resultados_lo_dice():
    print("· si internet no devuelve nada, se dice, no se inventa")
    tmp = Path(tempfile.mkdtemp())
    try:
        sk, llamadas = _prepara(tmp)
        from backend.core import websearch

        async def sin_nada(query, n=6):
            return []
        websearch.search = sin_nada
        import re
        m = re.search(sk.SKILL["patterns"]["ig_descubrir"], "busca competidores",
                      re.IGNORECASE)
        r = asyncio.run(sk.handle("ig_descubrir", "busca competidores", m, _ctx()))
        check("No he encontrado" in r["reply"], f"lo dice claro ({r['reply'][:60]})")
        check("He buscado esto" in r["reply"], "y enseña qué había buscado")
        check(not any(a[0] == "competencia" for a in llamadas["ig"]),
              "y NO gasta cuota de la API validando una lista vacía")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ══════════ 4. LA ENTRADA MANUAL, DE PUNTA A PUNTA ══════════
def test_apuntar_una_cuenta_a_mano():
    print("· apuntar una cuenta a mano funciona y queda marcado")
    tmp = Path(tempfile.mkdtemp())
    try:
        sk, _ = _prepara(tmp)
        import re
        frase = "apunta la cuenta @personal: 8.000 seguidores, 300 me gusta y 20 comentarios"
        m = re.search(sk.SKILL["patterns"]["ig_manual"], frase, re.IGNORECASE)
        r = asyncio.run(sk.handle("ig_manual", frase, m, _ctx()))
        check("personal" in r["reply"], "confirma de qué cuenta")
        check("8000" in r["reply"].replace(".", ""), "y con las cifras leídas")
        check("aportado por ti" in r["reply"], "diciendo que no es un dato verificado")

        f = tmp / "data" / "instagram" / "cuentas_manuales.json"
        check(f.is_file(), "y lo guarda")
        d = json.loads(f.read_text(encoding="utf-8"))
        ficha = d["personal"][0]
        check(ficha["seguidores"] == 8000, f"lee «8.000» como 8000 ({ficha['seguidores']})")
        check(ficha["med_me_gusta"] == 300 and ficha["med_comentarios"] == 20,
              "y el resto de cifras")
        check(ficha["verificado"] is False and ficha["fuente"] == "aportado",
              "marcado como aportado, nunca como verificado")
        check(ficha["cuando"], "con la fecha del día que lo miraste")

        # una segunda foto NO pisa a la primera: es un histórico
        frase2 = "apunta la cuenta @personal: 8500 seguidores"
        m2 = re.search(sk.SKILL["patterns"]["ig_manual"], frase2, re.IGNORECASE)
        asyncio.run(sk.handle("ig_manual", frase2, m2, _ctx()))
        d2 = json.loads(f.read_text(encoding="utf-8"))
        check(len(d2["personal"]) == 2, "la segunda foto se añade, no pisa a la primera")
        check(d2["personal"][-1]["seguidores"] == 8500, "con el dato nuevo")

        # y esto NO puede exigir token: los números los pones tú
        sk.credenciales = lambda ctx: ("", "")
        frase4 = "apunta la cuenta @sinconexion: 500 seguidores"
        m4 = re.search(sk.SKILL["patterns"]["ig_manual"], frase4, re.IGNORECASE)
        r4 = asyncio.run(sk.handle("ig_manual", frase4, m4, _ctx()))
        check("token" not in r4["reply"].lower(),
              f"apuntar a mano NO pide token: los números los pones tú ({r4['reply'][:70]})")
        check("sinconexion" in json.loads(f.read_text(encoding="utf-8")),
              "y se guarda igual, sin conexión con Instagram")
        sk.credenciales = lambda ctx: ("token-de-prueba", "1234567890")

        # y sin cifras, no se guarda basura
        frase3 = "apunta la cuenta @otra: pues eso"
        m3 = re.search(sk.SKILL["patterns"]["ig_manual"], frase3, re.IGNORECASE)
        r3 = asyncio.run(sk.handle("ig_manual", frase3, m3, _ctx()))
        check("No he pillado ninguna cifra" in r3["reply"], "sin cifras, lo dice")
        check("otra" not in json.loads(f.read_text(encoding="utf-8")),
              "y no guarda una ficha vacía")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ══════════ 5. EL SUBCOMANDO NUEVO DE ig.py EXISTE Y ESTÁ ENCHUFADO ══════════
def test_el_subcomando_perfil_esta_enchufado():
    print("· el subcomando «perfil» de ig.py existe y se despacha")
    import subprocess
    script = ROOT / "skills" / "instagram" / "scripts" / "ig.py"
    r = subprocess.run([sys.executable, str(script), "perfil", "--help"],
                       capture_output=True, text=True, timeout=60,
                       env={**os.environ, "PYTHONUTF8": "1"})
    check(r.returncode == 0, f"«ig.py perfil --help» responde ({r.returncode})")
    check("--recent" in r.stdout, "y acepta --recent")
    check("--out" in r.stdout, "y --out")
    # sin credenciales tiene que fallar LIMPIO, no reventar
    r2 = subprocess.run([sys.executable, str(script), "perfil"],
                        capture_output=True, text=True, timeout=60,
                        env={**os.environ, "PYTHONUTF8": "1",
                             "INSTAGRAM_ACCESS_TOKEN": "", "INSTAGRAM_BUSINESS_ACCOUNT_ID": ""})
    check(r2.returncode != 0, "sin credenciales no sigue adelante")
    check("Traceback" not in r2.stderr,
          f"y no revienta con un traceback en la cara ({r2.stderr[-90:]})")


# ══════════ 6bis. DAS UN NOMBRE Y ÉL ENCUENTRA LA CUENTA ══════════
def test_de_un_nombre_suelto_a_la_cuenta_real():
    print("· le das un nombre y busca por internet cuál es la cuenta")
    tmp = Path(tempfile.mkdtemp())
    try:
        sk, llamadas = _prepara(tmp)
        from backend.core import websearch

        async def busca(query, n=6):
            llamadas["web"].append(query)
            return [{"title": "LaMarca · calcetines (@lamarcaco) • Instagram",
                     "url": "https://www.instagram.com/lamarcaco/", "snippet": "oficial"},
                    {"title": "LaMarca socks (@lamarcaco)", "snippet": "sus reels",
                     "url": "https://www.instagram.com/lamarcaco/reels/"},
                    {"title": "un reel donde la mencionan", "snippet": "@otrapersona usa lamarca",
                     "url": "https://www.instagram.com/reel/C5l0DfPCohU/"}]
        websearch.search = busca

        cands = asyncio.run(sk._busca_la_cuenta("lamarca"))
        check(cands and cands[0] == "lamarcaco",
              f"del nombre suelto saca la cuenta real, y la primera ({cands})")
        check("reel" not in cands, "sin colar «reel» como si fuera una cuenta")
        check(any("instagram" in q for q in llamadas["web"]),
              "buscando el nombre junto a «instagram»")
        check(asyncio.run(sk._busca_la_cuenta("")) == [], "sin nombre no busca nada")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_reintenta_solo_con_la_cuenta_que_encuentra():
    print("· y reintenta el análisis solo, sin preguntarte nada")
    tmp = Path(tempfile.mkdtemp())
    try:
        sk, llamadas = _prepara(tmp)
        from backend.core import websearch

        async def busca(query, n=6):
            return [{"title": "LaMarca (@lamarcaco) • Instagram", "snippet": "oficial",
                     "url": "https://www.instagram.com/lamarcaco/"},
                    {"title": "LaMarca socks (@lamarcaco)", "snippet": "reels",
                     "url": "https://www.instagram.com/lamarcaco/reels/"}]
        websearch.search = busca

        # el doble: «lamarca» no existe, «lamarcaco» sí
        buena = dict(RIVAL, username="lamarcaco")

        async def falso_ig(ctx, args, timeout=180):
            llamadas["ig"].append(list(args))
            destino = Path(args[args.index("--out") + 1])
            if args[0] == "perfil":
                destino.write_text(json.dumps(MI_CUENTA), encoding="utf-8")
            else:
                cuentas = []
                for u in args[1].split(","):
                    if u == "lamarcaco":
                        cuentas.append({"usuario": u, "datos": buena})
                    else:
                        cuentas.append({"usuario": u, "datos": {
                            "error": "no se ha podido consultar esa cuenta",
                            "motivos": ["la cuenta no es Business/Creator"]}})
                destino.write_text(json.dumps({"cuentas": cuentas, "propia": MI_CUENTA}),
                                   encoding="utf-8")
            return True, ""
        sk.ejecutar_ig = falso_ig

        import re
        frase = "analiza la cuenta de instagram de lamarca"
        m = re.search(sk.SKILL["patterns"]["ig_competencia"], frase, re.IGNORECASE)
        r = asyncio.run(sk.handle("ig_competencia", frase, m, _ctx()))
        texto = r["reply"]

        pedidos = [a[1] for a in llamadas["ig"] if a[0] == "competencia"]
        check(pedidos[0] == "lamarca", f"primero prueba el nombre tal cual ({pedidos[0]})")
        check(len(pedidos) == 2 and "lamarcaco" in pedidos[1],
              f"y al fallar, reintenta solo con la que ha encontrado ({pedidos})")
        check("@lamarcaco" in texto, f"lo dice en la respuesta ({texto[:110]})")
        check("no existe tal cual" in texto, "explicando que el nombre que diste no era")
        check("¿Querías decir" not in texto and "¿Es @" not in texto,
              "y NO te devuelve la pelota con una pregunta: lo resuelve")
        # y la cuenta buena ha entrado de verdad en la comparativa
        pan = json.loads((tmp / "data" / "instagram" / "competencia.json")
                         .read_text(encoding="utf-8"))["panel"]
        cuentas = [s for s in pan["secciones"] if s["id"] == "cuentas"]
        check(cuentas and cuentas[0]["cuentas"][0]["usuario"] == "lamarcaco",
              "y sale analizada en la pestaña, no solo nombrada")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ══════════ 6. UN NOMBRE MAL ESCRITO NO ES UN CALLEJÓN SIN SALIDA ══════════
def test_quisiste_decir():
    print("· si el nombre está mal, propone el que sí existe")
    tmp = Path(tempfile.mkdtemp())
    try:
        sk, _ = _prepara(tmp)
        from backend.core import websearch

        async def busca_wabiks(query, n=6):
            return [{"title": "Wabiks · Calcetines deportivos (@wabiksco) • Instagram",
                     "url": "https://www.instagram.com/wabiksco/", "snippet": "Wabiks socks"},
                    {"title": "Wabiks socks (@wabiksco)", "snippet": "reels de @wabiksco",
                     "url": "https://www.instagram.com/wabiksco/reels/"},
                    {"title": "un reel suelto", "snippet": "@carmendidi9 recibe wabiks",
                     "url": "https://www.instagram.com/reel/C5l0DfPCohU/"}]
        websearch.search = busca_wabiks

        # el caso real: escribió «wabiks» y la cuenta es «wabiksco»
        pistas = asyncio.run(sk._quisiste_decir([{"usuario": "wabiks"}]))
        check("wabiks" in pistas, f"hay sugerencia para el nombre fallido ({pistas})")
        check("wabiksco" in pistas.get("wabiks", []),
              f"y propone la cuenta que sí existe ({pistas.get('wabiks')})")
        check("carmendidi9" not in pistas.get("wabiks", []),
              "sin colar cuentas que no se parecen en nada")
        # y no propone el mismo nombre que ya ha fallado
        check("wabiks" not in pistas.get("wabiks", []),
              "ni repite el que acaba de fallar")
        # sin nada parecido, no se inventa una sugerencia
        async def sin_nada(query, n=6):
            return [{"title": "otra cosa", "url": "https://x.es", "snippet": "nada"}]
        websearch.search = sin_nada
        check(asyncio.run(sk._quisiste_decir([{"usuario": "zzzzz"}])) == {},
              "y si no hay nada parecido, no se inventa ninguna")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ══════════ 7. EL PASO VISUAL, DENTRO DEL FLUJO ══════════
def test_el_analisis_mira_las_portadas():
    print("· el análisis de una cuenta mira sus portadas y cruza con las cifras")
    tmp = Path(tempfile.mkdtemp())
    try:
        sk, llamadas = _prepara(tmp)
        import re
        from skills.instagram import visual as V

        vistas = []

        async def falso_ojo(medios, settings, maximo=12):
            """Un modelo de visión de mentira: mira y rellena, sin red."""
            for i, m in enumerate(medios[:maximo]):
                vistas.append(m.get("id"))
                m["visual"] = {"personas": "una" if i % 2 == 0 else "ninguna",
                               "producto": "protagonista" if i % 2 == 0 else "no",
                               "genero_aparente": "mujer"}
            return {"hay": True, "motivo": "", "modelo": "llava:7b",
                    "miradas": len(medios[:maximo]), "fallidas": 0, "sin_mirar": 0,
                    "texto": f"Miradas {len(medios[:maximo])} portadas con «llava:7b»."}
        V.mira_portadas = falso_ojo

        rival = dict(RIVAL)
        rival["media"] = [dict(m, media_url=f"https://x/{m['id']}.jpg",
                               view_count=20000 if i % 2 == 0 else 5000)
                          for i, m in enumerate(RIVAL["media"])]

        async def falso_ig(ctx, args, timeout=180):
            llamadas["ig"].append(list(args))
            destino = Path(args[args.index("--out") + 1])
            if args[0] == "perfil":
                destino.write_text(json.dumps(MI_CUENTA), encoding="utf-8")
            else:
                destino.write_text(json.dumps(
                    {"cuentas": [{"usuario": "panrival", "datos": rival}],
                     "propia": MI_CUENTA}), encoding="utf-8")
            return True, ""
        sk.ejecutar_ig = falso_ig

        frase = "analiza la cuenta @panrival"
        m = re.search(sk.SKILL["patterns"]["ig_competencia"], frase, re.IGNORECASE)
        asyncio.run(sk.handle("ig_competencia", frase, m, _ctx()))

        check(vistas, f"ha mirado portadas ({len(vistas)})")
        pan = json.loads((tmp / "data" / "instagram" / "competencia.json")
                         .read_text(encoding="utf-8"))["panel"]
        cuenta = [s for s in pan["secciones"] if s["id"] == "cuentas"][0]["cuentas"][0]
        check("visual" in cuenta, "el cruce visual llega a la pestaña")
        check(cuenta["visual_estado"]["modelo"] == "llava:7b", "con qué modelo se miró")
        bl = {b["atributo"]: b for b in cuenta["visual"]["bloques"]}
        check("producto" in bl, f"con sus atributos ({list(bl)})")
        check(bl["producto"]["mejor"] == "protagonista",
              f"y dice qué versión rinde más ({bl['producto']['mejor']})")
        check(bl["genero_aparente"]["fiabilidad"] == "baja",
              "el género sigue marcado como poco fiable hasta el final")
        # y en el informe .md
        informes = list((tmp / "data" / "instagram" / "informes").glob("*competencia.md"))
        md = informes[0].read_text(encoding="utf-8")
        check("Qué sale en los vídeos" in md, "y el informe lo lleva escrito")
        check("ESTIMACIÓN" in md, "con el aviso del género dentro")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    for f in (test_el_flujo_entero_funciona,
              test_los_competidores_que_pongo_yo_van_primero,
              test_sin_resultados_lo_dice,
              test_apuntar_una_cuenta_a_mano,
              test_el_subcomando_perfil_esta_enchufado,
              test_de_un_nombre_suelto_a_la_cuenta_real,
              test_reintenta_solo_con_la_cuenta_que_encuentra,
              test_quisiste_decir,
              test_el_analisis_mira_las_portadas):
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
