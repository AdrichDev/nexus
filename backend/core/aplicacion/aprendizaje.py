"""
nexus — Las puertas del aprendizaje que necesitan saber quien enruta.

Capa: aplicacion. Importa `dominio/reglas` (abajo) y `aplicacion/skills_loader`
(misma capa). NO importa el cerebro: es el cerebro quien se registra como
arbitro al final de su modulo. Un ciclo entre dos modulos de la misma capa
pasaria la suite de capas, pero obligaria a importar dentro de la funcion y eso
esconde la dependencia — `CAPAS.md` ya explica los cuatro que se arrastran, y no
se anade el quinto.

Aqui vive lo que `dominio` no puede saber por si solo: que `carpeta/intent`
existen de verdad en esta instalacion, y que la puerta de suite NO se ejecuta en
la maquina de un usuario.

Bloque B de 004: este modulo sabe JUZGAR una regla. Rebanada C1: ademas sabe
OBSERVAR una correccion y decidir si delata un hueco de enrutado (donde cabe una
regla) o un fallo de codigo (donde una regla solo taparia el problema).

Aprobarlas por tandas y consultarlas en caliente sigue siendo C2/C3. Nada de
produccion importa este modulo todavia y NADIE ha registrado el arbitro, asi que
`observa()` contesta «no lo se» y nexus se comporta exactamente igual que antes.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re

from ..comun import audit
from ..dominio import reglas, selflearn
from . import skills_loader


# ------------------------------------------------------------------ catalogo
def existe_destino(destino: str) -> bool:
    """¿«carpeta/intent» existe AHORA MISMO y su skill esta sana?

    Se comprueba contra el registro cargado, no contra una lista escrita en
    ningun sitio: una skill desinstalada o que ha reventado al cargar
    (`status == "error"`) no puede ser el destino de nada. Ese es el caso
    «Destino que desaparece» de la matriz de amenazas."""
    if not isinstance(destino, str) or "/" not in destino:
        return False
    carpeta, _, intent = destino.partition("/")
    skill = skills_loader.get_skills().get(carpeta.strip())
    if skill is None or skill.status == "error":
        return False
    return intent.strip() in skill.patterns


def destino_averiado(destino: str) -> bool:
    """¿La skill del destino esta INSTALADA pero rota en este arranque?

    Separa las dos formas de que un destino no este: desinstalada (se fue, y la
    regla que apunta ahi ya no vale) y reventada al cargar (sigue ahi y volvera
    en cuanto se arregle). La segunda no puede costarle a la regla una marca
    permanente en disco."""
    if not isinstance(destino, str) or "/" not in destino:
        return False
    carpeta, _, _intent = destino.partition("/")
    skill = skills_loader.get_skills().get(carpeta.strip())
    return skill is not None and skill.status == "error"


def registrar() -> None:
    """Rellena el hueco que `dominio/reglas` deja para el catalogo.

    Sin esta llamada `reglas.existe_destino()` contesta `False` y NINGUNA regla
    de enrutado se activa. El valor por defecto va al reves que en
    `comun/events`: alli, sin rellenar, se contesta que si hay trabajo, porque un
    candado que se equivoca callando es peor que no tenerlo. Aqui una puerta que
    se equivoca APROBANDO es lo unico que este cambio no se puede permitir."""
    reglas.registrar_catalogo(existe_destino)
    reglas.registrar_averia(destino_averiado)


# ------------------------------------------------------------------- puerta 4
def barrido(regla: dict) -> dict:
    """Puerta 4 con el detalle en claro: que frases roba y cuales arrastra.

    `reglas.barrido()` hace la pasada; esto la presenta. La lista de arrastre es
    lo que convierte «qué has aprendido» en una decision informada: enseña las
    frases del corpus que pasarian de `planificador` a esa skill si se aprueba."""
    registrar()
    crudo = reglas.barrido(regla)
    return {
        "robadas": [{"frase": f, "antes": a, "despues": d}
                    for f, a, d in crudo["robadas"]],
        "arrastradas": list(crudo["arrastradas"]),
        "ms": crudo["ms"],
        "frases": crudo["frases"],
        # Si la pasada se planto, el motivo VIAJA. Sin esto, quien llame a esta
        # funcion ve cero frases y cero milisegundos y no sabe si es que la
        # regla no roba nada o es que ni siquiera se ha podido barrer.
        "abortado": crudo.get("abortado", ""),
    }


def valida(regla: dict) -> tuple[bool, str]:
    """Las cuatro puertas que SI corren en casa del usuario."""
    registrar()
    return reglas.valida(regla)


# ------------------------------------------------------------------- puerta 5
def puerta_suite(regla: dict) -> str:
    """SIEMPRE `no_aplicable`, y siempre con su linea en la auditoria.

    La puerta de suite no es una puerta de activacion sino de entrega: se ejecuta
    en desarrollo, sobre la TANDA COMPLETA y no regla a regla, y lo que bloquea
    es integrar el cambio, no aprobar una regla. En la maquina de un usuario no
    hay `tests/`, asi que no corre.

    NO SE MIRA `evidencia.suite`. Ese campo es texto plano dentro de
    `data/reglas_aprendidas.json` y cualquiera puede escribir `true` dentro;
    creerselo convertiria una puerta que no se ha ejecutado en una puerta
    superada. Alli activan CUATRO puertas, no cinco, y la auditoria lo dice."""
    rid = str((regla or {}).get("id") or "")
    audit.log("puerta_suite", actor="nexus", targets=[rid],
              interpreted=str((regla or {}).get("destino") or ""),
              result="no_aplicable",
              error="no hay tests/ en una instalacion de usuario: aqui activan "
                    "cuatro puertas, no cinco")
    return "no_aplicable"


# ═══════════════════════════════════════════════════════════════════════════
#  OBSERVAR UNA CORRECCION — el hueco y el fallo, que no son lo mismo
# ═══════════════════════════════════════════════════════════════════════════
# NO SE JUZGA LA QUEJA: SE JUZGA SU ANTECEDENTE.
#
# «no, te he dicho que cierres chrome» no dice nada por si sola. Lo que hay que
# mirar es el turno ANTERIOR del operador —la frase que se enruto mal— y
# preguntarle al arbitro quien la atiende HOY. De esa respuesta sale todo:
#
#   planificador  -> nadie la atiende: hueco de enrutado, y ahi cabe una regla
#   skill:X/Y     -> la frase SI llega: el fallo esta dentro de la skill
#   charla/queja/memoria -> se la quedo un atajo ANTERIOR al router
#   regla:<id>    -> ya hay una regla aprendida y sigue sin funcionar
#
# Solo el primer caso puede generar una propuesta. En los otros tres nexus
# registra un AVISO y lo dice con esas palabras. Tapar un fallo de codigo con
# una regla lo esconde para siempre, y este proyecto no finge.

# Como se llama cada caso que NO es un hueco, y que se contesta en cada uno.
_ATAJOS = ("charla", "queja", "memoria")

# LA FORMULA DE ENSENNANZA, COPIADA A PROPOSITO DE `brain._TEACH_RX`.
#
# No se importa: `aprendizaje` no puede nombrar a `brain` sin abrir el quinto
# ciclo de `CAPAS.md`, y un hueco registrado para una expresion regular seria
# mas maquinaria que la propia expresion. La copia se paga con una prueba que
# ejecuta las dos sobre el mismo puñado de frases y exige que contesten igual:
# si una cambia y la otra no, la suite se pone roja el mismo dia.
_ENSENANZA_RX = re.compile(
    r"^\s*apr[eé]nde(?:te)?\s*(?:que\s+)?cuando\s+(?:te\s+)?diga\s+"
    r"[\"'«]?(?P<ph>.+?)[\"'»]?\s*,?\s+(?:haz|hagas|ejecuta|ejecutes|significa|"
    r"es|quiero\s+que\s+hagas|pon(?:gas)?)\s+"
    r"[\"'«]?(?P<order>.+?)[\"'»]?\s*\.?\s*$", re.IGNORECASE)


def _norm(s: str) -> str:
    """La normalizacion de frases vive en `dominio/selflearn`, no aqui.

    Estaba copiada linea a linea con el argumento de que `aprendizaje` no puede
    importar `brain`. Cierto, pero la pregunta era otra: esto es una regla de
    dominio, y `aplicacion` SI puede bajar a `dominio`. Se deja el nombre corto
    para no tocar las llamadas."""
    return selflearn.normaliza(s)


def _ahora() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _identificador(prefijo: str, *partes: str) -> str:
    """Un id ESTABLE para la misma correccion.

    Sin esto, corregir dos veces lo mismo dejaria dos apuntes distintos y la
    lista de «que has aprendido» se llenaria de duplicados. `guardar()` sustituye
    por id, asi que un id derivado del contenido convierte la repeticion en una
    actualizacion."""
    crudo = "|".join(_norm(p) for p in partes)
    return f"{prefijo}-{hashlib.sha1(crudo.encode('utf-8')).hexdigest()[:6]}"


def _mensaje_aviso(clase: str, frase: str, veredicto: str) -> str:
    if clase == "fallo_de_codigo":
        return (f"«{frase}» ya llega a {veredicto}, asi que el enrutado no falla: "
                "el fallo esta dentro de esa skill. Una regla lo taparia, y no se "
                "aprende sobre un fallo de codigo.")
    if clase == "atajo_previo":
        return (f"«{frase}» se la queda el atajo «{veredicto}», que corre ANTES del "
                "router. Las reglas aprendidas van detras del router, asi que este "
                "mecanismo no lo arregla: hay que tocar el atajo.")
    if clase == "ya_hay_regla":
        return (f"«{frase}» ya la atiende una regla aprendida ({veredicto}) y aun asi "
                "no ha salido bien. Otra regla encima no lo arregla: revisa esa, o el "
                "destino al que apunta.")
    return (f"«{frase}» no ha llegado a ninguna skill y la correccion tampoco senala "
            "a cual deberia ir. Eso necesita una skill nueva, y nexus no escribe "
            "codigo: escribela tu, o dimelo con «aprende que cuando diga X hagas Y».")


def _guarda_aviso(clase: str, frase: str, veredicto: str, correccion: str,
                  canal: str) -> dict:
    """Deja constancia de que esa correccion NO era materia de regla.

    Vive en el mismo almacen con `tipo: "aviso"`, y por eso no se activa nunca:
    `activas()` solo mira las de enrutado y `valida()` rechaza un aviso antes de
    la primera puerta. Queda en `propuesta` —que aqui significa «abierto»— hasta
    que alguien lo cierre pasandolo a `descartada`: molestar hasta que se arregle
    de verdad es la decision 3 del duenno."""
    aviso = {
        "id": _identificador("a", clase, frase),
        "esquema": reglas.ESQUEMA,
        "tipo": "aviso",
        "revision": 1,
        "clase": clase,
        "origen": {"frase": frase, "canal": canal or "pc", "fecha": _ahora(),
                   "tipo": "observada", "veces": 1, "correccion": correccion},
        "destino": veredicto,
        "mensaje": _mensaje_aviso(clase, frase, veredicto),
        "evidencia": {"veredicto": veredicto, "suite": None},
        "estado": "propuesta",
    }
    try:
        reglas.guardar(aviso)
    except Exception as e:                                 # noqa: BLE001
        # Que no se pueda apuntar el aviso no puede tumbar la conversacion: se
        # deja en la auditoria y se devuelve igual, para que al menos se diga.
        audit.log("aviso_no_guardado", actor="nexus", result=clase, error=str(e))
    return dict(aviso)


def _destino_pretendido(reparacion: str) -> str:
    """El «carpeta/intent» que senala la reparacion, o '' si no senala ninguno.

    El destino no se adivina: sale de la frase con la que el operador ARREGLO la
    orden, preguntandole al arbitro a quien llega. Si esa frase tampoco llega a
    ninguna skill, no hay destino que proponer — y eso NO es un fallo del
    mecanismo, es que lo que se pide no lo sabe hacer nadie."""
    # AQUI `reglas=()` SI ES LO CORRECTO, y no es el mismo caso que en `observa()`.
    #
    # Alli el conjunto vacio mataba la fila «ya hay una regla». Aqui se busca lo
    # contrario: el destino NATIVO que hay detras de la reparacion. Con las
    # activas puestas, una regla aprendida que ya case la reparacion contestaria
    # `regla:<id>`, que no empieza por `skill:` y saldria como «sin capacidad» —
    # y aunque se leyera, apuntar una regla nueva a OTRA regla no lleva a ningun
    # sitio. Se pregunta con el conjunto vacio a proposito: se quiere saber quien
    # atiende esa frase POR CODIGO.
    veredicto = reglas.arbitro((reparacion or "").strip(), reglas=())
    if not veredicto.startswith("skill:"):
        return ""
    destino = veredicto[len("skill:"):]
    return destino if existe_destino(destino) else ""


def _patron_literal(frase: str) -> str:
    """La frase, anclada por los dos lados y con los espacios flexibles.

    Es el patron mas ESTRECHO posible: casa esa frase y ninguna otra. Es el
    suelo al que se cae cuando no hay generalizacion, y por eso se escapa cada
    palabra: una frase del operador puede traer parentesis o interrogantes, y
    pegarlos crudos en una expresion regular la convertiria en otra cosa."""
    palabras = [re.escape(p) for p in (frase or "").split()]
    return r"^\s*" + r"\s+".join(palabras) + r"\s*$"


def _propone(frase: str, reparacion: str, evidencia_tipo: str, correccion: str,
             canal: str) -> dict:
    """La rama del HUECO: nadie atiende `frase` y `reparacion` dice quien deberia."""
    destino = _destino_pretendido(reparacion)
    if not destino:
        # NI SE PROPONE, NI SE ACUMULA EVIDENCIA. Lo que se pide no lo sabe hacer
        # nadie: eso necesita una skill nueva, y nexus no escribe codigo. Contar
        # ocurrencias de algo inalcanzable solo engordaria el fichero esperando
        # un umbral que, aunque se cumpliera, no llevaria a ninguna parte.
        return _guarda_aviso("sin_capacidad", frase, "planificador", correccion, canal)

    # UMBRAL DE EVIDENCIA. Una orden explicita del duenno entra a la primera:
    # es una orden, no una sospecha. Lo que nexus DEDUCE observando espera a
    # tener varias pruebas, y una prueba es un DIA distinto: repetir la misma
    # queja tres veces seguidas de rabia es un enfado, no tres pruebas.
    if evidencia_tipo == "ordenada":
        veces = 1
    else:
        veces = reglas.anota_ocurrencia(frase)
        if veces < reglas.umbral("umbral_observada", 3):
            return {}

    literal = _patron_literal(frase)
    regla = {
        "id": _identificador("r", frase),
        "esquema": reglas.ESQUEMA,
        "tipo": "enrutado",
        "revision": 1,
        "origen": {"frase": frase, "canal": canal or "pc", "fecha": _ahora(),
                   "tipo": evidencia_tipo, "veces": veces, "correccion": correccion},
        "destino": destino,
        "patron": literal,
        "evidencia": {"origen": evidencia_tipo, "veces": veces, "generalizado": False,
                      "arrastradas": [], "suite": None},
        "estado": "propuesta",
    }

    # EL MODELO SOLO PUEDE ENSANCHAR, Y SU SALIDA ES ENTRADA DE LAS PUERTAS.
    #
    # Se le pide una version mas ancha del patron y se la manda a validar tal
    # cual. Si pasa, manda; si no pasa —o si no hay modelo— se queda el literal,
    # que es mas estrecho pero valido. El aprendizaje degrada, no desaparece, y
    # en ningun momento el modelo ha emitido un veredicto.
    candidato = selflearn.generaliza_patron(frase)
    ok, motivo = True, ""
    if candidato and candidato != literal:
        ancha = dict(regla)
        ancha["patron"] = candidato
        ok, motivo = valida(ancha)
        if ok:
            regla["patron"] = candidato
            regla["evidencia"]["generalizado"] = True
        else:
            audit.log("generalizacion_descartada", actor="nexus",
                      targets=[regla["id"]], interpreted=candidato,
                      result="cae_al_patron_literal", error=motivo)
    if regla["patron"] == literal:
        ok, motivo = valida(regla)
    if not ok:
        # Pasar el umbral de evidencia NO exime de pasar las puertas. Se dice en
        # la auditoria y no se propone: una propuesta que no puede activarse solo
        # sirve para gastarle el tiempo a quien revise la tanda.
        audit.log("propuesta_descartada", actor="nexus", targets=[regla["id"]],
                  interpreted=destino, result="no_pasa_las_puertas", error=motivo)
        return {}
    regla["evidencia"]["arrastradas"] = barrido(regla).get("arrastradas", [])
    reglas.guardar(regla)
    return dict(regla)


def observa(correccion: str, antecedente: str = "", canal: str = "pc") -> dict:
    """Mira una correccion y devuelve una propuesta, un aviso, o nada.

    `correccion` es lo que acaba de decir el operador; `antecedente` es su turno
    ANTERIOR, que es lo que de verdad se juzga. Si no llega, se busca en
    `interactions.jsonl` a traves de `selflearn`: el cerebro tiene el historial
    en RAM, pero una correccion que llega por otro canal no lo comparte.

    La formula explicita («aprende que cuando diga X hagas Y») trae dentro las
    dos frases, asi que se mira ANTES que el antecedente: ahi no hay nada que
    deducir, el duenno lo ha dicho.

    Devuelve `{}` cuando no hay nada que decir —y en particular cuando NADIE ha
    registrado el arbitro, porque juzgar sin saber enrutar seria adivinar."""
    registrar()
    correccion = (correccion or "").strip()
    orden = _ENSENANZA_RX.match(correccion)
    if orden:
        frase = orden.group("ph").strip()
        reparacion = orden.group("order").strip()
        evidencia_tipo = "ordenada"
    else:
        frase = (antecedente or "").strip() or selflearn.ultima_orden(excluir=correccion)
        reparacion = correccion
        evidencia_tipo = "observada"
    if not frase:
        return {}

    # SE PREGUNTA CON LAS REGLAS ACTIVAS PUESTAS, y no con `reglas=()`.
    #
    # `()` es el conjunto vacio, y con el el arbitro NUNCA puede contestar
    # `regla:<id>`: la fila «ya hay una regla» de la tabla de veredictos no se
    # ejecutaba jamas. El precio de esa fila muerta no era teorico — la frase
    # volvia a caer en `planificador`, se volvia a proponer, y como `guardar()`
    # sustituye por id, la regla que el duenno YA HABIA APROBADO regresaba a
    # `propuesta`: una correccion desactivaba en silencio una aprobacion.
    #
    # Se pasan las activas de forma EXPLICITA en vez de `reglas=None` porque
    # `None` deja que sea el arbitro quien vaya a buscarlas, y aqui interesa que
    # el conjunto con el que se juzga sea el mismo que se puede enseñar.
    veredicto = reglas.arbitro(frase, reglas=tuple(reglas.activas()))
    if not veredicto:
        # Cadena vacia es «no lo se», no «planificador». Sin arbitro no se juzga.
        return {}
    if veredicto.startswith("skill:"):
        return _guarda_aviso("fallo_de_codigo", frase, veredicto, correccion, canal)
    if veredicto in _ATAJOS:
        return _guarda_aviso("atajo_previo", frase, veredicto, correccion, canal)
    if veredicto.startswith("regla:"):
        return _guarda_aviso("ya_hay_regla", frase, veredicto, correccion, canal)
    return _propone(frase, reparacion, evidencia_tipo, correccion, canal)


# El hueco se rellena al importarse, como hace `comun/events`. Nada de produccion
# importa este modulo en el bloque B, asi que esto no cambia nada en marcha: lo
# que activa reglas es el arbitro, y el arbitro lo registra el cerebro (bloque C).
registrar()
