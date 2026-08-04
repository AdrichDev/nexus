# -*- coding: utf-8 -*-
"""Bloque B de 004: la puerta 5 no existe en casa del usuario, y se dice.

En la maquina de otra persona no hay `tests/`, asi que `run_all.py` no se puede
ejecutar y la puerta de suite NO CORRE. Lo que se prueba aqui es que tampoco se
marca como superada: alli activan CUATRO puertas, no cinco, y la auditoria lo
dice con esas palabras. Fingir lo contrario seria exactamente lo unico que este
proyecto no negocia.

OJO A DONDE MIRA ESTE FICHERO. La comprobacion lee la AUDITORIA, no el campo
`evidencia.suite` de la regla. Ese campo es texto que cualquiera puede escribir
en `data/reglas_aprendidas.json`; leerlo seria mirar un escalon por debajo del
fallo, y un `"suite": true` escrito a mano dejaria la prueba en verde.

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_aprendizaje_puertas.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("NEXUS_DATA_DIR", tempfile.mkdtemp(prefix="nexus_puertas_"))

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
from backend.core.comun import audit                        # noqa: E402
from backend.core.dominio import reglas                     # noqa: E402


def _regla(**cambios) -> dict:
    r = {"id": "r-suite", "esquema": reglas.ESQUEMA, "tipo": "enrutado", "revision": 1,
         "origen": {"frase": "tramoya de prueba", "canal": "pc",
                    "fecha": "2026-08-04T10:00:00", "tipo": "ordenada", "veces": 1},
         "destino": "tasks_board/create",
         "patron": r"^\s*tramoya\s+de\s+prueba\s*$",
         "evidencia": {"arrastradas": [], "suite": None},
         "estado": "propuesta"}
    r.update(cambios)
    return r


# ══════════ B3.7 · la puerta de suite nunca se da por superada ══════════
def test_puerta_suite_nunca_se_marca_superada_sola():
    print("== B3.7) la puerta 5 se registra «no_aplicable», la escriba quien la escriba ==")

    # Una regla con la evidencia MANIPULADA: alguien ha escrito «suite: true» a
    # mano en el fichero. La auditoria tiene que seguir diciendo la verdad.
    mentirosa = _regla(evidencia={"arrastradas": [], "suite": True})
    veredicto = aprendizaje.puerta_suite(mentirosa)
    check(veredicto == "no_aplicable",
          f"puerta_suite() devuelve «{veredicto}» con la evidencia manipulada")

    honesta = _regla(id="r-honesta")
    check(aprendizaje.puerta_suite(honesta) == "no_aplicable",
          "puerta_suite() no devuelve «no_aplicable» con la evidencia limpia")

    # SE LEE LA AUDITORIA, no la evidencia de la regla.
    trazas = [t for t in audit.tail(60) if t.get("action") == "puerta_suite"]
    check(len(trazas) >= 2, f"la puerta de suite no deja traza: {len(trazas)} lineas")
    de_la_mentirosa = [t for t in trazas if "r-suite" in (t.get("targets") or [])]
    check(de_la_mentirosa and all(t.get("result") == "no_aplicable" for t in de_la_mentirosa),
          f"la auditoria da por superada la puerta de suite: {de_la_mentirosa[-1:]!r}")
    check(all("no hay" in (t.get("error") or "").lower()
              or "tests" in (t.get("error") or "").lower() for t in de_la_mentirosa),
          "la auditoria no explica POR QUE la puerta no aplica")

    # Y `valida()` sigue sin incluirla: cuatro puertas, no cinco.
    src = (ROOT / "backend" / "core" / "dominio" / "reglas.py").read_text(encoding="utf-8")
    cuerpo = src[src.find("_PUERTAS = ("):src.find("\n", src.find("_PUERTAS = ("))]
    check("suite" not in cuerpo,
          f"la puerta de suite se ha colado en la cadena de validacion: {cuerpo}")
    check(cuerpo.count("_puerta_") == 4,
          f"la cadena de validacion no tiene exactamente cuatro puertas: {cuerpo}")


# ══════════ B3.1/B3.2 · el modulo respeta las capas ══════════
def test_aprendizaje_no_importa_brain():
    print("== B3.1) aprendizaje no importa brain: es brain quien se registra ==")
    src = (ROOT / "backend" / "core" / "aplicacion" / "aprendizaje.py").read_text(encoding="utf-8")
    sin_texto = re.sub(r'"""(?:.|\n)*?"""', " ", src)
    sin_texto = re.sub(r"#[^\n]*", " ", sin_texto)
    check("brain" not in sin_texto,
          "aprendizaje.py nombra a brain en codigo: un ciclo entre modulos de la "
          "misma capa obliga a importar dentro de la funcion y esconde la dependencia")
    check("skills_loader" in sin_texto,
          "aprendizaje.py ya no consulta skills_loader: sin el no sabe que destinos existen")

    # Y los dos modulos estan dados de alta en la suite de capas Y en CAPAS.md.
    capas = (ROOT / "tests" / "test_capas_backend.py").read_text(encoding="utf-8")
    doc = (ROOT / "backend" / "core" / "CAPAS.md").read_text(encoding="utf-8")
    for modulo in ("reglas", "aprendizaje"):
        check(f'"{modulo}"' in capas, f"«{modulo}» no esta en la lista CAPAS del test")
        check(f"`{modulo}`" in doc, f"«{modulo}» no esta en la tabla de CAPAS.md")
    check(capas.count("EXCEPCIONES: set") == 1 and capas.count('("llm", "llm_runtime")') == 1,
          "la lista de excepciones ha cambiado de forma")
    i = capas.find("EXCEPCIONES: set")
    bloque = capas[i:capas.find("}", i)]
    check(bloque.count("(\"") == 4,
          f"hay {bloque.count(chr(40) + chr(34))} excepciones en vez de las cuatro de "
          "siempre: este cambio no puede anadir deuda nueva")


# ══════════ B4.6 · nada personal en lo que se anade ══════════
def test_ficheros_nuevos_sin_datos_personales():
    print("== B4.6) ni un nombre, ni una IP, ni una MAC en los ficheros nuevos ==")
    nuevos = [
        ROOT / "backend" / "core" / "dominio" / "reglas.py",
        ROOT / "backend" / "core" / "aplicacion" / "aprendizaje.py",
        ROOT / "config" / "corpus_regresion.json",
        ROOT / "tests" / "test_reglas_valores.py",
        ROOT / "tests" / "test_reglas_contrato.py",
        ROOT / "tests" / "test_aprendizaje_no_robo.py",
        ROOT / "tests" / "test_aprendizaje_puertas.py",
    ]
    # Las palabras se arman por trozos: este fichero se escanea a si mismo y
    # escribirlas enteras lo pondria rojo por su propia guarda.
    prohibidas = ("ad" + "ri", "maq" + "ueda", "ach" + "oz")
    for f in nuevos:
        check(f.exists(), f"{f.name} no existe: la guarda no esta mirando nada")
        if not f.exists():
            continue
        txt = f.read_text(encoding="utf-8")
        for palabra in prohibidas:
            check(palabra not in txt.lower(),
                  f"«{palabra}» aparece en {f.name}: dato personal del duenno")
        ips = re.findall(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])", txt)
        check(not ips, f"IPs completas escritas en {f.name}: {ips[:3]}")
        macs = re.findall(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b", txt)
        check(not macs, f"MACs completas escritas en {f.name}: {macs[:3]}")

    # Y lo aprendido vive en data/, que esta excluido del repositorio.
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    check(re.search(r"^/?data/?\s*$", gitignore, re.MULTILINE) is not None,
          "«data/» ya no esta en .gitignore: la frase literal con la que el duenno "
          "corrigio acabaria en el repositorio")


def test_el_almacen_solo_escribe_dentro_de_data_dir():
    print("== el almacen no escribe fuera de DATA_DIR ==")
    tmp = Path(tempfile.mkdtemp(prefix="nexus_aislado_"))
    data_real = reglas.config.DATA_DIR
    try:
        reglas.config.DATA_DIR = tmp
        antes = {p.resolve() for p in tmp.rglob("*")}
        rid = reglas.guardar(_regla(id="r-aislada"))
        reglas.transitar(rid, "descartada", "prueba")
        nuevos = {p.resolve() for p in tmp.rglob("*") if p.is_file()} - antes
        nombres = sorted(p.name for p in nuevos)
        check(nombres and all(n.startswith("reglas_aprendidas.json") or n == "audit.jsonl"
                              for n in nombres),
              f"el almacen ha escrito ficheros que no esperaba: {nombres}")
        check((tmp / "reglas_aprendidas.json").exists(),
              "el almacen no ha escrito donde apunta NEXUS_DATA_DIR")
    finally:
        reglas.config.DATA_DIR = data_real


# ══════════ B3.8 · el barrido mira la forma ANTES de barrer ══════════
def test_el_barrido_no_ejecuta_un_patron_de_forma_peligrosa():
    print("== B3.8) barrido() rechaza la forma antes de correrla 289 veces ==")

    # `barrido()` es publica y se puede llamar suelta. Ejecutaba el patron
    # candidato contra todo el catalogo y SOLO DESPUES miraba el presupuesto de
    # tiempo: con retroceso catastrofico no llega nunca a mirarlo, porque se
    # cuelga antes. El presupuesto no protege de esto; mirar la forma si.
    for patron, pinta in ((r"^(a|ab)+$", "alternancia"),
                          (r"^(a+)+$", "anidado")):
        b = aprendizaje.barrido(_regla(patron=patron))
        check(b.get("abortado"), f"barrido() no aborta con {pinta}: {b.get('abortado')!r}")
        check(b["frases"] == 0,
              f"barrido() ha llegado a recorrer {b['frases']} frases con {pinta}")

    # Y la puerta 4 lo trata como fallo DE LA REGLA, no del entorno: hace falta
    # un arbitro registrado o la puerta sale antes de llegar al barrido.
    arbitro_real = reglas._arbitro
    try:
        reglas.registrar_arbitro(lambda frase, channel="pc", reglas=None: "planificador")
        ok, motivo, aislable = reglas._puerta_no_robo(_regla(patron=r"^(a|ab)+$"))
        check(ok is False, "la puerta 4 aprueba un patron que ni siquiera se puede barrer")
        check(aislable is True,
              "una forma peligrosa es culpa de la regla, no del entorno: tiene que aislarse")
    finally:
        reglas.registrar_arbitro(arbitro_real)


# ══════════ B3.9 · una skill rota no invalida la regla para siempre ══════════
def test_una_skill_rota_en_este_arranque_no_invalida_la_regla():
    print("== B3.9) destino averiado = cuarentena, destino ausente = invalida ==")

    ausente = _regla(id="r-ausente", destino="carpeta_que_no_existe/intent")
    catalogo_real, averia_real = reglas._catalogo, reglas._averia
    try:
        reglas.registrar_catalogo(lambda d: False)

        # 1) Sin averia: el destino no esta porque no esta. Culpa de la regla.
        reglas.registrar_averia(lambda d: False)
        ok, motivo, aislable = reglas._puerta_existencia(ausente)
        check(ok is False and aislable is True,
              f"un destino que de verdad falta tiene que aislarse: aislable={aislable}")
        check("no existe" in motivo, f"el motivo no dice que el destino falta: «{motivo}»")

        # 2) Con averia: la skill esta instalada pero ha reventado al cargar.
        #    Se deniega igual —no se activa nada a ciegas— pero NO se marca en
        #    disco, porque `invalida` no se deshace sola y la skill volvera.
        reglas.registrar_averia(lambda d: True)
        ok, motivo, aislable = reglas._puerta_existencia(ausente)
        check(ok is False, "una skill rota no puede aprobar la puerta de existencia")
        check(aislable is False,
              "una skill rota en este arranque marca la regla «invalida» PARA SIEMPRE")
        check("cuarentena" in motivo,
              f"el motivo no distingue la averia de la ausencia: «{motivo}»")
    finally:
        reglas.registrar_catalogo(catalogo_real)
        reglas.registrar_averia(averia_real)


# ══════════ B3.10 · dos hilos a la vez no se pisan la reentrada ══════════
def test_dos_hilos_no_se_roban_la_marca_de_reentrada():
    print("== B3.10) la marca de «ya estoy validando» es de cada hilo ==")
    import threading as _th

    # La marca existe para cortar el ciclo «barrido → arbitro → activas» DENTRO
    # de una misma pila. Siendo un global se contagiaba entre peticiones: el
    # hilo B veia la marca del hilo A y contestaba «ninguna regla activa». Lo
    # aprendido dejaba de aplicarse a ratos y sin dejar rastro.
    visto: list[bool] = []
    arrancado, suelta = _th.Event(), _th.Event()

    def _dentro_de_la_marca():
        reglas._reentrada.activo = True
        arrancado.set()
        suelta.wait(5)
        reglas._reentrada.activo = False

    hilo = _th.Thread(target=_dentro_de_la_marca, daemon=True)
    hilo.start()
    arrancado.wait(5)
    try:
        # Otro hilo, con la marca del primero puesta, tiene que ver la SUYA.
        def _mira():
            visto.append(bool(getattr(reglas._reentrada, "activo", False)))
        otro = _th.Thread(target=_mira, daemon=True)
        otro.start()
        otro.join(5)
    finally:
        suelta.set()
        hilo.join(5)

    check(visto == [False],
          f"un hilo ve la marca de reentrada de otro: {visto} (deberia ser [False])")


def main() -> int:
    for f in (test_puerta_suite_nunca_se_marca_superada_sola,
              test_aprendizaje_no_importa_brain,
              test_ficheros_nuevos_sin_datos_personales,
              test_el_almacen_solo_escribe_dentro_de_data_dir,
              test_el_barrido_no_ejecuta_un_patron_de_forma_peligrosa,
              test_una_skill_rota_en_este_arranque_no_invalida_la_regla,
              test_dos_hilos_no_se_roban_la_marca_de_reentrada):
        try:
            f()
        except Exception as e:                             # noqa: BLE001
            import traceback
            _fail.append(f"EXCEPCION en {f.__name__}: {type(e).__name__}: {e}")
            print("  ✖ EXCEPCION en", f.__name__, ":", type(e).__name__, e)
            traceback.print_exc()
    print(f"\n{'#' * 54}\ntest_aprendizaje_puertas: {_pass} OK, {len(_fail)} fallos")
    for m in _fail:
        print("  -", m)
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
