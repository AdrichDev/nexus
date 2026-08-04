"""
nexus — puente con Engram (github.com/Gentleman-Programming/engram), memoria
de PROYECTO/código para nexus, COMPARTIDA con tus otras herramientas de IA
(Claude Code, Cursor, Codex, Windsurf...) si también las conectaste a Engram.

Esto es DISTINTO de tu memoria PERSONAL (Postgres + RAG + grafo + perfil
destilado por selflearn, en backend/core/memory.py y profile.py) — Engram
guarda decisiones de arquitectura, bugs y features del PROPIO CÓDIGO de
nexus (o de cualquier proyecto), no datos tuyos. Nada de lo de aquí toca tu
memoria personal, y viceversa.

Cómo funciona (mismo tratamiento que el gateway de Hermes):
  * Engram es OPCIONAL. Si el binario `engram` no está instalado, todo esto
    se queda inactivo sin romper nada — nexus sigue funcionando exactamente
    igual sin él.
  * Si está instalado pero su servidor HTTP («engram serve», puerto 7437 por
    defecto) no está arrancado, nexus lo arranca él solo: proceso oculto en
    Windows (sin ventana de consola), log propio en data/engram_serve.log,
    y no relanza en ráfaga si ya lo intentó hace poco.
  * Toda la comunicación es HTTP LOCAL contra ese servidor. Engram es
    zero-config por defecto (sin token) — no hace falta ninguna clave.
  * Guardamos SIEMPRE bajo un proyecto fijo ("nexus") y una sesión estable
    reutilizada (Engram la trata de forma idempotente): no hace falta que
    nexus recuerde ningún estado de sesión entre reinicios.

API HTTP verificada a mano contra el binario real (v1.20.0) — no adivinada:
    GET  /health                              -> {"status":"ok",...}
    POST /sessions      {id, project}         -> 201 {"id","status":"created"}
    POST /observations  {session_id, title,
                          content, type,
                          project}             -> 201 {"id","status":"saved"}
                                                  400 si faltan campos
                                                  404 si session_id no existe
    GET  /search?q=&project=                  -> 200 JSON array, o `null` si
                                                  no hay resultados (¡ojo, NO
                                                  es una lista vacía!)
    GET  /context?project=                    -> 200 {"context": "<md>"}
    GET  /observations?project=                -> 200 JSON array (todo el
                                                  proyecto, sin buscar nada)
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
import time

import httpx

PROJECT = "nexus"                 # proyecto fijo bajo el que nexus guarda SUS decisiones
SESSION_ID = "nexus-backend"      # sesión estable y reutilizada (POST /sessions es idempotente)
_PORT_DEFAULT = 7437

_ALIVE = {"ok": False, "ts": 0.0}
_LAUNCH = {"ts": 0.0}
_LAST = {"err": ""}


def _port(ctx) -> int:
    try:
        return int((ctx.get("settings").get("engram_port", _PORT_DEFAULT))
                   if ctx.get("settings") else _PORT_DEFAULT)
    except Exception:
        return _PORT_DEFAULT


def _base_url(ctx) -> str:
    return f"http://127.0.0.1:{_port(ctx)}"


def _managed_bin_dir() -> str:
    """Carpeta donde nexus instala el binario de engram si lo baja él mismo:
    ~/.engram/bin (autocontenida junto a la base ~/.engram/engram.db)."""
    import os
    return os.path.join(os.path.expanduser("~"), ".engram", "bin")


def _engram_exe(ctx) -> str:
    """Ruta al binario de engram. Orden: ⚙ engram_exe -> PATH -> rutas típicas
    de instalación (go install / descarga manual a ~/bin / instalación propia de
    nexus en ~/.engram/bin)."""
    import os
    p = (ctx["settings"].get("engram_exe") or "").strip() if ctx.get("settings") else ""
    if p and os.path.exists(p):
        return p
    found = shutil.which("engram") or shutil.which("engram.exe")
    if found:
        return found
    home = os.path.expanduser("~")
    mbd = _managed_bin_dir()
    for cand in (
        os.path.join(mbd, "engram.exe"),
        os.path.join(mbd, "engram"),
        os.path.join(home, "go", "bin", "engram.exe"),
        os.path.join(home, "bin", "engram.exe"),
        os.path.join(home, "go", "bin", "engram"),
        os.path.join(home, "bin", "engram"),
        os.path.join(home, ".local", "bin", "engram"),
    ):
        if os.path.exists(cand):
            return cand
    return ""


def installed(ctx) -> bool:
    """¿Hay un binario de engram disponible? (para decidir si merece la pena
    intentar arrancarlo, o si Adri simplemente no lo tiene instalado)."""
    return bool(_engram_exe(ctx))


# ══════════════════════ INSTALACIÓN DEL BINARIO (opcional) ══════════════════════
# Adri quiere que nexus INSTALE Engram él mismo (no tener que hacerlo a mano). Dos
# vías, la 1ª más limpia:
#   1) «go install …@latest» si hay Go en el PATH → compila en local, deja el .exe
#      en ~/go/bin (que _engram_exe ya busca) y EVITA el falso positivo de antivirus
#      que a veces marca el binario prebuilt.
#   2) si no hay Go, se DESCARGA el binario oficial del release de GitHub (naming de
#      goreleaser: engram_<ver>_<os>_<arch>.(zip|tar.gz)), se VERIFICA su SHA-256
#      contra checksums.txt del mismo release (no ejecutamos nada sin verificar), y
#      se extrae a ~/.engram/bin. Todo best-effort: si algo falla, nexus sigue igual.
_REPO = "Gentleman-Programming/engram"
_KNOWN_VERSION = "1.20.0"      # fallback si no se puede resolver la última release


def _http_download(url: str, timeout: float = 60) -> bytes:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "nexus-engram-installer"})
    with urllib.request.urlopen(req, timeout=timeout) as r:      # nosec - release oficial de GitHub
        return r.read()


def _latest_version() -> str:
    """Última versión publicada (sin la «v»). Si no se puede resolver (sin red,
    rate-limit…), cae a una versión conocida buena para no quedarse tirado."""
    import json
    try:
        data = _http_download(f"https://api.github.com/repos/{_REPO}/releases/latest", timeout=15)
        tag = (json.loads(data).get("tag_name") or "").lstrip("v").strip()
        return tag or _KNOWN_VERSION
    except Exception:
        return _KNOWN_VERSION


def _plat_asset(version: str) -> tuple:
    """(nombre_del_asset, es_zip) para esta plataforma, según el naming de
    goreleaser del proyecto: engram_<ver>_<os>_<arch>.(zip|tar.gz)."""
    import platform
    m = (platform.machine() or "").lower()
    arch = "arm64" if m in ("arm64", "aarch64") else "amd64"
    if sys.platform.startswith("win"):
        return f"engram_{version}_windows_{arch}.zip", True
    if sys.platform == "darwin":
        return f"engram_{version}_darwin_{arch}.tar.gz", False
    return f"engram_{version}_linux_{arch}.tar.gz", False


def _sha256_ok(blob: bytes, asset: str, checksums_text: str) -> bool:
    """¿El SHA-256 del binario descargado coincide con el de checksums.txt del
    release? Es la barrera para no instalar/ejecutar algo corrupto o manipulado.
    Tolerante al formato: «<hash>  <asset>» y «<hash> *<asset>» (modo binario de
    sha256sum); el hash es el 1er campo y el nombre el último (con posible «*»)."""
    import hashlib
    want = ""
    for line in (checksums_text or "").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        name = parts[-1].lstrip("*")               # sha256sum -b antepone «*» al nombre
        if name == asset:
            want = parts[0].lower().strip()
            break
    return bool(want) and hashlib.sha256(blob).hexdigest() == want


def _extract_engram(blob: bytes, is_zip: bool, dest_dir: str) -> str:
    """Extrae SOLO el binario engram(.exe) del archivo descargado a dest_dir y
    devuelve su ruta. Descarta README/LICENSE/CHANGELOG que trae el archivo."""
    import io
    import os
    os.makedirs(dest_dir, exist_ok=True)
    bin_name = "engram.exe" if sys.platform.startswith("win") else "engram"
    dest = os.path.join(dest_dir, bin_name)
    if is_zip:
        import zipfile
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            member = next((n for n in z.namelist()
                           if os.path.basename(n) in ("engram", "engram.exe")), None)
            if not member:
                raise RuntimeError("el zip no contiene el binario engram")
            data = z.read(member)
    else:
        import tarfile
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as t:
            member = next((mi for mi in t.getmembers()
                           if os.path.basename(mi.name) in ("engram", "engram.exe") and mi.isfile()), None)
            if not member:
                raise RuntimeError("el tar.gz no contiene el binario engram")
            data = t.extractfile(member).read()
    # escritura atómica (temp + replace): si el proceso muere a mitad no deja un
    # binario corrupto a medio escribir. La extracción solo ocurre cuando NO estaba
    # instalado, así que aquí nunca hay un engram en marcha ocupando `dest`.
    tmp = dest + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    if not sys.platform.startswith("win"):
        os.chmod(tmp, 0o755)
    os.replace(tmp, dest)
    return dest


def _go_install() -> str:
    """Intenta «go install …@latest» si hay Go. Devuelve la ruta al binario que
    deja en ~/go/bin (GOBIN), o «» si no hay Go o falla. Evita el falso positivo
    de antivirus del binario prebuilt (compila en local)."""
    import os
    go = shutil.which("go")
    if not go:
        return ""
    try:
        env = dict(os.environ)
        subprocess.run([go, "install", f"github.com/{_REPO}/cmd/engram@latest"],
                       timeout=300, check=True, env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       **_win_hidden_kw())
    except Exception:
        return ""
    gobin = os.environ.get("GOBIN") or os.path.join(
        os.environ.get("GOPATH") or os.path.join(os.path.expanduser("~"), "go"), "bin")
    exe = os.path.join(gobin, "engram.exe" if sys.platform.startswith("win") else "engram")
    return exe if os.path.exists(exe) else ""


def install(ctx=None, *, log=None) -> str:
    """Instala el binario de engram si no está. Devuelve la ruta al binario o «»
    si no se pudo. NUNCA lanza (best-effort). `log` opcional: callable(str) para
    ir contando el progreso (lo usa el instalador de consola de run.bat)."""
    def _say(msg):
        _LAST["err"] = msg
        if log:
            try:
                log(msg)
            except Exception:
                pass

    def _download_version(ver):
        """Descarga+verifica+extrae para una versión concreta. Devuelve la ruta o
        lanza (para que el llamante decida reintentar con otra versión)."""
        asset, is_zip = _plat_asset(ver)
        base = f"https://github.com/{_REPO}/releases/download/v{ver}"
        _say(f"descargando {asset}…")
        blob = _http_download(f"{base}/{asset}", timeout=120)
        checks = _http_download(f"{base}/checksums.txt", timeout=30).decode("utf-8", "replace")
        if not _sha256_ok(blob, asset, checks):
            raise RuntimeError("el checksum del binario descargado NO coincide")
        return _extract_engram(blob, is_zip, _managed_bin_dir())

    exe = _engram_exe(ctx or {})
    if exe:
        return exe
    # 1) go install (limpio, sin falso positivo de antivirus)
    _say("probando «go install» (si tienes Go)…")
    exe = _go_install()
    if exe:
        _say(f"instalado con go install en {exe}")
        return exe
    # 2) binario oficial del release, verificado por checksum. Se prueba la última
    #    versión y, si su asset falla (404 para esta arch, red…), se reintenta con
    #    la versión conocida buena como red de seguridad.
    ver = _latest_version()
    for cand in (ver, _KNOWN_VERSION):
        if not cand:
            continue
        try:
            dest = _download_version(cand)
            _say(f"instalado en {dest}")
            return dest
        except Exception as exc:
            _say(f"no pude instalar engram {cand}: {type(exc).__name__}: {exc}")
            if cand == _KNOWN_VERSION:      # ya era el fallback: no hay más que probar
                break
    return ""


def install_cli() -> int:
    """Punto de entrada del INSTALADOR de nexus (run.bat lo llama con
    «python -m backend.core.engram_bridge»): Engram es un paquete más que el
    instalador deja listo, como edge-tts o pypdf. Instala el binario imprimiendo
    el progreso. Devuelve 0 si quedó instalado (o si el usuario lo desactivó)."""
    # ctx con settings REALES: así se respeta una ruta ⚙ engram_exe personalizada
    # y no se reinstala en balde en cada arranque quien tenga el binario en un sitio raro.
    ctx = {}
    try:
        from backend.core.comun.config import settings as _s
        ctx = {"settings": _s}
        if not _s.get("engram_autoinstall", True):
            print("[nexus] Engram: 'engram_autoinstall' está desactivado en ⚙; no lo instalo.")
            return 0
    except Exception:
        pass
    if installed(ctx):
        print("[nexus] Engram ya estaba instalado ✔")
        return 0
    print("[nexus] Engram: instalando la memoria de proyecto compartida (nexus + Hermes)…")
    exe = install(ctx, log=lambda m: print(f"[nexus]   engram: {m}"))
    if exe:
        print(f"[nexus] Engram listo en {exe} ✔")
        return 0
    print("[nexus] AVISO: no se pudo instalar Engram ahora. nexus funciona igual sin él; "
          "puedes instalarlo a mano con «go install github.com/Gentleman-Programming/engram/cmd/engram@latest».")
    return 1


async def maybe_install_background(ctx) -> None:
    """Instalación de Engram al ARRANCAR la app. Vale para los dos modos de
    distribución: «python -m backend.desktop» (dev) y el nexus.exe congelado
    (donde NO se ejecuta run.bat, así que el instalador de paquetes de run.bat
    no llega a correr — este es el que cubre ese caso). Si engram no está y
    engram_autoinstall está activo, lo baja/instala en un HILO para NO bloquear
    la apertura del HUD. Best-effort: nunca rompe el arranque."""
    try:
        if installed(ctx):
            return
        autoinstall = ctx["settings"].get("engram_autoinstall", True) if ctx.get("settings") else True
        if not autoinstall:
            return
        from backend.core.comun.events import bus
        await bus.emit("log", {"level": "info",
                               "msg": "🧠 Instalando Engram (memoria de proyecto) en segundo plano…"})
        exe = await asyncio.to_thread(install, ctx)
        if exe:
            await bus.emit("log", {"level": "info", "msg": f"🧠 Engram instalado ✔ ({exe})"})
        else:
            await bus.emit("log", {"level": "warn",
                                   "msg": "🧠 No pude instalar Engram automáticamente ("
                                          + (_LAST.get("err") or "motivo desconocido")
                                          + "). nexus sigue igual sin él."})
    except Exception:
        pass


async def _http_get(url: str, params: dict | None = None, timeout: float = 8) -> httpx.Response:
    """Fino envoltorio sobre httpx — TODA lectura HTTP pasa por aquí, así los
    tests pueden sustituir esta única función en vez de montar un servidor
    real (mismo patrón que _post() en skills/n8n_flows/skill.py)."""
    async with httpx.AsyncClient(timeout=timeout) as cli:
        return await cli.get(url, params=params)


async def _http_post(url: str, json: dict | None = None, timeout: float = 8) -> httpx.Response:
    """Fino envoltorio sobre httpx — TODA escritura HTTP pasa por aquí."""
    async with httpx.AsyncClient(timeout=timeout) as cli:
        return await cli.post(url, json=json)


async def _alive(url: str) -> bool:
    try:
        r = await _http_get(f"{url}/health", timeout=4)
        return r.status_code == 200
    except Exception:
        return False


async def alive_cached(ctx) -> bool:
    """/health con caché de 60 s — no pinga en cada mensaje."""
    now = time.monotonic()
    if now - _ALIVE["ts"] < 60:
        return _ALIVE["ok"]
    ok = await _alive(_base_url(ctx))
    _ALIVE.update(ok=ok, ts=now)
    return ok


def _win_hidden_kw() -> dict:
    """Mismo tratamiento que el gateway de Hermes: en Windows, lanza el
    proceso SIN ventana de consola visible, pero sin --detached (eso le abre
    su propia consola VISIBLE a un .exe de consola)."""
    if sys.platform != "win32":
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    si.wShowWindow = 0  # SW_HIDE
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
            "startupinfo": si}


def _log_file():
    from backend.core.comun.config import DATA_DIR
    return DATA_DIR / "engram_serve.log"


async def ensure_up(ctx) -> bool:
    """Garantiza que «engram serve» está arrancado y responde. Si el binario
    no está instalado, o engram_autostart está desactivado, devuelve False
    SIN lanzar nada — Engram es opcional y esto nunca debe romper a nexus."""
    if await alive_cached(ctx):
        return True
    exe = _engram_exe(ctx)
    if not exe:
        _LAST["err"] = "engram no está instalado (ni en ⚙ engram_exe ni en el PATH)"
        return False
    if not (ctx["settings"].get("engram_autostart", True) if ctx.get("settings") else True):
        _LAST["err"] = "engram_autostart está desactivado en ⚙"
        return False
    if time.monotonic() - _LAUNCH["ts"] < 45:
        # ya se intentó lanzar hace poco: no relanzar en ráfaga, solo comprobar
        return await alive_cached(ctx)
    _LAUNCH["ts"] = time.monotonic()
    try:
        logf = open(_log_file(), "ab")
        logf.write(("\n===== lanzamiento " + time.strftime("%Y-%m-%d %H:%M:%S")
                    + " =====\n").encode("utf-8"))
        subprocess.Popen([exe, "serve", str(_port(ctx))],
                         stdout=logf, stderr=logf, stdin=subprocess.DEVNULL,
                         close_fds=True, **_win_hidden_kw())
        from backend.core.comun.events import bus
        await bus.emit("log", {"level": "info",
                               "msg": "🧠 Arrancando el servidor de Engram "
                                      "(log en data/engram_serve.log)…"})
    except Exception as exc:
        _LAST["err"] = f"no pude lanzar «engram serve»: {type(exc).__name__}: {exc}"
        return False
    url = _base_url(ctx)
    for _ in range(20):        # binario Go: arranque casi instantáneo, 20 s de margen sobra
        await asyncio.sleep(1.0)
        if await _alive(url):
            _ALIVE.update(ok=True, ts=time.monotonic())
            return True
    _LAST["err"] = "«engram serve» no respondió en 20 s"
    return False


async def _ensure_session(url: str) -> None:
    """POST /sessions es idempotente (repetir el mismo id no falla) — se
    llama antes de cada guardado para no tener que recordar estado de sesión
    entre reinicios de nexus. Si falla, el POST /observations que sigue dará
    el error real (p.ej. «session not found»)."""
    try:
        await _http_post(f"{url}/sessions", json={"id": SESSION_ID, "project": PROJECT}, timeout=6)
    except Exception:
        pass


TIPOS = ("decision", "architecture", "bugfix", "feature", "note")


async def save(ctx, title: str, content: str, kind: str = "note") -> dict:
    """Guarda una decisión/nota de PROYECTO en Engram. Arranca el servidor si
    hace falta. Devuelve {"ok": True, "id": int} o {"ok": False, "error": str}
    — NUNCA lanza excepción, siempre hay algo que decirle al usuario."""
    kind = kind if kind in TIPOS else "note"
    if not await ensure_up(ctx):
        return {"ok": False, "error": _LAST["err"] or "Engram no está disponible ahora mismo"}
    url = _base_url(ctx)
    await _ensure_session(url)
    try:
        r = await _http_post(f"{url}/observations", json={
            "session_id": SESSION_ID, "title": (title or "").strip()[:200],
            "content": (content or "").strip(), "type": kind, "project": PROJECT})
        if r.status_code in (200, 201):
            try:
                return {"ok": True, "id": r.json().get("id")}
            except Exception:
                return {"ok": True, "id": None}
        return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


async def search(ctx, query: str, limit: int = 5) -> list:
    """Busca en la memoria de proyecto. [] si no hay nada o Engram no
    responde — es una consulta de apoyo, nunca debe romper la conversación."""
    query = (query or "").strip()
    if not query or not await ensure_up(ctx):
        return []
    url = _base_url(ctx)
    try:
        r = await _http_get(f"{url}/search", params={"q": query, "project": PROJECT})
        if r.status_code != 200:
            return []
        data = r.json()          # OJO: la API devuelve `null` (no []) sin resultados
        return list(data or [])[:max(1, limit)]
    except Exception:
        return []


async def context(ctx) -> str:
    """Resumen narrativo (markdown) de la memoria de proyecto reciente. ''
    si no hay nada o Engram no responde."""
    if not await ensure_up(ctx):
        return ""
    url = _base_url(ctx)
    try:
        r = await _http_get(f"{url}/context", params={"project": PROJECT})
        if r.status_code != 200:
            return ""
        data = r.json()
        return (data or {}).get("context", "") or ""
    except Exception:
        return ""


async def count(ctx) -> int:
    """Nº de recuerdos de proyecto guardados hasta ahora. 0 si Engram no
    responde (no arranca el servidor solo para contar: usa la caché)."""
    if not await alive_cached(ctx):
        return 0
    url = _base_url(ctx)
    try:
        r = await _http_get(f"{url}/observations", params={"project": PROJECT}, timeout=6)
        if r.status_code != 200:
            return 0
        return len(r.json() or [])
    except Exception:
        return 0


def status_sync(ctx) -> dict:
    """Ficha de estado SIN red (para responder rápido a «diagnostica
    engram» combinada con lo que ya se sepa en caché)."""
    return {"installed": installed(ctx), "exe": _engram_exe(ctx),
            "url": _base_url(ctx), "last_error": _LAST["err"],
            "alive_cached": _ALIVE["ok"]}


# El bloque __main__ va AL FINAL: run.bat llama «python -m backend.core.engram_bridge»,
# que ejecuta el módulo entero; si estuviera a mitad, install_cli() correría con las
# funciones de más abajo (p.ej. _win_hidden_kw, que usa _go_install) aún sin definir.
if __name__ == "__main__":
    raise SystemExit(install_cli())
