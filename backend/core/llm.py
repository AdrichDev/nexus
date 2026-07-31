"""
nexus — Capa LLM multi-proveedor v3.

Proveedores soportados (seleccionables en ⚙, API keys en config/secrets.json):
  * ollama     — modelos LOCALES (check "modelo local"); detecta los instalados
  * openai     — GPT (api.openai.com)
  * anthropic  — Claude (api.anthropic.com, formato Messages propio)
  * gemini     — Google Gemini (generativelanguage.googleapis.com)
  * cloud      — cualquier endpoint compatible OpenAI (OpenRouter, Groq...)
  * mock       — simulado (demo sin nada)

scan_local_models() encuentra los modelos locales instalados: pregunta a
Ollama y además rastrea las carpetas típicas (manifests de Ollama, GGUF de
LM Studio) por si el servidor no está arrancado.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import random
from pathlib import Path

import httpx

from . import net
from .config import settings

_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre"]


def fecha_actual() -> str:
    """Fecha y hora locales en texto natural, para que el modelo sepa en qué día
    vive y pueda interpretar «hoy», «ayer», «mañana», «esta semana», etc."""
    n = _dt.datetime.now()
    return (f"{_DIAS[n.weekday()]} {n.day} de {_MESES[n.month - 1]} de {n.year}, "
            f"son las {n:%H:%M}")

# ----------------------------------------------------------------------
#  PERSONALIDADES — elegibles en la instalación y en ⚙. Cada una inyecta un
#  bloque distinto en el system prompt, así que cambia DE VERDAD cómo habla.
# ----------------------------------------------------------------------
PERSONALITIES = {
    "jarvis": {
        "name": "JARVIS (mayordomo con chispa)",
        "desc": "Elegante, leal y con ironía fina. Chascarrillos, refranes y un «señor» de vez en cuando.",
        "prompt": (
            "PERSONALIDAD (parte de quién eres, no la ocultes): estilo JARVIS de Iron Man.\n"
            "- Te diriges a {operator} por su nombre o con un «señor» elegante; educado,\n"
            "  con gracia y calidez, nada acartonado.\n"
            "- Tienes chispa: chascarrillos, algún chiste bueno, un refrán español al vuelo\n"
            "  y un punto castizo cuando encaja. La ironía fina es tu sello, sin faltar nunca."),
    },
    "profesional": {
        "name": "Profesional (directo al grano)",
        "desc": "Serio, conciso y eficiente. Cero bromas: datos, pasos y resultados.",
        "prompt": (
            "PERSONALIDAD: asistente PROFESIONAL.\n"
            "- Tono serio, claro y directo con {operator}. Nada de bromas ni adornos.\n"
            "- Prioriza datos, pasos accionables y resultados medibles. Frases cortas.\n"
            "- Si algo es una mala idea, lo dices sin rodeos y propones alternativa."),
    },
    "colega": {
        "name": "Colega (cercano y natural)",
        "desc": "Habla como un amigo de confianza: relajado, con humor natural y sin formalidades.",
        "prompt": (
            "PERSONALIDAD: eres el COLEGA de confianza de {operator}.\n"
            "- Tuteo total, lenguaje coloquial español, humor natural sin pasarse.\n"
            "- Celebras sus logros («¡eso está hecho, crack!») y le animas en los malos ratos.\n"
            "- Cero formalidades: nada de «señor», habla como en un grupo de amigos."),
    },
    "sargento": {
        "name": "Sargento (disciplina y caña)",
        "desc": "Motivador exigente: te empuja, te marca plazos y no acepta excusas (con respeto).",
        "prompt": (
            "PERSONALIDAD: SARGENTO motivador de {operator}.\n"
            "- Exigente y enérgico: marcas plazos, pides compromiso y señalas las excusas.\n"
            "- Frases cortas e imperativas («A por ello. Ya.»). Celebras la disciplina.\n"
            "- Duro con el problema, respetuoso con la persona: nunca insultas ni humillas."),
    },
    "zen": {
        "name": "Zen (calma y perspectiva)",
        "desc": "Sereno y pausado. Baja el estrés, ordena prioridades y da perspectiva.",
        "prompt": (
            "PERSONALIDAD: asistente ZEN de {operator}.\n"
            "- Tono sereno y pausado; transmites calma incluso con malas noticias.\n"
            "- Ayudas a priorizar: una cosa cada vez, respiración, perspectiva.\n"
            "- Usas metáforas sencillas y recuerdas que casi nada es tan urgente como parece."),
    },
    "canalla": {
        "name": "Canalla (ironía sin filtro)",
        "desc": "Sarcástico y punzante, vacile constante — pero competente y siempre de tu lado.",
        "prompt": (
            "PERSONALIDAD: CANALLA con corazón, el vacilón de {operator}.\n"
            "- Sarcasmo e ironía constantes, réplicas rápidas y vacile de colega.\n"
            "- Debajo del vacile eres competentísimo: el trabajo sale perfecto igual.\n"
            "- Te ríes DE la situación, no de {operator}; jamás cruzas a lo ofensivo."),
    },
}


SYSTEM_PROMPT = """Eres {assistant}, {art} asistente personal de {operator}.
Tu nombre es {assistant}: preséntate y refiérete a ti {refl} SIEMPRE como {assistant}.
GÉNERO: tu voz es {vozgen}; cuando hables DE TI usa SIEMPRE el género {genero} en
adjetivos y participios (p. ej. «{ej}»), nunca el contrario.
Respondes SIEMPRE en español.

{personality}

- Eres un interlocutor COMPLETO: hablas de CUALQUIER tema con soltura —fútbol, ciencia,
  historia, cine, cocina, tecnología, lo que sea— como una conversación inteligente.

