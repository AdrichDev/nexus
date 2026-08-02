"""Minion Sistema/PC — control del equipo (con fallbacks simulados)."""
from __future__ import annotations

import datetime as dt
import os
import platform
import re
import subprocess
import sys
import webbrowser
from pathlib import Path

try:
    import psutil
except ImportError:
    psutil = None

SHOTS_DIR = Path(__file__).resolve().parents[2] / "data" / "captures"

SKILL = {
    "name": "Sistema / PC",
    "description": ("Control real del PC: CPU/RAM/GPU con temperaturas, procesos, abrir apps "
                    "y webs, capturas, webcam, Wake-on-LAN y apagado con doble confirmación"),
    "patterns": {
        # Volumen del PC. El «sube/baja el volumen» a secas lo atiende domotica
        # (va antes por alfabeto y lo manda a la tele); aquí caen «pon el volumen
        # al 40», «volumen al 75%» y similares con número.
        "volume": r"\bvolumen\s+(?:del?\s+(?:pc|equipo|sistema)\s+)?(?:al?\s*)?(?P<vol>\d{1,3})\s*%?"
                  r"|\b(sube|baja|pon)(?:me|le)?\b[^.\n]{0,25}\bvolumen\b",
        # Temperaturas de HARDWARE (cpu/gpu/gráfica…). OJO: exige un componente
        # detrás de "temperatura" para NO robar «¿qué temperatura hace en Madrid?»
        # (eso es clima y lo atiende la skill 'clima').
        "temps": r"temperatura[s]?\b.{0,25}\b(cpu|gpu|gr[aá]ficas?|tarjeta gr[aá]fica|procesador|n[uú]cleos?|componentes)\b|temperatura[s]?\s+(de\s+(la|el|los)\s+)?(cpu|gpu|gr[aá]ficas?|tarjeta|procesador|n[uú]cleos?|componentes|equipo|pc|ordenador|sistema)|(cpu|gpu|gr[aá]fica|procesador)\s+.{0,8}temperatura|qu[eé] temperatura (tiene|alcanza|marca|hay en)\s+(la|el|mi)?\s*(cpu|gpu|gr[aá]fica|procesador|pc|equipo)|c[oó]mo (est[aá]n?|van?)\s+(de\s+)?(las\s+|los\s+)?temperatura"
                 r"|(?:est[aá]|anda)\s+(?:muy\s+)?caliente\s+(?:la\s+|el\s+|mi\s+)?(cpu|gpu|gr[aá]fica|procesador|pc|equipo|ordenador|port[aá]til)"
                 r"|se\s+(?:me\s+)?(?:est[aá]\s+)?calentando\s+(?:la\s+|el\s+|mi\s+)?(cpu|gpu|gr[aá]fica|pc|equipo|ordenador|port[aá]til)"
                 r"|cu[aá]ntos?\s+grados\s+(?:tiene|marca|alcanza)\s+(?:la\s+|el\s+|mi\s+)?(cpu|gpu|gr[aá]fica|procesador|pc|equipo)",
        "hardware": r"estado del (sistema|equipo|pc)|c[oó]mo (?:va|anda) (la|el|mi) (cpu|ram|gpu|pc|equipo|ordenador)|informe de[l]? (sistema|equipo|hardware)|\bhardware\b|c[oó]mo (est[aá]|va|anda) (el|mi) (pc|equipo|ordenador|sistema)"
                    r"|diagn[oó]stico (?:r[aá]pido )?(?:del?|de mi) (pc|equipo|sistema|ordenador|hardware)"
                    r"|uso de (?:la\s+)?(cpu|ram|memoria|gpu|disco)"
                    r"|cu[aá]nta (ram|memoria) (?:libre\s+)?(hay|queda|tengo|me queda)",
        "processes": r"(?:l[ií]sta|ver|mu[eé]strame|ens[eé][ñn]ame|dime|dame|saca)(?:me)?\b[^.\n]{0,20}\bprocesos\b"
                     r"|procesos (?:activos|abiertos|en marcha|en ejecuci[oó]n)"
                     r"|qu[eé] procesos (?:hay|corren|est[aá]n|tengo)|top de procesos"
                     r"|qu[eé] [^.\n]{0,25}(?:consume|consumiendo|come|comiendo|gasta|gastando|"
                     r"chupa|chupando)[^.\n]{0,15}\b(?:ram|memoria|cpu)\b",
        # Matar procesos: SIEMPRE con ancla de dominio («proceso», «.exe», la app/
        # el programa, o el verbo «mata», que es inequívocamente de PC). Un «cierra X»
        # o «termina X» a secas NO cae aquí (sería robarle a tareas, correo, etc.).
        # La última alternativa excluye los sustantivos de ancla para que
        # «mátame el proceso spotify» capture «spotify» y no «proceso».
        "kill": r"\b(?:ci[eé]rra|m[aá]ta|termina|finaliza)(?:me|le)?\s+(?:el\s+)?procesos?\s+(?:de\s+)?(?P<proc>[\w.\-]+)"
                r"|\b(?:ci[eé]rra|m[aá]ta|termina|finaliza)(?:me|le)?\s+(?:la\s+(?:app|aplicaci[oó]n)|el\s+programa)\s+(?:de\s+)?(?P<proc2>[\w.\-]+)"
                r"|\b(?:ci[eé]rra|m[aá]ta|termina|finaliza)(?:me|le)?\s+(?P<proc3>[\w.\-]+\.exe)\b"
                r"|\bm[aá]ta(?:me)?\s+(?:a\s+|al\s+|el\s+)?"
                r"(?!la\b|los\b|las\b|una?\b|unos\b|unas\b|procesos?\b|aplicaci[oó]n\b|app\b|programa\b)"
                r"(?P<proc4>[\w.\-]{2,})",
        "youtube": r"\b[aá]bre(?:me)?\b.*youtube(\s+y\s+(busca|pon)\s+(?P<yt>.+))?|\bpon(?:me)?\b.*en youtube\s+(?P<yt2>.+)",
        # «abre la web/página (de) X»: captura TODO el nombre del sitio, no solo la
        # primera palabra. ANTES capturaba \S+ y con «abre la web de youtube» la URL
        # era literalmente "de" → abría https://de (el famoso «de/»). El «de» ahora
        # se ignora y el handler resuelve alias conocidos, dominios o busca en Google.
        "open_web": r"\b[aá]bre(?:me)?\b.*?\b(?:la\s+)?(?:web|p[aá]gina)(?:\s+web)?\s+"
                    r"(?:de\s+la\s+|de\s+los\s+|del\s+|de\s+|la\s+|el\s+)?(?P<url>.+)",
        "reindex": r"reindexa (las )?(aplicaciones|apps)|(?:actualiza|reconstruye) el [ií]ndice de (apps|aplicaciones)|reescanea (las )?(aplicaciones|apps)",
        "list_apps": r"qu[eé] (aplicaciones|apps|programas) (conoces|tienes|hay|tengo)( instalad[oa]s)?"
                     r"|(?:lista|mu[eé]strame|ens[eé][ñn]ame)\s+(?:de\s+|las?\s+|los\s+)?(?:aplicaciones|apps|programas)\s+instalad[oa]s",
        # Abrir apps instaladas. El lookahead NEGATIVO evita robar dominios ajenos:
        # el tablero/tareas (tasks_board), correos (google_workspace), pestañas o
        # «X en chrome» (navegador), hermes… Esos, si su skill no los caza, deben
        # llegar al planificador, no abrirse aquí como si fueran un .exe.
        "open_app": r"\b([aá]bre(?:me)?|ejecuta|lanza|arranca|inicia)\b\s+"
                    r"(?!(?:el\s+|la\s+|los\s+|las\s+|mis?\s+|una?\s+)?"
                    r"(?:tablero\b|tareas?\b|correos?\b|mails?\b|e-?mails?\b|"
                    r"pesta[ñn]as?\b|marcadores\b|historial\b|sesi[oó]n\b|hermes\b))"
                    r"(?!.*\ben\s+chrome\b)(?P<app>.+)",
        "screenshot": r"captura de (?:la\s+)?pantalla|haz(?:me)? una captura|s[aá]ca(?:me)? (?:una\s+)?captura|pantallazo|captura la pantalla|screenshot",
        "webcam": r"foto (?:con|desde) la (webcam|c[aá]mara)|haz(?:me)? una foto|s[aá]ca(?:me)? una foto|[eé]cha(?:me)? una foto",
        # SEGURIDAD: apagar y reiniciar SIEMPRE son dos pasos, armados en
        # backend.core.confirm. Los *_confirm solo llegan aquí cuando NO hay nada
        # armado (si lo hay, el brain resuelve el sí/no antes que el router).
        "shutdown_confirm": r"confirmo apagado",
        "shutdown": r"\bap[aá]ga(?:me)?\s+(?:el\s+|la\s+|mi\s+)?(pc|ordenador|equipo|sistema|torre|m[aá]quina)\b",
        "restart_confirm": r"confirmo reinicio",
        "restart": r"\brein[ií]cia(?:me)?\s+(?:el\s+|la\s+|mi\s+)?(pc|ordenador|equipo|sistema|torre|m[aá]quina)\b",
        "wake": r"enciende (el )?(pc|ordenador|equipo)|arranca (el )?(pc|ordenador)|despierta (el )?(pc|ordenador|equipo)|wake on lan",
        "set_mac": r"(guarda|configura|apunta) la mac\s+(?P<mac>[0-9a-fA-F:.\-]{12,17})",
    },
}


