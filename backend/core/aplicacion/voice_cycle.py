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
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from . import brain
from ..infraestructura import stt, tts
from ..comun.config import settings
from ..comun.events import bus

_STAGES = (
    "final_transcript",
    "brain_start",
    "first_token",
    "first_flush",
    "first_audio",
    "completion",
)
_BARGE_WATCH_SLICE_SECS = 0.5
_turn_epoch = 0
_current_turn: VoiceTurn | None = None
_busy: VoiceTurn | None = None
_listen_lock: asyncio.Lock | None = None
_listen_lock_loop = None
_metric_tasks: set[asyncio.Task] = set()


@dataclass
class VoiceTurn:
    epoch: int
    started_at: float
    clock: Callable[[], float] = field(repr=False)
    marks: dict[str, float] = field(default_factory=dict)
    cancelled: bool = False
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    listening: bool = False

    def is_current(self) -> bool:
        return not self.cancelled and _current_turn is self

    def mark(self, stage: str) -> None:
        if stage not in _STAGES or stage in self.marks or not self.is_current():
            return
        now = self.clock()
        if self.marks:
            now = max(now, next(reversed(self.marks.values())))
        self.marks[stage] = now

    async def wait_cancelled(self) -> None:
        await self.cancel_event.wait()


def _reserve_turn(clock: Callable[[], float] | None = None) -> VoiceTurn:
    global _turn_epoch, _current_turn, _busy
    if _current_turn is not None:
        previous = _current_turn
        previous.cancelled = True
        previous.cancel_event.set()
        if previous.listening:
            stt.cancel_listen()
    _turn_epoch += 1
    monotonic = clock or time.monotonic
    turn = VoiceTurn(_turn_epoch, monotonic(), monotonic)
    _current_turn = turn
    _busy = turn
    return turn


def _owns(turn: VoiceTurn) -> bool:
    return turn.is_current()


def _get_listen_lock() -> asyncio.Lock:
    global _listen_lock, _listen_lock_loop
    loop = asyncio.get_running_loop()
    if _listen_lock is None or _listen_lock_loop is not loop:
        _listen_lock = asyncio.Lock()
        _listen_lock_loop = loop
    return _listen_lock


async def _listen_once(turn: VoiceTurn, **kwargs) -> str | None:
    if not _owns(turn):
        return None
    async with _get_listen_lock():
        if not _owns(turn):
            return None
        turn.listening = True
        try:
            text = await stt.listen_once(**kwargs)
        finally:
            turn.listening = False
    return text if _owns(turn) else None


async def _watch_barge_in(turn: VoiceTurn, max_secs: float) -> bool:
    remaining = max(0.0, float(max_secs))
    loop = asyncio.get_running_loop()
    while remaining > 0 and _owns(turn):
        slice_secs = min(_BARGE_WATCH_SLICE_SECS, remaining)
        async with _get_listen_lock():
            if not _owns(turn):
                return False
            interrupted = await loop.run_in_executor(
                None, stt.watch_barge_in, slice_secs
            )
        if not _owns(turn):
            return False
        if interrupted:
            return True
        remaining -= slice_secs
    return False


def _latency_payload(
    turn: VoiceTurn, outcome: str, provider: str
) -> dict:
    offsets = {
        stage: round(max(0.0, (turn.marks[stage] - turn.started_at) * 1000), 3)
        for stage in _STAGES
        if stage in turn.marks
    }
    ttfa = None
    if "final_transcript" in turn.marks and "first_audio" in turn.marks:
        ttfa = round(
            max(
                0.0,
                (turn.marks["first_audio"] - turn.marks["final_transcript"]) * 1000,
            ),
            3,
        )
    target = tts.FIRST_FLUSH_MS
    return {
        "version": 1,
        "turn_epoch": turn.epoch,
        "outcome": outcome,
        "provider": provider,
        "offsets_ms": offsets,
        "ttfa_ms": ttfa,
        "target_ms": target,
        "target_met": ttfa is not None and ttfa <= target,
    }


def _publish_latency(
    turn: VoiceTurn, outcome: str, provider: str
) -> asyncio.Task | None:
    if not _owns(turn):
        return None
    payload = _latency_payload(turn, outcome, provider)

    async def _send() -> None:
        try:
            await bus.emit("voice_latency", payload)
        except Exception:
            pass

    task = asyncio.create_task(_send())
    _metric_tasks.add(task)

    def _done(done: asyncio.Task) -> None:
        _metric_tasks.discard(done)
        try:
            done.exception()
        except (asyncio.CancelledError, Exception):
            pass

    task.add_done_callback(_done)
    return task


def _superseded(turn: VoiceTurn) -> dict:
    return {"reply": "", "superseded": True, "turn_epoch": turn.epoch}


def _provider(result: dict) -> str:
    return str(result.get("provider") or settings.get("llm_provider", "unknown"))


