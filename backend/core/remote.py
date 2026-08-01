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
def nombre_local() -> str:
    """El nombre de red de este PC, en forma «equipo.local» (mDNS).

    ES LA DIRECCIÓN QUE NO CAMBIA. La IP de la WiFi la reparte el router y baila
    con cada reinicio; el nombre del equipo no. Windows 10+ responde a mDNS de
    serie y Android lo resuelve, así que «MIPC.local» sigue valiendo dentro de
    casa después de apagar el ordenador mil veces. Sin cuentas, sin servicios,
    sin nada que caduque."""
    try:
        n = socket.gethostname().strip().split(".")[0]
        return f"{n}.local" if n and n.lower() != "localhost" else ""
    except Exception:
        return ""


_alcance_cache: dict = {}


def responde(host_puerto: str, timeout: float = 0.6, cache_seg: float = 30.0) -> bool:
    """¿Hay algo escuchando de verdad en «maquina:puerto»?

    POR QUÉ EXISTE (31/07/2026). Esta lista prometía direcciones que NO
    aceptaban conexiones: uvicorn estaba atado solo a 127.0.0.1, así que el QR
    llevaba a «MIPC.local:8177» y el móvil se comía un «rechazada» sin más
    explicación. Ofrecer una dirección muerta es peor que no ofrecerla: el móvil
    la prueba, falla, y el usuario no sabe si el fallo es suyo o del PC.

    OJO CON LO QUE ESTO *NO* PRUEBA: se comprueba desde este mismo equipo, y el
    cortafuegos de Windows puede dejar pasar al propio PC y bloquear al móvil.
    Que salga True significa «el puerto está abierto aquí», no «tu móvil llega»."""
    ahora = time.time()
    prev = _alcance_cache.get(host_puerto)
    if prev and ahora - prev[0] < cache_seg:
        return prev[1]
    ok = False
    try:
        maquina, _, puerto = host_puerto.rpartition(":")
        with socket.create_connection((maquina, int(puerto)), timeout=timeout):
            ok = True
    except Exception:
        ok = False                          # cerrado, filtrado o nombre que no resuelve
    _alcance_cache[host_puerto] = (ahora, ok)
    return ok


def direcciones() -> list[dict]:
    """TODAS las formas de llegar a este nexus, de más estable a menos.

    El móvil se queda con la lista entera, no con una sola. Ese era el fallo de
    raíz: guardaba UNA dirección (la del túnel, que es aleatoria en cada
    arranque) y al reiniciar el PC se quedaba huérfano y había que revincular.
    Con la lista, prueba una por una y se queda con la que conteste.

    Las direcciones de red se SONDEAN antes de ofrecerlas (ver `responde`) y cada
    una sale marcada con «verificada». La del túnel no se sondea: vive en el borde
    de Cloudflare y comprobarla cuesta una vuelta a internet en cada refresco del
    HUD; que cloudflared haya registrado la conexión ya es señal de que está viva.

    OJO CON EL FILTRO, que casi la lío (31/07/2026). Al principio las no
    verificadas se TIRABAN. Si no contestaba ninguna —nexus levantándose todavía,
    el cortafuegos de por medio— la lista salía VACÍA y el QR se quedaba sin nada
    que ofrecer. Eso es peor que una dirección dudosa: con una dudosa el móvil al
    menos lo intenta; sin ninguna, ni eso, y encima no hay nada que explique por
    qué. Así que la regla es: se descartan las muertas SOLO si queda alguna viva."""
    cand: list[dict] = []
    ts = tailscale_url()
    if ts:
        cand.append({"host": ts, "esquema": "http", "tipo": "tailscale",
                     "estable": True, "desde": "cualquier red",
                     "verificada": responde(ts)})
    nl = nombre_local()
    if nl:
        cand.append({"host": f"{nl}:8177", "esquema": "http", "tipo": "nombre",
                     "estable": True, "desde": "tu casa",
                     "verificada": responde(f"{nl}:8177")})
    ip = lan_ip()
    if ip and ip != "127.0.0.1":
        cand.append({"host": f"{ip}:8177", "esquema": "http", "tipo": "wifi",
                     "estable": False, "desde": "tu casa",
                     "verificada": responde(f"{ip}:8177")})

    vivas = [d for d in cand if d["verificada"]]
    out = vivas if vivas else cand             # nunca vacía por culpa del sondeo

    if _state["url"]:
        out = out + [{"host": _state["url"].replace("https://", ""), "esquema": "https",
                      "tipo": "tunel", "estable": False, "desde": "cualquier red",
                      "verificada": True}]     # no se sondea: cloudflared ya la registró
    return out


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ------------------------------------------------------------------ tailscale
# POR QUÉ EXISTE (decisión de Adri, 30/07/2026)
# ---------------------------------------------
# El túnel «quick» de Cloudflare da una dirección DISTINTA cada vez que arranca
# (https://<algo-aleatorio>.trycloudflare.com). El móvil se guarda esa URL para
# siempre, así que en cuanto se reinicia el PC —o se cae cloudflared— la
# dirección guardada ya no existe y hay que volver a escanear el QR. El token no
# era el problema: la dirección sí.
#
# Tailscale resuelve justo eso: monta una red privada entre TUS aparatos y le da
# a cada uno una IP FIJA (100.x.y.z) que no cambia nunca, ni al reiniciar, ni al
# cambiar de WiFi, ni al salir a 4G. Y además nexus deja de estar publicado en
# internet: solo lo ven los dispositivos de tu propia red de Tailscale.
#
# Requisito honesto: Tailscale tiene que estar instalado y con sesión iniciada
# en LOS DOS aparatos (el PC y el móvil), con la misma cuenta. El plan gratuito
# llega de sobra. Sigue haciendo falta el token del QR: una IP de Tailscale no
# es «este equipo», así que pasa por el mismo control que todo lo demás.
TAILSCALE_WEB = "https://tailscale.com/download"
_ts_cache: dict = {"t": 0.0, "datos": None}


