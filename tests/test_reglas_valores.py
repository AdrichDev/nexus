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

# El orden de la tabla ES la prioridad del sondeo. Se escribe aqui a mano, no se
# deriva de VALORES: si se derivara, reordenarla en el codigo no pondria nada en
# rojo y esta prueba no probaria nada.
PUERTOS_EN_ORDEN = [8060, 8001, 8002, 55000, 8008, 8009, 7000, 32400, 8123,
                    1883, 9100, 631, 554, 445, 3389, 22, 62078, 5353, 53, 8080]


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
    reglas.guardar(_regla_valor("domotica.room_words", ["inventada"]))
    check(reglas.valor("domotica.room_words") == reglas.VALORES["domotica.room_words"][2],
          "una regla «activa» del fichero cambia el valor SIN catalogo registrado")

    # Con catalogo, esa misma regla si manda.
    reglas.registrar_catalogo(lambda clave: clave in reglas.VALORES)
    check(reglas.valor("domotica.room_words") == {"inventada"},
          "con catalogo registrado, la regla activa no se aplica")

    # Y una regla que NO esta activa nunca manda, aunque haya catalogo.
    reglas.guardar(_regla_valor("domotica.room_words", ["inventada"], "revertida"))
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
        json.dumps({"domotica": {"room_words": ["del", "fichero"]}}), encoding="utf-8")
    cfg_real = reglas.config.CONFIG_DIR
    try:
        reglas.config.CONFIG_DIR = tmp
        check(reglas.valor("domotica.room_words") == {"del", "fichero"},
              "2o tiempo: umbrales.json no pisa la reserva del codigo")

        reglas.registrar_catalogo(lambda clave: clave in reglas.VALORES)
        reglas.guardar(_regla_valor("domotica.room_words", ["de", "la", "regla"]))
        check(reglas.valor("domotica.room_words") == {"de", "la", "regla"},
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
    reglas.guardar(_regla_valor("domotica.room_words", ["zona", "alfa"]))
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
