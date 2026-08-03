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
    """ENCENDER nunca puede ser un interruptor: no hay estado que lo haga seguro
    (la TV dormida no contesta), así que solo vale la tecla absoluta."""
    src = (ROOT / "skills" / "domotica" / "skill.py").read_text(encoding="utf-8")
    check('"KEY_POWERON"' in src, "encender usa KEY_POWERON")
    i_on = src.find("async def _tv_power_on")
    bloque = src[i_on:src.find("\nasync def", i_on + 10)]
    check('"KEY_POWER"' not in bloque,
          "encender no puede usar el interruptor KEY_POWER")


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
        return tv.get("ip", "")

    async def _estado(ip):
        return secuencia.pop(0) if secuencia else "off"

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
    check("sigue diciendo que está encendida" in r["reply"],
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
    check("no puedo confirmarte" in r["reply"], f"y se avisa de que no consta ({r['reply']})")
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
    check("podría encenderla" in r["reply"],
          f"diciendo por qué no se ha usado el interruptor ({r['reply']})")
    check(guardado == [], "sin persistir ningún estado")


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
    check("await _tv_estado(ip)" in src[i_ap:src.find("\nasync def", i_ap + 10)],
          "quien apaga comprueba el resultado leyendo el estado")


def test_la_ip_caducada_se_resuelve_desde_la_mac():
    """La IP la reparte el router y caduca; la MAC no. Si la guardada no contesta,
    se busca la MAC en la tabla ARP y se ACTUALIZA la configuración."""
    m = _skill()
    m._tv_esta_viva = lambda ip, timeout=1.2: asyncio.sleep(0, result=False)
    m._ip_for_mac = lambda mac: "192.168.1.77"
    ctx = _ctx([{"name": "TV", "ip": "192.168.1.50", "mac": "AA:BB:CC:DD:EE:FF",
                 "is_tv": True}])
    ip = asyncio.run(m._tv_ip_actual(ctx, {"ip": "192.168.1.50",
                                           "mac": "AA:BB:CC:DD:EE:FF"}))
    check(ip == "192.168.1.77", f"se actúa contra la IP viva, no la caducada ({ip})")
    check(ctx["settings"]["known_devices"][0]["ip"] == "192.168.1.77",
          "y la nueva queda guardada para la próxima orden")

    # sin MAC no hay de dónde sacarla: se dice, no se inventa
    m._ip_for_mac = lambda mac: ""
    ip2 = asyncio.run(m._tv_ip_actual(_ctx(), {"ip": "192.168.1.50", "mac": ""}))
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
