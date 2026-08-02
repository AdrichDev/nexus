# -*- coding: utf-8 -*-
"""
nexus — RUNTIME DE MODELOS: una sola verdad sobre qué cerebro está funcionando.

POR QUÉ EXISTE (queja de Adri, 25/07/2026)
------------------------------------------
La DETECCIÓN VISUAL y el RUNTIME REAL estaban desacoplados:

  * el desplegable de ⚙ leía las carpetas del disco → «tengo qwen3:8b»
  * el badge «EN USO» salía de una preferencia guardada → «cerebro activo»
  * y el chat, dos segundos después → «el modelo qwen3:8b no está en Ollama»

Tres sitios distintos opinando sobre lo mismo, y ninguno de los tres había
hablado nunca con el modelo. De ahí los mensajes incoherentes.

REGLA DE ESTE MÓDULO
--------------------
Un modelo solo está ACTIVO si ha contestado a una INFERENCIA REAL.
Ni el disco, ni la configuración, ni aparecer en la lista de Ollama bastan.
Y si no está activo, nexus lo dice — no contesta con una imitación disimulada.

Todo lo que sale de aquí hacia el chat pasa por el vocabulario público: se habla
de «Ollama», del modelo y de qué hacer, nunca de rutas, puertos ni códigos.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import asdict, dataclass

import httpx

from backend.core import net
from backend.core.config import settings

# ──────────────────────────────────────────────────────────────────────────────
#  1. QUÉ TIPO DE MODELO ES
# ──────────────────────────────────────────────────────────────────────────────
# Un modelo de embeddings NO conversa: convierte texto en vectores. Ponerlo de
# cerebro daba una respuesta vacía o un error raro, y el usuario no tenía forma
# de saber por qué. Se separan AQUÍ, en el backend, para que la interfaz no
# tenga que adivinarlo (antes lo hacía con un regex suyo — dos criterios
# distintos para la misma pregunta).
EMBEDDING_MODELS: set[str] = {
    "bge-m3", "bge-large", "bge-small", "bge-base",
    "nomic-embed-text", "mxbai-embed-large", "all-minilm",
    "gte-base", "gte-large", "e5-base", "e5-large",
    "snowflake-arctic-embed", "paraphrase-multilingual",
}
_EMB_RX = re.compile(
    r"(?:^|[-_/])(?:bge|nomic-embed|mxbai|gte|e5|minilm|arctic-embed)"
    r"|embed(?:ding)?s?(?:[-_.:]|$)", re.IGNORECASE)


def classify_model(name: str) -> str:
    """«chat» (sirve de cerebro) | «embedding» (solo para buscar en documentos).

    Se mira el nombre BASE, sin la etiqueta: «bge-m3:latest» es lo mismo que
    «bge-m3», y «sorc/qwen3.5:q4» sigue siendo un modelo de conversación."""
    raw = (name or "").strip().lower()
    if not raw:
        return "desconocido"
    corto = raw.split("/")[-1]          # quita el namespace (sorc/…)
    base = corto.split(":")[0]          # quita la etiqueta (:8b, :latest)
    if base in EMBEDDING_MODELS or corto in EMBEDDING_MODELS:
        return "embedding"
    if _EMB_RX.search(base):
        return "embedding"
    return "chat"


def sirve_de_cerebro(name: str) -> bool:
    return classify_model(name) == "chat"


# ──────────────────────────────────────────────────────────────────────────────
#  2. EL ESTADO (lo que ve el HUD y lo que responde el chat)
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class LLMRuntimeStatus:
    """El estado REAL del cerebro. `active` solo es True si `verified` lo es."""
    active: bool = False
    provider: str = ""
    model: str = ""
    display: str = ""            # cómo se llama para el usuario
    kind: str = "chat"
    verified: bool = False       # ¿ha contestado a una inferencia de verdad?
    checked_at: float = 0.0
    latency_ms: int = 0
    sample: str = ""             # lo que contestó en la prueba (evidencia)
    error_code: str = ""         # categoría interna (embedding, infra, modelo…)
    error_public: str = ""       # LO ÚNICO que puede ir al chat
    error_tech: str = ""         # solo registro y panel de diagnóstico
    fallback_from: str = ""      # si se cambió de proveedor, desde cuál

    # --- lo que puede salir a la interfaz / al chat ---
    def publico(self) -> dict:
        return {
            "active": bool(self.active and self.verified),
            "provider": self.provider,
            "model": self.model,
            "display": self.display or self.model,
            "kind": self.kind,
            "verified": self.verified,
            "latency_ms": self.latency_ms,
            "checked_at": self.checked_at,
            "error": self.error_public,
            "error_code": self.error_code,
        }

    # --- lo que ve un administrador en el panel de diagnóstico ---
    def tecnico(self) -> dict:
        d = asdict(self)
        d["active"] = bool(self.active and self.verified)
        return d

    def resumen(self) -> str:
        """Una línea para el arranque / los registros."""
        if self.active and self.verified:
            return (f"Cerebro: {self.display or self.model} "
                    f"({self.provider}) — probado, {self.latency_ms} ms")
        return f"Cerebro SIN VERIFICAR: {self.error_public or 'sin configurar'}"


_STATUS = LLMRuntimeStatus()
_TTL = 60.0                      # segundos que vale una verificación
_lock = asyncio.Lock()


def status() -> LLMRuntimeStatus:
    """El último estado conocido. No hace red: es una lectura."""
    return _STATUS


def hay_cerebro() -> bool:
    return bool(_STATUS.active and _STATUS.verified)


# NO HAY «mensaje_sin_cerebro()» AQUÍ, Y ES A PROPÓSITO (02/08/2026).
# Devolvía el mensaje honesto de «no tengo modelo». No la llamaba nadie: quien de
# verdad lo dice es `llm.py:664`, que construye ese MISMO texto por su cuenta. O
# sea, una copia muerta al lado de la viva. Si hay que tocar el mensaje, se toca
# en llm.py; el estado para decidirlo se lee con `hay_cerebro()`.


# ──────────────────────────────────────────────────────────────────────────────
#  3. MENSAJES PÚBLICOS
# ──────────────────────────────────────────────────────────────────────────────
# Ninguno menciona rutas, puertos ni códigos HTTP: son instrucciones, no vísceras.
def _msg(code: str, model: str = "", extra: str = "") -> str:
    m = f"«{model}»" if model else "el modelo"
    textos = {
        "ollama_apagado":
            "Ollama no está en marcha, así que no puedo cargar ningún modelo local. "
            "Ábrelo (o ejecuta «ollama serve» en una consola) y vuelvo a intentarlo.",
        "modelo_ausente":
            f"{m} no está descargado en Ollama" + (f" — sí tienes {extra}" if extra else "")
            + f". Descárgalo con «ollama pull {model}» o elige otro en ⚙.",
        "etiqueta":
            f"{m} no existe con ese nombre exacto, pero sí tienes {extra}. "
            "Elige esa etiqueta en ⚙ y funcionará.",
        "embedding":
            f"{m} es un modelo de embeddings: sirve para buscar en tus documentos, "
            "no para conversar. Elige uno de conversación como cerebro.",
        "lento":
            f"{m} ha tardado demasiado en contestar a la prueba. Suele pasar la primera "
            "vez con modelos grandes: reintenta en un momento o elige uno más ligero.",
        "memoria":
            f"{m} no cabe en la memoria de tu equipo. Prueba una versión más pequeña "
            "o más comprimida del mismo modelo.",
        "vacio":
            f"{m} ha contestado sin contenido. No lo doy por bueno: prueba otro modelo.",
        "auth":
            "Ese servicio no me ha dejado entrar con las credenciales que tengo. "
            "Revísalas en ⚙ y lo vuelvo a probar.",
        "saldo":
            "Ese servicio no tiene crédito disponible ahora mismo, así que no puedo "
            "usarlo como cerebro.",
        "rate_limit":
            "Ese servicio me ha pedido esperar por exceso de peticiones. Prueba otra vez "
            "en un minuto.",
        "proveedor":
            "El servicio está dando problemas ahora mismo. No he podido dejarlo probado; "
            "puedes reintentarlo.",
        "desconocido_prov":
            f"No conozco el proveedor «{extra}». Elige uno de la lista en ⚙.",
        "sin_conexion":
            "No he podido contactar con ese servicio. Comprueba la conexión y reintento.",
        "vacio_modelo":
            "No me has dicho qué modelo activar.",
    }
    return textos.get(code, "No he podido dejar el modelo probado y funcionando.")


def _clasifica_excepcion(exc: Exception, model: str = "") -> tuple[str, str, str]:
    """(codigo, mensaje_publico, detalle_tecnico) a partir de un fallo real."""
    tech = f"{type(exc).__name__}: {exc}"
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        cuerpo = ""
        try:
            cuerpo = exc.response.text[:400]
        except Exception:
            pass
        tech = f"HTTP {code} · {cuerpo}"
        bajo = cuerpo.lower()
        if code == 404:
            return "modelo_ausente", _msg("modelo_ausente", model), tech
        if code in (401, 403):
            return "auth", _msg("auth"), tech
        if code == 402:
            return "saldo", _msg("saldo"), tech
        if code == 429:
            return "rate_limit", _msg("rate_limit"), tech
        if "memory" in bajo or "out of memory" in bajo or "requires more" in bajo:
            return "memoria", _msg("memoria", model), tech
        if 500 <= code < 600:
            return "proveedor", _msg("proveedor"), tech
        return "proveedor", _msg("proveedor"), tech
    if isinstance(exc, (httpx.ReadTimeout, httpx.PoolTimeout, asyncio.TimeoutError)):
        return "lento", _msg("lento", model), tech
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return "infra", _msg("ollama_apagado"), tech
    return "desconocido", _msg("desconocido"), tech


# ──────────────────────────────────────────────────────────────────────────────
#  4. CLIENTE DE OLLAMA (el único que habla con Ollama para el runtime)
# ──────────────────────────────────────────────────────────────────────────────
class OllamaNoDisponible(RuntimeError):
    def __init__(self, publico: str, tecnico: str = "", code: str = "infra"):
        super().__init__(tecnico or publico)
        self.publico = publico
        self.tecnico = tecnico
        self.code = code


class OllamaClient:
    """Ollama, de verdad: listar lo que sirve AHORA y probar una inferencia.

    No mira carpetas. Un modelo en el disco que Ollama no está sirviendo NO
    cuenta como disponible — esa confusión es justo la que rompía el HUD."""

    # Qué ruta acepta ESTA instalación. Se aprende en la primera llamada.
    ruta: str = ""

    def __init__(self, base_url: str = "", *, timeout: float = 4.0):
        self._base = (base_url or "").rstrip("/")
        self.timeout = timeout

    @property
    def base(self) -> str:
        if self._base:
            return self._base
        return str(settings.get("ollama_url", "http://localhost:11434")).rstrip("/")

    async def list_models(self) -> list[dict]:
        """Lo que Ollama SIRVE ahora mismo. Lanza OllamaNoDisponible si no está."""
        try:
            r = await net.client().get(f"{self.base}/api/tags", timeout=self.timeout)
            r.raise_for_status()
            datos = r.json().get("models") or []
        except Exception as exc:                                   # noqa: BLE001
            raise OllamaNoDisponible(_msg("ollama_apagado"),
                                     f"{type(exc).__name__}: {exc}") from exc
        salida = []
        for m in datos:
            nombre = m.get("name") or m.get("model") or ""
            if not nombre:
                continue
            salida.append({
                "name": nombre,
                "size": m.get("size", 0),
                "kind": classify_model(nombre),
                "family": ((m.get("details") or {}).get("family") or ""),
            })
        return salida

    async def probe(self, model: str, *, timeout: float = 90.0) -> tuple[str, int]:
        """LA PRUEBA DE VERDAD: una inferencia mínima. Devuelve (texto, ms).

        Es lo que separa «lo tengo instalado» de «funciona». Se pide una
        respuesta de dos palabras para que sea barata incluso con modelos
        grandes, y se deja cargado 10 minutos para que la primera pregunta
        real del usuario no vuelva a esperar."""
        t0 = time.time()
        msgs = [{"role": "user", "content": "Responde únicamente con la palabra OK."}]
        # num_predict 8 era MUY POCO. Los modelos de razonamiento (qwen3, deepseek-r1,
        # los «thinking») gastan los primeros tokens PENSANDO, en un campo aparte, y
        # devuelven `content` VACÍO si se les corta antes. Por eso el 30/07/2026 el
        # HUD decía «qwen3:8b ha contestado sin contenido» teniéndolo perfectamente
        # instalado y sirviendo. Con margen suficiente y `think: false` contesta.
        opciones = {"num_predict": 96, "temperature": 0}
        rutas = [OllamaClient.ruta] if OllamaClient.ruta else ["chat", "generate"]
        ultimo: Exception | None = None
        for ruta in rutas:
            try:
                if ruta == "chat":
                    r = await net.client().post(
                        f"{self.base}/api/chat",
                        json={"model": model, "messages": msgs, "stream": False,
                              "keep_alive": "10m", "think": False, "options": opciones},
                        timeout=timeout)
                    r.raise_for_status()
                    OllamaClient.ruta = "chat"
                    m = r.json().get("message") or {}
                    # Si aun así solo ha razonado, ESO TAMBIÉN es contestar: el
                    # modelo está vivo y responde. Lo que no vale es el silencio.
                    txt = ((m.get("content") or "").strip()
                           or (m.get("thinking") or m.get("reasoning") or "").strip())
                else:
                    r = await net.client().post(
                        f"{self.base}/api/generate",
                        json={"model": model, "prompt": msgs[0]["content"],
                              "stream": False, "keep_alive": "10m", "think": False,
                              "options": opciones},
                        timeout=timeout)
                    r.raise_for_status()
                    d = r.json()
                    OllamaClient.ruta = "generate"
                    txt = ((d.get("response") or "").strip()
                           or (d.get("thinking") or "").strip())
                return txt, int((time.time() - t0) * 1000)
            except httpx.HTTPStatusError as exc:
                ultimo = exc
                cuerpo = ""
                try:
                    cuerpo = exc.response.text[:400].lower()
                except Exception:
                    pass
                # 404 «no existe el modelo» ≠ 404 «no existe esa ruta».
                # Cambiar de ruta solo arregla el segundo.
                if exc.response.status_code == 404 and "model" not in cuerpo:
                    continue
                raise
            except Exception as exc:                                # noqa: BLE001
                raise
        raise ultimo if ultimo else RuntimeError("Ollama no respondió")


# ──────────────────────────────────────────────────────────────────────────────
#  5. ACTIVAR UN MODELO (esto es lo que hace el botón «usar como cerebro»)
# ──────────────────────────────────────────────────────────────────────────────
def _falla(code: str, publico: str, tecnico: str = "", *, provider: str = "",
           model: str = "", kind: str = "chat") -> LLMRuntimeStatus:
    return LLMRuntimeStatus(active=False, verified=False, provider=provider,
                            model=model, display=model, kind=kind,
                            checked_at=time.time(), error_code=code,
                            error_public=publico, error_tech=tecnico)


def _guardar_estado(st: LLMRuntimeStatus) -> LLMRuntimeStatus:
    global _STATUS
    _STATUS = st
    return st


async def activate_ollama_model(model: str, *, persistir: bool = True) -> LLMRuntimeStatus:
    """Activa un modelo local. Solo lo da por bueno si CONTESTA.

    Si falla, la configuración NO se toca: nexus no se queda diciendo que usa
    un cerebro que no funciona."""
    model = (model or "").strip()
    if not model:
        return _guardar_estado(_falla("vacio_modelo", _msg("vacio_modelo"),
                                      provider="ollama"))

    kind = classify_model(model)
    if kind == "embedding":
        return _guardar_estado(_falla("embedding", _msg("embedding", model),
                                      f"{model} clasificado como embeddings",
                                      provider="ollama", model=model, kind=kind))

    cli = OllamaClient()
    try:
        instalados = await cli.list_models()
    except OllamaNoDisponible as exc:
        return _guardar_estado(_falla(exc.code, exc.publico, exc.tecnico,
                                      provider="ollama", model=model))

    nombres = [m["name"] for m in instalados]
    if model not in nombres:
        base = model.split("/")[-1].split(":")[0].lower()
        parecidos = [n for n in nombres if n.split("/")[-1].split(":")[0].lower() == base]
        conversacion = [n for n in nombres if classify_model(n) == "chat"]
        if parecidos:
            return _guardar_estado(_falla(
                "etiqueta", _msg("etiqueta", model, ", ".join(parecidos[:3])),
                f"servidos: {nombres}", provider="ollama", model=model))
        return _guardar_estado(_falla(
            "modelo_ausente",
            _msg("modelo_ausente", model, ", ".join(conversacion[:4])),
            f"servidos: {nombres}", provider="ollama", model=model))

    try:
        texto, ms = await cli.probe(model)
    except Exception as exc:                                        # noqa: BLE001
        code, publico, tech = _clasifica_excepcion(exc, model)
        return _guardar_estado(_falla(code, publico, tech,
                                      provider="ollama", model=model))

    if not texto.strip():
        return _guardar_estado(_falla("vacio", _msg("vacio", model),
                                      "respuesta vacía en la prueba",
                                      provider="ollama", model=model))

    if persistir:
        settings.set("llm_provider", "ollama")
        settings.set("llm_local", True)
        settings.set("ollama_model", model)
        _invalidar_proveedor()

    return _guardar_estado(LLMRuntimeStatus(
        active=True, verified=True, provider="ollama", model=model, display=model,
        kind="chat", checked_at=time.time(), latency_ms=ms, sample=texto[:80]))


async def activate_cloud_model(provider: str, model: str = "",
                               *, persistir: bool = True) -> LLMRuntimeStatus:
    """Igual que el local pero con un proveedor de la nube: se PRUEBA con una
    llamada real antes de decir que está activo (specs v24, T13). Si no pasa la
    prueba, la configuración vuelve a como estaba."""
    from backend.core import llm as _llm

    prov = _llm.PROVIDERS.get(provider)
    if prov is None:
        return _guardar_estado(_falla("config", _msg("desconocido_prov", extra=provider),
                                      f"proveedor desconocido: {provider}",
                                      provider=provider, model=model))

    campo = {"openai": "openai_model", "anthropic": "anthropic_model",
             "gemini": "gemini_model", "cloud": "cloud_model"}.get(provider, "")
    # VERIFICAR NO PUEDE CAMBIAR LO QUE HAY GUARDADO. La sonda llama a
    # `prov.chat()` directamente sobre el proveedor elegido, así que no necesita
    # que `llm_provider` valga nada en concreto: solo el campo del modelo, que es
    # de donde el proveedor lo lee.
    #
    # Escribirlo igualmente abría una ventana peligrosa: `verify_current()` corre
    # EN CADA ARRANQUE con persistir=False, y entre el `set` y el `restore` el
    # disco tiene un proveedor que nadie ha elegido. Si el proceso muere ahí —o
    # si dos verificaciones se solapan— esa preferencia prestada se queda puesta.
    # Adrián lo vivió al revés: elegía Gemini y nexus arrancaba con qwen3.
    previo: dict = {}
    if persistir:
        previo = {"llm_provider": settings.get("llm_provider"),
                  "llm_local": settings.get("llm_local")}
    if campo:
        previo[campo] = settings.get(campo)

    if persistir:
        settings.set("llm_provider", provider)
        settings.set("llm_local", False)
    if campo and model:
        settings.set(campo, model)
    _invalidar_proveedor()

    try:
        texto = await asyncio.wait_for(
            prov.chat([{"role": "user", "content": "Responde únicamente con: OK"}]),
            timeout=60)
        ok = bool((texto or "").strip())
        if not ok:
            raise RuntimeError("respuesta vacía")
    except Exception as exc:                                        # noqa: BLE001
        for k, v in previo.items():                 # se deshace el cambio
            settings.set(k, v)
        _invalidar_proveedor()
        code, publico, tech = _clasifica_excepcion(
            exc if isinstance(exc, Exception) else RuntimeError("fallo"), model)
        return _guardar_estado(_falla(code, publico, tech,
                                      provider=provider, model=model))

    if not persistir:
        for k, v in previo.items():
            settings.set(k, v)
        _invalidar_proveedor()

    return _guardar_estado(LLMRuntimeStatus(
        active=True, verified=True, provider=provider, model=model or "(por defecto)",
        display=f"{provider} · {model}" if model else provider, kind="chat",
        checked_at=time.time(), sample=(texto or "")[:80]))


async def activate(provider: str, model: str = "", *, persistir: bool = True) -> LLMRuntimeStatus:
    """Punto único de activación: local o nube, misma promesa (probado o nada)."""
    if provider == "ollama":
        return await activate_ollama_model(model, persistir=persistir)
    if provider == "mock":
        return _guardar_estado(LLMRuntimeStatus(
            active=True, verified=True, provider="mock", model="mock",
            display="modo demostración", kind="chat", checked_at=time.time(),
            sample="modo demostración"))
    return await activate_cloud_model(provider, model, persistir=persistir)


def _invalidar_proveedor() -> None:
    try:
        from backend.core.llm import invalidate_provider
        invalidate_provider()
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
#  6. VERIFICAR LO QUE YA HAY CONFIGURADO (arranque y /api/llm/status)
# ──────────────────────────────────────────────────────────────────────────────
async def verify_current(*, force: bool = False) -> LLMRuntimeStatus:
    """Comprueba el cerebro CONFIGURADO sin cambiar nada.

    Es lo que hace que el badge «EN USO» del HUD signifique algo: no sale de la
    preferencia guardada, sale de esta comprobación."""
    if not force and _STATUS.checked_at and (time.time() - _STATUS.checked_at) < _TTL:
        return _STATUS
    async with _lock:
        if not force and _STATUS.checked_at and (time.time() - _STATUS.checked_at) < _TTL:
            return _STATUS
        prov = str(settings.get("llm_provider", "ollama"))
        if prov == "ollama":
            return await activate_ollama_model(str(settings.get("ollama_model", "")),
                                               persistir=False)
        if prov == "mock":
            return await activate(prov)
        campo = {"openai": "openai_model", "anthropic": "anthropic_model",
                 "gemini": "gemini_model", "cloud": "cloud_model"}.get(prov, "")
        return await activate_cloud_model(prov, str(settings.get(campo, "")) if campo else "",
                                          persistir=False)


async def initialize_llm_runtime(*, emitir: bool = True) -> LLMRuntimeStatus:
    """Se llama AL ARRANCAR el servidor: nexus sabe si tiene cerebro antes de
    que le preguntes, en vez de descubrirlo a mitad de la primera respuesta."""
    st = await verify_current(force=True)
    if emitir:
        try:
            from backend.core.events import bus
            await bus.emit("log", {"level": "ok" if st.active else "warn",
                                   "msg": st.resumen()})
        except Exception:
            pass
    return st


# ──────────────────────────────────────────────────────────────────────────────
#  7. CATÁLOGO PARA LA INTERFAZ (clasificado AQUÍ, no en el navegador)
# ──────────────────────────────────────────────────────────────────────────────
async def catalog() -> dict:
    """Todo lo que el selector de ⚙ necesita, ya masticado:

      * qué modelos SIRVE Ollama ahora (usables de verdad)
      * qué modelos están solo en el disco (no usables hasta arrancar Ollama)
      * cuáles son de embeddings (no valen de cerebro)
      * y cuál está activo DE VERDAD
    """
    from backend.core.llm import scan_local_models

    cli = OllamaClient()
    servidos: dict[str, dict] = {}
    ollama_up = False
    try:
        for m in await cli.list_models():
            servidos[m["name"]] = m
        ollama_up = True
    except OllamaNoDisponible:
        ollama_up = False

    items: list[dict] = []
    vistos: set[str] = set()
    for m in servidos.values():
        vistos.add(m["name"])
        gb = (m.get("size") or 0) / 1e9
        items.append({"name": m["name"], "kind": m["kind"],
                      "available": True, "usable": m["kind"] == "chat",
                      "source": "ollama (sirviendo)",
                      "detail": f"{gb:.1f} GB" if gb else "",
                      "note": "" if m["kind"] == "chat"
                              else "embeddings — no sirve de cerebro"})

    try:
        for m in await scan_local_models():
            nombre = m.get("name", "")
            if not nombre or nombre in vistos:
                continue
            vistos.add(nombre)
            kind = classify_model(nombre)
            items.append({"name": nombre, "kind": kind, "available": False,
                          "usable": False, "source": m.get("source", "disco"),
                          "detail": m.get("detail", ""),
                          "note": "embeddings — no sirve de cerebro" if kind == "embedding"
                                  else ("en el disco — Ollama no lo está sirviendo"
                                        if ollama_up else
                                        "en el disco — Ollama no está en marcha")})
    except Exception:
        pass

    items.sort(key=lambda d: (not d["usable"], d["name"].lower()))
    usables = [d for d in items if d["usable"]]
    return {"ollama_up": ollama_up, "items": items,
            "usables": len(usables), "total": len(items),
            "aviso": "" if usables else
                     (_msg("ollama_apagado") if not ollama_up else
                      "Ollama está en marcha pero no sirve ningún modelo de conversación."),
            "active": _STATUS.publico()}
