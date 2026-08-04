# -*- coding: utf-8 -*-
"""Bloque B de 004: la puerta de no robo, medida ejecutando y no razonando.

QUE SE PRUEBA AQUI. Que una regla aprendida no puede quitarle una frase a nadie.
No se prueba leyendo el patron ni pidiendole una explicacion a un modelo: se
ejecuta `brain.quien_atiende()` sobre el corpus entero SIN la regla y CON la
regla, y se comparan los dos resultados frase a frase. La unica transicion
admitida es `planificador → regla:<id>`.

Y hay una segunda mitad, que es la que de verdad sostiene el cambio: el robo no
se detecta, es INALCANZABLE. En `quien_atiende()` el escalon de las reglas esta
DESPUES de `route()`, que sale con `return` en cuanto una skill casa. Si el
router contesto, el codigo de las reglas no llega a ejecutarse. Por eso hay un
caso con una regla escrita a proposito para robar «apaga la tele»: no se
comprueba que se rechace, se comprueba que no pasa nada.

DIVERGENCIA DECLARADA, Y VA AQUI Y NO EN UN FICHERO QUE NADIE ABRA.
`quien_atiende()` NO modela `_learn_lookup()` ni `rag.find_task()`
(`brain.py`, rama `routed is None`). Las dos pueden cambiar el destino de una
frase, y el barrido de esta puerta no lo ve. Se deja fuera a proposito:
`find_task` es asincrona y llama a embeddings, y `quien_atiende` tiene que
seguir siendo sincrona, sin red y sin efectos. O sea que esta suite mira, para
esas dos, un escalon por debajo de donde se decide — dicho aqui en vez de
disimulado. El riesgo residual es que una frase que hoy resuelve
`_learn_lookup()` acabe atendida por una regla; no es robo a una skill, pero
tampoco es el hueco del planificador.

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_aprendizaje_no_robo.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("NEXUS_DATA_DIR", tempfile.mkdtemp(prefix="nexus_norobo_"))

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


from backend.core.aplicacion import aprendizaje             # noqa: E402
from backend.core.aplicacion import brain                   # noqa: E402
from backend.core.aplicacion import skills_loader as sl     # noqa: E402
from backend.core.dominio import reglas                     # noqa: E402

sl.load_skills()
aprendizaje.registrar()
reglas.registrar_arbitro(brain.quien_atiende)

# Una frase que hoy no atiende NADIE. Se comprueba, no se supone: si algun dia
# una skill la caza, el caso de abajo dejaria de probar lo que dice probar.
HUECO = "tramoya de prueba para el barrido"
PATRON_HUECO = r"^\s*tramoya\s+de\s+prueba\s+para\s+el\s+barrido\s*$"


def _limpia() -> None:
    p = reglas.ruta_almacen()
    for f in (p, p.with_name(p.name + ".bak"), p.with_name(p.name + ".tmp")):
        try:
            f.unlink()
        except Exception:                                  # noqa: BLE001
            pass
    reglas.olvida_huella()


def _regla(**cambios) -> dict:
    r = {"id": "r-hueco", "esquema": reglas.ESQUEMA, "tipo": "enrutado", "revision": 1,
         "origen": {"frase": HUECO, "canal": "pc", "fecha": "2026-08-04T10:00:00",
                    "tipo": "ordenada", "veces": 1},
         "destino": "tasks_board/create", "patron": PATRON_HUECO,
         "evidencia": {"arrastradas": [], "suite": None},
         "estado": "propuesta"}
    r.update(cambios)
    return r


def _corpus_de_juguete(frases: list[str]) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="nexus_corpus_"))
    (tmp / "falsa").mkdir()
    (tmp / "falsa" / "SKILL.md").write_text(
        "# Falsa\n\n" + "".join(f"- «{f}» → algo\n" for f in frases), encoding="utf-8")
    return tmp


def _config_de_juguete() -> Path:
    """Una carpeta de configuracion CON su corpus de regresion dentro.

    La puerta de no robo exige el catalogo ENTERO: si falta la mitad de
    regresion, deniega y lo dice. Un banco de pruebas que solo monta los
    SKILL.md deja el catalogo a medias, y entonces lo que mide el test no es lo
    que dice su nombre — mide la denegacion por catalogo incompleto."""
    tmp = Path(tempfile.mkdtemp(prefix="nexus_cfg_"))
    (tmp / "corpus_regresion.json").write_text(
        json.dumps({"frases": [{"frase": "hola", "duenno": "charla"}]},
                   ensure_ascii=False), encoding="utf-8")
    return tmp


# ══════════ B2.1 · el corpus de produccion es el mismo que el de la suite ══════════
def test_corpus_prometido_255_distintas():
    print("== B2.1) corpus_prometido() saca las 255 frases de los SKILL.md ==")
    frases = reglas.corpus_prometido()
    check(len(frases) == 255,
          f"corpus_prometido() devuelve {len(frases)} frases distintas, no 255: "
          "si has anadido o quitado ordenes de un SKILL.md, actualiza esta cifra")
    check(len(set(frases)) == len(frases), "corpus_prometido() devuelve repetidas")
    check(len(reglas.corpus_prometido(con_origen=True)) == 259,
          "con_origen=True ya no devuelve las 259 apariciones (una orden puede "
          "estar documentada en dos skills a proposito)")
    check("pon la tele" in frases,
          "una frase que domotica/SKILL.md promete no esta en el corpus")
    # Y el corpus COMPLETO suma las de regresion, que los SKILL.md no prometen.
    completo = reglas.corpus_completo()
    check("apaga la tele" in completo and "apaga la tele" not in frases,
          "«apaga la tele» solo esta en el corpus de regresion: si aparece en los "
          "dos o en ninguno, este caso deja de distinguir las dos fuentes")
    check(len(completo) > len(frases),
          f"el corpus completo ({len(completo)}) no suma las de regresion a las "
          f"prometidas ({len(frases)})")

    # Y la suite que vigila lo prometido usa ESTE extractor, no una copia suya.
    src = (ROOT / "tests" / "test_lo_prometido.py").read_text(encoding="utf-8")
    check("reglas.corpus_prometido" in src,
          "test_lo_prometido.py ha vuelto a tener extractor propio: dos extractores "
          "pueden discrepar sin que nadie se entere")


def test_corpus_regresion_esta_en_el_spec():
    print("== B2.4) el catalogo viaja en el instalador, y data/ no ==")
    spec = (ROOT / "installer" / "nexus.spec").read_text(encoding="utf-8")
    datas = spec[spec.find("datas=["):spec.find("hiddenimports=")]
    check("corpus_regresion.json" in datas,
          "config/corpus_regresion.json no esta en «datas» de installer/nexus.spec: "
          "en la maquina del usuario la puerta de no robo mediria contra menos frases")
    # Y lo aprendido NO viaja: `data/` es del usuario y puede llevar sus frases.
    import re as _re
    check(_re.search(r"ROOT\s*/\s*['\"]data['\"]", datas) is None,
          "«data/» aparece en «datas» del spec: se estaria empaquetando lo que el "
          "usuario ha aprendido, incluida la frase literal con la que corrigio")

    corpus = reglas.corpus_regresion()
    check(len(corpus) >= 30,
          f"corpus_regresion() lee solo {len(corpus)} frases de config/")
    check(all(e.get("frase") for e in corpus), "hay entradas sin frase en el corpus")


# ══════════ B2.5 · sin catalogo, ninguna regla se activa ══════════
def test_sin_catalogo_ninguna_regla_activa():
    print("== B2.5) sin catalogo de frases NINGUNA regla se activa ==")
    _limpia()
    vacio = Path(tempfile.mkdtemp(prefix="nexus_sin_skills_"))
    cfg_vacio = Path(tempfile.mkdtemp(prefix="nexus_sin_cfg_"))
    skills_real, cfg_real = reglas.config.SKILLS_DIR, reglas.config.CONFIG_DIR
    try:
        reglas.config.SKILLS_DIR = vacio
        reglas.config.CONFIG_DIR = cfg_vacio
        check(reglas.corpus_completo() == [],
              "con SKILLS_DIR vacio y sin corpus_regresion.json el corpus no sale vacio: "
              "el caso no esta probando lo que dice")
        ok, motivo = reglas.valida(_regla())
        check(ok is False, "sin catalogo de frases la regla pasa la validacion")
        check("catalogo" in motivo.lower() or "ciegas" in motivo.lower(),
              f"el motivo no dice que falta el catalogo: «{motivo}»")

        # Y una escrita a mano como activa tampoco entra.
        reglas.ruta_almacen().parent.mkdir(parents=True, exist_ok=True)
        reglas.ruta_almacen().write_text(
            json.dumps({"esquema": reglas.ESQUEMA, "reglas": [_regla(estado="activa")]},
                       ensure_ascii=False), encoding="utf-8")
        check(reglas.activas() == [],
              "sin catalogo instalado sigue habiendo reglas activas: validar a ciegas "
              "es peor que no aprender")
        # Y NO se marca invalida: no se puede juzgar, no es que este mal.
        en_disco = reglas.cargar()["reglas"][0]["estado"]
        check(en_disco == "activa",
              f"una regla buena se ha condenado a «{en_disco}» porque faltaba el catalogo")
    finally:
        reglas.config.SKILLS_DIR = skills_real
        reglas.config.CONFIG_DIR = cfg_real
        reglas.config.CONFIG_DIR = cfg_real
        _limpia()


# ══════════ B3.3 · la regla ladrona se descarta NOMBRANDO la frase ══════════
def test_regla_ladrona_se_descarta_nombrando_la_frase():
    print("== B3.3) una regla que roba se descarta diciendo QUE frase roba ==")
    _limpia()
    # Un arbitro que SI deja robar: es la unica forma de probar que la puerta
    # detecta el robo. Con el `quien_atiende` de verdad esto es inalcanzable, y
    # eso se prueba aparte, mas abajo.
    frases = ["apaga la tele", "crea una tarea", HUECO]
    corpus = _corpus_de_juguete(frases)

    def _arbitro_permisivo(frase, channel="pc", reglas=None):
        # El `return` iba DENTRO del bucle y en la primera vuelta, asi que con
        # dos reglas la segunda no se miraba nunca. Justo en el helper que
        # sostiene la prueba de que el robo es inalcanzable.
        import re as _re
        for r in (reglas or ()):
            if _re.search(r.get("patron", ""), frase, _re.IGNORECASE):
                return f"regla:{r.get('id')}"
        return "skill:domotica/tv_off" if frase == "apaga la tele" else "planificador"

    skills_real, cfg_real = reglas.config.SKILLS_DIR, reglas.config.CONFIG_DIR
    try:
        reglas.config.SKILLS_DIR = corpus
        reglas.config.CONFIG_DIR = _config_de_juguete()
        reglas.registrar_arbitro(_arbitro_permisivo)
        ladrona = _regla(id="r-ladrona", patron=r"^\s*apaga\s+la\s+tele\s*$",
                         origen={"frase": "apaga la tele", "canal": "pc",
                                 "fecha": "2026-08-04T10:00:00"})
        b = aprendizaje.barrido(ladrona)
        check(any("apaga la tele" in str(x) for x in b["robadas"]),
              f"el barrido no ve el robo de «apaga la tele»: {b}")
        ok, motivo = reglas.valida(ladrona)
        check(ok is False, "una regla que roba una frase pasa la validacion")
        check("apaga la tele" in motivo,
              f"el motivo no NOMBRA la frase robada, y sin eso no se puede juzgar: «{motivo}»")
        check("skill:domotica/tv_off" in motivo,
              f"el motivo no dice quien la atendia: «{motivo}»")
    finally:
        reglas.config.SKILLS_DIR = skills_real
        reglas.config.CONFIG_DIR = cfg_real
        reglas.registrar_arbitro(brain.quien_atiende)
        _limpia()


# ══════════ B3.4 · la regla ancha se descarta CON el listado ══════════
def test_arrastre_por_encima_del_tope_se_descarta():
    print("== B3.4) una regla demasiado ancha se descarta con el listado ==")
    _limpia()
    frases = ["arrastre uno de prueba", "arrastre dos de prueba",
              "arrastre tres de prueba", "arrastre cuatro de prueba"]
    corpus = _corpus_de_juguete(frases)

    def _arbitro_hueco(frase, channel="pc", reglas=None):
        import re as _re
        for r in (reglas or ()):
            if _re.search(r.get("patron", ""), frase, _re.IGNORECASE):
                return f"regla:{r.get('id')}"
        return "planificador"

    skills_real, cfg_real = reglas.config.SKILLS_DIR, reglas.config.CONFIG_DIR
    try:
        reglas.config.SKILLS_DIR = corpus
        reglas.config.CONFIG_DIR = _config_de_juguete()
        reglas.registrar_arbitro(_arbitro_hueco)
        # Casa con las cuatro: `tope_frases_arrastradas` son 2.
        ancha = _regla(id="r-ancha", patron=r"^\s*arrastre\s+\w+\s+de\s+prueba\s*$",
                       origen={"frase": "arrastre uno de prueba", "canal": "pc",
                               "fecha": "2026-08-04T10:00:00"})
        b = aprendizaje.barrido(ancha)
        check(len(b["arrastradas"]) == 4,
              f"el barrido no ve las cuatro frases arrastradas: {b['arrastradas']}")
        ok, motivo = reglas.valida(ancha)
        check(ok is False, "una regla que arrastra media lista pasa la validacion")
        check("arrastre dos de prueba" in motivo and "arrastre tres de prueba" in motivo,
              f"el motivo es un booleano disfrazado: no lista el arrastre: «{motivo}»")

        # Y una estrecha, en el MISMO montaje, si pasa: asi se ve que el corte es
        # el tope y no que todo se rechace.
        estrecha = _regla(id="r-estrecha", patron=r"^\s*arrastre\s+uno\s+de\s+prueba\s*$",
                          origen={"frase": "arrastre uno de prueba", "canal": "pc",
                                  "fecha": "2026-08-04T10:00:00"})
        ok, motivo = reglas.valida(estrecha)
        check(ok is True, f"una regla que solo casa con su propia frase se rechaza: «{motivo}»")
    finally:
        reglas.config.SKILLS_DIR = skills_real
        reglas.config.CONFIG_DIR = cfg_real
        reglas.registrar_arbitro(brain.quien_atiende)
        _limpia()


# ══════════ B3.5 · el presupuesto de tiempo ══════════
def test_barrido_lento_descarta_la_regla():
    print("== B3.5) un barrido por encima del presupuesto descarta la regla ==")
    _limpia()
    frases = [f"lentitud numero {i} de prueba" for i in range(5)]
    corpus = _corpus_de_juguete(frases)

    def _arbitro_lento(frase, channel="pc", reglas=None):
        # 5 ms por consulta: 5 frases x 2 barridos = ~50 ms medidos, no estimados.
        time.sleep(0.005)
        return "planificador"

    # Con corpus de regresion DENTRO: si no, la puerta deniega por catalogo
    # incompleto antes de llegar a medir el tiempo, y este test mediria eso.
    cfg = _config_de_juguete()
    skills_real, cfg_real = reglas.config.SKILLS_DIR, reglas.config.CONFIG_DIR
    try:
        reglas.config.SKILLS_DIR = corpus
        reglas.config.CONFIG_DIR = cfg
        reglas.registrar_arbitro(_arbitro_lento)
        lenta = _regla(id="r-lenta", origen={"frase": "lentitud numero 0 de prueba",
                                             "canal": "pc",
                                             "fecha": "2026-08-04T10:00:00"})

        (cfg / "umbrales.json").write_text(
            json.dumps({"aprendizaje": {"presupuesto_ms_barrido": 10}}), encoding="utf-8")
        ok, motivo = reglas.valida(lenta)
        check(ok is False, "un barrido de ~50 ms pasa con un presupuesto de 10 ms")
        check("presupuesto" in motivo.lower() and "ms" in motivo.lower(),
              f"el motivo no dice que se ha pasado de tiempo: «{motivo}»")

        # La MISMA regla, con presupuesto holgado, pasa: el corte es el tiempo y
        # no otra cosa que se estuviera colando en el veredicto.
        (cfg / "umbrales.json").write_text(
            json.dumps({"aprendizaje": {"presupuesto_ms_barrido": 60000}}), encoding="utf-8")
        ok, motivo = reglas.valida(lenta)
        check(ok is True, f"con presupuesto de 60 s la misma regla sigue cayendo: «{motivo}»")
    finally:
        reglas.config.SKILLS_DIR = skills_real
        reglas.config.CONFIG_DIR = cfg_real
        reglas.config.CONFIG_DIR = cfg_real
        reglas.registrar_arbitro(brain.quien_atiende)
        _limpia()


# ══════════ B4.2 · la unica transicion admitida ══════════
def test_solo_transicion_planificador_a_regla():
    print("== B4.2) toda frase que cambia lo hace de planificador a regla:<id> ==")
    _limpia()
    check(brain.quien_atiende(HUECO) == "planificador",
          f"«{HUECO}» ya la atiende alguien ({brain.quien_atiende(HUECO)}): "
          "este caso dejaria de probar lo que dice probar")

    corpus = reglas.corpus_completo()
    check(len(corpus) > 250, f"el corpus completo son {len(corpus)} frases, esperaba >250")
    antes = {f: brain.quien_atiende(f, reglas=()) for f in corpus}

    regla = _regla(estado="activa")
    despues = {f: brain.quien_atiende(f, reglas=(regla,)) for f in corpus}

    for f in corpus:
        if antes[f] == despues[f]:
            continue
        check(antes[f] == "planificador" and despues[f] == "regla:r-hueco",
              f"«{f}» pasa de {antes[f]} a {despues[f]}: la unica transicion "
              "admitida es planificador → regla:<id>")

    # Y la frase objetivo si cambia: sin esto el caso pasaria con una regla que
    # no hace nada, que es exactamente un verde que no prueba nada.
    check(brain.quien_atiende(HUECO, reglas=()) == "planificador",
          "con reglas=() la frase del hueco ya no cae al planificador")
    check(brain.quien_atiende(HUECO, reglas=(regla,)) == "regla:r-hueco",
          "con la regla activa la frase del hueco no pasa a regla:<id>")

    # `regla:<id>` y no `skill:carpeta/intent`: una regla aprendida no puede ser
    # indistinguible del enrutado nativo. El destino se recupera por el id.
    reglas.guardar(regla)
    check(reglas.destino_de("r-hueco") == "tasks_board/create",
          f"no se puede recuperar el destino de una regla por su id: "
          f"«{reglas.destino_de('r-hueco')}»")
    check(reglas.destino_de("r-que-no-existe") == "",
          "destino_de() se inventa un destino para un id que no existe")

    # `reglas=None` con el almacen vacio = ninguna regla = fabrica exacta.
    for f in corpus[:40]:
        check(brain.quien_atiende(f) == antes[f],
              f"«{f}» cambia de dueno con el almacen vacio: {brain.quien_atiende(f)}")
    _limpia()


def test_el_robo_es_inalcanzable_no_rechazado():
    print("== B4.2) si el router contesto, el codigo de las reglas NO se ejecuta ==")
    _limpia()
    ladrona = {"id": "r-ladrona", "esquema": reglas.ESQUEMA, "tipo": "enrutado",
               "revision": 1,
               "origen": {"frase": "apaga la tele", "canal": "pc",
                          "fecha": "2026-08-04T10:00:00"},
               "destino": "tasks_board/create",
               "patron": r"^\s*apaga\s+la\s+tele\s*$",
               "evidencia": {"arrastradas": [], "suite": None}, "estado": "activa"}

    # Se le pasa a la fuerza, sin pasar por ninguna puerta: aunque una regla asi
    # llegara a estar activa, no puede quitarle la frase a la skill.
    for frase, dueno in (("apaga la tele", "skill:domotica/tv_off"),
                         ("hola", "charla"),
                         ("no te he dicho que leas los correos", "queja"),
                         ("apunta que me gusta el café solo", "memoria")):
        atajo = {"id": "r-atajo", "esquema": reglas.ESQUEMA, "tipo": "enrutado",
                 "revision": 1,
                 "origen": {"frase": frase, "canal": "pc",
                            "fecha": "2026-08-04T10:00:00"},
                 "destino": "tasks_board/create",
                 "patron": r"^.{1,80}$",          # casa con todo: da igual
                 "evidencia": {"arrastradas": [], "suite": None}, "estado": "activa"}
        check(brain.quien_atiende(frase, reglas=(ladrona, atajo)) == dueno,
              f"«{frase}» deja de ser {dueno} con reglas activas: el escalon de las "
              "reglas NO esta detras del router y de los atajos")

    # Y se lee en el codigo, que es donde tiene que verse sin ejecutar nada.
    src = (ROOT / "backend" / "core" / "aplicacion" / "brain.py").read_text(encoding="utf-8")
    cuerpo = src[src.find("def quien_atiende"):src.find("\ndef ", src.find("def quien_atiende") + 10)]
    i_router = cuerpo.find("r = route(t)")
    i_regla = cuerpo.find("_regla_que_casa")
    check(i_router != -1 and i_regla != -1 and i_router < i_regla,
          "en quien_atiende() las reglas no van despues de route(): "
          f"router en {i_router}, reglas en {i_regla}")
    check(cuerpo.find("_META_QUEJA_RX") < i_regla,
          "las reglas se consultan antes de la meta-queja")
    _limpia()


def test_una_regla_valor_no_enruta():
    print("== una regla de tipo «valor» no mueve a nadie ==")
    _limpia()
    corpus = reglas.corpus_completo()
    antes = {f: brain.quien_atiende(f, reglas=()) for f in corpus}
    rv = {"id": "r-valor", "esquema": reglas.ESQUEMA, "tipo": "valor", "revision": 1,
          "origen": {"frase": "de prueba", "canal": "pc", "fecha": "2026-08-04T10:00:00"},
          "destino": "domotica.room_words", "valor": [f"palabra{i}" for i in range(8)],
          "evidencia": {"arrastradas": [], "suite": None}, "estado": "activa"}
    distintas = [f for f in corpus if brain.quien_atiende(f, reglas=(rv,)) != antes[f]]
    check(not distintas,
          f"activar una regla «valor» cambia el dueno de {len(distintas)} frases: {distintas[:3]}")
    _limpia()


# ══════════ B4.4 · la hermeticidad que ya estaba, y que no se puede quitar ══════════
def test_las_suites_de_enrutado_aislan_data_dir():
    print("== B4.4) las suites de enrutado siguen aislando NEXUS_DATA_DIR ==")
    for nombre in ("test_regresion_conversacion.py", "test_lo_prometido.py"):
        src = (ROOT / "tests" / nombre).read_text(encoding="utf-8")
        i = src.find("NEXUS_DATA_DIR")
        check(i != -1,
              f"{nombre} ya no aisla NEXUS_DATA_DIR: mira los datos REALES de la "
              "maquina y dice una cosa distinta en cada equipo")
        check("mkdtemp" in src[max(0, i - 200):i + 200],
              f"{nombre} nombra NEXUS_DATA_DIR pero no lo apunta a una carpeta temporal")
        # Y el aislamiento va ANTES del primer import de backend: `comun/config`
        # resuelve DATA_DIR al importarse, asi que ponerlo despues llega tarde.
        primer_import = src.find("from backend.core")
        check(primer_import == -1 or i < primer_import,
              f"{nombre} importa backend en la linea {src[:primer_import].count(chr(10)) + 1}, "
              "antes de aislar NEXUS_DATA_DIR: config ya ha resuelto DATA_DIR")


def main() -> int:
    for f in (test_corpus_prometido_255_distintas,
              test_corpus_regresion_esta_en_el_spec,
              test_sin_catalogo_ninguna_regla_activa,
              test_regla_ladrona_se_descarta_nombrando_la_frase,
              test_arrastre_por_encima_del_tope_se_descarta,
              test_barrido_lento_descarta_la_regla,
              test_solo_transicion_planificador_a_regla,
              test_el_robo_es_inalcanzable_no_rechazado,
              test_una_regla_valor_no_enruta,
              test_las_suites_de_enrutado_aislan_data_dir):
        try:
            f()
        except Exception as e:                             # noqa: BLE001
            import traceback
            _fail.append(f"EXCEPCION en {f.__name__}: {type(e).__name__}: {e}")
            print("  ✖ EXCEPCION en", f.__name__, ":", type(e).__name__, e)
            traceback.print_exc()
    print(f"\n{'#' * 54}\ntest_aprendizaje_no_robo: {_pass} OK, {len(_fail)} fallos")
    for m in _fail:
        print("  -", m)
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
