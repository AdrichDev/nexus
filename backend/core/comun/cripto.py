"""
nexus — cifrado de los secretos que se guardan en disco (Windows / DPAPI).

Hallazgo SEC-09 de la auditoría del 30/07/2026 (roadmap P2-6, tarea T13):
`config/secrets.json` se escribía como JSON PLANO. Cualquier proceso del
usuario, cualquier copia de seguridad del perfil y cualquier `git add -A` que se
saliera del `.gitignore` leía las API keys enteras. `CLAUDE.md` decía que
estaban «cifradas», y era mentira.

QUÉ HACE ESTE MÓDULO, Y SOLO ESTO
---------------------------------
Cifrar y descifrar UN valor de texto con DPAPI (`crypt32.dll`) a través de
`ctypes`. No conoce el almacén, no lo lee, no lo escribe: de eso se encarga
`comun/config.py`. No hay dependencia nueva de pip y no se usa `keyring` ni
`pywin32` — son ruedas que hay que instalar, actualizar y empaquetar dentro del
`.exe`, y DPAPI ya está en Windows desde 2000.

LA FORMA DE LA LLAMADA (lo que de verdad se ejecuta)
---------------------------------------------------
    CryptProtectData(&entrada, L"nexus", &entropia, NULL, NULL,
                     CRYPTPROTECT_UI_FORBIDDEN, &salida)
    CryptUnprotectData(&entrada, NULL, &entropia, NULL, NULL,
                       CRYPTPROTECT_UI_FORBIDDEN, &salida)
    LocalFree(salida.pbData)

`CRYPTPROTECT_UI_FORBIDDEN` (0x01) es obligatorio aquí: sin él, si el perfil
del usuario no tiene cargada su clave maestra, Windows puede sacar un cuadro de
diálogo pidiendo una contraseña — y nexus arranca como servicio, sin ventana y
sin nadie que lo pulse. Con el flag, la llamada FALLA y lo dice; nunca se queda
esperando a una persona.

NO se usa `CRYPTPROTECT_LOCAL_MACHINE` (0x04). Con ese flag la clave la protege
la MÁQUINA, así que cualquier usuario de ese PC descifra el archivo. Lo que se
quiere es justo lo contrario: usuario + máquina.

A QUÉ ESTÁ ATADO UN BLOB (y qué pasa si mueves el archivo)
---------------------------------------------------------
DPAPI deriva la clave de la CUENTA DE WINDOWS que llama. Un `dpapi:v1:…` escrito
por `NEXUS\adrian` solo lo abre `NEXUS\adrian` EN ESE EQUIPO. En concreto:

  * Restauras una copia de `config/` en OTRO PC → no se descifra nada.
  * Restauras la copia en el MISMO PC pero con OTRA cuenta de Windows (o después
    de reinstalar el sistema, que cambia el perfil) → tampoco.
  * Cambias la contraseña de Windows con el mismo perfil → SÍ funciona. DPAPI va
    atado al perfil (SID y clave maestra), no a la contraseña.
  * Un malware que corra COMO ESE USUARIO → descifra el archivo, exactamente
    igual que el malware podía leer el JSON plano. Esto no es un sandbox contra
    el propio usuario: es no dejar la clave escrita. El riesgo residual que
    queda está escrito en `audit-reports/09-remediation-roadmap.md`.

En los tres primeros casos nexus NO devuelve una clave vacía en silencio:
`config.py` avisa en castellano, deja el blob intacto y sigue funcionando. El
operador vuelve a pegar la clave en ⚙ → Claves API desde la cuenta correcta.

EL PARÁMETRO `ENTROPIA` NO ES UN MAC
------------------------------------
DPAPI mezcla la entropía opcional en la derivación de la clave, así que un blob
cifrado por otro programa (o por nexus con otra entropía) no descifra aquí: da
error. Sirve para SEPARAR USOS, no para demostrar integridad. No es un MAC
porque no hay ninguna clave compartida con la que verificar nada: si alguien
reescribe el archivo, el que se entera es DPAPI (autentica el criptograma con su
propia clave maestra y falla al descifrar), no nosotros. Y NO se guarda ningún
hash del texto en claro: con valores de baja entropía como una contraseña de
Postgres, un hash en el mismo archivo permitiría probar candidatos sin conexión.

QUÉ NO SE CIFRA AQUÍ (a propósito)
----------------------------------
  * `config/google_token.json` y `config/spotify_token.json`: los escribe la
    librería de Google (`creds.to_json()`) y el cliente de Spotify. Cifrarlos
    obliga a interceptar su lectura y su escritura, o a reautorizar. Sigue
    pendiente y está escrito como hueco conocido en `CLAUDE.md`.
  * `config/google_credentials.json`: es el cliente OAuth que el operador
    DESCARGA de Google y pega tal cual. No lo escribe nexus.
  * `config/settings.json`: no lleva secretos (SEC-12 y `as_dict()` lo
    impiden). Si alguna vez llevara una clave, `as_dict()` ya no la devuelve,
    pero en disco seguiría en claro: el sitio de las claves es `secrets.json`.

Con `estado_del_almacen()` este módulo también sabe qué archivos de
credenciales del operador siguen en claro, para que
`scripts/revisar_antes_de_subir.py --proteger-backups` lo cuente. De esos
archivos solo mira el nombre, el tamaño y la fecha; del almacén, además, CUENTA
los valores cifrados y en claro (nunca los devuelve ni los imprime). Es el
informe del hueco, no su arreglo.
"""
from __future__ import annotations

