# -*- coding: utf-8 -*-
"""Auditoría de la skill domotica: ¿se ACTIVA, llega y hace lo que promete?

La pregunta no es «¿está bien escrita?» sino «¿llega la frase del usuario hasta
ella?». Por eso NO prueba las regex sueltas: enruta con el enrutador DE VERDAD
(`skills_loader.load_skills()` + `route()`), que recorre las carpetas por orden
ALFABÉTICO y se queda con la PRIMERA regex que case. `domotica` va muy pronto en
el alfabeto, así que además se comprueba que no le roba frases a `media`,
`system_pc`, `files` ni `ai_media`.

REGLA ABSOLUTA: NI UN paquete a la red. Ningún test enciende, apaga ni toca un
aparato real; `wake_on_lan`, `_discover_all`, `_resolve_tv`, `_tv_key` y
`_ha_states` se sustituyen por dobles. Sin Home Assistant, sin red y sin
credenciales, esta suite pasa entera.

Ejecutar: .venv\\Scripts\\python.exe tests\\test_skill_domotica.py
"""
import asyncio
import os
import re
import sys
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from backend.core import skills_loader          # noqa: E402

_fail, _pass = [], 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


skills_loader.load_skills()
DOM = skills_loader.get_skills()["domotica"].module
SRC = Path(ROOT, "skills", "domotica", "skill.py").read_text(encoding="utf-8")
DOC = Path(ROOT, "skills", "domotica", "SKILL.md").read_text(encoding="utf-8")


def _ruta(frase):
    r = skills_loader.route(frase)
    return (r[0].folder, r[1]) if r else (None, None)


def _match(frase):
    r = skills_loader.route(frase)
    return r[2] if r else None


# --------------------------------------------------------------- dobles
class _Ajustes:
    """Ajustes en memoria. No lee ni escribe config/settings.json ni secrets.json."""

    def __init__(self, valores=None, secretos=None):
        self._v = dict(valores or {})
        self._s = dict(secretos or {})

    def get(self, k, d=None):
        return self._v.get(k, d)

    def set(self, k, v):
        self._v[k] = v

    def secret(self, k, d=""):
        return self._s.get(k, d)

    def set_secret(self, k, v):
        self._s[k] = v


def _ctx(valores=None, secretos=None):
    return {"settings": _Ajustes(valores, secretos), "channel": "pc"}


class _Parche:
    """Sustituye atributos del módulo y los restaura al salir."""

    def __init__(self, **kw):
        self.kw = kw

    def __enter__(self):
        self.old = {k: getattr(DOM, k) for k in self.kw}
        for k, v in self.kw.items():
            setattr(DOM, k, v)
        return self

    def __exit__(self, *a):
        for k, v in self.old.items():
            setattr(DOM, k, v)
        return False


def _corre(intent, frase, ctx, match=None):
    return asyncio.run(DOM.handle(intent, frase, match or _match(frase), ctx))


