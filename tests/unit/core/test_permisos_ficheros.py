# -*- coding: utf-8 -*-
"""PERMISOS DE FICHEROS SEGUROS POR DEFECTO — SEC-04 y SEC-12 (roadmap P1-6, task T7).

Lo que se prueba, y por qué:

  1. El DEFECTO ya no es `perm_files="todo"`. Sin `settings.json` el modo es
     «carpetas», y una ruta fuera de Documentos/Escritorio/Descargas se deniega
     con un mensaje accionable (⚙ → Permisos).
  2. Documentos, Escritorio y Descargas del perfil se permiten (y se crean al
     usarlas si faltan) sin migrar ningún `settings.json`.
  3. La DENYLIST FIJA se aplica TAMBIÉN en modo «todo»: credenciales y material
     de claves, nunca documentos del operador. Incluye `..` y mayúsculas, que
     son las dos formas obvias de intentar esquivarla.
  4. «carpetas» y «sandbox» siguen conteniendo por `resolve()` (regresión).
  5. La skill de archivos (read/summarize) y la de memoria (learn_doc) se niegan
     a leer una credencial y NO abren el archivo: se espía el lector real.
  6. SEC-12: `POST /api/config` con claves que controlan una guarda se rechaza
     con 403 desde fuera del equipo, aunque se traiga el token del QR, y no
     cambia nada; lo demás sigue funcionando por el token. `GET /api/config`
     sigue diciendo el modo.

TODO va EN PROCESO: la parte HTTP usa `httpx.ASGITransport` (NO ejecuta
`lifespan`: ni uvicorn, ni puertos, ni micrófono, ni Telegram). La configuración,
los datos y el PERFIL se apuntan a carpetas de usar y tirar antes de importar el
backend, así que no se lee ni se escribe nada del operador: ni su
`config/settings.json`, ni su `config/secrets.json`, ni su `~/.ssh`.

Ejecutar:  .venv\\Scripts\\python.exe tests\\unit\\core\\test_permisos_ficheros.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                              # noqa: BLE001
    pass

# ANTES de importar backend: ni la configuración ni el perfil del operador.
_CFG = Path(tempfile.mkdtemp(prefix="nexus_perm_cfg_"))
_DATA = Path(tempfile.mkdtemp(prefix="nexus_perm_data_"))
_HOME = Path(tempfile.mkdtemp(prefix="nexus_perm_home_"))
_OTRO = Path(tempfile.mkdtemp(prefix="nexus_perm_otro_"))       # «fuera» del perfil
_APPDATA = _HOME / "AppData" / "Roaming"
_LOCALAPPDATA = _HOME / "AppData" / "Local"
os.environ["NEXUS_CONFIG_DIR"] = str(_CFG)
os.environ["NEXUS_DATA_DIR"] = str(_DATA)
os.environ["USERPROFILE"] = str(_HOME)
os.environ["HOME"] = str(_HOME)
os.environ["APPDATA"] = str(_APPDATA)
os.environ["LOCALAPPDATA"] = str(_LOCALAPPDATA)
os.environ.pop("OneDrive", None)
os.environ.pop("OneDriveConsumer", None)

import httpx                                                     # noqa: E402

from backend.core.comun import permissions                       # noqa: E402
from backend.core.comun.config import (DATA_DIR, ROOT as REPO,   # noqa: E402
                                       settings)
from backend.core.infraestructura import files_io                # noqa: E402
from backend.core.aplicacion import skills_loader as sl          # noqa: E402
import backend.app as servidor                                   # noqa: E402

_fail: list[str] = []
_pass = 0


def check(cond, msg: str) -> bool:
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  ✖", msg)
    return bool(cond)


class _Config:
    """Cambia claves de configuración EN MEMORIA (nunca escribe settings.json).

    Se toca `settings._json` a propósito: así ni la lista de carpetas ni el modo
    acaban en el `settings.json` de la carpeta de usar y tirar, y cada sección
    sabe exactamente qué configuración estaba viendo.
    """

    def __init__(self, **vals):
        self.vals = vals

    def __enter__(self):
        self.previo = dict(settings._json)
        settings._json.update(self.vals)
        return self

    def __exit__(self, *_exc):
        settings._json.clear()
        settings._json.update(self.previo)
        return False


class _Entorno:
    """Cambia variables de entorno y las devuelve pase lo que pase (perfil falso)."""

    def __init__(self, **vals):
        self.vals = vals

    def __enter__(self):
        self.previo = {k: os.environ.get(k) for k in self.vals}
        os.environ.update(self.vals)
        return self

    def __exit__(self, *_exc):
        for k, v in self.previo.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False


class _Doble:
    """Contexto que cambia un atributo y lo devuelve pase lo que pase."""

    def __init__(self, obj, nombre, valor):
        self.obj, self.nombre, self.valor, self.previo = obj, nombre, valor, None

    def __enter__(self):
        self.previo = getattr(self.obj, self.nombre)
        setattr(self.obj, self.nombre, self.valor)
        return self.valor

    def __exit__(self, *_exc):
        setattr(self.obj, self.nombre, self.previo)
        return False


class _Espia:
    """Apunta las llamadas y contesta algo inocuo (no lee ni escribe nada)."""

    def __init__(self, respuesta=None):
        self.llamadas = []
        self.respuesta = respuesta if respuesta is not None else {
            "ok": True, "texto": "NO DEBÍA LEERSE", "meta": {}}

    def __call__(self, *a, **kw):
        self.llamadas.append((a, kw))
        return self.respuesta


async def _resumen_falso(_texto, _prompt):
    """Doble del resumen con IA: si llegara aquí, el archivo se leyó."""
    return "resumen de prueba"


DOCS = _HOME / "Documents"
DESK = _HOME / "Desktop"
DOWN = _HOME / "Downloads"
SECRETO = _CFG / "secrets.json"

# ---------------------------------------------------------------- 1) el defecto
print("== 1) sin settings.json el defecto es «carpetas», no «todo» ==")
check(not (_CFG / "settings.json").exists(),
      "la carpeta de configuración de la prueba debería estar vacía al empezar")
check("perm_files" not in settings._json,
      "no debe haber ningún perm_files guardado en esta prueba")
check(settings.get("perm_files") == "carpetas",
      f"el defecto de perm_files debe ser «carpetas», es {settings.get('perm_files')!r}")
check(permissions.files_mode() == "carpetas",
      f"files_mode() debe decir «carpetas», dice {permissions.files_mode()!r}")
fuera = _OTRO / "nota.txt"
check(permissions.path_allowed(fuera) is False,
      f"con el modo por defecto, {fuera} (fuera del perfil) debe DENEGARSE")
if os.name == "nt":
    check(permissions.path_allowed(Path("C:/Windows/win.ini")) is False,
          "con el modo por defecto, C:\\Windows\\win.ini debe DENEGARSE (prueba de la auditoría)")

# ------------------------------------- 2) las carpetas del perfil sí se permiten
print("== 2) Documentos/Escritorio/Descargas del perfil se permiten ==")
DOCS.mkdir(parents=True, exist_ok=True)
carta = DOCS / "carta.txt"
carta.write_text("documento del operador", encoding="utf-8")
check(permissions.path_allowed(carta) is True,
      f"{carta} está en Documentos y debe permitirse")
check(permissions.path_allowed(DESK / "nota.txt") is True,
      "un archivo del Escritorio del perfil debe permitirse")
check(permissions.path_allowed(DOWN / "paquete.zip") is True,
      "un archivo de Descargas del perfil debe permitirse")
check(DESK.is_dir() and DOWN.is_dir(),
      "Escritorio y Descargas deben crearse al usarlos (perfil recién creado)")

# la prueba de que se crean AL USARLAS, con un perfil que nadie ha tocado
_HOME2 = Path(tempfile.mkdtemp(prefix="nexus_perm_home2_"))
with _Config(perm_files="sandbox"), _Entorno(USERPROFILE=str(_HOME2), HOME=str(_HOME2)):
    permissions.path_allowed(_HOME2 / "Documents" / "x.txt")      # denegado en sandbox
    check(not (_HOME2 / "Documents").exists(),
          "en modo «sandbox» no se crea ninguna carpeta del perfil")
with _Config(perm_files="carpetas", perm_folders=[]), _Entorno(
        USERPROFILE=str(_HOME2), HOME=str(_HOME2)):
    check(not (_HOME2 / "Documents").exists(),
          "las carpetas del perfil no se crean hasta que se usan")
    check(permissions.path_allowed(_HOME2 / "Documents" / "x.txt") is True,
          "el Documentos de un perfil recién creado debe permitirse")
    check((_HOME2 / "Documents").is_dir(),
          "al usarla, la carpeta del perfil que faltaba se crea")
check(permissions.path_allowed(_HOME / "AppData" / "Local" / "x.txt") is False,
      "otra carpeta del perfil NO debe permitirse: solo las tres sembradas")
aviso = permissions.deny_msg(fuera)
check("⚙ → Permisos" in aviso,
      f"la negativa debe decir dónde se arregla (⚙ → Permisos): {aviso!r}")

# ---------------------- 3) lista propia del operador (⚙ → Carpetas permitidas)
print("== 3) la lista de ⚙ → Permisos manda cuando tiene carpetas ==")
_OTRO.mkdir(parents=True, exist_ok=True)
with _Config(perm_files="carpetas", perm_folders=[str(_OTRO)]):
    check(permissions.path_allowed(_OTRO / "informe.md") is True,
          "una carpeta añadida en ⚙ → Permisos debe permitirse")
    check(permissions.path_allowed(carta) is False,
          "si el operador elige sus carpetas, Documentos deja de estar permitido")

# ----------------------------------- 4) «todo»: documentos sí, credenciales no
print("== 4) en modo «todo» la denylist sigue vetando credenciales ==")
CASOS_DENEGADOS = [
    ("config/secrets.json", _CFG / "secrets.json"),
    ("config/google_token.json", _CFG / "google_token.json"),
    ("config/google_credentials.json", _CFG / "google_credentials.json"),
    ("config/spotify_token.json", _CFG / "spotify_token.json"),
    ("config/*token*.json (nombre nuevo)", _CFG / "otra_integracion_token.json"),
    ("config/*credential* (nombre nuevo)", _CFG / "salesforce_credentials.json"),
    ("config/*credencial* (nombre nuevo)", _CFG / "clave_credencial.json"),
    (".env de la raíz del repositorio", REPO / ".env"),
    ("data/telegram_owner.txt", DATA_DIR / "telegram_owner.txt"),
    ("data/telegram_link_code.txt", DATA_DIR / "telegram_link_code.txt"),
    ("~/.ssh/id_rsa", _HOME / ".ssh" / "id_rsa"),
    ("~/.ssh en MAYÚSCULAS", _HOME / ".SSH" / "ID_RSA"),
    ("~/.aws/credentials", _HOME / ".aws" / "credentials"),
    ("~/.gnupg", _HOME / ".gnupg" / "pubring.kbx"),
    ("%APPDATA%/Microsoft/Credentials",
     _APPDATA / "Microsoft" / "Credentials" / "DFBE70A7E5CC02345678"),
    ("Chrome Login Data",
     _LOCALAPPDATA / "Google" / "Chrome" / "User Data" / "Default" / "Login Data"),
    ("Edge Login Data",
     _LOCALAPPDATA / "Microsoft" / "Edge" / "User Data" / "Default" / "Login Data"),
    ("Firefox logins.json",
     _APPDATA / "Mozilla" / "Firefox" / "Profiles" / "abc.default" / "logins.json"),
    ("Firefox key4.db",
     _APPDATA / "Mozilla" / "Firefox" / "Profiles" / "abc.default" / "key4.db"),
    ("*.key", _HOME / "proyectos" / "servidor.key"),
    ("*.pem", _HOME / "proyectos" / "certificado.pem"),
    ("*.p12", _HOME / "proyectos" / "identidad.p12"),
]
documento_suelto = _OTRO / "documento_corriente.txt"
with _Config(perm_files="todo"):
    check(permissions.files_mode() == "todo", "el modo de esta sección debe ser «todo»")
    check(permissions.path_allowed(documento_suelto) is True,
          "en «todo», un documento corriente fuera del perfil debe permitirse")
    check(permissions.path_allowed(_OTRO / ".env") is True,
          "un .env que NO es el de la raíz del repositorio no es credencial de nexus")
    for etiqueta, ruta in CASOS_DENEGADOS:
        check(permissions.path_allowed(ruta) is False,
              f"en «todo» debe DENEGARSE {etiqueta} ({ruta})")

# la negativa de una credencial: honesta, accionable y sin delatar si existe
SECRETO.write_text("{}", encoding="utf-8")          # en la config de usar y tirar
msg_existe = permissions.deny_msg(SECRETO)
msg_no_existe = permissions.deny_msg(_CFG / "no_existe_jamas.json")
check("credenciales" in msg_existe,
      f"la negativa debe explicar que es material de credenciales: {msg_existe!r}")
check("⚙ → Permisos" in msg_existe,
      f"la negativa debe ser accionable (⚙ → Permisos): {msg_existe!r}")
check(msg_existe.replace(str(SECRETO), "X") != msg_no_existe.replace(
          str(_CFG / "no_existe_jamas.json"), "X"),
      "las dos rutas son distintas: el mensaje debe nombrar la ruta pedida")
msg_inexistente = permissions.deny_msg(_CFG / "otro_token.json")
check("No puedo tocar" in msg_inexistente and "No existe" not in msg_inexistente,
      f"la negativa no debe confesar si el archivo existe: {msg_inexistente!r}")

# --------------------------------------------- 5) `..` no esquiva la denylist
print("== 5) «..» tampoco esquiva la denylist ni el alcance ==")
with _Config(perm_files="todo"):
    for etiqueta, ruta in (
        ("config/secrets.json por subcarpeta",
         _CFG / "sub" / ".." / "secrets.json"),
        ("~/.ssh/id_rsa por Documents",
         _HOME / "Documents" / ".." / ".ssh" / "id_rsa"),
        ("Chrome Login Data por Default/..",
         _LOCALAPPDATA / "Google" / "Chrome" / "User Data" / "Default" / ".."
         / "Default" / "Login Data"),
    ):
        check(permissions.path_allowed(ruta) is False,
              f"en «todo», «..» no debe abrir {etiqueta}")
with _Config(perm_files="carpetas", perm_folders=[str(DOCS)]):
    check(permissions.path_allowed(DOCS / "sub" / "nota.txt") is True,
          "una subcarpeta de una carpeta permitida debe permitirse")
    check(permissions.path_allowed(DOCS / ".." / "nota.txt") is False,
          "salir de la carpeta permitida con «..» debe denegarse")

# ------------------------------ 6) «carpetas» y «sandbox» siguen conteniendo
print("== 6) «sandbox» y «carpetas» siguen conteniendo por resolve() ==")
SANDBOX = permissions.SANDBOX_DIR
with _Config(perm_files="sandbox"):
    check(permissions.path_allowed(SANDBOX / "nota.txt") is True,
          "en «sandbox», un archivo de data/sandbox debe permitirse")
    check(permissions.path_allowed(carta) is False,
          "en «sandbox», un documento de Documentos debe denegarse")
    check(permissions.path_allowed(SANDBOX / ".." / "telegram_owner.txt") is False,
          "en «sandbox», salir con «..» a data/ debe denegarse")
    check(permissions.path_allowed(SANDBOX / ".." / "otra_cosa.txt") is False,
          "en «sandbox», una ruta hermana de la carpeta debe denegarse")
    check("SANDBOX" in permissions.deny_msg(carta),
          "la negativa en sandbox debe explicar el modo")
with _Config(perm_files="carpetas", perm_folders=[]):
    check(permissions.files_mode() == "carpetas",
          "con la lista vacía el modo debe seguir siendo «carpetas»")
    check(permissions.path_allowed(carta) is True,
          "con perm_folders vacío vuelven las carpetas del perfil")

# enlaces simbólicos: en Windows suelen exigir modo desarrollador/administrador
print("== 7) enlaces simbólicos (si el equipo los permite) ==")
_ORIGEN = _HOME / ".ssh" / "id_rsa"
_ORIGEN.parent.mkdir(parents=True, exist_ok=True)
_ORIGEN.write_text("clave de mentira", encoding="utf-8")
_enlace = _OTRO / "atajo-a-clave"
try:
    os.symlink(str(_ORIGEN), str(_enlace))
except (OSError, NotImplementedError, AttributeError) as exc:   # noqa: BLE001
    print(f"  (no se comprueba: este equipo no deja crear enlaces simbólicos: "
          f"{type(exc).__name__})")
else:
    with _Config(perm_files="todo"):
        check(permissions.path_allowed(_enlace) is False,
              "un enlace simbólico a ~/.ssh/id_rsa debe denegarse (se resuelve antes)")

# ------------------------- 8) la skill de archivos se niega y NO abre el archivo
print("== 8) la skill de archivos se niega y no lee el archivo ==")
REG = sl.load_skills()
FSK = REG.get("files")
check(FSK is not None and getattr(FSK, "module", None) is not None,
      "la skill files debe cargar para poder probarla")


def _handler(frase, canal="pc", extra=None):
    """Enruta con el enrutador REAL y ejecuta el handler de la skill que toque."""
    r = sl.route(frase)
    assert r, f"«{frase}» no llega a ninguna skill"
    skill, intent, match = r
    ctx = {"channel": canal, "settings": None, **(extra or {})}
    res = asyncio.run(skill.module.handle(intent, frase, match, ctx))
    return skill.folder, intent, res


for modo in ("carpetas", "todo"):
    with _Config(perm_files=modo):
        for frase in (f"lee el archivo {SECRETO}",
                      f"resume el documento {SECRETO}",
                      f"lee el archivo {_ORIGEN}"):
            espia = _Espia()
            with _Doble(files_io, "read_any", espia), \
                    _Doble(FSK.module, "_ai_summary", _resumen_falso):
                carpeta, intent, res = _handler(frase)
            reply = str(res.get("reply", ""))
            check(carpeta == "files", f"«{frase}» debe ir a la skill files, fue a {carpeta}")
            check("No puedo tocar" in reply,
                  f"[{modo}] «{frase}» debe contestar la negativa honesta, contestó {reply[:90]!r}")
            check(espia.llamadas == [],
                  f"[{modo}] «{frase}» NO debe abrir el archivo: se abrió {espia.llamadas!r}")

# y la de memoria tampoco lo ingiere (recibe sus dobles por ctx, no del módulo)
class _GrafoEspia:
    """Doble del grafo de notas: cuenta lo que le habrían pedido escribir."""

    def __init__(self):
        self.llamadas = []

    def write_note(self, *a, **kw):
        self.llamadas.append((a, kw))
        return {"ok": True}

    def append_daily(self, *a, **kw):
        self.llamadas.append((a, kw))
        return {"ok": True}


class _PgEspia:
    online = False

    def remember(self, *a, **kw):
        raise AssertionError("no debe recordarse una credencial")


_grafo = _GrafoEspia()
with _Config(perm_files="todo"):
    carpeta, intent, res = _handler(f"aprende el documento {SECRETO}",
                                    extra={"pg": _PgEspia(), "graph": _grafo})
reply = str(res.get("reply", ""))
check(carpeta == "memory_graph",
      f"«aprende el documento …» debe ir a memory_graph, fue a {carpeta}")
check("No puedo tocar" in reply,
      f"memory_graph debe contestar la negativa honesta, contestó {reply[:90]!r}")
check(_grafo.llamadas == [],
      f"memory_graph NO debe escribir la credencial en el grafo: {_grafo.llamadas!r}")

# ---------------------------------------------------- 9) SEC-12: solo local
print("== 9) SEC-12: los permisos solo se cambian desde este equipo ==")
TOK = "token-de-prueba-del-qr"
HUD = "127.0.0.1:8177"
settings.set_secret("link_token", TOK)
APP = servidor.app


def _cliente(peer: str) -> httpx.AsyncClient:
    transporte = httpx.ASGITransport(app=APP, client=(peer, 4321))
    return httpx.AsyncClient(transport=transporte, base_url=f"http://{HUD}")


def _post(payload: dict, peer: str = "127.0.0.1", token: str = ""):
    async def _hacer():
        cab = {"x-nexus-token": token} if token else {}
        async with _cliente(peer) as c:
            return await c.post("/api/config", json=payload, headers=cab)
    return asyncio.run(_hacer())


def _get(peer: str = "127.0.0.1"):
    async def _hacer():
        async with _cliente(peer) as c:
            return await c.get("/api/config")
    return asyncio.run(_hacer())


with _Config(perm_files="carpetas", perm_folders=[]):
    # GET local sigue contando el modo (lo necesita el HUD)
    r = _get()
    check(r.status_code == 200, f"GET /api/config local debe dar 200, dio {r.status_code}")
    cuerpo = r.json() if r.status_code == 200 else {}
    check(cuerpo.get("perm_files") == "carpetas",
          f"GET /api/config debe exponer el modo, expone {cuerpo.get('perm_files')!r}")
    registradas = {str(x) for x in (cuerpo.get("perm_folders") or [])}
    check(str(DOCS) in registradas,
          f"GET /api/config debe enseñar las carpetas efectivas: {cuerpo.get('perm_folders')!r}")

    # 1) desde el equipo: sí (es la ventana local)
    r = _post({"perm_files": "todo"})
    check(r.status_code == 200, f"POST local de perm_files debe dar 200, dio {r.status_code}")
    check(settings.get("perm_files") == "todo",
          "el POST local sí debe aplicar perm_files")

# 2) desde fuera con token válido: 403 y NADA cambia
with _Config(perm_files="carpetas", perm_folders=[]):
    _antes_json = ((_CFG / "settings.json").read_text(encoding="utf-8")
                   if (_CFG / "settings.json").exists() else "")
    r = _post({"perm_files": "todo"}, peer="192.168.1.77", token=TOK)
    check(r.status_code == 403,
          f"POST remoto de perm_files debe dar 403 (token válido incluido), dio {r.status_code}")
    error = str((r.json() or {}).get("error", "")) if r.status_code == 403 else ""
    check("solo se cambian desde este equipo" in error,
          f"el 403 debe explicarse en español y decir por qué: {error!r}")
    check("perm_files" in error,
          f"el 403 debe nombrar la clave rechazada: {error!r}")
    check(settings.get("perm_files") == "carpetas",
          f"el 403 NO debe cambiar perm_files, quedó {settings.get('perm_files')!r}")
    _despues = ((_CFG / "settings.json").read_text(encoding="utf-8")
                if (_CFG / "settings.json").exists() else "")
    check(_despues == _antes_json,
          "el 403 remoto no debe escribir NADA en settings.json")

    # 3) las demás claves sensibles, también por el token
    for clave, valor in (("perm_folders", [str(_OTRO)]),
                         ("n8n_webhook_url", "http://10.0.0.9:5678/webhook/x"),
                         ("n8n_base_url", "http://10.0.0.9:5678"),
                         ("permitir_fallback_nube", True),
                         ("perm_hardware", False),
                         ("llm_local", False),
                         ("homeassistant_url", "http://10.0.0.9:8123"),
                         ("engram_autoinstall", False),
                         # T17: la segunda copia de TODO data/ cae en la misma clase
                         # (dirigirla a otra carpeta es una exfiltración local).
                         ("backup_destino_extra", "C:\\Users\\Public\\copia")):
        previo = settings.get(clave)
        r = _post({clave: valor}, peer="192.168.1.77", token=TOK)
        check(r.status_code == 403,
              f"POST remoto de {clave} debe dar 403, dio {r.status_code}")
        check(settings.get(clave) == previo,
              f"el 403 de {clave} no debe cambiar el valor ({previo!r} → {settings.get(clave)!r})")

    # 3b) TRINQUETE: la lista de arriba no puede quedarse atrás.
    # Si alguien añade una clave a `_CLAVES_SOLO_LOCALES` sin caso en la batería,
    # esta vuelta extra la prueba igual (con un valor de muestra) y el olvido de
    # sincronizar la lista deja de ser un agujero silencioso.
    for clave in sorted(servidor._CLAVES_SOLO_LOCALES):
        previo = settings.get(clave)
        r = _post({clave: "valor-de-prueba-desde-fuera"}, peer="192.168.1.77", token=TOK)
        check(r.status_code == 403,
              f"POST remoto de {clave} (trinquete) debe dar 403, dio {r.status_code}")
        check(settings.get(clave) == previo,
              f"el trinquete de {clave} no debe cambiar el valor")
    check(set(servidor._CLAVES_SOLO_LOCALES) <= set(
            {"perm_files", "perm_folders", "perm_hardware", "n8n_webhook_url",
             "n8n_base_url", "homeassistant_url", "permitir_fallback_nube",
             "llm_local", "engram_autoinstall", "backup_destino_extra"}),
          "hay claves nuevas en _CLAVES_SOLO_LOCALES sin motivo escrito aquí: "
          "añade su caso y su porqué")

    # 4) una petición mixta no aplica NADA (ni lo inocente)
    r = _post({"operator_name": "Intruso", "perm_files": "todo"},
              peer="192.168.1.77", token=TOK)
    check(r.status_code == 403, f"POST mixto remoto debe dar 403, dio {r.status_code}")
    check(settings.get("operator_name") != "Intruso",
          "un POST mixto rechazado NO debe aplicar operator_name")

    # 5) el resto de la configuración sigue funcionando por el token
    r = _post({"operator_name": "Ana"}, peer="192.168.1.77", token=TOK)
    check(r.status_code == 200,
          f"POST remoto de operator_name debe seguir dando 200, dio {r.status_code}")
    check(settings.get("operator_name") == "Ana",
          f"operator_name debe aplicarse desde el móvil, quedó {settings.get('operator_name')!r}")

    # 6) sin token desde fuera: 401 (lo sigue haciendo el middleware)
    r = _post({"perm_files": "todo"}, peer="192.168.1.77")
    check(r.status_code == 401,
          f"sin token, un POST remoto debe dar 401, dio {r.status_code}")

print(f"\n{'#' * 58}\nRESULTADO permisos de ficheros: {_pass} OK / {len(_fail)} fallos "
      f"({'' if not _fail else 'REVISAR'})")
sys.exit(1 if _fail else 0)
