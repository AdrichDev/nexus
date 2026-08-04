# -*- coding: utf-8 -*-
"""RUNTIME DE MODELOS — que «EN USO» signifique que FUNCIONA.

El fallo que se prueba aquí (reportado por Adri el 25/07/2026):

    ⚙ decía  →  «✓ Cerebro activo: qwen3:8b (local)»
    el chat  →  «el modelo qwen3:8b no está en Ollama»

Dos mensajes contradictorios porque la DETECCIÓN VISUAL (carpetas del disco +
preferencia guardada) y el RUNTIME REAL (quien de verdad habla con el modelo)
eran cosas distintas que nunca se consultaban entre sí.

Estas pruebas levantan un OLLAMA DE MENTIRA (un servidor HTTP local, de verdad,
con las mismas rutas y los mismos errores que el real) y comprueban el
comportamiento en los casos que le pasaron a Adri:

  * Ollama apagado             → no se activa nada y se dice qué hacer
  * el modelo no está servido  → se dice cuál sí, y NO se toca la configuración
  * la etiqueta no coincide    → «tienes qwen3:8b», no «no lo tienes»
  * un modelo de embeddings    → se rechaza ANTES de intentarlo
  * Ollama antiguo (sin /chat) → se reintenta por la vía antigua y funciona
  * respuesta vacía            → NO cuenta como activo
  * todo bien                  → activo, probado, con su tiempo de respuesta

Y además: que ningún mensaje de estos se le escape al usuario con jerga interna,
y que NINGUNO se pierda al pasar por el filtro de voz pública.

Ejecutar:  python tests/test_llm_runtime.py    (desde la carpeta nexus)
"""
import asyncio
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Caja de arena: ni la configuración ni los datos reales de Adri se tocan.
_SANDBOX = Path(tempfile.mkdtemp(prefix="nexus_rt_"))
(_SANDBOX / "data").mkdir()
(_SANDBOX / "config").mkdir()
(_SANDBOX / "config" / "settings.json").write_text(json.dumps({
    "setup_done": True, "llm_provider": "ollama", "llm_local": True,
    "ollama_model": "qwen3:8b", "tts_enabled": False, "engram_enabled": False,
}), encoding="utf-8")
os.environ["NEXUS_DATA_DIR"] = str(_SANDBOX / "data")
os.environ["NEXUS_CONFIG_DIR"] = str(_SANDBOX / "config")

from backend.core.infraestructura import llm as _llm  # noqa: E402
from backend.core.infraestructura import llm_runtime as rt  # noqa: E402
from _frontend_js import js_hud  # el HUD entero, no solo command.js
from backend.core.comun import publicvoice as pv  # noqa: E402
from backend.core.comun.config import settings                  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════════
#  OLLAMA DE MENTIRA (servidor HTTP real, respuestas reales)
# ══════════════════════════════════════════════════════════════════════════════
class _FakeOllama:
    """Habla como Ollama: /api/tags, /api/chat y /api/generate.

    `modo` decide qué le pasa hoy:
      ok           → todo correcto
      ruta_vieja   → /api/chat responde 404 «page not found» (Ollama antiguo)
      modelo_404   → 404 diciendo que el modelo no existe
      vacio        → contesta, pero sin contenido
      lento        → tarda más que el tiempo de espera
      memoria      → 500 «model requires more system memory»
    """

    def __init__(self, modelos, modo="ok"):
        self.modelos = modelos
        self.modo = modo
        self.recibido = []
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self.port = s.getsockname()[1]
        s.close()
        srv_self = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, obj):
                cuerpo = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)

            def do_GET(self):
                if self.path.startswith("/api/tags"):
                    self._json(200, {"models": [
                        {"name": n, "size": 4_700_000_000} for n in srv_self.modelos]})
                else:
                    self._json(404, {"error": "404 page not found"})

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                cuerpo = json.loads(self.rfile.read(n) or b"{}")
                srv_self.recibido.append((self.path, cuerpo))
                modo = srv_self.modo
                if modo == "lento":
                    time.sleep(3)
                if modo == "memoria":
                    self._json(500, {"error": "model requires more system memory "
                                              "(9.0 GiB) than is available (4.1 GiB)"})
                    return
                if modo == "modelo_404":
                    self._json(404, {"error": f"model '{cuerpo.get('model')}' not found, "
                                              f"try pulling it first"})
                    return
                if self.path.startswith("/api/chat"):
                    if modo == "ruta_vieja":
                        self._json(404, {"error": "404 page not found"})
                        return
                    self._json(200, {"message": {"content": "" if modo == "vacio" else "OK"}})
                    return
                if self.path.startswith("/api/generate"):
                    self._json(200, {"response": "" if modo == "vacio" else "OK"})
                    return
                self._json(404, {"error": "404 page not found"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), H)
        self.hilo = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.hilo.start()
        settings.set("ollama_url", f"http://127.0.0.1:{self.port}")
        rt.OllamaClient.ruta = ""          # cada escenario aprende su ruta de cero
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()


