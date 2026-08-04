"""
nexus — STT (voz → texto) v2.

Motor real: faster-whisper (local). Grabación DINÁMICA: empieza a grabar,
espera a que hables y corta solo cuando detecta ~1,2 s de silencio (máx 15 s),
en vez de los 5 s fijos de la v1 → reconocimiento mucho más natural.

Modo simulado solo si faltan librerías (instala: faster-whisper sounddevice numpy).
"""
from __future__ import annotations

import asyncio
import os
import threading
import time

# Silenciar avisos de HuggingFace antes de importar whisper
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

from .comun.config import settings
from .comun.events import bus

try:
    from faster_whisper import WhisperModel
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False

try:
    import numpy as np
    import sounddevice as sd
    HAS_MIC = True
except Exception:
    HAS_MIC = False

_model = None
SAMPLE_RATE = 16000
CHUNK_MS = 30                    # tamaño de bloque de análisis
MAX_SECONDS = 15                 # tope duro de grabación
SILENCE_STOP = 0.45              # segundos de silencio para cortar (modo conversación rápida)
START_TIMEOUT = 8                # segundos esperando a que empieces a hablar
ENERGY_GATE = 0.004              # umbral mínimo de energía (voz vs silencio) — muy sensible
SILENCE_FRACTION = 0.30          # silencio = caer por debajo del 30% de TU pico de voz

# --- BARGE-IN (cortar a la IA cuando hablas, en micro abierto) ---
# Pensado para AURICULARES (G935): el micro NO capta la voz de la IA, así que
# cualquier voz sostenida = eres TÚ. El umbral exigente + la voz sostenida evitan
# autocortes; con altavoces es menos fiable (lo ideal son auriculares).
BARGE_MIN = 0.06                 # energía absoluta mínima para dar por hecho que HABLAS
BARGE_RATIO = 4.0                # x veces por encima del ambiente medido justo antes
BARGE_CONFIRM = 0.18             # s de voz SOSTENIDA para confirmar (ignora clics/toses)
# Solo cuenta como VOZ si el bloque tiene PERIODICIDAD de habla (pitch 70-400 Hz).
# Así el barge-in NO salta con ruido de calle (banda ancha, sin tono) ni tecleo
# (transitorios sin tono): ambos dan autocorrelación baja en la banda de pitch.
VOICE_AC = 0.30                  # autocorrelación normalizada mínima en la banda de pitch

def _norm_name(s) -> str:
    """Nombre normalizado para comparar: minúsculas, sin acentos, espacios simples."""
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def _hostapi_rank(idx: int) -> int:
    """Prioridad del motor de audio (menor = más compatible con 16 kHz)."""
    try:
        api = (sd.query_hostapis(sd.query_devices(idx)["hostapi"])["name"] or "").lower()
    except Exception:
        return 9
    if "mme" in api:
        return 0
    if "directsound" in api:
        return 1
    if "wasapi" in api:
        return 2
    return 3


def _candidate_devices() -> list:
    """Índices de ENTRADA que casan con el micro elegido en ⚙, ordenados de más a
    menos compatible, con None (micro predeterminado) SIEMPRE al final como red de
    seguridad. En Windows el MISMO micro sale por varios motores (MME/WASAPI/
    DirectSound/WDM-KS) y los nombres MME van truncados a 31 caracteres, así que
    se compara sin acentos y por prefijo/contención, no solo igualdad exacta."""
    out: list = []
    dev = settings.get("input_device", "")
    if HAS_MIC and dev not in (None, ""):
        try:
            out.append(int(dev))
        except (TypeError, ValueError):
            try:
                want = _norm_name(dev)
                exact, partial = [], []
                for i, d in enumerate(sd.query_devices()):
                    if d.get("max_input_channels", 0) <= 0:
                        continue
                    name = _norm_name(d.get("name"))
                    if not name:
                        continue
                    if name == want:
                        exact.append(i)
                    elif want.startswith(name) or name.startswith(want) \
                            or want in name or name in want:
                        partial.append(i)
                # MME PRIMERO aunque su nombre esté truncado (parcial): es el
                # motor más compatible; DS/WASAPI a veces abren y dan solo ceros.
                exact_s = set(exact)
                out += sorted(exact + partial,
                              key=lambda i: (_hostapi_rank(i), 0 if i in exact_s else 1))
            except Exception:
                pass
    out.append(None)
    seen, res = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            res.append(x)
    return res


