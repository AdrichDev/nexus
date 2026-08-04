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
import json
import re
import secrets as pysecrets
import socket
import subprocess
import sys
import time
from pathlib import Path

from .comun.config import CONFIG_DIR, DATA_DIR, ROOT, settings

CLOUDFLARED_URL_WIN = ("https://github.com/cloudflare/cloudflared/releases/"
                       "latest/download/cloudflared-windows-amd64.exe")
CLOUDFLARED_PAGE = "https://github.com/cloudflare/cloudflared/releases/latest"

_state = {"proc": None, "url": "", "starting": False, "error": "",
          # «adoptado» = el túnel lo abrió un nexus ANTERIOR y este se ha
          # limitado a reutilizarlo, así que no tenemos su proceso. Ver
          # start_tunnel() y status(): sin esta marca, un túnel perfectamente
          # vivo salía como «caído» en el HUD por no tener `proc`.
          "adoptado": False}

# Dónde se apunta la URL del túnel para el arranque siguiente (data/ está en
# .gitignore). Ver `_guarda_tunel` / `start_tunnel`.
_TUNEL_FILE = DATA_DIR / "tunel.json"

# ─────────────────────────────────────────────────────────────────────────────
# Los números de red viven FUERA del código, en config/umbrales.json (sección
# «red»), como el resto de umbrales del proyecto. Lo de aquí abajo es el valor
# de reserva por si el archivo no está o está roto: nadie se queda sin sondeo
# por un JSON mal escrito.
_UMBRALES_RED_RESERVA = {"cache_sondeo_seg": 120.0}


def _carga_umbrales_red() -> dict:
    """Lee la sección «red» de config/umbrales.json sobre los de reserva."""
    vals = dict(_UMBRALES_RED_RESERVA)
    try:
        f = CONFIG_DIR / "umbrales.json"
        if f.is_file():
            leido = (json.loads(f.read_text(encoding="utf-8")) or {}).get("red") or {}
            for k, v in leido.items():
                if k in vals and isinstance(v, (int, float)) and not isinstance(v, bool):
                    vals[k] = float(v)
    except Exception:
        pass
    return vals


# CUIDADO AL TOCAR ESTE NÚMERO: tiene que ser MAYOR que el intervalo con el que
# el HUD pregunta por los dispositivos (45 s, `setInterval(refreshDevices, 45000)`
# en frontend/js/command.js). Estaba en 30 s, o sea SIEMPRE por debajo: cada
# refresco encontraba la caché caducada y volvía a pagar la resolución mDNS
# entera (4,25 s medidos aquí), que es lo que congelaba nexus. Una caché que dura
# menos que el intervalo de sondeo no cachea nada.
_CACHE_SONDEO = float(_carga_umbrales_red()["cache_sondeo_seg"])


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


def responde(host_puerto: str, timeout: float = 0.6, cache_seg: float | None = None) -> bool:
    """¿Hay algo escuchando de verdad en «maquina:puerto»?

    OJO CON `timeout` (01/08/2026): NO cubre la resolución del nombre. Aquí
    dentro `create_connection` primero llama a `getaddrinfo`, y resolver
    «TUPC.local» por mDNS tarda 4,25 s medidos en este equipo por muy bajo que
    pongas el timeout. Por eso esta función NO se puede llamar desde el bucle de
    asyncio sin `asyncio.to_thread` (ver /api/link/status en app.py) y por eso la
    caché de abajo importa tanto.

    POR QUÉ EXISTE (31/07/2026). Esta lista prometía direcciones que NO
    aceptaban conexiones: uvicorn estaba atado solo a 127.0.0.1, así que el QR
    llevaba a «MIPC.local:8177» y el móvil se comía un «rechazada» sin más
    explicación. Ofrecer una dirección muerta es peor que no ofrecerla: el móvil
    la prueba, falla, y el usuario no sabe si el fallo es suyo o del PC.

    OJO CON LO QUE ESTO *NO* PRUEBA: se comprueba desde este mismo equipo, y el
    cortafuegos de Windows puede dejar pasar al propio PC y bloquear al móvil.
    Que salga True significa «el puerto está abierto aquí», no «tu móvil llega»."""
    if cache_seg is None:
        cache_seg = _CACHE_SONDEO       # config/umbrales.json → «red»
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
    red = vivas if vivas else cand             # nunca vacía por culpa del sondeo

    tunel = []
    if _state["url"]:
        tunel = [{"host": _state["url"].replace("https://", ""), "esquema": "https",
                  "tipo": "tunel", "estable": False, "desde": "cualquier red",
                  "verificada": True}]         # no se sondea: cloudflared ya la registró

    # EL QR ABRE dirs[0]. La primaria tiene que ser alcanzable desde CUALQUIER red,
    # no solo en casa. Orden de esa primera puerta:
    #   1. Tailscale — IP fija, cualquier red, sobrevive reinicios. La buena.
    #   2. Túnel Cloudflare — llega desde fuera (cambia en cada arranque, pero llega).
    #   3. LAN (nombre .local / IP WiFi) — solo casa.
    # Antes la primaria era el nombre «.local»: fuera de casa NO resuelve (y el mDNS
    # de Android falla a menudo), así que el móvil en datos se comía 20-30 s de
    # timeout por cada dirección LAN antes de caer al túnel. De ahí la «pantalla
    # negra que tarda». Las LAN siguen en la lista como respaldo (rápidas en casa).
    ts_dirs = [d for d in red if d["tipo"] == "tailscale"]
    lan_dirs = [d for d in red if d["tipo"] != "tailscale"]
    return ts_dirs + tunel + lan_dirs


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