# ============ 1. ¿SE ACTIVAN LOS 9 INTENTS CON FRASES NATURALES? =============
# Frases como las diría alguien de viva voz, NO la regex leída al revés: con y
# sin tilde, con y sin enclítico, singular y plural, y con sinónimos. Si una se
# cae, la skill es inalcanzable por ahí y la frase acaba en el planificador del
# cerebro, que es justo donde nexus se inventa cosas.
FRASES = {
    "descubrir": ["escanea la red", "escanéame la red", "rastrea la red local",
                  "qué dispositivos hay conectados", "que aparatos hay en el wifi",
                  "cuántos cacharros hay conectados", "muéstrame los dispositivos de la red",
                  "enséñame los aparatos conectados", "haz un escaneo de la red",
                  "lista los dispositivos conectados", "quién está conectado al wifi",
                  "dime qué hay conectado a mi red", "mira a ver qué aparatos hay en casa",
                  "detecta los dispositivos de casa", "revisa qué hay conectado"],
    "tv_on": ["enciende la tele", "enciéndeme la tele", "enciéndela la tele",
              "pon la tele", "ponme la television", "enciende la televisión",
              "arranca la tv", "préndeme la tele", "quiero ver la tele",
              "enciende el televisor", "enciende la smart tv", "dale a la tele"],
    "tv_off": ["apaga la tele", "apágame la televisión", "apágala la tele",
               "apaga la tv", "apaga el televisor", "quita la tele",
               "desconecta la television", "apágalo el televisor"],
    "tv_mute": ["silencia la tele", "quita el sonido de la tele", "mutea la tv",
                "quítale el volumen a la tele", "pon la tele en silencio",
                "silénciame la tele", "calla la tele", "quita el ruido de la tele"],
    # El volumen EXIGE nombrar la tele, igual que silenciarla: el destino lo dice
    # siempre quien da la orden. El volumen a secas es de system_pc, que pregunta.
    "tv_volume": ["sube el volumen de la tele", "súbeme el volumen de la tv",
                  "baja el volumen del televisor", "bájale el volumen a la tele",
                  "más volumen en la televisión", "menos volumen en la tele",
                  "baja un poco el volumen de la tv"],
    "tv_channel": ["pon el canal 5", "ponme el canal 3", "cámbiame al canal 7",
                   "cambia al canal 12", "canal siguiente", "siguiente canal",
                   "canal anterior", "pon el canal cinco", "quiero el canal 1"],
    "tv_app": ["pon netflix en la tele", "abre youtube en la tv",
               "quiero ver netflix en la televisión", "en la tele pon netflix",
               "lanza disney+ en la tele", "pon hbo en la tv"],
    "wol": ["enciende el pc", "enciéndeme el ordenador", "arranca el servidor",
            "despierta el nas", "levanta la torre", "enciende el portátil",
            "prende el sobremesa", "enciende mi equipo", "despiértame el ordenador"],
    "casa": ["enciende la luz del salón", "apaga la luz de la cocina",
             "apágame las luces", "enciéndeme la lámpara del dormitorio",
             "baja la persiana", "sube la persiana del salón", "cierra la persiana",
             "pon la calefacción", "apaga el aire", "enciende el ventilador",
             "apaga el enchufe de la cocina", "enciende las luces del pasillo",
             "apaga la luz", "enciende la bombilla del baño", "quita la luz del salón",
             "ponme la calefacción", "abre la persiana de la terraza",
             "enciende la cafetera", "apaga el humidificador"],
}


def test_todos_los_intents_declarados_tienen_frases_de_prueba():
    declarados = set(DOM.SKILL["patterns"])
    check(declarados == set(FRASES),
          f"intents sin frases: {sorted(declarados - set(FRASES))}; "
          f"frases de intents inexistentes: {sorted(set(FRASES) - declarados)}")


def test_cada_intent_se_activa_con_frases_naturales():
    for intent, frases in FRASES.items():
        for frase in frases:
            folder, real = _ruta(frase)
            check(folder == "domotica" and real == intent,
                  f"«{frase}» → {folder}/{real} (se esperaba domotica/{intent})")


def test_ningun_intent_se_queda_sin_rama_en_handle():
    """Un patrón que enruta a un intent que handle() no atiende cae al mensaje
    genérico del final: enruta, pero no hace nada."""
    for intent in DOM.SKILL["patterns"]:
        check(f'"{intent}"' in SRC.split("async def handle(")[1],
              f"el intent «{intent}» enruta pero handle() no lo atiende")


# ============ 2. TILDES Y ENCLÍTICOS (el fallo que más se repite) ============
def test_el_pronombre_enclitico_desplaza_la_tilde_y_aun_asi_casa():
    """En español el enclítico MUEVE la tilde: apaga→apágalo, enciende→enciéndelo,
    quita→quítale, silencia→silénciame. Escribir el patrón con el verbo sin tilde
    deja fuera frases perfectamente normales."""
    casos = {
        "apágalo el televisor": "tv_off",
        "apágame la tele": "tv_off",
        "quítale el sonido a la tele": "tv_mute",
        "silénciame la tele": "tv_mute",
        "enciéndeme la tele": "tv_on",
        "cámbiame al canal 9": "tv_channel",
        "súbeme el volumen de la tele": "tv_volume",
        "enciéndeme el ordenador": "wol",
        "despiértame el pc": "wol",
        "apágame la luz del salón": "casa",
        "enciéndeme el ventilador": "casa",
        "quítame la luz de la cocina": "casa",
        "ciérrame la persiana": "casa",
        "escanéame la red": "descubrir",
    }
    for frase, esperado in casos.items():
        folder, intent = _ruta(frase)
        check(folder == "domotica" and intent == esperado,
              f"«{frase}» → {folder}/{intent} (se esperaba domotica/{esperado})")


def test_televisor_no_es_menos_tele_que_tele():
    """«televisor» es la palabra más normal del mundo y `tele` no la caza: en
    «televisor» no hay frontera de palabra tras «tele»."""
    for frase, esperado in (("enciende el televisor", "tv_on"),
                            ("apaga el televisor", "tv_off"),
                            ("silencia el televisor", "tv_mute")):
        folder, intent = _ruta(frase)
        check(folder == "domotica" and intent == esperado,
              f"«{frase}» → {folder}/{intent} (se esperaba {esperado})")