_last_open = {"key": None}
_good = {"cfg": None, "combo": None}     # (dev, rate, bs, name) que YA demostró capturar
_warn_ts = {"t": 0.0}


def _warn_ok() -> bool:
    """Máx 1 aviso de micro cada 6 s: sin esto, un micro roto en bucle INUNDA el
    registro con el mismo mensaje varias veces por segundo."""
    now = time.monotonic()
    if now - _warn_ts["t"] >= 6.0:
        _warn_ts["t"] = now
        return True
    return False


def _probe_stream(stream, bs: int, chunk_ms: int) -> str:
    """Prueba de VIDA (~0,3 s). Que un stream abra sin error NO garantiza capturar:
    · 'dead'   → las lecturas vuelven AL INSTANTE sin bloquear: no captura nada
                 (así salía «nivel máx 0.0000» varias veces por segundo).
    · 'silent' → captura a ritmo real pero entrega SOLO ceros (mute por hardware,
                 puerta de ruido de G HUB, privacidad de Windows…).
    · 'alive'  → entrega señal de verdad."""
    n = max(6, int(300 / chunk_ms))
    t0 = time.monotonic()
    mx = 0.0
    for _ in range(n):
        block, _o = stream.read(bs)
        if getattr(block, "size", 0):
            mx = max(mx, float(np.max(np.abs(block))))
    if time.monotonic() - t0 < n * (chunk_ms / 1000.0) * 0.35:
        return "dead"
    return "alive" if mx > 0.0 else "silent"


def _open_input_stream(chunk_ms: int = CHUNK_MS):
    """Abre el micrófono con TOLERANCIA A FALLOS y PRUEBA DE VIDA.

    Recorre los candidatos de _candidate_devices() (cada uno a 16 kHz y a su
    tasa nativa) y se queda con el PRIMERO que entrega señal REAL. Si ninguno da
    señal pero alguno captura a ritmo real (gate/mute), lo usa como plan B y
    avisa del porqué. La combinación buena se recuerda y se reutiliza SIN prueba
    (cero latencia extra) hasta que falle o se cambie el micro en ⚙.
    Devuelve (stream YA ARRANCADO, samplerate, blocksize, nombre)."""
    cfg = str(settings.get("input_device", ""))
    if _good["cfg"] != cfg:
        _good["cfg"], _good["combo"] = cfg, None

    if _good["combo"]:
        dev, rate, bs, name = _good["combo"]
        try:
            stream = sd.InputStream(samplerate=rate, channels=1, dtype="float32",
                                    blocksize=bs, device=dev)
            stream.start()
            return stream, rate, bs, name
        except Exception:
            _good["combo"] = None            # dejó de valer → re-descubrir abajo

    last_exc = None
    fallback = None                          # 1º candidato 'silent' (captura pero ceros)
    for dev in _candidate_devices():
        info = {}
        try:
            qi = dev if dev is not None else sd.default.device[0]
            if qi is not None and qi != -1:
                info = sd.query_devices(qi)
        except Exception:
            info = {}
        rates = [SAMPLE_RATE]
        native = int(info.get("default_samplerate") or 0)
        if native and native != SAMPLE_RATE:
            rates.append(native)
        name = (info.get("name") or "").strip() or (
            "predeterminado" if dev is None else f"dispositivo {dev}")
        for rate in rates:
            bs = max(1, int(rate * chunk_ms / 1000))
            try:
                stream = sd.InputStream(samplerate=rate, channels=1, dtype="float32",
                                        blocksize=bs, device=dev)
                stream.start()
            except Exception as exc:         # noqa: BLE001
                last_exc = exc
                continue
            try:
                estado = _probe_stream(stream, bs, chunk_ms)
            except Exception as exc:         # noqa: BLE001
                last_exc = exc
                estado = "dead"
            if estado == "alive":
                _good["combo"] = (dev, rate, bs, name)
                key = (dev, rate)
                if _last_open["key"] != key:
                    _last_open["key"] = key
                    try:
                        bus.emit_sync("log", {"level": "ok",
                                              "msg": f"🎙 Micro en uso: «{name}» a {rate} Hz "
                                                     "(captura señal ✓)."})
                    except Exception:
                        pass
                return stream, rate, bs, name
            try:
                stream.close()
            except Exception:
                pass
            if estado == "silent" and fallback is None:
                fallback = (dev, rate, bs, name)

    if fallback is not None:
        dev, rate, bs, name = fallback
        try:
            stream = sd.InputStream(samplerate=rate, channels=1, dtype="float32",
                                    blocksize=bs, device=dev)
            stream.start()
            if _warn_ok():
                try:
                    bus.emit_sync("log", {"level": "warn", "msg":
                        f"🎙 Micro «{name}» abierto pero entrega SILENCIO ABSOLUTO. "
                        "En el G935: el brazo del micro SUBIDO = silenciado por "
                        "hardware (bájalo del todo) y revisa el mute/puerta de ruido "
                        "en G HUB; también Configuración → Privacidad → Micrófono."})
                except Exception:
                    pass
            return stream, rate, bs, name
        except Exception as exc:             # noqa: BLE001
            last_exc = exc
    raise last_exc if last_exc else RuntimeError(
        "ningún micrófono capturó audio (los motores fallaron o devolvían datos "
        "al instante sin capturar)")


