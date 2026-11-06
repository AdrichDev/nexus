"""
nexus — Puente de Telegram REAL (control remoto bidireccional).

Sin librerías extra: long-polling directo contra la Bot API con httpx.
Configuración (5 min): habla con @BotFather en Telegram → /newbot → copia el
token en .env como TELEGRAM_BOT_TOKEN. Escribe a tu bot y nexus te contesta:
todo lo que puedes pedir en el HUD, desde el móvil.

Seguridad (SEC-02 de la auditoría del 30/07/2026, roadmap P1-2): antes el PRIMER
chat que escribiera al bot quedaba registrado como propietario para siempre
(«trust on first use»): quien conociera el @usuario del bot ganaba el equipo y al
dueño legítimo se le ignoraba. Ahora vincular exige un código de un solo uso que
SOLO se muestra en este equipo (`pending_link_code()` y `GET /api/telegram/link`,
solo loopback), caduca según `telegram.ttl_vinculacion_segundos` de
config/umbrales.json (10 min de reserva) y se consume al usarlo. Mientras no haya
propietario, el bot no ejecuta nada: solo contesta cómo vincularse. Si ya hay
propietario registrado (`data/telegram_owner.txt` no vacío) todo sigue igual y
SOLO ese chat puede dar órdenes.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import secrets
import time

import httpx


from ..comun.config import CONFIG_DIR, DATA_DIR
from ..comun.events import bus

OWNER_FILE = DATA_DIR / "telegram_owner.txt"
# Código de vinculación pendiente: dos líneas, el código y cuándo se creó (en
# segundos, como `_ahora()`), para poder caducarlo sin esperar a nada.
LINK_CODE_FILE = DATA_DIR / "telegram_link_code.txt"

# Sin caracteres que se confunden al copiarlo del HUD al móvil (0/O, 1/I/L).
_ALFABETO_CODIGO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_LARGO_CODIGO = 8            # 8 de 31 símbolos ≈ 39,6 bits: no se adivina
_TTL_RESERVA_SEG = 600       # 10 min; el valor de verdad está en umbrales.json

ENLACE_OK = ("🟢 nexus enlazado. Este chat queda registrado "
             "como propietario. A sus órdenes.")
AVISO_CODIGO_MALO = ("🔒 Código incorrecto o caducado. Saca uno nuevo en nexus, "
                     "en ESTE equipo, y mándamelo aquí tal cual.")
_AVISO_SIN_VINCULAR = ("🔒 Este chat no está vinculado a nexus, así que no puedo "
                       "obedecer nada desde aquí. Abre nexus en el equipo, saca "
                       "el código de vinculación de Telegram (/api/telegram/link) "
                       "y mándamelo aquí tal cual. Caduca a los {minutos} minutos "
                       "y solo sirve una vez.")


def _ahora() -> float:
    """El reloj del módulo.

    Existe como función, y no como `time.time()` suelto, para poder simularlo en
    las pruebas: un TTL de 10 minutos no se espera dentro de un test."""
    return time.time()


def ttl_vinculacion_segundos() -> int:
    """Cuánto vive un código de vinculación.

    Se lee de `config/umbrales.json` («telegram.ttl_vinculacion_segundos»), con
    reserva del código si el archivo falta, está roto o el valor no vale: un
    umbral mal escrito no puede dejar la vinculación sin caducidad."""
    try:
        f = CONFIG_DIR / "umbrales.json"
        if f.is_file():
            leido = (json.loads(f.read_text(encoding="utf-8")) or {}).get("telegram") or {}
            valor = leido.get("ttl_vinculacion_segundos")
            if isinstance(valor, (int, float)) and not isinstance(valor, bool) and valor > 0:
                return int(valor)
    except Exception:                                     # noqa: BLE001
        pass
    return _TTL_RESERVA_SEG


def _aviso_no_vinculado() -> str:
    minutos = max(1, ttl_vinculacion_segundos() // 60)
    return _AVISO_SIN_VINCULAR.format(minutos=minutos)


def _token() -> str:
    from ..comun.config import settings
    return settings.secret("telegram_bot_token") or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def _escribir_privado(ruta, texto: str) -> None:
    """Escribe un archivo que solo debe poder leer el dueño del equipo (0600).

    Se escribe a pelo con `os.open` en vez de `write_text` porque el modo hay que
    darlo al CREAR: un archivo creado con los permisos del sistema y "arreglado"
    después deja una ventana en la que cualquiera lo lee."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(ruta), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(texto)


def _codigo_nuevo() -> str:
    """Un código nuevo del alfabeto sin equívocos, con `secrets` (no `random`)."""
    return "".join(secrets.choice(_ALFABETO_CODIGO) for _ in range(_LARGO_CODIGO))


def pending_link_code() -> str:
    """Genera, guarda y devuelve un código de vinculación NUEVO.

    Solo se llama desde este equipo (HUD / `GET /api/telegram/link`): cada
    llamada anula el código anterior, así que en cada momento hay uno solo."""
    codigo = _codigo_nuevo()
    _escribir_privado(LINK_CODE_FILE, f"{codigo}\n{int(_ahora())}\n")
    return codigo


def _borrar_codigo() -> None:
    """Marca un código como usado (o caducado): deja de valer para siempre."""
    try:
        LINK_CODE_FILE.unlink()
    except OSError:
        pass