CAPACIDADES REALES (esto es CRÍTICO): NO eres solo un chat. Controlas el ordenador y
servicios de {operator} a través de módulos. Puedes, de verdad: abrir cualquier aplicación
instalada, reproducir música (Spotify o YouTube), crear/mover/copiar/renombrar archivos y
carpetas, crear documentos en el escritorio, leer Gmail, ver Google Calendar y Google Tasks,
gestionar tareas y memoria, controlarte por Telegram (incluidas notas de voz), y BUSCAR y
SCRAPEAR información en internet (tienes búsqueda web real). Cuando una pregunta necesita datos
actuales, el sistema ya te inyecta resultados de la web en el contexto: úsalos y responde con
datos frescos.
Tienes además un SUBAGENTE AGÉNTICO propio, Hermes: navega por webs DE VERDAD, automatiza el
navegador, investiga en profundidad varias fuentes, scrapea y ejecuta código. Hermes es TU
herramienta interna: TÚ decides delegarle el trabajo agéntico y el sistema lo arranca solo,
sin que {operator} abra nada ni lo nombre. PROHIBIDO decirle a {operator} que «se lo pida a
Hermes», que lo arranque o que lo mencione: si el encargo es agéntico, delega tú y di que ya
estás en ello.
Además tienes OÍDO y VOZ de verdad: {operator} puede HABLARTE por el micrófono (un Whisper
local transcribe su voz y te llega como texto ya transcrito) y tus respuestas se reproducen
EN VOZ ALTA por TTS. El reconocimiento de voz NO se «activa» con ninguna orden: ya funciona.
Por eso: JAMÁS digas «no tengo acceso a tu correo/agenda», «no puedo abrir programas»,
«no puedo crear archivos», «no puedo buscar/scrapear en internet», «no te oigo», «no recibo
audio» o «activa el reconocimiento de voz» ni nada parecido — SÍ puedes y SÍ oyes.
Nunca niegues una capacidad que tienes. Y NUNCA le pidas a {operator} que use una
«frase exacta» o «orden concreta»: TÚ debes DEDUCIR la intención de lo que dice, sea como
sea que lo diga. Si de verdad falta un dato para actuar, pregúntalo en lenguaje natural
(«¿en qué ciudad?», «¿qué canción?»), no le mandes repetir una fórmula.

REGLA DE ORO — ACCIONES: si una petición de ACCIÓN (crear/borrar/mover tareas, enviar
correos, abrir apps, poner música, encender aparatos…) te llega A TI, el modelo
conversacional, significa que NINGUNA skill la ha ejecutado. TERMINANTEMENTE PROHIBIDO
responder «hecho», «ya está», «he creado…», «tarea creada» o narrar la acción como
realizada: tú NO ejecutas nada, solo conversas — afirmar trabajo no hecho es el peor
fallo posible. En ese caso di con naturalidad que no has podido hacerlo aún y, si falta
un dato, pídelo con tus palabras. PROHIBIDO pedirle que repita la orden con una «frase
exacta» o una fórmula concreta — eso es cosa tuya, no suya. Jamás simules resultados.

ACTÚA SIEMPRE COMO PROJECT MANAGER Y ASISTENTE de {operator}, no como un chatbot pasivo:
lleva el control de sus tareas y citas, se las recuerdas, y cuando te plantea algo no te
limitas a responder — ORIENTAS: propones la MEJOR forma de afrontarlo, lo desglosas en
pasos accionables, priorizas y anticipas lo que hará falta. Tienes iniciativa: si detectas
algo importante (una fecha que se acerca, un cabo suelto, una mejor manera de hacerlo), dilo.

Sé breve por defecto (2-4 frases) pero extiéndete cuando el tema lo pida. No eres
complaciente: si {operator} se equivoca en un dato o razonamiento, lo corriges con respeto
y argumentos. Prefieres una verdad útil (con una sonrisa) a un halago vacío.

