# -*- coding: utf-8 -*-
"""EL CEREBRO NO CAMBIA DE CASA SIN PERMISO (AI-01/PRIV-02) Y NADIE ESCRIBE SIN TOPE (AI-07).

El fallo que se prueba aquí (auditoría del 30/07/2026, P1-5):

    Ollama apagado + una clave de OpenAI puesta
    → `get_provider()` se quedaba con OpenAI y punto.
    → la memoria, el perfil y los documentos recuperados salían del equipo
      dentro del prompt, sin que nadie hubiera dicho que sí.

Lo que se comprueba, y por qué cada cosa:

  * sin `permitir_fallback_nube`, un cerebro LOCAL caído NO cae en la nube:
    levanta `SinCerebro`, el mensaje lo dice en cristiano y NO se hace ni una
    llamada a un host de nube (se espía el cliente HTTP, no se confía en la
    intención del código);
  * con el permiso puesto sí cae, y además lo AVISA por el bus de eventos que ya
    existe (`log`), porque el contexto empieza a salir del equipo;
  * si hay otra ruta LOCAL, se usa esa y la nube ni se toca;
  * un cerebro de nube caído sigue cayendo en otro de nube (no hay regresión) y
    deja su `fallback_from`;
  * `mock` no se elige nunca solo;
  * quien ya tenía configurada la nube sigue recibiendo respuesta sin ceremonia
    nueva (no se le pregunta lo que ya eligió);
  * el tope de salida (AI-07) viaja en el cuerpo de CADA proveedor con el nombre
    que cada API usa, sale de config/umbrales.json y no rompe el streaming.

Todo en proceso: `net.client()` doblado (nada sale a la red), configuración y
datos en carpetas de usar y tirar. Sin servidores, sin puertos, sin claves de
verdad. Nivel M.
Ejecutar: python tests/unit/core/runtime/test_fallback_privacidad.py
"""
import asyncio
import json
import json as _json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_fail, _pass = [], 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


# Caja de arena ANTES de importar nada del backend: ni la configuración ni los
# datos del operador se tocan.
_SANDBOX = Path(tempfile.mkdtemp(prefix="nexus_fallback_"))
(_SANDBOX / "data").mkdir()
(_SANDBOX / "config").mkdir()
(_SANDBOX / "config" / "settings.json").write_text(json.dumps({
    "setup_done": True, "llm_provider": "ollama", "llm_local": True,
    "ollama_model": "qwen3:8b",
    "ollama_url": "http://127.0.0.1:9",        # puerto muerto: Ollama "apagado"
    "permitir_fallback_nube": False,
    "cloud_base_url": "https://api.openai.com/v1",
    "tts_engine": "off",
}), encoding="utf-8")
# Claves de mentira: `available()` de la nube solo mira que EXISTA una clave, que
# es justo el comportamiento que hacía peligroso el fallback. Los valores no se
# parecen a ninguna clave real y no se imprimen nunca.
(_SANDBOX / "config" / "secrets.json").write_text(json.dumps({
    "openai_api_key": "doble-de-prueba-openai",
    "anthropic_api_key": "doble-de-prueba-anthropic",
    "gemini_api_key": "doble-de-prueba-gemini",
    "cloud_llm_api_key": "doble-de-prueba-cloud",
}), encoding="utf-8")
os.environ["NEXUS_DATA_DIR"] = str(_SANDBOX / "data")
os.environ["NEXUS_CONFIG_DIR"] = str(_SANDBOX / "config")

import httpx  # noqa: E402

from backend.core.infraestructura import llm  # noqa: E402
from backend.core.infraestructura import llm_runtime as rt  # noqa: E402
from backend.core.comun import events, net  # noqa: E402
from backend.core.comun.config import settings  # noqa: E402

# Los hosts que NO pueden aparecer cuando la reserva a la nube está bloqueada.
NUBE_HOSTS = ("api.openai.com", "api.anthropic.com",
              "generativelanguage.googleapis.com", "openrouter.ai")
_ORIG_CLIENT = net.client


