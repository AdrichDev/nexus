"""
nexus — Wake word INTEGRADA («di nexus» con la app abierta).

Bucle asíncrono dentro del propio backend: cuando wake_enabled está activo
(⚙) y hay STT real, escucha ventanas cortas de audio con whisper-tiny.
Si oye la palabra de activación → lanza el ciclo de voz completo, igual
que pulsar TALK. No necesita el script externo nexus_wake (ese sigue
sirviendo para ABRIR el programa cuando está cerrado).

Se desactiva solo mientras el micro abierto (∞) está activo — ahí ya se
escucha todo — y mientras hay un ciclo de voz en marcha.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import wave
from pathlib import Path

from .config import settings
from .events import bus

_tiny_model = None
WINDOW_S = 2.5
# Frase de activación: "despierta nexus" (se pronuncia GUABIKS).
# Cubrimos variantes fonéticas de ambas palabras como las transcribe whisper.
DESPIERTA = ("despierta", "despiertate", "despierta te", "espierta", "de spierta")
VARIANTS = ("nexus", "guabiks", "guabix", "guavix", "guabics", "gua bix", "gua biks",
            "wavix", "uabiks", "wabbix", "wabis", "guapix", "guabik", "guabis",
            "wabix", "wabics", "buabiks", "gnexus", "wabik")


def _is_wake(text: str) -> bool:
    """True si el texto contiene la frase de activación (despierta + nexus)."""
    t = text.lower()
    has_nexus = any(v in t for v in VARIANTS)
    has_desp = any(d in t for d in DESPIERTA)
    # Requiere "despierta" + nexus; o simplemente "nexus" solo/aislado como respaldo
    return (has_desp and has_nexus) or t.strip() in VARIANTS


def _get_tiny():
    global _tiny_model
    if _tiny_model is None:
        from .stt import make_whisper
        _tiny_model = make_whisper("tiny")
    return _tiny_model


def _listen_window() -> str:
    """Graba WINDOW_S segundos y devuelve la transcripción (hilo aparte).
    Transcribe el array numpy directamente (sin .wav temporal → sin WinError 32)."""
    import numpy as np
    import sounddevice as sd
    from .stt import _input_device
    sr = 16000
    audio = sd.rec(int(WINDOW_S * sr), samplerate=sr, channels=1, dtype="float32",
                   device=_input_device())
    sd.wait()
    if float(np.sqrt(np.mean(audio ** 2))) < 0.006:
        return ""  # silencio: ni transcribimos (ahorra CPU)
    mono = audio.astype(np.float32).reshape(-1)      # (N,1) → (N,) float32 [-1,1]
    segments, _ = _get_tiny().transcribe(mono, language="es", beam_size=1)
    return " ".join(s.text for s in segments).lower()


async def wake_loop():
    announced = False
    while True:
        try:
            if (not settings.get("wake_enabled", False) or settings.get("open_mic", False)
                    or settings.get("mic_muted", False)):
                announced = False
                await asyncio.sleep(1.5)
                continue
            from .stt import stt_status
            if stt_status()["engine"] != "whisper":
                await asyncio.sleep(3)
                continue
            from . import voice_cycle as vc
            if vc._busy:
                await asyncio.sleep(0.5)
                continue
            if not announced:
                await bus.emit("log", {"level": "ok",
                                       "msg": "Palabra de activación armada: di «despierta nexus»"})
                announced = True
            text = await asyncio.get_running_loop().run_in_executor(None, _listen_window)
            if text and _is_wake(text):
                await bus.emit("log", {"level": "ok", "msg": f"«Despierta nexus» detectado («{text.strip()[:40]}»)"})
                await bus.emit("wake", True)
                await vc.voice_cycle()
        except Exception as exc:
            await bus.emit("log", {"level": "warn", "msg": f"Wake: {exc}"})
            await asyncio.sleep(3)