INFORMACIÓN SÚPER CONCRETA (obligatorio): ve al grano con el DATO exacto —cifras,
nombres, marcadores, fechas, resultados— en la PRIMERA frase. Nada de rodeos, relleno
ni vaguedades tipo «depende», «podría ser», «te recomiendo consultar» o «no estoy
seguro» cuando el dato está a tu alcance o te llega por la web. Si lo sabes, dilo claro
y directo. Si de verdad NO lo tienes, dilo en una sola frase y ofrece «busca en internet
<tema>» — nunca inventes ni rellenes."""


class BaseProvider:
    name = "base"

    async def chat(self, messages: list[dict]) -> str:
        raise NotImplementedError

    async def chat_stream(self, messages: list[dict]):
        """STREAMING: por defecto cede la respuesta COMPLETA en un único trozo.
        Los proveedores que streamean de verdad (OpenAI) lo sobreescriben."""
        yield await self.chat(messages)

    async def available(self) -> bool:
        return True


class OllamaProvider(BaseProvider):
    name = "ollama"

    @property
    def url(self) -> str:
        return settings.get("ollama_url").rstrip("/")

    async def available(self) -> bool:
        try:
            r = await net.client().get(f"{self.url}/api/tags", timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    # Qué ruta funciona en ESTA instalación de Ollama. Se aprende sola en la
    # primera llamada y se recuerda (v24, bug de Adri del 25/07: 404 con TODOS
    # los modelos porque su Ollama no servía /api/chat).
    _ruta: str = ""

    async def chat(self, messages: list[dict]) -> str:
        modelo = settings.get("ollama_model")
        rutas = [OllamaProvider._ruta] if OllamaProvider._ruta else ["chat", "generate"]
        ultimo = None
        for ruta in rutas:
            try:
                if ruta == "chat":
                    r = await net.client().post(
                        f"{self.url}/api/chat",
                        json={"model": modelo, "messages": messages, "stream": False,
                              "think": False},
                        timeout=180)
                    r.raise_for_status()
                    OllamaProvider._ruta = "chat"
                    # Los modelos de razonamiento (qwen3, deepseek-r1…) separan lo
                    # que PIENSAN de lo que DICEN. Si solo se lee `content`, la
                    # respuesta llega VACÍA y nexus se queda mudo teniendo el modelo
                    # funcionando. Se pide no razonar y, si aun así solo hay
                    # pensamiento, se usa eso antes que devolver la nada.
                    m = r.json().get("message") or {}
                    return ((m.get("content") or "").strip()
                            or (m.get("thinking") or m.get("reasoning") or "").strip())
                # /api/generate: existe en TODAS las versiones de Ollama
                sys_txt = "\n".join(m["content"] for m in messages
                                    if m.get("role") == "system")
                conv = "\n".join(
                    f"{'Usuario' if m.get('role') == 'user' else 'Asistente'}: {m['content']}"
                    for m in messages if m.get("role") in ("user", "assistant"))
                r = await net.client().post(
                    f"{self.url}/api/generate",
                    json={"model": modelo, "prompt": conv + "\nAsistente:",
                          "system": sys_txt, "stream": False},
                    timeout=180)
                r.raise_for_status()
                OllamaProvider._ruta = "generate"
                _d = r.json()
                return ((_d.get("response") or "").strip()
                        or (_d.get("thinking") or "").strip())
            except httpx.HTTPStatusError as exc:
                ultimo = exc
                cuerpo = ""
                try:
                    cuerpo = exc.response.text[:300]
                except Exception:
                    pass
                # Si el 404 es porque FALTA EL MODELO, cambiar de ruta no arregla nada.
                if exc.response.status_code == 404 and "model" in cuerpo.lower():
                    raise
                if exc.response.status_code != 404:
                    raise
                continue                       # 404 de ruta → probamos la siguiente
        raise ultimo if ultimo else RuntimeError("Ollama no respondió")


class OpenAIProvider(BaseProvider):
    name = "openai"
    base = "https://api.openai.com/v1"

    def _key(self) -> str:
        return settings.secret("openai_api_key")

    def _model(self) -> str:
        return settings.get("openai_model")

    async def available(self) -> bool:
        return bool(self._key())

    async def chat(self, messages: list[dict]) -> str:
        r = await net.client().post(f"{self.base}/chat/completions",
                                    headers={"Authorization": f"Bearer {self._key()}"},
                                    json={"model": self._model(), "messages": messages},
                                    timeout=120)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]



    async def chat_stream(self, messages: list[dict]):
        """STREAMING SSE: cede el texto SEGÚN lo escribe el modelo → la voz puede
        empezar a hablar la 1ª frase mientras el resto aún se genera."""
        import json as _json
        async with net.client().stream(
                "POST", f"{self.base}/chat/completions",
                headers={"Authorization": f"Bearer {self._key()}"},
                json={"model": self._model(), "messages": messages, "stream": True},
                timeout=120) as r:
            if r.status_code >= 400:
                await r.aread()
                r.raise_for_status()
            async for line in r.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    return
                try:
                    piece = ((_json.loads(payload)["choices"][0].get("delta") or {})
                             .get("content") or "")
                except Exception:
                    piece = ""
                if piece:
                    yield piece

class CloudProvider(OpenAIProvider):
    """Endpoint compatible OpenAI configurable (OpenRouter, Groq, DeepSeek...)."""
    name = "cloud"

    @property
    def base(self) -> str:  # type: ignore[override]
        return settings.get("cloud_base_url").rstrip("/")

    def _key(self) -> str:
        return settings.cloud_api_key

    def _model(self) -> str:
        return settings.get("cloud_model")


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    async def available(self) -> bool:
        return bool(settings.secret("anthropic_api_key"))

    async def chat(self, messages: list[dict]) -> str:
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        turns = [m for m in messages if m["role"] in ("user", "assistant")]
        r = await net.client().post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": settings.secret("anthropic_api_key"),
                     "anthropic-version": "2023-06-01"},
            json={"model": settings.get("anthropic_model"),
                  "max_tokens": 1024, "system": system, "messages": turns},
            timeout=120)
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json()["content"])


class GeminiProvider(BaseProvider):
    name = "gemini"

    async def available(self) -> bool:
        return bool(settings.secret("gemini_api_key"))

    async def chat(self, messages: list[dict]) -> str:
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        contents = [{"role": "user" if m["role"] == "user" else "model",
                     "parts": [{"text": m["content"]}]}
                    for m in messages if m["role"] in ("user", "assistant")]
        model = settings.get("gemini_model")
        r = await net.client().post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": settings.secret("gemini_api_key")},
            json={"contents": contents,
                  "system_instruction": {"parts": [{"text": system}]}},
            timeout=120)
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]


class MockProvider(BaseProvider):
    name = "mock"

    _CANNED = [
        "Procesado, {op}. He registrado la petición y queda anotada en memoria.",
        "Entendido. La mejor jugada es dividirlo en pasos pequeños: empieza por el primero hoy.",
        "Afirmativo. Sistemas estables, sin incidencias que reportar.",
        "Anotado. ¿Programo un recordatorio de seguimiento?",
    ]

    async def chat(self, messages: list[dict]) -> str:
        user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        if any(w in user.lower() for w in ("hola", "buenas", "hey")):
            return f"A sus órdenes, {settings.get('operator_name')}. Todos los sistemas operativos."
        if "?" in user or "¿" in user:
            # v24: UN mensaje coherente. Antes salía «modo simulación» + un aviso
            # técnico pegado detrás que decía otra cosa distinta (queja de Adri).
            motivo = ""
            try:
                if settings.get("llm_provider") == "ollama":
                    url = settings.get("ollama_url", "http://localhost:11434")
                    if not _ollama_instalados():
                        motivo = (f" Ollama no está respondiendo en {url}: ábrelo (o ejecuta "
                                  "«ollama serve») y contesto de verdad.")
                    else:
                        motivo = (" Ollama sí responde, así que el problema está en el modelo "
                                  "elegido: pruébalo con «detectar modelos locales» en ⚙.")
            except Exception:
                motivo = ""
            return ("Ahora mismo no tengo cerebro conectado, así que no puedo darte una "
                    "respuesta de verdad." + (motivo or " Configura un modelo local o una "
                                              "clave de API en ⚙."))
        return random.choice(self._CANNED).format(op=settings.get("operator_name"))


PROVIDERS: dict[str, BaseProvider] = {
    "ollama": OllamaProvider(), "openai": OpenAIProvider(),
    "anthropic": AnthropicProvider(), "gemini": GeminiProvider(),
    "cloud": CloudProvider(), "mock": MockProvider(),
}


# El proveedor activo se CACHEA: antes se sondeaba available() (probe HTTP) en CADA
# mensaje. Se revalida cada 30 s, o al instante si cambias el cerebro en ⚙.
_prov_cache = {"prov": None, "t": 0.0}


class SinCerebro(RuntimeError):
    """No hay ningún modelo utilizable AHORA MISMO.

    Antes esto no existía: si el proveedor elegido no respondía, `get_provider()`
    devolvía CALLANDO el proveedor de mentira (`mock`), que contesta frases
    prefabricadas. El usuario recibía una respuesta con pinta de respuesta y no
    tenía forma de saber que su modelo estaba caído (queja de Adri, 25/07/2026:
    «no son coherentes los mensajes que lanza»). Ahora se levanta esta excepción
    y nexus lo dice con todas las letras."""

    def __init__(self, publico: str, tecnico: str = ""):
        super().__init__(tecnico or publico)
        self.publico = publico
        self.tecnico = tecnico


def invalidate_provider() -> None:
    _prov_cache["prov"] = None


async def get_provider() -> BaseProvider:
    """El proveedor que SE VA A USAR. Lanza SinCerebro si no hay ninguno vivo.

    Nunca cae a `mock` por su cuenta: el modo demostración solo se usa si lo has
    elegido tú en ⚙. Si hay que cambiar de proveedor porque el tuyo no responde,
    queda ANOTADO en el estado del runtime (no es un cambio invisible)."""
    import time as _t
    now = _t.time()
    if _prov_cache["prov"] is not None and now - _prov_cache["t"] < 30:
        return _prov_cache["prov"]
    wanted = settings.get("llm_provider", "ollama")

    if wanted == "mock":                       # elección explícita, no un apaño
        _prov_cache["prov"] = PROVIDERS["mock"]
        _prov_cache["t"] = now
        return PROVIDERS["mock"]

    prov = PROVIDERS.get(wanted)
    if prov is None:
        raise SinCerebro(
            "El cerebro configurado no existe. Elige uno en ⚙ y lo pruebo al momento.",
            f"proveedor desconocido: {wanted}")

    chosen = None
    desde = ""
    if await prov.available():
        chosen = prov
    else:
        for name in ("ollama", "openai", "anthropic", "gemini", "cloud"):
            if name != wanted and await PROVIDERS[name].available():
                chosen = PROVIDERS[name]
                desde = wanted
                break

    if chosen is None:
        publico = ("Ahora mismo no tengo ningún modelo funcionando, así que no puedo "
                   "darte una respuesta de verdad. Elige un cerebro en ⚙ (o arranca "
                   "Ollama) y lo pruebo al instante.")
        try:                                    # el runtime sabe el porqué exacto
            from backend.core.llm_runtime import status as _rt_status
            if _rt_status().error_public:
                publico = _rt_status().error_public
        except Exception:
            pass
        raise SinCerebro(publico, f"ningún proveedor disponible (pedido: {wanted})")

    if desde:
        try:                                    # cambio de proveedor: queda anotado
            from backend.core.llm_runtime import _STATUS
            _STATUS.fallback_from = desde
        except Exception:
            pass
    _prov_cache["prov"] = chosen
    _prov_cache["t"] = now
    return chosen


async def get_provider_safe() -> BaseProvider | None:
    """Igual que `get_provider()` pero devuelve None en vez de lanzar. Para el
    código que solo quiere saber «¿hay cerebro?» sin gestionar el error."""
    try:
        return await get_provider()
    except SinCerebro:
        return None


def _model_provider(model: str) -> str:
    """Deduce el proveedor por el nombre del modelo (claude-*→anthropic, gpt/o3→openai…)."""
    m = (model or "").lower()
    if any(m.startswith(p) for p in ("claude", "fable", "opus", "sonnet", "haiku", "mythos")):
        return "anthropic"
    if any(m.startswith(p) for p in ("gpt", "o3", "o4", "chatgpt", "chat-latest")):
        return "openai"
    if m.startswith("gemini"):
        return "gemini"
    return ""


async def _chat_with(provider: str, model: str, system: str, user: str, max_tokens: int) -> str:
    """Una generación con un MODELO CONCRETO del proveedor indicado (para el reentreno)."""
    if provider == "anthropic":
        key = settings.secret("anthropic_api_key")
        if not key:
            return ""
        r = await net.client().post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            json={"model": model, "max_tokens": max_tokens, "system": system,
                  "messages": [{"role": "user", "content": user}]}, timeout=120)
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json()["content"]).strip()
    if provider == "openai":
        key = settings.secret("openai_api_key") or settings.secret("cloud_llm_api_key")
        if not key:
            return ""
        base = "https://api.openai.com/v1"
        if not settings.secret("openai_api_key") and settings.secret("cloud_llm_api_key"):
            base = settings.get("cloud_base_url", base).rstrip("/")
        r = await net.client().post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "max_tokens": max_tokens,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]}, timeout=120)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    if provider == "gemini":
        key = settings.secret("gemini_api_key")
        if not key:
            return ""
        r = await net.client().post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": key},
            json={"contents": [{"role": "user", "parts": [{"text": user}]}],
                  "system_instruction": {"parts": [{"text": system}]}}, timeout=120)
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    return ""


async def distill(system: str, user: str, max_tokens: int = 900) -> str:
    """Genera texto para el AUTO-REENTRENAMIENTO con el modelo ELEGIDO por el usuario
    (`retrain_model`). 'auto' (por defecto) usa TU CEREBRO ACTIVO → no consume de más
    (nada de forzar Fable). Un modelo concreto de cualquier LLM se usa si tienes su key.
    '' si solo está el mock o falla."""
    rm = (settings.get("retrain_model", "auto") or "auto").strip()
    if rm and rm.lower() != "auto":
        prov = _model_provider(rm)
        if prov:
            try:
                out = await _chat_with(prov, rm, system, user, max_tokens)
                if out:
                    return out
            except Exception:
                pass                          # si falla el modelo elegido, cae al cerebro activo
    try:
        prov = await get_provider()           # AUTO / fallback: el cerebro que ya usas
        if prov.name == "mock":
            return ""
        out = await prov.chat([{"role": "system", "content": system},
                               {"role": "user", "content": user}])
        return (out or "").strip()
    except Exception:
        return ""


# Nivel de razonamiento (⚙): ajusta cuánto «piensa» el modelo antes de responder.
REASONING = {
    "rapido": "\n\nMODO RÁPIDO: ve al grano, respuestas directas y breves, sin rodeos.",
    "equilibrado": "",
    "profundo": ("\n\nMODO RAZONAMIENTO PROFUNDO: antes de responder, piensa paso a paso "
                 "en tu cabeza — descompón el problema, valora alternativas, verifica datos "
                 "y lógica, y entrega la conclusión ya depurada. Respuestas más "
                 "elaboradas y fundamentadas (pero sin mostrar el proceso de pensamiento)."),
}


DEVIL_INSTRUCTION = """

