"""
nexus — TTS (texto → voz) v3: voces REALES y seleccionables.

Motores:
  * edge       — Edge-TTS: voces neuronales de Microsoft GRATUITAS (recomendado;
                 varias voces en español, suenan de verdad). pip install edge-tts
  * elevenlabs — premium con API key
  * local      — SAPI de Windows vía pyttsx3 (enumera las voces instaladas reales)
  * auto       — edge → elevenlabs → local (lo primero que funcione)

El HUD pide /api/voices y pinta el selector con TODAS las voces disponibles;
el cambio aplica al momento (settings tts_engine / tts_voice).
"""
from __future__ import annotations

import asyncio
import contextvars
import time
import re
import tempfile
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager


from ..comun import net
from ..comun.config import settings
from ..comun.events import bus

try:
    import pyttsx3
    HAS_PYTTSX3 = True
except Exception:
    HAS_PYTTSX3 = False

try:
    import edge_tts
    HAS_EDGE = True
except ImportError:
    HAS_EDGE = False

# Voces gratuitas Edge-TTS en español (neuronales, calidad alta)
EDGE_VOICES = {
    "Álvaro (España)": "es-ES-AlvaroNeural",
    "Elvira (España)": "es-ES-ElviraNeural",
    "Dalia (México)": "es-MX-DaliaNeural",
    "Jorge (México)": "es-MX-JorgeNeural",
    "Tomás (Argentina)": "es-AR-TomasNeural",
    "Elena (Argentina)": "es-AR-ElenaNeural",
    "Salomé (Colombia)": "es-CO-SalomeNeural",
}

ELEVEN_VOICES = {
    "Rachel": "21m00Tcm4TlvDq8ikWAM",
    "Adam": "pNInz6obpgDQGcFmaJgB",
    "Antoni": "ErXwobaYiN019PkySvjV",
    "Bella": "EXAVITQu4vr4xnSDxMaL",
}


from ..comun.config import DATA_DIR

TTS_DIR = DATA_DIR / "tts"
FIRST_FLUSH_CHARS = 72
FIRST_FLUSH_MS = 700
_turn_context: contextvars.ContextVar[object | None] = contextvars.ContextVar(
    "nexus_tts_turn", default=None
)


@contextmanager
def bind_turn(turn) -> Iterator[object]:
    """Bind assistant speech in this task to one authoritative voice turn."""
    token = _turn_context.set(turn)
    try:
        yield turn
    finally:
        _turn_context.reset(token)


def current_turn():
    return _turn_context.get()


def _owns_turn(turn) -> bool:
    if turn is None:
        return True
    try:
        return bool(turn.is_current())
    except Exception:
        return False


def _mark_turn(turn, stage: str) -> None:
    if turn is None:
        return
    try:
        turn.mark(stage)
    except Exception:
        pass


def _pron(text: str) -> str:
    """Corrige cómo la voz PRONUNCIA el nombre del sistema. Si se ha definido
    `assistant_pron` distinto del nombre, sustituye el nombre por esa grafía en el
    texto; si no, se lee tal cual («nexus» → «nexus»)."""
    import re
    try:
        from ..comun.config import assistant_name, assistant_pron
        name, pron = assistant_name(), assistant_pron()
    except Exception:
        name, pron = "nexus", "nexus"
    if pron and pron.lower() != name.lower():
        return re.sub(rf"\b{re.escape(name)}\b", pron, text, flags=re.IGNORECASE)
    return text