def _send_magic_packet(mac: str, broadcast: str = "255.255.255.255") -> bool:
    """Envía un paquete mágico Wake-on-LAN a la MAC indicada."""
    import socket
    clean = mac.replace(":", "").replace("-", "").replace(".", "")
    if len(clean) != 12:
        return False
    data = bytes.fromhex("FF" * 6 + clean * 16)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(data, (broadcast, 9))
        s.close()
        return True
    except Exception:
        return False

def _steam_appid_by_name(name: str):
    """AppID de Steam por nombre (búsqueda en la tienda, sin API key). None si no
    hay una coincidencia razonable — así «abre battlefield» lanza el juego, pero
    «abre asdf» no dispara nada raro."""
    import json
    import urllib.parse
    import urllib.request
    url = ("https://store.steampowered.com/api/storesearch/?term="
           + urllib.parse.quote(name) + "&l=spanish&cc=ES")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            items = (json.loads(r.read().decode("utf-8", "ignore")).get("items") or [])
        low = name.lower()
        for it in items:
            nm = str(it.get("name", "")).lower()
            if low in nm or any(len(w) > 2 and w in nm for w in low.split()):
                return it.get("id")
    except Exception:
        return None
    return None


def _cpu_temp():
    """Temperatura de CPU en °C (float) o None. Windows no la expone por psutil,
    así que probamos, en orden: psutil (Linux/algunos) → LibreHardwareMonitor u
    OpenHardwareMonitor por WMI (si están abiertos) → MSAcpi_ThermalZoneTemperature."""
    # 1) psutil — funciona en Linux y en algún hardware
    if psutil is not None:
        try:
            sensors = psutil.sensors_temperatures() or {}
            for key in ("coretemp", "k10temp", "zenpower", "acpitz", "cpu_thermal"):
                if sensors.get(key):
                    return max(s.current for s in sensors[key] if s.current)
            for arr in sensors.values():
                if arr and arr[0].current:
                    return arr[0].current
        except Exception:
            pass
    if sys.platform != "win32":
        return None
    # 2) LibreHardwareMonitor / OpenHardwareMonitor por WMI (lo más fiable en Windows)
    try:
        import wmi  # pip install wmi (lo instala run.bat)
        for ns in ("root\\LibreHardwareMonitor", "root\\OpenHardwareMonitor"):
            try:
                w = wmi.WMI(namespace=ns)
                temps = [s for s in w.Sensor() if getattr(s, "SensorType", "") == "Temperature"]
                cpu = [s.Value for s in temps if s.Value and "CPU" in (s.Name or "")
                       and any(k in (s.Name or "") for k in ("Package", "Core", "CCD", "Tctl"))]
                if cpu:
                    return max(cpu)
                cpu_any = [s.Value for s in temps if s.Value and "CPU" in (s.Name or "")]
                if cpu_any:
                    return max(cpu_any)
            except Exception:
                continue
    except Exception:
        pass
    # 3) MSAcpi_ThermalZoneTemperature (décimas de Kelvin; a veces requiere admin)
    try:
        import wmi
        vals = [z.CurrentTemperature for z in
                wmi.WMI(namespace="root\\wmi").MSAcpi_ThermalZoneTemperature()]
        if vals:
            return (min(vals) / 10.0) - 273.15
    except Exception:
        pass
    return None


