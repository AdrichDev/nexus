"""
nexus — Bus de eventos en tiempo real.

Todos los módulos publican eventos aquí y el WebSocket los reenvía al HUD:
    await bus.emit("log", {"level": "info", "msg": "..."})
Tipos usados por el frontend:
    log, alert, state (idle|listening|thinking|speaking), metrics,
    chat (respuesta del cerebro), skill (activación de skill),
    notification, reminder, boot
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any


class EventBus:
    def __init__(self):
        self._clients: set = set()          # WebSockets conectados
        self._loop: asyncio.AbstractEventLoop | None = None
        self.history: list[dict] = []       # últimos eventos (para reconexión)

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def register(self, ws) -> None:
        self._clients.add(ws)

    def unregister(self, ws) -> None:
        self._clients.discard(ws)

    async def emit(self, type_: str, data: Any = None) -> None:
        # specs v24 (T1/T2/T17): ÚLTIMA BARRERA antes de que algo llegue al chat.
        # Da igual qué módulo lo emita — aquí no pasa la fontanería interna
        # (subagentes, gateways, colas, códigos HTTP, trazas). Los eventos `log`
        # NO se tocan: ahí sí queremos el detalle técnico.
        if type_ in ("chat", "job_done") and isinstance(data, dict) and not data.get("admin"):
            try:
                from .publicvoice import sanitize
                data = dict(data)
                for campo in ("reply", "result", "error", "title"):
                    if data.get(campo):
                        data[campo] = sanitize(str(data[campo]))
            except Exception:
                pass
        evt = {"type": type_, "data": data, "ts": time.time()}
        self.history.append(evt)
        self.history = self.history[-200:]
        if type_ == "log":
            _persist_log(data)
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send_text(json.dumps(evt, ensure_ascii=False, default=str))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.unregister(ws)

    def emit_sync(self, type_: str, data: Any = None) -> None:
        """Para hilos sin loop propio (hotkey, scheduler, TTS...)."""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.emit(type_, data), self._loop)


_LOGF = [None]


def _persist_log(data) -> None:
    """Cada evento 'log' se APPENDEA a data/nexus.log (rotado a ~1 MB → .log.1).
    Antes los logs solo vivían en la memoria del HUD: al cerrar, imposible
    diagnosticar nada («los modelos fallan» y ni rastro del porqué)."""
    try:
        if _LOGF[0] is None:
            from pathlib import Path
            f = Path(__file__).resolve().parents[2] / "data" / "nexus.log"
            f.parent.mkdir(parents=True, exist_ok=True)
            _LOGF[0] = f
        f = _LOGF[0]
        try:
            if f.exists() and f.stat().st_size > 1_000_000:
                f.replace(f.with_name("nexus.log.1"))
        except OSError:
            pass
        d = data if isinstance(data, dict) else {"msg": str(data)}
        line = (time.strftime("%Y-%m-%d %H:%M:%S")
                + f" [{d.get('level', '?')}] {d.get('msg', '')}\n")
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        pass


bus = EventBus()


async def log(msg: str, level: str = "info") -> None:
    await bus.emit("log", {"level": level, "msg": msg})
