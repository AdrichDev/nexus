# -*- coding: utf-8 -*-
"""Auditoría de la skill SISTEMA/PC: activación con frases naturales, enrutado
real, fronteras con clima/domotica/games/discord, confirmación obligatoria antes
de apagar o reiniciar, y cierre de procesos directo pero con puntería.

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


from backend.core.aplicacion import skills_loader as sl
from backend.core.comun import confirm  # noqa: E402

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
for i in ("volume", "volume_app", "volume_ask",
          "temps", "hardware", "processes", "port_who", "ports", "kill",
          "youtube", "open_web",
          "reindex", "list_apps", "open_app", "screenshot", "webcam",
          "shutdown", "shutdown_confirm", "restart", "restart_confirm",
          "wake", "set_mac"):
    check(i in INTENTS, f"falta el intent «{i}»")

# LOS PATRONES ANCHOS VAN AL FINAL. `open_app` y `open_web` se quedan casi
# cualquier «abre X»; si un intent nuevo se cuela detrás de ellos, nunca se
# alcanza. Se comprueba el ORDEN del diccionario, que es el que recorre el router.
_ORDEN = list(SSK.patterns.keys()) if SSK else []
for antes, despues in (("port_who", "open_app"), ("ports", "open_app"),
                       ("port_who", "open_web"), ("ports", "open_web"),
                       ("port_who", "ports")):
    if antes in _ORDEN and despues in _ORDEN:
        check(_ORDEN.index(antes) < _ORDEN.index(despues),
              f"«{antes}» va detrás de «{despues}» en el diccionario de intents: "
              "el patrón ancho se lo come antes de llegar")

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
    # PUERTOS. Ninguna de las 32 skills sabía mirar puertos, así que estas
    # preguntas caían al planificador y el modelo rellenaba el hueco: una vez
    # delegó en Hermes y acertó, otra devolvió un ranking de procesos por
    # memoria, al instante y con total seguridad. No determinista y falso.
    "port_who": ["qué programa está usando el puerto 5678",
                 "qué hay en el puerto 8177",
                 "quién está escuchando en el puerto 3000",
                 "qué proceso usa el puerto 443",
                 "mira el puerto 8080",
                 "el puerto 5432"],
    "ports": ["qué puertos tengo abiertos", "lista los puertos abiertos",
              "qué puertos hay abiertos", "puertos en escucha",
              "muéstrame los puertos abiertos"],
    "kill": ["cierra el proceso chrome", "ciérrame el proceso chrome",
             "mata spotify", "mátame el proceso spotify", "termina discord.exe",
             "cierra la aplicación discord", "cierra el programa spotify",
             # forma corta: es como se dice de verdad, y antes caía al planificador
             "cierra chrome", "ciérrame chrome", "cierra el chrome", "cierra spotify",
             "cierra discord", "termina spotify", "cierra el navegador",
             "cierra la calculadora"],
    # Brillo de la PANTALLA. El SKILL.md de media lleva tiempo mandándolo aquí y
    # aquí no había nada: la frase caía al planificador.
    "brightness": ["pon el brillo al 80", "sube el brillo", "baja el brillo",
                   "brillo al 50", "pon el brillo de la pantalla al 30",
                   "sube el brillo de la pantalla"],
    "open_app": ["abre spotify", "ábreme spotify", "arranca la calculadora"],
    # Cualquier web, no una lista de sitios: con la palabra «web/página», con un
    # dominio a pelo, o con los verbos de navegar.
    "open_web": ["abre la web de marca", "ábreme la página de renfe",
                 "ponme la web del as", "entra en la web de marca",
                 "abre marca.com", "ábreme marca.com", "abre www.marca.com",
                 "métete en elmundo.es", "visita github.com",
                 "abre https://ejemplo.org/ruta"],
    "youtube": ["abre youtube y busca lofi"],
    # El destino del volumen lo dice SIEMPRE quien da la orden: el PC, una
    # aplicación, o nada — y entonces se pregunta, no se adivina.
    "volume": ["sube el volumen del pc", "baja el volumen del ordenador",
               "pon el volumen del pc al 40", "silencia el pc",
               "quita el silencio del pc", "sube el volumen del equipo"],
    "volume_app": ["sube el volumen de spotify", "baja el volumen de chrome",
                   "pon el volumen de discord al 30", "silencia spotify",
                   "quita el sonido de chrome", "quita el silencio de spotify"],
    "volume_ask": ["sube el volumen", "más volumen", "pon el volumen al 50",
                   "volumen al 75%", "silencia", "quita el sonido"],
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
    nombre = next((gd.get(k) for k in ("proc", "proc2", "proc3", "proc4", "proc5")
                   if gd.get(k)), "")
    check(nombre == esperado, f"«{frase}» captura «{nombre}» en vez de «{esperado}»")

# El cierre corto captura el programa, no el artículo ni el verbo.
for frase, esperado in (("cierra chrome", "chrome"), ("cierra el chrome", "chrome"),
                        ("ciérrame spotify", "spotify"), ("termina discord", "discord"),
                        ("cierra el navegador", "navegador")):
    r = sl.route(frase)
    gd = r[2].groupdict() if r else {}
    nombre = next((gd.get(k) for k in ("proc", "proc2", "proc3", "proc4", "proc5")
                   if gd.get(k)), "")
    check(nombre == esperado, f"«{frase}» captura «{nombre}» en vez de «{esperado}»")

# La URL se captura entera, venga como venga.
for frase, esperado in (("abre la web de marca", "marca"), ("abre marca.com", "marca.com"),
                        ("abre www.marca.com", "www.marca.com"),
                        ("métete en elmundo.es", "elmundo.es"),
                        ("ponme la web del as", "as")):
    r = sl.route(frase)
    gd = r[2].groupdict() if r else {}
    url = (gd.get("url") or gd.get("url2") or "").strip()
    check(url == esperado, f"«{frase}» captura la web «{url}» en vez de «{esperado}»")

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

# El brillo de una BOMBILLA es de domotica, no de la pantalla del PC.
for f in ("pon el brillo de la luz del salón al 40", "baja el brillo de la lámpara",
          "sube el brillo de la bombilla"):
    r = sl.route(f)
    check(not r or r[0].folder != "system_pc",
          f"«{f}» es de domotica y se lo queda system_pc")

# el lookahead de open_app tiene que dejar pasar los dominios ajenos
for f in ("abre el tablero", "abre los correos", "abre las pestañas"):
    r = sl.route(f)
    check(not r or r[0].folder != "system_pc" or r[1] != "open_app",
          f"«{f}» no es una app instalada y lo coge open_app")

# Y el cierre corto no puede tragarse lo que no es un programa. Estas frases o
# son de otra skill o no son de nadie, pero de system_pc/kill no son.
NO_SON_PROGRAMAS = ("cierra el tablero", "cierra las tareas", "cierra la sesión",
                    "cierra la ventana", "cierra la pestaña de twitter",
                    "cierra la persiana", "cierra la tele", "cierra los correos",
                    "cierra la factura", "cierra el chat", "cierra la boca",
                    "cierra el trato", "cierra el debate", "cierra el tema")
for f in NO_SON_PROGRAMAS:
    r = sl.route(f)
    check(not r or not (r[0].folder == "system_pc" and r[1] == "kill"),
          f"«{f}» no es un programa y lo coge system_pc/kill")

# ------------------------------------------------- 4) dobles: nada real se toca
print("== 4) cerrar procesos: directo, sin preguntar, y con puntería ==")


class _ProcDoble:
    def __init__(self, name, pid):
        self.info = {"name": name, "pid": pid}
        self.terminado = False

    def terminate(self):
        self.terminado = True


class _PsutilDoble:
    def __init__(self):
        self.procesos = [_ProcDoble("chrome.exe", 101), _ProcDoble("chrome.exe", 102),
                         _ProcDoble("code.exe", 200), _ProcDoble("codecs_host.exe", 201),
                         _ProcDoble("explorer.exe", 300)]

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


# Cerrar procesos es deliberadamente directo: la orden se ejecuta al vuelo.
confirm.clear()
res = _handle("cierra el proceso chrome")
reply = res.get("reply", "")
check(sum(1 for p in PS.procesos if p.terminado) == 2,
      "«cierra el proceso chrome» no ha terminado los dos chrome.exe")
check(confirm.pending("pc") is None,
      "cerrar procesos ha armado una confirmación, y tiene que ser directo")
check("chrome" in reply.lower(), "la respuesta no dice qué programa ha cerrado")
check(any(reply.startswith(p.split("{")[0]) or p.format(prog="Chrome") in reply
          for p in MOD._CERRADO_FRASES),
      "la respuesta no usa ninguna de las frases de cierre previstas")
check("101" not in reply and "pid" not in reply.lower(),
      "la respuesta suelta PIDs, y eso al operador no le dice nada")
# La frase se varía: repetida muchas veces, siempre igual suena a grabación.
frases_vistas = set()
for _ in range(40):
    for p in PS.procesos:
        p.terminado = False
    frases_vistas.add(_handle("cierra el proceso chrome").get("reply", ""))
check(len(frases_vistas) >= 3,
      f"la confirmación de cierre no varía: solo {len(frases_vistas)} frase(s) en 40 intentos")
check(all(not p.terminado for p in PS.procesos if p.info["name"] != "chrome.exe"),
      "ha terminado procesos que NO casaban con el nombre pedido")

# El nombre exacto manda sobre la subcadena: «code» no se lleva «codecs_host».
for p in PS.procesos:
    p.terminado = False
_handle("cierra el proceso code")
check([p.info["pid"] for p in PS.procesos if p.terminado] == [200],
      "«cierra el proceso code» se lleva por delante procesos que solo lo contienen")

# Sin nombre exacto sí vale la subcadena: «codecs» encuentra codecs_host.exe.
for p in PS.procesos:
    p.terminado = False
_handle("cierra el proceso codecs")
check([p.info["pid"] for p in PS.procesos if p.terminado] == [201],
      "sin nombre exacto no cae a la coincidencia por subcadena")

# proceso inexistente: lo dice y no toca nada
for p in PS.procesos:
    p.terminado = False
res = _handle("cierra el proceso noexistejamas")
check("no encuentro" in res.get("reply", "").lower(),
      "un proceso inexistente no se avisa con claridad")
check(not any(p.terminado for p in PS.procesos),
      "un proceso inexistente ha acabado terminando algo")

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

# ------------------------------------------------- 6b) puertos: o el dato o el «no sé»
print("== 6b) puertos: sin psutil NI netstat, lo dice; no aproxima ==")


class _SubprocessSinNetstat:
    """`netstat` que no está en el equipo. Es el peor caso real: sin psutil y sin
    la herramienta de respaldo no hay de dónde sacar el dato, y entonces la única
    respuesta honesta es decirlo."""

    def run(self, *_a, **_k):
        raise FileNotFoundError("netstat")


_subprocess_real = MOD.subprocess
MOD.subprocess = _SubprocessSinNetstat()
for frase in ("qué programa está usando el puerto 5678", "qué puertos tengo abiertos"):
    reply = _handle(frase).get("reply", "")
    low = reply.lower()
    check("no" in low and ("psutil" in low or "netstat" in low or "no puedo" in low
                           or "no he podido" in low),
          f"«{frase}» sin forma de mirar los puertos no dice que NO puede saberlo: {reply!r}")
    check("MB" not in reply and "GB" not in reply,
          f"«{frase}» devuelve un ranking de procesos por memoria en vez de puertos: {reply!r}")
MOD.subprocess = _subprocess_real

print("== 6c) puertos: el dato sale del sistema, y un puerto vacío se dice ==")


class _AddrDoble:
    def __init__(self, port):
        self.port = port


class _ConexionDoble:
    def __init__(self, port, status, pid):
        self.laddr = _AddrDoble(port)
        self.status = status
        self.pid = pid


class _ProcesoDoble:
    def __init__(self, nombre):
        self._nombre = nombre

    def name(self):
        return self._nombre


class _PsutilPuertosDoble:
    """psutil de mentira con una tabla de conexiones fija. Incluye a propósito
    una conexión ESTABLISHED y una escucha sin PID: la primera no es «un puerto
    abierto» y la segunda no tiene nombre que enseñar."""

    CONN_LISTEN = "LISTEN"

    class AccessDenied(Exception):
        pass

    class NoSuchProcess(Exception):
        pass

    NOMBRES = {4242: "node.exe", 700: "nexus.exe", 900: "postgres.exe"}

    def net_connections(self, kind="inet"):
        return [_ConexionDoble(5678, "LISTEN", 4242),
                _ConexionDoble(8177, "LISTEN", 700),
                _ConexionDoble(5432, "LISTEN", 900),
                _ConexionDoble(137, "LISTEN", None),
                _ConexionDoble(54321, "ESTABLISHED", 4242)]

    def Process(self, pid):                                  # noqa: N802 (API de psutil)
        if pid not in self.NOMBRES:
            raise self.NoSuchProcess(pid)
        return _ProcesoDoble(self.NOMBRES[pid])

    def process_iter(self, _campos=None):
        return []


MOD.psutil = _PsutilPuertosDoble()

reply = _handle("qué programa está usando el puerto 5678").get("reply", "")
check("5678" in reply, f"la respuesta no repite el puerto preguntado: {reply!r}")
check("node" in reply.lower(), f"no dice QUÉ programa escucha en el puerto: {reply!r}")
check("4242" in reply, f"no dice el PID del proceso que escucha: {reply!r}")

reply = _handle("qué hay en el puerto 8177").get("reply", "")
check("nexus" in reply.lower() and "700" in reply,
      f"«qué hay en el puerto 8177» no da el proceso real: {reply!r}")

# UN PUERTO SIN NADIE SE DICE TAL CUAL. Es justo donde el planificador se
# inventaba una respuesta: aquí no se aproxima ni se ofrece otra cosa.
reply = _handle("qué programa está usando el puerto 9999").get("reply", "")
low = reply.lower()
check("9999" in reply and ("nadie" in low or "no escucha" in low or "ninguno" in low
                           or "libre" in low),
      f"un puerto sin nadie escuchando no se dice tal cual: {reply!r}")
check(not any(n.split(".")[0] in low for n in _PsutilPuertosDoble.NOMBRES.values()),
      f"un puerto vacío devuelve el proceso de OTRO puerto: {reply!r}")

reply = _handle("qué puertos tengo abiertos").get("reply", "")
for esperado in ("5678", "8177", "5432", "node", "nexus", "postgres"):
    check(esperado in reply.lower(),
          f"la lista de puertos en escucha no trae «{esperado}»: {reply!r}")
check("54321" not in reply,
      f"la lista mete un puerto ESTABLISHED, que no es un puerto en escucha: {reply!r}")
check("137" in reply,
      f"una escucha sin PID desaparece de la lista en vez de decirse: {reply!r}")

MOD.psutil = _psutil_real
MOD.os.system = _os_system_real

# ------------------------------------------------- 6d) opening apps: never execute model text as a command
print("== 6d) app launch: safe names, fixed aliases and honest verification ==")
from unittest.mock import patch  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from backend.core.infraestructura import app_index  # noqa: E402

launches = []
resolved = {"harmless": r"C:\Tools\harmless.EXE", "harmless.exe": r"C:\Tools\harmless.EXE",
            "calc": r"C:\Tools\calc", "calc.exe": r"C:\Windows\calc.exe",
            "notepad": r"C:\Tools\notepad", "notepad.exe": r"C:\Windows\notepad.exe",
            "chrome.exe": None,
            "notes.cmd": r"C:\Tools\notes.cmd", "notes.bat": r"C:\Tools\notes.bat",
            "notes.ps1": r"C:\Tools\notes.ps1"}


def _fake_popen(argv, **kwargs):
    launches.append(("popen", argv, kwargs))


def _fake_startfile(target):
    launches.append(("startfile", target))


def _fake_system(cmd):
    launches.append(("system", cmd))


def _fake_which(name):
    launches.append(("which", name))
    return resolved.get(name)


def _fake_find(name):
    launches.append(("find", name))
    return ("Notepad", r"C:\Apps\notepad.exe") if name.lower() == "notepad" else None


_CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
_chrome_registry_value = [_CHROME_PATH]
_CHROME_KEY = (r"SOFTWARE\Microsoft\Windows\CurrentVersion"
               r"\App Paths\chrome.exe")


class _FakeRegistryKey:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _fake_open_key(hive, key):
    launches.append(("regkey", hive, key))
    if hive != "HKLM" or key != _CHROME_KEY:
        raise FileNotFoundError(key)
    return _FakeRegistryKey()


def _fake_query_value(_key, value):
    assert value is None
    return _chrome_registry_value[0], 1


_fake_winreg = SimpleNamespace(HKEY_LOCAL_MACHINE="HKLM", HKEY_CURRENT_USER="HKCU",
                               OpenKey=_fake_open_key, QueryValueEx=_fake_query_value)


verification = ["yes", ""]


async def _fake_verify(_before, _hint, wait=1.8):
    return tuple(verification)


def _open_app_named(name):
    # Model-supplied names can reach the handler without the voice router.
    class _Match:
        def group(self, key):
            assert key == "app"
            return name

    return asyncio.run(MOD.handle("open_app", "abre " + name, _Match(), CTX))


with (patch.object(MOD.sys, "platform", "win32"),
      patch.object(MOD.os, "system", _fake_system),
      patch.object(MOD.os, "startfile", _fake_startfile, create=True),
      patch.object(MOD.subprocess, "Popen", _fake_popen),
      patch.object(app_index, "get_index", lambda: {"Notepad": "target"}),
      patch.object(app_index, "find_app", _fake_find),
      patch.object(app_index, "launch", lambda target: launches.append(("indexed", target))),
      patch.object(MOD, "_match_steam_game", lambda _name: (None, None)),
      patch.object(MOD, "_steam_appid_by_name", lambda _name: None),
      patch.object(MOD, "_proc_names", lambda: set()),
      patch.object(MOD, "_verify_started", _fake_verify),
      patch("shutil.which", _fake_which),
      patch.dict(sys.modules, {"winreg": _fake_winreg}),
      patch.object(MOD.os.path, "isfile", lambda p: p == _CHROME_PATH),
      # These launch paths are Windows-only; keep the checks meaningful on other hosts.
      patch.object(MOD.sys, "platform", "win32"),
      patch.object(MOD.os.path, "isabs",
                   lambda p, _isabs=os.path.isabs: _isabs(p) or p[1:3] == ":\\"),
      patch.dict(os.environ, {"LOCALAPPDATA": os.environ.get("LOCALAPPDATA")
                              or "C:\\Users\\test\\AppData\\Local"}),
      patch.object(MOD.webbrowser, "open", lambda url: launches.append(("web", url)))):
    # Rejection precedes web aliases, fuzzy index matching and Steam lookup.
    for name in ("harmless & calc", "harmless | calc", "harmless > output",
                 "harmless < input", "harmless\ncalc", "harmless /silent",
                 "harmless --flag", "notepad & calc", "steam | calc",
                 "whatsapp web & calc", "discord & calc", "harmless\\calc",
                 "harmless & calc!", "harm!less", "calc! & harmless",
                 "harmless\n", "harmless\r  "):
        launches.clear()
        result = _open_app_named(name)
        check(not launches, f"unsafe app name {name!r} reached a resolver/launcher: {launches}")
        check("no" in result.get("reply", "").lower(),
              f"unsafe app name {name!r} was not refused: {result}")

    for name in ("!", "?!", " .?!  "):
        launches.clear()
        result = _open_app_named(name)
        check(not launches and "no" in result["reply"].lower(),
              f"empty normalized app name reached a resolver: {name!r}, {launches}, {result}")

    for name in ("harmless!", "harmless?!", "harmless.?!  "):
        launches.clear()
        result = _open_app_named(name)
        check(("popen", [resolved["harmless"]], {"shell": False}) in launches
              and "abierto" in result["reply"],
              f"sentence-final punctuation broke PATH app launch: {name!r}, {launches}, {result}")

    launches.clear()
    result = _open_app_named("calculadora!")
    check(("popen", [resolved["calc.exe"]], {"shell": False}) in launches
          and "abierto" in result["reply"],
          f"voice alias with exclamation was not launched safely: {launches}, {result}")

    launches.clear()
    result = _open_app_named("notas")
    check(("which", "notepad.exe") in launches and
          ("popen", [resolved["notepad.exe"]], {"shell": False}) in launches and
          "abierto" in result["reply"],
          f"fixed notes alias used shadowing extensionless tool: {launches}, {result}")

    launches.clear()
    result = _open_app_named("navegador")
    check(("which", "chrome.exe") in launches and
          ("popen", [_CHROME_PATH], {"shell": False}) in launches and
          ("regkey", "HKLM", _CHROME_KEY) in launches and
          "abierto" in result["reply"],
          f"fixed Chrome alias failed App Paths fallback: {launches}, {result}")
    launches.clear()
    _open_app_named("chrome")
    check(("popen", [_CHROME_PATH], {"shell": False}) in launches,
          f"fixed Chrome name did not use App Paths: {launches}")
    _chrome_registry_value[0] = _CHROME_PATH + " --flag"
    launches.clear()
    result = _open_app_named("navegador")
    check(not any(x[0] in ("popen", "startfile", "system") for x in launches)
          and "no encuentro" in result["reply"].lower(),
          f"registry target with arguments was launched: {launches}, {result}")
    _chrome_registry_value[0] = _CHROME_PATH

    launches.clear()
    result = _open_app_named("harmless")
    check(("popen", [resolved["harmless"]], {"shell": False}) in launches,
          f"exact PATH executable did not launch with a shell-free argv: {launches}")
    check(("which", "harmless") in launches and "abierto" in result["reply"]
          and not any(x[0] == "regkey" for x in launches),
          f"exact PATH launch was not resolved/verified: {launches}, {result}")

    launches.clear()
    _open_app_named("harmless.exe")
    check(("popen", [resolved["harmless.exe"]], {"shell": False}) in launches,
          "explicit .exe basename did not use the resolved executable")
    for state, detail, fragment in (("no", "", "no encuentro"),
                                    ("other", "launcher.exe", "no estoy seguro"),
                                    ("unknown", "", "abriendo")):
        verification[:] = [state, detail]
        result = _open_app_named("harmless")
        check(fragment in result["reply"].lower(),
              f"launch verification {state} was reported incorrectly: {result}")
    verification[:] = ["yes", ""]
    launches.clear()
    result = _open_app_named("missing_executable")
    check(not any(x[0] in ("popen", "startfile", "system") for x in launches)
          and "no encuentro" in result["reply"].lower(),
          f"unresolved executable reported success or launched: {launches}, {result}")
    with patch.object(MOD.subprocess, "Popen", side_effect=OSError("denied")):
        result = _open_app_named("harmless")
        check("no he podido" in result["reply"].lower() and "denied" in result["reply"],
              f"Popen failure was reported as success: {result}")

    for name in ("notes.cmd", "notes.bat", "notes.ps1"):
        launches.clear()
        result = _open_app_named(name)
        check(not any(x[0] in ("popen", "startfile", "system") for x in launches),
              f"script wrapper {name} was launched: {launches}")
        check("no" in result["reply"].lower(), f"script wrapper {name} was not refused")

    launches.clear()
    result = _open_app_named("notepad!")
    check(("indexed", r"C:\Apps\notepad.exe") in launches and "abierto" in result["reply"],
          f"sentence-final punctuation broke indexed app launch: {launches}, {result}")
    launches.clear()
    result = _open_app_named("notepad")
    check(("indexed", r"C:\Apps\notepad.exe") in launches and "abierto" in result["reply"],
          f"indexed app launch changed: {launches}, {result}")
    launches.clear()
    _open_app_named("whatsapp web")
    check(launches == [("web", "https://web.whatsapp.com")],
          f"fixed web alias changed: {launches}")
    for name, uri in (("spotify", "spotify:"), ("steam", "steam://open/main"),
                      ("epic", "com.epicgames.launcher://"), ("whatsapp", "whatsapp:")):
        launches.clear()
        _open_app_named(name)
        check([x for x in launches if x[0] != "find"] == [("startfile", uri)],
              f"fixed URI alias {name} did not use shell-free startfile: {launches}")
    launches.clear()
    _open_app_named("discord")
    check([x for x in launches if x[0] != "find"] ==
          [("popen", [os.path.join(os.environ.get("LOCALAPPDATA", ""),
                      "Discord", "Update.exe"), "--processStart", "Discord.exe"],
            {"shell": False})], f"Discord updater argv changed: {launches}")

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