def _gpu_info():
    """Info de GPU NVIDIA por nvidia-smi: {name, temp, util, mem_used, mem_total} o None."""
    try:
        out = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4)
        line = (out.stdout or "").strip().splitlines()[0]
        name, temp, util, mused, mtot = [x.strip() for x in line.split(",")]
        return {"name": name, "temp": float(temp), "util": float(util),
                "mem_used": float(mused), "mem_total": float(mtot)}
    except Exception:
        return None


def _temps_report() -> str:
    """Solo temperaturas — para «¿a qué temperatura está la CPU/gráfica?»."""
    parts = []
    ct = _cpu_temp()
    parts.append(f"CPU {ct:.0f}°C" if ct is not None else
                 "CPU n/d (para leerla en Windows, ten abierto LibreHardwareMonitor)")
    g = _gpu_info()
    if g:
        parts.append(f"GPU {g['name']} {g['temp']:.0f}°C")
    else:
        parts.append("GPU n/d (sin NVIDIA detectada por nvidia-smi)")
    return " · ".join(parts)


def _hw_report() -> str:
    if psutil is None:
        return ("no puedo leer CPU/RAM/disco: falta psutil (pip install psutil y reinicia). "
                "No te doy cifras que no he medido")
    vm = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.3)
    cpu_txt = f"CPU {cpu:.0f}% ({psutil.cpu_count()} núcleos)"
    ct = _cpu_temp()
    if ct is not None:
        cpu_txt += f" a {ct:.0f}°C"
    parts = [cpu_txt,
             f"RAM {vm.percent:.0f}% de {vm.total/2**30:.1f} GB",
             f"Disco {psutil.disk_usage('/').percent:.0f}%"]
    g = _gpu_info()
    if g:
        parts.append(f"GPU {g['name']} {g['util']:.0f}% a {g['temp']:.0f}°C "
                     f"({g['mem_used']/1024:.1f}/{g['mem_total']/1024:.1f} GB)")
    parts.append(f"{platform.system()} {platform.release()}")
    return " · ".join(parts)


