# -*- coding: utf-8 -*-
"""Bloque B de 004: el contrato de una regla y las puertas 1-3.

Lo que se comprueba aqui es que EL FICHERO NO OTORGA AUTORIDAD. `data/reglas_
aprendidas.json` vive en la maquina del usuario, es texto plano y cualquiera
puede escribir `"estado": "activa"` dentro. La unica defensa real es volver a
pasar las puertas en cada carga, y eso es lo que se prueba: una regla podrida
escrita a mano no activa nada, y ademas no tumba a las sanas que estan a su lado.

Las puertas se prueban por SU EFECTO, no por su nombre: cada caso construye una
regla que falla por un motivo concreto y exige que el motivo NOMBRE la causa. Un
booleano no dice que campo falta, y con un booleano el mensaje de la auditoria
puede mentir sin que nadie se entere.

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_reglas_contrato.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("NEXUS_DATA_DIR", tempfile.mkdtemp(prefix="nexus_contrato_"))

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


from backend.core.dominio import reglas                      # noqa: E402

# Frases que el arbitro de mentira da por atendidas por una skill. Sirven para
# distinguir un ROBO (skill -> otra cosa) de un ARRASTRE (planificador -> regla).
ATENDIDAS = {"apaga la tele": "skill:domotica/tv_off",
             "crea una tarea": "skill:tasks_board/create"}


def _arbitro_falso(frase: str, channel: str = "pc", reglas=None) -> str:
    """Un `quien_atiende` de juguete con el MISMO orden que el de verdad: primero
    la skill, y las reglas solo en el hueco que quedaria para el planificador.

    La firma calca la de `brain.quien_atiende(text, channel, reglas)` a proposito.
    `reglas.arbitro()` llama con `reglas=` por nombre y se traga cualquier
    excepcion: un arbitro con otra firma no revienta, contesta «no lo se» y todas
    las reglas caen — un fallo que se lee como si las reglas estuvieran mal."""
    if frase in ATENDIDAS:
        return ATENDIDAS[frase]
    for r in (reglas or ()):
        try:
            if re.search(r.get("patron", ""), frase, re.IGNORECASE):
                return f"regla:{r.get('id')}"
        except Exception:                                  # noqa: BLE001
            continue
    return "planificador"


def _catalogo_falso(destino: str) -> bool:
    return destino in ("domotica/tv_off", "tasks_board/create") or destino in reglas.VALORES


def _limpia() -> None:
    p = reglas.ruta_almacen()
    for f in (p, p.with_name(p.name + ".bak"), p.with_name(p.name + ".tmp")):
        try:
            f.unlink()
        except Exception:                                  # noqa: BLE001
            pass
    reglas.registrar_catalogo(None)
    reglas.registrar_arbitro(None)
    reglas.olvida_huella()


def _regla(**cambios) -> dict:
    r = {"id": "r-uno", "esquema": reglas.ESQUEMA, "tipo": "enrutado", "revision": 1,
         "origen": {"frase": "no, cierra el navegador", "canal": "pc",
                    "fecha": "2026-08-04T10:00:00", "tipo": "ordenada", "veces": 1},
         "destino": "tasks_board/create",
         "patron": r"^\s*cierra\s+el\s+navegador\s*$",
         "evidencia": {"arrastradas": [], "suite": None},
         "estado": "propuesta"}
    r.update(cambios)
    return r


def _corpus_con(frases: list[str]) -> Path:
    """Un SKILLS_DIR de mentira con las frases que se le pidan."""
    tmp = Path(tempfile.mkdtemp(prefix="nexus_corpus_"))
    (tmp / "falsa").mkdir()
    (tmp / "falsa" / "SKILL.md").write_text(
        "# Falsa\n\n" + "".join(f"- «{f}» → algo\n" for f in frases), encoding="utf-8")
    return tmp


def _corpus_de_juguete() -> Path:
    """Un SKILLS_DIR de mentira: asi tocar un `mtime` no roza las skills reales."""
    return _corpus_con(["apaga la tele", "crea una tarea", "cierra el navegador"])


# ══════════ B1.1 · estados y transiciones ══════════
def test_revertida_no_vuelve_a_activa():
    print("== B1.1) una regla revertida no vuelve a activa sin volver a aprobarse ==")
    _limpia()
    check(reglas.ESTADOS == ("propuesta", "activa", "revertida", "descartada", "invalida"),
          f"la lista de estados no es la del contrato: {reglas.ESTADOS}")
    check(reglas.TIPOS == ("enrutado", "valor", "aviso"),
          f"la lista de tipos no es la del contrato: {reglas.TIPOS}")

    reglas.guardar(_regla())
    check(reglas.transitar("r-uno", "activa", "aprobada") is True,
          "propuesta -> activa se rechaza, y es la transicion normal")
    check(reglas.transitar("r-uno", "revertida", "el duenno la olvida") is True,
          "activa -> revertida se rechaza, y es como se deshace")

    check(reglas.transitar("r-uno", "activa", "por la puerta de atras") is False,
          "revertida -> activa se acepta: una regla deshecha revive sola")
    guardada = [r for r in reglas.cargar()["reglas"] if r["id"] == "r-uno"][0]
    check(guardada["estado"] == "revertida",
          f"la transicion prohibida ha cambiado el estado igualmente: {guardada['estado']}")
    check(guardada["origen"]["frase"] == "no, cierra el navegador",
          "revertir ha perdido la frase que origino la regla: nada se borra")

    check(reglas.transitar("r-uno", "inventado", "x") is False,
          "un estado que no esta en ESTADOS se acepta")
    check(reglas.transitar("r-no-existe", "activa", "x") is False,
          "se puede transitar una regla que no esta en el almacen")
    _limpia()


# ══════════ B1.2 · puerta 1, campos ══════════
def test_puerta_campos_nombra_el_que_falta():
    print("== B1.2) la puerta de campos dice QUE campo falta, no «no vale» ==")
    _limpia()
    for campo in ("id", "tipo", "origen", "destino", "evidencia", "estado", "revision"):
        r = _regla()
        r.pop(campo)
        ok, motivo = reglas.valida(r)
        check(ok is False, f"una regla sin «{campo}» pasa la puerta de campos")
        check(campo in motivo,
              f"al faltar «{campo}» el motivo no lo nombra: «{motivo}»")

    # `patron` es el octavo campo cuando el tipo es `enrutado`.
    ok, motivo = reglas.valida(_regla(patron=""))
    check(ok is False and "patron" in motivo,
          f"una regla de enrutado sin patron pasa o no lo nombra: «{motivo}»")

    # `origen.frase` literal y no vacia: sin ella no se puede ensennar al duenno
    # que originó la regla, que es lo unico que le deja juzgarla.
    ok, motivo = reglas.valida(_regla(origen={"frase": "  ", "canal": "pc",
                                              "fecha": "2026-08-04T10:00:00"}))
    check(ok is False and "frase" in motivo,
          f"una regla con origen.frase vacia pasa la puerta: «{motivo}»")
    for hueco in ("canal", "fecha"):
        o = {"frase": "no, cierra el navegador", "canal": "pc",
             "fecha": "2026-08-04T10:00:00"}
        o.pop(hueco)
        ok, motivo = reglas.valida(_regla(origen=o))
        check(ok is False and hueco in motivo,
              f"un origen sin «{hueco}» pasa o no lo nombra: «{motivo}»")

    ok, motivo = reglas.valida(_regla(tipo="prompt"))
    check(ok is False and "prompt" in motivo,
          f"un tipo desconocido pasa o no se nombra: «{motivo}»")

    # Y guardar en el almacen tampoco acepta un objeto que no es una regla.
    antes = json.dumps(reglas.cargar(), sort_keys=True)
    lanzo = ""
    try:
        r = _regla()
        r.pop("evidencia")
        reglas.guardar(r)
    except ValueError as e:
        lanzo = str(e)
    check("evidencia" in lanzo,
          f"guardar() acepta una regla sin «evidencia» o no lo dice: «{lanzo}»")
    check(json.dumps(reglas.cargar(), sort_keys=True) == antes,
          "el almacen ha cambiado tras rechazar una regla invalida")
    _limpia()


# ══════════ B1.3 · puerta 2, existencia ══════════
def test_destino_inexistente_y_rango_fuera():
    print("== B1.3) la puerta de existencia deniega sin catalogo y por rango ==")
    _limpia()
    # Sin catalogo registrado NO se aprueba nada: nexus no valida a ciegas.
    ok, motivo = reglas.valida(_regla(destino="tasks_board/create"))
    check(ok is False and "catalogo" in motivo.lower(),
          f"sin catalogo registrado la puerta de existencia deja pasar: «{motivo}»")

    reglas.registrar_catalogo(_catalogo_falso)
    ok, motivo = reglas.valida(_regla(destino="agenda/crear_reunion"))
    check(ok is False and "agenda/crear_reunion" in motivo,
          f"un destino inexistente pasa o no se nombra: «{motivo}»")

    # Reglas `valor`: la clave tiene que estar declarada, y el valor respetar
    # tipo y rango. `domotica.room_words` es un set de entre 5 y 200 elementos.
    base = {"tipo": "valor", "destino": "domotica.room_words", "patron": None}
    ok, motivo = reglas.valida(_regla(**base, valor=["solo", "dos"]))
    check(ok is False and "rango" in motivo.lower(),
          f"un valor por debajo del rango declarado pasa: «{motivo}»")
    ok, motivo = reglas.valida(_regla(**base, valor="no soy una lista"))
    check(ok is False and "tipo" in motivo.lower(),
          f"un valor del tipo equivocado pasa: «{motivo}»")
    ok, motivo = reglas.valida(_regla(tipo="valor", destino="backend/core/brain.py",
                                      patron=None, valor=["a"]))
    check(ok is False and "backend/core/brain.py" in motivo,
          f"una regla valor puede apuntar a un fichero de codigo: «{motivo}»")

    dentro = [f"palabra{i}" for i in range(8)]
    ok, motivo = reglas.valida(_regla(**base, valor=dentro))
    check(ok is True, f"un valor dentro de tipo y rango se rechaza: «{motivo}»")

    # UNA CLAVE CUYO VALOR ES UN FRAGMENTO DE REGEX SE COMPILA AQUI.
    #
    # `system_pc.no_es_programa` no es texto: se CONCATENA al patron de una
    # skill al importarla. Tipo y longitud correctos no impiden que sea un
    # parentesis sin cerrar, y entonces la skill deja de compilar y se cae
    # entera al arrancar con la regla ya escrita en disco. Nadie miraba esto:
    # quitar el `re.compile` de la puerta dejaba las 81 suites verdes.
    regex = {"tipo": "valor", "destino": "system_pc.no_es_programa", "patron": None}
    ok, motivo = reglas.valida(_regla(**regex, valor="(?!(?:hola" + "x" * 20))
    check(ok is False and "compila" in motivo.lower(),
          f"un fragmento de regex con un parentesis sin cerrar entra en el patron "
          f"de una skill: «{motivo}»")
    ok, motivo = reglas.valida(_regla(**regex, valor="(?!(?:" + "a" * 10 + "+)+)"))
    check(ok is False and "retroceso" in motivo.lower(),
          f"un fragmento con cuantificador anidado entra en el patron de una "
          f"skill: «{motivo}»")
    ok, motivo = reglas.valida(_regla(**regex, valor=r"(?!(?:la|los|" + "x" * 10 + r")\b)"))
    check(ok is True, f"un fragmento de regex sano se rechaza: «{motivo}»")
    _limpia()


# ══════════ B1.4/B1.5 · puerta 3, forma ══════════
def test_puerta_forma_rechaza_cuantificador_anidado():
    print("== B1.4/5) la puerta de forma para el ReDoS y el patron sin anclar ==")
    _limpia()
    reglas.registrar_catalogo(_catalogo_falso)

    # ReDoS clasico: `^(a+)+$` retrocede exponencialmente con una cadena que no
    # casa. Una regex aprendida corre en CADA mensaje: colgaria nexus entero.
    ok, motivo = reglas.valida(_regla(patron=r"^(a+)+$"))
    check(ok is False and "cuantificador" in motivo.lower(),
          f"«^(a+)+$» pasa la puerta de forma: «{motivo}»")

    # AQUI NO BASTA CON `ok is False`, Y ESTE ES EL PUNTO ENTERO DEL CASO.
    #
    # En este banco NADIE ha registrado arbitro, asi que la puerta 4 deniega
    # SIEMPRE y `ok` sale `False` pase lo que pase en la puerta 3. Las dos
    # comprobaciones de abajo miraban solo eso: con la puerta de forma ENTERA
    # neutralizada seguian en verde, y quitar el rechazo del «.» libre dejaba
    # las 81 suites verdes. Se exige el MOTIVO, que es lo unico que distingue
    # «la puerta 3 lo ha parado» de «es que aqui no pasa nada».
    #
    # `^.*$` casa con TODO: no es una forma nueva de decir algo, es una red.
    ok, motivo = reglas.valida(_regla(patron=r"^.*$"))
    check(ok is False and "libre" in motivo.lower(),
          f"«^.*$» pasa la puerta de forma y se queda con el corpus entero: «{motivo}»")
    ok, motivo = reglas.valida(_regla(patron=r"^cierra el .*navegador$"))
    check(ok is False and "libre" in motivo.lower(),
          f"un «.» cuantificado en medio de un patron anclado pasa: «{motivo}»")

    ok, motivo = reglas.valida(_regla(patron=r"cierra el navegador"))
    check(ok is False and "ancl" in motivo.lower(),
          f"un patron sin anclar pasa: «{motivo}»")
    ok, motivo = reglas.valida(_regla(patron=r"^cierra el navegador"))
    check(ok is False and "ancl" in motivo.lower(),
          f"un patron anclado solo por delante pasa: «{motivo}»")
    ok, motivo = reglas.valida(_regla(patron=r"cierra el navegador$"))
    check(ok is False and "ancl" in motivo.lower(),
          f"un patron anclado solo por detras pasa: «{motivo}»")

    ok, motivo = reglas.valida(_regla(patron=r"^(cierra$"))
    check(ok is False and "compila" in motivo.lower(),
          f"un patron que no compila pasa o no se explica: «{motivo}»")

    ok, motivo = reglas.valida(_regla(patron=r"^ab$"))
    check(ok is False and "corto" in motivo.lower(),
          f"un patron por debajo del largo minimo pasa: «{motivo}»")
    ok, motivo = reglas.valida(_regla(patron="^" + "a" * 500 + "$"))
    check(ok is False and "largo" in motivo.lower(),
          f"un patron por encima del largo maximo pasa: «{motivo}»")

    # Y uno bien formado llega hasta la puerta 4, que sin arbitro deniega: asi se
    # ve que el fallo de arriba era de FORMA y no de que todo se rechace.
    ok, motivo = reglas.valida(_regla(patron=r"^\s*cierra\s+el\s+navegador\s*$"))
    check(ok is False and "arbitro" in motivo.lower(),
          f"un patron bien formado no llega a la puerta 4: «{motivo}»")
    _limpia()


# ══════════ B1.6/B1.7 · el fichero no otorga autoridad ══════════
def test_estado_activa_escrito_a_mano_no_activa():
    print("== B1.6/7) «estado: activa» escrito a mano no activa nada ==")
    _limpia()
    # Con catalogo registrado: asi la regla llega hasta la puerta de FORMA y el
    # motivo que se comprueba abajo es el de verdad, no un «falta catalogo».
    reglas.registrar_catalogo(_catalogo_falso)
    podrida = _regla(id="r-podrida", estado="activa", patron=r"^(a+)+$")
    reglas.ruta_almacen().parent.mkdir(parents=True, exist_ok=True)
    reglas.ruta_almacen().write_text(
        json.dumps({"esquema": reglas.ESQUEMA, "reglas": [podrida]}, ensure_ascii=False),
        encoding="utf-8")

    check(reglas.activas() == [],
          "una regla podrida con «estado: activa» escrita a mano entra en activas()")

    # Y queda AISLADA en el fichero, con el motivo escrito: el duenno tiene que
    # poder ver por que no se aplica sin ejecutar nada.
    en_disco = [r for r in reglas.cargar()["reglas"] if r["id"] == "r-podrida"][0]
    check(en_disco["estado"] == "invalida",
          f"la regla podrida sigue como «{en_disco['estado']}» en el fichero")
    check("cuantificador" in str(en_disco.get("motivo", "")).lower(),
          f"la regla aislada no dice por que: {en_disco.get('motivo')!r}")
    _limpia()


def test_una_regla_podrida_no_invalida_las_sanas():
    print("== B1.7) una regla mal escrita no tumba a las que estan a su lado ==")
    _limpia()
    reglas.registrar_catalogo(_catalogo_falso)
    reglas.registrar_arbitro(_arbitro_falso)
    corpus = _corpus_de_juguete()
    skills_real = reglas.config.SKILLS_DIR
    try:
        reglas.config.SKILLS_DIR = corpus
        sana = _regla(id="r-sana", estado="activa",
                      patron=r"^\s*cierra\s+el\s+navegador\s*$",
                      origen={"frase": "cierra el navegador", "canal": "pc",
                              "fecha": "2026-08-04T10:00:00"})
        podrida = _regla(id="r-podrida", estado="activa", patron=r"^(a+)+$")
        reglas.ruta_almacen().parent.mkdir(parents=True, exist_ok=True)
        reglas.ruta_almacen().write_text(
            json.dumps({"esquema": reglas.ESQUEMA, "reglas": [podrida, sana]},
                       ensure_ascii=False), encoding="utf-8")

        vivas = reglas.activas()
        check([r["id"] for r in vivas] == ["r-sana"],
              f"la regla podrida se ha llevado por delante a la sana: {[r['id'] for r in vivas]}")
        en_disco = {r["id"]: r["estado"] for r in reglas.cargar()["reglas"]}
        check(en_disco == {"r-podrida": "invalida", "r-sana": "activa"},
              f"los estados en el fichero no son los esperados: {en_disco}")
    finally:
        reglas.config.SKILLS_DIR = skills_real
        _limpia()


def test_esquema_futuro_no_activa_nada():
    print("== B1.7) un almacen de un nexus mas nuevo se lee en SOLO LECTURA ==")
    _limpia()
    reglas.registrar_catalogo(_catalogo_falso)
    reglas.registrar_arbitro(_arbitro_falso)
    corpus = _corpus_de_juguete()
    skills_real = reglas.config.SKILLS_DIR
    try:
        reglas.config.SKILLS_DIR = corpus
        sana = _regla(id="r-sana", estado="activa",
                      patron=r"^\s*cierra\s+el\s+navegador\s*$")
        reglas.ruta_almacen().parent.mkdir(parents=True, exist_ok=True)
        reglas.ruta_almacen().write_text(
            json.dumps({"esquema": reglas.ESQUEMA + 8, "reglas": [sana]},
                       ensure_ascii=False), encoding="utf-8")

        check(reglas.solo_lectura() is True,
              "un esquema mayor que el conocido no pone el almacen en solo lectura")
        check(reglas.activas() == [],
              "con un esquema del futuro sigue habiendo reglas activas")
        # Y no se escribe encima: migrar hacia atras en silencio pierde datos.
        antes = reglas.ruta_almacen().read_text(encoding="utf-8")
        reglas.transitar("r-sana", "revertida", "x")
        check(reglas.ruta_almacen().read_text(encoding="utf-8") == antes,
              "se ha escrito sobre un almacen de un esquema que no se entiende")
    finally:
        reglas.config.SKILLS_DIR = skills_real
        _limpia()


# ══════════ B1.8 · la huella evita el barrido, el cambio lo fuerza ══════════
def test_cambiar_el_corpus_fuerza_revalidacion():
    print("== B1.8) la revalidacion se salta si nada cambio, y se rehace si si ==")
    _limpia()
    reglas.registrar_catalogo(_catalogo_falso)
    reglas.registrar_arbitro(_arbitro_falso)
    corpus = _corpus_de_juguete()
    md = corpus / "falsa" / "SKILL.md"
    skills_real = reglas.config.SKILLS_DIR
    try:
        reglas.config.SKILLS_DIR = corpus
        sana = _regla(id="r-sana", estado="activa",
                      patron=r"^\s*cierra\s+el\s+navegador\s*$")
        reglas.ruta_almacen().parent.mkdir(parents=True, exist_ok=True)
        reglas.ruta_almacen().write_text(
            json.dumps({"esquema": reglas.ESQUEMA, "reglas": [sana]}, ensure_ascii=False),
            encoding="utf-8")

        # SE CUENTAN BARRIDOS, NO RESULTADOS. El resultado es identico las tres
        # veces: mirandolo no se ve si el trabajo se ha hecho una vez o tres, y
        # esta prueba estaria mirando un escalon por debajo.
        reglas.activas()
        n1 = reglas.barridos()
        check(n1 >= 1, "la primera consulta no ha barrido nada")
        reglas.activas()
        reglas.activas()
        check(reglas.barridos() == n1,
              f"sin cambiar nada se vuelve a barrer: {reglas.barridos()} vs {n1}")

        # Cambia el corpus (una skill instalada, un SKILL.md editado) -> se rehace.
        os.utime(md, (time.time() + 10, time.time() + 10))
        reglas.activas()
        check(reglas.barridos() == n1 + 1,
              f"tocar un SKILL.md no fuerza la revalidacion: {reglas.barridos()} vs {n1}")

        # Y cambiar el conjunto de reglas tambien.
        otra = _regla(id="r-dos", estado="activa",
                      patron=r"^\s*apaga\s+el\s+navegador\s*$")
        reglas.ruta_almacen().write_text(
            json.dumps({"esquema": reglas.ESQUEMA, "reglas": [sana, otra]},
                       ensure_ascii=False), encoding="utf-8")
        reglas.activas()
        check(reglas.barridos() == n1 + 2,
              f"anadir una regla no fuerza la revalidacion: {reglas.barridos()}")
    finally:
        reglas.config.SKILLS_DIR = skills_real
        _limpia()


# ══════════ orden determinista entre reglas activas ══════════
def test_gana_la_activada_mas_reciente():
    print("== el orden entre reglas activas no depende del fichero ==")
    _limpia()
    reglas.registrar_catalogo(_catalogo_falso)
    reglas.registrar_arbitro(_arbitro_falso)
    corpus = _corpus_de_juguete()
    skills_real = reglas.config.SKILLS_DIR
    try:
        reglas.config.SKILLS_DIR = corpus
        vieja = _regla(id="r-vieja", estado="activa",
                       patron=r"^\s*cierra\s+el\s+navegador\s*$",
                       activada="2026-08-01T10:00:00")
        nueva = _regla(id="r-nueva", estado="activa",
                       patron=r"^\s*cierra\s+el\s+navegador\s*$",
                       activada="2026-08-04T10:00:00")
        for orden in ([vieja, nueva], [nueva, vieja]):
            reglas.olvida_huella()
            reglas.ruta_almacen().parent.mkdir(parents=True, exist_ok=True)
            reglas.ruta_almacen().write_text(
                json.dumps({"esquema": reglas.ESQUEMA, "reglas": orden},
                           ensure_ascii=False), encoding="utf-8")
            ids = [r["id"] for r in reglas.activas()]
            check(ids and ids[0] == "r-nueva",
                  f"con el fichero en orden {[r['id'] for r in orden]} gana {ids}")
    finally:
        reglas.config.SKILLS_DIR = skills_real
        _limpia()


# ══════════ el cache del corpus no confunde dos catalogos ══════════
def test_el_cache_del_corpus_no_confunde_dos_carpetas():
    print("== dos SKILLS_DIR distintos no comparten el corpus cacheado ==")
    _limpia()
    # LA CLAVE DEL CACHE TIENE QUE IDENTIFICAR EL CATALOGO, NO SOLO MEDIRLO.
    #
    # Era `(cuantos SKILL.md, mtime mayor)`. En Windows el reloj del sistema
    # tiene ~15,6 ms de resolucion, asi que dos ficheros escritos seguidos
    # comparten `mtime` casi la mitad de las veces: medido, 90 colisiones por
    # cada 200 pares. Con el mismo numero de SKILL.md eso era LA MISMA CLAVE
    # para dos catalogos distintos, y el segundo recibia las frases del primero.
    #
    # Los `mtime` se igualan A MANO en vez de confiar en el reloj: asi el caso
    # es determinista en vez de saltar una de cada dos ejecuciones, que es
    # exactamente la clase de fallo que nadie termina de creerse.
    a = _corpus_con(["apaga la tele", "crea una tarea"])
    b = _corpus_con(["arrastre uno de prueba", "arrastre dos de prueba"])
    t = (a / "falsa" / "SKILL.md").stat().st_mtime
    os.utime(b / "falsa" / "SKILL.md", (t, t))
    check((a / "falsa" / "SKILL.md").stat().st_mtime
          == (b / "falsa" / "SKILL.md").stat().st_mtime,
          "los dos SKILL.md no han quedado con el mismo mtime: el caso no monta "
          "la colision que dice montar")

    skills_real = reglas.config.SKILLS_DIR
    try:
        reglas.config.SKILLS_DIR = a
        de_a = reglas.corpus_prometido()
        reglas.config.SKILLS_DIR = b
        de_b = reglas.corpus_prometido()
        check(de_a == ["apaga la tele", "crea una tarea"],
              f"el primer catalogo no sale entero: {de_a}")
        check(de_b == ["arrastre uno de prueba", "arrastre dos de prueba"],
              f"el segundo catalogo ha recibido las frases del primero: {de_b}")

        # Y editar un SKILL.md SIN mover su mtime tampoco puede colar el corpus
        # viejo: un editor que conserva la marca de tiempo existe, y el tamanno
        # es lo unico que delata el cambio sin abrir el fichero.
        md_b = b / "falsa" / "SKILL.md"
        md_b.write_text("# Falsa\n\n- «arrastre uno de prueba» → algo\n", encoding="utf-8")
        os.utime(md_b, (t, t))
        check(reglas.corpus_prometido() == ["arrastre uno de prueba"],
              f"editar un SKILL.md sin tocar su mtime deja el corpus viejo: "
              f"{reglas.corpus_prometido()}")
    finally:
        reglas.config.SKILLS_DIR = skills_real
        _limpia()


def test_el_cache_del_corpus_nunca_se_lee_a_medias():
    print("== el cache del corpus se publica de una pieza, no en dos pasos ==")
    _limpia()
    # LA PUBLICACION ES DE UN SOLO OBJETO. Se escribia `cache["clave"] = clave`
    # y DESPUES `cache["pares"] = pares`: entre las dos lineas, otro hilo veia
    # la clave NUEVA con las frases VIEJAS y se las creia sin volver a extraer.
    # nexus es un proceso con varios hilos y `corpus_prometido()` no corre bajo
    # el candado del almacen, asi que la ventana es real.
    import threading as _th

    a = _corpus_con(["apaga la tele", "crea una tarea"])
    b = _corpus_con(["arrastre uno de prueba", "arrastre dos de prueba"])
    t = (a / "falsa" / "SKILL.md").stat().st_mtime
    os.utime(b / "falsa" / "SKILL.md", (t, t))
    esperados = (["apaga la tele", "crea una tarea"],
                 ["arrastre uno de prueba", "arrastre dos de prueba"])

    skills_real = reglas.config.SKILLS_DIR
    raros: list[list] = []
    hilos: list = []
    parar = _th.Event()
    try:
        # El catalogo se apunta ANTES de arrancar a nadie: si los lectores
        # empiezan mirando el SKILLS_DIR de produccion, lo que se mediria es
        # una carrera de este banco de pruebas y no la del cache.
        reglas.config.SKILLS_DIR = b
        reglas.corpus_prometido()

        def _lee():
            while not parar.is_set():
                salida = reglas.corpus_prometido()
                if salida not in esperados:
                    raros.append(list(salida)[:3])

        hilos[:] = [_th.Thread(target=_lee, daemon=True) for _ in range(4)]
        for h in hilos:
            h.start()
        for i in range(2000):
            reglas.config.SKILLS_DIR = a if i % 2 else b
        parar.set()
        for h in hilos:
            h.join(5)
        check(not raros,
              f"un lector ha visto un corpus que no es ninguno de los dos "
              f"({len(raros)} veces): {raros[:2]}")
    finally:
        parar.set()
        for h in hilos:
            h.join(5)
        reglas.config.SKILLS_DIR = skills_real
        _limpia()


def main() -> int:
    for f in (test_revertida_no_vuelve_a_activa,
              test_puerta_campos_nombra_el_que_falta,
              test_destino_inexistente_y_rango_fuera,
              test_puerta_forma_rechaza_cuantificador_anidado,
              test_estado_activa_escrito_a_mano_no_activa,
              test_una_regla_podrida_no_invalida_las_sanas,
              test_esquema_futuro_no_activa_nada,
              test_cambiar_el_corpus_fuerza_revalidacion,
              test_gana_la_activada_mas_reciente,
              test_el_cache_del_corpus_no_confunde_dos_carpetas,
              test_el_cache_del_corpus_nunca_se_lee_a_medias):
        try:
            f()
        except Exception as e:                             # noqa: BLE001
            import traceback
            _fail.append(f"EXCEPCION en {f.__name__}: {type(e).__name__}: {e}")
            print("  ✖ EXCEPCION en", f.__name__, ":", type(e).__name__, e)
            traceback.print_exc()
    print(f"\n{'#' * 54}\ntest_reglas_contrato: {_pass} OK, {len(_fail)} fallos")
    for m in _fail:
        print("  -", m)
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
