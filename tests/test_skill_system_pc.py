# -*- coding: utf-8 -*-
"""Auditoría de la skill SISTEMA/PC: activación con frases naturales, enrutado
real, fronteras con clima/domotica/games/discord, y confirmación obligatoria
antes de matar procesos, apagar o reiniciar.

No apaga, no reinicia y no mata nada: psutil se sustituye por un doble con una
lista de procesos inventada y `os.system` se intercepta para apuntar el comando
en vez de ejecutarlo.

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_skill_system_pc.py
"""
from __future__ import annotations

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_fail = []
_pass = 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  ✖ " + msg)


from backend.core import confirm, skills_loader as sl       # noqa: E402

# ------------------------------------------------- 1) carga con el cargador real
print("== 1) la skill carga como la carga nexus (skills_loader) ==")
REG = sl.load_skills()
SSK = REG.get("system_pc")
check(SSK is not None, "skills_loader no registra la carpeta 'system_pc'")
check(SSK is not None and SSK.status != "error",
      f"la skill system_pc no carga: {SSK.description if SSK else ''}")
MOD = SSK.module if SSK else None
check(MOD is not None and hasattr(MOD, "handle"), "system_pc no expone handle()")

INTENTS = list(SSK.patterns.keys()) if SSK else []
for i in ("volume", "temps", "hardware", "processes", "kill", "youtube", "open_web",
          "reindex", "list_apps", "open_app", "screenshot", "webcam",
          "shutdown", "shutdown_confirm", "restart", "restart_confirm",
          "wake", "set_mac"):
    check(i in INTENTS, f"falta el intent «{i}»")

# --------------------------------------------- 2) activación: frases naturales
print("== 2) activación con frases naturales (tildes, enclíticos, sinónimos) ==")
ACTIVAN = {
    "hardware": ["estado del sistema", "cómo anda mi pc", "uso de la cpu",
                 "cuánta ram queda", "diagnóstico del equipo"],
    "temps": ["qué temperatura tiene la cpu", "cómo van las temperaturas",
              "está muy caliente la gpu", "cuántos grados marca la cpu"],
    "processes": ["lista los procesos", "lístame los procesos",
                  "muéstrame los procesos", "qué procesos hay",
                  "qué se está comiendo la ram", "qué consume más cpu"],
    "kill": ["cierra el proceso chrome", "ciérrame el proceso chrome",
             "mata spotify", "mátame el proceso spotify", "termina discord.exe",
             "cierra la aplicación discord", "cierra el programa spotify"],
    "open_app": ["abre spotify", "ábreme spotify", "arranca la calculadora"],
    "open_web": ["abre la web de marca", "ábreme la página de renfe"],
    "youtube": ["abre youtube y busca lofi"],
    "volume": ["pon el volumen al 40", "volumen al 75%", "sube el volumen del pc"],
    "screenshot": ["haz una captura de pantalla", "hazme un pantallazo",
                   "sácame una captura"],
    "webcam": ["haz una foto con la webcam", "sácame una foto", "échame una foto"],
    "set_mac": ["guarda la mac aa:bb:cc:dd:ee:ff"],
    "shutdown": ["apaga el pc", "apágame el ordenador", "apaga el equipo"],
    "restart": ["reinicia el pc", "reinicia el ordenador", "reiníciame el equipo"],
    "list_apps": ["qué aplicaciones tienes", "lista las aplicaciones instaladas"],
    "reindex": ["reindexa las aplicaciones"],
}
for intent, frases in ACTIVAN.items():
    for f in frases:
        r = sl.route(f)
        destino = f"{r[0].folder}/{r[1]}" if r else "ningún sitio"
        check(bool(r) and r[0].folder == "system_pc" and r[1] == intent,
              f"«{f}» debería ser system_pc/{intent} y va a {destino}")

# el nombre del proceso tiene que llegar limpio, no la palabra de ancla
for frase, esperado in (("cierra el proceso chrome", "chrome"),
                        ("ciérrame el proceso chrome", "chrome"),
                        ("mátame el proceso spotify", "spotify"),
                        ("mata spotify", "spotify"),
                        ("termina discord.exe", "discord.exe"),
                        ("cierra el programa spotify", "spotify")):
    r = sl.route(frase)
    gd = r[2].groupdict() if r else {}
    nombre = next((gd.get(k) for k in ("proc", "proc2", "proc3", "proc4") if gd.get(k)), "")
    check(nombre == esperado, f"«{frase}» captura «{nombre}» en vez de «{esperado}»")

