"""
nexus — Índice de TODAS las aplicaciones instaladas en el PC.

Escanea tres fuentes de Windows (cubren prácticamente todo lo instalado):
  1. Menú Inicio (.lnk de ProgramData y AppData) → Word, Excel, Spotify,
     iTunes, Photoshop, juegos... cualquier cosa con acceso directo.
  2. Registro App Paths (HKLM/HKCU) → ejecutables registrados (excel.exe...).
  3. Apps UWP / Microsoft Store (Get-StartApps) → Calculadora, Spotify Store,
     WhatsApp Desktop, Netflix...

El índice se construye al arrancar (en segundo plano), se cachea en
data/app_index.json y se puede reconstruir con «reindexa las aplicaciones».
La búsqueda es difusa: «abre word» encuentra "Microsoft Word".
"""
from __future__ import annotations

import difflib
import json
import os
import subprocess
import sys
import threading
import unicodedata
from pathlib import Path

from ..comun.config import DATA_DIR
from ..comun.events import bus

INDEX_FILE = DATA_DIR / "app_index.json"
_index: dict[str, str] = {}
_lock = threading.Lock()

# Palabras que se ignoran al buscar («abre el word» → «word»)
STOPWORDS = {"el", "la", "los", "las", "un", "una", "de", "del", "app",
             "aplicacion", "programa", "microsoft"}


def _norm(s: str) -> str:
    """minúsculas, sin acentos, sin extensión, sin palabras vacías."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower().replace(".lnk", "").replace(".exe", "").strip()
    words = [w for w in s.replace("-", " ").split() if w not in STOPWORDS]
    return " ".join(words) or s


def build_index() -> dict[str, str]:
    """Reconstruye el índice completo. Devuelve {nombre_normalizado: lanzador}."""
    apps: dict[str, str] = {}
    if sys.platform != "win32":
        return apps

    # ---- 1. Accesos directos del Menú Inicio ----
    roots = [
        Path(os.environ.get("ProgramData", r"C:\ProgramData"))
        / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.environ.get("APPDATA", ""))
        / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    ]
    skip = ("uninstall", "desinstalar", "readme", "ayuda", "help", "website", "web site")
    for root in roots:
        if not root.is_dir():
            continue
        for lnk in root.rglob("*.lnk"):
            name = lnk.stem
            if any(k in name.lower() for k in skip):
                continue
            apps.setdefault(_norm(name), str(lnk))

    # ---- 2. Registro App Paths ----
    try:
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                key = winreg.OpenKey(
                    hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths")
                for i in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        sub = winreg.EnumKey(key, i)
                        path, _ = winreg.QueryValueEx(winreg.OpenKey(key, sub), None)
                        if path:
                            apps.setdefault(_norm(sub), path.strip('"'))
                    except OSError:
                        continue
            except OSError:
                continue
    except ImportError:
        pass

    # ---- 3. Apps UWP / Microsoft Store ----
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             'Get-StartApps | ForEach-Object { "$($_.Name)|$($_.AppID)" }'],
            capture_output=True, text=True, timeout=25,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for line in out.stdout.splitlines():
            if "|" in line:
                name, appid = line.split("|", 1)
                apps.setdefault(_norm(name), "shell:AppsFolder\\" + appid.strip())
    except Exception:
        pass

    # ---- 4. Registro de programas instalados (Uninstall) ----
    try:
        import winreg
        uninst = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
        for hive, flag in ((winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
                           (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
                           (winreg.HKEY_CURRENT_USER, 0)):
            try:
                base = winreg.OpenKey(hive, uninst, 0, winreg.KEY_READ | flag)
            except OSError:
                continue
            for i in range(winreg.QueryInfoKey(base)[0]):
                try:
                    sub = winreg.OpenKey(base, winreg.EnumKey(base, i))
                    name = winreg.QueryValueEx(sub, "DisplayName")[0]
                    if not name or any(k in name.lower() for k in skip):
                        continue
                    target = ""
                    for val in ("DisplayIcon", "InstallLocation"):
                        try:
                            target = str(winreg.QueryValueEx(sub, val)[0]).split(",")[0].strip('"')
                            if target:
                                break
                        except OSError:
                            continue
                    if not target:
                        continue
                    p = Path(target)
                    if p.is_dir():
                        exes = list(p.glob("*.exe"))
                        if not exes:
                            continue
                        target = str(exes[0])
                    elif not target.lower().endswith(".exe"):
                        continue
                    apps.setdefault(_norm(name), target)
                except OSError:
                    continue
    except ImportError:
        pass

    with _lock:
        _index.clear()
        _index.update(apps)
    try:
        INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
        INDEX_FILE.write_text(json.dumps(apps, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    except Exception:
        pass
    return apps


def get_index() -> dict[str, str]:
    with _lock:
        if _index:
            return dict(_index)
    if INDEX_FILE.exists():
        try:
            cached = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
            with _lock:
                _index.update(cached)
            return cached
        except Exception:
            pass
    return build_index()


def find_app(query: str) -> tuple[str, str] | None:
    """Búsqueda difusa tolerante a nombres mal oídos:
    exacta → empieza-por → contiene → inverso → por palabra → fonético (difflib)."""
    apps = get_index()
    if not apps:
        return None
    q = _norm(query)
    if not q:
        return None
    if q in apps:
        return q, apps[q]
    starts = [k for k in apps if k.startswith(q)]
    if starts:
        best = min(starts, key=len)
        return best, apps[best]
    contains = [k for k in apps if q in k]
    if contains:
        best = min(contains, key=len)
        return best, apps[best]
    # inverso: la consulta contiene el nombre de la app («abre el photoshop cs6»)
    inv = [k for k in apps if len(k) > 2 and k in q]
    if inv:
        best = max(inv, key=len)
        return best, apps[best]
    # solape por palabra significativa (≥4 letras): «abre discord ahora» → discord
    qwords = [w for w in q.split() if len(w) >= 4]
    for w in qwords:
        wc = [k for k in apps if w in k]
        if wc:
            best = min(wc, key=len)
            return best, apps[best]
    # parecido fonético/tipográfico (umbral laxo, tolera cómo lo oye Whisper)
    close = difflib.get_close_matches(q, list(apps), n=1, cutoff=0.66)
    if close:
        return close[0], apps[close[0]]
    for w in qwords:                      # última pasada, palabra a palabra
        c = difflib.get_close_matches(w, list(apps), n=1, cutoff=0.72)
        if c:
            return c[0], apps[c[0]]
    return None


def launch(target: str) -> None:
    """Lanza un .lnk, .exe o app UWP (shell:AppsFolder\\...)."""
    if target.startswith("shell:"):
        subprocess.Popen(["explorer.exe", target])
    else:
        os.startfile(target)  # Windows resuelve .lnk y .exe nativamente


def start_background_index() -> None:
    """Construye el índice al arrancar sin bloquear el servidor."""
    def _run():
        apps = build_index()
        if apps:
            bus.emit_sync("log", {"level": "ok",
                                  "msg": f"Índice de aplicaciones: {len(apps)} apps detectadas"})
    threading.Thread(target=_run, daemon=True).start()