async def voice_cycle() -> dict:
    global _busy
    if settings.get("mic_muted", False):
        msg = "Estás muteado (🎙⛔). Quita el mute para que pueda oírte."
        await bus.emit(
            "chat",
            {
                "user": "[voz]",
                "reply": msg,
                "provider": "sistema",
                "skill": None,
            },
        )
        if _current_turn is None or not _owns(_current_turn):
            await bus.emit("state", "idle")
        return {"reply": msg, "muted": True}

    turn = _reserve_turn()
    try:
        with (
            bus.guard_transient(turn.is_current),
            tts.bind_turn(turn),
        ):
            await tts.stop(turn=turn)
            if not _owns(turn):
                return _superseded(turn)

            text = await asyncio.wait_for(_listen_once(turn), timeout=40)
            if not _owns(turn):
                return _superseded(turn)
            if not text:
                st = stt.stt_status()
                if st["engine"] == "whisper":
                    msg = "No he detectado voz. Prueba otra vez, más cerca del micro."
                else:
                    msg = (
                        "Aún no tengo oído: falta la voz real. Instálala con "
                        "`pip install -r requirements-voice.txt` — OJO: faster-whisper "
                        "todavía no soporta Python 3.14; usa un venv con Python 3.11 o 3.12 "
                        "(instalable desde python.org, y run.bat lo detecta solo)."
                    )
                await bus.emit(
                    "chat",
                    {
                        "user": "[voz]",
                        "reply": msg,
                        "provider": "sistema",
                        "skill": None,
                    },
                )
                await bus.emit("state", "idle")
                return {"reply": msg, "turn_epoch": turn.epoch}

            turn.mark("final_transcript")
            turn.mark("brain_start")
            result = await asyncio.wait_for(
                brain.process(text, source="voice", stream_voice=True), timeout=120
            )
            if not _owns(turn):
                return _superseded(turn)
            if not result.get("spoken"):
                await tts.speak(result["reply"])
            if not _owns(turn):
                return _superseded(turn)
            turn.mark("completion")
            result["turn_epoch"] = turn.epoch
            _publish_latency(turn, "completed", _provider(result))
            return result
    except asyncio.TimeoutError:
        if not _owns(turn):
            return _superseded(turn)
        await bus.emit(
            "log",
            {
                "level": "warn",
                "msg": "Voz: se tardó demasiado; reinicio el ciclo (botón libre).",
            },
        )
        await bus.emit("state", "idle")
        return {"reply": ""}
    except Exception as exc:                                   # noqa: BLE001
        if not _owns(turn):
            return _superseded(turn)
        await bus.emit(
            "log",
            {"level": "error", "msg": f"Ciclo de voz: {type(exc).__name__}: {exc}"},
        )
        await bus.emit("state", "idle")
        return {"reply": ""}
    finally:
        if _busy is turn:
            _busy = None


async def _open_mic_turn(turn: VoiceTurn) -> dict:
    with (
        bus.guard_transient(turn.is_current),
        tts.bind_turn(turn),
    ):
        if not _owns(turn):
            return _superseded(turn)
        try:
            await bus.emit("state", "listening")
            text = await asyncio.wait_for(
                _listen_once(turn, announce=False), timeout=40
            )
            if not _owns(turn):
                return _superseded(turn)
            if text:
                turn.mark("final_transcript")
                turn.mark("brain_start")
                result = await asyncio.wait_for(
                    brain.process(text, source="voice", stream_voice=True), timeout=120)
                if not _owns(turn):
                    return _superseded(turn)
                talk_secs = (float(result.get("spoken_secs") or 0.0) if result.get("spoken")
                             else (await tts.speak(result["reply"]) or 0.0))
                if not _owns(turn):
                    return _superseded(turn)
                await bus.emit("state", "idle")
                # BARGE-IN + ANTI-ECO en uno: mientras nexus habla, VIGILA el micro.
                #  · Si HABLAS → corta la voz de la IA al instante y sale ya para
                #    capturarte (el bucle vuelve a listen_once de inmediato).
                #  · Si NO hablas → hace de espera hasta que nexus CALLA del todo, así
                #    el micro no se re-arma sobre su propia voz (bug de «no me oía justo
                #    al responder»). +0.3 s de colchón para que el audio termine.
                if talk_secs > 0.4:
                    interrupted = await _watch_barge_in(turn, talk_secs + 0.3)
                    if not _owns(turn):
                        return _superseded(turn)
                    if interrupted and _owns(turn):
                        await tts.stop(turn=turn)      # manda al HUD callar YA
                        await bus.emit("log", {"level": "info",
                                               "msg": "🎙 Te he oído — te dejo hablar."})
                if not _owns(turn):
                    return _superseded(turn)
                turn.mark("completion")
                result["turn_epoch"] = turn.epoch
                _publish_latency(turn, "completed", _provider(result))
                return result
            else:
                await bus.emit("state", "idle")
                return {"reply": "", "turn_epoch": turn.epoch}
        except asyncio.TimeoutError:
            if _owns(turn):
                await bus.emit("state", "idle")
            return {"reply": "", "turn_epoch": turn.epoch}
        except Exception as exc:
            if not _owns(turn):
                return _superseded(turn)
            await bus.emit("log", {"level": "error", "msg": f"Micro abierto: {exc}"})
            await bus.emit("state", "idle")
            return {"reply": "", "turn_epoch": turn.epoch}


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

        turn = _reserve_turn()
        try:
            await _open_mic_turn(turn)
        finally:
            if _busy is turn:
                _busy = None
        await asyncio.sleep(0.2)   # pequeño respiro entre turnos