# ------------------------------------------------- 3) fronteras con otras skills
print("== 3) fronteras: no roba lo que es de otras skills, ni al revés ==")
DE_OTROS = {
    "qué temperatura hace en Madrid": "clima",
    "enciende el ordenador": "domotica",
    "despierta el pc": "domotica",
    "instala rust en steam": "games",
}
for f, duenyo in DE_OTROS.items():
    r = sl.route(f)
    check(bool(r) and r[0].folder == duenyo,
          f"«{f}» es de {duenyo} y va a " + (f"{r[0].folder}/{r[1]}" if r else "ningún sitio"))

# el lookahead de open_app tiene que dejar pasar los dominios ajenos
for f in ("abre el tablero", "abre los correos", "abre las pestañas"):
    r = sl.route(f)
    check(not r or r[0].folder != "system_pc" or r[1] != "open_app",
          f"«{f}» no es una app instalada y lo coge open_app")

# ------------------------------------------------- 4) dobles: nada real se toca
print("== 4) matar procesos exige confirmación y previsualiza qué se lleva ==")


class _ProcDoble:
    def __init__(self, name, pid):
        self.info = {"name": name, "pid": pid}
        self.terminado = False

    def terminate(self):
        self.terminado = True


class _PsutilDoble:
    def __init__(self):
        self.procesos = [_ProcDoble("chrome.exe", 101), _ProcDoble("chrome.exe", 102),
                         _ProcDoble("code.exe", 200), _ProcDoble("explorer.exe", 300)]

    def process_iter(self, _campos=None):
        return list(self.procesos)


PS = _PsutilDoble()
_psutil_real = MOD.psutil
MOD.psutil = PS

_comandos = []
_os_system_real = MOD.os.system
MOD.os.system = lambda cmd: _comandos.append(cmd)


class _BusDoble:
    async def emit(self, *_a, **_k):
        return None


class _SettingsDoble:
    def __init__(self):
        self.datos = {}

    def get(self, k, d=""):
        return self.datos.get(k, d)

    def set(self, k, v):
        self.datos[k] = v


CTX = {"bus": _BusDoble(), "settings": _SettingsDoble(), "channel": "pc"}


def _handle(frase):
    r = sl.route(frase)
    assert r and r[0].folder == "system_pc", f"«{frase}» no llega a system_pc: {r}"
    return asyncio.run(MOD.handle(r[1], frase, r[2], CTX))


confirm.clear()
res = _handle("cierra el proceso chrome")
reply = res.get("reply", "")
check(not any(p.terminado for p in PS.procesos),
      "¡«cierra el proceso chrome» ha matado procesos SIN confirmación!")
check(confirm.pending("pc") is not None, "matar procesos no arma ninguna confirmación")
check("chrome.exe" in reply and "101" in reply,
      "la pregunta no enseña qué procesos (nombre y PID) se va a llevar")
check("2 proceso" in reply, "la pregunta no dice CUÁNTOS procesos casan")
check("sí" in reply.lower() and "no" in reply.lower(), "la pregunta no pide un sí/no")

respuesta = asyncio.run(confirm.answer("no", "pc")) or ""
check(not any(p.terminado for p in PS.procesos), "un «no» ha matado procesos igualmente")

confirm.clear()
_handle("cierra el proceso chrome")
respuesta = asyncio.run(confirm.answer("sí", "pc")) or ""
check(sum(1 for p in PS.procesos if p.terminado) == 2,
      "tras el «sí» no ha terminado los dos chrome.exe")
check(all(not p.terminado for p in PS.procesos if p.info["name"] != "chrome.exe"),
      "ha terminado procesos que NO casaban con el nombre pedido")
check("2" in respuesta, "no informa de cuántos ha terminado")
confirm.clear()

# proceso inexistente: lo dice, no arma nada
for p in PS.procesos:
    p.terminado = False
res = _handle("cierra el proceso noexistejamas")
check("no encuentro" in res.get("reply", "").lower(),
      "un proceso inexistente no se avisa con claridad")
check(confirm.pending("pc") is None, "arma una confirmación para un proceso que no existe")