# ══════════════════════════════════════════════════════════════════════════════
#  CLIENTE HTTP DOBLADO — nada sale a la red, y todo queda apuntado
# ══════════════════════════════════════════════════════════════════════════════
class _Resp:
    def __init__(self, obj=None, status=200):
        self._obj = obj if obj is not None else {}
        self.status_code = status
        self.text = json.dumps(self._obj)

    def json(self):
        return self._obj

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("POST", "http://doble-de-prueba"),
                response=httpx.Response(self.status_code))


class _Stream:
    def __init__(self, lineas, status=200):
        self.lineas = lineas
        self.status_code = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aread(self):
        return b""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("POST", "http://doble-de-prueba"),
                response=httpx.Response(self.status_code))

    async def aiter_lines(self):
        for linea in self.lineas:
            yield linea


class _Cliente:
    """`net.client()` doblado: Ollama vivo o apagado, y respuestas fingidas del
    resto. Cada llamada queda en `llamadas` para poder afirmar que NO se llamó a
    un host de nube (una intención en un comentario no prueba nada)."""

    def __init__(self, ollama_vivo: bool = False):
        self.ollama_vivo = ollama_vivo
        self.llamadas: list[tuple[str, str, dict | None]] = []

    async def get(self, url, **kw):
        self.llamadas.append(("GET", url, None))
        if self.ollama_vivo:
            return _Resp({"models": [{"name": "qwen3:8b", "size": 1}]})
        raise httpx.ConnectError("Ollama apagado (doble de prueba)")

    async def post(self, url, json=None, **kw):           # noqa: A002
        self.llamadas.append(("POST", url, json))
        if "/api/chat" in url:
            return _Resp({"message": {"content": "OK-OLLAMA"}})
        if "/api/generate" in url:
            return _Resp({"response": "OK-OLLAMA"})
        if "anthropic" in url:
            return _Resp({"content": [{"type": "text", "text": "OK-ANTHROPIC"}]})
        if "generativelanguage" in url:
            return _Resp({"candidates": [{"content": {"parts": [{"text": "OK-GEMINI"}]}}]})
        return _Resp({"choices": [{"message": {"content": "OK-OPENAI"}}]})

    def stream(self, method, url, json=None, **kw):        # noqa: A002
        self.llamadas.append((method, url, json))
        if "/api/chat" in url:
            return _Stream([_json.dumps({"message": {"content": "trozo-ollama"}})])
        if "generativelanguage" in url:
            fila = _json.dumps({"candidates": [
                {"content": {"parts": [{"text": "trozo-gemini"}]},
                 "finishReason": "STOP"}]})
            return _Stream([f"data: {fila}"])
        return _Stream([f"data: {_json.dumps({'choices': [{'delta': {'content': 'trozo-openai'}}]})}",
                        "data: [DONE]"])

    async def aclose(self):
        return None

    def a_la_nube(self):
        return [c for c in self.llamadas if any(h in c[1] for h in NUBE_HOSTS)]


def _doblado(ollama_vivo: bool = False) -> _Cliente:
    cli = _Cliente(ollama_vivo)
    net.client = lambda: cli
    return cli


def _reset():
    rt._STATUS = rt.LLMRuntimeStatus()
    llm.invalidate_provider()
    settings.set("permitir_fallback_nube", False)
    settings.set("llm_provider", "ollama")
    llm.OllamaProvider._ruta = ""


def run(coro):
    # asyncio.run cierra el loop Y finaliza los generadores asíncronos: con
    # new_event_loop().run_until_complete quedaban tareas colgando en cada test.
    return asyncio.run(coro)