def _puerto_muerto() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _reset_estado():
    rt._STATUS = rt.LLMRuntimeStatus()
    _llm.invalidate_provider()


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ══════════════════════════════════════════════════════════════════════════════
#  1. CLASIFICACIÓN: un modelo de embeddings no es un cerebro
# ══════════════════════════════════════════════════════════════════════════════
def test_clasificacion():
    print("· clasificación de modelos (chat vs embeddings)")
    embeddings = ["bge-m3", "bge-m3:latest", "nomic-embed-text",
                  "nomic-embed-text:v1.5", "mxbai-embed-large:335m",
                  "all-minilm", "snowflake-arctic-embed:l"]
    for m in embeddings:
        check(rt.classify_model(m) == "embedding", f"«{m}» se reconoce como embeddings")
        check(not rt.sirve_de_cerebro(m), f"«{m}» no se ofrece como cerebro")
    cerebros = ["qwen3:8b", "llama3.1", "llama3.1:70b", "gemma3:12b",
                "deepseek-r1:14b", "sorc/qwen3.5-claude-4.6-opus-q4",
                "mistral-small:latest", "phi4", "gpt-oss:20b"]
    for m in cerebros:
        check(rt.classify_model(m) == "chat", f"«{m}» se reconoce como modelo de conversación")
        check(rt.sirve_de_cerebro(m), f"«{m}» sí se puede usar de cerebro")
    # el HUD ya NO clasifica por su cuenta: lo hace esta función y punto
    js = js_hud()
    check("nomic-embed" not in js,
          "la interfaz ya no tiene su propio regex de embeddings (lo dice el backend)")


# ══════════════════════════════════════════════════════════════════════════════
#  2. EL CASO DE ADRI: activar un modelo que SÍ está
# ══════════════════════════════════════════════════════════════════════════════
def test_activacion_correcta():
    print("· activar un modelo que funciona")
    _reset_estado()
    with _FakeOllama(["qwen3:8b", "bge-m3"], "ok") as fake:
        st = run(rt.activate_ollama_model("qwen3:8b"))
        check(st.active and st.verified,
              f"«qwen3:8b» queda ACTIVO tras contestar (activo={st.active}, "
              f"probado={st.verified}, error={st.error_public!r})")
        check(st.model == "qwen3:8b", "el estado guarda qué modelo es")
        check(st.sample.strip() == "OK", f"guarda la prueba como evidencia ({st.sample!r})")
        check(st.latency_ms >= 0, "y cuánto tardó en contestar")
        check(any(p.startswith("/api/chat") for p, _ in fake.recibido),
              "se ha hecho una INFERENCIA de verdad, no solo mirar la lista")
        check(settings.get("ollama_model") == "qwen3:8b",
              "la configuración se guarda SOLO después de la prueba")
        check(rt.hay_cerebro(), "y nexus sabe que tiene cerebro")
        check(st.publico()["active"] is True, "el HUD recibe active=true")


