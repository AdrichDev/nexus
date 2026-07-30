"""
nexus — Vinculación remota del móvil (QR + túnel, SIN misma WiFi).

Cómo funciona:
  1. El PC arranca un túnel público con cloudflared («quick tunnel», gratis y
     sin cuenta): https://<algo>.trycloudflare.com → tu nexus local.
  2. Se genera un TOKEN de vinculación (config/secrets.json → link_token).
  3. El HUD muestra un QR con la URL del túnel + el token.
  4. El móvil escanea el QR y ya habla con tu PC desde CUALQUIER red (4G/5G,
     otra WiFi…), autenticado con el token (middleware en app.py).

Si cloudflared no está: se intenta DESCARGAR solo (GitHub oficial) a la
carpeta config/; si tampoco se puede, se da el enlace para bajarlo a mano.
Plan B sin túnel: QR con la IP local (solo misma WiFi).
"""
from __future__ import annotations

import asyncio
import io
import re
import secrets as pysecrets
import socket
import subprocess
import sys
import time
from pathlib import Path

from .config import ROOT, settings

CLOUDFLARED_URL_WIN = ("https://github.com/cloudflare/cloudflared/releases/"
                       "latest/download/cloudflared-windows-amd64.exe")
CLOUDFLARED_PAGE = "https://github.com/cloudflare/cloudflared/releases/latest"

_state = {"proc": None, "url": "", "starting": False, "error": ""}


# ------------------------------------------------------------------ dispositivos
# Registro EN MEMORIA de los móviles vinculados y conectados AHORA. El móvil,
# nada más enlazar por WS, se presenta con un «hello» (ver app.py) y aquí queda
# apuntado; al desconectarse se borra. El HUD lo consulta por /api/link/status
# y recibe eventos 'paired'/'unpaired' por el bus para cerrar el QR y mostrarlo.
_devices: dict[str, dict] = {}


def register_device(info: dict) -> dict:
    """Apunta (o refresca) un móvil vinculado. Devuelve la ficha del dispositivo."""
    did = (str(info.get("id") or "").strip() or pysecrets.token_hex(4))
    prev = _devices.get(did, {})
    dev = {
        "id": did,
        "name": (str(info.get("name") or "").strip() or "Móvil")[:40],
        "ua": str(info.get("ua") or "")[:200],
        "ip": str(info.get("ip") or "")[:60],
        "since": prev.get("since") or time.strftime("%H:%M"),
        "last": time.strftime("%H:%M"),
        "ts": time.time(),
        "online": True,
    }
    _devices[did] = dev
    return dev


def forget_device(did: str) -> None:
    _devices.pop(str(did), None)


def mark_offline(did: str) -> None:
    """El WS del móvil se ha cortado (pantalla bloqueada / app en 2º plano).
    NO se desvincula: queda «en espera» — antes el HUD decía «no vinculado» en
    cuanto bloqueabas el móvil, y eso es mentira (bug reportado por Adri)."""
    d = _devices.get(str(did))
    if d:
        d["online"] = False
        d["ts_off"] = time.time()


def is_online(did: str) -> bool:
    d = _devices.get(str(did))
    return bool(d and d.get("online", True))


def devices() -> list:
    """Móviles conectados ahora, el más reciente primero."""
    return sorted(_devices.values(), key=lambda d: d.get("ts", 0), reverse=True)


# ------------------------------------------------------------------ token
def link_token() -> str:
    tok = settings.secret("link_token")
    if not tok:
        tok = pysecrets.token_urlsafe(18)
        settings.set_secret("link_token", tok)
    return tok


def rotate_token() -> str:
    settings.set_secret("link_token", pysecrets.token_urlsafe(18))
    return settings.secret("link_token")


# ------------------------------------------------------------------ red local
def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ------------------------------------------------------------------ cloudflared
def _cloudflared_path() -> Path | None:
    """Busca cloudflared: PATH del sistema o config/cloudflared.exe."""
    import shutil
    exe = shutil.which("cloudflared")
    if exe:
        return Path(exe)
    local = ROOT / "config" / ("cloudflared.exe" if sys.platform == "win32" else "cloudflared")
    return local if local.exists() else None