def list_input_devices() -> list:
    """Micrófonos de ENTRADA disponibles (para el selector de ⚙)."""
    if not HAS_MIC:
        return []
    try:
        default_in = None
        try:
            default_in = sd.default.device[0]
        except Exception:
            pass
        out, seen = [], {}
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0:
                name = (d.get("name") or f"dispositivo {i}").strip()
                is_def = (i == default_in)
                # Windows lista el MISMO micro por cada motor de audio (MME/WASAPI/
                # DirectSound/WDM-KS) → deduplicamos por nombre y nos quedamos con el
                # nombre MÁS LARGO (el completo, no el truncado de MME).
                key = name.lower()[:24]
                if key in seen:
                    j = seen[key]
                    if len(name) > len(out[j]["name"]):
                        out[j]["name"], out[j]["index"] = name, i
                    if is_def:
                        out[j]["default"] = True
                else:
                    seen[key] = len(out)
                    out.append({"index": i, "name": name, "default": is_def})
        return out
    except Exception:
        return []


def _app_hints() -> str:
    """Nombres de apps instaladas + servicios → sesgan a Whisper para que
    transcriba bien los nombres propios («abre fotoshop» → «Photoshop»)."""
    names = []
    try:
        from .app_index import get_index
        seen = set()
        for k in sorted((get_index() or {}).keys(), key=len):
            t = k.title()
            if t.lower() in seen:
                continue
            seen.add(t.lower())
            names.append(t)
            if len(names) >= 40:
                break
    except Exception:
        pass
    servicios = ["Spotify", "YouTube", "iTunes", "Apple Music", "Steam", "Discord",
                 "Chrome", "Telegram", "WhatsApp", "Netflix", "Photoshop"]
    return ", ".join(dict.fromkeys(servicios + names))


def _cuda_warmup(m) -> None:
    """Fuerza la carga REAL de CUDA (cuBLAS/cuDNN) con una transcripción mínima.
    faster-whisper NO falla al crear el modelo en 'cuda' aunque falten las DLL
    (cublas64_12.dll); el error salta en la PRIMERA transcripción. Este warmup lo
    provoca aquí, en un try controlado, para poder caer a CPU antes de que reviente
    el micro en pleno uso."""
    import numpy as _np
    seg, _info = m.transcribe(_np.zeros(16000, dtype=_np.float32),
                              language="es", beam_size=1, vad_filter=False)
    list(seg)                                        # consume el generador → ejecuta el encoder