def _proc_names() -> set:
    """Conjunto de nombres de proceso en marcha (en minúsculas)."""
    if psutil is None:
        return set()
    out = set()
    for p in psutil.process_iter(["name"]):
        n = (p.info.get("name") or "").lower()
        if n:
            out.add(n)
    return out


def _tokens(name: str) -> list:
    return [w for w in re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()).split() if len(w) > 2]


async def _verify_started(before: set, name_hint: str, wait: float = 1.8):
    """Comprueba de VERDAD si arrancó LO QUE SE PIDIÓ, comparando procesos
    antes/después. Devuelve (estado, detalle):
      'yes'     = arrancó (o ya estaba) un proceso que CASA con el nombre pedido
      'other'   = arrancó algo, pero NO casa con el nombre (quizá un launcher/otra cosa)
      'no'      = no arrancó nada ni casa nada → NO se abrió (no mentimos)
      'unknown' = sin psutil, no se puede verificar → se da por lanzado sin afirmar de más."""
    if psutil is None:
        return "unknown", ""
    import asyncio as _a
    await _a.sleep(wait)
    after = _proc_names()
    new = after - before
    toks = _tokens(name_hint)
    def casa(n):
        return any(t in n for t in toks)
    new_match = [n for n in new if casa(n)]
    if new_match:
        return "yes", new_match[0]
    if any(casa(n) for n in after):          # ya estaba abierto y coincide con el nombre
        return "yes", next(n for n in after if casa(n)) + " (ya estaba en marcha)"
    if new:
        return "other", sorted(new, key=len)[-1]   # abrió algo, pero no casa el nombre
    return "no", ""