import base64
import ctypes
import datetime as dt
import json
import re
import sys
from pathlib import Path

# El valor en disco de un secreto cifrado es una CADENA ETIQUETADA dentro del
# mismo JSON: `"dpapi:v1:<base64>"`. Tres propiedades que se buscaban a propósito:
#   1. El archivo sigue siendo JSON legible con `cat` (nombres de las claves y
#      nada más), así que un `secrets.json` viejo con valores en claro se sigue
#      leyendo y se puede migrar.
#   2. `git`, un escáner de secretos o un `grep` no ven una clave usable.
#   3. La etiqueta dice con qué se cifró. Un `dpapi:v2:` del futuro NO se
#      reinterpreta como v1: se deja intacto y se avisa (ver config.py).
MARCA = "dpapi:"
PREFIJO = "dpapi:v1:"

# Entropía fija: separa los blobs de secrets.json de cualquier otro uso de DPAPI
# en el mismo usuario. NO es un secreto y NO es un MAC (ver el docstring).
ENTROPIA = b"nexus/secrets.json/dpapi-v1"

# Sin esto, un perfil sin clave maestra cargada puede abrir un cuadro de diálogo
# y nexus se queda esperando a que alguien lo pulse. Falla y lo dice.
CRYPTPROTECT_UI_FORBIDDEN = 0x01


class CriptoError(RuntimeError):
    """No se pudo cifrar o descifrar. Nunca se silencia: quien llama avisa."""