def _speak_norm(text: str) -> str:
    """Normaliza para que la voz suene NATURAL, no en abreviaturas ni símbolos:
    «máx 33°C / mín 25°C» → «máxima 33 grados y mínima 25 grados». El género
    (máxima/máximo, mínima/mínimo) se decide por el contexto (temperatura=femenino)."""
    import re
    t = text or ""
    t = re.sub(r"\s*°\s*C\b|\s*ºC\b", " grados", t)              # 33°C → 33 grados
    t = re.sub(r"\s*°\b", " grados", t)                          # 33° → 33 grados
    fem = bool(re.search(r"grados|temperatura|m[aá]xima|m[ií]nima", t, re.IGNORECASE))
    mx, mn = ("máxima", "mínima") if fem else ("máximo", "mínimo")
    # abreviaturas máx./mín. (no tocar «máxima/mínima» que ya están completas)
    t = re.sub(r"\bm[aá]x(?![a-záéíóúü])\.?", mx, t, flags=re.IGNORECASE)
    t = re.sub(r"\bm[ií]n(?![a-záéíóúü])\.?", mn, t, flags=re.IGNORECASE)
    t = re.sub(r"(\d)\s*/\s*(?=\d|máx|mín|m[aá]x|m[ií]n)", r"\1 y ", t, flags=re.IGNORECASE)
    t = t.replace(" / ", " y ")                                  # barras sueltas → «y»
    # RUTAS: JAMÁS se leen enteras (orden de Adri). Solo lo que ES una ruta
    # (unidad C:\, barra inicial, ~, o fichero.ext con carpetas) se reduce a su
    # ÚLTIMO componente sin extensión; las LISTAS (HUD/APK/Telegram) no se tocan.
    def _ruta_final(m):
        last = re.split(r"[\\/]+", m.group(0).strip("\\/"))[-1]
        return re.sub(r"\.\w{1,5}$", "", last) or last
    t = re.sub(r"\b[A-Za-z]:[\\/][\w.~()\\/-]+", _ruta_final, t)   # C:\... con unidad
    t = re.sub(r"(?:^|(?<=[\s(«\"']))(?:[\\/]{1,2}|~[\\/])[\w.~()\\/-]+",
               _ruta_final, t)                                   # /absolutas, ~/ y \\server
    t = re.sub(r"\b[\w~()-]+(?:[\\/][\w.~()-]+)*[\\/][\w~()-]+\.\w{1,5}\b",
               _ruta_final, t)                                   # relativas tipo data/x/y.log
    # «/» restantes entre palabras = SEPARADOR de elementos → pausa con coma
    # («HUD/APK/Telegram» se dice «HUD, APK, Telegram», nunca «barra»).
    t = re.sub(r"(?<=[\wáéíóúñÁÉÍÓÚÑ])\s*/\s*(?=[\wáéíóúñÁÉÍÓÚÑ¿¡])", ", ", t)
    # «_» y «-» dentro de palabras = espacios, no se pronuncian
    # (wake_word → «wake word»; edge-tts → «edge tts»; 2026-07 se conserva).
    t = re.sub(r"(?<=\w)_(?=\w)", " ", t)
    t = re.sub(r"(?<=[A-Za-zÁÉÍÓÚáéíóúñÑ])-(?=[A-Za-zÁÉÍÓÚáéíóúñÑ])", " ", t)
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()


# Emojis y símbolos decorativos (◈ ▸ ● ✔ ✕ 🔎 📱 😈 …) → NUNCA se leen en voz.
# Cubre emoji del plano suplementario + flechas/técnicos/geométricos/dingbats del BMP.
# NO toca los signos españoles (¿ ¡ « » — … ' ') que están en otros rangos.
_EMOJI_RX = re.compile(
    "[\U00002190-\U000027BF\U00002B00-\U00002BFF\U0000FE00-\U0000FE0F"
    "\U0000200D\U000020E3\U0000221E\U000024C2\U00003030\U0000303D"
    "\U0001F000-\U0001FAFF]+", flags=re.UNICODE)


def _strip_symbols(text: str) -> str:
    """Quita emojis y símbolos decorativos para que la voz NUNCA los lea."""
    t = _EMOJI_RX.sub(" ", text or "")
    return re.sub(r"[ \t]+", " ", t).strip()


def _strip_md(text: str) -> str:
    """Quita el markdown para que la voz NO lea «asterisco asterisco» ni las
    viñetas. Se leerá el contenido concreto, no los símbolos de formato."""
    import re
    t = text or ""
    t = re.sub(r"```.*?```", " ", t, flags=re.DOTALL)     # bloques de código
    t = re.sub(r"`([^`]*)`", r"\1", t)                    # código en línea
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)              # **negrita**
    t = re.sub(r"\*([^*]+)\*", r"\1", t)                  # *cursiva*
    t = re.sub(r"__([^_]+)__", r"\1", t)                  # __negrita__
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)        # [texto](enlace) → texto
    t = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", t)           # # encabezados
    t = re.sub(r"(?m)^\s*[-*•]\s+", "", t)                # viñetas
    t = re.sub(r"(?m)^\s*\d+\.\s+", "", t)                # listas numeradas
    t = t.replace("*", "").replace("`", "").replace("#", "").replace("•", "")
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()