def make_whisper(model_name: str):
    """Crea un WhisperModel probando GPU (CUDA) y cayendo a CPU si faltan las
    librerías de CUDA (cublas64_12.dll / cudnn). Así nunca peta el micro."""
    dev_pref = settings.get("stt_device", "auto")   # auto | cuda | cpu
    intentos = []
    if dev_pref in ("auto", "cuda"):
        intentos.append(("cuda", "float16"))
    intentos.append(("cpu", "int8"))                # respaldo universal
    last = None
    for device, ctype in intentos:
        try:
            m = WhisperModel(model_name, device=device, compute_type=ctype)
            if device == "cuda":
                _cuda_warmup(m)                      # ← si falta cuBLAS/cuDNN, revienta AQUÍ
            if device == "cpu" and dev_pref != "cpu":
                bus.emit_sync("log", {"level": "info",
                                      "msg": "Voz en CPU (sin CUDA). Funciona perfectamente; "
                                             "para usar la GPU instala cuBLAS+cuDNN de NVIDIA."})
            return m
        except Exception as exc:
            last = exc
            if device == "cuda":
                bus.emit_sync("log", {"level": "info",
                                      "msg": "GPU sin librerías CUDA completas — uso la CPU "
                                             "para la voz (funciona igual)."})
            continue
    raise last if last else RuntimeError("no se pudo cargar whisper")


def _get_model():
    global _model
    if _model is None and HAS_WHISPER:
        bus.emit_sync("log", {"level": "info",
                              "msg": "Cargando modelo de voz (la primera vez puede descargar ~460 MB)…"})
        _model = make_whisper(settings.get("whisper_model", "small"))
        bus.emit_sync("log", {"level": "ok", "msg": "Modelo de voz listo. A la escucha."})
    return _model


def preload_model() -> None:
    """Carga el modelo de voz al arrancar (en segundo plano) para que la 1ª orden
    sea instantánea y para que cualquier fallo de CUDA salga AHORA, no al hablar."""
    if HAS_WHISPER and HAS_MIC:
        try:
            _get_model()
        except Exception as exc:                       # noqa: BLE001
            bus.emit_sync("log", {"level": "warn", "msg": f"Voz: no pude precargar el modelo ({exc})"})


_CANCEL = threading.Event()


def cancel_listen() -> None:
    """Aborta la escucha en curso: el botón «habla» pulsado de nuevo RE-ARMA al
    instante en vez de quedarse «pillado» esperando a que acabe el ciclo previo."""
    _CANCEL.set()


