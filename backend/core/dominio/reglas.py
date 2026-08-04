"""
nexus — Almacen de reglas aprendidas y capa de valores declarados.

Capa: dominio. Importa SOLO `comun/config` y `comun/audit`; nada de `aplicacion`.

Aqui vive el fichero `data/reglas_aprendidas.json` (el unico que nexus escribe
por aprender) y la tabla `VALORES`, que es la lista de listas y umbrales que han
salido del codigo y por tanto pueden aprenderse.

Bloque A de 004: almacen, tabla y accesor. Ni contrato de estados, ni puertas,
ni propuestas: eso llega en los bloques B y C.
"""
from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

from ..comun import audit, config

ESQUEMA = 1

# Un candado de modulo para la lectura-modificacion-escritura entera. nexus es UN
# proceso (puerto 8177) con varios hilos: planificador, atajo de teclado y puente
# de mensajeria escriben desde hilos distintos.
_lock = threading.Lock()


# ---------------------------------------------------------------- el almacen
def ruta_almacen() -> Path:
    """Ruta del almacen. Se resuelve en cada llamada, no al importar, para que
    NEXUS_DATA_DIR apuntando a una carpeta temporal cambie de verdad el destino."""
    return config.DATA_DIR / "reglas_aprendidas.json"


def _fabrica() -> dict:
    return {"esquema": ESQUEMA, "reglas": []}


def _leer() -> dict:
    """Principal -> `.bak` -> fabrica. NUNCA lanza: un fichero corrupto degrada a
    cero reglas, no deja a nexus sin arrancar."""
    p = ruta_almacen()
    for cand in (p, p.with_name(p.name + ".bak")):
        try:
            if cand.exists():
                datos = json.loads(cand.read_text(encoding="utf-8"))
                if isinstance(datos, dict) and isinstance(datos.get("reglas"), list):
                    datos.setdefault("esquema", ESQUEMA)
                    return datos
        except Exception:                                  # noqa: BLE001
            continue
    return _fabrica()


def cargar() -> dict:
    """El almacen entero: {"esquema": int, "reglas": [...]}."""
    with _lock:
        return _leer()


def guardar(regla: dict) -> str:
    """Inserta o reemplaza una regla por su `id` y devuelve ese `id`.

    La escritura la hace `config._write_json_atomic()`: `.bak` de la version
    valida anterior, `.tmp` y `os.replace`. Es el mismo codigo que arreglo la
    truncacion de settings.json, asi que no se copia: se llama."""
    if not isinstance(regla, dict):
        raise TypeError("una regla es un dict")
    with _lock:
        datos = _leer()
        rid = str(regla.get("id") or "").strip() or f"r-{uuid.uuid4().hex[:6]}"
        nueva = dict(regla)
        nueva["id"] = rid
        datos["reglas"] = [r for r in datos.get("reglas", [])
                           if str(r.get("id") or "") != rid] + [nueva]
        datos["esquema"] = datos.get("esquema", ESQUEMA)
        config._write_json_atomic(ruta_almacen(), datos)
    audit.log("regla_guardada", actor="nexus",
              interpreted=str(nueva.get("destino") or ""),
              targets=[rid], result=str(nueva.get("estado") or ""))
    return rid


# --------------------------------------------- huecos de inversion de dependencia
# `dominio` no puede importar `aplicacion`, asi que quien sabe enrutar y quien
# sabe que destinos existen se registran desde arriba, como hace
# `comun/events.registrar_hay_trabajo()`.
#
# EL VALOR POR DEFECTO VA AL REVES QUE EN `events`: alli, sin rellenar, se
# contesta que SI hay trabajo. Aqui, sin rellenar, `existe_destino()` contesta
# `False` y el arbitro contesta "no lo se". Sin arbitro no se activa nada.
_arbitro = None
_catalogo = None


def registrar_arbitro(fn) -> None:
    """Guarda quien decide que frase atiende quien (`brain.quien_atiende`)."""
    global _arbitro
    _arbitro = fn


def registrar_catalogo(fn) -> None:
    """Guarda quien sabe si un destino existe (`carpeta/intent` o clave de `VALORES`)."""
    global _catalogo
    _catalogo = fn


def hay_arbitro() -> bool:
    return _arbitro is not None


def existe_destino(destino: str) -> bool:
    """`False` mientras nadie registre el catalogo."""
    if _catalogo is None:
        return False
    try:
        return bool(_catalogo(destino))
    except Exception:                                      # noqa: BLE001
        return False


def arbitro(frase: str, reglas=None) -> str:
    """Quien atiende esa frase. Cadena vacia = "no lo se" (nadie ha registrado
    arbitro), que no es lo mismo que "planificador"."""
    if _arbitro is None:
        return ""
    try:
        return str(_arbitro(frase) if reglas is None else _arbitro(frase, reglas=reglas))
    except Exception:                                      # noqa: BLE001
        return ""


