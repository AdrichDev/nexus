# -*- coding: utf-8 -*-
"""Bloque C de 004, rebanada C1: observar la correccion sin taparla.

QUE SE PRUEBA AQUI. Que `aprendizaje.observa()` distingue un HUECO DE ENRUTADO
—nadie atiende la frase, y ahi si cabe una regla— de un FALLO DE CODIGO —la
frase llega a quien debe y quien la atiende se porta mal—. La diferencia no es
un matiz: una regla que tapa un fallo de codigo lo esconde para siempre, y esa
es la decision 3 del duenno.

QUIEN JUZGA Y A QUIEN. No se juzga la queja: se juzga su ANTECEDENTE, el turno
anterior del operador. Y se juzga con el arbitro de verdad
(`brain.quien_atiende`), no con un doble: un doble contestaria lo que le
apetezca al test y la prueba no diria nada del sistema.

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_aprendizaje_ciclo.py
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("NEXUS_DATA_DIR", tempfile.mkdtemp(prefix="nexus_ciclo_"))

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
from backend.core.dominio import selflearn                  # noqa: E402

sl.load_skills()
aprendizaje.registrar()
reglas.registrar_arbitro(brain.quien_atiende)

# Una frase que hoy NO atiende nadie: es el hueco donde una regla si cabe.
HUECO = "tramoya de prueba para el barrido"
# Una correccion que SI llega a una skill: de ahi sale el destino pretendido.
REPARA = "cierra chrome"


def _limpia() -> None:
    p = reglas.ruta_almacen()
    for f in (p, p.with_name(p.name + ".bak"), p.with_name(p.name + ".tmp")):
        try:
            f.unlink()
        except Exception:                                  # noqa: BLE001
            pass
    reglas.olvida_huella()


def _propuestas() -> list[dict]:
    return [r for r in reglas.cargar().get("reglas", [])
            if r.get("tipo") == "enrutado" and r.get("estado") == "propuesta"]


def _avisos() -> list[dict]:
    return [r for r in reglas.cargar().get("reglas", []) if r.get("tipo") == "aviso"]


# ══════════ C1.2 · un fallo de codigo no se tapa con una regla ══════════
def test_antecedente_que_llega_a_una_skill_no_propone_nada():
    print("== C1.2) antecedente que YA llega a una skill: cero propuestas y un aviso ==")
    _limpia()
    # Se comprueba, no se supone: si algun dia esta frase deja de llegar a la
    # skill, el caso dejaria de probar lo que dice probar y saldria verde igual.
    veredicto = brain.quien_atiende("apaga la tele", reglas=())
    check(veredicto.startswith("skill:"),
          f"«apaga la tele» ya no llega a ninguna skill ({veredicto}): "
          "este caso ha dejado de medir un fallo de codigo")

    salida = aprendizaje.observa("no, la del salon", antecedente="apaga la tele",
                                 canal="pc")

    check(salida.get("tipo") == "aviso",
          f"observa() no ha devuelto un aviso sino {salida.get('tipo')!r}: {salida}")
    check(salida.get("clase") == "fallo_de_codigo",
          f"el aviso no se clasifica como fallo de codigo: {salida.get('clase')!r}")
    check(veredicto in str(salida.get("mensaje") or ""),
          f"el aviso no dice A QUIEN llega hoy la frase: «{salida.get('mensaje')}»")
    check("skill" in str(salida.get("mensaje") or "").lower(),
          f"el aviso no dice que el fallo esta dentro de la skill: «{salida.get('mensaje')}»")

    # Y las DOS afirmaciones, no una: cero propuestas Y el aviso registrado.
    check(_propuestas() == [],
          f"se ha propuesto una regla sobre un fallo de codigo: {_propuestas()}")
    guardados = _avisos()
    check(len(guardados) == 1,
          f"el aviso no queda registrado en el almacen: {len(guardados)} avisos")
    check(guardados and guardados[0].get("origen", {}).get("frase") == "apaga la tele",
          "el aviso no lleva pegada la frase que se enruto, sino otra cosa")

    # Un aviso NUNCA se activa, por mucho que alguien le escriba «activa».
    reglas.transitar(guardados[0]["id"], "activa", "a mano")
    check(all(r.get("tipo") != "aviso" for r in reglas.activas()),
          "un aviso ha entrado en el conjunto activo: un fallo de codigo no es una regla")
    _limpia()


# ══════════ C1.3 · un atajo previo se queda la frase, y se dice ══════════
def test_antecedente_capturado_por_un_atajo_no_propone():
    print("== C1.3) antecedente que se queda un atajo previo al router: aviso ==")
    _limpia()
    # Los tres atajos que corren ANTES del router. Una regla vive DETRAS del
    # router, asi que no puede recuperar ninguna de estas frases.
    casos = (("apunta que me gusta el cafe solo", "memoria"),
             ("hola", "charla"),
             ("no te he dicho que leas los correos", "queja"))
    for frase, esperado in casos:
        real = brain.quien_atiende(frase, reglas=())
        check(real == esperado,
              f"«{frase}» ya no la coge el atajo «{esperado}» sino «{real}»: "
              "el caso ha dejado de medir lo que dice medir")

        salida = aprendizaje.observa("no era eso", antecedente=frase, canal="pc")
        check(salida.get("tipo") == "aviso",
              f"«{frase}» ({esperado}) genera {salida.get('tipo')!r} en vez de un aviso")
        check(salida.get("clase") == "atajo_previo",
              f"«{frase}» no se clasifica como atajo previo: {salida.get('clase')!r}")
        mensaje = str(salida.get("mensaje") or "").lower()
        check("detr" in mensaje and "router" in mensaje,
              f"el aviso no explica que las reglas van detras del router: «{mensaje}»")
        check("no lo arregla" in mensaje or "no arregla" in mensaje,
              f"el aviso no dice que este mecanismo NO arregla ese fallo: «{mensaje}»")

    check(_propuestas() == [],
          f"un atajo previo ha generado propuestas: {_propuestas()}")
    check(len(_avisos()) == 3,
          f"los tres atajos no dejan tres avisos distintos: {len(_avisos())}")
    _limpia()


# ══════════ C1.5 · la evidencia depende de quien lo diga ══════════
def test_misma_queja_repetida_cuenta_una_vez():
    print("== C1.5) tres quejas el mismo dia son UNA prueba, no tres ==")
    _limpia()
    tope = reglas.umbral("umbral_observada", 3)
    check(tope == 3,
          f"aprendizaje.umbral_observada vale {tope} y no 3: este caso cuenta hasta 3")

    # Se comprueba el montaje: el antecedente cae al planificador (hueco real) y
    # la correccion SI llega a una skill (de ahi sale el destino pretendido).
    check(brain.quien_atiende(HUECO, reglas=()) == "planificador",
          f"«{HUECO}» ya la atiende alguien: no queda hueco que medir")
    check(brain.quien_atiende(REPARA, reglas=()) == "skill:system_pc/kill",
          f"«{REPARA}» ya no llega a system_pc/kill: el destino no se puede deducir")

    # Tres veces la MISMA queja, el MISMO dia. Si el contador contara llamadas en
    # vez de dias distintos, la tercera propondria.
    for i in range(3):
        salida = aprendizaje.observa(REPARA, antecedente=HUECO, canal="pc")
        check(salida == {},
              f"la queja numero {i + 1} del mismo dia ya propone algo: {salida}")
    check(reglas.ocurrencias(HUECO) == 1,
          f"tres quejas del mismo dia cuentan {reglas.ocurrencias(HUECO)} pruebas: "
          "repetir la misma queja de rabia no es evidencia nueva")
    check(_propuestas() == [], f"hay propuesta por debajo del umbral: {_propuestas()}")

    # Dos dias anteriores + el de hoy: tres pruebas DISTINTAS, y ahi si.
    reglas.anota_ocurrencia(HUECO, "2026-07-30")
    reglas.anota_ocurrencia(HUECO, "2026-07-31")
    check(reglas.ocurrencias(HUECO) == 3,
          f"dos dias mas no suman: {reglas.ocurrencias(HUECO)} pruebas")
    salida = aprendizaje.observa(REPARA, antecedente=HUECO, canal="pc")
    check(salida.get("tipo") == "enrutado",
          f"con tres dias distintos sigue sin proponerse nada: {salida}")
    origen = salida.get("origen") or {}
    check(origen.get("tipo") == "observada",
          f"la evidencia no se marca como observada: {origen.get('tipo')!r}")
    check(origen.get("veces") == 3,
          f"la propuesta dice {origen.get('veces')!r} ocurrencias en vez de 3")
    check(origen.get("frase") == HUECO,
          "la propuesta no lleva pegada la frase que se enrutaba mal")
    check(salida.get("destino") == "system_pc/kill",
          f"el destino no sale de la correccion: {salida.get('destino')!r}")
    check(salida.get("estado") == "propuesta",
          f"la propuesta nace en estado {salida.get('estado')!r}: nada se activa solo")
    check(len(_propuestas()) == 1,
          f"la propuesta no queda en el almacen: {len(_propuestas())}")
    _limpia()


def test_una_orden_explicita_entra_a_la_primera():
    print("== C1.5) «aprende que cuando diga X hagas Y» es una orden, no una sospecha ==")
    _limpia()
    salida = aprendizaje.observa(f"aprende que cuando diga {HUECO} hagas {REPARA}")
    check(salida.get("tipo") == "enrutado",
          f"una orden explicita no propone a la primera: {salida}")
    origen = salida.get("origen") or {}
    check(origen.get("tipo") == "ordenada",
          f"la evidencia no se marca como ordenada: {origen.get('tipo')!r}")
    check(origen.get("veces") == 1,
          f"una orden explicita exige {origen.get('veces')!r} ocurrencias en vez de 1")
    check(origen.get("frase") == HUECO,
          f"la frase de la orden no se ha extraido bien: {origen.get('frase')!r}")
    check(salida.get("destino") == "system_pc/kill",
          f"el destino no sale de la orden: {salida.get('destino')!r}")

    # Y la formula que reconoce el aprendizaje es LA MISMA que la del cerebro.
    # No se importa (seria el quinto ciclo de CAPAS.md), asi que se compara:
    # si una de las dos cambia sin la otra, esto se pone rojo.
    for frase in (f"aprende que cuando diga {HUECO} hagas {REPARA}",
                  f"aprendete cuando diga {HUECO} ejecuta {REPARA}",
                  "aprende a cocinar", "no era eso", REPARA):
        check(bool(aprendizaje._ENSENANZA_RX.match(frase))
              == bool(brain._TEACH_RX.match(frase)),
              f"la formula de ensenanza de aprendizaje y la del cerebro discrepan "
              f"en «{frase}»")
    _limpia()


# ══════════ C1.6 · nexus no propone jamas escribir una skill ══════════
def test_capacidad_inexistente_no_genera_propuesta():
    print("== C1.6) si nadie sabe hacerlo, no hay regla: hace falta una skill nueva ==")
    _limpia()
    # Una reparacion que tampoco llega a nadie: el operador esta pidiendo una
    # capacidad que ninguna skill declara.
    imposible = "hazme un cafe irlandes ahora mismo"
    check(brain.quien_atiende(imposible, reglas=()) == "planificador",
          f"«{imposible}» ya la atiende alguien: el caso ha dejado de medir "
          "una capacidad inexistente")

    salida = aprendizaje.observa(imposible, antecedente=HUECO, canal="pc")
    check(salida.get("tipo") == "aviso",
          f"una capacidad que no existe genera {salida.get('tipo')!r} en vez de un aviso")
    check(salida.get("clase") == "sin_capacidad",
          f"el aviso no se clasifica como capacidad inexistente: {salida.get('clase')!r}")
    mensaje = str(salida.get("mensaje") or "").lower()
    check("skill nueva" in mensaje,
          f"el aviso no dice que eso necesita una skill nueva: «{mensaje}»")
    check("no escribe" in mensaje,
          f"el aviso no dice que nexus NO escribe codigo: «{mensaje}»")
    check(_propuestas() == [],
          f"se ha propuesto una regla hacia un destino que no existe: {_propuestas()}")

    # Y ni siquiera se apunta la ocurrencia: sin destino no hay nada que contar,
    # y acumular evidencia de algo inalcanzable solo engorda el fichero.
    check(reglas.ocurrencias(HUECO) == 0,
          f"se acumula evidencia de una correccion sin destino posible: "
          f"{reglas.ocurrencias(HUECO)}")

    # Triangulacion: la MISMA frase mal enrutada, con una reparacion que SI
    # llega a una skill, si propone. El corte es el destino y no otra cosa.
    salida = aprendizaje.observa(f"aprende que cuando diga {HUECO} hagas {REPARA}")
    check(salida.get("tipo") == "enrutado",
          f"con una reparacion que si existe sigue sin proponerse nada: {salida}")
    _limpia()


# ══════════ C1.7 · el modelo ENSANCHA, las puertas deciden ══════════
def test_sin_modelo_cae_al_patron_literal():
    print("== C1.7) sin modelo, o con una generalizacion que no pasa, manda el literal ==")
    _limpia()
    literal = r"^\s*tramoya\s+de\s+prueba\s+para\s+el\s+barrido\s*$"

    # 1) SIN MODELO. El aprendizaje degrada a un patron mas estrecho, no
    #    desaparece: sigue habiendo propuesta y sigue casando su propia frase.
    selflearn.registrar_generalizador(None)
    check(selflearn.generaliza_patron(HUECO) == "",
          "sin generalizador registrado sale un patron de algun sitio")
    salida = aprendizaje.observa(f"aprende que cuando diga {HUECO} hagas {REPARA}")
    check(salida.get("patron") == literal,
          f"sin modelo el patron no es el literal anclado: {salida.get('patron')!r}")
    check(re.search(salida.get("patron", "zzz"), HUECO, re.IGNORECASE) is not None,
          "el patron literal ni siquiera casa la frase que lo origino")
    _limpia()

    try:
        # 2) CON UN MODELO QUE DEVUELVE UNA RED DE ARRASTRE. La puerta de forma
        #    la tira y se cae al literal: la salida del modelo es ENTRADA de las
        #    puertas, nunca un veredicto.
        selflearn.registrar_generalizador(lambda f: r"^.*$")
        check(selflearn.generaliza_patron(HUECO) == "",
              "un «.*» libre se acepta como generalizacion")
        salida = aprendizaje.observa(f"aprende que cuando diga {HUECO} hagas {REPARA}")
        check(salida.get("patron") == literal,
              f"una generalizacion peligrosa se ha colado en la propuesta: "
              f"{salida.get('patron')!r}")
        _limpia()

        # 3) CON UN MODELO QUE DEVUELVE ALGO QUE NO CASA SU PROPIA FRASE. No es
        #    una version ancha de esa regla: es otra regla colada por detras.
        selflearn.registrar_generalizador(lambda f: r"^\s*otra\s+cosa\s+distinta\s*$")
        check(selflearn.generaliza_patron(HUECO) == "",
              "se acepta como generalizacion un patron que no casa la frase original")
        _limpia()

        # 4) CON UN MODELO QUE ENSANCHA DE VERDAD. Ese si manda, y se nota:
        #    casa la frase original Y una variante que el literal no cazaba.
        ancho = r"^\s*tramoya\s+de\s+prueba\s+(?:para\s+el\s+)?barrido\s*$"
        selflearn.registrar_generalizador(lambda f: ancho)
        check(selflearn.generaliza_patron(HUECO) == ancho,
              "una generalizacion valida se descarta")
        salida = aprendizaje.observa(f"aprende que cuando diga {HUECO} hagas {REPARA}")
        check(salida.get("patron") == ancho,
              f"la generalizacion valida no llega a la propuesta: {salida.get('patron')!r}")
        check(re.search(ancho, "tramoya de prueba barrido", re.IGNORECASE) is not None,
              "el patron «ancho» de este caso no ensancha nada: no prueba la diferencia")
        check(re.search(literal, "tramoya de prueba barrido", re.IGNORECASE) is None,
              "el patron literal ya casaba la variante: los dos casos son el mismo")
    finally:
        selflearn.registrar_generalizador(None)
        _limpia()


# ══════════ C1.1 · el antecedente, y de donde sale cuando no lo pasan ══════════
def test_el_antecedente_se_busca_en_el_registro_si_no_llega():
    print("== C1.1) sin antecedente en mano se busca en interactions.jsonl ==")
    _limpia()
    registro = selflearn._INTER
    try:
        registro.unlink()
    except Exception:                                      # noqa: BLE001
        pass

    # Sin turno anterior por ningun lado no hay nada que juzgar. Ni aviso.
    check(aprendizaje.observa("no era eso") == {},
          "se juzga una correccion sin ningun antecedente del que tirar")

    # El cerebro guarda el historial en RAM, pero una correccion que llega por
    # otro canal —o despues de reiniciar— no lo comparte. Lo que sobrevive es
    # esto, y de aqui sale el turno anterior.
    selflearn.record_interaction("apaga la tele", "hecho", "domotica")
    selflearn.record_interaction("no era eso", "vale", "")
    check(selflearn.ultima_orden(excluir="no era eso") == "apaga la tele",
          f"el registro no devuelve el turno anterior: "
          f"«{selflearn.ultima_orden(excluir='no era eso')}»")

    salida = aprendizaje.observa("no era eso")
    check(salida.get("tipo") == "aviso",
          f"con el turno anterior en el registro sigue sin juzgarse nada: {salida}")
    check((salida.get("origen") or {}).get("frase") == "apaga la tele",
          "el aviso no se ha construido sobre el turno anterior del registro")
    _limpia()
    try:
        registro.unlink()
    except Exception:                                      # noqa: BLE001
        pass


def test_ficheros_nuevos_de_c1_sin_datos_personales():
    print("== C1) ni un nombre, ni una IP, ni una MAC en lo que anade C1 ==")
    # La guarda viaja CON los ficheros que vigila: metida en la suite de B, un
    # `git revert` de C1 la dejaria mirando ficheros que ya no existen.
    prohibidas = ("ad" + "ri", "maq" + "ueda", "ach" + "oz")
    for f in (ROOT / "tests" / "test_aprendizaje_ciclo.py",):
        txt = f.read_text(encoding="utf-8")
        for palabra in prohibidas:
            check(palabra not in txt.lower(),
                  f"«{palabra}» aparece en {f.name}: dato personal del duenno")
        ips = re.findall(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])", txt)
        check(not ips, f"IPs completas escritas en {f.name}: {ips[:3]}")


def main() -> int:
    for f in (test_antecedente_que_llega_a_una_skill_no_propone_nada,
              test_antecedente_capturado_por_un_atajo_no_propone,
              test_misma_queja_repetida_cuenta_una_vez,
              test_una_orden_explicita_entra_a_la_primera,
              test_capacidad_inexistente_no_genera_propuesta,
              test_sin_modelo_cae_al_patron_literal,
              test_el_antecedente_se_busca_en_el_registro_si_no_llega,
              test_ficheros_nuevos_de_c1_sin_datos_personales):
        try:
            f()
        except Exception as e:                             # noqa: BLE001
            import traceback
            _fail.append(f"EXCEPCION en {f.__name__}: {type(e).__name__}: {e}")
            print("  ✖ EXCEPCION en", f.__name__, ":", type(e).__name__, e)
            traceback.print_exc()
    print(f"\n{'#' * 54}\ntest_aprendizaje_ciclo: {_pass} OK, {len(_fail)} fallos")
    for m in _fail:
        print("  -", m)
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
