"""
nexus — Permisos estilo sandbox (se eligen en la instalación y en ⚙).

* perm_hardware  → ¿puede leer CPU/RAM/placa/discos/temperaturas del equipo?
* perm_files     → alcance del acceso a archivos:
      'sandbox'  : SOLO su propia carpeta (data/sandbox junto a la instalación)
      'carpetas' : solo las carpetas de la lista perm_folders (si la lista está
                   vacía: Documentos, Escritorio y Descargas del perfil).
                   ES EL VALOR POR DEFECTO desde SEC-04 / roadmap P1-6.
      'todo'     : todo el equipo (lo elige el operador a mano en ⚙ → Permisos)

Las skills de archivos/memoria pasan cada ruta por path_allowed() antes de
tocar nada, y el informe de hardware se corta si perm_hardware está apagado.

DENYLIST FIJA (SEC-04 / P1-6, auditoría del 30/07/2026)
------------------------------------------------------
Además del modo hay un conjunto de rutas que se NIEGAN SIEMPRE, también en modo
«todo»: material de credenciales. La razón es el hallazgo entero: con el defecto
«todo», cualquier canal comprometido —un flujo de n8n con el token, el móvil
vinculado, una prompt injection que llegue a un canal de confianza— dejaba de
ser «el asistente puede leer mis archivos» y pasaba a ser «cualquiera puede
robar mis credenciales»: `config/secrets.json` tiene las API keys, los
`*token*.json` los OAuth de Google/Spotify en claro, `~/.ssh` las claves del
servidor y el navegador las sesiones ya abiertas. Un documento del operador
nunca entra en esta lista: solo entran credenciales y material de claves.

Lo que esta denylist NO hace: proteger Credential Manager ni el proceso LSASS a
nivel de sistema operativo. Eso pide DPAPI y permisos de proceso, no un filtro
de rutas; aquí solo se cierra el camino de nexus (una ruta pedida por la skill,
el planificador o la ingesta). Queda anotado como límite conocido.

Se aplica en UN SOLO sitio —`_credenciales()`, llamada desde `path_allowed()`—
para que ninguna skill pueda saltársela con su propia lista.
"""
from __future__ import annotations

import os
from fnmatch import fnmatch
from pathlib import Path

from .config import (CONFIG_DIR, DATA_DIR, ROOT, carpetas_permiso_por_defecto,
                     settings)

SANDBOX_DIR = DATA_DIR / "sandbox"

MODOS = ("sandbox", "carpetas", "todo")
# Si el valor guardado no es ninguno de los tres (una errata, un settings.json
# viejo), se cae al modo seguro: un valor ilegible NO puede abrir el disco.
MODO_POR_DEFECTO = "carpetas"

# ---- denylist: material de credenciales, aplicada también en modo «todo» ----
# Nombres de archivo. Se comparan en minúsculas porque en Windows/HFS/APFS el
# nombre no distingue mayúsculas: «.SSH/ID_RSA» es el mismo archivo que «.ssh/id_rsa».
_DENY_NOMBRES = {
    # bases de datos de acceso del navegador (sesiones y contraseñas guardadas)
    "login data",          # Chrome, Edge, Brave, Opera…
    "logins.json",         # Firefox
    "key4.db",             # Firefox: almacén de claves
    "key3.db",             # Firefox antiguo
}
_DENY_SUFIJOS = {".key", ".pem", ".p12"}
# Dentro de CONFIG_DIR. Los nombrados uno a uno son los que usa nexus hoy; los
# comodines cubren los que añada cualquier integración futura sin que nadie
# tenga que acordarse de venir a esta lista.
_DENY_CONFIG_NOMBRES = {"secrets.json", "google_token.json",
                        "google_credentials.json", "spotify_token.json"}
_DENY_CONFIG_PATRONES = ("*token*.json", "*credential*", "*credencial*")
_ENV_RAIZ = ROOT / ".env"              # el .env del repositorio (raíz, no uno de un subproyecto)


def hardware_allowed() -> bool:
    return bool(settings.get("perm_hardware", True))


HW_DENIED = ("No tengo permiso para leer el hardware de este equipo. "
             "Actívalo en ⚙ → Permisos si quieres que lo vea.")


def files_mode() -> str:
    m = str(settings.get("perm_files", MODO_POR_DEFECTO) or "").strip().lower()
    return m if m in MODOS else MODO_POR_DEFECTO


# ---------------------------- denylist de credenciales ---------------------
def _hogar() -> Path:
    """Perfil del usuario AHORA (no cacheado: las pruebas usan uno de mentira)."""
    return Path(os.environ.get("USERPROFILE", "").strip() or Path.home())


_CACHE_CARPETAS: dict = {}


def _carpetas_credenciales() -> tuple[Path, ...]:
    """Carpetas que son almacén de credenciales del sistema operativo."""
    h = _hogar()
    appdata = Path(os.environ.get("APPDATA", "").strip()
                   or (h / "AppData" / "Roaming"))
    clave = (str(h), str(appdata))
    hit = _CACHE_CARPETAS.get(clave)
    if hit is not None:
        return hit
    out = []
    for d in (h / ".ssh", h / ".aws", h / ".gnupg",
              appdata / "Microsoft" / "Credentials"):
        try:
            out.append(d.resolve())          # por si el perfil lleva junction/symlink
        except Exception:                    # noqa: BLE001
            out.append(d)
    _CACHE_CARPETAS.clear()
    _CACHE_CARPETAS[clave] = tuple(out)
    return tuple(out)