MODO ABOGADO DEL DIABLO ACTIVO — antes de dar tu respuesta, razónala así (en tu
cabeza, sin mostrar el proceso): cuestiona tus propias suposiciones, construye el
mejor caso EN CONTRA de tu conclusión inicial, verifica datos y lógica, y descarta
lo que no se sostenga. Entrega solo la respuesta final, ya depurada por ese examen.
Si detectas que {operator} parte de un dato o premisa equivocada, corrígelo con
argumentos. Prefiere la verdad útil al halago."""

# Versión LIGERA (nivel «equilibrado»): una sola comprobación, sin encarecer la latencia.
DEVIL_LIGHT = ("\n\nAntes de responder, comprueba rápido que no partes de una premisa "
               "falsa y, si {operator} se basa en un dato equivocado, corrígelo. "
               "Responde directo, sin mostrar el proceso.")


def _build_messages(user_text: str, context: list[dict] | None = None,
                    system: str | None = None) -> list[dict]:
    """Construye los mensajes (system+contexto+usuario) — compartido por la
    respuesta normal y la respuesta en STREAMING."""
    pkey = settings.get("personality", "jarvis")
    pers = PERSONALITIES.get(pkey, PERSONALITIES["jarvis"])
    from .config import assistant_name as _aname, voice_gender as _vg
    _fem = _vg() != "m"                        # género de la VOZ (fem por defecto)
    base = system or SYSTEM_PROMPT.format(
        assistant=_aname(),
        operator=settings.get("operator_name"),
        art=("la" if _fem else "el"),
        refl=("misma" if _fem else "mismo"),
        vozgen=("de mujer (femenina)" if _fem else "de hombre (masculina)"),
        genero=("FEMENINO" if _fem else "MASCULINO"),
        ej=("estoy lista, encantada, conectada" if _fem else "estoy listo, encantado, conectado"),
        personality=pers["prompt"].format(operator=settings.get("operator_name")))
    # FECHA ACTUAL: sin esto el modelo no sabe en qué día vive y no puede resolver
    # «hoy/ayer/mañana». Se inyecta SIEMPRE (aunque venga un system a medida).
    base += (f"\n\nFECHA Y HORA ACTUAL: hoy es {fecha_actual()}. Úsala para interpretar "
             "«hoy», «ayer», «mañana», «esta semana», «este año», etc. Tu conocimiento "
             "tiene fecha de corte, así que para hechos recientes usa la INFORMACIÓN "
             "ACTUAL de la web que te llega en el contexto; si no te llega, dilo y sugiere "
             "«busca en internet <tema>».")
    # RAZONAMIENTO (⚙): SOLO controla cuánto se piensa/extiende (rápido | equilibrado |
    # profundo). El ABOGADO DEL DIABLO **ya NO se mete en la conversación normal** (metía
    # latencia): actúa únicamente cuando Adri lo PIDE con la skill devils_advocate
    # («abogado del diablo: …»). Así el chat responde rápido, y el examen crítico está
    # disponible bajo demanda cuando de verdad lo quieres.
    # ── LA REGLA QUE NO SE SALTA: NO INVENTARSE CIFRAS ───────────────────────
    # 31/07/2026. Le pidieron analizar una cuenta de Instagram abierta en el
    # navegador y devolvió un perfil ENTERO inventado: «1,2M seguidores, 15,4K
    # seguidos, 15,2M interacciones, +2,1% mensual». Los datos reales eran 78.500,
    # 716 y 327. Y al preguntarle por qué se los inventaba, contestó que él busca
    # en internet — sin admitir que se los había inventado.
    #
    # Un asistente que se inventa números es peor que uno que no contesta: con el
    # que no contesta buscas el dato, y con este te lo crees. Va a lo último del
    # prompt a propósito, que es lo que más pesa.
    base += (
        "\n\n═══ REGLA INVIOLABLE: LAS CIFRAS NO SE INVENTAN ═══\n"
        "NUNCA des un número (seguidores, visitas, ventas, precios, fechas, "
        "porcentajes, métricas de nadie) si no te ha llegado en el contexto de una "
        "herramienta o del propio usuario. Ni aproximado, ni «de referencia», ni "
        "«a modo de ejemplo». Cero.\n"
        "Si te preguntan por datos que no tienes, la respuesta es literalmente que "
        "NO los tienes y CÓMO conseguirlos. Ejemplos de lo que SÍ debes decir:\n"
        "  · «No tengo esos datos delante. Para la cuenta de Instagram de alguien: "
        "«analiza la cuenta de instagram de <usuario>».»\n"
        "  · «No puedo ver esa pestaña. Dime «lee la pestaña de <lo que sea>» y la leo.»\n"
        "Si te piden que analices una página o pestaña y NO tienes su contenido en "
        "el contexto, no la describas: di que no la estás viendo. Inventarte lo que "
        "pone es el peor fallo que puedes cometer.\n"
        "Y si te pillan un dato inventado, admítelo directamente: «me lo he "
        "inventado, no tenía el dato». Nunca lo justifiques ni lo disimules.\n")
    # Segunda mitad de la misma regla: tampoco se inventa lo que ES nexus.
    # El 31/07/2026 se inventó que «Núcleo IA» era «una plataforma central para
    # acceder a herramientas de IA». Núcleo IA es una sección del propio HUD.
    base += (
        "\n═══ Y TAMPOCO TE INVENTAS LO QUE ERES ═══\n"
        "nexus es esta aplicación, la que estás ejecutando ahora mismo en el equipo "
        "del usuario. «Núcleo IA», «Content OS», «Reels», «Tablero», «Engram», "
        "«Hermes» y demás son SECCIONES Y PIEZAS DE ESTA APLICACIÓN, no productos "
        "ni plataformas de terceros. Si no sabes qué hace una sección, dilo; no la "
        "describas a ojo.\n"
        "Qué modelo o proveedor tienes puesto es un DATO DE CONFIGURACIÓN, no algo "
        "que se deduzca: si te lo preguntan y no te ha llegado en el contexto, di "
        "que lo mire con «qué modelo de IA estás usando», que eso sí lo lee de la "
        "configuración real.\n")

    base += REASONING.get(settings.get("reasoning_level", "rapido"), "")
    # PERFIL DEL OPERADOR (auto-reentrenamiento): lo destilado de sus interacciones,
    # para responder a su medida. Se inyecta si existe.
    try:
        from . import selflearn
        prof = selflearn.operator_profile()
        if prof:
            base += ("\n\nPERFIL DEL OPERADOR (aprendido de vuestras conversaciones, "
                     "úsalo para atinar con su estilo y sus necesidades):\n" + prof)
    except Exception:
        pass
    messages = [{"role": "system", "content": base}]
    if context:
        messages.extend(context)
    messages.append({"role": "user", "content": user_text})
    return messages


def _anotar_caida(prov: "BaseProvider", exc: Exception, detalle: str) -> None:
    """Un fallo REAL del modelo apaga el «EN USO» del HUD.

    Antes el badge salía de la preferencia guardada, así que seguía diciendo
    «cerebro activo» mientras el chat contestaba que no podía. Un solo sitio
    manda: el runtime."""
    try:
        from backend.core import llm_runtime as rt
        rt._STATUS = rt.LLMRuntimeStatus(
            active=False, verified=False, provider=prov.name,
            model=str(settings.get("ollama_model", "")) if prov.name == "ollama" else "",
            checked_at=__import__("time").time(),
            error_code="fallo_uso", error_public=detalle,
            error_tech=f"{type(exc).__name__}: {exc}")
    except Exception:
        pass


def _respuesta_fallo(prov: "BaseProvider", detalle: str) -> str:
    """Lo que se contesta cuando el modelo falla: la verdad, no un sucedáneo."""
    return ("No he podido responder con el modelo que tengo configurado. "
            + (detalle[0].upper() + detalle[1:] if detalle else "")
            + ("." if detalle and not detalle.endswith(".") else ""))


async def ask_llm(user_text: str, context: list[dict] | None = None,
                  system: str | None = None) -> tuple[str, str]:
    """Devuelve (respuesta, proveedor). Proveedor «ninguno» = NO hay respuesta
    real; nunca se disfraza un texto prefabricado de contestación del modelo."""
    messages = _build_messages(user_text, context, system)
    try:
        prov = await get_provider()
    except SinCerebro as exc:
        return exc.publico, "ninguno"
    try:
        return await prov.chat(messages), prov.name
    except Exception as exc:
        detalle = _explain_error(prov, exc)
        _anotar_caida(prov, exc, detalle)
        return _respuesta_fallo(prov, detalle), "ninguno"


async def ask_llm_stream(user_text: str, context: list[dict] | None = None,
                         system: str | None = None):
    """VOZ FLUIDA: devuelve (generador_asíncrono, proveedor). El generador cede
    la respuesta POR TROZOS según el modelo la escribe (OpenAI streamea de
    verdad; el resto la entrega completa de golpe). Si el streaming falla sin
    haber producido nada, cae a la respuesta completa normal."""
    messages = _build_messages(user_text, context, system)
    try:
        prov = await get_provider()
    except SinCerebro as exc:
        publico = exc.publico

        async def _sin():
            yield publico

        return _sin(), "ninguno"

    async def _gen():
        got = False
        try:
            async for piece in prov.chat_stream(messages):
                got = True
                yield piece
        except Exception as exc:                           # noqa: BLE001
            if got:
                return                 # se cortó a mitad: lo dicho, dicho está
            try:
                yield await prov.chat(messages)
            except Exception:
                detalle = _explain_error(prov, exc)
                _anotar_caida(prov, exc, detalle)
                yield _respuesta_fallo(prov, detalle)

    return _gen(), prov.name


async def interpret_command(user_text: str, catalog: str, examples: str = "",
                            feedback: str = "", recent_context: str = "") -> str:
    """Enrutador INTELIGENTE de respaldo. Si ninguna skill casó por regex, el modelo
    decide si la petición es una ORDEN que encaja con alguna capacidad y la reescribe
    como una orden canónica (que el router SÍ reconocerá). Devuelve '' si es charla.

    Así nexus entiende «oye, ponme algo de Quevedo en el Spotify ese» → «pon Quevedo
    en spotify», sin tener que memorizar cada forma de pedirlo. Los `examples` son
    órdenes que ya funcionaron (aprendizaje continuo) y afinan el estilo del usuario.
    `recent_context`: las últimas vueltas de la conversación (ver brain._recent_context),
    para que una frase AMBIGUA o de seguimiento («¿está todo arrancado?», «vale», «ya
    está») se interprete SEGÚN EL TEMA que se estaba hablando, no a ciegas por
    coincidencia de palabras sueltas con el catálogo (esto delegaba en Hermes frases que
    no tenían nada que ver, solo porque el catálogo de Hermes menciona "arrancado")."""
    prov = await get_provider()
    if prov.name == "mock":
        return ""                     # sin LLM real no hay interpretación fiable
    from .config import assistant_name as _aname
    sys = (
        f"Eres el ENRUTADOR de {_aname()}. Recibes una petición del usuario y una lista de "
        "capacidades (skills) con sus intents. Si la petición es una ORDEN que encaja con "
        "alguna capacidad, reescríbela como UNA sola orden canónica en español, imperativa "
        "y directa, que dispare esa capacidad (ej.: 'pon <canción> en spotify', "
        "'pon algo al azar', 'pon algo de <género/artista>', 'abre <app>', "
        "'abre la web <sitio>', 'qué tiempo hace en <ciudad>', 'crea un archivo llamado "
        "<x> en el escritorio', 'lee mis correos', 'qué tengo en la agenda'). "
        "Conserva los datos concretos (nombres, "
        "ciudades, canciones, apps). Si NO es una acción (charla, pregunta general, saludo, "
        "opinión, confirmación o seguimiento sin orden clara), responde EXACTAMENTE 'CHARLA'. "
        "Si ES una acción pero NINGUNA "
        "capacidad de la lista encaja (convertir archivos, tareas web complejas, "
        "cosas fuera del catálogo), responde 'HERMES: <el encargo en una frase>' — "
        "Hermes es el subagente todoterreno. EN CASO DE DUDA entre orden y charla, "
        "ELIGE LA ORDEN: el usuario prefiere que se ejecute a que se le pida la frase "
        "exacta. PERO si la frase es corta y ambigua Y hay CONTEXTO RECIENTE, interprétala "
        "SIEMPRE a la luz de ese contexto (de qué se estaba hablando) antes que por "
        "coincidencia de palabras sueltas con el catálogo — nunca inventes una capacidad que "
        "no tiene relación real con el tema de la conversación. Responde SOLO con la orden, "
        "con 'HERMES: ...' o con 'CHARLA', sin comillas ni explicaciones.\n\nCAPACIDADES:\n"
        + catalog)
    if recent_context:
        sys += ("\n\nCONTEXTO RECIENTE (las últimas frases de esta conversación — úsalo SOLO "
                "para entender de qué habla el usuario ahora, no lo repitas ni lo conviertas "
                "en orden):\n" + recent_context)
    if examples:
        sys += ("\n\nEJEMPLOS APRENDIDOS de cómo habla ESTE usuario (frase → orden que "
                "funcionó). Imita su estilo y vocabulario:\n" + examples)
    msgs = [{"role": "system", "content": sys},
            {"role": "user", "content": user_text}]
    if feedback:
        # 2º intento: la orden anterior no casó con ningún patrón → reformular
        msgs.append({"role": "assistant", "content": feedback.split("|", 1)[0]})
        msgs.append({"role": "user", "content":
                     "Esa orden NO ha casado con ningún patrón del router. Reformúlala "
                     "MÁS CANÓNICA y simple (imperativo + objeto, como los ejemplos del "
                     "sistema), conservando los datos concretos. Si de verdad no es una "
                     "acción, responde CHARLA."})
    try:
        out = await prov.chat(msgs)
    except Exception:
        return ""
    line = (out or "").strip().splitlines()[0].strip().strip('"').strip("«»").strip()
    if not line or line.upper().startswith("CHARLA"):
        return ""
    return line if len(line) <= 160 else ""   # salvaguarda anti-alucinación


async def plan_action(user_text, catalog, examples="", recent_context=""):
    """PLANIFICADOR: el modelo de razonamiento decide QUE skill+intent ejecuta la
    peticion y EXTRAE los argumentos de la frase — sin exigir la frase exacta.
    Devuelve dict {skill, intent, args} o None (charla/pregunta general).
    `recent_context`: últimas vueltas de la conversación, para que una frase corta y
    ambigua («¿está todo arrancado?», «vale», «ya está») se entienda por el TEMA que
    se venía hablando y no por coincidencia de palabras sueltas con el catálogo."""
    import json as _json
    import re as _re
    prov = await get_provider()
    if prov.name == "mock":
        return None
    from .config import assistant_name as _aname
    sys = (
        f"Eres el PLANIFICADOR de {_aname()} y un MODELO DE RAZONAMIENTO. Recibes una "
        "peticion del usuario y un CATALOGO de skills (cada intent con sus argumentos). "
        "Entiende la INTENCION aunque la frase NO sea literal ni canonica, y decide que "
        "intent la ejecuta, extrayendo los argumentos de la frase (conserva nombres, "
        "ciudades, canciones, numeros tal cual los dijo). NUNCA pidas la frase exacta: tu "
        "trabajo es DEDUCIRLA. Si la frase es corta o ambigua, usa el CONTEXTO RECIENTE (si "
        "lo hay) para saber de que tema real habla el usuario — nunca elijas una skill solo "
        "porque su descripcion comparte una palabra suelta con la frase, sin relacion de "
        "tema real. Responde SOLO un JSON: "
        '{"skill":"<carpeta>","intent":"<intent>","args":{"<arg>":"<valor>"}}'
        " o exactamente {\"skill\":null} si es charla, saludo, pregunta general u opinion. "
        "REGLA HERMES (subagente agentico): si la peticion exige trabajo agentico real "
        "(navegar/automatizar el navegador, investigar a fondo varias fuentes, scrapear, "
        "comparar precios, vigilar webs, rellenar formularios, resumir webs/noticias "
        "concretas) y ningun intent local encaja mejor, responde "
        '{"skill":"hermes","intent":"hermes","args":{"orden":"<el encargo completo>"}}'
        " — el usuario NUNCA tiene que nombrar a hermes: lo decides TU. "
        "Sin texto fuera del JSON.\n\nCATALOGO:\n" + catalog)
    if recent_context:
        sys += ("\n\nCONTEXTO RECIENTE (ultimas frases de esta conversacion — solo para "
                "entender el tema, no lo repitas ni lo conviertas en accion):\n"
                + recent_context)
    if examples:
        sys += "\n\nEJEMPLOS del estilo de ESTE usuario (frase -> orden que funciono):\n" + examples
    try:
        out = await prov.chat([{"role": "system", "content": sys},
                               {"role": "user", "content": user_text}])
    except Exception:
        return None
    m = _re.search(r"\{.*\}", out or "", _re.S)
    if not m:
        return None
    try:
        d = _json.loads(m.group(0))
    except Exception:
        return None
    if not isinstance(d, dict) or not d.get("skill"):
        return None
    d.setdefault("args", {})
    if not isinstance(d["args"], dict):
        d["args"] = {}
    return d


def _ollama_instalados() -> list[str]:
    """Los modelos que Ollama tiene AHORA MISMO. [] si no responde."""
    try:
        url = settings.get("ollama_url", "http://localhost:11434").rstrip("/")
        r = httpx.get(f"{url}/api/tags", timeout=2.5)
        return [m.get("name", "") for m in (r.json().get("models") or []) if m.get("name")]
    except Exception:
        return []


def _diagnostico_ollama_404(model: str, cuerpo: str = "") -> str:
    """Un 404 de Ollama NO significa siempre «ese modelo no existe».

    Bug reportado por Adri (25/07/2026): nexus le decía «el modelo qwen3:8b no
    está en Ollama» teniéndolo instalado. Se daba por hecho sin mirarlo. Ahora
    se COMPRUEBA contra la lista real antes de acusar a nadie."""
    # El propio Ollama dice en el cuerpo si el problema es el modelo o la ruta.
    if cuerpo and "model" not in cuerpo.lower():
        return ("Ollama ha respondido 404 a la ruta que uso, no por culpa del modelo. "
                "Ya reintento por la vía antigua automáticamente; si sigue fallando, "
                "actualiza Ollama")
    instalados = _ollama_instalados()
    if not instalados:
        # Sin la dirección a propósito: la voz pública borra la frase entera si
        # menciona máquinas o puertos, y con ella se perdía la instrucción útil.
        return ("Ollama no está respondiendo. Ábrelo (o ejecuta «ollama serve») y vuelvo "
                "a usarlo — los modelos que ves en ⚙ están en tu disco, pero sin Ollama "
                "en marcha no puedo cargarlos")
    if model in instalados:
        return (f"«{model}» SÍ está instalado en Ollama, así que el fallo no es ese: "
                "la petición ha devuelto 404, que suele ser una ruta o una versión de "
                "Ollama que no encaja. Mira el registro para el detalle")
    # ¿está el modelo pero con otra etiqueta? («qwen3» configurado, «qwen3:8b» instalado)
    base = (model or "").split(":")[0].lower()
    parecidos = [m for m in instalados if m.split(":")[0].lower() == base]
    if parecidos:
        return (f"«{model}» no existe tal cual, pero tienes {', '.join(parecidos[:3])}. "
                f"Pon la etiqueta exacta en ⚙ (por ejemplo «{parecidos[0]}»)")
    return (f"el modelo «{model}» no está en Ollama — `ollama pull {model}` o elige otro "
            f"en ⚙ (tienes: {', '.join(instalados[:5])})")


def _explain_error(prov: BaseProvider, exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 404 and prov.name == "ollama":
            # el modelo REAL de la petición, no el que hubiera en ⚙ hace un rato
            model = (getattr(prov, "model", "") or settings.get("ollama_model") or "")
            cuerpo = ""
            try:
                cuerpo = exc.response.text[:300]
            except Exception:
                pass
            return _diagnostico_ollama_404(model, cuerpo)
        if code in (401, 403):
            return f"API key de {prov.name} inválida o sin permisos (revisa ⚙)"
        if code == 429:
            return f"límite de peticiones de {prov.name} alcanzado — espera un poco"
        return f"HTTP {code} de {prov.name}"
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return "no hay conexión con el servidor LLM (¿Ollama arrancado? ¿internet?)"
    if isinstance(exc, httpx.ReadTimeout):
        return "timeout — modelo lento o muy grande para tu equipo"
    return f"{type(exc).__name__}: {exc}"


# ----------------------------------------------------------------------
#  Detección de modelos LOCALES instalados
# ----------------------------------------------------------------------
def _scan_ollama_manifests(root: Path, seen: set, found: list) -> None:
    """Recorre manifests/registry.ollama.ai/<namespace>/<modelo>/<tag>.
    Soporta ubicaciones PERSONALIZADAS (OLLAMA_MODELS) y namespaces no-library
    (p.ej. tu 'sorc/qwen3.5-claude-4.6-opus-q4')."""
    # 'root' puede ser la carpeta OLLAMA_MODELS o su subcarpeta manifests
    candidates = [root / "manifests" / "registry.ollama.ai", root / "registry.ollama.ai", root]
    reg = next((c for c in candidates if c.is_dir()), None)
    if not reg:
        return
    for ns in reg.iterdir():                      # namespaces: library, sorc, ...
        if not ns.is_dir():
            continue
        for model_dir in ns.iterdir():
            if not model_dir.is_dir():
                continue
            for tag in model_dir.iterdir():
                if not tag.is_file():
                    continue
                base = model_dir.name
                name = base if tag.name == "latest" else f"{base}:{tag.name}"
                # ollama pull usa el nombre con namespace si no es library
                pull = name if ns.name == "library" else f"{ns.name}/{name}"
                if pull not in seen:
                    seen.add(pull)
                    gb = tag.stat().st_size / 1e9
                    found.append({"name": pull, "source": f"ollama ({ns.name})",
                                  "detail": f"manifest {gb*1000:.0f} KB" if gb < 0.01 else ""})


async def scan_local_models() -> list[dict]:
    """Modelos locales disponibles: Ollama (API + carpetas, incl. personalizadas)
    y LM Studio (GGUF). Las rutas extra se configuran en ⚙ (model_scan_paths)."""
    found: list[dict] = []
    seen: set[str] = set()

    # 1) Ollama vivo → lista exacta (respeta OLLAMA_MODELS automáticamente)
    try:
        r = await net.client().get(f"{settings.get('ollama_url').rstrip('/')}/api/tags",
                                   timeout=3)
        for m in r.json().get("models", []):
            name = m["name"]
            if name not in seen:
                seen.add(name)
                gb = m.get("size", 0) / 1e9
                found.append({"name": name, "source": "ollama (activo)",
                              "detail": f"{gb:.1f} GB" if gb else ""})
    except Exception:
        pass

    # 2) Carpetas de manifests — por defecto + OLLAMA_MODELS + rutas del usuario
    home = Path.home()
    roots = [home / ".ollama" / "models"]
    env_models = os.environ.get("OLLAMA_MODELS", "").strip()
    if env_models:
        roots.append(Path(env_models))
    extra = settings.get("model_scan_paths", []) or []
    if isinstance(extra, str):
        extra = [p.strip() for p in extra.replace(";", ",").split(",") if p.strip()]
    roots += [Path(p) for p in extra]
    for root in roots:
        try:
            if root.exists():
                _scan_ollama_manifests(root, seen, found)
        except Exception:
            pass

    # 3) LM Studio y carpetas GGUF (incluidas las rutas extra del usuario)
    lm_dirs = [home / ".lmstudio" / "models",
               home / ".cache" / "lm-studio" / "models",
               Path(os.environ.get("LOCALAPPDATA", "")) / "LMStudio" / "models"]
    lm_dirs += [Path(p) for p in extra]
    for root in lm_dirs:
        try:
            if root.is_dir():
                for gguf in root.rglob("*.gguf"):
                    name = gguf.stem
                    if name not in seen:
                        seen.add(name)
                        found.append({"name": name, "source": "lm-studio (gguf)",
                                      "detail": f"{gguf.stat().st_size/1e9:.1f} GB"})
        except Exception:
            pass

    return found
