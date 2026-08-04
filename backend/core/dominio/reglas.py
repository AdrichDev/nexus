"""
nexus — Almacen de reglas aprendidas y capa de valores declarados.

Capa: dominio. Importa SOLO `comun/config` y `comun/audit`; nada de `aplicacion`.

Aqui vive el fichero `data/reglas_aprendidas.json` (el unico que nexus escribe
por aprender) y la tabla `VALORES`, que es la lista de listas y umbrales que han
salido del codigo y por tanto pueden aprenderse.

Bloques A y B de 004: almacen, tabla de valores, contrato de estados y las
puertas 1-4 que una regla tiene que cruzar para contar como activa. Proponer,
aprobar y consultar en caliente es el bloque C: aqui todavia no hay nada que
active una regla por su cuenta.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from pathlib import Path

from ..comun import audit, config

ESQUEMA = 1

# Nada se borra: revertir o descartar es cambiar de estado, no perder la
# historia. `invalida` es donde queda aislada una regla que ya no pasa las
# puertas —una skill desinstalada, un patron editado a mano— sin arrastrar con
# ella a las que estan sanas.
ESTADOS = ("propuesta", "activa", "revertida", "descartada", "invalida")

# `enrutado` amplia el alcance de un handler que YA existe; `valor` pisa una
# clave de la tabla VALORES; `aviso` no es una regla activable: es la constancia
# de que una correccion delataba un fallo de codigo y no un hueco de enrutado.
TIPOS = ("enrutado", "valor", "aviso")

# Los ocho campos del contrato. El octavo es `patron` o `valor` segun el tipo.
CAMPOS = ("id", "tipo", "origen", "destino", "evidencia", "estado", "revision")

# Largo admitido de un patron aprendido, en caracteres.
LARGO_PATRON = (6, 200)

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
    # Puerta 1 ANTES de escribir: un objeto al que le falta un campo no es una
    # regla, y guardarlo dejaria en el fichero algo que ninguna carga posterior
    # va a poder juzgar. El almacen queda exactamente igual que estaba.
    ok, motivo, _ = _puerta_campos(regla)
    if not ok:
        raise ValueError(motivo)
    if solo_lectura():
        raise ValueError("el almacen es de un esquema mas nuevo: solo lectura")
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
_averia = None


def registrar_arbitro(fn) -> None:
    """Guarda quien decide que frase atiende quien (`brain.quien_atiende`)."""
    global _arbitro
    _arbitro = fn


def registrar_catalogo(fn) -> None:
    """Guarda quien sabe si un destino existe (`carpeta/intent` o clave de `VALORES`)."""
    global _catalogo
    _catalogo = fn


def registrar_averia(fn) -> None:
    """Guarda quien sabe si un destino falta POR AVERIA en vez de por no existir.

    Sin registrar, todo destino ausente se trata como ausencia de verdad, que es
    el comportamiento de siempre. Es opcional a proposito: quien no lo rellene
    no cambia de conducta."""
    global _averia
    _averia = fn


def destino_averiado(destino: str) -> bool:
    """¿El destino falta porque su skill esta rota AHORA MISMO?"""
    if _averia is None:
        return False
    try:
        return bool(_averia(destino))
    except Exception:                                      # noqa: BLE001
        return False


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
        # Y PASA LAS PUERTAS, aunque el fichero la de por «activa».
        #
        # Antes bastaba con que el destino existiera. Un valor escrito a mano en
        # el almacen entraba sin comprobar tipo ni rango — y una de estas claves
        # es un FRAGMENTO DE REGEX que se concatena al patron de una skill. Un
        # «estado: activa» puesto a mano no es una autorizacion: la unica
        # autorizacion son las puertas, y se vuelven a pasar aqui porque este es
        # el punto donde el valor entra de verdad en el programa.
        ok, _motivo, _intrinseco = _puerta_campos(r)
        if not ok:
            continue
        ok, _motivo, _intrinseco = _puerta_existencia(r)
        if not ok:
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


# ═══════════════════════════════════════════════════════════════════════════
#  EL CORPUS — las frases contra las que se mide si una regla le roba a alguien
# ═══════════════════════════════════════════════════════════════════════════
# No hay artefacto nuevo que mantener al dia: `installer/nexus.spec` YA empaqueta
# `skills/` entero, y las frases prometidas salen de las listas de activacion de
# los propios `SKILL.md`. El extractor que vivia en `tests/test_lo_prometido.py`
# baja aqui y el test pasa a importarlo, para que no puedan discrepar.

# Frases entrecomilladas en una vinneta que NO son ordenes: son trozos de prosa
# explicando como se resuelve algo. Se listan a mano porque distinguirlas
# automaticamente no es fiable.
_NO_SON_ORDENES = {
    "escritorio", "documentos", "descargas", "imágenes", "imagenes",
    "actualizar", "forzar update",
}

_corpus_cache: dict = {"clave": None, "pares": []}


def _skill_mds() -> list[Path]:
    try:
        return sorted(config.SKILLS_DIR.glob("*/SKILL.md"))
    except Exception:                                      # noqa: BLE001
        return []


def _clave_corpus(mds: list[Path]) -> tuple:
    """Lo BARATO de la huella: cuantos SKILL.md hay y cual es el mtime mayor.
    Se calcula sin abrir un solo fichero, y es lo que decide si hace falta
    volver a extraer las frases (que si cuesta)."""
    mayor = 0.0
    for md in mds:
        try:
            mayor = max(mayor, md.stat().st_mtime)
        except OSError:
            continue
    return (len(mds), mayor)


def corpus_prometido(con_origen: bool = False):
    """Las frases que los `SKILL.md` prometen atender.

    Por defecto, la lista de frases DISTINTAS en orden estable. Con
    `con_origen=True`, los pares `(carpeta, frase)` incluyendo las repetidas:
    una misma orden puede estar documentada en dos skills a proposito, porque
    las fronteras se explican en los dos lados."""
    mds = _skill_mds()
    clave = _clave_corpus(mds)
    if _corpus_cache["clave"] != clave:
        pares: list[tuple[str, str]] = []
        for md in mds:
            try:
                texto = md.read_text(encoding="utf-8")
            except OSError:
                continue
            for linea in texto.splitlines():
                if not re.match(r"^\s*[-*]\s*«", linea):    # solo las vinnetas
                    continue
                for f in re.findall(r"«([^»]{6,70})»", linea):
                    f = f.strip()
                    if "…" in f or "..." in f or "<" in f:  # plantillas con hueco
                        continue
                    if re.search(r"\b[A-ZÁÉÍÓÚÑ]{3,}\b", f):  # marcadores «pon CANCION»
                        continue
                    if f.lower() in _NO_SON_ORDENES:
                        continue
                    pares.append((md.parent.name, f))
        _corpus_cache["clave"] = clave
        _corpus_cache["pares"] = pares
    pares = _corpus_cache["pares"]
    if con_origen:
        return list(pares)
    vistas, unicas = set(), []
    for _carpeta, f in pares:
        if f not in vistas:
            vistas.add(f)
            unicas.append(f)
    return unicas


def corpus_regresion() -> list[dict]:
    """Las frases reales de aquella tarde y su duenno esperado, leidas de
    `config/corpus_regresion.json`.

    Viajan en el instalador porque en la maquina del usuario no hay `tests/`, y
    sin ellas la puerta de no robo mediria solo contra lo que los SKILL.md
    prometen — que es justo lo que ya se demostro insuficiente el 03/08."""
    try:
        datos = json.loads(
            (config.CONFIG_DIR / "corpus_regresion.json").read_text(encoding="utf-8"))
    except Exception:                                      # noqa: BLE001
        return []
    frases = datos.get("frases") if isinstance(datos, dict) else None
    if not isinstance(frases, list):
        return []
    return [f for f in frases if isinstance(f, dict) and str(f.get("frase") or "").strip()]


def corpus_incompleto() -> str:
    """'' si el catalogo esta ENTERO; si no, por que no lo esta.

    `corpus_regresion()` se traga cualquier fallo y devuelve lista vacia, que
    para leer esta bien pero para VALIDAR no: si solo falla esa mitad, el corpus
    total sigue teniendo las frases prometidas, la puerta de no robo se ejecuta
    igual y pasa — midiendo contra menos frases de las que cree. Eso no es una
    puerta que falla: es una puerta que se abre sola y no lo dice.

    La regla de este cambio es denegar por defecto, y un catalogo a medias es
    exactamente el caso en el que hay que denegar."""
    p = config.CONFIG_DIR / "corpus_regresion.json"
    if not p.exists():
        return "falta config/corpus_regresion.json"
    try:
        datos = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:                                 # noqa: BLE001
        return f"config/corpus_regresion.json no se puede leer ({type(e).__name__})"
    frases = datos.get("frases") if isinstance(datos, dict) else None
    if not isinstance(frases, list) or not frases:
        return "config/corpus_regresion.json no trae ninguna frase"
    if not corpus_prometido():
        return "no hay SKILL.md de los que sacar las frases que se prometen"
    return ""


def corpus_completo() -> list[str]:
    """Todo contra lo que se mide una regla candidata, sin repetir."""
    vistas, fuera = set(), []
    for f in corpus_prometido():
        if f not in vistas:
            vistas.add(f)
            fuera.append(f)
    for entrada in corpus_regresion():
        f = str(entrada.get("frase") or "").strip()
        if f and f not in vistas:
            vistas.add(f)
            fuera.append(f)
    return fuera


# ═══════════════════════════════════════════════════════════════════════════
#  LAS PUERTAS — en orden de coste, y cortando en la primera que falle
# ═══════════════════════════════════════════════════════════════════════════
# Cada puerta devuelve (ok, motivo, aislable).
#
# `aislable` distingue dos clases de fallo, y la distincion importa:
#
#   * INTRINSECO (aislable=True): la regla esta mal —le falta un campo, su
#     destino ya no existe, su patron es una red de arrastre—. Se marca
#     `invalida` en el fichero con el motivo, para que se vea sin ejecutar nada.
#   * DEL ENTORNO (aislable=False): no se puede juzgar ahora mismo —nadie ha
#     registrado el arbitro, el catalogo de frases no esta instalado—. La regla
#     NO se activa, pero TAMPOCO se marca invalida: condenarla por que quien la
#     juzga no ha llegado todavia seria destruir una regla buena por un problema
#     de arranque.
#
# En las dos clases el resultado para la activacion es el mismo: no entra.

def _vacio(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip()
    if isinstance(v, (list, tuple, set, dict)):
        return len(v) == 0
    return False


def _umbral(clave: str, reserva):
    """Un numero del bloque `aprendizaje` de `config/umbrales.json`, o su reserva
    del codigo. El fichero puede no existir: en una instalacion limpia no viaja."""
    try:
        datos = json.loads((config.CONFIG_DIR / "umbrales.json").read_text(encoding="utf-8"))
        v = datos["aprendizaje"][clave]
    except Exception:                                      # noqa: BLE001
        return reserva
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else reserva


def _puerta_campos(r) -> tuple[bool, str, bool]:
    """Puerta 1. Los ocho campos, y el motivo NOMBRA el que falta: «no vale» no
    le dice nada a quien tiene que arreglarlo."""
    if not isinstance(r, dict):
        return False, "una regla es un dict", True
    for campo in CAMPOS:
        if campo not in r or _vacio(r.get(campo)):
            return False, f"falta el campo «{campo}»", True
    if r["tipo"] not in TIPOS:
        return False, f"tipo «{r['tipo']}» no admitido: solo {TIPOS}", True
    if r["estado"] not in ESTADOS:
        return False, f"estado «{r['estado']}» no admitido: solo {ESTADOS}", True
    if not isinstance(r["revision"], int) or isinstance(r["revision"], bool) or r["revision"] < 1:
        return False, "el campo «revision» tiene que ser un entero >= 1", True
    origen = r["origen"]
    if not isinstance(origen, dict):
        return False, "el campo «origen» tiene que ser un objeto", True
    if _vacio(origen.get("frase")):
        return False, "el campo «origen» no trae la frase literal del operador", True
    for hueco in ("canal", "fecha"):
        if _vacio(origen.get(hueco)):
            return False, f"el campo «origen» no trae «{hueco}»", True
    if r["tipo"] == "enrutado" and _vacio(r.get("patron")):
        return False, "falta el campo «patron», obligatorio en una regla de enrutado", True
    if r["tipo"] == "valor" and "valor" not in r:
        return False, "falta el campo «valor», obligatorio en una regla de valor", True
    return True, "", True


def _puerta_existencia(r) -> tuple[bool, str, bool]:
    """Puerta 2. El destino existe DE VERDAD en esta instalacion."""
    destino = str(r.get("destino") or "")
    if r["tipo"] == "valor":
        if destino not in VALORES:
            return (False,
                    f"la clave «{destino}» no esta declarada en la tabla VALORES: "
                    "primero hay que sacar del codigo lo que se quiere aprender", True)
        tipo, rango, _reserva = VALORES[destino]
        # EL TIPO SE MIRA EN CRUDO, ANTES DE CONVERTIR. `set("hola")` no falla:
        # devuelve cuatro letras, y una cadena colada donde se espera una lista
        # entraba como un conjunto de caracteres del tamanno justo para pasar el
        # rango. Convertir primero y preguntar despues es preguntar por el
        # resultado de la conversion, no por lo que trajo la regla.
        crudo = r["valor"]
        admitido = {set: (list, tuple, set), dict: (dict,), str: (str,),
                    int: (int,), float: (int, float)}.get(tipo, (tipo,))
        if not isinstance(crudo, admitido) or isinstance(crudo, bool):
            return (False,
                    f"el valor no es del tipo declarado ({tipo.__name__}): "
                    f"ha llegado un {type(crudo).__name__}", True)
        try:
            convertido = _normaliza(destino, tipo, crudo)
        except Exception as e:                             # noqa: BLE001
            return False, f"el valor no es del tipo declarado ({tipo.__name__}): {e}", True
        if not isinstance(convertido, tipo):
            return False, f"el valor no es del tipo declarado ({tipo.__name__})", True
        minimo, maximo = rango
        medida = len(convertido) if isinstance(convertido, (str, list, tuple, set, dict)) \
            else convertido
        if not (minimo <= medida <= maximo):
            return (False,
                    f"el valor esta fuera del rango declarado ({minimo}..{maximo}): {medida}",
                    True)
        # Y SI LO QUE SE APRENDE ES UNA REGEX, SE COMPILA AQUI.
        #
        # `system_pc.no_es_programa` no es texto cualquiera: se concatena al
        # patron de una skill. Tipo y longitud correctos no impiden que sea un
        # parentesis sin cerrar — y entonces la skill deja de compilar y se cae
        # entera al arrancar, con la regla ya escrita en disco. Un valor que
        # rompe el programa donde va a vivir no cumple el contrato aunque mida
        # lo que toca.
        if destino in _CLAVES_REGEX:
            try:
                re.compile(convertido)
            except re.error as e:
                return False, f"el fragmento de expresion regular no compila: {e}", True
            malo = _forma_peligrosa(convertido)
            if malo:
                return False, f"el fragmento de expresion regular {malo}", True
        return True, "", True
    # `enrutado`: quien sabe que destinos existen esta en `aplicacion`, asi que
    # se pregunta por el hueco. Sin rellenar contesta False, y eso es una
    # denegacion del ENTORNO: validar a ciegas es peor que no aprender.
    if _catalogo is None:
        return False, "no hay catalogo de destinos registrado: no se valida a ciegas", False
    if not existe_destino(destino):
        # AUSENTE NO ES LO MISMO QUE AVERIADO, Y LA DIFERENCIA ES PERMANENTE.
        # Marcar `invalida` escribe en disco y no se deshace solo. Si la skill
        # esta instalada pero ha reventado al cargar —un parentesis a medio
        # guardar, una dependencia que aun no esta— el destino existe y volvera:
        # invalidar la regla por eso la mata para siempre por un fallo de un
        # minuto. Se deniega igual (no se activa nada a ciegas), pero sin dejar
        # marca durable: al siguiente arranque sano se revalida y entra.
        if destino_averiado(destino):
            return (False,
                    f"la skill de «{destino}» no ha cargado en este arranque: "
                    "se deja en cuarentena hasta que vuelva, no se invalida", False)
        return False, f"el destino «{destino}» no existe en esta instalacion", True
    return True, "", True


# Un grupo que ya lleva cuantificador y encima va cuantificado: `(a+)+`, `(?:a*)*`.
# Es el retroceso exponencial de manual, y una regex aprendida corre en CADA
# mensaje: colgaria nexus entero sin dejar rastro de por que.
_ANIDADO_RX = re.compile(r"\([^()]*[*+][^()]*\)\s*[*+{]")
# Un `.` cuantificado y suelto: casa con medio catalogo. No es una forma nueva de
# decir algo, es una red de arrastre.
_PUNTO_LIBRE_RX = re.compile(r"(?<!\\)\.[*+]")


# Alternancia cuantificada: `(a|ab)+`. Es la OTRA forma clasica de retroceso
# catastrofico y no la ve `_ANIDADO_RX`, que solo busca un cuantificador dentro
# de otro. Se detecto revisando: un patron asi pasaba la puerta y luego colgaba
# el barrido contra las 289 frases.
_ALTERNANCIA_RX = re.compile(r"\((?:\?:)?[^()]*\|[^()]*\)\s*[*+]")

# Claves cuyo valor NO es texto: se concatena a un patron y tiene que compilar.
_CLAVES_REGEX = {"system_pc.no_es_programa"}


def _forma_peligrosa(patron: str) -> str:
    """'' si la forma es sana; si no, POR QUE es peligrosa.

    Se usa desde dos sitios —el patron de una regla de enrutado y el fragmento de
    una regla de valor— y por eso vive aparte: dos copias de esta lista se
    separan al primer descubrimiento nuevo, y el descubrimiento nuevo llega
    siempre por el lado que no se actualizo."""
    if _ANIDADO_RX.search(patron):
        return "lleva un cuantificador anidado: retroceso catastrofico"
    if _ALTERNANCIA_RX.search(patron):
        return "lleva una alternancia cuantificada: retroceso catastrofico"
    if _PUNTO_LIBRE_RX.search(patron):
        return "lleva un «.» cuantificado libre: casaria con casi todo"
    return ""


def _puerta_forma(r) -> tuple[bool, str, bool]:
    """Puerta 3. Solo para `enrutado`: compila, ancla y no es una red."""
    if r["tipo"] != "enrutado":
        return True, "", True
    patron = str(r.get("patron") or "")
    try:
        re.compile(patron)
    except re.error as e:
        return False, f"el patron no compila: {e}", True
    if not (patron.startswith("^") and patron.endswith("$")):
        return False, "el patron tiene que estar anclado por los dos lados (^…$)", True
    malo = _forma_peligrosa(patron)
    if malo:
        return False, f"el patron {malo}", True
    minimo, maximo = LARGO_PATRON
    if len(patron) < minimo:
        return False, f"el patron es demasiado corto ({len(patron)} < {minimo})", True
    if len(patron) > maximo:
        return False, f"el patron es demasiado largo ({len(patron)} > {maximo})", True
    return True, "", True


def barrido(regla: dict) -> dict:
    """Puerta 4, en crudo: quien atiende cada frase del corpus SIN la regla y CON
    la regla, y en que se diferencian.

    Es la misma funcion llamada dos veces, no dos funciones parecidas: por eso
    `arbitro()` recibe el conjunto de reglas como argumento en vez de leerlo de
    ningun sitio. Un barrido que parcheara un global mediria otra cosa.

    LA FORMA SE MIRA AQUI, NO SOLO EN LA PUERTA 3. Esta funcion es publica y se
    puede llamar suelta, y ejecuta el patron candidato 289 veces. Con un patron
    de retroceso catastrofico no hay presupuesto que valga: el presupuesto se
    mide DESPUES de barrer, asi que se cuelga antes de poder medirlo. Comprobar
    la forma cuesta microsegundos y es lo unico que evita ese cuelgue."""
    if str(regla.get("tipo") or "") == "enrutado":
        patron = str(regla.get("patron") or "")
        try:
            re.compile(patron)
        except re.error as e:
            return {"robadas": [], "arrastradas": [], "ms": 0.0, "frases": 0,
                    "abortado": f"el patron no compila: {e}"}
        malo = _forma_peligrosa(patron)
        if malo:
            return {"robadas": [], "arrastradas": [], "ms": 0.0, "frases": 0,
                    "abortado": f"el patron {malo}"}
    corpus = corpus_completo()
    rid = str(regla.get("id") or "")
    esperado = f"regla:{rid}"
    robadas: list[tuple[str, str, str]] = []
    arrastradas: list[str] = []
    ini = time.perf_counter()
    for frase in corpus:
        antes = arbitro(frase, reglas=())
        despues = arbitro(frase, reglas=(regla,))
        if antes == despues:
            continue
        if antes == "planificador" and despues == esperado:
            arrastradas.append(frase)
        else:
            robadas.append((frase, antes, despues))
    ms = (time.perf_counter() - ini) * 1000.0
    return {"robadas": robadas, "arrastradas": arrastradas,
            "ms": ms, "frases": len(corpus), "abortado": ""}


def _puerta_no_robo(r) -> tuple[bool, str, bool]:
    """Puerta 4. La unica red que va a tener el usuario, y la unica que cuesta
    tiempo real: por eso va la ultima."""
    if r["tipo"] == "valor":
        # UNA REGLA `valor` NO ENRUTA. No participa en la decision de quien
        # atiende una frase, asi que no hay barrido que hacer: el no robo se
        # cumple por construccion, no por comprobacion.
        return True, "", True
    if _arbitro is None:
        return False, "no hay arbitro registrado: no se puede comprobar el no robo", False
    # No basta con que el corpus NO ESTE VACIO: tiene que estar ENTERO. Si solo
    # falla la mitad de regresion, lo que queda sigue siendo una lista de frases
    # y la puerta pasaria midiendo contra menos de lo que cree.
    falta = corpus_incompleto()
    if falta:
        return (False,
                f"el catalogo de frases no esta entero ({falta}): validar asi "
                "seria hacerlo a medias y creerselo", False)
    corpus = corpus_completo()
    if not corpus:
        return (False,
                "el catalogo de frases no esta instalado o esta vacio: sin el, "
                "validar seria hacerlo a ciegas", False)
    b = barrido(r)
    # El barrido se planta si la forma es peligrosa; eso es un fallo de la regla,
    # no del entorno.
    if b.get("abortado"):
        return False, b["abortado"], True
    presupuesto = _umbral("presupuesto_ms_barrido", 1500)
    if b["ms"] > presupuesto:
        return (False,
                f"el barrido ha tardado {b['ms']:.0f} ms sobre {b['frases']} frases, "
                f"por encima del presupuesto de {presupuesto:.0f} ms", False)
    if b["robadas"]:
        frase, antes, despues = b["robadas"][0]
        return (False,
                f"roba «{frase}»: hoy la atiende {antes} y pasaria a {despues}"
                f" ({len(b['robadas'])} frases afectadas)", True)
    tope = _umbral("tope_frases_arrastradas", 2)
    propia = str((r.get("origen") or {}).get("frase") or "").strip()
    extra = [f for f in b["arrastradas"] if f != propia]
    if len(extra) > tope:
        return (False,
                f"la regla es demasiado ancha: ademas de la suya arrastra "
                f"{len(extra)} frases (tope {tope:.0f}): {extra}", True)
    if propia and arbitro(propia, reglas=()) != "planificador":
        return (False,
                f"«{propia}» ya la atiende {arbitro(propia, reglas=())}: "
                "no hay hueco que ocupar, y una regla no arregla un fallo de codigo",
                True)
    return True, "", True


_PUERTAS = (_puerta_campos, _puerta_existencia, _puerta_forma, _puerta_no_robo)


def _valida(r) -> tuple[bool, str, bool]:
    # Un `aviso` no es una regla activable: es la constancia de que una
    # correccion delataba un fallo de codigo. Taparlo con una regla es
    # exactamente lo que el duenno prohibio, asi que no cruza ninguna puerta.
    if isinstance(r, dict) and r.get("tipo") == "aviso":
        return False, "un aviso no se activa: es un fallo de codigo, no un hueco", False
    for puerta in _PUERTAS:
        ok, motivo, aislable = puerta(r)
        if not ok:
            return False, motivo, aislable
    return True, "", True


def valida(regla: dict) -> tuple[bool, str]:
    """Las puertas 1-4 en orden de coste, cortando en la primera que falle.

    La puerta 5 (la suite) NO se ejecuta desde aqui y no se marca como superada:
    en la maquina de un usuario no hay `tests/`. La lleva `aplicacion/aprendizaje`
    y se registra como `no_aplicable`."""
    ok, motivo, _aislable = _valida(regla)
    return ok, motivo


# ═══════════════════════════════════════════════════════════════════════════
#  ESTADOS Y CONJUNTO ACTIVO
# ═══════════════════════════════════════════════════════════════════════════

def solo_lectura() -> bool:
    """`True` si el almacen viene de un nexus mas nuevo.

    Un nexus viejo no adivina un formato nuevo: en vez de migrar hacia atras en
    silencio —que es exactamente como se pierden datos— se lee y no se toca, y
    NINGUNA regla se activa."""
    try:
        return int(cargar().get("esquema", ESQUEMA)) > ESQUEMA
    except Exception:                                      # noqa: BLE001
        return False


def transitar(rid: str, estado: str, motivo: str = "") -> bool:
    """Cambia el estado de una regla. Devuelve si el cambio se ha hecho.

    `revertida → activa` se RECHAZA: una regla que el duenno deshizo no puede
    revivir sola, tiene que volver a proponerse y aprobarse. Nada se borra."""
    if estado not in ESTADOS:
        return False
    if solo_lectura():
        return False
    with _lock:
        datos = _leer()
        for r in datos.get("reglas", []):
            if not isinstance(r, dict) or str(r.get("id") or "") != str(rid):
                continue
            if r.get("estado") == "revertida" and estado == "activa":
                audit.log("regla_transicion_rechazada", actor="nexus", targets=[str(rid)],
                          result="revertida->activa", error=motivo)
                return False
            r["estado"] = estado
            r["motivo"] = motivo
            if estado == "activa":
                r["activada"] = _ahora()
            config._write_json_atomic(ruta_almacen(), datos)
            _olvida_huella_sin_candado()
            audit.log("regla_transicion", actor="nexus", targets=[str(rid)],
                      interpreted=str(r.get("destino") or ""), result=estado, error=motivo)
            return True
    return False


def _ahora() -> str:
    import datetime as _dt
    return _dt.datetime.now().isoformat(timespec="seconds")


def destino_de(rid: str) -> str:
    """El `carpeta/intent` que declara una regla. `quien_atiende()` devuelve
    `regla:<id>` y no el destino, para que una regla aprendida no se confunda
    NUNCA con enrutado nativo; esto es lo que permite mirar detras del id."""
    for r in cargar().get("reglas", []):
        if isinstance(r, dict) and str(r.get("id") or "") == str(rid):
            return str(r.get("destino") or "")
    return ""


# Huella de revalidacion perezosa. Revalidar cuesta un barrido sobre ~290
# frases; hacerlo en CADA consulta seria pagarlo en cada mensaje. Se paga cuando
# algo ha cambiado: el corpus (se instalo una skill, se edito un SKILL.md) o el
# conjunto de reglas.
_huella: dict = {"corpus": None, "reglas": None, "activas": [], "barridos": 0}

# LA REENTRADA ES DE UN HILO, NO DEL PROCESO.
#
# Esto marca «ya estoy validando MAS ABAJO EN ESTA MISMA PILA», para que el
# barrido de una regla que acaba preguntando por el conjunto activo corte el
# ciclo. Siendo un global se contagiaba: con el servidor atendiendo dos
# mensajes a la vez, el hilo B veia la marca del hilo A, se creia dentro de un
# ciclo que no era suyo y contestaba «ninguna regla activa». Resultado: lo
# aprendido dejaba de aplicarse de forma intermitente y sin dejar rastro, que
# es la peor variante. Guardado por hilo, cada pila responde por la suya.
_reentrada = threading.local()


def barridos() -> int:
    """Cuantas veces se ha revalidado de verdad. Lo usa la suite: mirando el
    RESULTADO no se distingue un barrido de tres, porque sale lo mismo."""
    return int(_huella["barridos"])


def olvida_huella() -> None:
    with _lock:
        _olvida_huella_sin_candado()


def _olvida_huella_sin_candado() -> None:
    _huella["corpus"] = None
    _huella["reglas"] = None
    _huella["activas"] = []


def _huella_corpus() -> tuple:
    mds = _skill_mds()
    return _clave_corpus(mds) + (len(corpus_prometido()), len(corpus_regresion()))


def _huella_reglas(datos: dict) -> str:
    crudo = json.dumps(datos.get("reglas", []), sort_keys=True, ensure_ascii=False,
                       default=str)
    return hashlib.sha256(crudo.encode("utf-8")).hexdigest()


def activas() -> list[dict]:
    """Las reglas de enrutado que vuelven a pasar las puertas 1-4 EN ESTA CARGA.

    El `estado` del fichero no otorga autoridad: `data/reglas_aprendidas.json`
    vive en la maquina del usuario y es texto plano. Escribir «activa» dentro no
    activa nada — se revalida, y la que falla queda aislada sin tumbar a las
    sanas.

    Orden: gana la de activacion mas reciente. No se depende del orden de lectura
    del fichero ni del de insercion de un diccionario, para que dos ejecuciones
    con el mismo almacen den lo mismo."""
    if getattr(_reentrada, "activo", False):
        # Reentrada: el barrido de una regla ha acabado preguntando por el
        # conjunto activo. Contestar «ninguna» corta el ciclo por el lado seguro.
        return []
    if solo_lectura():
        return []
    datos = cargar()
    candidatas = [r for r in datos.get("reglas", [])
                  if isinstance(r, dict) and r.get("estado") == "activa"
                  and r.get("tipo") == "enrutado"]
    if not candidatas:
        # ESTADO DE FABRICA, QUE ES EL DE CASI TODO EL MUNDO CASI SIEMPRE. Sin
        # ninguna candidata no hay nada que revalidar, y calcular la huella del
        # corpus cuesta un `stat` por cada SKILL.md. Medido: 3,3 ms por llamada,
        # y `quien_atiende()` corre en CADA mensaje que llega al planificador.
        # Salir aqui no relaja ninguna puerta: cero candidatas son cero activas.
        return []
    hc, hr = _huella_corpus(), _huella_reglas(datos)
    with _lock:
        if _huella["corpus"] == hc and _huella["reglas"] == hr:
            return list(_huella["activas"])

    vivas: list[dict] = []
    aislar: list[tuple[str, str]] = []
    _reentrada.activo = True
    try:
        for r in candidatas:
            ok, motivo, aislable = _valida(r)
            if ok:
                vivas.append(r)
            elif aislable:
                aislar.append((str(r.get("id") or ""), motivo))
            else:
                audit.log("regla_sin_juzgar", actor="nexus",
                          targets=[str(r.get("id") or "")], result="no_activada",
                          error=motivo)
    finally:
        _reentrada.activo = False
        with _lock:
            _huella["barridos"] += 1

    for rid, motivo in aislar:
        transitar(rid, "invalida", motivo)

    vivas.sort(key=lambda r: (str(r.get("activada") or ""), str(r.get("id") or "")),
               reverse=True)
    # Se calcula FUERA y se publica DENTRO. `cargar()` coge `_lock` por su
    # cuenta y el cerrojo no es reentrante: calcular dentro se traba consigo
    # mismo y cuelga el proceso entero. Y publicar sin candado deja ver el
    # corpus nuevo con las activas viejas.
    hc_nueva, hr_nueva = _huella_corpus(), _huella_reglas(cargar())
    with _lock:
        _huella["corpus"] = hc_nueva
        _huella["reglas"] = hr_nueva
        _huella["activas"] = vivas
    return list(vivas)
