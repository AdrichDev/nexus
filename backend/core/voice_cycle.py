"""
nexus — Ciclos de voz.

* voice_cycle():   una intervención (F9 / botón MIC)
* open_mic_loop(): MICRO ABIERTO — conversación fluida sin pulsar nada.
  Se activa/desactiva desde el HUD (botón ∞ AUTO) o con settings open_mic.
  Requiere STT real (whisper + micrófono); con STT simulado se auto-desactiva
  para no entrar en bucle de frases inventadas.
"""
from __future__ import annotations

import asyncio

from . import brain, stt, tts
from .config import settings
from .events import bus

_busy = False


async def voice_cycle() -> dict:
    global _busy
    if settings.get("mic_muted", False):
        msg = "Estás muteado (🎙⛔). Quita el mute para que pueda oírte."
        await bus.emit("chat", {"user": "[voz]", "reply": msg, "provider": "sistema", "skill": None})
        await bus.emit("state", "idle")
        return {"reply": msg, "muted": True}
    if _busy:
        # NO ignorar el botón: CANCELA lo que hubiera (escucha o voz sonando) y
        # re-arma la escucha en cuanto el ciclo anterior suelte el candado.
        stt.cancel_listen()
        await tts.stop()
        await bus.emit("log", {"level": "info",
                               "msg": "🎙 Reinicio la escucha (lo anterior, cancelado)."})
        for _ in range(25):
            await asyncio.sleep(0.1)
            if not _busy:
                break
        if _busy:
            return {"reply": "", "skipped": True}
    _busy = True
    try:
        await tts.stop()      # INTERRUMPIR: si nexus estaba hablando, se calla y te escucha
        text = await asyncio.wait_for(stt.listen_once(), timeout=40)
        if not text:
            st = stt.stt_status()
            if st["engine"] == "whisper":
                msg = "No he detectado voz. Prueba otra vez, más cerca del micro."
            else:
                msg = ("Aún no tengo oído: falta la voz real. Instálala con "
                       "`pip install -r requirements-voice.txt` — OJO: faster-whisper "
                       "todavía no soporta Python 3.14; usa un venv con Python 3.11 o 3.12 "
                       "(instalable desde python.org, y run.bat lo detecta solo).")
            await bus.emit("chat", {"user": "[voz]", "reply": msg,
                                    "provider": "sistema", "skill": None})
            await bus.emit("state", "idle")
            return {"reply": msg}
        result = await asyncio.wait_for(
            brain.process(text, source="voice", stream_voice=True), timeout=120)
        if not result.get("spoken"):
            await tts.speak(result["reply"])
        return result
    except asyncio.TimeoutError:
        await bus.emit("log", {"level": "warn",
                               "msg": "Voz: se tardó demasiado; reinicio el ciclo (botón libre)."})
        await bus.emit("state", "idle")
        return {"reply": ""}
    except Exception as exc:                                   # noqa: BLE001
        await bus.emit("log", {"level": "error", "msg": f"Ciclo de voz: {type(exc).__name__}: {exc}"})
        await bus.emit("state", "idle")
        return {"reply": ""}
    finally:
        _busy = False       # SIEMPRE se libera → el botón nunca se queda bloqueado


async def open_mic_loop():
    """Bucle de conversación continua. Corre siempre; actúa solo si open_mic=True."""
    global _busy
    warned = False
    while True:
        if not settings.get("open_mic", False) or settings.get("mic_muted", False):
            warned = False
            await asyncio.sleep(1)      # muteado: el micro abierto NO te oye
            continue

        st = stt.stt_status()
        if st["engine"] != "whisper":
            if not warned:
                await bus.emit("log", {"level": "warn",
                                       "msg": "Micro abierto desactivado: necesita STT real "
                                              "(pip install faster-whisper sounddevice numpy)"})
                warned = True
            settings.set("open_mic", False)
            await bus.emit("openmic", False)
            continue

        if _busy:
            await asyncio.sleep(0.3)
            continue

        _busy = True
        try:
            await bus.emit("state", "listening")
            text = await asyncio.wait_for(stt.listen_once(announce=False), timeout=40)
            if text:
                result = await asyncio.wait_for(
                    brain.process(text, source="voice", stream_voice=True), timeout=120)
                talk_secs = (float(result.get("spoken_secs") or 0.0) if result.get("spoken")
                             else (await tts.speak(result["reply"]) or 0.0))
                await bus.emit("state", "idle")
                # BARGE-IN + ANTI-ECO en uno: mientras nexus habla, VIGILA el micro.
                #  · Si HABLAS → corta la voz de la IA al instante y sale ya para
                #    capturarte (el bucle vuelve a listen_once de inmediato).
                #  · Si NO hablas → hace de espera hasta que nexus CALLA del todo, así
                #    el micro no se re-arma sobre su propia voz (bug de «no me oía justo
                #    al responder»). +0.3 s de colchón para que el audio termine.
                if talk_secs > 0.4:
                    loop = asyncio.get_running_loop()
                    interrupted = await loop.run_in_executor(
                        None, stt.watch_barge_in, talk_secs + 0.3)
                    if interrupted:
                        await tts.stop()      # manda al HUD callar YA
                        await bus.emit("log", {"level": "info",
                                               "msg": "🎙 Te he oído — te dejo hablar."})
            else:
                await bus.emit("state", "idle")
        except asyncio.TimeoutError:
            await bus.emit("state", "idle")
        except Exception as exc:
            await bus.emit("log", {"level": "error", "msg": f"Micro abierto: {exc}"})
            await bus.emit("state", "idle")
            await asyncio.sleep(2)
        finally:
            _busy = False
        await asyncio.sleep(0.2)   # pequeño respiro entre turnos