# ─────────────────────────────────────────────────────────────── túnel adoptado
# POR QUÉ EXISTE (tarea #12, 01/08/2026)
# --------------------------------------
# El «quick tunnel» de Cloudflare da un subdominio ALEATORIO distinto cada vez
# que arranca. Como start_tunnel() empezaba matando el cloudflared anterior y
# abriendo uno nuevo, la dirección cambiaba en CADA reinicio del PC y el móvil se
# quedaba apuntando a un sitio que ya no existe: a re-escanear el QR otra vez.
#
# Si el cloudflared del arranque anterior sigue vivo y sigue apuntando a nuestro
# 127.0.0.1:8177, lo suyo es QUEDÁRSELO. Misma dirección, cero QR.
_ADOPCION_TIMEOUT = 5.0                 # lo que se espera a que conteste la URL vieja
_ADOPCION_MAX_HORAS = 72.0              # más viejo que esto ni se prueba


def _guarda_tunel(url: str) -> None:
    """Apunta la URL del túnel para poder reutilizarla en el arranque siguiente."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _TUNEL_FILE.write_text(json.dumps({"url": url, "ts": time.time()}),
                               encoding="utf-8")
    except Exception:
        pass                            # no poder anotarlo no puede tumbar el túnel


def _tunel_guardado() -> str:
    """La URL del arranque anterior, o '' si no hay o es demasiado vieja."""
    try:
        if not _TUNEL_FILE.is_file():
            return ""
        d = json.loads(_TUNEL_FILE.read_text(encoding="utf-8")) or {}
        url = str(d.get("url") or "").strip()
        ts = float(d.get("ts") or 0)
        if not url.startswith("https://"):
            return ""
        if ts and (time.time() - ts) > _ADOPCION_MAX_HORAS * 3600:
            return ""
        return url
    except Exception:
        return ""


def _olvida_tunel() -> None:
    try:
        _TUNEL_FILE.unlink()
    except Exception:
        pass


async def _sigue_siendo_nuestro(url: str) -> bool:
    """¿La URL guardada sigue viva Y sigue sirviendo NUESTRA página del móvil?

    NO vale con mirar si `cloudflared.exe` está en la lista de procesos: un
    cloudflared vivo puede estar sirviendo un túnel viejo que ya no apunta aquí,
    o apuntar a otra cosa completamente. La única prueba que vale es pedirle la
    página y reconocerla.

    Se pide `/m`, que es ruta PÚBLICA (`_RUTAS_PUBLICAS` en app.py): no hace
    falta token y no se enseña ningún secreto por el camino."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=_ADOPCION_TIMEOUT,
                                     follow_redirects=True) as cli:
            r = await cli.get(url.rstrip("/") + "/m")
        # El marcador tiene que ser ESTABLE: el <title> de la página del móvil.
        # Un 200 pelado no basta — Cloudflare devuelve 200 en sus propias
        # páginas de error, y otro servicio cualquiera detrás del mismo túnel
        # también contestaría 200.
        return r.status_code == 200 and "<title>nexus</title>" in r.text.lower()
    except Exception:
        return False                    # túnel muerto, lento o apuntando a otro sitio


async def _log(nivel: str, msg: str) -> None:
    """Deja constancia en el monitor del HUD. Si el bus no está, no pasa nada."""
    try:
        from .comun.events import bus
        await bus.emit("log", {"level": nivel, "msg": msg})
    except Exception:
        pass


async def adopta_tunel_al_arrancar() -> bool:
    """AL ARRANCAR nexus: quedarse el túnel que siguiera vivo. Devuelve si adoptó.

    Esto es la mitad que faltaba de la tarea #12. La adopción dentro de
    `start_tunnel()` solo salta cuando el usuario abre el panel del QR; hasta ese
    momento nexus creía no tener túnel, y el HUD lo decía, aunque el cloudflared
    del arranque anterior siguiera sirviendo perfectamente. Ahora se comprueba
    nada más levantar el núcleo.

    NO ABRE NADA. Si no hay un túnel vivo que ya apunte aquí, se va de vacío y
    deja las cosas como estaban. Abrir un túnel es publicar este PC en internet y
    eso lo decide el usuario, no el arranque: aquí como mucho se RE-ENGANCHA a
    uno que YA estaba abierto y YA era público."""
    if _state["url"]:
        return False                    # ya hay túnel en esta sesión: nada que adoptar
    viejo = _tunel_guardado()
    if not viejo:
        return False
    if not await _sigue_siendo_nuestro(viejo):
        _olvida_tunel()                 # murió o apunta a otro sitio: fuera la nota
        return False
    _state.update(url=viejo, proc=None, adoptado=True, error="")
    _guarda_tunel(viejo)                # refresca la marca de tiempo
    await _log("ok", f"🔗 El túnel del arranque anterior sigue vivo ({viejo}): "
                     "me lo quedo. La dirección no cambia y el móvil sigue "
                     "vinculado, NO hace falta re-escanear el QR.")
    return True


