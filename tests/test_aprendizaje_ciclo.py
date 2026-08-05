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

import datetime as dt
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
from backend.core.comun import audit                        # noqa: E402

sl.load_skills()
aprendizaje.registrar()
reglas.registrar_arbitro(brain.quien_atiende)

# Una frase que hoy NO atiende nadie: es el hueco donde una regla si cabe.
HUECO = "tramoya de prueba para el barrido"
# La misma, con signos que en una expresion regular significan otra cosa. Sirve
# para comprobar que la frase del operador se ESCAPA antes de convertirse en
# patron: pegarla cruda la convertiria en un grupo y el patron casaria de mas.
HUECO_CON_SIGNOS = "tramoya (de prueba) para el barrido"
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
    # UN AVISO NACE ABIERTO. «propuesta» aqui significa «abierto»: el aviso se
    # queda molestando en la lista hasta que alguien lo cierre a mano pasandolo a
    # «descartada». Naciendo ya cerrado se apuntaria el fallo de codigo y nadie
    # volveria a verlo, que es justo lo contrario de la decision 3 del duenno.
    check(guardados and guardados[0].get("estado") == "propuesta",
          f"el aviso nace en estado {guardados[0].get('estado') if guardados else None!r} "
          "en vez de abierto: un fallo de codigo tiene que molestar hasta que se arregle")

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


# ══════════ C1.4 · si YA hay una regla, no se apila otra encima ══════════
def test_antecedente_que_ya_tiene_regla_no_apila_otra():
    print("== C1.4) el antecedente ya lo atiende una regla aprendida: aviso, no otra regla ==")
    _limpia()
    # 1) Se aprende una regla para el hueco y se ACTIVA. A partir de aqui el
    #    antecedente ya no cae al planificador: lo atiende una regla.
    propuesta = aprendizaje.observa(f"aprende que cuando diga {HUECO} hagas {REPARA}")
    check(propuesta.get("tipo") == "enrutado",
          f"el montaje falla: no hay regla que activar ({propuesta})")
    if propuesta.get("tipo") != "enrutado":
        _limpia()
        return
    rid = propuesta["id"]
    check(reglas.transitar(rid, "activa", "prueba"), "la regla no se ha podido activar")
    activas = tuple(reglas.activas())
    check([r["id"] for r in activas] == [rid],
          f"la regla activada no esta en el conjunto activo: {[r['id'] for r in activas]}")

    # EL ARBITRO DE VERDAD YA LO DICE. Si esto no fuera asi, lo de abajo estaria
    # midiendo una situacion que no existe.
    check(brain.quien_atiende(HUECO, reglas=activas) == f"regla:{rid}",
          f"«{HUECO}» no la atiende la regla recien activada sino "
          f"«{brain.quien_atiende(HUECO, reglas=activas)}»")

    # 2) Y corregir OTRA VEZ sobre la misma frase avisa, no apila.
    salida = aprendizaje.observa("no, eso tampoco", antecedente=HUECO, canal="pc")
    check(salida.get("tipo") == "aviso",
          f"con una regla ya activa sobre la frase se devuelve {salida.get('tipo')!r} "
          "en vez de un aviso")
    check(salida.get("clase") == "ya_hay_regla",
          f"el aviso no se clasifica como «ya hay regla»: {salida.get('clase')!r}")
    check(rid in str(salida.get("mensaje") or ""),
          f"el aviso no dice QUE regla es la que ya lo atiende: «{salida.get('mensaje')}»")

    # 3) Y lo mismo con la formula explicita, que es la que de verdad hace dano:
    #    trae destino, asi que sin este veredicto llegaria a proponer, y
    #    `guardar()` sustituye por id — la regla ACTIVA volveria a «propuesta».
    #    Una correccion habria DESACTIVADO en silencio lo que ya estaba aprobado.
    otra = aprendizaje.observa(f"aprende que cuando diga {HUECO} hagas {REPARA}")
    check(otra.get("clase") == "ya_hay_regla",
          f"reensenar una frase que ya tiene regla activa devuelve "
          f"{otra.get('tipo')!r}/{otra.get('clase')!r} en vez de un aviso")
    check([r["id"] for r in reglas.activas()] == [rid],
          "corregir dos veces la misma frase ha desactivado la regla que ya estaba "
          "activa: una correccion no puede deshacer una aprobacion")
    almacen = [r for r in reglas.cargar().get("reglas", []) if r.get("tipo") == "enrutado"]
    check(len(almacen) == 1 and almacen[0].get("estado") == "activa",
          f"la regla aprendida ya no esta como estaba: {[(r['id'], r['estado']) for r in almacen]}")
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
    #
    # LOS DOS DIAS SE DERIVAN DEL QUE SE ACABA DE APUNTAR, no se escriben a mano.
    # Aqui ponia «2026-07-30» y «2026-07-31»: el dia que el reloj de la maquina
    # marcara una de esas dos fechas, la que se apunto arriba coincidiria con
    # una de ellas, saldrian dos dias distintos en vez de tres y el caso se
    # pondria rojo sin que nadie hubiera tocado nada. Una bomba de relojeria en
    # un caso que existe precisamente para vigilar el paso de los dias.
    apuntado = reglas.cargar().get("ocurrencias", {}).get(HUECO, [])
    check(len(apuntado) == 1,
          f"no hay un unico dia apuntado del que tirar: {apuntado}")
    hoy = dt.date.fromisoformat(apuntado[0])
    for atras in (1, 2):
        reglas.anota_ocurrencia(HUECO, (hoy - dt.timedelta(days=atras)).isoformat())
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

    _limpia()