# ══════════════════════════════════════════════════════════════════════════════
#  3. OLLAMA APAGADO — el motivo real del enfado
# ══════════════════════════════════════════════════════════════════════════════
def test_ollama_apagado():
    print("· Ollama apagado")
    _reset_estado()
    settings.set("ollama_model", "qwen3:8b")
    settings.set("ollama_url", f"http://127.0.0.1:{_puerto_muerto()}")
    st = run(rt.activate_ollama_model("llama3.1"))
    check(not st.active, "no se activa nada si Ollama no está en marcha")
    check("ollama serve" in st.error_public.lower(),
          f"y se dice EXACTAMENTE qué hacer ({st.error_public!r})")
    check(settings.get("ollama_model") == "qwen3:8b",
          "la configuración NO se cambia por un intento fallido")
    check(not rt.hay_cerebro(), "nexus sabe que no tiene cerebro")
    # el mensaje sobrevive al filtro de voz pública (antes se borraba la frase
    # entera por mencionar la dirección de la máquina)
    limpio = pv.sanitize(st.error_public)
    check("ollama serve" in limpio.lower(),
          f"el aviso llega ENTERO al chat, no lo borra el filtro ({limpio!r})")
    check(not pv.tiene_fugas(st.error_public),
          f"y sin jerga interna: {pv.tiene_fugas(st.error_public)}")


# ══════════════════════════════════════════════════════════════════════════════
#  4. EL MODELO NO ESTÁ / LA ETIQUETA NO COINCIDE
# ══════════════════════════════════════════════════════════════════════════════
def test_modelo_ausente_y_etiqueta():
    print("· modelo ausente y etiqueta equivocada")
    _reset_estado()
    with _FakeOllama(["llama3.1:8b", "gemma3:12b", "bge-m3"], "ok"):
        st = run(rt.activate_ollama_model("mixtral:8x7b"))
        check(not st.active, "un modelo que Ollama no sirve NO se da por activo")
        check("ollama pull mixtral:8x7b" in st.error_public,
              f"se dice el comando exacto para instalarlo ({st.error_public!r})")
        check("llama3.1:8b" in st.error_public,
              "y qué modelos SÍ tienes para elegir ahora mismo")
        check("bge-m3" not in st.error_public,
              "sin ofrecer un modelo de embeddings como alternativa")

        # el caso «qwen3» vs «qwen3:8b» — decir «no lo tienes» era mentira
        st2 = run(rt.activate_ollama_model("llama3.1"))
        check(not st2.active, "una etiqueta que no existe tampoco se activa")
        check(st2.error_code == "etiqueta",
              f"pero se distingue de «no lo tienes» (código {st2.error_code})")
        check("llama3.1:8b" in st2.error_public,
              f"y se propone la etiqueta correcta ({st2.error_public!r})")
        for s in (st, st2):
            check(not pv.tiene_fugas(s.error_public), "mensaje sin jerga interna")


# ══════════════════════════════════════════════════════════════════════════════
#  5. EMBEDDINGS: se rechaza ANTES de intentarlo
# ══════════════════════════════════════════════════════════════════════════════
def test_embeddings_no_valen():
    print("· un modelo de embeddings no puede ser el cerebro")
    _reset_estado()
    with _FakeOllama(["bge-m3", "qwen3:8b"], "ok") as fake:
        st = run(rt.activate_ollama_model("bge-m3"))
        check(not st.active, "«bge-m3» no se acepta como cerebro")
        check(st.error_code == "embedding", f"con su motivo propio ({st.error_code})")
        check("embeddings" in st.error_public.lower(),
              f"y explicado en cristiano ({st.error_public!r})")
        check(not fake.recibido,
              "ni se molesta en llamarlo: se sabe por el tipo de modelo")