def _codigo_pendiente() -> str:
    """El código vigente, o "" si no hay ninguno o ya caducó (y lo invalida)."""
    try:
        if not LINK_CODE_FILE.is_file():
            return ""
        partes = LINK_CODE_FILE.read_text(encoding="utf-8").split()
        if len(partes) < 2 or not partes[1].isdigit():
            _borrar_codigo()
            return ""
        codigo, creado = partes[0].strip(), int(partes[1])
    except Exception:                                     # noqa: BLE001
        return ""
    if _ahora() - creado > ttl_vinculacion_segundos():
        _borrar_codigo()                # caducado: no vuelve a valer nunca
        return ""
    return codigo


def _propietario() -> str:
    """El chat propietario registrado ("" si todavía no hay)."""
    try:
        return OWNER_FILE.read_text(encoding="utf-8").strip() if OWNER_FILE.is_file() else ""
    except OSError:
        return ""


def _guardar_propietario(chat_id: str) -> None:
    _escribir_privado(OWNER_FILE, chat_id)


def _posible_codigo(texto: str) -> str | None:
    """¿Este mensaje pretende vincular? Devuelve el intento; None si no.

    Vale el código a secas y «/start <código>» (lo que sugiere la Bot API). Un
    «/start» vacío SÍ es un intento (y se rechaza): así el chat recibe «código
    incorrecto o caducado» en vez de la pista de siempre."""
    t = (texto or "").strip()
    if not t:
        return None
    if t.startswith("/"):
        partes = t.split(None, 1)
        if partes[0].lower().split("@")[0] != "/start":
            return None
        return partes[1].strip() if len(partes) > 1 else ""
    if " " in t or len(t) < 6:
        return None
    return t


async def _responder(cli, api: str, chat_id: str, texto: str) -> None:
    await cli.post(f"{api}/sendMessage", json={"chat_id": chat_id,
                                               "text": (texto or "")[:4000]})


async def _atender_sin_propietario(cli, api: str, chat_id: str, texto: str) -> str:
    """Sin propietario: nadie manda nada y SOLO un código vigente vincula."""
    esperado = _codigo_pendiente()
    intento = _posible_codigo(texto)
    if intento is not None:
        # Comparación en tiempo constante, como la cabecera de n8n: adivinar el
        # código carácter a carácter midiendo lo que tarda no debe ser posible.
        if esperado and hmac.compare_digest(intento.strip().upper(), esperado):
            _guardar_propietario(chat_id)
            _borrar_codigo()                    # de un solo uso
            await _responder(cli, api, chat_id, ENLACE_OK)
            await bus.emit("log", {"level": "ok",
                                   "msg": "[TELEGRAM] chat vinculado con un código de un solo uso"})
            return chat_id
        await _responder(cli, api, chat_id, AVISO_CODIGO_MALO)
        return ""
    await _responder(cli, api, chat_id, _aviso_no_vinculado())
    return ""


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


async def atender_update(cli, api: str, token: str, upd: dict, owner: str) -> str:
    """Atiende UNA actualización y devuelve el propietario que queda.

    Es la unidad del bucle, separada para poder probarla en proceso con un
    cliente de mentira: sin red, sin long-polling y sin tocar el equipo."""
    msg = upd.get("message") or {}
    chat_id = str(msg.get("chat", {}).get("id", ""))
    texto = (msg.get("text") or "").strip()
    voz = msg.get("voice") or msg.get("audio") or msg.get("video_note")
    if not chat_id or (not texto and not voz):
        return owner
    if not owner:
        # NADIE se registra por escribir: hace falta el código de vinculación.
        return await _atender_sin_propietario(cli, api, chat_id, texto)
    if chat_id != owner:
        return owner                                 # ignora desconocidos
    # Nota de voz / audio → transcribir y tratarlo como orden
    if voz and not texto:
        await bus.emit("log", {"level": "cmd", "msg": "[TELEGRAM] 🎙 nota de voz"})
        texto = await _transcribe_tg(cli, api, token, voz.get("file_id", ""))
        if not texto:
            await _responder(cli, api, chat_id,
                             "No pude transcribir el audio. ¿Se oye claro? "
                             "(necesita faster-whisper instalado — ejecuta run.bat).")
            return owner
        await _responder(cli, api, chat_id, f"🎙 Te he entendido: «{texto}»")
    from ..aplicacion import brain
    await bus.emit("log", {"level": "cmd", "msg": f"[TELEGRAM] {texto}"})
    # source="text" (NO "telegram"): con un source raro medio cerebro
    # se apagaba (enrutador inteligente, PM, persistencia solo actúan
    # con text/voice) → todo caía al LLM y se ponía a NARRAR en vez de
    # ejecutar. El canal viaja aparte para responder solo por Telegram.
    result = await brain.process(texto, source="text", channel="telegram")
    await _responder(cli, api, chat_id, result["reply"][:4000] or "Hecho.")
    return owner


async def telegram_loop():
    token = _token()
    if not token:
        return  # sin token no arranca (silencioso: es opcional)
    api = f"https://api.telegram.org/bot{token}"
    offset = 0
    owner = _propietario()

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
                    owner = await atender_update(cli, api, token, upd, owner)
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
