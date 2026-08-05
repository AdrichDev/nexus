# -*- coding: utf-8 -*-
"""Bloque A de 004: las tres listas del duenno salen del codigo, y nada cambia.

Lo que se comprueba aqui NO es «el modulo existe». Eso no prueba nada. Se
comprueba que:

  * el almacen degrada a fabrica cuando el fichero esta roto, sin lanzar;
  * sin catalogo registrado NINGUNA regla del fichero activa nada, aunque
    alguien escriba `estado: "activa"` a mano;
  * `valor()` resuelve en tres tiempos y una clave desconocida LANZA;
  * `config/umbrales.json` no se toca nunca (sha256 antes y despues);
  * los TRES lectores migrados siguen comportandose igual, comprobado sobre el
    HANDLER y no solo sobre la regex: `_resolve_named_device()`, `_probe_ports()`
    y el patron «kill» con su handler.

La trampa de `port_hints` esta en su propio caso: es un `dict[int, str]` cuyo
ORDEN es la prioridad del sondeo. En JSON las claves son cadenas. Perder el
orden o el tipo no rompe nada visible — sigue devolviendo una etiqueta, solo que
la equivocada.

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_reglas_valores.py
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("NEXUS_DATA_DIR", tempfile.mkdtemp(prefix="nexus_reglas_"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                          # noqa: BLE001
    pass

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


# Huella del fichero ANTES de importar nada del backend. Importar una skill ya
# llama a reglas.valor(), asi que una escritura que ocurriera ahi quedaria fuera
# de la ventana si la huella se tomara dentro del caso de prueba: seria una
# prueba que mira un escalon por debajo del fallo.
UMBRALES = ROOT / "config" / "umbrales.json"
SHA_AL_ARRANCAR = hashlib.sha256(UMBRALES.read_bytes()).hexdigest()

from backend.core.aplicacion import skills_loader as sl   # noqa: E402
from backend.core.dominio import reglas                    # noqa: E402

REG = sl.load_skills()
DOM = REG["domotica"].module
SPC = REG["system_pc"].module

# ═══════════════════════════════════════════════════════════════════════════
#  LO QUE HABIA ANTES DE LA MIGRACION, ESCRITO A MANO
# ═══════════════════════════════════════════════════════════════════════════
# Copiado literalmente de la revision ANTERIOR al bloque A (`e616021`):
# `skills/domotica/skill.py:1677` (_ROOM_WORDS), `:506` (_PORT_HINTS) y
# `skills/system_pc/skill.py` (_NO_ES_PROGRAMA).
#
# SE ESCRIBE A MANO Y NO SE DERIVA DE `VALORES`. Derivarlo seria comparar la
# tabla consigo misma: cambiar un valor en el codigo no pondria nada en rojo, y
# la prueba diria «todo bien» mientras el comportamiento cambia. La promesa
# entera del bloque A era «lo unico que cambia es DE DONDE se lee un valor»; sin
# esto, esa promesa no la vigila nadie.
#
# COMPROBADO EL 05/08/2026, y por eso esta escrito: quitar tres palabras del
# fragmento de `no_es_programa` («conversacion», «hilos», «mensajes») dejaba las
# 81 suites en VERDE. «cierra la conversacion» pasaba a tratarse como un
# programa que cerrar. Cambiar la etiqueta del puerto 8060 de «TV Roku» a otra
# cosa, tambien verde. Se pinchaba el ORDEN y el TIPO de las claves, que era la
# trampa declarada de A3.2, pero NINGUN valor.
ROOM_WORDS_DE_ANTES = {
    "habitacion", "salon", "cocina", "cuarto", "bano", "pasillo", "entrada",
    "dormitorio", "comedor", "garaje", "jardin", "terraza", "oficina",
    "despacho", "tv", "tele", "television", "smart", "casa", "sala",
}

# Puerto → etiqueta, EN ORDEN: el orden es la prioridad del sondeo
# (`skill.py:540`, «orden de `_port_hints()` = prioridad»).
PORT_HINTS_DE_ANTES = [
    (8060, "TV Roku"), (8001, "TV Samsung"), (8002, "TV Samsung"),
    (55000, "TV Samsung"), (8008, "Chromecast"), (8009, "Chromecast"),
    (7000, "AirPlay"), (32400, "Servidor Plex"), (8123, "Home Assistant"),
    (1883, "IoT (MQTT)"), (9100, "Impresora"), (631, "Impresora (IPP)"),
    (554, "Cámara IP (RTSP)"), (445, "PC/servidor (SMB)"),
    (3389, "PC Windows (escritorio remoto)"), (22, "Linux/servidor (SSH)"),
    (62078, "iPhone/iPad"), (5353, "mDNS"), (53, "Router/DNS"), (8080, "Web/panel"),
]

PUERTOS_EN_ORDEN = [p for p, _e in PORT_HINTS_DE_ANTES]

# Las 59 alternativas del lookahead negativo de «kill», en orden.
NO_ES_PROGRAMA_DE_ANTES = [
    "la", "los", "las", "una", "unos", "unas",
    "procesos?", "aplicaci[oó]n", "app", "programa",
    "pesta[ñn]as?", "marcadores?", "historial", "navegaci[oó]n",
    "tablero", "tareas?", "notas?", "listas?", "proyectos?",
    "facturas?", "presupuestos?",
    "correos?", "mails?", "e-?mails?", "bandeja", "calendario",
    "tele", "televisi[oó]n", "persianas?", "cortinas?", "puertas?", "garaje",
    "luz", "luces", "gas", "grifo", "calefacci[oó]n",
    "chats?", "conversaci[oó]n", "hilos?", "mensajes?",
    "sesi[oó]n", "ventanas?", "pantallas?", "di[aá]logos?", "men[uú]s?",
    "paneles?", "modal", "pico", "boca", "ojos?", "puertos?",
    "trato", "acuerdo", "caso", "tema", "asunto", "debate", "discusi[oó]n",
]


def _escribe_almacen(lista) -> None:
    """Escribe el almacen A PELO, sin pasar por `guardar()`.

    Es el camino que toma quien edita el fichero a mano, y el unico que prueba
    de verdad que la superposicion no se fia del «estado» escrito alli."""
    import json
    reglas.ruta_almacen().write_text(
        json.dumps({"esquema": reglas.ESQUEMA, "reglas": lista}, ensure_ascii=False),
        encoding="utf-8")


def _limpia_almacen() -> None:
    """Deja el almacen y los huecos como recien instalados."""
    p = reglas.ruta_almacen()
    for f in (p, p.with_name(p.name + ".bak"), p.with_name(p.name + ".tmp")):
        try:
            f.unlink()
        except Exception:                                  # noqa: BLE001
            pass
    reglas.registrar_catalogo(None)
    reglas.registrar_arbitro(None)


def _regla_valor(clave, valor, estado="activa", rid="r-prueba"):
    return {"id": rid, "esquema": reglas.ESQUEMA, "tipo": "valor", "revision": 1,
            "origen": {"frase": "orden de prueba", "canal": "pc",
                       "fecha": "2026-08-04T10:00:00", "tipo": "ordenada", "veces": 1},
            "destino": clave, "valor": valor,
            "evidencia": {"arrastradas": [], "suite": None}, "estado": estado}


# ══════════ A1.1 · el almacen degrada a fabrica y nunca lanza ══════════
def test_almacen_corrupto_degrada_a_fabrica():
    print("== A1.1) un almacen roto no deja a nexus sin arrancar ==")
    _limpia_almacen()
    check(reglas.cargar() == {"esquema": reglas.ESQUEMA, "reglas": []},
          "sin fichero, cargar() no devuelve la fabrica")

    rid = reglas.guardar(_regla_valor("domotica.room_words", ["alfa"], "propuesta"))
    check(rid == "r-prueba", f"guardar() no respeta el id que trae la regla ({rid})")
    check(len(reglas.cargar()["reglas"]) == 1, "la regla guardada no esta en el almacen")

    # Reemplazo por id: no se duplica.
    reglas.guardar(_regla_valor("domotica.room_words", ["beta"], "propuesta"))
    guardadas = reglas.cargar()["reglas"]
    check(len(guardadas) == 1, f"guardar() duplica en vez de reemplazar por id ({len(guardadas)})")
    check(guardadas[0]["valor"] == ["beta"], "guardar() no ha reemplazado el contenido")

    # La segunda escritura deja un .bak con la version anterior valida.
    bak = reglas.ruta_almacen().with_name(reglas.ruta_almacen().name + ".bak")
    check(bak.exists(), "la escritura no ha dejado respaldo .bak")

    # Fichero principal roto -> se lee el .bak, no la fabrica.
    reglas.ruta_almacen().write_text("{ esto no es json ,,,", encoding="utf-8")
    recuperado = reglas.cargar()
    check(recuperado["reglas"] and recuperado["reglas"][0]["valor"] == ["alfa"],
          f"con el principal roto no se recurre al .bak ({recuperado})")

    # Los dos rotos -> fabrica, sin excepcion.
    bak.write_text("tampoco", encoding="utf-8")
    check(reglas.cargar() == {"esquema": reglas.ESQUEMA, "reglas": []},
          "con los dos ficheros rotos no se cae a fabrica")

    # Un JSON valido pero que no es un almacen tampoco lanza.
    reglas.ruta_almacen().write_text('{"esquema": 1}', encoding="utf-8")
    check(reglas.cargar()["reglas"] == [], "un JSON sin «reglas» no degrada a fabrica")
    _limpia_almacen()


# ══════════ A1.2 · sin arbitro/catalogo no se activa nada ══════════
def test_sin_arbitro_no_activa_nada():
    print("== A1.2) sin catalogo registrado, el fichero no otorga autoridad ==")
    _limpia_almacen()
    check(reglas.existe_destino("domotica.room_words") is False,
          "existe_destino() no deniega por defecto")
    check(reglas.arbitro("apaga la tele") == "",
          "el arbitro no contesta «no lo se» cuando nadie lo ha registrado")
    check(reglas.hay_arbitro() is False, "hay_arbitro() miente sin arbitro registrado")

    # Una regla ACTIVA escrita a mano en el fichero.
    reglas.guardar(_regla_valor("domotica.room_words", ["inventada", "otra", "tercera", "cuarta", "quinta"]))
    check(reglas.valor("domotica.room_words") == reglas.VALORES["domotica.room_words"][2],
          "una regla «activa» del fichero cambia el valor SIN catalogo registrado")

    # Con catalogo, esa misma regla si manda.
    reglas.registrar_catalogo(lambda clave: clave in reglas.VALORES)
    check(reglas.valor("domotica.room_words") == {"inventada", "otra", "tercera", "cuarta", "quinta"},
          "con catalogo registrado, la regla activa no se aplica")

    # Y una regla que NO esta activa nunca manda, aunque haya catalogo.
    reglas.guardar(_regla_valor("domotica.room_words", ["inventada", "otra", "tercera", "cuarta", "quinta"], "revertida"))
    check(reglas.valor("domotica.room_words") == reglas.VALORES["domotica.room_words"][2],
          "una regla revertida sigue mandando")
    _limpia_almacen()


# ══════════ A2.2 · reserva -> umbrales.json -> superposicion ══════════
def test_valor_resuelve_en_tres_tiempos():
    print("== A2.2) valor() resuelve en tres tiempos y la clave rara LANZA ==")
    _limpia_almacen()
    reserva = reglas.VALORES["domotica.room_words"][2]
    check(reglas.valor("domotica.room_words") == reserva,
          "1er tiempo: sin fichero ni regla, no sale la reserva del codigo")

    lanza = False
    try:
        reglas.valor("clave.que.no.existe")
    except KeyError:
        lanza = True
    check(lanza, "una clave desconocida devuelve algo en silencio en vez de lanzar")

    tmp = Path(tempfile.mkdtemp(prefix="nexus_cfg_"))
    (tmp / "umbrales.json").write_text(
        json.dumps({"domotica": {"room_words": ["del", "fichero", "tres", "cuatro", "cinco"]}}), encoding="utf-8")
    cfg_real = reglas.config.CONFIG_DIR
    try:
        reglas.config.CONFIG_DIR = tmp
        check(reglas.valor("domotica.room_words") == {"del", "fichero", "tres", "cuatro", "cinco"},
              "2o tiempo: umbrales.json no pisa la reserva del codigo")

        reglas.registrar_catalogo(lambda clave: clave in reglas.VALORES)
        reglas.guardar(_regla_valor("domotica.room_words", ["de", "la", "regla", "cuatro", "cinco"]))
        check(reglas.valor("domotica.room_words") == {"de", "la", "regla", "cuatro", "cinco"},
              "3er tiempo: la superposicion activa no pisa a umbrales.json")

        # Un umbrales.json roto no rompe nada: se vuelve a la reserva.
        (tmp / "umbrales.json").write_text("{roto,,,", encoding="utf-8")
        reglas.guardar(_regla_valor("domotica.room_words", ["x"], "revertida"))
        check(reglas.valor("domotica.room_words") == reserva,
              "con umbrales.json roto y sin regla activa no se vuelve a la reserva")
    finally:
        reglas.config.CONFIG_DIR = cfg_real
        _limpia_almacen()


# ══════════ A2.3 · umbrales.json NO se escribe nunca ══════════
def test_umbrales_json_no_se_toca():
    print("== A2.3) un ciclo completo no toca config/umbrales.json ==")
    _limpia_almacen()
    check(hashlib.sha256(UMBRALES.read_bytes()).hexdigest() == SHA_AL_ARRANCAR,
          "config/umbrales.json ha cambiado antes de llegar a este caso: alguna "
          "llamada a valor() de los casos anteriores lo ha escrito")
    antes = SHA_AL_ARRANCAR

    # Ciclo entero: leer, superponer, revertir, volver a leer.
    reglas.registrar_catalogo(lambda clave: clave in reglas.VALORES)
    for clave in ("domotica.room_words", "domotica.port_hints", "system_pc.no_es_programa"):
        reglas.valor(clave)
    reglas.guardar(_regla_valor("system_pc.no_es_programa", r"(?!(?:nada)\b)"))
    check(reglas.valor("system_pc.no_es_programa") == r"(?!(?:nada)\b)",
          "la superposicion no se ha llegado a aplicar: el ciclo no prueba nada")
    reglas.guardar(_regla_valor("system_pc.no_es_programa", r"(?!(?:nada)\b)", "revertida"))
    check(reglas.valor("system_pc.no_es_programa") == reglas.VALORES["system_pc.no_es_programa"][2],
          "revertir no devuelve el valor de fabrica")

    despues = hashlib.sha256(UMBRALES.read_bytes()).hexdigest()
    check(antes == despues,
          "config/umbrales.json ha cambiado tras un ciclo de valor(): nexus escribe "
          "datos, no configuracion del usuario")
    _limpia_almacen()


# ══════════ A3.1 · _ROOM_WORDS ══════════
def test_room_words_sale_de_reglas():
    print("== A3.1) las palabras de estancia salen de reglas, y el handler las usa ==")
    _limpia_almacen()
    check(not hasattr(DOM, "_ROOM_WORDS"),
          "skills/domotica sigue con la constante _ROOM_WORDS escrita a fuego")
    check(DOM._room_words() == reglas.valor("domotica.room_words"),
          "_room_words() no devuelve lo que dice reglas.valor()")

    class _S:
        def get(self, k, d=None):
            return {"known_devices": [{"name": "Zona Alfa", "ip": "", "brand": "",
                                       "is_tv": True}]}.get(k, d)

    ctx = {"settings": _S()}
    # EL HANDLER, no la regex: «zona» y «alfa» son tokens distintivos, asi que
    # el aparato se resuelve por nombre.
    check(DOM._resolve_named_device(ctx, "enciende zona alfa") is not None,
          "el handler no resuelve un aparato cuyo nombre tiene tokens distintivos")

    # Y si esas dos palabras pasan a ser «de estancia», el mismo handler deja de
    # resolverlo. Eso solo puede pasar si de verdad lee la lista de reglas.
    reglas.registrar_catalogo(lambda clave: clave in reglas.VALORES)
    # Cinco palabras porque el rango declarado exige un minimo: la regla tiene
    # que pasar las puertas para aplicarse, y aqui se comprueba justo eso.
    reglas.guardar(_regla_valor(
        "domotica.room_words", ["zona", "alfa", "sector", "area", "recinto"]))
    check(DOM._resolve_named_device(ctx, "enciende zona alfa") is None,
          "cambiar domotica.room_words no cambia lo que hace _resolve_named_device()")
    _limpia_almacen()


# ══════════ A3.2 · _PORT_HINTS: orden = prioridad, claves int ══════════
def test_port_hints_conserva_orden_y_claves_int():
    print("== A3.2) el sondeo conserva el ORDEN (prioridad) y las claves int ==")
    _limpia_almacen()
    check(not hasattr(DOM, "_PORT_HINTS"),
          "skills/domotica sigue con la constante _PORT_HINTS escrita a fuego")

    tabla = reglas.valor("domotica.port_hints")
    check(list(tabla.keys()) == PUERTOS_EN_ORDEN,
          f"el ORDEN de la tabla ha cambiado: {list(tabla.keys())}")
    check(all(isinstance(k, int) for k in tabla),
          f"hay claves que no son int: {[k for k in tabla if not isinstance(k, int)]}")

    # El mismo valor, pero viniendo de un JSON (donde toda clave es cadena).
    tmp = Path(tempfile.mkdtemp(prefix="nexus_cfg_"))
    (tmp / "umbrales.json").write_text(
        json.dumps({"domotica": {"port_hints": {str(p): tabla[p] for p in PUERTOS_EN_ORDEN}}}),
        encoding="utf-8")
    cfg_real = reglas.config.CONFIG_DIR
    try:
        reglas.config.CONFIG_DIR = tmp
        desde_json = reglas.valor("domotica.port_hints")
        check(list(desde_json.keys()) == PUERTOS_EN_ORDEN,
              f"leido de JSON, el orden se pierde: {list(desde_json.keys())}")
        check(all(isinstance(k, int) for k in desde_json),
              "leido de JSON, las claves se quedan en cadena y el sondeo indexa por int")
    finally:
        reglas.config.CONFIG_DIR = cfg_real

    # EL HANDLER: dos puertos abiertos, gana el que va ANTES en la tabla. 55000
    # esta antes que 8008 en la tabla y DESPUES si alguien la ordena por numero:
    # por eso la etiqueta correcta distingue las dos cosas.
    abiertos = {55000, 8008}
    real = DOM._try_port

    async def _falso(ip, port):
        return port in abiertos

    try:
        DOM._try_port = _falso
        etiqueta = asyncio.run(DOM._probe_ports("ip-de-prueba", asyncio.Semaphore(8)))
    finally:
        DOM._try_port = real
    check(etiqueta == "TV Samsung",
          f"_probe_ports() no respeta la prioridad de la tabla: devuelve «{etiqueta}» "
          "en vez de «TV Samsung» (55000 va antes que 8008)")
    _limpia_almacen()


# ══════════ A3.3 · _NO_ES_PROGRAMA ══════════
def test_no_es_programa_sale_de_reglas():
    print("== A3.3) la lista de exclusion de «kill» sale de reglas ==")
    _limpia_almacen()
    check(SPC._NO_ES_PROGRAMA == reglas.valor("system_pc.no_es_programa"),
          "_NO_ES_PROGRAMA no es lo que dice reglas.valor()")
    check("from backend.core.dominio import reglas" in
          (ROOT / "skills" / "system_pc" / "skill.py").read_text(encoding="utf-8"),
          "system_pc no importa reglas a nivel de modulo, que es la decision de A3.3")

    # El patron sigue acotando igual: un programa entra, un sustantivo de otra
    # skill no.
    def _donde(frase):
        r = sl.route(frase)
        return f"{r[0].folder}/{r[1]}" if r else "planificador"

    check(_donde("cierra spotify") == "system_pc/kill",
          f"«cierra spotify» ya no llega a system_pc/kill: {_donde('cierra spotify')}")
    check(_donde("cierra la sesión") != "system_pc/kill",
          f"«cierra la sesión» se cuela como programa a cerrar: {_donde('cierra la sesión')}")

    # EL HANDLER, no la regex.
    class _Bus:
        async def emit(self, *_a, **_k):
            return None

    class _Set:
        def get(self, k, d=""):
            return d

        def set(self, k, v):
            return None

    class _PsutilVacio:
        @staticmethod
        def process_iter(_campos):
            return []

    psutil_real = SPC.psutil
    try:
        SPC.psutil = _PsutilVacio()
        r = sl.route("cierra spotify")
        res = asyncio.run(SPC.handle(r[1], "cierra spotify", r[2],
                                     {"bus": _Bus(), "settings": _Set(), "channel": "pc"}))
    finally:
        SPC.psutil = psutil_real
    check("spotify" in res.get("reply", "").lower(),
          f"el handler de «kill» no nombra el programa pedido: {res.get('reply', '')!r}")

    # Y cambiar la lista cambia lo que el patron excluye, releyendo el modulo.
    reglas.registrar_catalogo(lambda clave: clave in reglas.VALORES)
    reglas.guardar(_regla_valor("system_pc.no_es_programa", r"(?!(?:zumbido)\b)"))
    sp = importlib.util.spec_from_file_location(
        "_spc_releido", ROOT / "skills" / "system_pc" / "skill.py")
    mod = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(mod)
    import re as _re
    kill = _re.compile(mod.SKILL["patterns"]["kill"], _re.IGNORECASE)
    check(kill.search("cierra zumbido") is None,
          "con «zumbido» en la lista de exclusion, «cierra zumbido» sigue casando: "
          "el patron no se monta con lo que dice reglas")
    check(kill.search("cierra spotify") is not None,
          "el patron releido ya no caza «cierra spotify»")
    _limpia_almacen()


# ══════════ A3.4 · las 32 skills cargan ══════════
def test_un_valor_escrito_a_mano_no_se_salta_las_puertas():
    """«estado: activa» en el fichero NO es una autorizacion.

    EL AGUJERO (encontrado revisando el bloque B, antes de que llegara a
    revision). La superposicion filtraba solo por «el destino existe», asi que un
    valor escrito a mano en `data/reglas_aprendidas.json` entraba en el programa
    SIN pasar por la puerta de tipo ni por la de rango. Y una de estas claves,
    `system_pc.no_es_programa`, es un FRAGMENTO DE REGEX que se concatena al
    patron de una skill: por ahi se cuela lo que se quiera.

    Que solo pueda escribirlo el dueño de la maquina no lo arregla. La promesa de
    este cambio son las puertas; un camino que las rodea las convierte en
    decorado. La unica autorizacion son las puertas, y se vuelven a pasar en el
    punto donde el valor entra de verdad.

    PARA VERLO ROJO: en `reglas._superposicion()`, quitar las dos llamadas a
    `_puerta_campos` y `_puerta_existencia`."""
    print("== B·extra) un valor a mano no se salta las puertas ==")
    _limpia_almacen()
    reglas.registrar_catalogo(lambda clave: clave in reglas.VALORES)
    reserva = reglas.VALORES["domotica.room_words"][2]

    # 1) FUERA DE RANGO. El minimo declarado son 5; se cuela una sola palabra.
    _escribe_almacen([_regla_valor("domotica.room_words", ["unica"])])
    check(reglas.valor("domotica.room_words") == reserva,
          "un valor fuera del rango declarado se aplica igual")

    # 2) TIPO EQUIVOCADO. Se espera un conjunto y llega una cadena; sin mirar el
    #    tipo en crudo, `set("...")` la convierte en letras sueltas y pasa.
    _escribe_almacen([_regla_valor("domotica.room_words", "esto no es una lista")])
    check(reglas.valor("domotica.room_words") == reserva,
          "un valor del tipo equivocado se aplica igual")

    # 3) EL CASO QUE MAS DUELE: un fragmento de regex arbitrario en la clave que
    #    se concatena al patron de una skill.
    reserva_np = reglas.VALORES["system_pc.no_es_programa"][2]
    _escribe_almacen([_regla_valor("system_pc.no_es_programa", "x")])   # 1 < minimo 10
    check(reglas.valor("system_pc.no_es_programa") == reserva_np,
          "un fragmento de regex fuera de contrato entra en el patron de una skill")

    # 4) Y lo que SI cumple el contrato sigue entrando: la puerta no es un muro.
    buena = ["zona", "alfa", "sector", "area", "recinto"]
    _escribe_almacen([_regla_valor("domotica.room_words", buena)])
    check(reglas.valor("domotica.room_words") == set(buena),
          "una regla que cumple el contrato ha dejado de aplicarse")


def test_los_tres_valores_migrados_son_LOS_DE_ANTES():
    """A4.3, pero como PRUEBA y no como comprobacion de una tarde.

    A4.3 se verificaba volcando el enrutado de todo el corpus antes y despues y
    comparando los dos ficheros. Eso demuestra que la migracion salio bien EL DIA
    QUE SE HIZO, y despues no queda nada: el diff se tira y nadie lo repite.

    EL AGUJERO QUE TAPA ESTE CASO (medido el 05/08/2026). Las pruebas del bloque
    A pinchaban la fontaneria —de donde sale el valor, en que orden, con que tipo
    de clave— pero NINGUN valor. Se comprobo saboteando:

      * quitar «conversaci[oó]n», «hilos?» y «mensajes?» del fragmento de
        `system_pc.no_es_programa`: las 81 suites en VERDE. Y con eso «cierra la
        conversacion» pasa a tratarse como un programa que cerrar.
      * cambiar la etiqueta del puerto 8060 de «TV Roku» a «TV LG»: VERDE.
      * quitar «salon», «tele», «tv», «television» y «sala» de
        `domotica.room_words`: solo `test_routing` se quejaba, y de rebote.

    Los tres casos son el error tipico de sacar una lista del codigo: se copia y
    se pierde una linea por el camino. Aqui se compara contra lo que habia ANTES,
    escrito a mano arriba.

    PARA VERLO ROJO: borra una palabra de cualquiera de las tres reservas de
    `reglas.VALORES`."""
    print("== A4.3) los tres valores migrados son EXACTAMENTE los de antes ==")
    _limpia_almacen()

    # 1) room_words: el conjunto entero, no solo «sale de reglas».
    hoy = reglas.valor("domotica.room_words")
    check(hoy == ROOM_WORDS_DE_ANTES,
          f"domotica.room_words ya no es la lista de antes de la migracion: "
          f"faltan {sorted(ROOM_WORDS_DE_ANTES - hoy)}, "
          f"sobran {sorted(hoy - ROOM_WORDS_DE_ANTES)}")

    # 2) port_hints: puerto Y ETIQUETA, en orden. El orden ya se comprobaba; la
    #    etiqueta no la miraba nadie, y es lo que ve el usuario en el HUD.
    check(list(reglas.valor("domotica.port_hints").items()) == PORT_HINTS_DE_ANTES,
          "domotica.port_hints ya no es la tabla de antes (puerto, etiqueta u orden): "
          f"{list(reglas.valor('domotica.port_hints').items())}")

    # 3) no_es_programa: las 59 alternativas del lookahead, en orden.
    frag = reglas.valor("system_pc.no_es_programa")
    cuerpo = frag[len("(?!(?:"):-len(r")\b)")]
    toks = [t for t in cuerpo.split("|") if t]
    check(toks == NO_ES_PROGRAMA_DE_ANTES,
          "system_pc.no_es_programa ya no excluye lo mismo que antes: "
          f"faltan {[t for t in NO_ES_PROGRAMA_DE_ANTES if t not in toks]}, "
          f"sobran {[t for t in toks if t not in NO_ES_PROGRAMA_DE_ANTES]}")


def test_lo_que_no_es_un_programa_sigue_sin_serlo():
    """Y lo mismo, pero por el lado del COMPORTAMIENTO.

    Comparar listas prueba que el texto no ha cambiado. Esto prueba que el texto
    SIRVE PARA ALGO: cada sustantivo que el fragmento excluye tiene que seguir
    sin llegar a `system_pc/kill`. Si un dia el fragmento se reescribe entero
    —agrupando alternativas, por ejemplo— la comparacion de arriba se pondria
    roja aunque el comportamiento fuera identico, y alguien la «arreglaria»
    pegando la lista nueva. Este caso es el que no se puede arreglar pegando.

    PARA VERLO ROJO: quita «conversaci[oó]n» de la reserva de
    `system_pc.no_es_programa`; «cierra la conversación» pasa a system_pc/kill."""
    print("== A4.3) lo que el fragmento excluye no llega a «kill» ==")
    _limpia_almacen()

    def _donde(frase):
        r = sl.route(frase)
        return f"{r[0].folder}/{r[1]}" if r else "planificador"

    # Un sustantivo por bloque del fragmento: chrome, tasks_board, billing,
    # google_workspace, domotica, comms, «no son programas» y metaforas.
    for frase in ("cierra las pestañas", "cierra el historial",
                  "cierra el tablero", "cierra las tareas", "cierra las notas",
                  "cierra las facturas", "cierra los presupuestos",
                  "cierra los correos", "cierra la bandeja", "cierra el calendario",
                  "cierra la tele", "cierra las persianas", "cierra las cortinas",
                  "cierra la puerta", "cierra el garaje", "cierra el gas",
                  "cierra el grifo", "cierra la calefacción",
                  "cierra la conversación", "cierra los hilos", "cierra los mensajes",
                  "cierra el chat", "cierra la sesión", "cierra las ventanas",
                  "cierra el diálogo", "cierra el menú", "cierra los paneles",
                  "cierra la boca", "cierra los ojos", "cierra los puertos",
                  "cierra el trato", "cierra el acuerdo", "cierra el caso",
                  "cierra el tema", "cierra el asunto", "cierra el debate"):
        check(_donde(frase) != "system_pc/kill",
              f"«{frase}» se trata como un programa que cerrar: "
              "el fragmento system_pc.no_es_programa ha dejado de excluirlo")

    # Y lo que SI es un programa sigue llegando: el lookahead no es un muro.
    for frase in ("cierra spotify", "cierra chrome", "mata notepad"):
        check(_donde(frase) == "system_pc/kill",
              f"«{frase}» ha dejado de llegar a system_pc/kill: {_donde(frase)}")


def test_dos_reglas_del_mismo_valor_no_dependen_del_orden_del_fichero():
    """Con dos reglas activas sobre la MISMA clave, gana la mas reciente —
    siempre la misma, se lean en el orden que se lean.

    EL FALLO (encontrado auditando el bloque A el 05/08/2026). `activas()` ordena
    a proposito por fecha de activacion, y lo dice en su propio docstring: «no se
    depende del orden de lectura del fichero ni del de insercion de un
    diccionario, para que dos ejecuciones con el mismo almacen den lo mismo».
    `_superposicion()` —que es la TERCERA fase de `valor()`— no ordenaba nada:
    recorria las reglas en el orden del fichero y la ultima pisaba a las
    anteriores. Con las mismas dos reglas, cambiar de sitio dos lineas del JSON
    cambiaba el valor.

    Y no es hipotetico: `guardar()` reescribe la lista como «todas menos esta, y
    esta al final», asi que guardar CUALQUIER regla reordena el fichero. Una de
    estas claves, `system_pc.no_es_programa`, se concatena al patron de una skill
    AL IMPORTARLA: el mismo almacen podia dar dos patrones distintos en dos
    arranques, sin dejar rastro de por que.

    PARA VERLO ROJO: en `_superposicion()`, volver a recorrer
    `cargar()["reglas"]` directamente en vez de la lista ordenada."""
    print("== A2.2) el orden de las lineas del almacen no cambia el valor ==")
    _limpia_almacen()
    reglas.registrar_catalogo(lambda clave: clave in reglas.VALORES)

    def _r(rid, palabras, activada):
        r = _regla_valor("domotica.room_words", palabras, rid=rid)
        r["activada"] = activada
        return r

    vieja = _r("r-vieja", ["alfa", "beta", "gamma", "delta", "epsilon"],
               "2026-01-01T00:00:00")
    nueva = _r("r-nueva", ["uno", "dos", "tres", "cuatro", "cinco"],
               "2026-08-04T00:00:00")

    salidas = []
    for lista in ([vieja, nueva], [nueva, vieja]):
        _escribe_almacen(lista)
        reglas.olvida_huella()
        salidas.append(reglas.valor("domotica.room_words"))
    check(salidas[0] == salidas[1],
          f"el mismo almacen da valores distintos segun el orden de sus lineas: "
          f"{sorted(salidas[0])} vs {sorted(salidas[1])}")
    check(salidas[0] == {"uno", "dos", "tres", "cuatro", "cinco"},
          f"no gana la regla mas reciente, gana la que toque por orden: {sorted(salidas[0])}")
    _limpia_almacen()


# Claves del bloque `aprendizaje` que estan en el fichero A PROPOSITO sin que
# ningun codigo las lea todavia, cada una con la tarea que las va a cablear. Que
# haya que apuntarlas AQUI es el objetivo: una clave que el usuario puede tocar y
# que no hace nada es una promesa que nadie cumple, y sin esta lista se queda ahi
# para siempre sin que nadie se entere. El dia que C3.9 aterrice, este test dira
# que la quites de la lista.
UMBRALES_PENDIENTES = {
    "dias_caducidad_propuesta": "C3.9, todavia sin hacer: hoy ninguna propuesta caduca",
}


def test_el_bloque_aprendizaje_de_umbrales_esta_cableado():
    """Cada numero de `config/umbrales.json` lo lee alguien, y cada numero que
    lee el codigo lo puede tocar el usuario.

    A2.4 metio cuatro claves en `config/umbrales.json` y no dejo ninguna prueba.
    Borrar el bloque `aprendizaje` ENTERO dejaba las 81 suites en verde
    (comprobado el 05/08/2026), lo cual esta bien —el fichero no viaja en una
    instalacion limpia y el codigo tiene reserva— pero significa que nadie
    vigilaba las dos formas de que ese fichero mienta:

      * una clave escrita en el fichero que ningun codigo lee: el usuario la
        cambia, reinicia, y no pasa nada. `dias_caducidad_propuesta` es
        exactamente eso hoy, y su texto de ayuda describe un comportamiento que
        todavia no existe.
      * una clave que el codigo lee con un nombre distinto del que hay en el
        fichero (una errata en cualquiera de los dos lados): nexus se queda con
        la reserva para siempre y el ajuste del usuario no hace nada, en
        silencio.

    PARA VERLO ROJO: cambia `tope_frases_arrastradas` por `tope_frases` en
    `config/umbrales.json`, o quita `dias_caducidad_propuesta` de
    `UMBRALES_PENDIENTES` de aqui arriba."""
    print("== A2.4) el bloque «aprendizaje» de umbrales.json esta cableado ==")
    import re as _re
    datos = json.loads(UMBRALES.read_text(encoding="utf-8"))
    bloque = datos.get("aprendizaje")
    if not check(isinstance(bloque, dict),
                 "config/umbrales.json no trae el bloque «aprendizaje» de A2.4"):
        return

    # Las claves de verdad: las que no empiezan por «_» (esas son la explicacion).
    del_fichero = {k: v for k, v in bloque.items() if not k.startswith("_")}

    # Las que el codigo lee de verdad, sacadas del propio codigo.
    leidas: dict[str, float] = {}
    for py in sorted((ROOT / "backend").rglob("*.py")):
        for clave, reserva in _re.findall(
                r'\b_?umbral\(\s*"([a-z_]+)"\s*,\s*([0-9.]+)\s*\)',
                py.read_text(encoding="utf-8")):
            leidas[clave] = float(reserva)
    check(leidas, "no se ha encontrado ni una llamada a umbral() en backend/: "
                  "¿ha cambiado la forma de leer los umbrales?")

    for clave in sorted(leidas):
        check(clave in del_fichero,
              f"el codigo lee el umbral «{clave}» pero no esta en el bloque "
              "«aprendizaje» de config/umbrales.json: el usuario no puede tocarlo")

    for clave in sorted(del_fichero):
        if clave in leidas:
            continue
        check(clave in UMBRALES_PENDIENTES,
              f"«{clave}» esta en config/umbrales.json y no lo lee NINGUN codigo: "
              "o lo cableas, o lo quitas, o lo declaras en UMBRALES_PENDIENTES "
              "diciendo que tarea lo va a cablear")

    for clave in sorted(UMBRALES_PENDIENTES):
        check(clave not in leidas,
              f"«{clave}» ya lo lee el codigo: quitalo de UMBRALES_PENDIENTES, "
              f"que su motivo era «{UMBRALES_PENDIENTES[clave]}»")
        check(clave in del_fichero,
              f"«{clave}» esta declarado pendiente pero ya no esta en "
              "config/umbrales.json: quitalo tambien de UMBRALES_PENDIENTES")

    # Y la reserva del codigo coincide con lo que trae el fichero: si no, el
    # fichero documenta un valor por defecto que no es el que se usa cuando el
    # fichero no viaja.
    for clave, reserva in sorted(leidas.items()):
        if clave not in del_fichero:
            continue
        check(float(del_fichero[clave]) == reserva,
              f"«{clave}» vale {del_fichero[clave]} en config/umbrales.json y "
              f"{reserva} de reserva en el codigo: en una instalacion limpia, "
              "donde el fichero no viaja, nexus se comporta de otra manera")

    # Y el cableado se comprueba de verdad: cambiar el fichero cambia lo que
    # devuelve umbral(). Comparar dos numeros iguales no prueba que se lean.
    tmp = Path(tempfile.mkdtemp(prefix="nexus_umb_"))
    (tmp / "umbrales.json").write_text(
        json.dumps({"aprendizaje": {k: 987 for k in leidas}}), encoding="utf-8")
    cfg_real = reglas.config.CONFIG_DIR
    try:
        reglas.config.CONFIG_DIR = tmp
        for clave, reserva in sorted(leidas.items()):
            check(reglas.umbral(clave, reserva) == 987,
                  f"umbral(«{clave}») no lee config/umbrales.json: devuelve la "
                  "reserva del codigo aunque el fichero diga otra cosa")
    finally:
        reglas.config.CONFIG_DIR = cfg_real


def test_las_skills_siguen_cargando():
    print("== A3.4) ninguna skill se queda en error por el import nuevo ==")
    reg = sl.load_skills()
    malas = {k: v.description for k, v in reg.items() if v.status == "error"}
    check(not malas, f"skills en error tras la migracion: {malas}")
    check(len(reg) == 32, f"se cargan {len(reg)} skills en vez de 32")


# ══════════ nada personal en los ficheros nuevos ══════════
def test_los_ficheros_nuevos_no_llevan_datos_personales():
    print("== los ficheros nuevos no llevan nada del duenno ==")
    import re as _re
    nuevos = [ROOT / "backend" / "core" / "dominio" / "reglas.py",
              ROOT / "tests" / "test_reglas_valores.py"]
    # Las palabras se arman por trozos a proposito: este fichero se escanea a si
    # mismo, y escribirlas enteras lo pondria rojo por su propia guarda.
    prohibidas = ("ad" + "ri", "maq" + "ueda", "ach" + "oz")
    for f in nuevos:
        txt = f.read_text(encoding="utf-8")
        for palabra in prohibidas:
            check(palabra not in txt.lower(), f"«{palabra}» aparece en {f.name}")
        ips = _re.findall(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])", txt)
        check(not ips, f"IPs completas escritas en {f.name}: {ips[:3]}")
        macs = _re.findall(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b", txt)
        check(not macs, f"MACs completas escritas en {f.name}: {macs[:3]}")


def main() -> int:
    for f in (test_almacen_corrupto_degrada_a_fabrica,
              test_sin_arbitro_no_activa_nada,
              test_valor_resuelve_en_tres_tiempos,
              test_umbrales_json_no_se_toca,
              test_room_words_sale_de_reglas,
              test_port_hints_conserva_orden_y_claves_int,
              test_no_es_programa_sale_de_reglas,
              test_un_valor_escrito_a_mano_no_se_salta_las_puertas,
              test_los_tres_valores_migrados_son_LOS_DE_ANTES,
              test_lo_que_no_es_un_programa_sigue_sin_serlo,
              test_dos_reglas_del_mismo_valor_no_dependen_del_orden_del_fichero,
              test_el_bloque_aprendizaje_de_umbrales_esta_cableado,
              test_las_skills_siguen_cargando,
              test_los_ficheros_nuevos_no_llevan_datos_personales):
        try:
            f()
        except Exception as e:                             # noqa: BLE001
            import traceback
            _fail.append(f"EXCEPCION en {f.__name__}: {type(e).__name__}: {e}")
            print("  ✖ EXCEPCION en", f.__name__, ":", type(e).__name__, e)
            traceback.print_exc()
    print(f"\n{'#' * 54}\ntest_reglas_valores: {_pass} OK, {len(_fail)} fallos")
    for m in _fail:
        print("  -", m)
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