def _serve_audio(data: bytes, ext: str = "mp3") -> str:
    """Guarda el audio y devuelve una URL local que el HUD reproduce EN LA APP."""
    import uuid
    TTS_DIR.mkdir(parents=True, exist_ok=True)
    # limpia audios viejos (deja los últimos 24 — una respuesta troceada en frases
    # puede generar varios ficheros que aún se están reproduciendo en cola)
    olds = sorted(TTS_DIR.glob("*.*"), key=lambda p: p.stat().st_mtime)
    for p in olds[:-24]:
        p.unlink(missing_ok=True)
    name = f"{uuid.uuid4().hex[:10]}.{ext}"
    (TTS_DIR / name).write_bytes(data)
    return f"/api/tts_audio/{name}"


_pyttsx3_engine = None


def _local_wav_bytes(text):
    """Genera un WAV con la voz LOCAL (SAPI/pyttsx3) y devuelve sus bytes. Respaldo
    para que el MOVIL hable con la misma voz del PC cuando no hay edge-tts."""
    if not HAS_PYTTSX3 or not text:
        return None
    import os
    import tempfile
    try:
        eng = pyttsx3.init()
    except Exception:
        return None
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        wanted = settings.get("tts_voice", "")
        try:
            for v in eng.getProperty("voices"):
                if wanted and wanted.lower() in (v.name or "").lower():
                    eng.setProperty("voice", v.id)
                    break
        except Exception:
            pass
        try:
            eng.setProperty("rate", 175)
        except Exception:
            pass
        eng.save_to_file(text, path)
        eng.runAndWait()
        data = b""
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except Exception:
            data = b""
        return data or None
    except Exception:
        return None
    finally:
        try:
            eng.stop()
        except Exception:
            pass
        try:
            os.remove(path)
        except OSError:
            pass


def _local_engine():
    """Motor SAPI cacheado: pyttsx3.init() es LENTO en Windows y se llamaba en cada
    voz/consulta. Se crea una vez y se reutiliza."""
    global _pyttsx3_engine
    if not HAS_PYTTSX3:
        return None
    if _pyttsx3_engine is None:
        try:
            _pyttsx3_engine = pyttsx3.init()
        except Exception:
            _pyttsx3_engine = None
    return _pyttsx3_engine


def local_voices() -> list[str]:
    """Voces SAPI reales instaladas, sin duplicados y priorizando español."""
    engine = _local_engine()
    if engine is None:
        return []
    try:
        seen, out = set(), []
        for v in engine.getProperty("voices"):
            name = v.name.strip()
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            # prioriza español al frente
            es = "spanish" in (v.id + name).lower() or "español" in name.lower() or \
                 any(t and "es" in str(t).lower()[:3] for t in (getattr(v, "languages", []) or []))
            out.append((0 if es else 1, name))
        return [n for _, n in sorted(out)]
    except Exception:
        return []


async def _edge_bytes(text: str) -> bytes | None:
    """Genera el MP3 con Edge-TTS y devuelve los bytes (o None). Sin emitir nada."""
    if not HAS_EDGE:
        return None
    voice = EDGE_VOICES.get(settings.get("tts_voice"),
                            settings.get("tts_voice") if str(
                                settings.get("tts_voice", "")).endswith("Neural")
                            else "es-ES-AlvaroNeural")
    try:
        chunks = bytearray()
        async for c in edge_tts.Communicate(text, voice).stream():
            if c["type"] == "audio":
                chunks += c["data"]
        return bytes(chunks) or None
    except Exception as exc:
        await bus.emit("log", {"level": "warn", "msg": f"Edge-TTS falló: {exc}"})
        return None