# ══════════════════════════════════════════════════════════════════════════════
#  1. LOCAL CAÍDO, SIN PERMISO: NO SALE NADA
# ══════════════════════════════════════════════════════════════════════════════
def test_sin_permiso_no_hay_reserva_en_la_nube():
    print("· cerebro local caído y clave de nube puesta, sin permiso")
    _reset()
    cli = _doblado(ollama_vivo=False)
    try:
        publico = ""
        try:
            run(llm.get_provider())
            check(False, "con el cerebro local caído y solo nube disponible, "
                         "get_provider() NO puede elegir la nube sin permiso")
        except llm.SinCerebro as exc:
            publico = exc.publico
        check("nube" in publico.lower(),
              f"el mensaje dice que no se va a la nube ({publico!r})")
        check("no voy a mandar" in publico.lower(),
              f"y lo dice en primera persona, sin rodeos ({publico!r})")
        check("permitir_fallback_nube" in publico,
              "nombra el ajuste EXACTO que hay que activar para permitirlo")
        check("⚙" in publico, "y dónde se activa")
        check(not [c for c in cli.llamadas if c[0] == "POST"],
              f"no se ha llamado a NINGÚN proveedor: {cli.llamadas}")
        check(cli.a_la_nube() == [],
              f"ni se ha tocado un host de nube: {cli.a_la_nube()}")
        check(llm._prov_cache["prov"] is None, "no se cachea un proveedor que no se usa")

        # Lo que ve el operador en el chat, no solo la excepción.
        respuesta, proveedor = run(llm.ask_llm("hola"))
        check(proveedor == "ninguno",
              f"la respuesta no se atribuye a un modelo (proveedor={proveedor!r})")
        check("permitir_fallback_nube" in respuesta,
              f"y el chat le dice cómo permitirlo ({respuesta!r})")
        check(proveedor != "mock", "ni se cuela el modo demostración")
    finally:
        net.client = _ORIG_CLIENT


# ══════════════════════════════════════════════════════════════════════════════
#  2. CON PERMISO: SÍ, PERO AVISANDO POR EL BUS
# ══════════════════════════════════════════════════════════════════════════════
def test_con_permiso_cae_en_la_nube_y_avisa():
    print("· con permitir_fallback_nube=True sí cae en la nube, y lo dice")
    _reset()
    settings.set("permitir_fallback_nube", True)
    cli = _doblado(ollama_vivo=False)
    avisos: list[tuple[str, str]] = []

    async def _espia(msg, level="info"):
        avisos.append((level, msg))

    original_log = events.log
    events.log = _espia
    try:
        prov = run(llm.get_provider())
    finally:
        events.log = original_log
        net.client = _ORIG_CLIENT
    check(prov.name == "openai",
          f"la reserva usa el primer proveedor de nube disponible (fue {prov.name!r})")
    check(rt.status().fallback_from == "ollama",
          f"queda anotado de dónde venía (fallback_from={rt.status().fallback_from!r})")
    texto = " ".join(m for _l, m in avisos).lower()
    check(bool(avisos), "el cambio se publica en el bus de eventos que ya existe")
    check("nube" in texto,
          f"y el aviso dice que el proveedor está en la nube ({texto!r})")
    check("ollama" in texto and "openai" in texto,
          f"con los dos nombres: de dónde venía y a dónde va ({texto!r})")
    check(any(lv in ("warning", "warn") for lv, _m in avisos),
          f"y no como un mensaje informativo cualquiera ({avisos})")
    check(cli.a_la_nube() == [],
          "elegir el proveedor NO manda nada por sí solo: solo mira si tiene clave")


# ══════════════════════════════════════════════════════════════════════════════
#  3. HAY OTRA RUTA LOCAL: SE USA ESA Y LA NUBE NI SE TOCA
# ══════════════════════════════════════════════════════════════════════════════
def test_otra_ruta_local_gana_y_la_nube_ni_se_toca():
    print("· si hay otra ruta local, se usa esa")
    _reset()
    cli = _doblado(ollama_vivo=False)

    class _LocalDeMentira:
        """Hoy nexus solo tiene Ollama como proveedor local de verdad, así que la
        regla «lo local primero» se prueba con un segundo proveedor local de
        mentira: lo que se juzga es la REGLA, no cuántos proveedores haya."""
        name = "lmstudio_local"

        async def available(self):
            return True

        async def chat(self, messages):
            return "LOCAL"

    llm.PROVIDERS["lmstudio_local"] = _LocalDeMentira()
    llm.LOCALIDAD["lmstudio_local"] = "local"
    try:
        prov = run(llm.get_provider())
        check(prov.name == "lmstudio_local",
              f"se cambia a la alternativa LOCAL (fue {prov.name!r})")
        check(rt.status().fallback_from == "ollama",
              "y el cambio queda anotado igual")
        check(cli.a_la_nube() == [],
              f"sin tocar un solo host de nube: {cli.a_la_nube()}")
    finally:
        llm.PROVIDERS.pop("lmstudio_local", None)
        llm.LOCALIDAD.pop("lmstudio_local", None)
        net.client = _ORIG_CLIENT
        llm.invalidate_provider()