# ══════════════════════════════════════════════════════════════════════════════
#  6. OLLAMA ANTIGUO, RESPUESTA VACÍA, SIN MEMORIA
# ══════════════════════════════════════════════════════════════════════════════
def test_variantes_de_fallo():
    print("· Ollama antiguo / respuesta vacía / sin memoria")
    _reset_estado()
    with _FakeOllama(["qwen3:8b"], "ruta_vieja") as fake:
        st = run(rt.activate_ollama_model("qwen3:8b"))
        check(st.active, f"con un Ollama antiguo se reintenta por la vía que sí "
                         f"tiene y funciona igual ({st.error_public!r})")
        check(any(p.startswith("/api/generate") for p, _ in fake.recibido),
              "efectivamente ha usado la vía alternativa")

    _reset_estado()
    with _FakeOllama(["qwen3:8b"], "vacio"):
        st = run(rt.activate_ollama_model("qwen3:8b"))
        check(not st.active, "una respuesta VACÍA no cuenta como modelo funcionando")
        check(st.error_code == "vacio", f"y se distingue del resto ({st.error_code})")

    _reset_estado()
    with _FakeOllama(["llama3.1:70b"], "memoria"):
        st = run(rt.activate_ollama_model("llama3.1:70b"))
        check(not st.active, "un modelo que no cabe en memoria no se activa")
        check(st.error_code == "memoria", f"y se dice que es la memoria ({st.error_code})")
        check("memoria" in st.error_public.lower(),
              f"con una salida clara ({st.error_public!r})")

    _reset_estado()
    with _FakeOllama(["qwen3:8b"], "modelo_404"):
        st = run(rt.activate_ollama_model("qwen3:8b"))
        check(not st.active, "un 404 de modelo tampoco se da por bueno")
        check(not pv.tiene_fugas(st.error_public), "sin jerga interna")


# ══════════════════════════════════════════════════════════════════════════════
#  7. VERIFICAR LO CONFIGURADO SIN TOCAR NADA
# ══════════════════════════════════════════════════════════════════════════════
def test_verificacion_no_persiste():
    print("· verificar el cerebro configurado sin cambiar la configuración")
    _reset_estado()
    with _FakeOllama(["qwen3:8b"], "ok"):
        settings.set("llm_provider", "ollama")
        settings.set("ollama_model", "qwen3:8b")
        st = run(rt.verify_current(force=True))
        check(st.active and st.verified, "el modelo configurado se comprueba de verdad")
        check(st.resumen().startswith("Cerebro:"), f"resumen legible: {st.resumen()!r}")

    _reset_estado()
    with _FakeOllama(["gemma3:12b"], "ok"):
        settings.set("ollama_model", "qwen3:8b")       # ya no está servido
        st = run(rt.verify_current(force=True))
        check(not st.active, "si el configurado ya no está, deja de estar activo")
        check(settings.get("ollama_model") == "qwen3:8b",
              "y aun así NO se cambia lo que eligió el usuario")
        check("SIN VERIFICAR" in st.resumen(), f"el resumen lo dice: {st.resumen()!r}")


def test_el_cerebro_elegido_sobrevive_al_reinicio():
    """Adrián ponía Gemini y nexus arrancaba con qwen3 (03/08/2026).

    `verify_current()` corre EN CADA ARRANQUE con persistir=False, y aun así
    `activate_cloud_model()` escribía `llm_provider` en disco antes de la sonda
    para restaurarlo después. Entre el `set` y el `restore` el disco tiene un
    proveedor que nadie ha elegido: si el proceso muere ahí, o si dos
    verificaciones se solapan, esa preferencia prestada se queda puesta.

    La sonda no lo necesita: llama a `prov.chat()` sobre el proveedor elegido.
    """
    _reset_estado()
    settings.set("llm_provider", "gemini")
    settings.set("llm_local", False)
    settings.set("gemini_model", "gemini-2.5-flash")

    # Verificar NO puede tocar la preferencia guardada, ni siquiera un instante.
    tocados: list = []
    real_set = settings.set

    def espia(k, v):
        if k in ("llm_provider", "llm_local"):
            tocados.append((k, v))
        return real_set(k, v)

    settings.set = espia
    try:
        run(rt.verify_current(force=True))
    finally:
        settings.set = real_set

    check(tocados == [],
          f"verificar ha escrito la preferencia del cerebro: {tocados}. "
          "Con persistir=False no puede tocarla NI para restaurarla luego")
    check(settings.get("llm_provider") == "gemini",
          f"tras verificar, el cerebro elegido ya no es gemini sino "
          f"{settings.get('llm_provider')!r}")
    check(settings.get("ollama_model") != settings.get("llm_provider"),
          "el proveedor ha acabado apuntando al modelo local")