def _record_dynamic():
    # -> np.ndarray | None  (audio float32 mono 16 kHz, ya normalizado a [-1,1])
    """Graba y CORTA cuando dejas de hablar. Endpointing ADAPTATIVO: el umbral de
    silencio es relativo a TU pico de voz (caes por debajo del 30% → silencio), no
    a un valor fijo. Así corta bien aunque haya ventilador/música de fondo, siempre
    que tu voz suene por encima del ruido. Incluye pre-roll para no cortar la 1ª sílaba."""
    if not HAS_MIC:
        return None

    def _rms(b) -> float:
        return float(np.sqrt(np.mean(b ** 2)))

    dt = CHUNK_MS / 1000.0
    pre_n = max(4, int(0.2 / dt))          # ~0.2 s de pre-roll
    preroll: list = []
    frames: list = []
    started = False
    silent_time = 0.0
    speech_time = 0.0
    waited = 0.0
    peak = 0.0
    vu_i = 0
    max_e = 0.0
    _CANCEL.clear()
    try:
        stream, rate, chunk, dev_name = _open_input_stream()
    except Exception as exc:                               # noqa: BLE001
        if _warn_ok():
            bus.emit_sync("log", {"level": "warn", "msg":
                f"Micro: no pude abrir ningún dispositivo de entrada "
                f"({type(exc).__name__}: {exc}). Revisa el micrófono elegido en ⚙ y que "
                "Windows permita el micrófono a las apps (Configuración → Privacidad y "
                "seguridad → Micrófono)."})
        time.sleep(1.0)      # freno: un micro roto NO debe reintentar en bucle loco
        return None
    try:
        with stream:
            # --- calibración de ruido ambiente (~0.35 s) ---
            ambient = []
            for _ in range(12):
                block, _o = stream.read(chunk)
                ambient.append(_rms(block))
                preroll.append(block.copy())
                if len(preroll) > pre_n:
                    preroll.pop(0)
            noise = sorted(ambient)[len(ambient) // 2]      # mediana
            gate = max(ENERGY_GATE, noise * 1.6)            # arrancar: apenas por encima del ambiente
            floor = max(ENERGY_GATE * 0.5, noise * 1.3)     # suelo de silencio (nunca por debajo del ruido)
            while True:
                if _CANCEL.is_set():
                    _CANCEL.clear()
                    return None
                block, _o = stream.read(chunk)
                energy = _rms(block)
                # Vúmetro REAL para el HUD: 0 en silencio, sube solo con tu voz.
                vu_i += 1
                if vu_i % 3 == 0:
                    base = max(floor, peak * SILENCE_FRACTION) if started else gate
                    lvl = 0.0 if energy < base else min(1.0, energy / (base * 1.8))
                    try:
                        bus.emit_sync("vu", {"level": round(lvl, 3)})
                    except Exception:
                        pass
                if not started:
                    max_e = max(max_e, energy)
                    preroll.append(block.copy())
                    if len(preroll) > pre_n:
                        preroll.pop(0)
                    waited += dt
                    if energy > gate:
                        started = True
                        frames.extend(preroll)              # arranca con el pre-roll (no corta el inicio)
                        frames.append(block.copy())
                        peak = energy
                    elif waited > START_TIMEOUT:
                        # Diagnóstico: por qué no arrancó (para saber si el micro capta o no)
                        if max_e <= 0.0:
                            _good["combo"] = None   # este combo NO capta → re-probar motores
                        if max_e < 0.004:
                            if _warn_ok():
                                bus.emit_sync("log", {"level": "warn", "msg":
                                    f"Micro sin señal escuchando «{dev_name}» (nivel máx "
                                    f"{max_e:.4f}). Si es el G935: BAJA el brazo del micro "
                                    "(subido = silenciado) y mira el mute en G HUB; o elige "
                                    "otro micrófono en ⚙."})
                        else:
                            bus.emit_sync("log", {"level": "info", "msg":
                                f"No detecté voz (tu nivel {max_e:.3f} no superó el umbral "
                                f"{gate:.3f}). Habla un poco más fuerte/cerca."})
                        return None                         # nadie habló
                    continue
                frames.append(block.copy())
                peak = max(peak * 0.995, energy)            # pico de voz con leve decaimiento
                release = max(floor, peak * SILENCE_FRACTION)
                if energy < release:
                    silent_time += dt
                else:
                    silent_time = 0.0
                    speech_time += dt
                dur = len(frames) * dt
                if (silent_time >= SILENCE_STOP and speech_time >= 0.25) or dur >= MAX_SECONDS:
                    break
    except Exception as exc:                               # noqa: BLE001
        _good["combo"] = None
        if _warn_ok():
            bus.emit_sync("log", {"level": "warn", "msg":
                f"Micro: no pude leer el dispositivo ({type(exc).__name__}: {exc}). "
                "¿Hay otro programa usándolo en exclusiva?"})
        return None
    if not frames or speech_time < 0.2:                     # ignora chasquidos/ruido breve
        return None
    # SIN ARCHIVO TEMPORAL: faster-whisper acepta el array numpy directamente.
    # Antes escribíamos un .wav en %TEMP% y Whisper lo releía → en Windows el
    # archivo quedaba bloqueado (WinError 32). Pasando el audio en memoria como
    # float32 mono 16 kHz [-1,1] ese problema DESAPARECE de raíz (no hay fichero).
    audio = np.concatenate(frames).astype(np.float32).reshape(-1)
    if rate != SAMPLE_RATE and audio.size > 1:
        # el micro se abrió a su tasa nativa → remuestreo lineal a 16 kHz
        n = max(1, int(round(audio.size * SAMPLE_RATE / float(rate))))
        audio = np.interp(np.linspace(0.0, audio.size - 1.0, n),
                          np.arange(audio.size, dtype=np.float64),
                          audio.astype(np.float64)).astype(np.float32)
    return audio


def _voiced_ac(block, rate: int) -> bool:
    """True si el bloque suena a VOZ HUMANA (tiene tono/pitch en 70-400 Hz). El habla
    es PERIÓDICA; el ruido de calle es de banda ancha y el tecleo son transitorios:
    ambos dan autocorrelación baja en la banda de pitch → se rechazan. Es lo que evita
    que el barge-in corte a la IA por ruido de ambiente o teclas. Sin dependencias nuevas."""
    import numpy as np
    x = np.asarray(block, dtype=np.float64)
    x = x.mean(axis=1) if x.ndim > 1 else x.ravel()
    if x.size < 16:
        return False
    x = x - x.mean()
    e0 = float(np.dot(x, x))
    if e0 < 1e-8:                                   # silencio
        return False
    lag_min = max(2, int(rate / 400))               # pitch máx 400 Hz
    lag_max = min(int(rate / 70), x.size - 2)        # pitch mín 70 Hz
    if lag_max <= lag_min:
        return False
    m = 1
    while m < x.size * 2:                            # FFT: autocorrelación rápida
        m <<= 1
    X = np.fft.rfft(x, n=m)
    ac = np.fft.irfft(X * np.conj(X))[:x.size]
    ac = ac / (ac[0] + 1e-9)                         # normaliza a [-1, 1]
    band = ac[lag_min:lag_max + 1]
    k = int(band.argmax())
    kk = lag_min + k
    # exige un PICO real (máximo local dentro de la banda): un tono grave por debajo
    # de la banda solo DECAE (su máximo cae en el borde) → se rechaza; la VOZ tiene su
    # pico de pitch en medio. Los picos espurios de ruido no se sostienen (BARGE_CONFIRM).
    if not (lag_min < kk < lag_max and ac[kk] >= ac[kk - 1] and ac[kk] >= ac[kk + 1]):
        return False
    return float(band[k]) >= VOICE_AC


def watch_barge_in(max_secs: float) -> bool:
    """Escucha el micro MIENTRAS la IA habla (micro abierto). Devuelve True EN CUANTO
    detecta tu VOZ sostenida (para cortar la voz de la IA y escucharte), o False si
    pasan max_secs sin que hables. BLOQUEANTE → correr en un hilo (run_in_executor).
    Si no hay micro, hace de simple espera pasiva (no interrumpe)."""
    if max_secs <= 0:
        return False
    if not HAS_MIC:
        time.sleep(max_secs)
        return False
    import numpy as np
    import sounddevice as sd

    def _rms(b) -> float:
        return float(np.sqrt(np.mean(b ** 2))) if getattr(b, "size", 0) else 0.0

    dt = CHUNK_MS / 1000.0
    voiced = 0.0
    waited = 0.0
    try:
        stream, _rate, chunk, _dn = _open_input_stream()
        with stream:
            ambient = []
            for _ in range(8):                       # ~0.24 s de ambiente
                block, _o = stream.read(chunk)
                ambient.append(_rms(block))
                waited += dt
            noise = sorted(ambient)[len(ambient) // 2]
            gate = max(BARGE_MIN, noise * BARGE_RATIO)
            while waited < max_secs:
                block, _o = stream.read(chunk)
                waited += dt
                # cuenta SOLO si es FUERTE **y** suena a VOZ (pitch) — así el ruido de
                # calle (banda ancha) y el tecleo (transitorios) ya no cortan a la IA.
                if _rms(block) >= gate and _voiced_ac(block, _rate):
                    voiced += dt
                    if voiced >= BARGE_CONFIRM:       # voz sostenida → eres tú
                        return True
                else:
                    voiced = 0.0
    except Exception:
        # si el micro no se puede abrir aquí, no interrumpimos: espera pasiva el resto
        time.sleep(max(0.0, max_secs - waited))
        return False
    return False


async def listen_once(announce: bool = True) -> str:
    """Escucha una intervención. Devuelve '' si no se detectó voz."""
    if announce:
        await bus.emit("state", "listening")
    engine = settings.get("stt_engine", "auto")

    if engine != "mock" and HAS_WHISPER and HAS_MIC:
        loop = asyncio.get_running_loop()
        audio = await loop.run_in_executor(None, _record_dynamic)
        if audio is None:
            return ""
        await bus.emit("state", "thinking")
        await bus.emit("log", {"level": "info", "msg": "Voz captada, transcribiendo…"})

        def _transcribe():
            global _model
            _prompt = ("Órdenes en español para el asistente nexus: abrir "
                       "aplicaciones, poner música, tareas, recordatorios, agenda, "
                       "correos. Nombres propios frecuentes: " + _app_hints() + ".")
            try:
                # Se transcribe el ARRAY en memoria (sin .wav): imposible que
                # Windows lo bloquee → adiós WinError 32.
                segments, _info = _get_model().transcribe(
                    audio, language="es", beam_size=1, vad_filter=True,
                    condition_on_previous_text=False, initial_prompt=_prompt)
                return " ".join(s.text.strip() for s in segments)
            except Exception as exc:
                # Red de seguridad: si la GPU falla en caliente (p.ej. cublas64_12.dll),
                # rehacemos el modelo en CPU y reintentamos una vez. Nunca dejamos el
                # micro roto por CUDA.
                bus.emit_sync("log", {"level": "warn",
                                      "msg": f"Voz: fallo en GPU ({type(exc).__name__}); "
                                             "reintento en CPU."})
                settings.set("stt_device", "cpu")
                _model = None
                segments, _info = _get_model().transcribe(
                    audio, language="es", beam_size=1, vad_filter=True,
                    condition_on_previous_text=False, initial_prompt=_prompt)
                return " ".join(s.text.strip() for s in segments)

        text = await loop.run_in_executor(None, _transcribe)
        text = text.strip()
        if text:
            await bus.emit("log", {"level": "ok", "msg": f"🎙 Has dicho: «{text}»"})
        else:
            await bus.emit("log", {"level": "warn",
                                   "msg": "Grabé audio pero no reconocí texto (habla más claro "
                                          "o revisa el micro)."})
        return text

    # Sin STT real NO inventamos frases (ejecutar órdenes falsas confunde):
    # devolvemos vacío y voice_cycle explica al operador cómo activar la voz.
    await asyncio.sleep(0.4)
    await bus.emit("log", {"level": "warn",
                           "msg": "STT no instalado — ejecuta: pip install -r "
                                  "requirements-voice.txt (necesita Python 3.11/3.12)"})
    return ""


async def transcribe_path(path: str) -> str:
    """Transcribe un ARCHIVO de audio (voz grabada en el MÓVIL: webm/ogg/m4a) con
    el mismo Whisper local y el mismo prompt de nombres propios que el micro del
    PC. faster-whisper decodifica el contenedor con PyAV (no hace falta ffmpeg)."""
    if not HAS_WHISPER:
        return ""
    loop = asyncio.get_running_loop()

    def _run():
        global _model
        _prompt = ("Órdenes en español para el asistente nexus: abrir "
                   "aplicaciones, poner música, tareas, recordatorios, agenda, "
                   "correos. Nombres propios frecuentes: " + _app_hints() + ".")
        try:
            segments, _info = _get_model().transcribe(
                path, language="es", beam_size=1, vad_filter=True,
                condition_on_previous_text=False, initial_prompt=_prompt)
            return " ".join(seg.text.strip() for seg in segments)
        except Exception as exc:                           # noqa: BLE001
            bus.emit_sync("log", {"level": "warn",
                                  "msg": f"Voz móvil: fallo ({type(exc).__name__}); "
                                         "reintento en CPU."})
            settings.set("stt_device", "cpu")
            _model = None
            segments, _info = _get_model().transcribe(
                path, language="es", beam_size=1, vad_filter=True,
                condition_on_previous_text=False, initial_prompt=_prompt)
            return " ".join(seg.text.strip() for seg in segments)

    try:
        text = (await loop.run_in_executor(None, _run)).strip()
    except Exception:                                      # noqa: BLE001
        return ""
    if text:
        bus.emit_sync("log", {"level": "ok", "msg": f"📱🎙 Voz del móvil: «{text}»"})
    return text


def stt_status() -> dict:
    return {"whisper": HAS_WHISPER, "mic": HAS_MIC,
            "engine": "whisper" if (HAS_WHISPER and HAS_MIC) else "mock",
            "model": settings.get("whisper_model", "small")}