def _steam_root():
    """Carpeta raíz de Steam (registro o rutas por defecto). None si no está."""
    if sys.platform == "win32":
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
            p = winreg.QueryValueEx(k, "SteamPath")[0]
            if p and Path(p).exists():
                return Path(p)
        except Exception:
            pass
    for c in (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"):
        if Path(c).exists():
            return Path(c)
    return None


def _steam_installed() -> list:
    """Juegos Steam INSTALADOS: [(appid, nombre)] leyendo appmanifest_*.acf."""
    root = _steam_root()
    if not root:
        return []
    libs = [root / "steamapps"]
    try:
        vdf = (root / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r'"path"\s*"([^"]+)"', vdf):
            libs.append(Path(m.group(1).replace("\\\\", "\\")) / "steamapps")
    except Exception:
        pass
    games, seen = [], set()
    for lib in libs:
        try:
            for acf in lib.glob("appmanifest_*.acf"):
                t = acf.read_text(encoding="utf-8", errors="ignore")
                aid = re.search(r'"appid"\s*"(\d+)"', t)
                nm = re.search(r'"name"\s*"([^"]+)"', t)
                if aid and nm and aid.group(1) not in seen:
                    seen.add(aid.group(1))
                    games.append((aid.group(1), nm.group(1)))
        except Exception:
            continue
    return games


def _match_steam_game(query: str):
    """Empareja la petición con un juego INSTALADO. (appid, nombre) o (None, None)."""
    q = query.lower().strip()
    qtok = _tokens(q)
    for aid, nm in _steam_installed():
        low = nm.lower()
        if q in low or low in q or any(t in low for t in qtok):
            return aid, nm
    return None, None


async def handle(intent: str, text: str, match, ctx) -> dict:
    bus = ctx["bus"]

    if intent == "volume":
        num = match.groupdict().get("vol")
        if not num:  # «pon el volumen al 40» entra por la 2ª alternativa: rescata el número
            m2 = re.search(r"\b(\d{1,3})\s*%?", text)
            num = m2.group(1) if m2 else None
        target = f"al {num}%" if num else ("subido" if "sube" in text.lower() else "bajado")
        if sys.platform == "win32":
            try:  # nircmd si está en PATH; si no, simulado
                if num:
                    subprocess.run(["nircmd", "setsysvolume", str(int(int(num) * 655.35))],
                                   timeout=3, check=True)
                else:
                    step = "5000" if "sube" in text.lower() else "-5000"
                    subprocess.run(["nircmd", "changesysvolume", step], timeout=3, check=True)
                return {"reply": f"Volumen {target}. ✔"}
            except Exception:
                pass
        return {"reply": f"Volumen {target}… en teoría. Aún no tengo nircmd para tocarlo de "
                         "verdad: descárgalo de nirsoft.net y deja nircmd.exe en el PATH; "
                         "a partir de ahí el control es real."}

    if intent == "hardware":
        from backend.core import permissions
        if not permissions.hardware_allowed():
            return {"reply": permissions.HW_DENIED}
        return {"reply": f"Informe de sistemas: {_hw_report()}. "
                         "Si quieres afinar, di «lista los procesos» y vemos quién consume."}

    if intent == "temps":
        from backend.core import permissions
        if not permissions.hardware_allowed():
            return {"reply": permissions.HW_DENIED}
        return {"reply": f"Temperaturas: {_temps_report()}"}

    if intent == "processes":
        if psutil is None:
            return {"reply": "No puedo leer los procesos: falta psutil (pip install psutil y "
                             "reinicia). No me invento una lista."}
        procs = sorted(psutil.process_iter(["name", "memory_info"]),
                       key=lambda p: p.info["memory_info"].rss if p.info["memory_info"] else 0,
                       reverse=True)[:8]
        top = " · ".join(f"{p.info['name']} {p.info['memory_info'].rss/2**20:.0f} MB"
                         for p in procs if p.info["name"])
        return {"reply": f"Top procesos por memoria: {top}. "
                         "Di «cierra el proceso <nombre>» y tumbo el que sobre."}

    if intent == "kill":
        gd = match.groupdict()
        name = next((gd.get(k) for k in ("proc", "proc2", "proc3", "proc4") if gd.get(k)), "")
        if psutil is None:
            return {"reply": f"Sin psutil no puedo tocar procesos de verdad (pip install psutil "
                             f"y reinicia). No he terminado «{name}»."}
        low = name.lower()
        exactos, parciales = [], []
        for p in psutil.process_iter(["name", "pid"]):
            n = (p.info.get("name") or "")
            if not n:
                continue
            nl = n.lower()
            if nl == low or nl == f"{low}.exe" or nl.rsplit(".", 1)[0] == low:
                exactos.append((p, n, p.info.get("pid")))
            elif low in nl:
                parciales.append((p, n, p.info.get("pid")))
        # El nombre exacto manda: «cierra el proceso code» no debe llevarse
        # también a «codecs_host». Solo si no casa ninguno se usa la subcadena.
        victimas = exactos or parciales
        if not victimas:
            return {"reply": f"No encuentro ningún proceso llamado «{name}». "
                             "Di «lista los procesos» y te enseño los que hay en marcha."}

        # Cerrar procesos es directo, sin confirmación: es lo que se le pide.
        ok, fallidos = 0, 0
        for p, _n, _pid in victimas:
            try:
                p.terminate()
                ok += 1
            except Exception:                              # noqa: BLE001
                fallidos += 1
        if not ok:
            return {"reply": f"No he podido terminar ninguno de los {len(victimas)} proceso(s) "
                             f"de «{name}»: seguramente hagan falta permisos de administrador."}
        # Un solo nombre, sin PIDs: lo que el operador quiere saber es que ya está.
        programa = victimas[0][1]
        for _p, n, _pid in victimas:
            if n.lower().startswith(low):
                programa = n
                break
        programa = programa.rsplit(".", 1)[0] if programa.lower().endswith(".exe") else programa
        extra = f" ({fallidos} instancia(s) se han resistido, seguramente por permisos)" \
            if fallidos else ""
        return {"reply": f"{programa.title()} cerrado{extra}.",
                "data": {"killed": ok, "failed": fallidos}}

    if intent == "youtube":
        q = (match.groupdict().get("yt") or match.groupdict().get("yt2") or "").strip()
        url = f"https://www.youtube.com/results?search_query={q.replace(' ', '+')}" if q \
            else "https://www.youtube.com"
        webbrowser.open(url)
        return {"reply": f"Abriendo YouTube{f' y buscando «{q}»' if q else ''}."}

    if intent == "open_web":
        raw = (match.group("url") or "").strip().rstrip(".?!,;:")
        low_raw = raw.lower()
        # 1) URL o dominio explícito → directo, sin pensar
        if raw.startswith("http://") or raw.startswith("https://"):
            webbrowser.open(raw)
            return {"reply": f"Abriendo {raw}."}
        if "." in raw and " " not in raw:
            webbrowser.open("https://" + raw)
            return {"reply": f"Abriendo https://{raw}."}
        # 2) Webs ya APRENDIDAS (el modelo las dedujo antes) → instantáneo
        import json as _json
        from backend.core.config import DATA_DIR
        cache_file = DATA_DIR / "web_urls.json"
        try:
            cache = _json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
        if low_raw in cache:
            webbrowser.open(cache[low_raw])
            return {"reply": f"Abriendo {raw} ({cache[low_raw]})."}
        # 3) El MODELO razona la URL oficial de CUALQUIER web que le pidas
        #    (sin listas fijas). Si acierta, la memoriza para la próxima vez.
        url = ""
        try:
            from backend.core.llm import get_provider_safe
            prov = await get_provider_safe()
            if prov is not None and prov.name != "mock":
                out = await prov.chat([
                    {"role": "system", "content":
                     "Devuelve SOLO la URL oficial y completa (empezando por https://) "
                     "de la web que te pida el usuario. Una sola línea, sin comillas ni "
                     "explicaciones. Prioriza la versión española (.es o /es) si existe. "
                     "Si de verdad no conoces su web oficial, responde exactamente SEARCH."},
                    {"role": "user", "content": f"La web de: {raw}"}])
                cand = (out or "").strip().splitlines()[0].strip().strip('"\'«»<>').rstrip(".")
                if re.match(r"^https?://[\w.\-]+(?::\d+)?(?:/\S*)?$", cand) \
                        and "SEARCH" not in cand.upper():
                    url = cand
        except Exception:
            pass
        if url:
            webbrowser.open(url)
            cache[low_raw] = url          # aprendida: la próxima vez ni lo piensa
            try:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(_json.dumps(cache, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
            except Exception:
                pass
            return {"reply": f"Abriendo la web de {raw} → {url}"}
        # 4) Último recurso (modelo apagado o no la conoce): búsqueda en Google,
        #    que es lo honesto — mejor que inventarse un dominio.
        webbrowser.open(f"https://www.google.com/search?q={raw.replace(' ', '+')}")
        return {"reply": f"No he podido deducir la URL de «{raw}» (¿modelo apagado?); "
                         "te la he buscado en Google — el primer resultado será su web."}

    if intent == "set_mac":
        mac = match.group("mac")
        ctx["settings"].set("wol_mac", mac)
        return {"reply": f"MAC guardada ({mac}). Ahora puedo encender ese equipo con "
                         "«enciende el ordenador» (necesita Wake-on-LAN activado en su BIOS)."}

    if intent == "wake":
        mac = ctx["settings"].get("wol_mac", "")
        if not mac:
            return {"reply": "No tengo la MAC del equipo a encender. Dímela: «guarda la mac "
                             "aa:bb:cc:dd:ee:ff» (la ves con «ipconfig /all» → Dirección física). "
                             "Y activa Wake-on-LAN en la BIOS y en el adaptador de red del PC."}
        bcast = ctx["settings"].get("wol_broadcast", "255.255.255.255")
        ok = _send_magic_packet(mac, bcast)
        return {"reply": f"Paquete mágico enviado a {mac}. Si el equipo tiene Wake-on-LAN "
                         "activado y está en la misma red, debería encenderse en unos segundos."
                if ok else "No he podido enviar el paquete (¿MAC válida? ¿red disponible?)."}

    if intent == "reindex":
        from backend.core.app_index import build_index
        import asyncio
        apps = await asyncio.to_thread(build_index)
        return {"reply": f"Índice reconstruido: conozco {len(apps)} aplicaciones instaladas."
                if apps else "Índice vacío (esto solo funciona en Windows)."}

    if intent == "list_apps":
        from backend.core.app_index import get_index
        apps = get_index()
        if not apps:
            return {"reply": "Aún no tengo índice de aplicaciones (¿estamos en Windows? "
                             "prueba «reindexa las aplicaciones»)."}
        sample = " · ".join(sorted(apps)[:25])
        return {"reply": f"Conozco {len(apps)} aplicaciones instaladas. Muestra: {sample}…"}

    if intent == "open_app":
        app = match.group("app").strip().rstrip(".?!")
        low = app.lower().strip()
        # 1) Webs frecuentes (no son apps instaladas)
        web_alias = {"internet": "https://www.google.com",
                     "whatsapp web": "https://web.whatsapp.com",
                     "gmail": "https://mail.google.com",
                     "el calendario de google": "https://calendar.google.com",
                     "twitch": "https://www.twitch.tv"}
        if low in web_alias:
            webbrowser.open(web_alias[low])
            return {"reply": f"Abriendo {app}."}

        # 2) ÍNDICE COMPLETO de aplicaciones instaladas (Menú Inicio +
        #    registro + Microsoft Store) con búsqueda difusa.
        #    Si el índice está vacío (primer uso / arranque incompleto),
        #    lo construimos AHORA en vez de decir que no se puede.
        import asyncio
        from backend.core.app_index import build_index, find_app, get_index, launch
        if not get_index() and sys.platform == "win32":
            await ctx["bus"].emit("log", {"level": "info",
                                          "msg": "Índice de apps vacío — escaneando ahora..."})
            await asyncio.to_thread(build_index)
        hit = find_app(app)
        if hit:
            name, target = hit
            before = _proc_names()
            try:
                launch(target)
            except Exception as exc:
                return {"reply": f"He encontrado «{name}» pero no se deja abrir: {exc}"}
            st, detail = await _verify_started(before, name or app)
            if st == "no":
                return {"reply": f"He intentado abrir «{name.title()}» pero NO detecto que "
                                 "haya arrancado. ¿Sigue cargando, o el acceso directo apunta a "
                                 "algo que ya no existe? (prueba «reindexa las aplicaciones»)."}
            if st == "other":
                return {"reply": f"He lanzado algo ({detail}) pero no estoy seguro de que sea "
                                 f"«{name.title()}». Échale un ojo, por si acaso."}
            if st == "yes":
                return {"reply": f"Listo, {name.title()} está abierto. ✓"}
            return {"reply": f"Abriendo {name.title()}…"}   # sin psutil: no puedo confirmar

        # 3b) ¿Es un JUEGO de Steam INSTALADO? Solo lanzamos lo que está instalado:
        #     si no, mentiríamos diciendo que lo abrimos.
        if sys.platform == "win32":
            aid, gname = _match_steam_game(app)
            if aid:
                before = _proc_names()
                os.system(f'start "" steam://rungameid/{aid}')
                st, _d = await _verify_started(before, gname, wait=3.0)
                if st == "no":
                    return {"reply": f"He pedido a Steam abrir «{gname}» (appid {aid}) pero no "
                                     "arranca. Revisa que Steam esté abierto y con la sesión iniciada."}
                return {"reply": f"Lanzando «{gname}» desde Steam ▶ ✓"}
            # No está instalado → NO decimos que lo abrimos. Ofrecemos la tienda.
            store = await asyncio.to_thread(_steam_appid_by_name, app)
            if store:
                return {"reply": f"No veo «{app}» instalado en Steam, así que no puedo abrirlo. "
                                 f"Existe en la tienda; si quieres instalarlo dime «instala {app} en steam»."}

        # 3) Último recurso: comandos clásicos de Windows / protocolo URI.
        #    OJO: los valores NO llevan 'start' (ya lo añade el wrapper de abajo);
        #    antes ponía «start "" start spotify:» y por eso no abría Spotify.
        alias = {"calculadora": "calc", "notas": "notepad", "explorador": "explorer",
                 "navegador": "chrome", "terminal": "cmd", "cmd": "cmd",
                 "spotify": "spotify:", "steam": "steam://open/main",
                 "epic": "com.epicgames.launcher://", "whatsapp": "whatsapp:"}
        before = _proc_names()
        try:
            if sys.platform == "win32":
                if low == "discord":
                    os.system('start "" "%LOCALAPPDATA%\\Discord\\Update.exe" --processStart Discord.exe')
                else:
                    os.system(f'start "" {alias.get(low, app)}')
            else:
                subprocess.Popen(alias.get(low, app).split())
        except Exception as exc:
            return {"reply": f"No he podido abrir «{app}»: {exc}"}
        st, detail = await _verify_started(before, app)
        if st == "no":
            return {"reply": f"No encuentro «{app}» instalado (ni en el índice ni como app "
                             "conocida), así que no se ha abierto nada. Dime el nombre exacto o "
                             "«reindexa las aplicaciones»."}
        if st == "other":
            return {"reply": f"He lanzado algo ({detail}) pero no estoy seguro de que sea "
                             f"«{app}». Compruébalo, por favor."}
        if st == "yes":
            return {"reply": f"Listo, «{app}» está abierto. ✓"}
        return {"reply": f"Abriendo «{app}»…"}

    if intent == "screenshot":
        SHOTS_DIR.mkdir(parents=True, exist_ok=True)
        out = SHOTS_DIR / f"captura-{dt.datetime.now():%Y%m%d-%H%M%S}.png"
        try:
            import mss
            with mss.mss() as sct:
                sct.shot(output=str(out))
            return {"reply": f"Captura guardada en data/captures/{out.name}. ✔"}
        except Exception:
            return {"reply": "Aún no puedo capturar la pantalla de verdad: instala mss "
                             "(pip install mss) y reinicia; la captura quedaría en "
                             "data/captures/ con fecha y hora."}

    if intent == "webcam":
        SHOTS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            import cv2
            cam = cv2.VideoCapture(0)
            ok, frame = cam.read()
            cam.release()
            if ok:
                out = SHOTS_DIR / f"webcam-{dt.datetime.now():%Y%m%d-%H%M%S}.jpg"
                cv2.imwrite(str(out), frame)
                return {"reply": f"Foto tomada: data/captures/{out.name}. ✔"}
        except Exception:
            pass
        return {"reply": "No consigo abrir la webcam: instala opencv-python "
                         "(pip install opencv-python) y comprueba que ninguna otra app "
                         "la esté usando. La foto iría a data/captures/."}

    if intent in ("shutdown", "restart"):
        apagar = intent == "shutdown"
        verbo = "apagar" if apagar else "reiniciar"
        yo = "apago" if apagar else "reinicio"
        from backend.core import confirm
        canal = (ctx or {}).get("channel", "pc") if isinstance(ctx, dict) else "pc"
        abiertos = len(_proc_names()) if psutil is not None else 0
        cuantos = (f" Ahora mismo hay {abiertos} programa(s) distintos en marcha y "
                   "se cerrarán todos." if abiertos else "")

        def _ejecutar(_apagar=apagar):
            if sys.platform != "win32":
                return f"No sé {verbo} este sistema operativo, así que no he hecho nada."
            os.system("shutdown /s /t 15" if _apagar else "shutdown /r /t 15")
            return (f"{'Apagando' if _apagar else 'Reiniciando'} en 15 segundos. "
                    "Si te has arrepentido, aún puedes cancelarlo con: shutdown /a")

        await bus.emit("alert", {"level": "warn",
                                 "msg": f"{verbo.upper()} SOLICITADO — esperando confirmación"})
        pregunta = (f"⚠ Voy a {verbo} este equipo en 15 segundos desde que me digas que sí."
                    f"{cuantos} Lo que no esté guardado se pierde.\n"
                    f"¿Lo {yo}? Responde «sí» o «no» "
                    f"(o la frase exacta «confirmo {'apagado' if apagar else 'reinicio'}»).")
        return {"reply": confirm.request(
            channel=canal, kind=f"{verbo}_equipo", summary=pregunta,
            action=_ejecutar, request_text=text, targets=[{"host": platform.node()}],
            cancel_reply=f"Cancelado, no {yo} nada."),
            "data": {"confirm": True}}

    if intent in ("shutdown_confirm", "restart_confirm"):
        # si hubiera algo armado, el brain lo habría resuelto antes del router
        que = "apagado" if intent == "shutdown_confirm" else "reinicio"
        return {"reply": f"No hay ningún {que} pendiente de confirmar, así que no he hecho "
                         f"nada. Si lo quieres de verdad, dime «{'apaga' if que == 'apagado' else 'reinicia'} el pc»."}

    return {"reply": "Esa orden de sistema no la tengo mapeada. Puedo darte el estado del "
                     "equipo, temperaturas, procesos, abrir apps y webs, capturas, webcam, "
                     "y apagar o reiniciar (siempre con confirmación)."}
