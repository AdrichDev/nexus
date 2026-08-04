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

Bloque B de 004: este modulo sabe JUZGAR una regla. Proponerlas, aprobarlas por
tandas y consultarlas en caliente es el bloque C. Nada de produccion lo importa
todavia, asi que con este bloque aplicado nexus se comporta exactamente igual
que antes.
"""
from __future__ import annotations

from ..comun import audit
from ..dominio import reglas
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


# El hueco se rellena al importarse, como hace `comun/events`. Nada de produccion
# importa este modulo en el bloque B, asi que esto no cambia nada en marcha: lo
# que activa reglas es el arbitro, y el arbitro lo registra el cerebro (bloque C).
registrar()