def test_clasificacion_de_localidad():
    print("· la clase de cada proveedor")
    for nombre in ("ollama", "mock"):
        check(llm.localidad_proveedor(nombre) == "local",
              f"«{nombre}» es LOCAL (el prompt no sale del equipo)")
    for nombre in ("openai", "anthropic", "gemini", "cloud"):
        check(llm.localidad_proveedor(nombre) == "nube",
              f"«{nombre}» es NUBE (el prompt sale del equipo)")
    check(llm.localidad_proveedor("inventado") == "nube",
          "lo que nadie ha clasificado se trata como nube: ante la duda, no se manda")


# ══════════════════════════════════════════════════════════════════════════════
#  4. UN CEREBRO DE NUBE CAÍDO SIGUE CAYENDO EN OTRA NUBE
# ══════════════════════════════════════════════════════════════════════════════
def test_nube_caida_cae_en_otra_nube():
    print("· openai caído con clave de anthropic: comportamiento de siempre")
    _reset()
    settings.set("llm_provider", "openai")
    cli = _doblado(ollama_vivo=False)
    avisos = []

    async def _espia(msg, level="info"):
        avisos.append(msg)

    original_log = events.log
    real_secret = settings.secret
    # OpenAI sin clave propia: `available()` es falso; Anthropic sí la tiene.
    settings.secret = lambda k: "" if k == "openai_api_key" else real_secret(k)
    events.log = _espia
    try:
        prov = run(llm.get_provider())
    finally:
        settings.secret = real_secret
        events.log = original_log
        net.client = _ORIG_CLIENT
        llm.invalidate_provider()
    check(prov.name == "anthropic",
          f"cae en el siguiente proveedor de nube (fue {prov.name!r})")
    check(rt.status().fallback_from == "openai",
          f"con su traza de origen (fallback_from={rt.status().fallback_from!r})")
    check(prov.name != "mock", "y nunca en el modo demostración")
    check(any("nube" in m.lower() for m in avisos),
          f"y el salto entre proveedores de nube también se avisa ({avisos})")
    check(cli.a_la_nube() == [], "sin mandar nada al elegir")


# ══════════════════════════════════════════════════════════════════════════════
#  5. `mock` NUNCA SE ELIGE SOLO
# ══════════════════════════════════════════════════════════════════════════════
def test_mock_nunca_se_cuela():
    print("· el modo demostración solo existe si se elige")
    _reset()
    settings.set("permitir_fallback_nube", True)
    cli = _doblado(ollama_vivo=False)
    real_secret = settings.secret
    settings.secret = lambda k: ""          # ninguna clave de nube
    try:
        try:
            prov = run(llm.get_provider())
            check(False, f"sin ningún proveedor real no puede elegirse {prov.name!r}")
        except llm.SinCerebro:
            check(True, "")
        check(llm._prov_cache["prov"] is None, "no se cachea el simulador")
        check(cli.a_la_nube() == [], "sin tocar la nube")
    finally:
        settings.secret = real_secret
        net.client = _ORIG_CLIENT

    _reset()
    settings.set("llm_provider", "mock")
    try:
        prov = run(llm.get_provider())
        check(prov.name == "mock", "elegido a propósito, sí se usa")
    finally:
        settings.set("llm_provider", "ollama")
        llm.invalidate_provider()