def test_silenciar_gana_a_apagar_y_a_encender():
    """«quita el sonido de la tele» casa también con tv_off y «pon la tele en
    silencio» con tv_on: el orden del dict decide, y silenciar va primero."""
    orden = list(DOM.SKILL["patterns"])
    check(orden.index("tv_mute") < orden.index("tv_off"),
          "tv_mute tiene que ir ANTES que tv_off en el dict de patterns")
    check(orden.index("tv_mute") < orden.index("tv_on"),
          "tv_mute tiene que ir ANTES que tv_on en el dict de patterns")
    for frase in ("quita el sonido de la tele", "pon la tele en silencio",
                  "quítale el volumen a la tv"):
        check(_ruta(frase) == ("domotica", "tv_mute"),
              f"«{frase}» → {_ruta(frase)}; era silenciar")


# ==================== 3. COLISIONES CON OTRAS SKILLS =========================
def test_no_le_roba_el_volumen_de_la_musica_ni_el_del_pc():
    """`domotica` va antes que `media` y `system_pc` por alfabeto, así que si su
    volumen no exigiera la palabra «tele» se quedaría con todas las órdenes de
    volumen del sistema. El volumen sin tele NO es suyo, ni siquiera a secas."""
    for frase in ("sube el volumen de spotify", "baja el volumen de la música",
                  "sube el volumen del pc", "baja el volumen del vídeo",
                  "sube el volumen de youtube", "sube el volumen", "más volumen",
                  "pon el volumen al 50", "silencia", "quita el sonido"):
        folder, intent = _ruta(frase)
        check(folder != "domotica",
              f"«{frase}» → {folder}/{intent}; eso no es la tele")


def test_no_le_roba_ordenes_a_media_system_pc_ni_files():
    ajenas = {
        "pon música": "media",
        "pon spotify": "media",
        "pon youtube": "media",
        "apaga el pc": "system_pc",
        "apaga el ordenador": "system_pc",
        "pon el volumen al 50": "system_pc",
        "abre la carpeta de descargas": "files",
        "busca en la red el precio del bitcoin": "ai_media",
    }
    for frase, esperado in ajenas.items():
        folder, intent = _ruta(frase)
        check(folder == esperado,
              f"«{frase}» → {folder}/{intent}; era de {esperado}")


def test_apagar_el_pc_es_del_pc_y_encenderlo_es_wake_on_lan():
    """«apaga el pc» apaga ESTE equipo (system_pc); «enciende el pc» solo puede
    ser un paquete Wake-on-LAN a otro. Confundirlos apaga la máquina del usuario."""
    check(_ruta("apaga el pc")[0] == "system_pc", "«apaga el pc» no es de system_pc")
    check(_ruta("enciende el pc") == ("domotica", "wol"), "«enciende el pc» no es wol")


# ============== 4. HONESTIDAD DEL ERROR (sin HA, sin red, sin nada) ==========
def test_sin_home_assistant_dice_QUE_falta_y_DONDE_se_pone():
    r = _corre("casa", "enciende la luz del salón", _ctx())
    txt = r["reply"]
    check("Traceback" not in txt, "suelta un traceback en vez de explicarse")
    check("Home Assistant" in txt, "no dice qué falta")
    check("token" in txt.lower() and "⚙" in txt, "no dice CÓMO se arregla")
    check("Encendido" not in txt and "Apagado" not in txt,
          "dice que ha hecho algo sin haber hablado con nadie")


def test_con_home_assistant_configurado_pero_mudo_NO_manda_a_configurarlo_otra_vez():
    """Con URL y token puestos, un HA que no contesta no es un HA sin configurar.
    Decir «aún no tengo Home Assistant conectado» manda al usuario a reconfigurar
    lo que ya está bien."""
    ctx = _ctx({"homeassistant_url": "http://ha.local:8123"},
               {"homeassistant_token": "un-token"})
    with _Parche(_ha_states=lambda c: _async([])):
        r = _corre("casa", "enciende la luz del salón", ctx)
    txt = r["reply"]
    check("Traceback" not in txt, "suelta un traceback")
    check("ha.local" in txt, "no dice contra qué URL lo ha intentado")
    check("Aún no tengo Home Assistant conectado" not in txt,
          "dice que HA no está configurado cuando SÍ lo está")
    check("token" in txt.lower(), "no apunta a la causa probable (token/no responde)")