def _dentro(rp: Path, root) -> bool:
    """¿`rp` está dentro de `root`? Compara sin distinguir mayúsculas: en Windows
    el sistema de archivos tampoco las distingue, así que «.SSH\\id_rsa» tiene
    que caer igual que «.ssh/id_rsa» (si no, la denylist se esquiva cambiando
    una letra)."""
    try:
        a = os.path.normcase(os.path.abspath(str(rp)))
        b = os.path.normcase(os.path.abspath(str(root)))
    except Exception:                        # noqa: BLE001
        return False
    if a == b:
        return True
    return a.startswith(b if b.endswith(os.sep) else b + os.sep)


def _misma_ruta(a, b) -> bool:
    """¿Las dos rutas SON la misma? (sin distinguir mayúsculas en Windows)."""
    try:
        return (os.path.normcase(os.path.abspath(str(a)))
                == os.path.normcase(os.path.abspath(str(b))))
    except Exception:                        # noqa: BLE001
        return False


def denied(p) -> bool:
    """¿Esta ruta es material de credenciales? Se niega SIEMPRE, también en «todo».

    Nunca mira si el archivo existe (no hace stat sobre la ruta pedida): así la
    negativa no revela qué hay y qué no hay en el equipo.
    """
    try:
        rp = Path(p).expanduser().resolve()
    except Exception:                        # noqa: BLE001
        return True                          # sin poder resolverlo no hay comprobación posible
    nombre = rp.name.casefold()
    if rp.suffix.casefold() in _DENY_SUFIJOS:
        return True
    if nombre in _DENY_NOMBRES:
        return True
    try:
        if _misma_ruta(rp, _ENV_RAIZ):      # .env de la raíz del repositorio
            return True
    except Exception:                                # noqa: BLE001
        pass
    if _dentro(rp, CONFIG_DIR) and (nombre in _DENY_CONFIG_NOMBRES
                                    or any(fnmatch(nombre, pat) for pat in _DENY_CONFIG_PATRONES)):
        return True
    for fijo in ("telegram_owner.txt", "telegram_link_code.txt"):
        if _dentro(rp, DATA_DIR) and nombre == fijo:
            return True
    for carpeta in _carpetas_credenciales():
        if _dentro(rp, carpeta):
            return True
    return False


# ------------------------------- rutas permitidas --------------------------
def carpetas_permitidas() -> list[Path]:
    """Carpetas del modo «carpetas»: las de ⚙ o, si la lista está vacía, las del perfil.

    Las del perfil se CREAN si faltan, y solo aquí (al usarlas): un operador con
    el perfil recién creado no tiene por qué haber abierto nunca «Descargas», y
    negarse a trabajar por eso sería una tontería. No se crea nada mientras el
    modo no sea «carpetas».
    """
    lista: list[Path] = []
    for raw in settings.get("perm_folders", []) or []:
        try:
            txt = str(raw).strip()
            if txt:
                lista.append(Path(txt).expanduser().resolve())
        except Exception:                    # noqa: BLE001
            continue
    if lista:
        return lista
    for txt in carpetas_permiso_por_defecto():
        p = Path(txt).expanduser()
        try:
            p.mkdir(parents=True, exist_ok=True)
            p = p.resolve()
        except Exception:                    # noqa: BLE001  (disco lleno, permisos…)
            pass
        lista.append(p)
    return lista


def _allowed_roots() -> list[Path]:
    roots = [SANDBOX_DIR.resolve()]
    if files_mode() == "carpetas":
        roots.extend(carpetas_permitidas())
    return roots


def path_allowed(p) -> bool:
    """¿Puede nexus leer/escribir en esta ruta con los permisos actuales?"""
    try:
        rp = Path(p).expanduser().resolve()
    except Exception:                        # noqa: BLE001
        return False
    # PRIMERO la denylist: es la única regla que vale en los tres modos.
    if denied(rp):
        return False
    if files_mode() == "todo":
        return True
    for root in _allowed_roots():
        if _dentro(rp, root):
            return True
    return False


def deny_msg(p) -> str:
    if denied(p):
        # Honesta y accionable: dice QUÉ es y por qué no se puede activar. No
        # confirma si el archivo existe (no se ha mirado).
        return (f"No puedo tocar «{p}»: es material de credenciales (claves, tokens "
                "o contraseñas guardadas) y eso queda fuera de mi alcance SIEMPRE, "
                "también con el permiso de archivos en «todo». No se habilita en "
                "⚙ → Permisos: si necesitas ese contenido, haz una copia tú y "
                "déjala en una carpeta permitida.")
    mode = files_mode()
    if mode == "sandbox":
        SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
        return (f"No tengo permiso para tocar «{p}»: estoy en modo SANDBOX y solo "
                f"puedo trabajar dentro de {SANDBOX_DIR}. Cambia el alcance en ⚙ → Permisos.")
    return (f"No tengo permiso para tocar «{p}»: solo puedo trabajar en las carpetas "
            "autorizadas. Añádela en ⚙ → Permisos → Carpetas permitidas.")