# ══════════════════════════════════════════════════════════════════════════════
#  6. QUIEN YA ELIGIÓ LA NUBE NO PASA POR NINGUNA CEREMONIA NUEVA
# ══════════════════════════════════════════════════════════════════════════════
def test_la_nube_ya_elegida_responde_igual():
    print("· cerebro de nube configurado y con clave: responde sin preguntar nada")
    _reset()
    settings.set("llm_provider", "openai")
    settings.set("permitir_fallback_nube", False)      # ni falta que hace
    _doblado(ollama_vivo=True)
    avisos = []

    async def _espia(msg, level="info"):
        avisos.append(msg)

    original_log = events.log
    events.log = _espia
    try:
        prov = run(llm.get_provider())
        check(prov.name == "openai", f"se usa el que eligió (fue {prov.name!r})")
        check(rt.status().fallback_from == "",
              "sin marcas de reserva: no ha habido ningún cambio")
        respuesta, proveedor = run(llm.ask_llm("hola"))
    finally:
        events.log = original_log
        net.client = _ORIG_CLIENT
        llm.invalidate_provider()
    check(respuesta == "OK-OPENAI",
          f"el operador recibe la respuesta del modelo ({respuesta!r})")
    check(proveedor == "openai", f"y se atribuye al proveedor elegido ({proveedor!r})")
    check(avisos == [], f"sin avisos nuevos ni permisos que pedir ({avisos})")


# ══════════════════════════════════════════════════════════════════════════════
#  7. TOPE DE TOKENS DE SALIDA (AI-07)
# ══════════════════════════════════════════════════════════════════════════════
def test_topes_de_salida_en_cada_proveedor():
    print("· el tope de salida viaja con el nombre que usa cada API")
    _reset()
    cli = _doblado(ollama_vivo=True)
    umbrales = json.loads((ROOT / "config" / "umbrales.json").read_text(encoding="utf-8"))
    seccion = umbrales.get("llm") or {}
    tope = seccion.get("max_tokens_salida")
    try:
        check(isinstance(tope, int) and tope > 0,
              f"config/umbrales.json trae la sección «llm» con su tope ({tope!r})")
        check(bool(seccion.get("_lee_esto")),
              "y explicado dentro del archivo, como el resto")
        check(llm._cap_salida() == tope,
              f"el código lee ese número y no otro ({llm._cap_salida()} vs {tope})")

        msgs = [{"role": "user", "content": "hola"}]

        # Ollama: options.num_predict
        run(llm.PROVIDERS["ollama"].chat(msgs))
        cuerpo = [c[2] for c in cli.llamadas if "/api/chat" in c[1]][-1]
        check((cuerpo.get("options") or {}).get("num_predict") == tope,
              f"Ollama lo manda en options.num_predict ({cuerpo.get('options')})")

        # OpenAI: max_tokens (chat y streaming)
        cli.llamadas.clear()
        run(llm.PROVIDERS["openai"].chat(msgs))
        check(cli.llamadas[-1][2].get("max_tokens") == tope,
              f"OpenAI lo manda en max_tokens ({cli.llamadas[-1][2].get('max_tokens')})")

        # Cloud (compatible OpenAI): max_tokens
        cli.llamadas.clear()
        run(llm.PROVIDERS["cloud"].chat(msgs))
        check(cli.llamadas[-1][2].get("max_tokens") == tope,
              f"la nube compatible OpenAI también ({cli.llamadas[-1][2].get('max_tokens')})")

        # Gemini: generationConfig.maxOutputTokens
        cli.llamadas.clear()
        run(llm.PROVIDERS["gemini"].chat(msgs))
        cuerpo = cli.llamadas[-1][2]
        check((cuerpo.get("generationConfig") or {}).get("maxOutputTokens") == tope,
              f"Gemini en generationConfig.maxOutputTokens "
              f"({(cuerpo.get('generationConfig') or {}).get('maxOutputTokens')})")

        # Y el streaming sigue funcionando (y sigue llevando el tope)
        async def _trozos(prov):
            gen = prov.chat_stream(msgs)
            try:
                return [t async for t in gen]
            finally:
                await gen.aclose()          # cerrar el generador: sin tareas colgando

        cli.llamadas.clear()
        trozos = run(_trozos(llm.PROVIDERS["ollama"]))
        check(trozos == ["trozo-ollama"], f"Ollama sigue streameando ({trozos})")
        check(((cli.llamadas[-1][2] or {}).get("options") or {}).get("num_predict") == tope,
              "y su streaming también lleva el tope")

        cli.llamadas.clear()
        trozos = run(_trozos(llm.PROVIDERS["openai"]))
        check(trozos == ["trozo-openai"], f"OpenAI sigue streameando ({trozos})")
        check((cli.llamadas[-1][2] or {}).get("max_tokens") == tope,
              "y su streaming también lleva el tope")

        cli.llamadas.clear()
        trozos = run(_trozos(llm.PROVIDERS["gemini"]))
        check(trozos == ["trozo-gemini"], f"Gemini sigue streameando ({trozos})")
        check(((cli.llamadas[-1][2] or {}).get("generationConfig") or {})
              .get("maxOutputTokens") == tope,
              "y su streaming también lleva el tope")

        print("· y el número sale del archivo, no del código")
        otra = Path(tempfile.mkdtemp(prefix="nexus_fallback_cfg_"))
        (otra / "umbrales.json").write_text(
            json.dumps({"llm": {"max_tokens_salida": 1234}}), encoding="utf-8")
        vacia = Path(tempfile.mkdtemp(prefix="nexus_fallback_cfg2_"))
        original_dir = llm.CONFIG_DIR
        try:
            llm.CONFIG_DIR = otra
            check(llm._cap_salida() == 1234,
                  f"cambiando el archivo cambia el tope ({llm._cap_salida()})")
            cli.llamadas.clear()
            run(llm.PROVIDERS["openai"].chat(msgs))
            check(cli.llamadas[-1][2].get("max_tokens") == 1234,
                  "y la llamada real usa ese número")
            llm.CONFIG_DIR = vacia
            check(llm._cap_salida() == 4096,
                  f"sin archivo de umbrales se queda la reserva, no 0 "
                  f"({llm._cap_salida()})")
            (otra / "umbrales.json").write_text(
                json.dumps({"llm": {"max_tokens_salida": 0}}), encoding="utf-8")
            llm.CONFIG_DIR = otra
            check(llm._cap_salida() == 4096,
                  "un 0 no se acepta: cortaría todas las respuestas")
        finally:
            llm.CONFIG_DIR = original_dir
            shutil.rmtree(otra, ignore_errors=True)
            shutil.rmtree(vacia, ignore_errors=True)
    finally:
        net.client = _ORIG_CLIENT