def test_sin_tv_a_la_vista_dice_como_ensenarsela():
    with _Parche(_resolve_tv=lambda c: _async(None)):
        for intent, frase in (("tv_on", "enciende la tele"),
                              ("tv_off", "apaga la tele"),
                              ("tv_mute", "silencia la tele"),
                              ("tv_volume", "sube el volumen de la tele"),
                              ("tv_channel", "pon el canal 5"),
                              ("tv_app", "pon netflix en la tele")):
            txt = _corre(intent, frase, _ctx())["reply"]
            check("Traceback" not in txt, f"«{frase}»: traceback")
            check("⚙" in txt or "mando" in txt,
                  f"«{frase}»: no dice cómo enseñarle la TV: {txt[:90]}")
            check("Encendiendo" not in txt and "Apagando" not in txt,
                  f"«{frase}»: dice que ha actuado sobre una TV que no existe")


def test_sin_mac_no_finge_haber_encendido_nada():
    r = _corre("wol", "enciende el pc", _ctx())
    txt = r["reply"]
    check("Traceback" not in txt, "suelta un traceback")
    check("MAC" in txt and "⚙" in txt, f"no dice qué falta ni dónde: {txt[:90]}")
    check("enviado" not in txt, "dice que ha enviado el paquete sin tener MAC")


def test_la_red_vacia_se_dice_no_se_rellena():
    """Un escaneo sin respuesta es un escaneo sin respuesta. Inventar aparatos
    para no quedar mal es el fallo estrella de este proyecto."""
    with _Parche(_discover_all=lambda c: _async(
            {"devices": {}, "live": set(), "n_ha": 0, "n_upnp": 0, "n_mdns": 0})):
        txt = _corre("descubrir", "escanea la red", _ctx())["reply"]
    check("Traceback" not in txt, "suelta un traceback")
    check(not re.search(r"\d{1,3}(?:\.\d{1,3}){3}", txt),
          f"la respuesta de una red vacía trae IPs de algún sitio: {txt[:120]}")
    check("⚙" in txt, "no dice qué hacer si el descubrimiento viene en blanco")


def test_un_intent_desconocido_no_finge_haberlo_hecho():
    txt = _corre("inventado", "haz cualquier cosa", _ctx(), match=None)["reply"]
    check("no la tengo mapeada" in txt, f"no admite que no sabe hacerlo: {txt[:90]}")


# ================= 5. ¿INVENTA DATOS? (el fallo estrella) ====================
def test_el_listado_sale_SOLO_de_lo_que_devuelve_el_escaneo():
    falso = {"10.0.0.7": {"ip": "10.0.0.7", "mac": "aa:bb:cc:dd:ee:ff", "vendor": "",
                          "ssdp_type": "", "names": {"aparato-de-prueba"},
                          "services": set(), "live": True, "port_type": ""}}
    with _Parche(_discover_all=lambda c: _async(
            {"devices": falso, "live": {"10.0.0.7"}, "n_ha": 0, "n_upnp": 0, "n_mdns": 0})):
        txt = _corre("descubrir", "escanea la red", _ctx())["reply"]
    ips = set(re.findall(r"\d{1,3}(?:\.\d{1,3}){3}", txt))
    check(ips == {"10.0.0.7"},
          f"el listado trae IPs que no venían del escaneo: {sorted(ips)}")
    check("aparato-de-prueba" in txt, "no muestra el nombre que dio la red")
    check("1 dispositivo" in txt, f"el recuento no cuadra con lo encontrado: {txt[:80]}")


def test_una_mac_desconocida_no_recibe_un_fabricante_inventado():
    check(DOM._mac_vendor("02:00:00:00:00:01") == "",
          "se inventa el fabricante de una MAC que no está en la tabla OUI")
    check(DOM._mac_vendor("") == "", "devuelve fabricante para una MAC vacía")