def test_la_formula_de_ensenanza_es_LA_MISMA_QUE_LA_DEL_CEREBRO():
    print("== C1.5) _ENSENANZA_RX es copia literal de brain._TEACH_RX, letra por letra ==")
    # SE COMPARA EL TEXTO DE LA EXPRESION, NO SU COMPORTAMIENTO SOBRE UN PUNADO
    # DE FRASES.
    #
    # Aqui habia una tabla de cinco frases y una comparacion de `bool(match)`.
    # Ejercitaba `hagas` y `ejecuta`, y ni una sola vez `haz`, `ejecutes`,
    # `significa`, `es`, `quiero que hagas`, `pon`, `pongas` ni el «cuando TE
    # diga». Medido: quitarle a `_ENSENANZA_RX` la mitad de los verbos dejaba la
    # suite VERDE, y quitarle el «te» tambien. La copia se estaba vigilando con
    # una lupa que solo miraba dos letras de la firma.
    #
    # Comparar el patron entero cierra el hueco de una vez: cualquier divergencia
    # —un verbo, una tilde, una bandera— sale roja el mismo dia.
    check(aprendizaje._ENSENANZA_RX.pattern == brain._TEACH_RX.pattern,
          "la formula de ensenanza de aprendizaje ya no es la copia literal de la "
          "del cerebro:\n"
          f"    aprendizaje: {aprendizaje._ENSENANZA_RX.pattern!r}\n"
          f"    brain      : {brain._TEACH_RX.pattern!r}")
    check(aprendizaje._ENSENANZA_RX.flags == brain._TEACH_RX.flags,
          f"las dos formulas se compilan con banderas distintas: "
          f"{aprendizaje._ENSENANZA_RX.flags} vs {brain._TEACH_RX.flags}")

    # Y ademas se ejercita CADA verbo de la formula, para que la comparacion de
    # arriba no se quede en una igualdad entre dos cosas rotas por igual.
    for verbo in ("haz", "hagas", "ejecuta", "ejecutes", "significa", "es",
                  "quiero que hagas", "pon", "pongas"):
        frase = f"aprende que cuando te diga {HUECO} {verbo} {REPARA}"
        m = aprendizaje._ENSENANZA_RX.match(frase)
        check(m is not None and m.group("ph").strip() == HUECO
              and m.group("order").strip() == REPARA,
              f"la formula no reconoce «{verbo}»: {frase!r} -> "
              f"{(m.group('ph'), m.group('order')) if m else None}")
    for frase in ("aprende a cocinar", "no era eso", REPARA):
        check(aprendizaje._ENSENANZA_RX.match(frase) is None,
              f"la formula se traga «{frase}», que no es una ensenanza")


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

        # 2 bis) LA GENERALIZACION QUE `selflearn` DA POR BUENA Y LAS PUERTAS
        #        TIRAN. Los dos casos de arriba los para `generaliza_patron()`
        #        —devuelven cadena vacia—, asi que el `if ok:` de `_propone()`
        #        NUNCA veia un candidato malo: la comprobacion de que la salida
        #        del modelo es ENTRADA de las puertas estaba muerta en el banco
        #        de pruebas. Medido: aceptar el candidato pasaran o no las
        #        puertas dejaba la suite entera verde.
        #
        #        Este patron esta anclado, compila, no es una forma peligrosa y
        #        CASA su propia frase —las tres cosas que mira `selflearn`—, pero
        #        se pasa del largo maximo que exige la puerta 3.
        largo = (r"^\s*tramoya\s+de\s+prueba\s+para\s+el\s+barrido\s*(?:"
                 + "|".join(f"relleno{i:02d}" for i in range(20)) + r")?\s*$")
        selflearn.registrar_generalizador(lambda f: largo)
        check(selflearn.generaliza_patron(HUECO) == largo,
              "selflearn ya para este candidato: entonces no prueba que lo paren "
              "LAS PUERTAS, que es lo que este caso mide")
        check(reglas.valida({**{"id": "r-tmp", "esquema": reglas.ESQUEMA,
                                "tipo": "enrutado", "revision": 1,
                                "origen": {"frase": HUECO, "canal": "pc",
                                           "fecha": "2026-01-01T00:00:00"},
                                "destino": "system_pc/kill", "patron": largo,
                                "evidencia": {"arrastradas": [], "suite": None},
                                "estado": "propuesta"}})[0] is False,
              "el candidato largo pasa las puertas: este caso no mide nada")
        salida = aprendizaje.observa(f"aprende que cuando diga {HUECO} hagas {REPARA}")
        check(salida.get("patron") == literal,
              f"una generalizacion que NO pasa las puertas se ha quedado en la "
              f"propuesta: {salida.get('patron')!r}")
        check((salida.get("evidencia") or {}).get("generalizado") is False,
              "la propuesta dice que esta generalizada y lleva el patron literal")
        # Y se dice POR QUE se cayo al literal: una degradacion silenciosa es
        # indistinguible de un modelo apagado.
        acciones = [a for a in audit.tail(40)
                    if a.get("action") == "generalizacion_descartada"]
        check(acciones and acciones[-1].get("result") == "cae_al_patron_literal",
              "descartar la generalizacion no deja linea en la auditoria: "
              f"{[a.get('action') for a in audit.tail(10)]}")
        check(acciones and "demasiado largo" in str(acciones[-1].get("error") or ""),
              f"la auditoria no dice por que se descarto: "
              f"{acciones[-1].get('error') if acciones else None!r}")
        _limpia()

        # 3) CON UN MODELO QUE DEVUELVE ALGO QUE NO CASA SU PROPIA FRASE. No es
        #    una version ancha de esa regla: es otra regla colada por detras.
        selflearn.registrar_generalizador(lambda f: r"^\s*otra\s+cosa\s+distinta\s*$")
        check(selflearn.generaliza_patron(HUECO) == "",
              "se acepta como generalizacion un patron que no casa la frase original")
        _limpia()

        # 3 bis) LAS OTRAS DOS COSAS QUE `generaliza_patron()` PROMETE MIRAR y
        #        que no comprobaba nadie: que compila y que esta anclado por los
        #        dos lados. Las tapaba la puerta 3, que exige lo mismo mas tarde
        #        —el resultado visible era el mismo patron literal—, pero una
        #        guarda que solo esta viva porque otra la cubre es una guarda que
        #        se puede borrar sin que salte nada.
        for malo, por_que in (
                (r"\s*tramoya\s+de\s+prueba\s+para\s+el\s+barrido\s*$", "sin anclar por delante"),
                (r"^\s*tramoya\s+de\s+prueba\s+para\s+el\s+barrido\s*", "sin anclar por detras"),
                (r"^\s*tramoya\s+(de\s+prueba\s+para\s+el\s+barrido\s*$", "no compila")):
            selflearn.registrar_generalizador(lambda f, _m=malo: _m)
            check(selflearn.generaliza_patron(HUECO) == "",
                  f"se acepta un candidato {por_que}: {malo!r}")
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