# ══════════════════════════════════════════════════════════════════════════════
#  8. CATÁLOGO PARA EL HUD (clasificado en el backend)
# ══════════════════════════════════════════════════════════════════════════════
def test_catalogo():
    print("· catálogo de modelos para ⚙")
    _reset_estado()
    with _FakeOllama(["qwen3:8b", "bge-m3", "gemma3:12b"], "ok"):
        cat = run(rt.catalog())
        check(cat["ollama_up"] is True, "el catálogo sabe si Ollama está en marcha")
        por_nombre = {i["name"]: i for i in cat["items"]}
        check(por_nombre["qwen3:8b"]["usable"] is True, "qwen3:8b se ofrece como cerebro")
        check(por_nombre["bge-m3"]["usable"] is False, "bge-m3 se ofrece pero bloqueado")
        check("embeddings" in por_nombre["bge-m3"]["note"],
              f"con su motivo escrito ({por_nombre['bge-m3']['note']!r})")
        check(cat["usables"] == 2, f"cuenta 2 utilizables (dice {cat['usables']})")
        check(cat["aviso"] == "", "y sin aviso, porque hay modelos utilizables")

    _reset_estado()
    settings.set("ollama_url", f"http://127.0.0.1:{_puerto_muerto()}")
    cat = run(rt.catalog())
    check(cat["ollama_up"] is False, "si Ollama no responde, el catálogo lo dice")
    check("ollama serve" in cat["aviso"].lower(),
          f"con la instrucción para arreglarlo ({cat['aviso']!r})")
    check(all(not i["usable"] for i in cat["items"]),
          "y NINGÚN modelo del disco aparece como utilizable")


# ══════════════════════════════════════════════════════════════════════════════
#  9. SE ACABÓ EL CEREBRO DE MENTIRA SILENCIOSO
# ══════════════════════════════════════════════════════════════════════════════
def test_sin_fallback_simulado():
    print("· ya no hay respuesta simulada a escondidas")
    _reset_estado()
    settings.set("llm_provider", "ollama")
    settings.set("ollama_url", f"http://127.0.0.1:{_puerto_muerto()}")
    for k in ("openai_api_key", "anthropic_api_key", "gemini_api_key", "cloud_llm_api_key"):
        try:
            settings.set_secret(k, "")
        except Exception:
            pass

    salto = {"ok": False}

    async def _prueba():
        try:
            await _llm.get_provider()
        except _llm.SinCerebro as exc:
            salto["ok"] = True
            salto["publico"] = exc.publico
        return await _llm.ask_llm("¿qué tal?")

    respuesta, proveedor = run(_prueba())
    check(salto["ok"], "sin ningún proveedor vivo se avisa en vez de disimular")
    check(proveedor == "ninguno",
          f"la respuesta NO se atribuye a un modelo (proveedor={proveedor!r})")
    check(proveedor != "mock", "y no se cuela el modo demostración como si fuera real")
    check(len(respuesta) > 20 and "⚙" in respuesta or "Ollama" in respuesta,
          f"se explica qué pasa y qué hacer: {respuesta!r}")
    check(not pv.tiene_fugas(respuesta), f"sin jerga interna: {pv.tiene_fugas(respuesta)}")

    # el modo demostración sigue existiendo SI LO ELIGES TÚ
    _reset_estado()
    settings.set("llm_provider", "mock")
    prov = run(_llm.get_provider())
    check(prov.name == "mock", "elegir «mock» a propósito sigue funcionando")
    settings.set("llm_provider", "ollama")
    _reset_estado()