async def _eleven_bytes(text: str) -> bytes | None:
    key = settings.elevenlabs_key
    if not key:
        return None
    voice = ELEVEN_VOICES.get(settings.get("tts_voice"), ELEVEN_VOICES["Rachel"])
    try:
        r = await net.client().post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
            headers={"xi-api-key": key},
            json={"text": text, "model_id": "eleven_multilingual_v2"}, timeout=30)
        r.raise_for_status()
        return r.content
    except Exception as exc:
        await bus.emit("log", {"level": "warn", "msg": f"ElevenLabs falló: {exc}"})
        return None


async def synthesize(text: str) -> str | None:
    """Genera audio TTS y devuelve su URL local SIN emitir al bus. Sirve para que un
    cliente concreto (el MÓVIL) reproduzca la voz ÉL SOLO, sin eco en el PC. Usa la
    MISMA voz/normalización que speak(); solo motores con archivo (edge/elevenlabs),
    porque el SAPI local suena en el PC y no vale para el móvil."""
    mode = settings.get("tts_engine", "auto")
    if mode == "off" or not text:
        return None
    text = _speak_norm(_strip_symbols(_strip_md(_pron(text))))
    if not text:
        return None
    _remember_spoken(text)                 # el móvil también habla: su eco también cuenta
    if mode in ("auto", "edge"):
        data = await _edge_bytes(text)
        if data:
            return _serve_audio(data, "mp3")
    if mode in ("auto", "elevenlabs"):
        data = await _eleven_bytes(text)
        if data:
            return _serve_audio(data, "mp3")
    # RESPALDO MOVIL: sin edge/eleven -> WAV con la voz LOCAL (SAPI), misma voz del PC.
    if mode in ("auto", "local") and HAS_PYTTSX3:
        import asyncio as _a
        data = await _a.get_running_loop().run_in_executor(None, _local_wav_bytes, text)
        if data:
            await bus.emit("log", {"level": "info",
                                   "msg": "\U0001F50A Voz del movil generada con voz local (SAPI/WAV)."})
            return _serve_audio(data, "wav")
    await bus.emit("log", {"level": "warn", "msg":
        "\U0001F507 /api/tts_say sin motor de fichero (ni edge/eleven/SAPI-WAV): "
        "instala edge-tts para la voz del movil."})
    return None


def _speak_local_sync(text: str) -> bool:
    engine = _local_engine()
    if engine is None:
        return False
    try:
        wanted = settings.get("tts_voice", "")
        for v in engine.getProperty("voices"):
            if wanted and wanted.lower() in v.name.lower():
                engine.setProperty("voice", v.id)
                break
        engine.setProperty("rate", 175)
        engine.say(text)
        engine.runAndWait()
        return True
    except Exception:
        return False


def _split_sentences(text: str, maxlen: int = 260) -> list[str]:
    """Trocea en frases para hablar CASI AL INSTANTE. La 1ª frase va SOLA (arranque
    rápido: suena en ~0,5 s mientras se generan las demás); el resto se juntan hasta
    ~maxlen para que suene FLUIDO (menos trozos = menos pausas robóticas al encadenar).
    Corta SOLO por final de frase (. ! ? …) y saltos de línea — NUNCA por ; ni : , que
    rompen a media frase y suenan entrecortados."""
    sents = [s.strip() for s in re.split(r"(?<=[.!?…])\s+|\n+", (text or "").strip()) if s.strip()]
    if not sents:
        return [text]
    out = [sents[0]]                 # 1ª frase sola → empieza a hablar ya
    cur = ""
    for p in sents[1:]:
        if not cur:
            cur = p
        elif len(cur) + 1 + len(p) <= maxlen:
            cur += " " + p
        else:
            out.append(cur)
            cur = p
    if cur:
        out.append(cur)
    return out


def _estimate_secs(text: str) -> float:
    """Cuánto DURA (en segundos) decir un texto con voz neuronal en español
    (~14 caracteres/segundo). El MICRO ABIERTO lo usa para NO volver a escuchar
    mientras nexus todavía suena: si se re-armara antes, el micro calibraría el
    ruido con la propia voz de nexus y no te oiría justo al terminar de responder."""
    n = len(text or "")
    return max(0.5, n / 14.0)


_SPOKEN: list = []          # [(ts, texto)] últimas locuciones — para el filtro ANTI-ECO