def test_una_frase_con_signos_no_se_cuela_como_expresion_regular():
    print("== C1.7) la frase del operador se ESCAPA antes de ser patron ==")
    _limpia()
    # Una frase del duenno puede traer parentesis, interrogantes o un punto.
    # Pegada cruda en una expresion regular deja de ser esa frase y pasa a ser
    # otra cosa: los parentesis se convierten en un grupo y el patron casa
    # frases que el operador nunca dijo.
    check(brain.quien_atiende(HUECO_CON_SIGNOS, reglas=()) == "planificador",
          f"«{HUECO_CON_SIGNOS}» ya la atiende alguien: no queda hueco que medir")
    salida = aprendizaje.observa(
        f"aprende que cuando diga {HUECO_CON_SIGNOS} hagas {REPARA}")
    check(salida.get("tipo") == "enrutado",
          f"una frase con signos no llega a proponerse: {salida}")
    patron = str(salida.get("patron") or "zzz")
    check(re.search(patron, HUECO_CON_SIGNOS, re.IGNORECASE) is not None,
          f"el patron no casa la frase que lo origino: {patron!r}")
    # Y ESTA ES LA QUE IMPORTA: sin escapar, «(de prueba)» seria un grupo y el
    # patron casaria tambien la frase SIN los parentesis, que es otra distinta.
    check(re.search(patron, HUECO, re.IGNORECASE) is None,
          f"el patron casa «{HUECO}», que es otra frase: los parentesis se han "
          f"colado como sintaxis en vez de como texto ({patron!r})")
    _limpia()


