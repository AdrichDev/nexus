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
import os
import re
import sys
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

def test_las_teclas_son_absolutas_no_interruptores():
    m = _skill()
    check(m._TV_KEYMAP["off"][1] == "KEY_POWEROFF",
          f"apagar manda KEY_POWEROFF, no el interruptor ({m._TV_KEYMAP['off'][1]})")
    src = (ROOT / "skills" / "domotica" / "skill.py").read_text(encoding="utf-8")
    # KEY_POWER a secas no puede aparecer como orden de encendido/apagado
    usos = re.findall(r'"(KEY_POWER)"', src)
    check(not usos, f"no queda ninguna orden con el interruptor KEY_POWER ({len(usos)})")
    check('"KEY_POWERON"' in src, "encender usa KEY_POWERON")
    check('"KEY_POWEROFF"' in src, "apagar usa KEY_POWEROFF")


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


def test_apagar_devuelve_estado():
    m = _skill()
    m._save_tv = lambda ctx, tv: None
    guardado = []
    m._save_estado = lambda ctx, tv, on: guardado.append(on)
    m._mac_for_ip = lambda ip: ""

    async def _key(ctx, tv, roku, samsung):
        return True
    m._tv_key = _key
    r = asyncio.run(m.control_api(_ctx(), {"kind": "tv", "action": "off",
                                           "ip": "192.168.1.50", "brand": "samsung",
                                           "name": "TV"}))
    check(r["ok"] and r.get("state") == "off", f"apagar devuelve el estado ({r})")
    check(guardado == [False], "y lo persiste")


def test_home_assistant_tambien_devuelve_estado():
    src = (ROOT / "skills" / "domotica" / "skill.py").read_text(encoding="utf-8")
    i_ha = src.find('if kind == "ha":')
    bloque = src[i_ha:src.find('if kind == "tv":')]
    check('"state": (estado if ok else None)' in bloque,
          "Home Assistant también devuelve el estado resultante")
    check("None" in bloque, "y no inventa estado si la orden falló")


# ══════════════ 3. El HUD pinta lo que dice el backend ══════════════

def test_el_hud_usa_el_estado_del_backend():
    js = (ROOT / "frontend" / "js" / "command.js").read_text(encoding="utf-8")
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
    L.settings.set("llm_provider", "ollama")
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


def test_el_selector_distingue_disponible_de_en_disco():
    """Mismo requisito de siempre, comprobado donde ahora vive.

    Antes estos textos los escribía el JavaScript con su propio criterio; desde
    el runtime v24 los decide el BACKEND (una sola clasificación para todos) y
    el navegador solo los pinta. La comprobación de comportamiento real —con un
    Ollama simulado— está en tests/test_llm_runtime.py::test_catalogo."""
    js = (ROOT / "frontend" / "js" / "command.js").read_text(encoding="utf-8")
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
    tests = [test_las_teclas_son_absolutas_no_interruptores,
             test_encender_una_tv_dormida_no_manda_tecla,
             test_encender_una_tv_viva_manda_encender,
             test_encender_dos_veces_no_la_apaga,
             test_el_estado_se_persiste, test_apagar_devuelve_estado,
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