# ══════════════════════════════════════════════════════════════════════════════
# 10. EL CÓDIGO QUE SE ENTREGA (interfaz y servidor)
# ══════════════════════════════════════════════════════════════════════════════
def test_codigo_entregado():
    print("· la interfaz y el servidor están conectados al runtime")
    js = js_hud()
    app = (Path(ROOT) / "backend" / "app.py").read_text(encoding="utf-8")
    llmsrc = (Path(ROOT) / "backend" / "core" / "infraestructura" / "llm.py").read_text(encoding="utf-8")

    check("/api/llm/activate" in js, "el botón del HUD activa a través del runtime")
    check("/api/llm/status" in js, "y el HUD pregunta el estado real")
    check("/api/llm/models" in js, "el desplegable usa el catálogo ya clasificado")
    check("rt.active && rt.provider === 'ollama'" in js,
          "«EN USO» sale del runtime, no de la preferencia guardada")
    check("SIN PROBAR" in js, "y hay un estado visible para «elegido pero sin probar»")
    check("Probar y usar como cerebro" in js.replace('\\n', ''),
          "el botón dice lo que hace: PROBAR")
    check("'/api/local_models'" not in js,
          "ya no se pinta el desplegable con la lista sin clasificar")

    for ruta in ("/api/llm/status", "/api/llm/activate", "/api/llm/models",
                 "/api/llm/status_full"):
        check(f'"{ruta}"' in app, f"el servidor expone {ruta}")
    check("_arranca_runtime_llm" in app, "y comprueba el cerebro al arrancar")
    check('chosen = chosen or PROVIDERS["mock"]' not in llmsrc,
          "el salto silencioso al modo demostración ha desaparecido del código")
    check("class SinCerebro" in llmsrc, "y en su lugar hay un aviso explícito")


# ══════════════════════════════════════════════════════════════════════════════
# 11. NINGÚN MENSAJE DEL RUNTIME SE VA DE LA LENGUA
# ══════════════════════════════════════════════════════════════════════════════
def test_voz_publica():
    print("· todos los mensajes del runtime son publicables")
    codigos = ["ollama_apagado", "modelo_ausente", "etiqueta", "embedding", "lento",
               "memoria", "vacio", "auth", "saldo", "rate_limit", "proveedor",
               "sin_conexion", "vacio_modelo"]
    for c in codigos:
        m = rt._msg(c, "qwen3:8b", "gemma3:12b")
        check(bool(m), f"«{c}» tiene mensaje")
        check(not pv.tiene_fugas(m), f"«{c}» sin jerga interna: {pv.tiene_fugas(m)}")
        check(len(pv.sanitize(m)) >= len(m) * 0.8,
              f"«{c}» llega entero al chat (el filtro no se lo come): {pv.sanitize(m)!r}")
        check(not any(x in m for x in ("HTTP", "404", "500", "127.0.0.1", "11434")),
              f"«{c}» no enseña códigos ni direcciones")


def main() -> int:
    for f in (test_clasificacion, test_activacion_correcta, test_ollama_apagado,
              test_modelo_ausente_y_etiqueta, test_embeddings_no_valen,
              test_variantes_de_fallo, test_verificacion_no_persiste,
              test_el_cerebro_elegido_sobrevive_al_reinicio, test_catalogo,
              test_sin_fallback_simulado, test_codigo_entregado, test_voz_publica):
        try:
            f()
        except Exception as e:                                   # noqa: BLE001
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
        shutil.rmtree(_SANDBOX, ignore_errors=True)
    sys.exit(code)
