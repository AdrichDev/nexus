"""
nexus — Hotkey global F9 (manos libres).

Usa la librería `keyboard` (Windows: funciona sin privilegios especiales;
Linux requiere root, por eso es opcional). Al pulsar F9 se dispara el
ciclo completo: escuchar → transcribir → nexus → responder → hablar.
"""
from __future__ import annotations

import asyncio

from .config import settings
from .events import bus

try:
    import keyboard
    HAS_KEYBOARD = True
except Exception:
    HAS_KEYBOARD = False

_started = False


def start_hotkey(loop: asyncio.AbstractEventLoop) -> bool:
    """Registra F9 → voice_cycle(). Devuelve True si quedó activo."""
    global _started
    if _started or not HAS_KEYBOARD:
        return _started

    def _on_press():
        from .voice_cycle import voice_cycle  # import tardío (evita ciclos)
        asyncio.run_coroutine_threadsafe(voice_cycle(), loop)

    try:
        keyboard.add_hotkey(settings.get("hotkey", "f9"), _on_press)
        _started = True
        bus.emit_sync("log", {"level": "ok",
                              "msg": f"Hotkey global [{settings.get('hotkey', 'f9').upper()}] armada"})
    except Exception as exc:
        bus.emit_sync("log", {"level": "warn", "msg": f"Hotkey no disponible: {exc}"})
    return _started