def _remember_spoken(say: str) -> None:
    """Apunta lo que nexus acaba de DECIR: si el micro lo capta y whisper lo
    transcribe, el cerebro lo reconoce como ECO y no lo trata como orden
    (así se rompe el bucle «se oye a sí mismo y se responde sin parar»)."""
    import time as _t
    if say and say.strip():
        _SPOKEN.append((_t.time(), say.strip()))
        del _SPOKEN[:-8]


def recent_spoken(window: float = 45.0) -> list[str]:
    """Lo dicho por nexus en los últimos `window` segundos."""
    import time as _t
    now = _t.time()
    return [txt for ts, txt in _SPOKEN if now - ts <= window]


# ── v23 (T7): EL TTS SOLO REPRODUCE RESPUESTAS DE nexus ───────────────────────
# Queja de Adri: escribía por el chat y nexus le LEÍA EN VOZ ALTA su propio texto.
# Aquí se cierra por diseño: speak() solo acepta rol 'assistant', y además se
# niega a repetir lo que el operador acaba de escribir o dictar.
_user_recent: list = []          # [(ts, texto normalizado)] de lo que dijo/escribió Adri


def note_user_text(text: str) -> None:
    """El brain apunta aquí CADA entrada del operador (tecleada o transcrita)."""
    t = _norm_user(text)
    if not t:
        return
    _user_recent.append((time.time(), t))
    del _user_recent[:-12]


def _norm_user(text: str) -> str:
    import unicodedata as _u
    t = _u.normalize("NFKD", (text or "").lower()).encode("ascii", "ignore").decode()
    return " ".join("".join(c if c.isalnum() or c.isspace() else " " for c in t).split())


def is_user_echo(text: str, window: float = 90.0) -> bool:
    """¿Esto es lo que ACABA de escribir/decir el operador? Entonces no se dice."""
    t = _norm_user(text)
    if not t or len(t) < 4:
        return False
    ahora = time.time()
    for ts, prev in _user_recent:
        if ahora - ts > window or not prev:
            continue
        if t == prev or (len(prev) >= 8 and (t.startswith(prev) or prev.startswith(t))):
            return True
    return False


async def speak(text: str, role: str = "assistant") -> float:
    """Habla el texto. Devuelve los SEGUNDOS de audio que AÚN quedan sonando cuando
    esta función retorna (el HUD reproduce en cola, así que al volver aquí todavía
    puede estar hablando). El micro abierto espera ese margen antes de re-escuchar.
    Devuelve 0.0 si no sonó nada, o si el motor local (SAPI) ya bloqueó hasta el fin.

    v23 (T7): `role` DEBE ser 'assistant'. Ni el texto tecleado por el operador ni
    la transcripción de su voz se reproducen jamás."""
    mode = settings.get("tts_engine", "auto")
    if mode == "off" or not text:
        return 0.0
    if not settings.get("tts_enabled", True):
        return 0.0
    if role != "assistant":
        await bus.emit("log", {"level": "warn",
                               "msg": f"🔇 TTS rechazado: solo hablo respuestas mías "
                                      f"(llegó rol '{role}')"})
        return 0.0
    if is_user_echo(text):
        await bus.emit("log", {"level": "info",
                               "msg": "🔇 No leo en voz alta lo que acabas de escribir."})
        return 0.0
    text = _speak_norm(_strip_symbols(_strip_md(_pron(text))))   # sin emojis/markdown, «máxima…y mínima…»
    if not text:
        return 0.0
    turn = current_turn()
    if turn is not None:
        async def _one_piece():
            yield text

        _, remaining = await speak_stream(_one_piece(), turn=turn)
        return remaining
    _remember_spoken(text)
    await bus.emit("state", "speaking")
    loop = asyncio.get_running_loop()
    # VOZ INMEDIATA: partir en frases y emitir el audio de CADA UNA en cuanto está lista
    # (la 1ª suena mientras se generan las siguientes → no espera al MP3 entero). El HUD
    # las reproduce en cola sin cortes. El SAPI local no da fichero → se habla entero.
    spoke = False
    total_secs = 0.0
    t0 = None
    if mode in ("auto", "edge", "elevenlabs"):
        chunks = _split_sentences(text)
        for i, ch in enumerate(chunks):
            data = None
            if mode in ("auto", "edge"):
                data = await _edge_bytes(ch)
            if not data and mode in ("auto", "elevenlabs"):
                data = await _eleven_bytes(ch)
            if data:
                url = _serve_audio(data, "mp3")
                if t0 is None:
                    t0 = loop.time()                 # el HUD arranca la reproducción aquí
                total_secs += _estimate_secs(ch)
                await bus.emit("audio", {"url": url, "seq": i, "last": i == len(chunks) - 1})
                spoke = True
    if not spoke and mode in ("auto", "local"):
        # SAPI local: runAndWait() BLOQUEA hasta terminar de hablar → al volver ya no
        # suena nada, así que no hay que esperar margen alguno.
        spoke = await loop.run_in_executor(None, _speak_local_sync, text)
        await bus.emit("state", "idle")
        return 0.0
    if not spoke:
        await bus.emit("log", {"level": "warn",
                               "msg": "TTS sin motor disponible (pip install edge-tts "
                                      "para voces gratis, o pyttsx3, o key de ElevenLabs)"})
    await bus.emit("state", "idle")
    if t0 is None:
        return 0.0
    # Lo que YA se reprodujo mientras se generaban las frases siguientes no hay que
    # esperarlo: solo lo que resta de sonar.
    return max(0.0, total_secs - (loop.time() - t0))