class _BLOB(ctypes.Structure):
    """`DATA_BLOB` de `winsta.h`. DWORD + puntero, tal cual los declara Windows:
    en 64 bits el puntero va alineado a 8, y eso lo pone ctypes solo."""
    _fields_ = [("cbData", ctypes.c_uint32),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


_libs: tuple | None = None


def _cargar():
    """(crypt32, kernel32) con sus firmas, o (None, None) si no se puede.

    Se cachea el resultado BUENO. El fallo NO se cachea: en Windows, un error de
    carga al principio (por ejemplo, dentro de un servicio sin perfil) no debe
    condenar al proceso entero para siempre. Se intenta otra vez la próxima vez.
    """
    global _libs
    if _libs is not None:
        return _libs
    if sys.platform != "win32":
        return (None, None)
    try:
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        crypt32.CryptProtectData.restype = ctypes.c_int
        crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_BLOB),      # pDataIn
            ctypes.c_wchar_p,           # szDataDescr (opcional, informativo)
            ctypes.POINTER(_BLOB),      # pOptionalEntropy
            ctypes.c_void_p,            # pvReserved (debe ser NULL)
            ctypes.c_void_p,            # pPromptStruct (NULL = sin interfaz)
            ctypes.c_uint32,            # dwFlags
            ctypes.POINTER(_BLOB),      # pDataOut
        ]
        crypt32.CryptUnprotectData.restype = ctypes.c_int
        crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_BLOB),      # pDataIn
            ctypes.c_void_p,            # ppszDataDescr (salida opcional: NULL)
            ctypes.POINTER(_BLOB),      # pOptionalEntropy
            ctypes.c_void_p,            # pvReserved (NULL)
            ctypes.c_void_p,            # pPromptStruct (NULL)
            ctypes.c_uint32,            # dwFlags
            ctypes.POINTER(_BLOB),      # pDataOut
        ]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        _libs = (crypt32, kernel32)
        return _libs
    except Exception:                                          # noqa: BLE001
        return (None, None)


def _crypt32():
    return _cargar()[0]


def disponible() -> bool:
    """¿Se puede cifrar en este equipo ahora mismo?

    Se consulta en CADA llamada, sin cachear la respuesta, por dos razones: el
    proceso puede empezar sin perfil y tenerlo después, y las pruebas tienen que
    poder doblar la plataforma (`sys.platform`) para comprobar el camino de
    Linux. En Linux/Docker/CI devuelve False y `config.py` se queda con el JSON
    plano de siempre: el contenedor de CI es Linux y nexus tiene que funcionar
    ahí, no solo en el PC del operador.
    """
    if sys.platform != "win32":
        return False
    return _crypt32() is not None


def es_de_dpapi(valor) -> bool:
    """¿Es un valor que dice estar cifrado con DPAPI (de cualquier versión)?"""
    return isinstance(valor, str) and valor.startswith(MARCA)


def es_cifrado(valor) -> bool:
    """¿Es un valor cifrado con el formato EXACTO que entiende esta versión?"""
    return isinstance(valor, str) and valor.startswith(PREFIJO)


