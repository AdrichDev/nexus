"""
nexus — Puente de Telegram REAL (control remoto bidireccional).

Sin librerías extra: long-polling directo contra la Bot API con httpx.
Configuración (5 min): habla con @BotFather en Telegram → /newbot → copia el
token en .env como TELEGRAM_BOT_TOKEN. Escribe a tu bot y nexus te contesta:
todo lo que puedes pedir en el HUD, desde el móvil.

Seguridad: el primer chat que escriba queda registrado como propietario
(data/telegram_owner.txt) y SOLO ese chat puede dar órdenes.
"""
from __future__ import annotations

import asyncio
import os

import httpx

from pathlib import Path
import tempfile

from .config import DATA_DIR
from .events import bus

OWNER_FILE = DATA_DIR / "telegram_owner.txt"


def _token() -> str:
    from .config import settings
    return settings.secret("telegram_bot_token") or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


async def _transcribe_tg(cli, api: str, token: str, file_id: str) -> str:
    """Descarga una nota de voz/audio de Telegram y la transcribe con Whisper."""
    if not file_id:
        return ""
    try:
        gf = (await cli.get(f"{api}/getFile", params={"file_id": file_id})).json()
        fpath = gf.get("result", {}).get("file_path")
        if not fpath:
            return ""
        data = (await cli.get(f"https://api.telegram.org/file/bot{token}/{fpath}")).content
        # SIN archivo temporal: faster-whisper decodifica un objeto tipo-fichero
        # (BytesIO) con PyAV. Así el .ogg/.oga nunca toca el disco y no puede
        # quedar bloqueado en Windows (WinError 32).
        import io
        from .stt import _get_model
        def _run():
            seg, _info = _get_model().transcribe(io.BytesIO(data), language="es", vad_filter=True)
            return " ".join(s.text.strip() for s in seg)
        return (await asyncio.to_thread(_run)).strip()
    except Exception as exc:
        await bus.emit("log", {"level": "warn", "msg": f"Telegram audio: {exc}"})
        return ""


async def telegram_loop():
    token = _token()
    if not token:
        return  # sin token no arranca (silencioso: es opcional)
    api = f"https://api.telegram.org/bot{token}"
    offset = 0
    owner = OWNER_FILE.read_text().strip() if OWNER_FILE.exists() else ""

    async with httpx.AsyncClient(timeout=40) as cli:
        try:
            me = (await cli.get(f"{api}/getMe")).json()
            name = me["result"]["username"]
            await bus.emit("log", {"level": "ok", "msg": f"Telegram ONLINE: @{name}"})
        except Exception as exc:
            await bus.emit("log", {"level": "warn", "msg": f"Telegram: token inválido ({exc})"})
            return

        while True:
            try:
                r = await cli.get(f"{api}/getUpdates",
                                  params={"offset": offset, "timeout": 30})
                for upd in r.json().get("result", []):
                    offset = upd["update_id"] + 1
                    msg = upd.get("message") or {}
                    chat_id = str(msg.get("chat", {}).get("id", ""))
                    text = (msg.get("text") or "").strip()
                    voice = msg.get("voice") or msg.get("audio") or msg.get("video_note")
                    if not chat_id or (not text and not voice):
                        continue
                    # Registro de propietario (primer chat que escriba)
                    if not owner:
                        owner = chat_id
                        OWNER_FILE.parent.mkdir(parents=True, exist_ok=True)
                        OWNER_FILE.write_text(owner, encoding="utf-8")
                        await cli.post(f"{api}/sendMessage", json={
                            "chat_id": chat_id,
                            "text": "🟢 nexus enlazado. Este chat queda registrado "
                                    "como propietario. A sus órdenes."})
                        continue
                    if chat_id != owner:
                        continue  # ignora desconocidos
                    # Nota de voz / audio → transcribir y tratarlo como orden
                    if voice and not text:
                        await bus.emit("log", {"level": "cmd", "msg": "[TELEGRAM] 🎙 nota de voz"})
                        text = await _transcribe_tg(cli, api, token, voice.get("file_id", ""))
                        if not text:
                            await cli.post(f"{api}/sendMessage", json={"chat_id": chat_id,
                                "text": "No pude transcribir el audio. ¿Se oye claro? "
                                        "(necesita faster-whisper instalado — ejecuta run.bat)."})
                            continue
                        await cli.post(f"{api}/sendMessage", json={"chat_id": chat_id,
                            "text": f"🎙 Te he entendido: «{text}»"})
                    from . import brain
                    await bus.emit("log", {"level": "cmd", "msg": f"[TELEGRAM] {text}"})
                    # source="text" (NO "telegram"): con un source raro medio cerebro
                    # se apagaba (enrutador inteligente, PM, persistencia solo actúan
                    # con text/voice) → todo caía al LLM y se ponía a NARRAR en vez de
                    # ejecutar. El canal viaja aparte para responder solo por Telegram.
                    result = await brain.process(text, source="text", channel="telegram")
                    await cli.post(f"{api}/sendMessage",
                                   json={"chat_id": chat_id,
                                         "text": result["reply"][:4000] or "Hecho."})
            except Exception as exc:
                await bus.emit("log", {"level": "warn", "msg": f"Telegram: {exc}"})
                await asyncio.sleep(5)


async def send_telegram(text: str) -> bool:
    """Envía un mensaje al propietario (para notificaciones proactivas)."""
    token = _token()
    if not token or not OWNER_FILE.exists():
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as cli:
            await cli.post(f"https://api.telegram.org/bot{token}/sendMessage",
                           json={"chat_id": OWNER_FILE.read_text().strip(),
                                 "text": text[:4000]})
        return True
    except Exception:
        return False