async def start_tunnel() -> dict:
    """Arranca el quick tunnel (si no está ya). Devuelve el estado."""
    if _state["url"] and _state["proc"] and _state["proc"].poll() is None:
        return status()
    if _state["url"] and _state["adoptado"]:
        return status()
    if _state["starting"]:
        return status()
    _state.update(starting=True, error="", url_pending="")
    try:
        # ADOPCIÓN ANTES DEL TASKKILL. Si el túnel del arranque anterior sigue
        # vivo y sigue siendo nuestro, se reutiliza: así la dirección NO cambia y
        # el móvil no tiene que volver a escanear el QR.
        viejo = _tunel_guardado()
        if viejo and await _sigue_siendo_nuestro(viejo):
            _state.update(url=viejo, proc=None, adoptado=True, error="")
            _guarda_tunel(viejo)        # refresca la marca de tiempo
            await _log("ok", f"🔗 Reutilizo el túnel que seguía vivo ({viejo}): "
                             "la dirección no cambia, NO hace falta re-escanear el QR.")
            return status()

        # LIMPIEZA: cada reinicio del PC con taskkill deja el cloudflared anterior
        # VIVO (es un proceso hijo aparte) con un túnel viejo colgando. Se matan
        # antes de abrir el nuevo para que no se acumulen ni confundan.
        _state["adoptado"] = False
        _olvida_tunel()                 # la guardada ya no vale: no contestó
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
                    _guarda_tunel(pend)   # para poder adoptarlo en el arranque siguiente
                    return

        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(loop.run_in_executor(None, _read_url), timeout=30)
        except asyncio.TimeoutError:
            if _state.get("url_pending"):
                # URL impresa pero sin ver el registro en el log: úsala igualmente
                _state["url"] = _state["url_pending"]
                _guarda_tunel(_state["url_pending"])
            else:
                _state["error"] = "El túnel no ha dado URL en 30 s (¿internet caído?)."
    finally:
        _state["starting"] = False
    if _state["url"] and not _state["adoptado"]:
        await _log("warn", f"🔗 Túnel NUEVO ({_state['url']}): la dirección ha cambiado, "
                           "hay que volver a escanear el QR en el móvil.")
    return status()


def stop_tunnel() -> None:
    if _state["proc"] and _state["proc"].poll() is None:
        try:
            _state["proc"].terminate()
        except Exception:
            pass
    elif _state["adoptado"] and _state["url"]:
        # TÚNEL ADOPTADO: el cloudflared es hijo del nexus ANTERIOR, no nuestro,
        # así que no hay `proc` que terminar. Sin esto, «parar el túnel» no
        # paraba nada y el usuario se quedaba publicado en internet creyendo que
        # lo había cerrado. Se mata por nombre.
        if sys.platform == "win32":
            try:
                subprocess.run(["taskkill", "/F", "/IM", "cloudflared.exe"],
                               capture_output=True, timeout=8,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            except Exception:
                pass
        else:
            try:
                subprocess.run(["pkill", "-f", "cloudflared"],
                               capture_output=True, timeout=8)
            except Exception:
                pass
    _olvida_tunel()          # si se para a propósito, no se readopta al reiniciar
    _state.update(proc=None, url="", url_pending="", starting=False, adoptado=False)


def status() -> dict:
    """Estado de la vinculación, con la MEJOR dirección disponible.

    Orden de preferencia, y el porqué:
      1. TAILSCALE — IP fija (100.x.y.z). Sobrevive a reinicios y a cambios de
         red, y no publica nada en internet. Es la buena.
      2. TÚNEL de Cloudflare — llega desde fuera, pero la dirección cambia en
         cada arranque, así que el móvil hay que revincularlo cada vez.
      3. IP de la WiFi — solo sirve dentro de casa.
    """
    # OJO CON `alive`: un túnel ADOPTADO no tiene `proc` (lo abrió el nexus
    # anterior y su cloudflared es hijo de aquel proceso). Sin contar la marca,
    # el HUD decía «no hay túnel» con el túnel funcionando perfectamente.
    alive = bool(_state["url"]) and (
        _state["adoptado"] or bool(_state["proc"] and _state["proc"].poll() is None))
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
            "adoptado": bool(_state["adoptado"]),
            "tunel_nota": ("Reutilizo el túnel que seguía vivo del arranque anterior: "
                           "la dirección NO ha cambiado, no hace falta re-escanear el QR."
                           if _state["adoptado"] and _state["url"]
                           else ("Túnel nuevo: la dirección ha cambiado, hay que "
                                 "re-escanear el QR." if _state["url"] else "")),
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