# ══════════ C1.1 · sin arbitro no se juzga: «no lo se» no es «planificador» ══════════
def test_sin_arbitro_registrado_no_se_juzga_nada():
    print("== C1.1) sin arbitro registrado, observa() calla y no escribe nada ==")
    _limpia()
    # NADIE REGISTRA EL ARBITRO HASTA EL BLOQUE C. La promesa escrita en la
    # cabecera del modulo es que, hasta entonces, `observa()` contesta «no lo se»
    # y nexus se comporta EXACTAMENTE igual que antes. Nadie la comprobaba:
    # medido, cambiar ese `return {}` por «tratalo como planificador» dejaba las
    # 81 suites verdes — y con eso cada correccion se juzgaria a ciegas, sin
    # saber quien enruta, que es adivinar.
    reglas.registrar_arbitro(None)
    try:
        check(reglas.arbitro(HUECO, reglas=()) == "",
              "sin arbitro registrado el arbitro contesta algo: revisa este caso")
        for correccion, antecedente in (
                (f"aprende que cuando diga {HUECO} hagas {REPARA}", ""),
                ("no era eso", "apaga la tele"),
                (REPARA, HUECO)):
            salida = aprendizaje.observa(correccion, antecedente=antecedente)
            check(salida == {},
                  f"sin arbitro se juzga «{antecedente or correccion}» igual: {salida}")
        check(reglas.cargar().get("reglas", []) == [],
              f"sin arbitro se ha escrito algo en el almacen: "
              f"{reglas.cargar().get('reglas')}")
        check(reglas.ocurrencias(HUECO) == 0,
              "sin arbitro se acumula evidencia de una correccion que nadie ha juzgado")
    finally:
        reglas.registrar_arbitro(brain.quien_atiende)
    check(reglas.arbitro(HUECO, reglas=()) == "planificador",
          "el arbitro no se ha vuelto a registrar: los casos de despues mienten")
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
    # `selflearn.py` entra aqui: C1 le anade `ultima_orden()` y
    # `generaliza_patron()`, y la guarda de B4.6 no lo miraba. Al meterlo salio
    # rojo a la primera por el nombre del duenno escrito en su cabecera, que
    # llevaba ahi desde antes de este cambio y no vigilaba nadie.
    for f in (ROOT / "tests" / "test_aprendizaje_ciclo.py",
              ROOT / "backend" / "core" / "dominio" / "selflearn.py"):
        check(f.exists(), f"{f.name} no existe: la guarda no esta mirando nada")
        if not f.exists():
            continue
        txt = f.read_text(encoding="utf-8")
        for palabra in prohibidas:
            check(palabra not in txt.lower(),
                  f"«{palabra}» aparece en {f.name}: dato personal del duenno")
        ips = re.findall(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])", txt)
        check(not ips, f"IPs completas escritas en {f.name}: {ips[:3]}")
        # La copia de B4.6 miraba tambien las MAC y esta se dejo el caso fuera.
        macs = re.findall(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b", txt)
        check(not macs, f"MACs completas escritas en {f.name}: {macs[:3]}")


# ══════════ la normalizacion de frases, que ahora es punto unico ══════════
def test_la_normalizacion_de_frases_hace_las_cuatro_cosas():
    print("== C1) `selflearn.normaliza()` es la unica, y por eso hay que vigilarla ==")

    # ESTA LINEA VIVIA COPIADA TRES VECES (`brain`, `aprendizaje`, `selflearn`) y
    # NINGUNA COPIA TENIA TEST. Al unificarlas dejo de existir la divergencia,
    # pero apareció algo peor: un punto unico de fallo sin vigilancia. Medido:
    # dejando `normaliza()` en un simple `.strip()` las 81 suites seguian verdes,
    # y con ella rota «Apaga la tele.» deja de reconocerse como «apaga la tele».
    for crudo, esperado, que in (
            ("APAGA la Tele", "apaga la tele", "no baja a minusculas"),
            ("apaga   la    tele", "apaga la tele", "no colapsa los espacios"),
            ("  apaga la tele  ", "apaga la tele", "no recorta los extremos"),
            ("¿apaga la tele?", "apaga la tele", "no quita los signos de pregunta"),
            ("¡apaga la tele!", "apaga la tele", "no quita los signos de admiracion"),
            ("apaga la tele.", "apaga la tele", "no quita el punto final"),
            ("apaga la tele,", "apaga la tele", "no quita la coma final"),
            ("¿APAGA   la Tele?  ", "apaga la tele", "no aplica las cuatro a la vez"),
            ("", "", "no aguanta la cadena vacia"),
    ):
        check(selflearn.normaliza(crudo) == esperado,
              f"normaliza({crudo!r}) {que}: {selflearn.normaliza(crudo)!r} "
              f"en vez de {esperado!r}")

    # Y la consecuencia que de verdad importa: dos maneras de escribir la MISMA
    # orden tienen que contar como la misma. Si no, la evidencia se dispersa y el
    # umbral no se alcanza nunca.
    check(selflearn.normaliza("¿Apaga la TELE?") == selflearn.normaliza("apaga la tele"),
          "dos formas de escribir la misma orden no se reconocen como la misma: "
          "la evidencia se dispersaria y el umbral no se alcanzaria nunca")
    check(selflearn.normaliza("Crea una tarea") != selflearn.normaliza("borra una tarea"),
          "normaliza() iguala dos ordenes distintas: estaria borrando informacion")


def test_la_normalizacion_es_una_sola_implementacion():
    print("== C1) nadie vuelve a copiar la normalizacion en su propio modulo ==")

    # La copia se justificaba con «no puedo importar `brain`». Era verdad y era
    # irrelevante: esto es una regla de DOMINIO y `aplicacion` puede bajar a
    # dominio. Este test existe para que la copia no vuelva por la puerta de
    # atras: si alguien reescribe la linea en su modulo, salta.
    ORIGEN = ROOT / "backend" / "core" / "dominio" / "selflearn.py"
    HUELLA = 'strip("¿?¡!.,;:")'
    duplicados = []
    for py in (ROOT / "backend").rglob("*.py"):
        if py.resolve() == ORIGEN.resolve():
            continue
        if HUELLA in py.read_text(encoding="utf-8", errors="replace"):
            duplicados.append(str(py.relative_to(ROOT)).replace("\\", "/"))
    check(not duplicados,
          f"la normalizacion vuelve a estar copiada fuera de dominio/selflearn.py: "
          f"{duplicados}. Es una regla de dominio: importala, no la reescribas")

    # Y que las dos de `aplicacion` sigan dando lo mismo que la de dominio, que
    # es lo unico que garantiza que delegan de verdad y no han vuelto a divergir.
    for frase in ("¿Apaga la TELE?", "  crea   una tarea. ", ""):
        check(brain._norm(frase) == selflearn.normaliza(frase),
              f"brain._norm ya no delega en dominio para {frase!r}")
        check(aprendizaje._norm(frase) == selflearn.normaliza(frase),
              f"aprendizaje._norm ya no delega en dominio para {frase!r}")


def main() -> int:
    for f in (test_la_normalizacion_de_frases_hace_las_cuatro_cosas,
              test_la_normalizacion_es_una_sola_implementacion,
              test_antecedente_que_llega_a_una_skill_no_propone_nada,
              test_antecedente_que_ya_tiene_regla_no_apila_otra,
              test_antecedente_capturado_por_un_atajo_no_propone,
              test_misma_queja_repetida_cuenta_una_vez,
              test_una_orden_explicita_entra_a_la_primera,
              test_capacidad_inexistente_no_genera_propuesta,
              test_sin_modelo_cae_al_patron_literal,
              test_una_frase_con_signos_no_se_cuela_como_expresion_regular,
              test_la_formula_de_ensenanza_es_LA_MISMA_QUE_LA_DEL_CEREBRO,
              test_sin_arbitro_registrado_no_se_juzga_nada,
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