# --------------------------------------------------------------------- helpers
def _a_blob(datos: bytes):
    """(BLOB, búfer). El búfer se devuelve aparte para que NO lo recoja el GC
    mientras Windows lo está leyendo: si solo se devolviera el BLOB, el puntero
    apuntaría a memoria liberada y el fallo saldría más tarde y en otro sitio."""
    buf = ctypes.create_string_buffer(datos, max(len(datos), 1))
    return (_BLOB(len(datos), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf)


def _de_blob(blob: _BLOB) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


def _liberar(blob: _BLOB) -> None:
    """Windows entrega `pDataOut` con LocalAlloc: lo libera quien llama.
    Es la única fuga de memoria posible aquí y no puede tumbar la operación."""
    if not blob.pbData:
        return
    try:
        kernel32 = _cargar()[1]
        if kernel32 is not None:
            kernel32.LocalFree(ctypes.cast(blob.pbData, ctypes.c_void_p))
    except Exception:                                          # noqa: BLE001
        pass


# --------------------------------------------------------------------- API
def cifrar(texto: str) -> str:
    """`"texto"` → `"dpapi:v1:<base64>"`. Lanza CriptoError si no se puede."""
    if not isinstance(texto, str):
        raise CriptoError("solo se cifra texto")
    lib = _crypt32()
    if lib is None:
        raise CriptoError("DPAPI no está disponible en este equipo")
    datos = texto.encode("utf-8")
    entrada, _b1 = _a_blob(datos)
    entropia, _b2 = _a_blob(ENTROPIA)
    salida = _BLOB()
    ok = lib.CryptProtectData(ctypes.byref(entrada), "nexus",
                              ctypes.byref(entropia), None, None,
                              CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(salida))
    if not ok:
        err = ctypes.get_last_error()
        _liberar(salida)
        raise CriptoError(f"DPAPI no pudo cifrar (error {err})")
    try:
        return PREFIJO + base64.b64encode(_de_blob(salida)).decode("ascii")
    finally:
        _liberar(salida)


def descifrar(marca: str) -> str:
    """`"dpapi:v1:<base64>"` → el texto. Lanza CriptoError si no se puede.

    Base64 ESTÁNDAR (no urlsafe) a propósito: su alfabeto no incluye `-` ni `_`,
    así que dentro de un blob no puede aparecer un `sk-…` que un escáner de
    secretos confunda con una clave. Y por eso el escáner
    (scripts/revisar_antes_de_subir.py) puede neutralizar por la FORMA —etiqueta +
    tramo largo de este alfabeto, cerrado ahí mismo— en vez de por la etiqueta a
    secas: con «empieza por dpapi:» se tragaba también un secreto en crudo
    pegado detrás (advisory del verificador sobre 562c777)."""
    if not es_cifrado(marca):
        if es_de_dpapi(marca):
            raise CriptoError("está cifrado con una versión de DPAPI que esta "
                              "versión de nexus no conoce")
        raise CriptoError("ese valor no está cifrado")
    lib = _crypt32()
    if lib is None:
        raise CriptoError("DPAPI no está disponible en este equipo")
    try:
        blob = base64.b64decode(marca[len(PREFIJO):], validate=True)
    except Exception:                                          # noqa: BLE001
        raise CriptoError("el valor cifrado está corrupto (base64 ilegible)")
    entrada, _b1 = _a_blob(blob)
    entropia, _b2 = _a_blob(ENTROPIA)
    salida = _BLOB()
    ok = lib.CryptUnprotectData(ctypes.byref(entrada), None, ctypes.byref(entropia),
                                None, None, CRYPTPROTECT_UI_FORBIDDEN,
                                ctypes.byref(salida))
    if not ok:
        err = ctypes.get_last_error()
        _liberar(salida)
        raise CriptoError(
            f"DPAPI no pudo descifrarlo (error {err}): se cifró con otra máquina "
            "u otra cuenta de Windows, o el archivo se ha tocado")
    try:
        return _de_blob(salida).decode("utf-8")
    finally:
        _liberar(salida)


# ------------------------------------------------- informe del hueco que queda
# Qué archivos de `config/` llevan credenciales y qué se hace con cada uno. El
# CONSEJO vive aquí, en un solo sitio, para que el comando de mantenimiento y
# cualquier otro lector digan lo mismo.
#
# Ojo a lo que NO está en la lista: `settings.json` (no lleva secretos: lo
# impiden SEC-12 y `as_dict()`) y `docker-compose.yml` (lleva la contraseña de
# Postgres que genera nexus; está en `.gitignore` y en la lista de vetados de
# `permissions.py`).
_CONOCIDOS = (
    ("secrets.json",
     "el almacén de claves de nexus",
     "Con DPAPI se cifra valor a valor. Si aquí quedan valores en claro, esta "
     "copia de nexus no ha podido cifrarlos (Linux, o DPAPI no disponible): "
     "ábrelo en el PC del operador con nexus arrancado y se migra solo."),
    ("secrets.json.bak",
     "copia de seguridad del almacén, EN CLARO",
     "nexus ya no escribe esta copia (T13: el archivo cifrado ES la copia). "
     "Está ahí porque la escribió una versión anterior. Bórrala cuando tengas "
     "una copia de seguridad de config/ hecha: «del config\\secrets.json.bak». "
     "nexus no la borra por su cuenta — es un archivo suyo."),
    ("google_token.json",
     "token OAuth de Google (gmail, calendar, tasks, drive)",
     "Lo escribe la librería de Google con creds.to_json(), así que sigue en "
     "claro. Hueco conocido de SEC-09: cerrarlo obliga a interceptar la lectura "
     "y la escritura de la librería o a pedir una reautorización. Mientras "
     "tanto: no lo copies fuera del PC y ten el perfil de Windows protegido."),
    ("google_credentials.json",
     "cliente OAuth de Google (client id + secret)",
     "Es el JSON que se DESCARGA de Google Cloud y se pega en config/. Sigue en "
     "claro: es del operador y nexus no lo reescribe. Los dos valores también se "
     "pueden pegar en ⚙ → Claves API, que sí se cifra."),
    ("spotify_token.json",
     "token OAuth de Spotify (refresh_token)",
     "Lo escribe backend/core/infraestructura/spotify.py con write_text(): sigue "
     "en claro. Hueco conocido de SEC-09, igual que el de Google."),
)

# Cualquier OTRO archivo de la carpeta con este nombre se nombra en el informe
# (sin abrirlo): copias que nadie previó, tipo `google_credentials.OLD.json`.
_PISTA_CREDENCIAL = re.compile(
    r"(?i)(secret|token|credential|credencial|contrase|password|api[_\-]?key)")


def estado_del_almacen(config_dir) -> dict:
    """Informe de SOLO LECTURA de las credenciales de `config_dir`.

    No descifra nada, no escribe nada y NUNCA devuelve un valor: solo nombres,
    tamaños, fechas, el consejo de qué hacer y —para `secrets.json`— cuántos
    valores están cifrados y cuántos en claro.

    `config_dir` se pasa a mano (no se importa `config`) porque importar `config`
    CONSTRUYE el `Settings` y dispara la migración: un informe no puede tener
    como efecto secundario reescribir el almacén que está informando."""
    carpeta = Path(config_dir)
    archivos = []
    for nombre, que_es, consejo in _CONOCIDOS:
        ruta = carpeta / nombre
        fila = {"archivo": nombre, "que_es": que_es, "consejo": consejo,
                "existe": ruta.is_file(), "bytes": 0, "modificado": ""}
        if fila["existe"]:
            try:
                st = ruta.stat()
                fila["bytes"] = st.st_size
                fila["modificado"] = dt.datetime.fromtimestamp(
                    st.st_mtime).strftime("%Y-%m-%d %H:%M")
            except OSError:
                pass
        archivos.append(fila)

    # Y lo que NO está en la lista pero TIENE PINTA de credencial: una copia
    # «google_credentials.OLD.json», un «secrets (2).json»… Mirar por nombre
    # exacto es lo que evita confundir settings.json con un secreto, pero también
    # es lo que deja invisible lo que nadie previó. Este segundo barrido mira
    # SOLO nombres, tamaños y fechas: nunca abre el contenido.
    conocidos = {nombre for nombre, _q, _c in _CONOCIDOS}
    otros = []
    try:
        for ruta in sorted(carpeta.iterdir()):
            if not ruta.is_file() or ruta.name in conocidos:
                continue
            if not _PISTA_CREDENCIAL.search(ruta.name):
                continue
            fila = {"archivo": ruta.name, "bytes": 0, "modificado": ""}
            try:
                st = ruta.stat()
                fila["bytes"] = st.st_size
                fila["modificado"] = dt.datetime.fromtimestamp(
                    st.st_mtime).strftime("%Y-%m-%d %H:%M")
            except OSError:
                pass
            otros.append(fila)
    except OSError:
        pass

    cuenta = {"total": 0, "cifrados": 0, "en_claro": 0, "otros": 0, "legible": False}
    ruta = carpeta / "secrets.json"
    if ruta.is_file():
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
            if isinstance(datos, dict):
                cuenta["legible"] = True
                for valor in datos.values():
                    cuenta["total"] += 1
                    if es_cifrado(valor):
                        cuenta["cifrados"] += 1
                    elif isinstance(valor, str):
                        cuenta["en_claro"] += 1
                    else:
                        cuenta["otros"] += 1
        except Exception:                                      # noqa: BLE001
            cuenta["legible"] = False
    return {"carpeta": str(carpeta), "archivos": archivos,
            "otros": otros, "secretos": cuenta}
