# -*- coding: utf-8 -*-
"""Dispositivos y modelos locales: no afirmar nada sin comprobarlo.

Encender es ENCENDER: el botón de un dispositivo no puede ser un interruptor.

Bug reportado por Adri el 25/07/2026: «el botón de encender un dispositivo, la
primera vez que lo pulsas se enciende y se apaga después, pero no cambia el
estado a encender en nexus. Si pone encender solo tiene que mandar la orden de
encender».

Dos causas, las dos cubiertas aquí:
  1. En Samsung se mandaba `KEY_POWER`, que es un TOGGLE, tanto para encender
     como para apagar. Y al encender se lanzaba el Wake-on-LAN Y la tecla EN
     PARALELO: el WoL despertaba la TV y el toggle la volvía a apagar.
  2. El estado no se guardaba en ningún sitio, así que el botón seguía diciendo
     «Encender» después de encenderla.

Ejecutar:  python tests/test_dispositivos.py    (desde la carpeta nexus)
"""
import asyncio
import importlib.util
import re
import sys
import time
from pathlib import Path
from _frontend_js import js_hud  # el HUD entero, no solo command.js

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


def _skill():
    spec = importlib.util.spec_from_file_location(
        "sk_domotica", str(ROOT / "skills" / "domotica" / "skill.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Settings(dict):
    def get(self, k, d=None):
        return dict.get(self, k, d)

    def set(self, k, v):
        self[k] = v

    def secret(self, _k):
        return ""


def _ctx(known=None):
    st = _Settings({"known_devices": list(known or []), "wol_broadcast": ""})
    return {"settings": st, "bus": None, "graph": None}


# ══════════════ 1. Nunca un toggle ══════════════

def test_encender_es_una_orden_absoluta():
    """ENCENDER es KEY_POWERON, la orden absoluta, SALVO con el reposo confirmado.

    Esto decía antes «nunca un interruptor», y era lo correcto mientras no se
    supiera el estado. Ahora se sabe: los modelos que no publican `PowerState`
    delatan el reposo por UPnP. Y sabiéndolo, el interruptor no puede apagar lo
    que ya está apagado — que es la misma regla del apagado, del revés.

    Hace falta porque hay un estado intermedio que engaña: EN REPOSO PERO CON LA
    RED VIVA. Ahí la TV contesta y KEY_POWERON no la despierta.

    Lo que este test fija es que el interruptor SOLO aparece atado a esa
    confirmación, nunca suelto."""
    src = (ROOT / "skills" / "domotica" / "skill.py").read_text(encoding="utf-8")
    check('"KEY_POWERON"' in src, "encender usa KEY_POWERON")
    i_on = src.find("async def _tv_power_on")
    bloque = src[i_on:src.find("\nasync def", i_on + 10)]
    check("en_reposo" in bloque and "_samsung_mute_upnp" in bloque,
          "encender comprueba el reposo antes de elegir tecla")
    check('"KEY_POWER" if en_reposo else "KEY_POWERON"' in bloque,
          "el interruptor SOLO se usa con el reposo confirmado")


def test_apagar_usa_el_interruptor_solo_tras_leer_el_estado():
    """Medido contra dos Tizen: KEY_POWEROFF se acepta y la TV NO se apaga; la que
    apaga es KEY_POWER, que es un interruptor. Usarlo es seguro SOLO con el estado
    confirmado «encendida»: no basta con descartar «apagada», porque hay un tercer
    estado —responde pero no dice cuál— que también puede ser reposo."""
    m = _skill()
    check(m._TV_KEYMAP["off"][1] == "KEY_POWER",
          f"apagar manda KEY_POWER, que es la que Tizen obedece ({m._TV_KEYMAP['off'][1]})")
    check(m._TECLA_APAGADO_SEGURA[1] == "KEY_POWEROFF",
          f"y hay una tecla absoluta para cuando no se sabe el estado "
          f"({m._TECLA_APAGADO_SEGURA[1]})")
    src = (ROOT / "skills" / "domotica" / "skill.py").read_text(encoding="utf-8")
    # el interruptor solo se toca desde el camino que ANTES lee el estado
    i_ap = src.find("async def _tv_apagar")
    bloque = src[i_ap:src.find("\nasync def", i_ap + 10)]
    check("_tv_estado(ip)" in bloque, "apagar lee el estado antes de pulsar")
    check('antes == "off"' in bloque, "y si ya está apagada no pulsa el interruptor")
    check('antes != "on"' in bloque,
          "y si el estado no está confirmado tampoco: ahí va la tecla absoluta")
    check(src.count('_TV_KEYMAP["off"]') == 1,
          "la tecla de apagado solo se usa desde ese camino comprobado")


def test_encender_una_tv_dormida_no_manda_tecla():
    """EL BUG: WoL + tecla a la vez = se enciende y se apaga."""
    m = _skill()
    teclas, wol = [], []
    m._tv_esta_viva = lambda ip, timeout=1.2: asyncio.sleep(0, result=False)
    m._mac_for_ip = lambda ip: "AA:BB:CC:DD:EE:FF"
    m._ip_for_mac = lambda mac: ""      # sin esto se leia la tabla ARP de verdad
    m._wol_burst = lambda mac, ip, bc: wol.append(mac) or True
    m._save_tv = lambda ctx, tv: None
    m._save_estado = lambda ctx, tv, on: teclas.append(("estado", on))

    async def _key(ctx, tv, roku, samsung):
        teclas.append(samsung)
        return True
    m._tv_key = _key

    r = asyncio.run(m._tv_power_on(_ctx(), {"ip": "192.168.1.50", "brand": "samsung",
                                            "name": "TV salón"}))
    pulsadas = [t for t in teclas if isinstance(t, str)]
    check(pulsadas == [], f"a una TV DORMIDA no se le manda ninguna tecla ({pulsadas})")
    check(wol == ["AA:BB:CC:DD:EE:FF"], "solo se la despierta por Wake-on-LAN")
    check(r["ok"] and r.get("state") == "on", f"y se informa de que queda encendida ({r})")


def test_encender_una_tv_viva_manda_encender():
    m = _skill()
    teclas, wol = [], []
    m._tv_esta_viva = lambda ip, timeout=1.2: asyncio.sleep(0, result=True)
    m._mac_for_ip = lambda ip: "AA:BB:CC:DD:EE:FF"
    m._ip_for_mac = lambda mac: ""      # sin esto se leia la tabla ARP de verdad
    m._wol_burst = lambda mac, ip, bc: wol.append(mac) or True
    m._save_tv = lambda ctx, tv: None
    m._save_estado = lambda ctx, tv, on: None

    async def _key(ctx, tv, roku, samsung):
        teclas.append((roku, samsung))
        return True
    m._tv_key = _key

    r = asyncio.run(m._tv_power_on(_ctx(), {"ip": "192.168.1.50", "brand": "samsung",
                                            "name": "TV salón"}))
    check(teclas == [("keypress/PowerOn", "KEY_POWERON")],
          f"a una TV VIVA se le manda ENCENDER, no un interruptor ({teclas})")
    check(wol == [], "y no hace falta despertarla por red")
    check(r["ok"] and r.get("state") == "on", "queda encendida")


def test_encender_dos_veces_no_la_apaga():
    """Idempotencia: «encender» sobre algo encendido lo deja encendido."""
    m = _skill()
    m._tv_esta_viva = lambda ip, timeout=1.2: asyncio.sleep(0, result=True)
    m._mac_for_ip = lambda ip: ""
    m._ip_for_mac = lambda mac: ""      # sin esto se leia la tabla ARP de verdad
    m._save_tv = lambda ctx, tv: None
    estados = []
    m._save_estado = lambda ctx, tv, on: estados.append(on)
    ordenes = []

    async def _key(ctx, tv, roku, samsung):
        ordenes.append(samsung)
        return True
    m._tv_key = _key
    tv = {"ip": "192.168.1.50", "brand": "samsung", "name": "TV"}
    asyncio.run(m._tv_power_on(_ctx(), tv))
    asyncio.run(m._tv_power_on(_ctx(), tv))
    check(ordenes == ["KEY_POWERON", "KEY_POWERON"],
          f"las dos veces manda ENCENDER ({ordenes})")
    check(estados == [True, True], "y las dos veces queda encendida")


# ══════════════ 2. El estado se guarda y se devuelve ══════════════

def test_el_estado_se_persiste():
    m = _skill()
    ctx = _ctx([{"ip": "192.168.1.50", "mac": "AA:BB:CC:DD:EE:FF", "is_tv": True}])
    m._save_estado(ctx, {"ip": "192.168.1.50"}, True)
    dev = ctx["settings"]["known_devices"][0]
    check(dev.get("on") is True, "queda guardado que está encendido")
    check(bool(dev.get("on_ts")), "y cuándo")
    m._save_estado(ctx, {"ip": "192.168.1.50"}, False)
    check(ctx["settings"]["known_devices"][0]["on"] is False, "y al apagar, lo contrario")
    check(len(ctx["settings"]["known_devices"]) == 1, "sin duplicar el aparato")


def _apagado(estados, teclas=None, guardado=None):
    """Prepara el módulo para probar `_tv_apagar` sin tocar la red. `estados` es la
    secuencia que irá devolviendo la lectura de estado (antes, después…)."""
    m = _skill()
    m._ESPERA_APAGADO = 0
    m._save_tv = lambda ctx, tv: None
    m._mac_for_ip = lambda ip: ""
    m._save_estado = lambda ctx, tv, on: (guardado if guardado is not None else []).append(on)
    secuencia = list(estados)

    async def _ip(ctx, tv):
        return tv.get("ip", ""), True

    # Al agotarse la secuencia se REPITE lo último, no se cae a «off». Una TV que
    # sigue encendida sigue diciéndolo cada vez que le preguntas; con el «off» de
    # antes, insistir acababa confirmando un apagado que no había ocurrido.
    ultimo = ["off"]

    async def _estado(ip, *a, **k):
        if secuencia:
            ultimo[0] = secuencia.pop(0)
        return ultimo[0]

    async def _key(ctx, tv, roku, samsung):
        if teclas is not None:
            teclas.append(samsung)
        return m.ENVIADO
    m._tv_ip_actual, m._tv_estado, m._tv_key = _ip, _estado, _key
    return m


def test_apagar_devuelve_estado():
    guardado, teclas = [], []
    m = _apagado(["on", "off"], teclas, guardado)
    r = asyncio.run(m.control_api(_ctx(), {"kind": "tv", "action": "off",
                                           "ip": "192.168.1.50", "brand": "samsung",
                                           "name": "TV"}))
    check(r["ok"] and r.get("state") == "off", f"apagar devuelve el estado ({r})")
    check(guardado == [False], "y lo persiste")
    check(teclas == ["KEY_POWER"], f"pulsando la tecla que Tizen obedece ({teclas})")


def test_apagar_lo_ya_apagado_no_pulsa_nada():
    """El interruptor sobre una TV apagada la ENCENDERÍA. Por eso «apagar» es
    idempotente: si el estado ya es apagado, no se manda ninguna tecla."""
    guardado, teclas = [], []
    m = _apagado(["off"], teclas, guardado)
    r = asyncio.run(m._tv_apagar(_ctx(), {"ip": "192.168.1.50", "brand": "samsung",
                                          "name": "TV"}))
    check(teclas == [], f"a una TV ya apagada no se le pulsa nada ({teclas})")
    check(r["ok"] and r.get("state") == "off", f"y se informa de que está apagada ({r})")
    check("ya estaba apagada" in r["reply"], f"diciendo la verdad ({r['reply']})")


def test_apagar_no_afirma_lo_que_no_ha_comprobado():
    """Mandar la orden no es que la TV obedezca: si al comprobarlo sigue encendida,
    ni se dice «apagada» ni se persiste ese estado."""
    guardado, teclas = [], []
    m = _apagado(["on", "on"], teclas, guardado)
    r = asyncio.run(m._tv_apagar(_ctx(), {"ip": "192.168.1.50", "brand": "samsung",
                                          "name": "TV"}))
    check(teclas == ["KEY_POWER"], "se manda la orden")
    check(not r["ok"], f"pero no se da por buena ({r})")
    check("sigue encendida" in r["reply"].lower(),
          f"y se dice lo que pasa de verdad ({r['reply']})")
    check(guardado == [], f"sin persistir un apagado que no ha ocurrido ({guardado})")


def test_apagar_avisa_cuando_no_puede_confirmarlo():
    """Los modelos que no publican PowerState siguen respondiendo en reposo: ahí no
    se puede confirmar el apagado, y hay que decirlo en vez de mentir."""
    guardado, teclas = [], []
    m = _apagado(["on?", "on?"], teclas, guardado)
    r = asyncio.run(m._tv_apagar(_ctx(), {"ip": "192.168.1.50", "brand": "samsung",
                                          "name": "TV"}))
    check(r.get("state") is None, f"no se inventa un estado ({r})")
    check("míralo" in r["reply"].lower() or "no puedo confirmar" in r["reply"].lower(),
          f"y se avisa de que no consta ({r['reply']})")
    check(guardado == [], "ni se persiste nada sin confirmar")
    check(teclas == ["KEY_POWEROFF"],
          f"y a ciegas se manda la absoluta, nunca el interruptor ({teclas})")


def test_apagar_a_ciegas_no_pulsa_el_interruptor():
    """EL FALLO QUE ESTE TEST GUARDA: «responde en la red» no es «está encendida».
    Un modelo que no publica su estado responde igual en reposo, así que pulsar
    ahí el interruptor no apaga: ENCIENDE la tele. La orden era apagarla."""
    guardado, teclas = [], []
    m = _apagado(["on?", "on?"], teclas, guardado)
    r = asyncio.run(m._tv_apagar(_ctx(), {"ip": "192.168.1.50", "brand": "samsung",
                                          "name": "TV"}))
    check("KEY_POWER" not in teclas,
          f"«apagar» sin estado confirmado NO pulsa el interruptor ({teclas})")
    check(teclas == ["KEY_POWEROFF"],
          f"manda la tecla absoluta, que no puede encender nada ({teclas})")
    check(not r["ok"], f"y no se da por bueno lo que no se ha podido comprobar ({r})")
    check("no sé si" in r["reply"].lower() or "podría encenderla" in r["reply"].lower(),
          f"sin dar por hecho lo que no se ha comprobado ({r['reply']})")
    check(guardado == [], "sin persistir ningún estado")


def test_apagar_no_se_queda_esperando_para_siempre():
    """Apagar encadena sondeos de red: resolver la IP, leer el estado, mandar la
    tecla, esperar y releerlo. Cada uno falla por agotamiento, y sin un tope
    común se suman: una TV desenchufada dejaba la orden pensando medio minuto.

    Aquí la TV no contesta NUNCA. Lo que se fija es que se deja de esperar
    dentro del tope y que la respuesta no da por hecho lo que no ha podido
    comprobar."""
    m = _skill()
    m._ESPERA_APAGADO = 0
    m._LIMITE_APAGADO = 0.6          # el mismo tope, en pequeño, para no dormir el test
    m._save_tv = lambda ctx, tv: None
    m._save_estado = lambda ctx, tv, on: None
    teclas = []

    async def _nunca_contesta(ip):
        await asyncio.sleep(30)      # una TV muerta: la conexión se agota, no falla
        return "on"

    async def _ip(ctx, tv):
        return tv.get("ip", ""), False

    async def _key(ctx, tv, roku, samsung):
        teclas.append(samsung)
        return m.ENVIADO
    m._tv_ip_actual, m._tv_estado, m._tv_key = _ip, _nunca_contesta, _key

    t0 = time.monotonic()
    r = asyncio.run(m._tv_apagar(_ctx(), {"ip": "192.168.1.50", "brand": "samsung",
                                          "name": "TV salón"}))
    tardo = time.monotonic() - t0

    check(tardo < 3, f"deja de esperar dentro del tope (tardó {tardo:.1f} s)")
    check(teclas == ["KEY_POWEROFF"],
          f"sin saber el estado manda la tecla que no puede encenderla ({teclas})")
    check("apagada." not in r["reply"], f"no afirma haberla apagado ({r['reply']})")
    check("no" in r["reply"].lower(), f"y dice que no ha podido confirmarlo ({r['reply']})")


def _ctx_dos_tvs():
    """Dos TVs guardadas, en my_devices y known_devices a la vez, como en casa."""
    tvs = [{"name": "Habitación Robledo", "ip": "192.168.1.136",
            "mac": "38:68:a4:95:54:cc", "brand": "samsung", "is_tv": True},
           {"name": "TV Samsung salón", "ip": "192.168.1.137",
            "mac": "d4:9d:c0:45:74:72", "brand": "samsung", "is_tv": True}]
    ctx = _ctx(list(tvs))
    ctx["settings"]["my_devices"] = list(tvs)
    return ctx


def test_la_tv_que_se_toca_es_la_que_has_nombrado():
    """EL BUG: `_resolve_tv` NO recibía la frase. Devolvía la PRIMERA TV de la
    lista, así que «enciende la tv de la habitación» encendía la del salón y que
    acertara dependía del orden de la lista, no de lo que pedías.

    Actuar sobre un aparato que no has nombrado es lo más grave que puede hacer:
    apagar la tele que estabas viendo."""
    m = _skill()
    ctx = _ctx_dos_tvs()

    def elegida(frase):
        tv, amb = asyncio.run(m._elegir_tv(ctx, frase))
        return (tv or {}).get("name"), [d["name"] for d in amb]

    # 1) el nombre propio manda
    for frase, esperado in (("enciende la tv de robledo", "Habitación Robledo"),
                            ("apaga robledo", "Habitación Robledo"),
                            ("apaga la tv del salón", "TV Samsung salón"),
                            ("sube el volumen de la tele del salón", "TV Samsung salón")):
        n, _ = elegida(frase)
        check(n == esperado, f"«{frase}» debía ir a {esperado} y fue a {n}")

    # 2) la ESTANCIA también desambigua, aunque `_resolve_named_device` la ignore:
    #    allí decide si la frase es de una TV o de una luz; aquí solo entre TVs.
    n, _ = elegida("enciende la tv de la habitación")
    check(n == "Habitación Robledo",
          f"«la tv de la habitación» debía ir a la de la habitación y fue a {n}")

    # 3) sin decir cuál, con dos y SIN antecedente, NO se elige: se pregunta
    m._ULTIMA_TV.clear()
    n, amb = elegida("apaga la tele")
    check(n is None and len(amb) == 2,
          f"con dos TVs y sin nombrar ninguna hay que preguntar, no elegir ({n})")

    # 4) pero si acabas de nombrar una, «apaga la tele» es ESA. Preguntar dos
    #    veces seguidas lo mismo es lo que hace una máquina, no alguien con quien
    #    hablas. Solo se recuerda lo que has dicho TÚ, y caduca en 10 minutos.
    m._ULTIMA_TV.clear()
    elegida("apaga la tv de robledo")
    n, amb = elegida("y ahora apágala")
    check(n == "Habitación Robledo" and not amb,
          f"no recuerda la TV que acabas de nombrar ({n})")
    m._ULTIMA_TV.clear()

    # 5) con una sola no hay nada que preguntar
    una = _ctx([{"name": "TV Samsung salón", "ip": "192.168.1.137",
                 "mac": "d4:9d:c0:45:74:72", "brand": "samsung", "is_tv": True}])
    una["settings"]["my_devices"] = []
    tv, amb = asyncio.run(m._elegir_tv(una, "apaga la tele"))
    check(tv is not None and not amb, "con UNA sola TV no hay ambigüedad que preguntar")


def test_el_dictado_no_escribe_robledo_y_aun_asi_se_entiende():
    """LO QUE PASÓ (03/08/2026). Adrián dijo por voz «apaga la televisión de
    Robledo» y el micro escribió «Robledal»; al repetir, «Roblera». nexus preguntó
    cuál las dos veces, porque el emparejado era letra a letra.

    Se comparan los SONIDOS, no las letras: fuera tildes y hache muda, y qu/c→k,
    z→s, v→b, ll→y, que en castellano suenan igual. De paso deja de importar que
    el nombre guardado tenga una errata: «salóm» encuentra «salón».

    Solo vale si señala a UNA sola TV y con margen sobre la segunda. Entre dos
    parecidas se pregunta: actuar sobre la que no era es peor que preguntar."""
    m = _skill()
    ctx = _ctx_dos_tvs()

    def elegida(frase):
        m._ULTIMA_TV.clear()                 # sin memoria: se prueba el sonido
        tv, amb = asyncio.run(m._elegir_tv(ctx, frase))
        return (tv or {}).get("name"), amb

    for frase in ("apaga la televisión de Robledal", "la de Roblera",
                  "enciende la tv de robleda"):
        n, _ = elegida(frase)
        check(n == "Habitación Robledo",
              f"«{frase}» no llega a Robledo por cómo suena (fue a {n})")

    # Lo que NO suena parecido sigue sin colarse.
    check(m._suena_como({"name": "Habitación Robledo"}, "apaga la cocina")
          < m._PARECIDO_MINIMO,
          "da por buena una palabra que no se parece en nada")

    # Y con dos TVs y una palabra que no señala a ninguna, se pregunta.
    n, amb = elegida("apaga esa cosa")
    check(n is None and len(amb) == 2,
          f"elige sin que nada apunte a una TV concreta ({n})")


def test_una_errata_en_el_nombre_no_deja_la_tv_inalcanzable():
    """El nombre guardado era «TV Samsung salóm», con eme. «Del salón» no casaba
    y esa TV solo se podía nombrar escribiendo la errata."""
    m = _skill()
    ctx = _ctx([{"name": "Habitación Robledo", "ip": "192.168.1.136",
                 "mac": "38:68:a4:95:54:cc", "brand": "samsung", "is_tv": True},
                {"name": "TV Samsung salóm", "ip": "192.168.1.137",
                 "mac": "d4:9d:c0:45:74:72", "brand": "samsung", "is_tv": True}])
    ctx["settings"]["my_devices"] = []
    m._ULTIMA_TV.clear()
    tv, _ = asyncio.run(m._elegir_tv(ctx, "apaga la tv del salón"))
    check((tv or {}).get("name") == "TV Samsung salóm",
          f"la errata del nombre deja la TV inalcanzable ({(tv or {}).get('name')})")


def test_contestar_a_la_pregunta_de_que_tele_es_una_orden():
    """«¿Cuál? A o B» → «la de arriba». Suelto no significa nada, y por eso no
    llegaba a ninguna skill: se iba al planificador y la orden se perdía.

    Pegado a la pregunta sí es una orden. Aquí se comprueban las dos piezas: que
    la orden queda apuntada al preguntar, y que la frase resultante enruta y
    elige la TV correcta. El pegado lo hace el cerebro, y solo cuando la frase
    suelta NO llega a nadie por su cuenta."""
    from backend.core.comun import context as ctxt
    from backend.core.skills_loader import load_skills, route
    load_skills()

    ctxt.olvida_pregunta("pc")
    check(ctxt.pregunta_pendiente("pc") == "", "arranca con una pregunta pendiente")

    ctxt.note_pregunta("apaga la tele", "pc")
    check(ctxt.pregunta_pendiente("pc") == "apaga la tele",
          "no recuerda la orden que dejó la pregunta abierta")

    # La respuesta suelta no es una orden; pegada a la pregunta, sí.
    check(route("la de robleda") is None,
          "«la de robleda» a secas ya enruta: entonces no hace falta pegarla")
    r = route("apaga la tele la de robleda")
    check(r is not None and r[0].folder == "domotica",
          "la frase pegada no llega a domotica")

    # Y elige la que suena parecido, no la otra.
    m = _skill()
    m._ULTIMA_TV.clear()
    tv, amb = asyncio.run(m._elegir_tv(_ctx_dos_tvs(), "apaga la tele la de robleda"))
    check((tv or {}).get("name") == "Habitación Robledo" and not amb,
          f"la respuesta no señala a la TV que suena parecido ({tv})")

    ctxt.olvida_pregunta("pc")
    check(ctxt.pregunta_pendiente("pc") == "",
          "la pregunta sigue viva después de contestarla")


def test_las_tvs_no_se_cuentan_por_duplicado():
    """`my_devices` y `known_devices` listan los mismos aparatos. Sin deduplicar
    por MAC, dos TVs parecen cuatro y la pregunta sale absurda."""
    m = _skill()
    tvs = m._tvs_guardadas(_ctx_dos_tvs())
    check(len(tvs) == 2, f"dos TVs guardadas en dos listas siguen siendo dos ({len(tvs)})")
    check({d["name"] for d in tvs} == {"Habitación Robledo", "TV Samsung salón"},
          "y son las dos que hay, no la misma repetida")


def test_mandar_una_tecla_no_es_que_la_tv_obedezca():
    """`_samsung`/`_roku` devolvían True tras enviar por el socket: eso es «salió»,
    no «la TV hizo caso». Tizen acepta teclas que luego ignora."""
    m = _skill()
    src = (ROOT / "skills" / "domotica" / "skill.py").read_text(encoding="utf-8")
    check(m.ENVIADO and m.ENVIADO is not True,
          "hay un valor propio para «enviado» distinto de «hecho»")
    for fn in ("_samsung", "_roku", "_tv_key"):
        i = src.find(f"async def {fn}(")
        bloque = src[i:src.find("\nasync def", i + 10)]
        check("return True" not in bloque,
              f"{fn} ya no devuelve True: enviar no es obedecer")
    i_ap = src.find("async def _tv_apagar")
    # Sin «await» delante: la lectura va envuelta en el tope de tiempo, y lo que
    # este test fija es que se lee el estado, no cómo se espera a que conteste.
    check("_tv_estado(ip)" in src[i_ap:src.find("\nasync def", i_ap + 10)],
          "quien apaga comprueba el resultado leyendo el estado")


def test_la_ip_caducada_se_resuelve_desde_la_mac():
    """La IP la reparte el router y caduca; la MAC no. Si la guardada no contesta,
    se busca la MAC en la tabla ARP y se ACTUALIZA la configuración."""
    m = _skill()
    m._tv_esta_viva = lambda ip, timeout=1.2: asyncio.sleep(0, result=False)
    m._ip_for_mac = lambda mac: "192.168.1.77"
    ctx = _ctx([{"name": "TV", "ip": "192.168.1.50", "mac": "AA:BB:CC:DD:EE:FF",
                 "is_tv": True}])
    ip, viva = asyncio.run(m._tv_ip_actual(ctx, {"ip": "192.168.1.50",
                                                 "mac": "AA:BB:CC:DD:EE:FF"}))
    check(ip == "192.168.1.77", f"se actúa contra la IP viva, no la caducada ({ip})")
    check(viva is False, "y dice si contesta por ella, para no sondearla dos veces")
    check(ctx["settings"]["known_devices"][0]["ip"] == "192.168.1.77",
          "y la nueva queda guardada para la próxima orden")

    # sin MAC no hay de dónde sacarla: se dice, no se inventa
    m._ip_for_mac = lambda mac: ""
    ip2, _ = asyncio.run(m._tv_ip_actual(_ctx(), {"ip": "192.168.1.50", "mac": ""}))
    check(ip2 == "192.168.1.50", f"sin MAC se queda con lo único que tiene ({ip2})")


def test_que_algo_sea_tv_lo_dice_la_configuracion_no_su_nombre():
    """Una TV con el nombre de su cuarto no lleva «tv» dentro: adivinarlo por el
    nombre la dejaba fuera de la ruta de apagado."""
    m = _skill()
    check(m._is_tv_device({"name": "Cuarto de arriba", "is_tv": True}),
          "el flag explícito manda aunque el nombre no diga «tv»")
    check(not m._is_tv_device({"name": "TV del salón", "is_tv": False}),
          "y si la configuración dice que NO es una TV, se respeta")
    check(m._is_tv_device({"name": "Cuarto de arriba", "kind": "tv"}),
          "el tipo declarado también vale")
    check(m._is_tv_device({"name": "TV del salón"}),
          "adivinar por el nombre sigue estando, como último recurso")
    check(not m._is_tv_device({"name": "Impresora"}), "y no marca lo que no lo es")


def test_home_assistant_tambien_devuelve_estado():
    src = (ROOT / "skills" / "domotica" / "skill.py").read_text(encoding="utf-8")
    i_ha = src.find('if kind == "ha":')
    bloque = src[i_ha:src.find('if kind == "tv":')]
    check('"state": (estado if ok else None)' in bloque,
          "Home Assistant también devuelve el estado resultante")
    check("None" in bloque, "y no inventa estado si la orden falló")


# ══════════════ 3. El HUD pinta lo que dice el backend ══════════════

def test_el_hud_usa_el_estado_del_backend():
    js = js_hud()
    check("res.state === 'on'" in js, "el HUD hace caso al estado que devuelve nexus")
    check("(state.devices || []).forEach" in js,
          "y lo sincroniza con la rejilla (antes se perdía en otra copia del objeto)")
    check("_devList || []).forEach" in js, "y con la lista visible")
    # el botón se pinta a partir de d.on: si no cambia, el usuario no ve nada
    check("_pwBtn = (d) => d.on ?" in js, "el botón se dibuja según el estado real")


# ══════════════ El diagnóstico de Ollama no puede acusar sin mirar ══════════════

def test_ollama_no_acusa_sin_comprobar():
    """Bug de Adri (25/07/2026): «el modelo qwen3:8b no está en Ollama»
    teniéndolo instalado. Un 404 no basta para afirmar eso."""
    import backend.core.llm as L
    L._ollama_instalados = lambda: ["qwen3:8b", "llama3.1:latest"]
    r = L._diagnostico_ollama_404("qwen3:8b")
    check("SÍ está instalado" in r, f"si el modelo ESTÁ, no dice que falte ({r[:60]}…)")
    check("404" in r, "y explica que el 404 viene de otra cosa")

    r2 = L._diagnostico_ollama_404("qwen3")
    check("qwen3:8b" in r2 and "etiqueta exacta" in r2,
          f"si falta la etiqueta, propone la que tienes ({r2[:60]}…)")

    r3 = L._diagnostico_ollama_404("mistral:7b")
    check("no está en Ollama" in r3, "si de verdad no está, lo dice")
    check("ollama pull mistral:7b" in r3, "con la orden exacta para instalarlo")
    check("qwen3:8b" in r3, "y enseña los que sí tienes")

    L._ollama_instalados = lambda: []
    r4 = L._diagnostico_ollama_404("qwen3:8b")
    check("no está respondiendo" in r4 and "tu disco" in r4,
          f"y si no puede comprobarlo, lo dice en vez de inventar ({r4[:60]}…)")


def test_ollama_reintenta_por_la_via_antigua():
    """«Pasa lo mismo con el resto de modelos» → el 404 no era del modelo, era de
    la RUTA. Ahora prueba /api/chat y, si esa ruta no existe, /api/generate."""
    import backend.core.llm as L

    class _Resp:
        def __init__(self, code, texto="", data=None):
            self.status_code = code
            self.text = texto
            self._d = data or {}

        def json(self):
            return self._d

        def raise_for_status(self):
            if self.status_code >= 400:
                import httpx as _h
                raise _h.HTTPStatusError("x", request=None, response=self)

    llamadas = []

    class _Cli:
        async def post(self, url, **kw):
            llamadas.append(url.rsplit("/", 1)[-1])
            if url.endswith("/api/chat"):
                return _Resp(404, "404 page not found")
            return _Resp(200, data={"response": "hola"})

    L.OllamaProvider._ruta = ""
    L.net.client = lambda: _Cli()
    prov = L.OllamaProvider()
    out = asyncio.run(prov.chat([{"role": "user", "content": "hola"}]))
    check(llamadas == ["chat", "generate"],
          f"prueba la ruta nueva y luego la antigua ({llamadas})")
    check(out == "hola", "y devuelve la respuesta igualmente")
    check(L.OllamaProvider._ruta == "generate",
          "recuerda cuál funciona para no repetir el intento fallido")
    llamadas.clear()
    asyncio.run(prov.chat([{"role": "user", "content": "otra"}]))
    check(llamadas == ["generate"], f"la siguiente vez va directo ({llamadas})")
    L.OllamaProvider._ruta = ""


def test_ollama_distingue_ruta_de_modelo():
    import backend.core.llm as L
    r = L._diagnostico_ollama_404("qwen3:8b", "404 page not found")
    check("no por culpa del modelo" in r,
          f"un 404 de RUTA no se echa al modelo ({r[:60]}…)")
    L._ollama_instalados = lambda: ["qwen3:8b"]
    r2 = L._diagnostico_ollama_404("qwen3:8b", 'model "qwen3:8b" not found')
    check("SÍ está instalado" in r2, "y si el cuerpo habla del modelo, se comprueba")


def test_mensajes_coherentes_cuando_no_hay_cerebro():
    """Queja de Adri (25/07): la pantalla decía «5 modelos detectados · EN USO» y
    el chat «no he podido hablar con Ollama». Dos mensajes que se contradicen."""
    import backend.core.llm as L
    # NO se escribe en los ajustes de verdad. Esta línea ponía
    # llm_provider=ollama en el config/settings.json REAL y no lo devolvía, así
    # que CADA pasada de la suite le cambiaba el cerebro a Adrián: elegía Gemini
    # y al arrancar nexus salía qwen3. El test solo necesita que el proveedor
    # LEÍDO sea ollama, no dejarlo escrito.
    _get = L.settings.get
    L.settings.get = lambda k, d=None: "ollama" if k == "llm_provider" else _get(k, d)
    L._ollama_instalados = lambda: []
    r = asyncio.run(L.MockProvider().chat([{"role": "user", "content": "¿qué tal?"}]))
    check("modo simulación" not in r, "se acabó la jerga de «modo simulación»")
    check("no está respondiendo" in r, f"dice el motivo REAL: Ollama no responde ({r[:70]}…)")
    check("ollama serve" in r, "y qué hacer para arreglarlo")
    check(r.count("Ollama") <= 2 and "(aviso:" not in r,
          "un solo mensaje, no dos pegados que se contradicen")

    L._ollama_instalados = lambda: ["qwen3:8b"]
    r2 = asyncio.run(L.MockProvider().chat([{"role": "user", "content": "¿qué tal?"}]))
    check("sí responde" in r2,
          f"y si Ollama SÍ responde, no dice lo contrario ({r2[:70]}…)")
    check("modelo elegido" in r2, "apunta al modelo, que es donde está el problema")

    L._ollama_instalados = lambda: []
    d2 = L._diagnostico_ollama_404("qwen3:8b")
    check("no está respondiendo" in d2 and "tu disco" in d2,
          "y el diagnóstico explica que tener el modelo en disco no basta")
    L.settings.get = _get                       # se devuelve el lector de verdad


def test_el_selector_distingue_disponible_de_en_disco():
    """Mismo requisito de siempre, comprobado donde ahora vive.

    Antes estos textos los escribía el JavaScript con su propio criterio; desde
    el runtime v24 los decide el BACKEND (una sola clasificación para todos) y
    el navegador solo los pinta. La comprobación de comportamiento real —con un
    Ollama simulado— está en tests/test_llm_runtime.py::test_catalogo."""
    js = js_hud()
    rt = (ROOT / "backend" / "core" / "llm_runtime.py").read_text(encoding="utf-8")
    check("Ollama no lo está sirviendo" in rt,
          "se marcan los modelos que están solo en el disco")
    check("no sirve de cerebro" in rt,
          "un modelo de embeddings se marca y no se puede elegir de cerebro")
    trozo = js.split("function fillLocalModelSelect")[1][:1400]
    check("m.note" in trozo, "el desplegable muestra el motivo que manda el servidor")
    check("m.usable ? '' : ' disabled'" in trozo,
          "…y lo que no vale sale deshabilitado en la lista")
    check("utilizables de" in js,
          "y el botón dice cuántos son UTILIZABLES, no cuántos hay en el disco")


def test_ollama_usa_el_modelo_de_la_peticion():
    src = (ROOT / "backend" / "core" / "llm.py").read_text(encoding="utf-8")
    check('getattr(prov, "model", "")' in src,
          "se nombra el modelo de la petición, no el que hubiera en ⚙ hace un rato")
    check("_diagnostico_ollama_404(model, cuerpo)" in src,
          "el 404 pasa por el diagnóstico, no por una conclusión fija")


if __name__ == "__main__":
    tests = [test_encender_es_una_orden_absoluta,
             test_apagar_usa_el_interruptor_solo_tras_leer_el_estado,
             test_encender_una_tv_dormida_no_manda_tecla,
             test_encender_una_tv_viva_manda_encender,
             test_encender_dos_veces_no_la_apaga,
             test_el_estado_se_persiste, test_apagar_devuelve_estado,
             test_apagar_lo_ya_apagado_no_pulsa_nada,
             test_apagar_no_afirma_lo_que_no_ha_comprobado,
             test_apagar_avisa_cuando_no_puede_confirmarlo,
             test_apagar_a_ciegas_no_pulsa_el_interruptor,
             test_apagar_no_se_queda_esperando_para_siempre,
             test_la_tv_que_se_toca_es_la_que_has_nombrado,
             test_el_dictado_no_escribe_robledo_y_aun_asi_se_entiende,
             test_una_errata_en_el_nombre_no_deja_la_tv_inalcanzable,
             test_contestar_a_la_pregunta_de_que_tele_es_una_orden,
             test_las_tvs_no_se_cuentan_por_duplicado,
             test_mandar_una_tecla_no_es_que_la_tv_obedezca,
             test_la_ip_caducada_se_resuelve_desde_la_mac,
             test_que_algo_sea_tv_lo_dice_la_configuracion_no_su_nombre,
             test_home_assistant_tambien_devuelve_estado,
             test_el_hud_usa_el_estado_del_backend,
             test_ollama_no_acusa_sin_comprobar,
             test_ollama_reintenta_por_la_via_antigua,
             test_ollama_distingue_ruta_de_modelo,
             test_mensajes_coherentes_cuando_no_hay_cerebro,
             test_el_selector_distingue_disponible_de_en_disco,
             test_ollama_usa_el_modelo_de_la_peticion]
    for t in tests:
        print(f"· {t.__name__}")
        try:
            t()
        except Exception as e:
            _fail.append(f"{t.__name__} EXCEPCIÓN: {type(e).__name__}: {e}")
            print("  EXCEPCIÓN:", type(e).__name__, e)
    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    sys.exit(1 if _fail else 0)