# ------------------------------------------------- la tabla de valores declarados
# clave -> (tipo, rango, reserva).
#
# Es CODIGO, asi que viaja siempre: en una instalacion limpia, sin
# `config/umbrales.json`, cada lector sigue teniendo su valor de siempre.
#
# Una clave solo se vuelve aprendible cuando su lector pasa por `valor()`. Esta
# tabla es, literalmente, la lista de lectores migrados.
#
# `rango` acota el TAMANO: (minimo, maximo) elementos para las colecciones y
# caracteres para las cadenas.
VALORES: dict[str, tuple[type, tuple, object]] = {
    # skills/domotica/skill.py, _resolve_named_device(): palabras de estancia o
    # de tipo que por si solas NO identifican un aparato concreto.
    "domotica.room_words": (set, (5, 200), {
        "habitacion", "salon", "cocina", "cuarto", "bano", "pasillo", "entrada",
        "dormitorio", "comedor", "garaje", "jardin", "terraza", "oficina",
        "despacho", "tv", "tele", "television", "smart", "casa", "sala",
    }),
    # skills/domotica/skill.py, _probe_ports(): puerto -> etiqueta del aparato.
    # EL ORDEN ES LA PRIORIDAD del sondeo y las claves son ENTEROS; `valor()`
    # devuelve las dos cosas intactas aunque el valor venga de un JSON.
    "domotica.port_hints": (dict, (1, 200), {
        8060: "TV Roku", 8001: "TV Samsung", 8002: "TV Samsung", 55000: "TV Samsung",
        8008: "Chromecast", 8009: "Chromecast", 7000: "AirPlay",
        32400: "Servidor Plex", 8123: "Home Assistant", 1883: "IoT (MQTT)",
        9100: "Impresora", 631: "Impresora (IPP)", 554: "Cámara IP (RTSP)",
        445: "PC/servidor (SMB)", 3389: "PC Windows (escritorio remoto)",
        22: "Linux/servidor (SSH)", 62078: "iPhone/iPad", 5353: "mDNS",
        53: "Router/DNS", 8080: "Web/panel",
    }),
    # skills/system_pc/skill.py, patron «kill»: fragmento de regex (lookahead
    # negativo) con lo que NO es un programa que se pueda cerrar.
    "system_pc.no_es_programa": (str, (10, 4000), (
        r"(?!(?:"
        r"la|los|las|una|unos|unas|"                                   # artículos sueltos
        r"procesos?|aplicaci[oó]n|app|programa|"                        # ancla, ya tratada arriba
        r"pesta[ñn]as?|marcadores?|historial|navegaci[oó]n|"            # chrome
        r"tablero|tareas?|notas?|listas?|proyectos?|"                   # tasks_board / coach
        r"facturas?|presupuestos?|"                                     # billing
        r"correos?|mails?|e-?mails?|bandeja|calendario|"                # google_workspace
        r"tele|televisi[oó]n|persianas?|cortinas?|puertas?|garaje|"     # domotica
        r"luz|luces|gas|grifo|calefacci[oó]n|"                          # domotica
        r"chats?|conversaci[oó]n|hilos?|mensajes?|"                     # comms / telefono
        r"sesi[oó]n|ventanas?|pantallas?|di[aá]logos?|men[uú]s?|"       # no son programas
        r"paneles?|modal|pico|boca|ojos?|puertos?|"
        r"trato|acuerdo|caso|tema|asunto|debate|discusi[oó]n"           # metáforas
        r")\b)"
    )),
}


def _claves_a_int(crudo) -> dict:
    """dict con las claves convertidas a `int`, conservando el orden de insercion.
    En JSON las claves son cadenas y el sondeo indexa por numero de puerto."""
    return {int(k): v for k, v in dict(crudo).items()}


# Conversiones que el tipo declarado no cubre por si solo.
_NORMALIZA = {"domotica.port_hints": _claves_a_int}


def _normaliza(clave: str, tipo: type, crudo):
    """Convierte al tipo declarado. Devuelve siempre un objeto NUEVO para las
    colecciones: quien reciba el valor no puede ensuciar la reserva del codigo."""
    fn = _NORMALIZA.get(clave)
    if fn is not None:
        return fn(crudo)
    return tipo(crudo)


def _de_umbrales(clave: str):
    """El valor de `config/umbrales.json` para «bloque.clave», o `None` si no esta.
    Solo LEE: este fichero no se escribe nunca desde aqui."""
    bloque, _, sub = clave.partition(".")
    try:
        datos = json.loads((config.CONFIG_DIR / "umbrales.json").read_text(encoding="utf-8"))
    except Exception:                                      # noqa: BLE001
        return None
    if not isinstance(datos, dict):
        return None
    trozo = datos.get(bloque)
    if not isinstance(trozo, dict):
        return None
    return trozo.get(sub)


def _superposicion() -> dict:
    """clave -> valor de las reglas `valor` activas del almacen.

    Sin catalogo registrado, `existe_destino()` contesta `False` y esto sale
    vacio: una regla escrita a mano en el fichero no activa nada por si sola."""
    fuera = {}
    for r in cargar().get("reglas", []):
        if not isinstance(r, dict):
            continue
        if r.get("tipo") != "valor" or r.get("estado") != "activa":
            continue
        clave = str(r.get("destino") or "")
        if clave not in VALORES or not existe_destino(clave):
            continue
        if "valor" in r:
            fuera[clave] = r["valor"]
    return fuera


def valor(clave: str):
    """El valor vigente de una clave declarada, en tres tiempos:

        reserva de VALORES  ->  config/umbrales.json si existe  ->  superposicion activa

    Una clave desconocida LANZA. Devolver `None` en silencio convertiria una
    errata en un comportamiento distinto sin que nadie se entere."""
    if clave not in VALORES:
        raise KeyError(f"«{clave}» no esta declarada en reglas.VALORES")
    tipo, _rango, reserva = VALORES[clave]
    crudo = reserva
    del_fichero = _de_umbrales(clave)
    if del_fichero is not None:
        crudo = del_fichero
    encima = _superposicion().get(clave)
    if encima is not None:
        crudo = encima
    return _normaliza(clave, tipo, crudo)