def _tailscale_exe() -> str:
    """Ruta del ejecutable de tailscale, o '' si no está instalado."""
    import shutil
    exe = shutil.which("tailscale")
    if exe:
        return exe
    if sys.platform == "win32":
        for c in (r"C:\Program Files\Tailscale\tailscale.exe",
                  r"C:\Program Files (x86)\Tailscale\tailscale.exe"):
            if Path(c).exists():
                return c
    for c in ("/Applications/Tailscale.app/Contents/MacOS/Tailscale",
              "/usr/bin/tailscale", "/usr/local/bin/tailscale"):
        if Path(c).exists():
            return c
    return ""


def tailscale_status(cache_seg: float = 20.0) -> dict:
    """Estado real de Tailscale en ESTE equipo.

    {instalado, activo, ip, host, dispositivos, error}. Nunca lanza: si algo
    falla, `activo` es False y `error` explica qué pasa en cristiano."""
    ahora = time.time()
    if _ts_cache["datos"] is not None and ahora - _ts_cache["t"] < cache_seg:
        return _ts_cache["datos"]
    info = {"instalado": False, "activo": False, "ip": "", "host": "",
            "dispositivos": 0, "error": ""}
    exe = _tailscale_exe()
    if not exe:
        info["error"] = ("Tailscale no está instalado en este equipo. "
                         f"Se descarga en {TAILSCALE_WEB} (el plan gratis sobra).")
        _ts_cache.update(t=ahora, datos=info)
        return info
    info["instalado"] = True
    try:
        import json as _json
        r = subprocess.run([exe, "status", "--json"], capture_output=True, text=True,
                           timeout=10,
                           creationflags=(subprocess.CREATE_NO_WINDOW
                                          if sys.platform == "win32" else 0))
        if r.returncode != 0:
            info["error"] = ("Tailscale está instalado pero no ha arrancado sesión. "
                             "Ábrelo e inicia sesión con tu cuenta.")
            _ts_cache.update(t=ahora, datos=info)
            return info
        d = _json.loads(r.stdout or "{}")
        yo = d.get("Self") or {}
        ips = [x for x in (yo.get("TailscaleIPs") or []) if ":" not in x]   # IPv4
        info["ip"] = ips[0] if ips else ""
        info["host"] = (yo.get("DNSName") or "").rstrip(".")
        info["dispositivos"] = len(d.get("Peer") or {})
        estado = (d.get("BackendState") or "").lower()
        info["activo"] = bool(info["ip"]) and estado == "running"
        if not info["activo"]:
            info["error"] = ("Tailscale está instalado pero no conectado "
                             f"(estado: {estado or 'desconocido'}). Ábrelo e inicia sesión.")
    except FileNotFoundError:
        info["error"] = "Tailscale no está instalado en este equipo."
        info["instalado"] = False
    except subprocess.TimeoutExpired:
        info["error"] = "Tailscale ha tardado demasiado en contestar."
    except Exception as exc:                                        # noqa: BLE001
        info["error"] = f"No he podido leer el estado de Tailscale ({type(exc).__name__})."
    _ts_cache.update(t=ahora, datos=info)
    return info


def tailscale_url() -> str:
    """La dirección ESTABLE del PC, o '' si Tailscale no está listo."""
    ts = tailscale_status()
    return f"{ts['ip']}:8177" if ts.get("activo") and ts.get("ip") else ""


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
    """Estado de la vinculación, con la MEJOR dirección disponible.

    Orden de preferencia, y el porqué:
      1. TAILSCALE — IP fija (100.x.y.z). Sobrevive a reinicios y a cambios de
         red, y no publica nada en internet. Es la buena.
      2. TÚNEL de Cloudflare — llega desde fuera, pero la dirección cambia en
         cada arranque, así que el móvil hay que revincularlo cada vez.
      3. IP de la WiFi — solo sirve dentro de casa.
    """
    alive = bool(_state["proc"] and _state["proc"].poll() is None and _state["url"])
    dirs = direcciones()
    # La PRIMERA es la que abre el móvil; el resto van en el QR como respaldo,
    # para que el enlace sobreviva a que una de ellas deje de valer.
    principal = dirs[0] if dirs else {"host": f"{lan_ip()}:8177", "esquema": "http",
                                      "tipo": "wifi", "estable": False}
    host, esquema, via = principal["host"], principal["esquema"], principal["tipo"]
    alternativas = ",".join(f"{d['esquema']}://{d['host']}" for d in dirs[1:])
    link = (f"{esquema}://{host}/m?host={host}&token={link_token()}"
            + (f"&alt={alternativas}" if alternativas else ""))
    return {"tunnel": alive, "url": _state["url"], "error": _state["error"],
            "lan": f"{lan_ip()}:8177", "link": link, "token": link_token(),
            "devices": devices(), "paired": len(_devices),
            "via": via, "estable": bool(principal.get("estable")),
            "hosts": dirs, "nombre_local": nombre_local(),
            "tailscale": tailscale_status()}


# ------------------------------------------------------------------ QR
def qr_png(data: str) -> bytes:
    """PNG del QR (qrcode + pillow; run.bat los instala)."""
    import qrcode
    img = qrcode.make(data, box_size=9, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