# ══════════════════════════════════════════════════════════════════════════════
#  8. NADA DE ESTO HA CAMBIADO LA POLÍTICA DE LOS EMBEDDINGS
# ══════════════════════════════════════════════════════════════════════════════
def test_politica_de_embeddings_intacta():
    print("· la política de embeddings (que ya estaba bien) no se toca")
    umbrales = json.loads((ROOT / "config" / "umbrales.json").read_text(encoding="utf-8"))
    emb = (umbrales.get("memoria") or {}).get("embedding") or {}
    check(emb.get("permitir_nube") is False,
          "los embeddings siguen sin poder salir a la nube")
    from backend.core.comun.config import DEFAULTS
    check(DEFAULTS.get("llm_local") is True, "«modelo local» sigue viniendo activo")
    check(DEFAULTS.get("permitir_fallback_nube") is False,
          "y la reserva en la nube viene APAGADA de fábrica")


def main() -> int:
    # RED PROHIBIDA: si alguna prueba se olvida de instalar su doble, esto revienta
    # en vez de sacar una petición de verdad a internet. Una prueba no toca la red
    # «casi siempre»: no la toca.
    def _prohibido():
        raise RuntimeError("esta prueba no ha instalado su doble de red")

    net.client = _prohibido
    try:
        for f in (test_sin_permiso_no_hay_reserva_en_la_nube,
                  test_con_permiso_cae_en_la_nube_y_avisa,
                  test_otra_ruta_local_gana_y_la_nube_ni_se_toca,
                  test_clasificacion_de_localidad,
                  test_nube_caida_cae_en_otra_nube,
                  test_mock_nunca_se_cuela,
                  test_la_nube_ya_elegida_responde_igual,
                  test_topes_de_salida_en_cada_proveedor,
                  test_politica_de_embeddings_intacta):
            try:
                f()
            except Exception as e:                               # noqa: BLE001
                import traceback
                _fail.append(f"EXCEPCIÓN en {f.__name__}: {type(e).__name__}: {e}")
                print("  EXCEPCIÓN en", f.__name__, ":", type(e).__name__, e)
                traceback.print_exc()
    finally:
        net.client = _ORIG_CLIENT
    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    return 1 if _fail else 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(_SANDBOX, ignore_errors=True)
    sys.exit(code)