async def _download_cloudflared() -> Path | None:
    """Descarga cloudflared oficial a config/ (Windows). None si no se pudo."""
    if sys.platform != "win32":
        return None
    dest = ROOT / "config" / "cloudflared.exe"
    try:
        import httpx
        async with httpx.AsyncClient(timeout=180, follow_redirects=True) as cli:
            r = await cli.get(CLOUDFLARED_URL_WIN)
            r.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(r.content)
        return dest
    except Exception:
        return None


async def start_tunnel() -> dict:
    """Arranca el quick tunnel (si no está ya). Devuelve el estado."""
    if _state["url"] and _state["proc"] and _state["proc"].poll() is None:
        return status()
    if _state["starting"]:
        return status()
    _state.update(starting=True, error="", url_pending="")
    try:
        # LIMPIEZA: cada reinicio del PC con taskkill deja el cloudflared anterior
        # VIVO (es un proceso hijo aparte) con un túnel viejo colgando. Se matan
        # antes de abrir el nuevo para que no se acumulen ni confundan.
        if sys.platform == "win32":
            try:
                subprocess.run(["taskkill", "/F", "/IM", "cloudflared.exe"],
                               capture_output=True, timeout=8,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            except Exception:
                pass
        exe = _cloudflared_path()
        if exe is None:
            exe = await _download_cloudflared()
        if exe is None:
            _state["error"] = ("cloudflared no está instalado y no he podido descargarlo. "
                               f"Bájalo aquí y déjalo en config/: {CLOUDFLARED_PAGE}")
            return status()
        proc = subprocess.Popen(
            [str(exe), "tunnel", "--url", "http://127.0.0.1:8177", "--no-autoupdate"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0))
        _state["proc"] = proc

        def _read_url():
            pend = ""
            for line in proc.stdout:                      # type: ignore[union-attr]
                if not pend:
                    m = re.search(r"https://[\w\-]+\.trycloudflare\.com", line)
                    if m:
                        pend = m.group(0)
                        _state["url_pending"] = pend
                        continue
                # el túnel FUNCIONA cuando cloudflared registra la conexión con el
                # borde («Registered tunnel connection»); hasta entonces la URL
                # existe pero devuelve 530 y el móvil dice «túnel caído».
                if pend and ("Registered tunnel connection" in line
                             or "registered connIndex" in line.lower()):
                    _state["url"] = pend
                    return

        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(loop.run_in_executor(None, _read_url), timeout=30)
        except asyncio.TimeoutError:
            if _state.get("url_pending"):
                # URL impresa pero sin ver el registro en el log: úsala igualmente
                _state["url"] = _state["url_pending"]
            else:
                _state["error"] = "El túnel no ha dado URL en 30 s (¿internet caído?)."
    finally:
        _state["starting"] = False
    return status()


def stop_tunnel() -> None:
    if _state["proc"] and _state["proc"].poll() is None:
        try:
            _state["proc"].terminate()
        except Exception:
            pass
    _state.update(proc=None, url="", url_pending="", starting=False)


def status() -> dict:
    alive = bool(_state["proc"] and _state["proc"].poll() is None and _state["url"])
    host = _state["url"].replace("https://", "") if alive else f"{lan_ip()}:8177"
    link = (f"{'https' if alive else 'http'}://{host}/m"
            f"?host={host}&token={link_token()}")
    return {"tunnel": alive, "url": _state["url"], "error": _state["error"],
            "lan": f"{lan_ip()}:8177", "link": link, "token": link_token(),
            "devices": devices(), "paired": len(_devices)}


# ------------------------------------------------------------------ QR
def qr_png(data: str) -> bytes:
    """PNG del QR (qrcode + pillow; run.bat los instala)."""
    import qrcode
    img = qrcode.make(data, box_size=9, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