# ------------------------------------------------- 5) apagado y reinicio
print("== 5) apagar y reiniciar: nada se ejecuta sin confirmación ==")
for frase, marca in (("apaga el pc", "/s"), ("reinicia el pc", "/r")):
    confirm.clear()
    _comandos.clear()
    res = _handle(frase)
    reply = res.get("reply", "")
    check(not _comandos, f"¡«{frase}» ha lanzado el comando SIN confirmación!")
    check(confirm.pending("pc") is not None, f"«{frase}» no arma ninguna confirmación")
    check("sí" in reply.lower() and "no" in reply.lower(),
          f"«{frase}» no pide un sí/no")
    check("pierde" in reply.lower() or "guardado" in reply.lower(),
          f"«{frase}» no avisa de que se pierde lo no guardado")
    asyncio.run(confirm.answer("no", "pc"))
    check(not _comandos, f"un «no» ha ejecutado «{frase}» igualmente")

    confirm.clear()
    _comandos.clear()
    _handle(frase)
    asyncio.run(confirm.answer("sí", "pc"))
    if sys.platform == "win32":
        check(len(_comandos) == 1 and marca in _comandos[0],
              f"tras el «sí», «{frase}» no lanza shutdown {marca}: {_comandos}")
    confirm.clear()

# la frase exacta también vale, y sin nada armado no dispara nada
_comandos.clear()
confirm.clear()
res = _handle("confirmo apagado")
check(not _comandos, "«confirmo apagado» sin nada armado ha apagado el equipo")
check("no hay ningún apagado" in res.get("reply", "").lower(),
      "«confirmo apagado» sin nada armado no responde con honestidad")
res = _handle("confirmo reinicio")
check(not _comandos, "«confirmo reinicio» sin nada armado ha reiniciado el equipo")

# ------------------------------------------------- 6) honestidad sin psutil
print("== 6) sin psutil no inventa cifras ni listas ==")
MOD.psutil = None
res = _handle("lista los procesos")
reply = res.get("reply", "")
check("psutil" in reply, "sin psutil no dice qué falta instalar")
check("MB" not in reply and "GB" not in reply,
      "sin psutil se inventa una lista de procesos con cifras")
informe = MOD._hw_report()
check("psutil" in informe, "el informe de hardware sin psutil no dice qué falta")
check("%" not in informe, "el informe de hardware sin psutil se inventa porcentajes")
res = _handle("cierra el proceso chrome")
check("psutil" in res.get("reply", ""), "sin psutil, matar procesos no dice qué falta")
check("no he terminado" in res.get("reply", "").lower(),
      "sin psutil no deja claro que NO ha terminado nada")

MOD.psutil = _psutil_real
MOD.os.system = _os_system_real

# ------------------------------------------------- 7) agnóstica
print("== 7) agnóstica: sin nombres propios ni rutas del usuario ==")
import re as _re                                            # noqa: E402

src = open(os.path.join(ROOT, "skills", "system_pc", "skill.py"), encoding="utf-8").read()
md = open(os.path.join(ROOT, "skills", "system_pc", "SKILL.md"), encoding="utf-8").read()
_PROPIOS = _re.compile(r"\b(achoz|adri|adri[aá]n|C:\\Users\\a)\b", _re.I)
check(not _PROPIOS.search(src), "skill.py lleva dentro datos del usuario")
check(not _PROPIOS.search(md), "SKILL.md lleva dentro datos del usuario")

# ------------------------------------------------- 8) SKILL.md dice la verdad
print("== 8) SKILL.md: lo que promete se activa de verdad ==")
# solo la sección de órdenes: la de fronteras enseña, a propósito, lo que NO es suyo
_cuerpo = md.split("## Órdenes de ejemplo")[-1].split("## Fronteras")[0]
_ejemplos = [ln for ln in _cuerpo.splitlines() if ln.startswith("- «")]
for ln in _ejemplos:
    for frase in _re.findall(r"«([^»\n]+)»", ln):
        if frase.startswith(("confirmo", "sí", "no", "wake on lan")):
            continue
        r = sl.route(frase)
        check(bool(r) and r[0].folder == "system_pc",
              f"SKILL.md promete «{frase}» pero va a "
              + (f"{r[0].folder}/{r[1]}" if r else "ningún sitio"))

check("confirmación" in md.lower(), "SKILL.md no explica la confirmación")
check("domotica" in md.lower(), "SKILL.md no aclara que el Wake-on-LAN es de domotica")

print(f"\n{'#' * 54}\ntest_skill_system_pc: {_pass} OK, {len(_fail)} fallos")
if _fail:
    for f in _fail:
        print("  - " + f)
sys.exit(1 if _fail else 0)