def test_el_codigo_no_lleva_dispositivos_de_ejemplo_a_fuego():
    """Ni una IP completa ni una MAC escritas en el código: serían datos falsos
    servidos como si fueran de la red del usuario."""
    ips = re.findall(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])", SRC)
    permitidas = {"239.255.255.250", "224.0.0.251", "255.255.255.255", "8.8.8.8"}
    check(not (set(ips) - permitidas),
          f"IPs a fuego que no son direcciones estándar: {sorted(set(ips) - permitidas)}")
    macs = [m for m in re.findall(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b", SRC)
            if m != "AA:BB:CC:DD:EE:FF"]          # el formato de ejemplo del error
    check(not macs, f"MACs completas escritas en el código: {macs[:3]}")


def test_no_hay_datos_ni_nombres_personales_del_usuario():
    """La skill la instala cualquiera: ni un nombre propio, ni una marca concreta
    del usuario, ni una IP suya, ni un ejemplo con datos reales."""
    for texto, donde in ((SRC, "skill.py"), (DOC, "SKILL.md")):
        for palabra in ("adri", "maqueda", "achoz"):
            check(palabra not in texto.lower(),
                  f"«{palabra}» aparece en {donde}: dato personal del usuario")


# ================= 6. ¿HACE LO QUE PROMETE EL SKILL.md? =====================
def test_el_skill_md_no_promete_frases_que_no_se_activan():
    """Cada frase entrecomillada del SKILL.md tiene que llegar a esta skill. Una
    frase de ejemplo que no enruta es una mentira al LLM y al usuario."""
    ejemplos = [re.sub(r"\s+", " ", f).strip() for f in re.findall(r"«([^»]{6,70})»", DOC)]
    # Lo que el SKILL.md entrecomilla SIN prometer que lo atienda esta skill:
    # nombres de menús, contraejemplos y las órdenes que van a otras skills.
    ignorar = ("Tokens de acceso", "enciende estudio", "TV Samsung", "habitación",
               "tele/tv", "a secas", "MAC del PC", "buscar dispositivos",
               "encendido por red", "del PC", "App de escritorio",
               "sube el volumen de Spotify")
    for frase in ejemplos:
        if any(x in frase for x in ignorar) or frase.startswith("http"):
            continue
        folder, intent = _ruta(frase)
        check(folder == "domotica",
              f"el SKILL.md pone «{frase}» como ejemplo y enruta a {folder}/{intent}")


def test_lo_que_el_skill_md_dice_que_necesita_es_lo_que_lee_el_codigo():
    for clave in ("homeassistant_url", "homeassistant_token", "known_devices", "wol_mac"):
        check(clave in SRC, f"el SKILL.md documenta «{clave}» y el código no lo lee")
    check("/api/home/ha_test" in Path(ROOT, "backend", "app.py").read_text(encoding="utf-8"),
          "el SKILL.md promete el endpoint /api/home/ha_test y no existe")
    for dominio in ("light", "switch", "fan", "cover", "climate", "media_player",
                    "input_boolean", "scene", "script"):
        check(f'"{dominio}"' in SRC,
              f"el SKILL.md promete controlar el dominio «{dominio}» de HA y no está")


def test_apagar_nunca_puede_acabar_encendiendo():
    """El SKILL.md promete apagar, no cambiar de estado. En Tizen la única tecla
    que apaga es el interruptor KEY_POWER, así que «apagar» tiene que leer el
    estado antes y pulsarlo SOLO con «encendida» confirmada: descartar «apagada»
    no basta, porque queda un estado intermedio que también puede ser reposo."""
    check('"KEY_POWERON"' in SRC, "encender sigue siendo una orden absoluta")
    i = SRC.find("async def _tv_apagar")
    check(i > 0, "existe un camino de apagado propio, no una tecla suelta")
    bloque = SRC[i:SRC.find("\nasync def", i + 10)]
    check("_tv_estado(ip)" in bloque and 'antes == "off"' in bloque,
          "apagar lee el estado antes y no pulsa si ya está apagada")
    check('antes != "on"' in bloque and "_TECLA_APAGADO_SEGURA" in bloque,
          "y sin confirmación de que está encendida manda la tecla que no enciende")
    # y ninguna ruta de apagado manda la tecla a pelo, saltándose la comprobación
    check(SRC.count('"KEY_POWER"') == 1,
          "el interruptor solo aparece en el mapa de teclas, no suelto por el código")


# ================= 7. COMPORTAMIENTO CON DOBLES (sin tocar nada) ============
def _async(valor):
    async def _f(*a, **kw):
        return valor
    return _f()


def _corutina(valor):
    async def _f(*a, **kw):
        return valor
    return _f


def test_el_canal_dicho_con_letra_llega_como_numero():
    pulsadas = []

    async def _falso_key(ctx, tv, roku, samsung):
        pulsadas.append(samsung)
        return True

    with _Parche(_resolve_tv=_corutina({"name": "TV", "ip": "", "brand": "roku"}),
                 _tv_key=_falso_key):
        r = _corre("tv_channel", "pon el canal cinco", _ctx())
    check("KEY_5" in pulsadas, f"«pon el canal cinco» no pulsó el 5: {pulsadas}")
    check("canal 5" in r["reply"], f"la respuesta no menciona el canal: {r['reply']}")


def test_el_wake_on_lan_no_se_manda_a_la_TV_cuando_pides_el_pc():
    """known_devices lo llena el escáner con las TVs. Coger «la primera MAC que
    haya» manda el paquete mágico a la tele y contesta que ha encendido el PC."""
    enviados = []
    ctx = _ctx({"known_devices": [
        {"name": "TV salón", "mac": "aa:aa:aa:aa:aa:aa", "is_tv": True},
        {"name": "Torre trabajo", "mac": "bb:bb:bb:bb:bb:bb"}]})
    with _Parche(wake_on_lan=lambda mac, bcast="": enviados.append(mac) or True):
        r = _corre("wol", "enciende el pc", ctx)
    check(enviados == ["bb:bb:bb:bb:bb:bb"],
          f"el paquete fue a {enviados}, no al equipo que NO es una TV")
    check("aa:aa" not in r["reply"], "la respuesta nombra la MAC de la TV")


def test_el_wake_on_lan_prefiere_la_mac_configurada_a_mano():
    enviados = []
    ctx = _ctx({"wol_mac": "cc:cc:cc:cc:cc:cc",
                "known_devices": [{"name": "TV", "mac": "aa:aa:aa:aa:aa:aa", "is_tv": True}]})
    with _Parche(wake_on_lan=lambda mac, bcast="": enviados.append(mac) or True):
        r = _corre("wol", "enciende el pc", ctx)
    check(enviados == ["cc:cc:cc:cc:cc:cc"], f"no usó la MAC de ⚙: {enviados}")
    check("enviado" in r["reply"], "no confirma el envío cuando sí lo ha hecho")


def test_apagar_una_TV_que_no_contesta_no_dice_que_la_ha_apagado():
    """La TV está encendida pero no acepta la orden: ni se dice que se ha apagado
    ni se calla con quién se ha intentado."""
    with _Parche(_resolve_tv=_corutina({"name": "TV", "ip": "10.0.0.9", "brand": "roku"}),
                 _tv_ip_actual=_corutina("10.0.0.9"),
                 _tv_estado=_corutina("on"),
                 _tv_key=_corutina("")):
        txt = _corre("tv_off", "apaga la tele", _ctx())["reply"]
    check("apagada" not in txt.lower(), "dice que apaga una TV que no ha respondido")
    check("10.0.0.9" in txt, "no dice con qué aparato lo ha intentado")


# --------------------------------------------------------------- funciones puras
def test_las_ayudas_puras_no_adornan_lo_que_no_saben():
    check(DOM._upnp_name_from_xml("") == {}, "saca un nombre de un XML vacío")
    check(DOM._upnp_name_from_xml("<friendlyName> Salón </friendlyName>")["friendly"] == "Salón",
          "no lee el friendlyName del XML UPnP")
    check(DOM._label_device({}) == "Dispositivo de red",
          "etiqueta un aparato sin ninguna pista con algo concreto")
    check(DOM._is_junk_ip("192.168.1.255") and DOM._is_junk_ip("239.255.255.250"),
          "cuela broadcast/multicast como si fueran aparatos")
    check(not DOM._is_junk_ip("10.0.0.4"), "descarta una IP normal")
    check(DOM._is_generic_name("TV Samsung", "samsung"), "«TV Samsung» no es genérico")
    check(not DOM._is_generic_name("TV del estudio", "samsung"),
          "toma un nombre propio por genérico")
    check(DOM._pick_name({"friendly": "Altavoz cocina"}, None, "Altavoz") == "Altavoz cocina",
          "el nombre que difunde el aparato no gana a la etiqueta de tipo")
    check(DOM._wants_on("enciende la luz") and not DOM._wants_on("apaga la luz"),
          "confunde encender con apagar")


# ------------------------------------------------------------------ ejecución
if __name__ == "__main__":
    print("== Auditoría de la skill domotica ==")
    for nombre, fn in sorted(list(globals().items())):
        if nombre.startswith("test_") and callable(fn):
            print("-", nombre)
            fn()
    print(f"\n{_pass} comprobaciones OK, {len(_fail)} fallos")
    if _fail:
        print("\nFALLOS:")
        for f in _fail:
            print("  -", f)
    sys.exit(1 if _fail else 0)