async def speak_stream(
    pieces,
    *,
    turn=None,
    first_flush_chars: int | None = None,
    first_flush_ms: int | None = None,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> tuple[str, float]:
    """VOZ MIENTRAS EL MODELO ESCRIBE (estilo app de Claude): consume un generador
    asíncrono de trozos de texto, corta por FRASES y emite el audio de cada frase
    en cuanto está lista — el HUD las reproduce EN COLA, sin cortes. La 1ª frase
    suena en ~1 s aunque la respuesta sea larga. Devuelve (texto_completo,
    segundos_que_quedan_sonando). Sin motor de archivo → habla todo al final (SAPI)."""
    turn = current_turn() if turn is None else turn
    mode = settings.get("tts_engine", "auto")
    loop = asyncio.get_running_loop()
    monotonic = clock or time.monotonic
    wait = sleep or asyncio.sleep
    char_bound = max(1, first_flush_chars or FIRST_FLUSH_CHARS)
    time_bound = max(0, first_flush_ms if first_flush_ms is not None else FIRST_FLUSH_MS)
    full = ""
    buf = ""
    seq = 0
    total = 0.0
    t0 = None
    first_text_at = None
    can_files = mode in ("auto", "edge", "elevenlabs")

    async def _emit_sent(txt: str) -> bool:
        nonlocal seq, total, t0
        if not _owns_turn(turn):
            return False
        say = _speak_norm(_strip_symbols(_strip_md(_pron(txt))))
        if not say.strip():
            return False
        if seq == 0:
            _mark_turn(turn, "first_flush")
        _remember_spoken(say)
        data = None
        if not _owns_turn(turn):
            return False
        if mode in ("auto", "edge"):
            data = await _edge_bytes(say)
        if not _owns_turn(turn):
            return False
        if not data and mode in ("auto", "elevenlabs"):
            data = await _eleven_bytes(say)
        if data and _owns_turn(turn):
            if t0 is None:
                t0 = loop.time()
            total += _estimate_secs(say)
            if seq == 0:
                _mark_turn(turn, "first_audio")
            if not _owns_turn(turn):
                return False
            await bus.emit("audio", {"url": _serve_audio(data, "mp3"),
                                     "seq": seq, "last": False})
            seq += 1
            return True
        return False

    def _pop_sentence() -> str | None:
        nonlocal buf
        m = re.search(r"^([\s\S]*?[\.\!\?…])(?=\s|$)", buf)
        if not m:
            return None
        out = m.group(1)
        buf = buf[m.end():].lstrip()
        return out

    if mode == "off":
        async for piece in pieces:
            if not _owns_turn(turn):
                break
            full += piece
        return full, 0.0

    if not _owns_turn(turn):
        return full, 0.0
    await bus.emit("state", "speaking")
    iterator = pieces.__aiter__()
    next_piece: asyncio.Task | None = None
    wait_cancelled = getattr(turn, "wait_cancelled", None)
    cancel_task = (
        asyncio.create_task(wait_cancelled()) if callable(wait_cancelled) else None
    )
    try:
        while _owns_turn(turn):
            if next_piece is None:
                next_piece = asyncio.create_task(anext(iterator))
            deadline_task = None
            if seq == 0 and buf.strip() and first_text_at is not None:
                elapsed = max(0.0, monotonic() - first_text_at)
                remaining = max(0.0, time_bound / 1000 - elapsed)
                deadline_task = asyncio.create_task(wait(remaining))
                waiters = {next_piece, deadline_task}
                if cancel_task is not None:
                    waiters.add(cancel_task)
                done, _ = await asyncio.wait(
                    waiters,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if cancel_task is not None and cancel_task in done:
                    deadline_task.cancel()
                    break
                if deadline_task in done and next_piece not in done:
                    if not _owns_turn(turn):
                        break
                    pending, buf = buf.strip(), ""
                    await _emit_sent(pending)
                    continue
                deadline_task.cancel()
            elif cancel_task is not None:
                done, _ = await asyncio.wait(
                    {next_piece, cancel_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if cancel_task in done:
                    break
            try:
                piece = await next_piece
            except StopAsyncIteration:
                next_piece = None
                break
            next_piece = None
            if not _owns_turn(turn):
                break
            full += piece
            if piece and first_text_at is None:
                first_text_at = monotonic()
                _mark_turn(turn, "first_token")
            if not can_files:
                continue
            buf += piece
            while True:
                sent = _pop_sentence()
                if sent is None:
                    break
                await _emit_sent(sent)
                if not _owns_turn(turn):
                    break
            if not _owns_turn(turn):
                break
            if seq == 0 and len(buf.strip()) >= char_bound:
                pending, buf = buf.strip(), ""
                await _emit_sent(pending)
    finally:
        if next_piece is not None and not next_piece.done():
            next_piece.cancel()
        if cancel_task is not None and not cancel_task.done():
            cancel_task.cancel()
    if can_files and buf.strip() and _owns_turn(turn):
        await _emit_sent(buf.strip())
    if not _owns_turn(turn):
        return full, 0.0
    if seq == 0 and full.strip() and mode in ("auto", "local"):
        # sin edge/eleven: voz local BLOQUEANTE con el texto completo
        say = _speak_norm(_strip_symbols(_strip_md(_pron(full))))
        spoke = await loop.run_in_executor(None, _speak_local_sync, say)
        if spoke:
            _mark_turn(turn, "first_flush")
            _mark_turn(turn, "first_audio")
            _remember_spoken(say)
        if not _owns_turn(turn):
            return full, 0.0
        await bus.emit("state", "idle")
        return full, 0.0
    if _owns_turn(turn):
        await bus.emit("state", "idle")
    if t0 is None:
        return full, 0.0
    return full, max(0.0, total - (loop.time() - t0))


async def stop(*, turn=None) -> None:
    """Corta la voz de la IA AL INSTANTE en el HUD (barge-in): cuando el operador
    habla en micro abierto, mandamos parar la reproducción y limpiar la cola."""
    try:
        await bus.emit("audio", {"stop": True})
    except Exception:
        pass
    turn = current_turn() if turn is None else turn
    if not _owns_turn(turn):
        return
    try:
        await bus.emit("state", "idle")
    except Exception:
        pass


def all_voices() -> dict:
    """Catálogo completo para el selector del HUD, agrupado por motor."""
    return {
        "edge": {"available": HAS_EDGE, "voices": list(EDGE_VOICES.keys()),
                 "note": "" if HAS_EDGE else "pip install edge-tts (gratis)"},
        "elevenlabs": {"available": bool(settings.elevenlabs_key),
                       "voices": list(ELEVEN_VOICES.keys()),
                       "note": "" if settings.elevenlabs_key else "requiere API key"},
        "local": {"available": HAS_PYTTSX3, "voices": local_voices(),
                  "note": "" if HAS_PYTTSX3 else "pip install pyttsx3"},
    }


def tts_status() -> dict:
    return {"engine": settings.get("tts_engine"), "voice": settings.get("tts_voice"),
            "edge": HAS_EDGE, "elevenlabs": bool(settings.elevenlabs_key),
            "local": HAS_PYTTSX3}
