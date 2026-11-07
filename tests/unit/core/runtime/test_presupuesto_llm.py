# -*- coding: utf-8 -*-
"""CONTADOR DIARIO DEL MODELO Y TECHO QUE FRENA LA NUBE — AI-07 / T19.

El hueco que se prueba aquí (auditoría del 30/07/2026, `05` AI-07 y `07` §5
«Costes y consumo»):

    nexus no contaba NADA. Ni llamadas, ni caracteres, ni tokens, ni por
    proveedor ni por día. Un bucle, un flujo de n8n que reenvía el mismo texto o
    una tarde de investigación pesada no tenían techo. El tope de salida
    (`llm.max_tokens_salida`, T6) acota UNA respuesta; aquí falta acotar el DÍA:
    «contador diario de llamadas y tokens por proveedor, con un límite
    configurable y un aviso al 80 %».

Lo que se comprueba, y por qué cada cosa:

  * una llamada = una entrada en el contador, en su clase (`chat`, `stream`,
    `distill`), con los caracteres del prompt y de la respuesta, y el doble de
    transporte confirma que la llamada ocurrió UNA vez;
  * el día es la CLAVE del archivo: lo de ayer no consume el presupuesto de hoy
    y no se mezcla (reloj movido a mano, nunca `sleep`);
  * si el proceso muere justo entre el `.tmp` y el `os.replace`, el contador
    anterior sigue entero y válido, no queda basura y el incremento no se pierde:
    el siguiente volcado lo incluye (misma técnica que
    `tests/unit/core/test_escrituras_atomicas.py`);
  * con un techo pequeño, la llamada N a la nube se RECHAZA con un mensaje en
    español que dice qué ha pasado, qué ha contado y cómo subirlo, y el doble de
    transporte confirma que NO se ha hecho la petición;
  * los locales (Ollama) NO están sujetos al techo por defecto (el riesgo es el
    dinero), y subir el umbral en el archivo desbloquea la nube otra vez;
  * `GET /api/status` publica los contadores de hoy y ni una clave;
  * los tokens reales se guardan donde el proveedor los devuelve de verdad
    (openai/anthropic/gemini/ollama) y en ningún sitio se estiman;
  * el tope de salida de T6 sigue leyéndose igual (no hay regresión);
  * sin `config/umbrales.json`, o con uno roto, se usan los valores documentados
    y no se rompe nada;
  * el disco se toca DESPUÉS del modelo y en OTRO hilo (`asyncio.to_thread`), que
    es lo que impide que el contador frene el ciclo de voz.

TODO EN PROCESO: `net.client()` doblado antes de la primera llamada (una prueba
no toca la red «casi siempre»: no la toca), configuración y datos en carpetas de
usar y tirar puestas ANTES de importar el backend, y ni una clave de verdad.

Ejecutar:  .venv\\Scripts\\python.exe tests/unit/core/runtime/test_presupuesto_llm.py
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                              # noqa: BLE001
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
_SANDBOX = Path(tempfile.mkdtemp(prefix="nexus_presupuesto_"))
_CFG = _SANDBOX / "config"
_DATA = _SANDBOX / "data"
_CFG.mkdir()
_DATA.mkdir()
(_CFG / "settings.json").write_text(json.dumps({
    "setup_done": True, "llm_provider": "ollama", "llm_local": True,
    "ollama_model": "qwen3:8b",
    "ollama_url": "http://127.0.0.1:9",        # puerto muerto: todo va doblado
    "permitir_fallback_nube": False,
    "cloud_base_url": "https://api.openai.com/v1",
    "retrain_model": "auto",
    "tts_engine": "off",
}), encoding="utf-8")
# Claves de mentira: `available()` de la nube solo mira que EXISTA una clave. Los
# valores no se parecen a ninguna clave real y no se imprimen nunca; la prueba
# comprueba además que NO salen por el estado ni por los avisos.
_CLAVES_FALSAS = ("doble-de-prueba-openai", "doble-de-prueba-anthropic",
                  "doble-de-prueba-gemini", "doble-de-prueba-cloud")
(_CFG / "secrets.json").write_text(json.dumps({
    "openai_api_key": _CLAVES_FALSAS[0],
    "anthropic_api_key": _CLAVES_FALSAS[1],
    "gemini_api_key": _CLAVES_FALSAS[2],
    "cloud_llm_api_key": _CLAVES_FALSAS[3],
}), encoding="utf-8")
os.environ["NEXUS_DATA_DIR"] = str(_DATA)
os.environ["NEXUS_CONFIG_DIR"] = str(_CFG)

import httpx  # noqa: E402

from backend.core.comun import atomicos, events, net, presupuesto  # noqa: E402
from backend.core.comun.config import CONFIG_DIR, DATA_DIR, settings  # noqa: E402
from backend.core.dominio import rag  # noqa: E402
from backend.core.infraestructura import llm  # noqa: E402
from backend.core.infraestructura import llm_runtime as rt  # noqa: E402

_HOY_REAL = presupuesto._hoy
_ORIG_CLIENT = net.client

import httpx as _httpx_modulo  # noqa: E402
_REAL_HTTPX_POST = _httpx_modulo.post      # el transporte real, para devolverlo


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
    """`net.client()` doblado. Responde con las formas REALES de cada proveedor,
    incluidos los bloques de uso (`usage`, `usageMetadata`, `*_eval_count`), para
    poder comprobar qué proveedores dan tokens de verdad y cuáles no.

    `ollama_uso`: campos de conteo que Ollama añade a la respuesta (su API real
    los manda; aquí se eligen para probar los dos casos)."""

    def __init__(self, ollama_vivo: bool = True, ollama_uso: dict | None = None):
        self.ollama_vivo = ollama_vivo
        self.ollama_uso = ollama_uso if ollama_uso is not None else {}
        self.llamadas: list[tuple[str, str, dict | None]] = []
        self.orden: list[str] = []

    async def get(self, url, **kw):
        self.llamadas.append(("GET", url, None))
        if self.ollama_vivo:
            return _Resp({"models": [{"name": "qwen3:8b", "size": 1}]})
        raise httpx.ConnectError("Ollama apagado (doble de prueba)")

    async def post(self, url, json=None, **kw):           # noqa: A002
        self.llamadas.append(("POST", url, json))
        self.orden.append("modelo")
        if "/api/chat" in url:
            return _Resp({"message": {"content": "OK-OLLAMA"}, **self.ollama_uso})
        if "/api/generate" in url:
            return _Resp({"response": "OK-OLLAMA", **self.ollama_uso})
        if "anthropic" in url:
            return _Resp({"content": [{"type": "text", "text": "OK-ANTHROPIC"}],
                          "usage": {"input_tokens": 21, "output_tokens": 9}})
        if "generativelanguage" in url:
            return _Resp({"candidates": [{"content": {"parts": [{"text": "OK-GEMINI"}]}}],
                          "usageMetadata": {"promptTokenCount": 31,
                                            "candidatesTokenCount": 6}})
        return _Resp({"choices": [{"message": {"content": "OK-OPENAI"}}],
                      "usage": {"prompt_tokens": 11, "completion_tokens": 7}})

    def stream(self, method, url, json=None, **kw):       # noqa: A002
        self.llamadas.append((method, url, json))
        self.orden.append("modelo")
        if "/api/chat" in url:
            return _Stream([json_dumps({"message": {"content": "trozo-ollama"},
                                        **self.ollama_uso})])
        if "generativelanguage" in url:
            fila = json_dumps({"candidates": [
                {"content": {"parts": [{"text": "trozo-gemini"}]},
                 "finishReason": "STOP"}]})
            return _Stream([f"data: {fila}"])
        return _Stream([f"data: {json_dumps({'choices': [{'delta': {'content': 'trozo-openai'}}]})}",
                        "data: [DONE]"])

    async def aclose(self):
        return None


def json_dumps(obj):
    return json.dumps(obj)


class _TransporteEmb:
    """`httpx.post` doblado: es el transporte REAL de `rag._emb_*` (síncrono).

    Se dobla el módulo, no `net.client()`, porque los embeddings no usan el
    cliente asíncrono: usan `httpx.post` a pelo desde un hilo de trabajo. Sin
    este doble, la prueba sacaría peticiones de verdad a Ollama y a OpenAI. El
    doble imita las formas reales, `usage.prompt_tokens` de OpenAI incluido.
    """

    def __init__(self):
        self.llamadas: list[tuple[str, dict | None, dict | None]] = []

    def post(self, url, json=None, params=None, headers=None, timeout=None, **kw):
        self.llamadas.append((url, json, params))
        if "/api/embeddings" in url:
            return _Resp({"embedding": [0.1, 0.2, 0.3]})
        if ":embedContent" in url:
            return _Resp({"embedding": {"values": [0.7, 0.8]}})
        return _Resp({"data": [{"embedding": [0.4, 0.5, 0.6]}],
                      "usage": {"prompt_tokens": 5, "total_tokens": 5}})

    def urls(self) -> list[str]:
        return [u for u, _j, _p in self.llamadas]


def _doblado_emb() -> _TransporteEmb:
    doble = _TransporteEmb()
    import httpx as _hx
    _hx.post = doble.post
    return doble


def _doblado(ollama_vivo: bool = True, ollama_uso: dict | None = None) -> _Cliente:
    cli = _Cliente(ollama_vivo, ollama_uso)
    net.client = lambda: cli
    return cli


def _reset(provider: str = "ollama") -> None:
    """Deja el contador, los umbrales y el proveedor como recién instalados."""
    rt._STATUS = rt.LLMRuntimeStatus()
    llm.invalidate_provider()
    settings.set("llm_provider", provider)
    settings.set("permitir_fallback_nube", False)
    llm.OllamaProvider._ruta = ""
    presupuesto._DOC = None
    presupuesto._ultimo_error = ""
    presupuesto._aviso_80_dia = ""
    presupuesto._hoy = _HOY_REAL
    for ruta in (presupuesto.ruta_archivo(), Path(CONFIG_DIR) / "umbrales.json"):
        try:
            ruta.unlink()
        except OSError:
            pass


def _umbrales(seccion_llm: dict) -> None:
    """Escribe el techo en la configuración DESECHABLE de esta prueba."""
    (Path(CONFIG_DIR) / "umbrales.json").write_text(
        json.dumps({"llm": seccion_llm}, ensure_ascii=False), encoding="utf-8")


def run(coro):
    return asyncio.run(coro)


def _disco() -> dict:
    return json.loads(presupuesto.ruta_archivo().read_text(encoding="utf-8"))


def _stream(pregunta: str):
    """Consume el streaming como lo haría la voz y devuelve (trozos, proveedor)."""
    async def _corre():
        gen, prov = await llm.ask_llm_stream(pregunta)
        try:
            return [t async for t in gen], prov
        finally:
            await gen.aclose()
    return run(_corre())


# ══════════════════════════════════════════════════════════════════════════════
#  1. UNA LLAMADA = UNA ENTRADA, EN SU CLASE Y CON SUS CARACTERES
# ══════════════════════════════════════════════════════════════════════════════
def test_cuenta_por_proveedor_y_clase():
    print("· cada llamada cuenta una vez, en su clase y con sus caracteres")
    _reset()
    cli = _doblado()

    respuesta, proveedor = run(llm.ask_llm("hola"))
    check(proveedor == "ollama" and respuesta == "OK-OLLAMA",
          f"la llamada responde de verdad ({proveedor!r} → {respuesta!r})")
    posts = [c for c in cli.llamadas if c[0] == "POST"]
    check(len(posts) == 1, f"el doble ha recibido UNA petición ({len(posts)})")

    resumen = presupuesto.resumen()
    chat = resumen["por_proveedor"]["ollama"]["clases"]["chat"]
    check(chat["llamadas"] == 1, f"y el contador dice UNA llamada ({chat})")
    check(chat["caracteres_salida"] == len("OK-OLLAMA"),
          f"con los caracteres de la respuesta ({chat.get('caracteres_salida')})")
    check(chat["caracteres_entrada"] > 1000,
          f"y los del prompt ENTERO, no solo el texto del usuario "
          f"({chat.get('caracteres_entrada')})")
    check(resumen["por_proveedor"]["ollama"]["local"] is True,
          "y queda anotado que ese proveedor es local")

    disco = _disco()
    check(presupuesto._hoy() in disco["dias"],
          f"el día es la CLAVE del archivo ({list(disco['dias'])})")
    check(disco["dias"][presupuesto._hoy()]["ollama"]["clases"]["chat"]["llamadas"] == 1,
          "y en disco está lo mismo que en memoria (no se pierde al volcar)")

    print("· el streaming se cuenta aparte del chat")
    trozos, prov2 = _stream("¿qué tal?")
    check(trozos == ["trozo-ollama"], f"el streaming sigue funcionando ({trozos})")
    check(prov2 == "ollama", f"y se atribuye al proveedor ({prov2!r})")
    resumen = presupuesto.resumen()
    clases = resumen["por_proveedor"]["ollama"]["clases"]
    check(clases["stream"]["llamadas"] == 1,
          f"una llamada de streaming contada ({clases.get('stream')})")
    check(clases["stream"]["caracteres_salida"] == len("trozo-ollama"),
          f"con los caracteres que de verdad se cedieron "
          f"({clases['stream'].get('caracteres_salida')})")
    check(clases["chat"]["llamadas"] == 1,
          f"y el stream NO se suma al chat ({clases['chat']['llamadas']})")

    print("· el destilado del perfil se cuenta como destilado")
    salida = run(llm.distill("SISTEMA", "USUARIO"))
    check(salida == "OK-OLLAMA", f"el destilado devuelve texto ({salida!r})")
    clases = presupuesto.resumen()["por_proveedor"]["ollama"]["clases"]
    check(clases["distill"]["llamadas"] == 1,
          f"una llamada de destilado contada ({clases.get('distill')})")
    check(clases["distill"]["caracteres_entrada"] == len("SISTEMA") + len("USUARIO"),
          f"con sus caracteres ({clases['distill'].get('caracteres_entrada')})")
    check(clases["chat"]["llamadas"] == 1,
          "y tampoco se suma al chat: cada clase dice lo suyo")
    posts = [c for c in cli.llamadas if c[0] == "POST"]
    check(len(posts) == 3, f"tres llamadas al modelo, tres peticiones ({len(posts)})")


# ══════════════════════════════════════════════════════════════════════════════
#  2. EL DÍA ES LA CLAVE: LO DE AYER NO GASTA EL PRESUPUESTO DE HOY
# ══════════════════════════════════════════════════════════════════════════════
def test_cambio_de_dia_no_mezcla_contadores():
    print("· reloj movido a mano (sin dormir): cada día su contador")
    _reset("openai")
    _umbrales({"presupuesto_diario_llamadas": 1})
    cli = _doblado()

    presupuesto._hoy = lambda: "2030-01-01"
    texto, prov = run(llm.ask_llm("uno"))
    check(prov == "openai", f"el primer día, la primera llamada pasa ({prov!r})")
    texto, prov = run(llm.ask_llm("dos"))
    check(prov == "ninguno", "y con techo de 1, la segunda del día se rechaza")
    check(len([c for c in cli.llamadas if c[0] == "POST"]) == 1,
          "sin hacer la segunda petición")

    presupuesto._hoy = lambda: "2030-01-02"
    texto, prov = run(llm.ask_llm("tres"))
    check(prov == "openai",
          f"al día siguiente el contador arranca de cero: lo de ayer no consume "
          f"el presupuesto de hoy ({prov!r})")
    resumen = presupuesto.resumen()
    check(resumen["dia"] == "2030-01-02", f"y el resumen es del día de hoy ({resumen['dia']})")
    check(resumen["llamadas"] == 1, f"con las llamadas de hoy ({resumen['llamadas']})")

    disco = _disco()
    check("2030-01-01" in disco["dias"] and "2030-01-02" in disco["dias"],
          f"el archivo guarda un día por clave ({list(disco['dias'])})")
    check(disco["dias"]["2030-01-01"]["openai"]["clases"]["chat"]["llamadas"] == 1,
          "y lo de ayer sigue intacto, no se reescribe con lo de hoy")
    check(disco["dias"]["2030-01-02"]["openai"]["clases"]["chat"]["llamadas"] == 1,
          "ni lo de hoy arrastra lo de ayer")
    presupuesto._hoy = _HOY_REAL
    check(list(json.loads(presupuesto.ruta_archivo().read_text(encoding="utf-8"))
               ["dias"]) != [], "el archivo sigue siendo JSON válido")


# ══════════════════════════════════════════════════════════════════════════════
#  3. CAÍDA A MITAD DE ESCRITURA: EL CONTADOR ANTERIOR SOBREVIVE
# ══════════════════════════════════════════════════════════════════════════════
def test_caida_a_mitad_de_escritura():
    print("· corte entre el .tmp y el os.replace (técnica de test_escrituras_atomicas)")
    _reset()
    _doblado()
    run(llm.ask_llm("primera"))
    antes = presupuesto.ruta_archivo().read_text(encoding="utf-8")
    json.loads(antes)                                   # era (y sigue siendo) válido

    real_replace = os.replace
    vistos: list[Path] = []

    def _revienta(src, dst):
        vistos.append(Path(src))
        raise OSError("corte simulado entre el .tmp y el reemplazo")

    os.replace = _revienta
    try:
        ok = run(presupuesto.anotar("ollama", "chat", caracteres_entrada=100,
                                    caracteres_salida=10, local=True))
        check(ok is False, "el volcado informa del fallo en vez de mentir")
        check(bool(vistos) and vistos[0].name.endswith(".tmp"),
              f"el .tmp llegó a existir antes del corte ({vistos})")
        check(not vistos[0].exists(), "y NO queda basura .tmp al lado")
        check(not list(Path(DATA_DIR).glob("*.tmp")), "ni ningún otro temporal")
        despues = presupuesto.ruta_archivo().read_text(encoding="utf-8")
        check(despues == antes,
              "el contador ANTERIOR sigue entero y byte a byte igual")
        json.loads(despues)
        check(presupuesto.resumen()["error_guardado"] != "",
              "y el fallo se puede ver en el resumen (no se calla)")
    finally:
        os.replace = real_replace

    print("· y el incremento no se pierde: el siguiente volcado lo incluye")
    run(presupuesto.anotar("ollama", "chat", caracteres_entrada=1,
                           caracteres_salida=1, local=True))
    total = presupuesto.resumen()["por_proveedor"]["ollama"]["clases"]["chat"]["llamadas"]
    check(total == 3, f"1 que estaba en disco + 1 que falló + 1 nueva = 3 ({total})")
    check(presupuesto.resumen()["error_guardado"] == "",
          "y al volcar bien, el error se limpia")


# ══════════════════════════════════════════════════════════════════════════════
#  4. EL TECHO FRENA LA NUBE, LO DICE Y AVISA AL 80 %
# ══════════════════════════════════════════════════════════════════════════════
def test_techo_frena_la_nube_y_avisa():
    print("· con el techo alcanzado no hay petición, y el mensaje es honesto")
    _reset("openai")
    _umbrales({"presupuesto_diario_llamadas": 2})
    cli = _doblado()
    avisos: list[tuple[str, str]] = []
    real_log = events.log

    async def _espia(msg, level="info"):
        avisos.append((level, msg))

    events.log = _espia
    try:
        for i in range(2):
            texto, prov = run(llm.ask_llm(f"pregunta {i}"))
            check(prov == "openai", f"la llamada {i + 1} pasa ({prov!r})")
        texto, prov = run(llm.ask_llm("la tercera"))
    finally:
        events.log = real_log

    check(prov == "ninguno",
          f"la tercera NO se atribuye a ningún modelo: no se finge una respuesta ({prov!r})")
    check("presupuesto" in texto.lower(),
          f"el mensaje dice que se ha acabado el presupuesto ({texto!r})")
    check("2 llamadas" in texto,
          f"y qué ha contado: las llamadas ({texto!r})")
    check("caracteres" in texto, "y los caracteres")
    check("presupuesto_diario_llamadas" in texto,
          "y el ajuste EXACTO que hay que subir")
    check("⚙" in texto, "y dónde se sube")
    check("Ollama" in texto,
          "diciendo que los locales siguen: el techo es el dinero, no el uso")
    posts = [c for c in cli.llamadas if c[0] == "POST"]
    check(len(posts) == 2,
          f"el doble de transporte NO ha recibido la tercera petición ({len(posts)})")
    contadores = presupuesto.resumen()
    check(contadores["por_proveedor"]["openai"]["clases"]["chat"]["llamadas"] == 2,
          "el rechazo no infla el contador")
    check(contadores["agotado"] is True, "y el resumen lo dice: agotado")

    textos = " ".join(m for _lv, m in avisos)
    check(any("80 %" in m for m in (m for _lv, m in avisos)),
          f"al 80 % avisó ANTES de llegar al techo ({avisos})")
    check(any("presupuesto" in m.lower() or "tope" in m.lower() for m in (m for _lv, m in avisos)),
          "y el rechazo queda en el bus (observable), no solo en la respuesta")
    check(any(lv in ("warning", "warn") for lv, _m in avisos),
          f"como aviso, no como mensaje informativo ({avisos})")
    check(all(clave not in textos for clave in _CLAVES_FALSAS),
          "sin una sola clave en los avisos")
    check(all(clave not in texto for clave in _CLAVES_FALSAS),
          "ni en el mensaje del chat")

    print("· con el techo alcanzado, el modelo LOCAL sigue funcionando")
    settings.set("llm_provider", "ollama")
    llm.invalidate_provider()
    texto2, prov2 = run(llm.ask_llm("hola"))
    check(prov2 == "ollama" and texto2 == "OK-OLLAMA",
          f"Ollama no está limitado por el techo de la nube ({prov2!r} → {texto2!r})")


# ══════════════════════════════════════════════════════════════════════════════
#  5. EL TECHO DE CARACTERES, Y SUBIR EL UMBRAL DESBLOQUEA
# ══════════════════════════════════════════════════════════════════════════════
def test_techo_de_caracteres_y_desbloqueo():
    print("· el otro techo: caracteres")
    _reset("openai")
    _umbrales({"presupuesto_diario_llamadas": 1000,
               "presupuesto_diario_caracteres": 500})
    cli = _doblado()
    texto, prov = run(llm.ask_llm("x" * 50))
    check(prov == "ninguno",
          "un prompt más largo que el techo de caracteres no se manda")
    check("caracteres" in texto, f"y el mensaje lo dice con su unidad ({texto!r})")
    check(cli.llamadas == [], f"sin hacer NI UNA petición ({cli.llamadas})")

    print("· subiendo el umbral en el archivo, la misma llamada pasa")
    _umbrales({"presupuesto_diario_llamadas": 1000,
               "presupuesto_diario_caracteres": 100_000})
    texto, prov = run(llm.ask_llm("x" * 50))
    check(prov == "openai", f"ahora sí responde ({prov!r})")
    check(len([c for c in cli.llamadas if c[0] == "POST"]) == 1,
          "y ha hecho exactamente una petición")


# ══════════════════════════════════════════════════════════════════════════════
#  6. TOKENS REALES DONDE LOS HAY; NI UNO ESTIMADO DONDE NO
# ══════════════════════════════════════════════════════════════════════════════
def test_tokens_reales_solo_donde_el_proveedor_los_da():
    print("· openai/anthropic/gemini devuelven uso y se guarda")
    _reset("openai")
    _doblado()
    run(llm.ask_llm("hola"))
    resumen = presupuesto.resumen()
    chat = resumen["por_proveedor"]["openai"]["clases"]["chat"]
    check((chat.get("tokens_entrada"), chat.get("tokens_salida")) == (11, 7),
          f"openai: 11 de entrada y 7 de salida, tal cual ({chat})")
    check("openai" in resumen["tokens_reales"],
          f"y el resumen lo reconoce ({resumen['tokens_reales']})")

    for nombre, esperado in (("anthropic", (21, 9)), ("gemini", (31, 6))):
        settings.set("llm_provider", nombre)
        llm.invalidate_provider()
        texto, prov = run(llm.ask_llm("hola"))
        check(prov == nombre, f"{nombre} responde ({prov!r} → {texto!r})")
        chat = presupuesto.resumen()["por_proveedor"][nombre]["clases"]["chat"]
        check((chat.get("tokens_entrada"), chat.get("tokens_salida")) == esperado,
              f"{nombre}: tokens reales guardados ({chat})")

    print("· Ollama sin contadores en la respuesta: caracteres y NADA inventado")
    settings.set("llm_provider", "ollama")
    llm.invalidate_provider()
    _doblado()                                    # respuesta sin *_eval_count
    run(llm.ask_llm("hola"))
    resumen = presupuesto.resumen()
    chat = resumen["por_proveedor"]["ollama"]["clases"]["chat"]
    check("tokens_entrada" not in chat and "tokens_salida" not in chat,
          f"sin números del proveedor no se escriben tokens ({chat})")
    check("ollama" not in resumen["tokens_reales"],
          "y no se apunta como proveedor con tokens reales")
    check(chat["caracteres_entrada"] > 0 and chat["caracteres_salida"] > 0,
          "pero los caracteres sí están: son la unidad que siempre se puede medir")

    print("· y cuando Ollama SÍ los manda, se guardan")
    settings.set("llm_provider", "ollama")
    llm.invalidate_provider()
    _doblado(ollama_uso={"prompt_eval_count": 5, "eval_count": 3})
    run(llm.ask_llm("hola"))
    chat = presupuesto.resumen()["por_proveedor"]["ollama"]["clases"]["chat"]
    check((chat.get("tokens_entrada"), chat.get("tokens_salida")) == (5, 3),
          f"los campos prompt_eval_count/eval_count de Ollama ({chat})")


# ══════════════════════════════════════════════════════════════════════════════
#  7. GET /api/status PUBLICA LOS CONTADORES DE HOY (Y NINGUNA CLAVE)
# ══════════════════════════════════════════════════════════════════════════════
def test_api_status_publica_los_contadores():
    print("· el HUD ya lee /api/status: ahí están los números del día")
    _reset("openai")
    _doblado()
    run(llm.ask_llm("hola"))
    import backend.app as servidor

    async def _pide():
        # ASGI en proceso y peer de loopback: no arranca uvicorn ni ejecuta lifespan.
        transporte = httpx.ASGITransport(app=servidor.app, client=("127.0.0.1", 4321))
        async with httpx.AsyncClient(transport=transporte,
                                     base_url="http://127.0.0.1:8177") as cliente:
            return await cliente.get("/api/status", headers={"host": "127.0.0.1:8177"})

    respuesta = run(_pide())
    check(respuesta.status_code == 200,
          f"/api/status contesta bien ({respuesta.status_code})")
    cuerpo = respuesta.json()
    check("presupuesto" in cuerpo, "y trae el presupuesto del día")
    datos = cuerpo["presupuesto"]
    check(datos["dia"] == presupuesto._hoy(), f"del día de hoy ({datos.get('dia')})")
    chat = datos["por_proveedor"]["openai"]["clases"]["chat"]
    check(chat["llamadas"] == 1, f"con la llamada que se hizo ({chat})")
    check(datos["limites"]["llamadas"] == presupuesto.UMBRALES_RESERVA[
        "presupuesto_diario_llamadas"],
        f"y el techo puesto ({datos.get('limites')})")
    check("secretos_ilegibles" in cuerpo, "sin quitarse lo que ya publicaba (T13)")
    texto = respuesta.text
    for clave in _CLAVES_FALSAS:
        check(clave not in texto, f"ninguna clave en el estado ({clave})")
    check("doble-de-prueba" not in texto, "ni rastro de las claves de prueba")


# ══════════════════════════════════════════════════════════════════════════════
#  8. SIN UMBRALES (O ROTOS): LOS VALORES DOCUMENTADOS, SIN ROMPER NADA
# ══════════════════════════════════════════════════════════════════════════════
def test_sin_umbrales_se_usan_los_valores_documentados():
    print("· umbrales.json ausente o roto → reserva del código, y no revienta")
    _reset()
    check(presupuesto.limites() == presupuesto.UMBRALES_RESERVA,
          f"sin archivo se usan los valores de reserva ({presupuesto.limites()})")

    ruta = Path(CONFIG_DIR) / "umbrales.json"
    ruta.write_text("{esto no es json,,,", encoding="utf-8")
    check(presupuesto.limites() == presupuesto.UMBRALES_RESERVA,
          "con un archivo roto, los mismos")
    ruta.write_text(json.dumps({"llm": {"presupuesto_diario_llamadas": 0,
                                        "presupuesto_diario_caracteres": -5,
                                        "presupuesto_incluye_locales": "sí"}}),
                    encoding="utf-8")
    check(presupuesto.limites() == presupuesto.UMBRALES_RESERVA,
          f"un 0 (o un negativo) NO corta todas las llamadas: se queda la reserva "
          f"({presupuesto.limites()})")
    check(run(presupuesto.anotar("ollama", "chat", caracteres_entrada=1, local=True)) is True,
          "y el contador sigue funcionando con el archivo roto")

    print("· el archivo que se entrega dice lo MISMO que el código")
    fabrica = json.loads((ROOT / "config" / "umbrales.json").read_text(encoding="utf-8"))["llm"]
    for clave, valor in presupuesto.UMBRALES_RESERVA.items():
        check(fabrica.get(clave) == valor,
              f"«{clave}» se entrega con el valor de reserva "
              f"({fabrica.get(clave)} vs {valor})")
        check(bool(fabrica.get("_" + clave)),
              f"y está explicado dentro del archivo («_{clave}»)")


# ══════════════════════════════════════════════════════════════════════════════
#  9. EL TOPE DE SALIDA DE T6 NO CAMBIA (no hay regresión)
# ══════════════════════════════════════════════════════════════════════════════
def test_el_tope_de_salida_sigue_igual():
    print("· sección «llm» ampliada: el tope de 4096 se sigue leyendo")
    _reset()
    check(llm._cap_salida() == 4096,
          f"con la sección nueva y sin max_tokens_salida, la reserva es 4096 "
          f"({llm._cap_salida()})")
    _umbrales({"max_tokens_salida": 1234, "presupuesto_diario_llamadas": 7})
    check(llm._cap_salida() == 1234,
          f"y sigue saliendo del archivo ({llm._cap_salida()})")


# ══════════════════════════════════════════════════════════════════════════════
# 10. EL DISCO SE TOCA DESPUÉS DEL MODELO Y EN OTRO HILO
# ══════════════════════════════════════════════════════════════════════════════
def test_el_disco_se_toca_despues_y_en_otro_hilo():
    print("· el volcado no puede frenar el ciclo de voz: después y fuera del bucle")
    _reset()
    cli = _doblado()
    orden: list[str] = []
    hilos: list[str] = []
    real_escribir = presupuesto.escribir_json_atomico

    def _espia(path, data, **kw):
        orden.append("disco")
        hilos.append(threading.current_thread().name)
        return real_escribir(path, data, **kw)

    presupuesto.escribir_json_atomico = _espia
    try:
        run(llm.ask_llm("hola"))
    finally:
        presupuesto.escribir_json_atomico = real_escribir

    check(cli.orden[:1] == ["modelo"] and orden == ["disco"],
          f"primero la llamada al modelo y después el contador ({cli.orden} / {orden})")
    check(bool(hilos) and hilos[0] != threading.current_thread().name,
          f"y el volcado corre en OTRO hilo (asyncio.to_thread): {hilos} "
          f"frente a {threading.current_thread().name}")


# ══════════════════════════════════════════════════════════════════════════════
# 11. UN CONTADOR ROTO NO DEJA A NEXUS SIN HABLAR
# ══════════════════════════════════════════════════════════════════════════════
def test_un_contador_roto_no_rompe_el_chat():
    print("· si el contador falla, la respuesta sale igual")
    _reset()
    _doblado()
    real_anotar = presupuesto.anotar

    async def _revienta(*a, **k):
        raise RuntimeError("contador roto a propósito")

    presupuesto.anotar = _revienta
    try:
        texto, prov = run(llm.ask_llm("hola"))
    finally:
        presupuesto.anotar = real_anotar
    check(prov == "ollama" and texto == "OK-OLLAMA",
          f"la conversación no se rompe por el contador ({prov!r} → {texto!r})")


# ══════════════════════════════════════════════════════════════════════════════
# 12. LA CLASE «embed» EXISTE EN EL CONTADOR
# ══════════════════════════════════════════════════════════════════════════════
def test_la_clase_embed_esta_en_el_contador():
    print("· la cuarta clase del contador: embeddings")
    _reset()
    ok = run(presupuesto.anotar("ollama", "embed", caracteres_entrada=120,
                                caracteres_salida=0, local=True))
    check(ok is True, "una llamada de embedding se apunta")
    datos = presupuesto.resumen()["por_proveedor"]["ollama"]["clases"]["embed"]
    check(datos["llamadas"] == 1, f"como una llamada ({datos})")
    check(datos["caracteres_entrada"] == 120, f"con sus caracteres ({datos})")
    check("embed" in presupuesto.CLASES, "y la clase está declarada en el módulo")


# ══════════════════════════════════════════════════════════════════════════════
# 13. LOS EMBEDDINGS TAMBIÉN SE CUENTAN (y su techo es el de la nube)
# ══════════════════════════════════════════════════════════════════════════════
def test_los_embeddings_se_cuentan():
    print("· un embedding es una llamada al modelo: se cuenta, con su proveedor")
    _reset()
    doble = _doblado_emb()
    import httpx as _hx
    try:
        vector = rag._embed_sync("hola mundo")          # auto → Ollama local
        check(vector == [0.1, 0.2, 0.3], f"el embedding local se devuelve ({vector})")
        check(doble.urls() == ["http://127.0.0.1:9/api/embeddings"],
              f"y ha salido UNA petición, al Ollama doblado ({doble.urls()})")
        embed = presupuesto.resumen()["por_proveedor"]["ollama"]["clases"]["embed"]
        check(embed["llamadas"] == 1, f"contado como UNA llamada de embed ({embed})")
        check(embed["caracteres_entrada"] == len("hola mundo"),
              f"con los caracteres del texto vectorizado ({embed})")
        check("tokens_entrada" not in embed,
              f"y sin tokens: Ollama no los da y no se inventan ({embed})")
        check(presupuesto.resumen()["por_proveedor"]["ollama"]["local"] is True,
              "marcado como local (no consume el techo de la nube)")

        print("· el de OpenAI cuenta con tokens REALES y el de Gemini también cuenta")
        rag._embed_sync("otro texto", proveedor="openai")
        embed = presupuesto.resumen()["por_proveedor"]["openai"]["clases"]["embed"]
        check(embed["llamadas"] == 1, f"embed de openai contado ({embed})")
        check(embed["caracteres_entrada"] == len("otro texto"),
              f"con sus caracteres ({embed})")
        check(embed.get("tokens_entrada") == 5,
              f"y los tokens que manda `usage.prompt_tokens` ({embed})")
        rag._embed_sync("tercero", proveedor="gemini")
        embed = presupuesto.resumen()["por_proveedor"]["gemini"]["clases"]["embed"]
        check(embed["llamadas"] == 1, f"embed de gemini contado ({embed})")
        check("tokens_entrada" not in embed,
              f"y sin tokens: su respuesta no trae uso ({embed})")
        urls = " ".join(doble.urls())
        check("api.openai.com" in urls and "embedContent" in urls,
              f"los tres transportes son los de verdad ({doble.urls()})")
    finally:
        _hx.post = _REAL_HTTPX_POST


def test_el_techo_frena_los_embeddings_de_nube():
    print("· con el techo agotado, un embedding de nube no sale; uno local sí")
    _reset("openai")
    _umbrales({"presupuesto_diario_llamadas": 1000,
               "presupuesto_diario_caracteres": 10})
    doble = _doblado_emb()
    import httpx as _hx
    avisos: list[tuple[str, dict]] = []
    real_emit = events.bus.emit_sync

    def _espia(tipo, datos=None):
        avisos.append((tipo, datos or {}))

    events.bus.emit_sync = _espia
    try:
        texto = "un texto bastante más largo que diez caracteres"
        vector = rag._embed_sync(texto, proveedor="openai")
        check(vector is None,
              f"un embedding de nube pasado el techo no se hace ({vector})")
        check(doble.urls() == [],
              f"y NO sale ni una petición a la nube ({doble.urls()})")
        embed = presupuesto.resumen()["por_proveedor"].get("openai", {}).get("clases", {})
        check("embed" not in embed,
              f"ni se apunta una llamada que no ha ocurrido ({embed})")
        mensajes = " ".join(str(d.get("msg", "")) for _t, d in avisos)
        check("vectorización" in mensajes,
              f"el aviso dice que se ha parado la vectorización ({avisos})")
        check("embeddings" in mensajes and "presupuesto" in mensajes.lower(),
              f"nombra los embeddings y el presupuesto ({mensajes!r})")
        check("presupuesto_diario_caracteres" in mensajes,
              "y cómo subirlo")
        check(any(d.get("level") in ("warning", "warn") for _t, d in avisos),
              f"como aviso en el bus, no como mensaje informativo ({avisos})")
        check(all(clave not in mensajes for clave in _CLAVES_FALSAS),
              "sin una sola clave en el aviso")

        print("· el embedding LOCAL no está sujeto al techo por defecto")
        vector = rag._embed_sync(texto)                  # auto → Ollama
        check(vector == [0.1, 0.2, 0.3],
              f"Ollama vectoriza igual con el presupuesto de la nube agotado ({vector})")
        embed = presupuesto.resumen()["por_proveedor"]["ollama"]["clases"]["embed"]
        check(embed["llamadas"] == 1, f"y queda contado como local ({embed})")

        print("· subiendo el techo, el embedding de nube vuelve")
        _umbrales({"presupuesto_diario_llamadas": 1000,
                   "presupuesto_diario_caracteres": 100_000})
        vector = rag._embed_sync(texto, proveedor="openai")
        check(vector == [0.4, 0.5, 0.6], f"ahora sí se vectoriza en la nube ({vector})")
        check(len([u for u in doble.urls() if "openai" in u]) == 1,
              f"con UNA petición ({doble.urls()})")
        embed = presupuesto.resumen()["por_proveedor"]["openai"]["clases"]["embed"]
        check(embed["llamadas"] == 1, f"y contada ({embed})")
    finally:
        events.bus.emit_sync = real_emit
        _hx.post = _REAL_HTTPX_POST


def main() -> int:
    # RED PROHIBIDA: si una prueba se olvida de instalar su doble, esto revienta
    # en vez de sacar una petición de verdad a internet.
    def _prohibido():
        raise RuntimeError("esta prueba no ha instalado su doble de red")

    net.client = _prohibido
    try:
        for f in (test_cuenta_por_proveedor_y_clase,
                  test_cambio_de_dia_no_mezcla_contadores,
                  test_caida_a_mitad_de_escritura,
                  test_techo_frena_la_nube_y_avisa,
                  test_techo_de_caracteres_y_desbloqueo,
                  test_tokens_reales_solo_donde_el_proveedor_los_da,
                  test_api_status_publica_los_contadores,
                  test_sin_umbrales_se_usan_los_valores_documentados,
                  test_el_tope_de_salida_sigue_igual,
                  test_el_disco_se_toca_despues_y_en_otro_hilo,
                  test_un_contador_roto_no_rompe_el_chat,
                  test_la_clase_embed_esta_en_el_contador,
                  test_los_embeddings_se_cuentan,
                  test_el_techo_frena_los_embeddings_de_nube):
            try:
                f()
            except Exception as e:                             # noqa: BLE001
                import traceback
                _fail.append(f"EXCEPCIÓN en {f.__name__}: {type(e).__name__}: {e}")
                print("  EXCEPCIÓN en", f.__name__, ":", type(e).__name__, e)
                traceback.print_exc()
    finally:
        net.client = _ORIG_CLIENT
    print(f"\n{'=' * 50}\n{_pass} pasados, {len(_fail)} fallados")
    return 1 if _fail else 0


if __name__ == "__main__":
    try:
        codigo = main()
    finally:
        shutil.rmtree(_SANDBOX, ignore_errors=True)
    sys.exit(codigo)
