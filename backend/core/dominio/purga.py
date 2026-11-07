"""
nexus — purga.py (002-memoria-y-conocimiento, bloque B).

Motor de reglas explicable para retirar de `data/memory/` y de `memories` lo
que ya no aporta. NINGÚN LLM decide: solo palabras/umbrales de
`config/umbrales.json` (bloque `purga`), y cada resultado lleva la regla
concreta que lo clasificó.

Protocolo (innegociable, ver CLAUDE.md y las specs `memoria-purga` /
`memoria-deduplicacion`):
  1. `previsualizar()` SIEMPRE antes de `aplicar()` — nada preseleccionado.
  2. `aplicar()` confirma UNA categoría (o varias, explícitas) cada vez,
     nunca «purgar todo»; rechaza plan desconocido, caducado o rancio
     (huella del corpus cambiada desde la previsualización).
  3. Retirar = mover a papelera (ESTADO reversible, dos tiempos): la nota
     `.md` se mueve dentro de `data/memory/papelera/`, la fila Postgres solo
     recibe `retirado_en`/`retirado_lote`. Nada se destruye aquí.
  4. `exportar()`/`borrar_definitivo()` son el PASO 2 — SOLO los inicia el
     operador; el scheduler nunca los toca (ver `scheduler.py`, sin
     referencia alguna a papelera).
  5. Categoría personal: exporta una copia legible ANTES de mover; el
     borrado duro NUNCA es su acción por defecto.
  6. BARRIDO COMPLETO (PRIV-03 / roadmap P2-8, ver `B3.5`): la retirada no
     termina en la nota y en la fila. `previsualizar()` ENSEÑA la lista de
     almacenes que se van a tocar —y de los que NO se pueden tocar, con su
     motivo— y `aplicar()` actúa sobre ESA lista, ni una tienda más. Un
     «olvida X» deja de dejar copias en `knowledge.jsonl`, en el espejo de
     documentos, en la memoria operativa y en Engram; los registros de
     conversación son un alcance APARTE que el operador tiene que pedir
     (`incluir_logs=True`), y las copias de seguridad NO se reescriben: se
     nombran, con sus fechas, para que el operador decida.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
import unicodedata
import uuid
from pathlib import Path

from ..comun import permissions
from ..comun.atomicos import escribir_json_atomico
from ..comun.config import CONFIG_DIR, DATA_DIR, settings

MEMORY_DIR = DATA_DIR / "memory"
PAPELERA_DIR = MEMORY_DIR / "papelera"
PAPELERA_FILE = PAPELERA_DIR / "papelera.json"
EXPORT_DIR = DATA_DIR / "exportado_purga"
# Espejo de la ingesta (`ingesta.DOCUMENTOS_DIR`). Se declara aquí para que la
# purga pueda barrerlo aunque `ingesta` no esté importado, y una prueba
# estructural comprueba que las dos rutas son la MISMA: si alguien mueve el
# espejo, el barrido se entera en rojo y no en silencio.
DOCUMENTOS_DIR = MEMORY_DIR / "documentos"

# Excluidos SIEMPRE de la clasificación: daily/ es log de conversación (igual
# que NoteGraph.search()), papelera/ es lo ya retirado (no se re-clasifica).
_CARPETAS_EXCLUIDAS = ("daily", "papelera")

_planes: dict[str, dict] = {}          # previsualizar() en vuelo, por plan_id


def _umbrales_purga() -> dict:
    """Reglas de clasificación: las que se publican, más las tuyas.

    `umbrales.json` solo lleva TIPOS de documento genéricos («curriculum»,
    «empadronamiento»). Los nombres propios —tu apellido, tu centro de estudios,
    tus asignaturas— van a `purga_local.json`, que está fuera del repositorio.
    Es lo mismo que se hace con `settings.json`: lo que sirve a cualquiera se
    publica, lo que te identifica se queda en tu máquina.

    Las palabras de las dos fuentes se suman por categoría."""
    base: dict = {}
    try:
        f = CONFIG_DIR / "umbrales.json"
        if f.is_file():
            base = (json.loads(f.read_text(encoding="utf-8")) or {}).get("purga") or {}
    except Exception:
        return {}

    try:
        local = CONFIG_DIR / "purga_local.json"
        if not local.is_file():
            return base
        extra = (json.loads(local.read_text(encoding="utf-8")) or {}).get("categorias") or {}
    except Exception:
        return base

    cats = {k: dict(v) if isinstance(v, dict) else v
            for k, v in (base.get("categorias") or {}).items()}
    for cat_id, cfg in extra.items():
        if not isinstance(cfg, dict):
            continue
        destino = cats.setdefault(cat_id, {})
        palabras = list(destino.get("palabras") or []) + list(cfg.get("palabras") or [])
        destino["palabras"] = sorted(set(palabras))
        for clave in ("personal", "minimo_aciertos"):
            if clave in cfg:
                destino[clave] = cfg[clave]
    return {**base, "categorias": cats}


def _notas() -> list[Path]:
    out = []
    for p in MEMORY_DIR.rglob("*.md"):
        try:
            rel = p.relative_to(MEMORY_DIR)
        except ValueError:
            continue
        if rel.parts and rel.parts[0] in _CARPETAS_EXCLUIDAS:
            continue
        out.append(p)
    return out


# ---------------------------------------------------------------------
#  B2.1 — clasificación explicable
# ---------------------------------------------------------------------
def clasificar() -> dict:
    """`{ruta_relativa: {categoria, personal, regla, ruta_abs}}` de cada nota
    que casa con alguna regla. Lo que no casa con nada queda FUERA de este
    dict — no aparece en ninguna previsualización (memoria-purga, «Nota sin
    categoría reconocida»). Empate entre categorías (mismo nº de aciertos):
    se queda sin clasificar, no se toca."""
    categorias = _umbrales_purga().get("categorias") or {}
    out: dict[str, dict] = {}
    for path in _notas():
        try:
            texto = f"{path.name}\n{path.read_text(encoding='utf-8', errors='replace')}".lower()
        except Exception:
            continue
        candidatas = []
        for cat_id, cfg in categorias.items():
            palabras = cfg.get("palabras") or []
            if not palabras:
                continue
            hits = [w for w in palabras if str(w).lower() in texto]
            if len(hits) >= int(cfg.get("minimo_aciertos", 1)):
                candidatas.append((len(hits), cat_id, hits))
        if not candidatas:
            continue
        candidatas.sort(key=lambda c: -c[0])
        if len(candidatas) > 1 and candidatas[0][0] == candidatas[1][0]:
            continue
        n, cat_id, hits = candidatas[0]
        out[str(path.relative_to(MEMORY_DIR))] = {
            "categoria": cat_id,
            "personal": bool(categorias[cat_id].get("personal", False)),
            "regla": f"{n} coincidencia(s) de «{cat_id}»: {', '.join(hits[:5])}",
            "ruta_abs": str(path),
        }
    return out


def _huella_corpus() -> dict:
    """Nº de notas + mtime máximo + nº de filas de `memories`: si CUALQUIERA
    cambia entre `previsualizar()` y `aplicar()`, el plan queda rancio
    (memoria-purga, «Aplicar sin previsualización vigente»)."""
    notas = _notas()
    n_filas = 0
    try:
        from . import memory
        if memory.pg.online:
            n_filas = memory.pg._rows("SELECT count(*) AS n FROM memories")[0]["n"]
    except Exception:
        pass
    return {"n_notas": len(notas),
            "mtime_max": max((p.stat().st_mtime for p in notas), default=0.0),
            "n_filas": n_filas}


# ---------------------------------------------------------------------
#  B2.1-bis — segundo camino: filas huérfanas casadas por CONTENIDO
#
#  INCIDENTE (medido sobre la base real, 01/08/2026): `previsualizar()`
#  devolvía `filas_pg: 0` en TODAS las categorías. `filas_ligadas_a_nota()`
#  ata fila y nota por la marca de origen `[fichero]` que escribe el buzón,
#  y solo 233 de las 697 filas `knowledge` la llevan; las otras 464 son
#  anteriores al bloque C y quedaron huérfanas. Consecuencia verificada:
#  retirar las 35 notas de la FP habría dejado 10 filas con tablespaces,
#  actividades y 2DAM VIVAS y buscables en la memoria vectorial — justo lo
#  contrario de lo que se pidió.
#
#  Este segundo camino NO sustituye al primero: la marca de origen sigue
#  mandando cuando existe. Solo entra cuando una nota no tiene NINGUNA fila
#  marcada. El criterio es de vocabulario, explicable y sin LLM: se exige
#  que la NOTA cubra casi todo el vocabulario de la FILA (no al revés), que
#  es la dirección conservadora — una fila ajena siempre trae términos que
#  la nota no tiene. Ante la duda NO se casa: es peor llevarse una fila
#  ajena que dejar una propia.
# ---------------------------------------------------------------------
_RE_TERMINO = re.compile(r"[0-9a-záéíóúüñçàèìòùâêîôû]+")

_CONTENIDO_POR_DEFECTO = {
    "activo": True,
    "tipos": ["knowledge"],
    "longitud_minima_termino": 4,
    "minimo_terminos_fila": 6,
    "minimo_terminos_comunes": 6,
    "solape_minimo": 0.75,
    "palabras_vacias": [],
}


def _cfg_contenido() -> dict:
    """Umbrales del emparejamiento por contenido. NUNCA a fuego: salen de
    `config/umbrales.json` → `purga.emparejar_por_contenido`. Los valores de
    `_CONTENIDO_POR_DEFECTO` solo tapan el hueco de una clave que falte, para
    que un JSON incompleto no reviente la previsualización."""
    cfg = dict(_CONTENIDO_POR_DEFECTO)
    cfg.update(_umbrales_purga().get("emparejar_por_contenido") or {})
    return cfg


def terminos(texto: str, cfg: dict | None = None) -> set[str]:
    """Vocabulario distintivo de un texto: palabras normalizadas (NFKC +
    minúsculas) de al menos `longitud_minima_termino` caracteres que no
    estén en `palabras_vacias`. Se conservan las tildes a propósito
    («año» ≠ «ano», la misma razón que en `memory.huella()`)."""
    cfg = cfg or _cfg_contenido()
    minimo = int(cfg.get("longitud_minima_termino", 4))
    vacias = {str(w).lower() for w in (cfg.get("palabras_vacias") or [])}
    plano = unicodedata.normalize("NFKC", texto).lower()
    return {t for t in _RE_TERMINO.findall(plano)
            if len(t) >= minimo and t not in vacias}


# ── UNA CONSULTA CON NOMBRE PROPIO (T37) ──────────────────────────────────────
# El clasificador de arriba solo conoce las categorías CERRADAS de
# `umbrales.json`/`purga_local.json`. Un «olvida que me divorcié» dicho por voz no
# es una categoría: es el operador nombrando una nota con sus propias palabras, y
# sin esto no había forma de que llegara a la previsualización. La selección la
# hace `_notas_de_la_consulta()`; esta constante es el id de la categoría con la
# que viajan las notas que NO estaban clasificadas en ninguna otra.
CATEGORIA_CONSULTA = "consulta"


def consulta_util(consulta: str) -> tuple[bool, str]:
    """¿La frase con la que se pide olvidar sirve para barrer algo? `(ok, motivo)`.

    Reusa la regla que YA decide qué palabra es distintiva (`terminos()`:
    `longitud_minima_termino` caracteres y fuera de `palabras_vacias`) en vez de
    inventar un mínimo nuevo. Una consulta sin ninguna palabra distintiva
    —«olvida eso», «olvida la cosa»— no selecciona nada y podría arrastrar media
    memoria, así que se rechaza y se pide una frase más concreta. El umbral es
    DATO: sale de `config/umbrales.json → purga.emparejar_por_contenido`."""
    cfg = _cfg_contenido()
    if terminos(consulta or "", cfg):
        return True, ""
    minimo = int(cfg.get("longitud_minima_termino", 4))
    return False, (f"«{(consulta or '').strip()}» no tiene ninguna palabra distintiva: "
                   f"hacen falta palabras de {minimo}+ caracteres que no sean de "
                   f"relleno («eso» no sirve)")


def titulo_encabezado(texto: str) -> str:
    """Primera línea de un texto si es un encabezado markdown, ya limpia.

    Es la OTRA marca de origen, más vieja que `[fichero]`: el importador que
    dejó las 464 filas huérfanas escribía el nombre del documento como título
    (`# doc CV_ADRIAN_CHOZAS_VINUESA`). Es exacta, así que no necesita
    umbrales — y rescata las filas que el vocabulario no puede juzgar, como
    el CV, que salió del PDF con las letras separadas («T é c n i c o») y
    solo deja cuatro términos utilizables."""
    primera = (texto or "").lstrip().split("\n", 1)[0].strip()
    if not primera.startswith("#"):
        return ""
    return " ".join(primera.lstrip("#").split()).casefold()


def emparejar_por_contenido(nombre_nota: str, terminos_nota: set,
                            huerfanas: list[dict], cfg: dict | None = None,
                            ya_asignadas: set | None = None) -> list[dict]:
    """Filas huérfanas que se llevaría esta nota, cada una CON SU MOTIVO.

    `huerfanas` es `[{"id": int, "terminos": set[str], "titulo": str}]`,
    calculado una sola vez por previsualización. Casan, por este orden:
      1. la fila cuyo encabezado es EXACTAMENTE el nombre de la nota;
      2. si no, por vocabulario, y solo si:
         * tiene al menos `minimo_terminos_fila` términos propios — con
           menos no hay materia para juzgarla y NO se casa;
         * comparte al menos `minimo_terminos_comunes` con la nota;
         * la nota cubre `solape_minimo` de su vocabulario.
    Una fila ya asignada a otra nota no se reclama dos veces."""
    cfg = cfg or _cfg_contenido()
    min_fila = int(cfg.get("minimo_terminos_fila", 6))
    min_comunes = int(cfg.get("minimo_terminos_comunes", 6))
    solape_min = float(cfg.get("solape_minimo", 0.75))
    ya = ya_asignadas if ya_asignadas is not None else set()
    titulo_nota = " ".join(Path(nombre_nota).stem.split()).casefold()
    out: list[dict] = []
    for fila in huerfanas:
        if fila["id"] in ya:
            continue
        if titulo_nota and fila.get("titulo") == titulo_nota:
            out.append({
                "id": fila["id"], "encabezado": True, "solape": 1.0,
                "comunes": len(fila["terminos"]),
                "motivo": (f"encabezado de origen «# {Path(nombre_nota).stem}» "
                           f"en la primera línea de la fila"),
            })
            continue
        propios = fila["terminos"]
        if len(propios) < min_fila:
            continue
        comunes = propios & terminos_nota
        if len(comunes) < min_comunes:
            continue
        solape = len(comunes) / len(propios)
        if solape < solape_min:
            continue
        out.append({
            "id": fila["id"],
            "encabezado": False,
            "solape": round(solape, 4),
            "comunes": len(comunes),
            "motivo": (f"fila sin marca de origen: «{nombre_nota}» cubre el "
                       f"{solape:.0%} de su vocabulario ({len(comunes)} de "
                       f"{len(propios)} términos: "
                       f"{', '.join(sorted(comunes)[:5])}…), umbral "
                       f"{solape_min:.0%}"),
        })
    return out


def _huerfanas_con_terminos(cfg: dict) -> list[dict]:
    """Pool de filas huérfanas del almacén, troceado en términos UNA sola vez
    por previsualización: son ~464 filas y recorrerlas nota a nota sería
    tirar el tiempo."""
    from . import memory
    if not cfg.get("activo", True) or not memory.pg.online:
        return []
    try:
        filas = memory.pg.filas_sin_marca_origen(cfg.get("tipos"))
    except Exception:
        return []
    return [{"id": f["id"],
             "terminos": terminos(f.get("content") or "", cfg),
             "titulo": titulo_encabezado(f.get("content") or "")}
            for f in filas]


# ---------------------------------------------------------------------
#  B2.2 — previsualización obligatoria y previa
# ---------------------------------------------------------------------
def _notas_del_plan(categorias: list[dict]) -> list[dict]:
    """Las notas que el plan retiraría, con su texto ya troceado en muestras.

    Se lee AQUÍ y no al aplicar: cuando `aplicar()` ejecuta, la nota ya está en la
    papelera y su texto hay que haberlo leído antes (y lo que la previsualización
    enseñó es lo que se barre después)."""
    out: list[dict] = []
    for cat in categorias:
        for item in cat.get("items") or []:
            ruta = item.get("ruta")
            if not ruta:
                continue                     # item del camino de filas sueltas
            try:
                texto = (MEMORY_DIR / ruta).read_text(encoding="utf-8", errors="replace")
            except Exception:                                  # noqa: BLE001
                texto = ""
            out.append({"categoria": cat["id"], "ruta": ruta,
                        "nombre": Path(ruta).name, "muestras": _muestras(texto)})
    return out


def _casa_palabra(buscada: str, propias: set, corte: int) -> bool:
    """¿La nota tiene esta palabra de la consulta?

    Igual, o con los primeros `corte` caracteres en común: eso es lo que empareja
    «divorcié» con «divorcio» sin meter un diccionario ni un stemmer. `corte` es
    `longitud_minima_termino`, el mismo mínimo con el que `terminos()` decide qué
    palabra cuenta — una sola definición de «palabra» en todo el módulo."""
    # `corte` viene de `umbrales.json`: si alguien lo deja en 0, el prefijo sería
    # la cadena vacía y CUALQUIER palabra casaría. Un valor absurdo en la
    # configuración no puede ensanchar lo que se purga.
    corte = max(1, int(corte or 1))
    prefijo = buscada[:corte]
    for p in propias:
        if p == buscada or (len(p) >= corte and p.startswith(prefijo)):
            return True
    return False


def _notas_de_la_consulta(consulta: str, clasif: dict) -> dict:
    """Las notas que HABLAN de lo que el operador ha nombrado, con su motivo.

    Devuelve el mismo `{ruta_rel: {categoria, personal, regla, ruta_abs}}` que
    `clasificar()`, para que el resto de la previsualización (filas ligadas,
    huérfanas por contenido, inventario de almacenes, `aplicar()`) siga
    funcionando sin una sola rama nueva.

    Casa por DOS caminos, los dos explicables:
      1. la nota CONTIENE la frase tal cual, normalizada con `_plano()` (la misma
         normalización que usa el cotejo del barrido: una sola definición de «el
         mismo texto»);
      2. la nota tiene TODAS las palabras distintivas de la consulta.

    Se exige que casen TODAS, no una: aquí un falso positivo significa enseñar —y
    luego mover— una nota que no era, así que ante la duda NO se casa.

    `personal` a True en la categoría de consulta es deliberado: lo que el
    operador guardó de sí mismo se exporta legible ANTES de moverse (la regla de
    las categorías personales de la purga), y el borrado duro sigue sin ser su
    acción por defecto."""
    cfg = _cfg_contenido()
    corte = int(cfg.get("longitud_minima_termino", 4))
    buscados = terminos(consulta, cfg)
    frase = _plano(consulta)
    out: dict[str, dict] = {}
    for path in _notas():
        # El espejo de la ingesta NO es una nota: es material DERIVADO que viaja a
        # la papelera con su nota, y lo barre `_barrer_documentos()`. Seleccionarlo
        # aquí lo metería dos veces en el mismo lote y los dos movimientos se
        # pelearían por el mismo nombre en la papelera.
        if _dentro(path, DOCUMENTOS_DIR):
            continue
        try:
            texto = f"{path.name}\n{path.read_text(encoding='utf-8', errors='replace')}"
        except Exception:                                  # noqa: BLE001
            continue
        plano = _plano(texto)
        if frase and frase in plano:
            motivo = f"contiene «{consulta.strip()}» tal cual"
        elif buscados and all(_casa_palabra(t, terminos(plano, cfg), corte)
                              for t in buscados):
            motivo = ("comparte " + ", ".join(sorted(buscados)) +
                      f" (hacen falta todas las palabras distintivas de la consulta)")
        else:
            continue
        rel = str(path.relative_to(MEMORY_DIR))
        info = clasif.get(rel)
        out[rel] = {
            "categoria": info["categoria"] if info else CATEGORIA_CONSULTA,
            "personal": bool(info["personal"]) if info else True,
            "regla": (f"lo nombras tú: {motivo}" if not info else
                      f"lo nombras tú: {motivo}; además está en la categoría "
                      f"«{info['categoria']}» por {info['regla']}"),
            "ruta_abs": str(path),
        }
    return out


def previsualizar(incluir_logs: bool = False, consulta: str = "") -> dict:
    """`{id, caduca, categorias, almacenes, incluir_logs, consulta}`. NO cambia
    nada — ni un fichero se mueve, ni una fila se toca. Ninguna categoría viene
    marcada.

    `consulta` (T37, aditivo): en vez de barrer TODAS las categorías conocidas,
    se barre solo lo que HABLE de lo que el operador ha nombrado («olvida que me
    divorcié»). Sin `consulta` el comportamiento es exactamente el de siempre.
    El resto del contrato no cambia: lo que se enseña aquí es lo que `aplicar()`
    ejecuta, y el «todavía no se ha tocado nada» sigue siendo literal.

    Cada fila llega con SU motivo, igual que las notas: o la marca de origen la
    delata, o la casó el vocabulario (y entonces se dice cuánto solapa).
    `aplicar()` retira exactamente estos ids, no los que recalcule después: lo
    que se enseña es lo que se hace.

    `almacenes` es la otra mitad del contrato (PRIV-03): la lista de TODOS los
    sitios donde el hecho está copiado —cuáles se van a tocar, cuáles no se
    pueden tocar y por qué (Engram caído, servidor sin borrado), cuáles son
    opcionales y no se incluyeron, y qué copias de seguridad lo conservan, con
    sus fechas—. `aplicar()` ejecuta ESA lista y ninguna otra.

    `incluir_logs=True` mete en el alcance los registros de conversación, de
    auditoría, de recall y los resultados de trabajos. Por defecto NO: son la
    traza del incidente y la regla es no tocar lo que no se pidió."""
    from . import memory
    consulta = (consulta or "").strip()
    clasif = clasificar()
    if consulta:
        # La consulta SUSTITUYE a la clasificación cerrada como criterio de
        # selección: el operador ha dicho con sus palabras qué quiere olvidar, y
        # barrer además todo lo que casara con una categoría de `umbrales.json`
        # sería tocar lo que nadie pidió.
        clasif = _notas_de_la_consulta(consulta, clasif)
    cfg = _umbrales_purga().get("categorias") or {}
    cfg_cont = _cfg_contenido()
    huerfanas = _huerfanas_con_terminos(cfg_cont)
    por_ruta: dict[str, list] = {}
    # Una fila huérfana puede parecerse a varias notas. Se la queda la que
    # MEJOR la explica (mayor solape, luego más términos comunes), no la
    # primera del recorrido: así el motivo que lee el usuario es el bueno.
    disputa: dict[int, tuple] = {}
    for ruta in sorted(clasif):
        info = clasif[ruta]
        nombre = Path(info["ruta_abs"]).name
        marcadas = memory.pg.filas_ligadas_a_nota(nombre) if memory.pg.online else []
        por_ruta[ruta] = [{"id": f["id"],
                           "motivo": f"marca de origen «[{nombre}]» en el propio texto"}
                          for f in marcadas]
        if por_ruta[ruta] or not huerfanas:
            continue
        # Segundo camino, SOLO sin marca: ver el bloque B2.1-bis.
        try:
            cuerpo = Path(info["ruta_abs"]).read_text(encoding="utf-8", errors="replace")
        except Exception:
            cuerpo = ""
        for f in emparejar_por_contenido(
                nombre, terminos(f"{nombre}\n{cuerpo}", cfg_cont), huerfanas, cfg_cont):
            clave = (f["encabezado"], f["solape"], f["comunes"])
            if f["id"] not in disputa or clave > disputa[f["id"]][0]:
                disputa[f["id"]] = (clave, ruta, f)
    for _clave, ruta, f in disputa.values():
        por_ruta[ruta].append({"id": f["id"], "motivo": f["motivo"]})

    por_cat: dict[str, list] = {}
    for ruta in sorted(clasif):
        filas = sorted(por_ruta[ruta], key=lambda x: x["id"])
        por_cat.setdefault(clasif[ruta]["categoria"], []).append({
            "ruta": ruta, "motivo": clasif[ruta]["regla"],
            "filas_pg": len(filas), "filas": filas})

    # Los duplicados exactos son filas SUELTAS de la base de datos, sin nota que
    # las nombre: no pueden casar con lo que el operador ha dicho, así que con
    # consulta NO entran (barrerlos sería tocar lo que no pidió).
    if not consulta and "duplicados-exactos" in cfg:
        grupos = memory.pg.duplicados_exactos() if memory.pg.online else []
        items = [{"ruta": None, "fila_id": fila["id"],
                  "motivo": (f"duplicado exacto de la huella {g['huella'][:12]}… "
                             f"(se conserva id {g['conservar']['id']})")}
                 for g in grupos for fila in g["sobran"]]
        if items:
            por_cat["duplicados-exactos"] = items

    categorias_out = [
        {"id": cat_id,
         # La categoría de la consulta es personal POR DEFINICIÓN (es lo que el
         # operador guardó de sí mismo): se exporta copia legible antes de mover
         # y el borrado duro no es su acción por defecto.
         "personal": (bool(cfg.get(cat_id, {}).get("personal", False))
                      or (bool(consulta) and cat_id == CATEGORIA_CONSULTA)),
         "items": items}
        for cat_id, items in por_cat.items()]
    plan_id = f"purga-{uuid.uuid4().hex[:10]}"
    minutos = int(_umbrales_purga().get("minutos_vigencia_plan", 30))
    caduca_dt = dt.datetime.now() + dt.timedelta(minutes=minutos)
    almacenes = _inventario_almacenes(_notas_del_plan(categorias_out), incluir_logs)
    plan = {"id": plan_id, "caduca": caduca_dt.isoformat(timespec="seconds"),
            "categorias": categorias_out, "almacenes": almacenes,
            "incluir_logs": bool(incluir_logs), "consulta": consulta}
    _planes[plan_id] = {**plan, "_caduca_dt": caduca_dt,
                        "_huella_corpus": _huella_corpus()}
    return plan


# ---------------------------------------------------------------------
#  B3.2 — retirada (papelera, primer tiempo)
# ---------------------------------------------------------------------
def _cargar_papelera() -> list[dict]:
    try:
        if PAPELERA_FILE.is_file():
            data = json.loads(PAPELERA_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def _guardar_papelera(items: list[dict]) -> None:
    PAPELERA_FILE.parent.mkdir(parents=True, exist_ok=True)
    # SIN TOPE a propósito (decisión de tasks.md): un límite aquí sería un
    # borrado automático encubierto. Solo se avisa, nunca se recorta.
    PAPELERA_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=1),
                             encoding="utf-8")
    aviso = int(_umbrales_purga().get("papelera_aviso_items", 3000))
    if len(items) >= aviso:
        try:
            from ..comun.events import bus
            bus.emit_sync("log", {"level": "warn",
                "msg": f"🗑️ Papelera de memoria: {len(items)} elemento(s) — solo "
                       f"aviso, nada se borra por su cuenta."})
        except Exception:
            pass


def _exportar_copia_personal(path: Path, lote: str) -> str | None:
    """Categoría personal: copia legible FUERA de `data/memory/`, ANTES de
    mover a papelera (memoria-purga, «Categoría personal — exportar, nunca
    borrado duro»)."""
    try:
        destino_dir = EXPORT_DIR / "personal" / lote
        destino_dir.mkdir(parents=True, exist_ok=True)
        destino = destino_dir / path.name
        shutil.copy2(path, destino)
        return str(destino)
    except Exception:
        return None


def retirar_nota(ruta_rel: str, lote: str) -> dict:
    """Mueve UNA nota a `papelera/{lote}/`. Enlaces simbólicos NUNCA se
    mueven — se listan aparte (matriz de amenazas «Escape por enlace
    simbólico»). Devuelve `{movido, razon}` o `{movido, ruta_papelera,
    sha256}`."""
    origen = MEMORY_DIR / ruta_rel
    if origen.is_symlink():
        return {"movido": False, "razon": "symlink: no se mueve, se lista aparte"}
    if not origen.is_file():
        return {"movido": False, "razon": "no existe (¿ya retirada?)"}
    destino_dir = PAPELERA_DIR / lote
    destino_dir.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(origen.read_bytes()).hexdigest()
    destino = destino_dir / origen.name
    origen.replace(destino)
    entradas = _cargar_papelera()
    entradas.append({
        "lote": lote, "nombre": origen.name, "ruta_original": str(origen),
        "ruta_papelera": str(destino), "sha256": sha,
        "retirado_en": dt.datetime.now().isoformat(timespec="seconds"),
    })
    _guardar_papelera(entradas)
    return {"movido": True, "ruta_papelera": str(destino), "sha256": sha}


def _retirar_categoria(cat: dict, lote: str) -> dict:
    from . import memory
    movidas = symlinks = filas = 0
    retiradas: list[dict] = []
    for item in cat["items"]:
        if item.get("ruta"):
            nombre = Path(item["ruta"]).name
            # El texto se lee ANTES de mover: después ya no está en su ruta y el
            # barrido de los demás almacenes necesita sus muestras.
            try:
                texto = (MEMORY_DIR / item["ruta"]).read_text(
                    encoding="utf-8", errors="replace")
            except Exception:                                  # noqa: BLE001
                texto = ""
            if cat["personal"]:
                _exportar_copia_personal(MEMORY_DIR / item["ruta"], lote)
            r = retirar_nota(item["ruta"], lote)
            if r["movido"]:
                movidas += 1
                retiradas.append({"categoria": cat["id"], "ruta": item["ruta"],
                                  "nombre": nombre, "muestras": _muestras(texto)})
            elif "symlink" in r.get("razon", ""):
                symlinks += 1
            if memory.pg.online:
                # Se retiran los ids QUE SE ENSEÑARON en la previsualización,
                # no los que se recalculen ahora: si no, lo aplicado podría no
                # ser lo revisado. Sin `filas` (plan viejo) se recalcula el
                # camino de la marca, que es el comportamiento de siempre.
                ids = [f["id"] for f in item.get("filas") or []]
                if not ids and "filas" not in item:
                    ids = [f["id"] for f in memory.pg.filas_ligadas_a_nota(nombre)]
                filas += memory.pg.retirar_filas(ids, lote)
        elif item.get("fila_id") and memory.pg.online:
            filas += memory.pg.retirar_filas([item["fila_id"]], lote)
    return {"notas": movidas, "symlinks_omitidos": symlinks, "filas": filas,
            "retiradas": retiradas}


# ---------------------------------------------------------------------
#  B3.1 — aplicar (categoría por categoría, plan vigente y NO rancio)
# ---------------------------------------------------------------------
def aplicar(plan_id: str, categorias: list[str], acepto_personal: bool = False,
            incluir_logs: bool = False) -> dict:
    """Retira las categorías confirmadas y BARRE los demás almacenes con la lista
    que enseñó la previsualización (PRIV-03).

    `incluir_logs` NO puede ampliar lo enseñado: si el plan se hizo sin los
    registros y aquí llega `True`, esto se niega y pide una previsualización
    nueva. El sentido contrario sí vale (un plan con registros se puede aplicar
    sin volver a pedirlos) porque entonces no se toca nada que no se viera.

    El informe que devuelve dice, almacén por almacén, qué se retiró, qué es
    restaurable, qué NO se pudo completar y qué sobrevive a propósito. Nunca un
    «borrado» a secas."""
    plan = _planes.get(plan_id)
    if not plan:
        return {"ok": False, "error": f"plan «{plan_id}» desconocido o caducado"}
    if dt.datetime.now() > plan["_caduca_dt"]:
        _planes.pop(plan_id, None)
        return {"ok": False, "error": "el plan ha caducado, pide una previsualización nueva"}
    if _huella_corpus() != plan["_huella_corpus"]:
        return {"ok": False, "error": (
            "el plan está rancio: data/memory/ o la tabla memories cambiaron "
            "desde la previsualización — pide una previsualización nueva.")}
    if not categorias:
        return {"ok": False, "error": "no has confirmado ninguna categoría"}
    if incluir_logs and not plan.get("incluir_logs"):
        return {"ok": False, "error": (
            f"la previsualización «{plan_id}» NO incluía los registros (interacciones, "
            f"auditoría, recall) ni los resultados de trabajos: repítela con "
            f"incluir_logs=true. Lo que se enseña es lo que se hace.")}
    cats_plan = {c["id"]: c for c in plan["categorias"]}
    for cat_id in categorias:
        if cat_id not in cats_plan:
            return {"ok": False, "error": f"«{cat_id}» no estaba en la previsualización «{plan_id}»"}
        if cats_plan[cat_id]["personal"] and not acepto_personal:
            return {"ok": False, "error": (
                f"«{cat_id}» es una categoría personal: exige acepto_personal=true "
                f"(se exporta antes de mover, nunca se borra el fichero).")}

    lote = f"lote-{uuid.uuid4().hex[:8]}"
    resultado = {}
    retiradas: list[dict] = []
    for cat_id in categorias:
        r = _retirar_categoria(cats_plan[cat_id], lote)
        resultado[cat_id] = r
        retiradas.extend(r.get("retiradas") or [])
        if cat_id == "duplicados-exactos":
            # Orden obligado (diseño §4): el índice único solo se crea DESPUÉS
            # de confirmar la limpieza, y solo si ya no quedan grupos.
            try:
                from . import memory
                memory.pg.crear_indice_huella()
            except Exception:
                pass
    _planes.pop(plan_id, None)

    # BARRIDO COMPLETO: la lista del plan, ni una tienda más (PRIV-03 / P2-8).
    almacenes = plan.get("almacenes") or []
    barrido = _barrer_almacenes(almacenes, retiradas, lote)
    informe = _informe(almacenes, barrido, list(categorias), lote)

    from ..comun import audit
    audit.log(action="purga_aplicar", actor="operador", destructive=True, confirmed=True,
              request=str(categorias), result=f"lote {lote}: {resultado} · {informe['resumen']}",
              extra={"plan_id": plan_id, "lote": lote, "categorias": categorias,
                     "almacenes": barrido, "incluir_logs": bool(plan.get("incluir_logs"))})
    return {"ok": True, "lote": lote, "categorias": resultado,
            "almacenes": barrido, "incluir_logs": bool(plan.get("incluir_logs")),
            **informe}


# ---------------------------------------------------------------------
#  B3.3 — papelera / restaurar
# ---------------------------------------------------------------------
def papelera(lote: str = "") -> list[dict]:
    items = _cargar_papelera()
    if lote:
        items = [i for i in items if i.get("lote") == lote]
    return list(reversed(items))


def restaurar(lote: str) -> dict:
    items = _cargar_papelera()
    del_lote = [i for i in items if i.get("lote") == lote and not i.get("restaurado")]
    if not del_lote:
        return {"ok": False, "error": f"no hay nada del lote «{lote}» en la papelera"}
    restauradas = []
    for it in del_lote:
        origen = Path(it["ruta_papelera"])
        if not origen.is_file():
            continue
        destino = Path(it["ruta_original"])
        # Sobrescritura al restaurar (matriz de amenazas): si la ruta está
        # ocupada, se renombra y SE DICE — nunca se pisa lo que hay.
        if destino.exists():
            base = destino.with_stem(destino.stem + " (restaurado)")
            destino = base
            n = 1
            while destino.exists():
                destino = base.with_stem(f"{base.stem} {n}")
                n += 1
        destino.parent.mkdir(parents=True, exist_ok=True)
        origen.replace(destino)
        it["restaurado"] = True
        it["restaurado_en"] = dt.datetime.now().isoformat(timespec="seconds")
        it["ruta_restaurada"] = str(destino)
        restauradas.append({"nombre": it["nombre"], "ruta": str(destino)})
    _guardar_papelera(items)
    n_filas = 0
    try:
        from . import memory
        if memory.pg.online:
            n_filas = memory.pg.restaurar_filas(lote)
    except Exception:
        pass
    from ..comun import audit
    audit.log(action="purga_restaurar", actor="operador", destructive=False, confirmed=True,
              result=f"{len(restauradas)} nota(s), {n_filas} fila(s)", extra={"lote": lote})
    return {"ok": True, "restauradas": restauradas, "filas": n_filas}


# ════════════════════════════════════════════════════════════════════════
#  B3.5 — BARRIDO COMPLETO DE ALMACENES (PRIV-03 / roadmap P2-8)
#
#  EL HUECO QUE CIERRA ESTO. La retirada de arriba está bien hecha para lo que
#  cubre (papelera → `retirado_en` → borrado duro con «sí»), pero dejaba copias
#  del hecho en SEIS sitios más. Medido: el operador decía «olvida mi divorcio»,
#  nexus dejaba de recordarlo de verdad, y el texto seguía escrito en
#  `data/rag/knowledge.jsonl`, en el espejo de la ingesta, en la memoria
#  operativa (`data/engram_ops.json`), en el servidor de Engram, en
#  `data/webcache.json` y en los JSONL de interacciones/auditoría/recall. Y en
#  cada uno de los zips de `data/backups/`.
#
#  LA REGLA DE ESTA SECCIÓN, en una línea: lo que la previsualización no
#  enseñó, no se toca. Por eso el inventario se calcula UNA vez, se guarda
#  dentro del plan y `aplicar()` ejecuta ESA lista — no una recalculada. Un
#  almacén que la previsualización marcó como «no disponible» (Engram caído) o
#  «opcional no incluido» (los registros) NO se convierte en tocado al aplicar:
#  o el resultado dice «no completado», o dice «no incluido», pero nunca «hecho».
#
#  LO QUE NO SE HACE, A PROPÓSITO:
#    * los registros de conversación/auditoría son la TRAZA del incidente: no se
#      borran si el operador no lo pide expresamente (`incluir_logs`), y cuando
#      lo pide se quitan LÍNEAS ENTERAS, dejando intactas byte a byte las que no
#      vienen al caso;
#    * las copias de seguridad NO se reescriben ni se borran (son la única red
#      del operador): se cuentan y se nombran con sus fechas, y el camino
#      documentado es rotarlas o borrarlas a mano;
#    * nada de esto es un borrado duro nuevo: el único destructor sigue siendo
#      `borrar_definitivo(lote)`, detrás del «sí» del operador.
#
#  EL BARRIDO SOLO VALE PARA EL `data/` DE LA MEMORIA QUE SE PURGA. Si la
#  carpeta de memoria no está dentro de `data/` —lo que pasa en una prueba que
#  redirige `MEMORY_DIR`, o con un NEXUS_DATA_DIR mal puesto— el barrido NO se
#  hace: se enseñan los almacenes con el motivo y se dice que no se tocó nada.
#  Sin esa condición, una purga de prueba con textos sintéticos podría borrar
#  registros reales del operador que casaran por casualidad, que es justo el
#  fallo que esta unidad existe para cerrar.
# ════════════════════════════════════════════════════════════════════════

_MUESTRA_LARGO = 120      # tamaño de cada trozo de texto que se usa como prueba
_MUESTRA_MIN = 40         # por debajo de esto una frase no prueba identidad


def _plano(texto: str) -> str:
    """Normalización para comparar: NFKC + espacios colapsados. Es la de
    `rag.plano()`, y de ahí se pide: una sola definición de «el mismo texto»,
    no dos que se parezcan."""
    from . import rag
    return rag.plano(texto)


def _muestras(texto: str) -> list[str]:
    """Trozos del texto que sirven de PRUEBA de identidad en otro almacén.

    Principio, medio y final (120 caracteres cada uno). Es la misma idea que el
    cotejo de los fragmentos de continuación en `borrar_carpeta_definitivo()`:
    se coge una huella del CENTRO del texto, lejos de los bordes, para que un
    troceado distinto no la rompa. Por debajo de `_MUESTRA_MIN` caracteres no se
    devuelve nada: una frase corta casa por casualidad, y aquí un falso positivo
    significa texto ajeno borrado."""
    plano = _plano(texto)
    if len(plano) < _MUESTRA_MIN:
        return []
    if len(plano) <= _MUESTRA_LARGO:
        return [plano]
    medio = len(plano) // 2
    trozos = [plano[:_MUESTRA_LARGO],
              plano[medio - _MUESTRA_LARGO // 2: medio + _MUESTRA_LARGO // 2],
              plano[-_MUESTRA_LARGO:]]
    out: list[str] = []
    for t in trozos:
        t = t.strip()
        if len(t) >= _MUESTRA_MIN and t not in out:
            out.append(t)
    return out


def _dentro(ruta: Path, raiz: Path) -> bool:
    """¿`ruta` está dentro de `raiz`? Sin distinguir mayúsculas (Windows)."""
    try:
        a = os.path.normcase(os.path.abspath(str(ruta)))
        b = os.path.normcase(os.path.abspath(str(raiz)))
    except Exception:                                          # noqa: BLE001
        return False
    return a == b or a.startswith(b if b.endswith(os.sep) else b + os.sep)


def _ruta_de(modulo: str, atributo: str, por_defecto: Path) -> Path:
    """Ruta de un almacén, pedida a su DUEÑO si ya está cargado.

    No se importa el módulo dueño solo para leer una ruta: importar
    `aplicacion.jobs` construye el `JobManager` (y lee `data/jobs.json`), e
    importar `infraestructura.websearch` arrastra httpx. Si el dueño ya está en
    `sys.modules` se usa SU constante (una sola verdad por almacén) y, si no, se
    deriva de `DATA_DIR` igual que la deriva él. Una prueba estructural comprueba
    que las dos formas coinciden, para que un renombrado no deje la purga
    escribiendo en un archivo que ya nadie lee."""
    mod = sys.modules.get(modulo)
    valor = getattr(mod, atributo, None) if mod is not None else None
    if callable(valor):
        try:
            valor = valor()
        except Exception:                                      # noqa: BLE001
            valor = None
    return Path(valor) if valor else Path(por_defecto)


def rutas_almacenes() -> dict[str, Path]:
    """Las rutas de TODOS los almacenes que el barrido puede tocar, por id."""
    return {
        "rag": _ruta_de("backend.core.dominio.rag", "_STORE",
                        DATA_DIR / "rag" / "knowledge.jsonl"),
        "documentos": DOCUMENTOS_DIR,
        "opmem": _ruta_de("backend.core.dominio.opmem", "OPS_FILE",
                          DATA_DIR / "engram_ops.json"),
        "webcache": _ruta_de("backend.core.infraestructura.websearch", "_cache_file",
                             DATA_DIR / "webcache.json"),
        "jobs": _ruta_de("backend.core.aplicacion.jobs", "JOBS_FILE",
                         DATA_DIR / "jobs.json"),
        "interacciones": _ruta_de("backend.core.dominio.selflearn", "_INTER",
                                  DATA_DIR / "interactions.jsonl"),
        "audit": _ruta_de("backend.core.comun.audit", "AUDIT_FILE",
                          DATA_DIR / "logs" / "audit.jsonl"),
        "recall": _ruta_de("backend.core.dominio.opmem", "RECALL_LOG",
                           DATA_DIR / "logs" / "recall.jsonl"),
        "backups": DATA_DIR / "backups",
    }


def barrido_habilitado() -> tuple[bool, str]:
    """¿Se puede barrer? Sí cuando la memoria que se purga es la de ESTE `data/`.

    Es una condición de seguridad, no una comodidad de pruebas: el barrido
    escribe en almacenes compartidos por todo nexus, así que solo tiene sentido
    cuando la carpeta de notas que se está vaciando es la que corresponde a esos
    almacenes. Con una carpeta de memoria de usar y tirar (pruebas) el barrido se
    declara fuera de alcance en vez de adivinar."""
    try:
        if _dentro(Path(MEMORY_DIR).resolve(), Path(DATA_DIR).resolve()):
            return True, ""
    except Exception:                                          # noqa: BLE001
        pass
    return False, (f"la carpeta de memoria ({MEMORY_DIR}) no está dentro de "
                   f"«{DATA_DIR}», así que no toco los almacenes de datos: no "
                   f"son los de esta memoria.")


def _casar(texto: str, fuente: str, notas: list[dict]) -> set[str]:
    """Rutas de las notas purgadas a las que PERTENECE este texto.

    Dos criterios, los dos comprobables: `fuente` (el `meta.source` de un
    registro del RAG) es el nombre de la nota, o el texto CONTIENE una muestra
    suya. Nada de parecidos: aquí un falso positivo significa borrar texto ajeno."""
    casan: set[str] = set()
    nombre_fuente = Path(fuente).name if fuente else ""
    plano = _plano(texto) if any(n["muestras"] for n in notas) else ""
    for n in notas:
        if nombre_fuente and nombre_fuente == n["nombre"]:
            casan.add(n["ruta"])
            continue
        if plano and any(m in plano for m in n["muestras"]):
            casan.add(n["ruta"])
    return casan


def _suma_categoria(por_cat: dict, casan: set[str], cat_de: dict) -> None:
    """Suma 1 por CADA categoría afectada (no por nota): el informe dice cuántos
    registros toca cada categoría, que es lo que el operador ve."""
    for cat in {cat_de[r] for r in casan if r in cat_de}:
        por_cat[cat] = por_cat.get(cat, 0) + 1


def _leer_jsonl(ruta: Path) -> list[str]:
    try:
        return ruta.read_text(encoding="utf-8").splitlines() if ruta.is_file() else []
    except Exception:                                          # noqa: BLE001
        return []


def _escribir_texto_atomico(ruta: Path, texto: str) -> None:
    """Publica `texto` en `ruta` de forma indivisible, con el temporal ÚNICO de
    `comun/atomicos.py` (pid + azar + `.tmp`, en la misma carpeta) y su mismo
    `os.replace`. `atomicos.escribir_json_atomico()` escribe UN documento JSON y
    aquí hay ficheros JSONL: se reutiliza su primitiva en vez de inventar otra
    política de temporales."""
    from ..comun.atomicos import _tmp_unico
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_unico(ruta)
    try:
        tmp.write_text(texto, encoding="utf-8")
        os.replace(tmp, ruta)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _invalidar_cache_web() -> None:
    """La caché de `websearch` vive en RAM (`_MEM`) y se vuelca al disco en el
    siguiente `cache_put()`: sin invalidarla, lo purgado VOLVERÍA al archivo en la
    siguiente búsqueda. Se toca su RAM solo si el módulo ya está cargado — no se
    importa aquí para no arrastrar httpx desde el motor de purga."""
    mod = sys.modules.get("backend.core.infraestructura.websearch")
    if mod is None:
        return
    mod._MEM = None
    mod._MEM_DIR = None


def _olvidar_jobs_en_ram(ids: list) -> int:
    """El panel de multitarea guarda los trabajos en RAM y los reescribe en el
    siguiente `_persist()`: si no se quitan también de ahí, el resultado purgado
    vuelve a `jobs.json`. Solo se toca la RAM si el gestor está vivo."""
    try:
        mod = sys.modules.get("backend.core.aplicacion.jobs")
        mgr = getattr(mod, "jobs", None) if mod is not None else None
        vivos = getattr(mgr, "_jobs", None)
        if not isinstance(vivos, dict):
            return 0
        quitados = 0
        for jid in ids:
            if jid and vivos.pop(jid, None) is not None:
                quitados += 1
        return quitados
    except Exception:                                          # noqa: BLE001
        return 0


def _origen_de_cabecera(texto: str) -> str:
    """El `origen:` de la cabecera que escribe `ingesta.py` en cada espejo."""
    for linea in (texto or "").splitlines()[:8]:
        if linea.startswith("origen:"):
            return linea.split(":", 1)[1].strip()
    return ""


def _estado_backups(notas: list[dict]) -> dict:
    """Las copias de seguridad que DE VERDAD contienen lo purgado: se nombran,
    no se tocan.

    No se supone «todos los zips contienen todo `data/`»: se abre el índice de
    cada archivo (solo el índice central, no se descomprime nada) y se busca la
    ruta de cada nota purgada dentro de `memory/`. Así el informe puede decir
    «estos 2 zips, con estas fechas» en vez de un susto genérico — y no se
    equivoca ni con las copias hechas DESPUÉS de la purga ni con las que no
    llegaron a incluir la nota."""
    ruta = rutas_almacenes()["backups"]
    out = {"revisadas": 0, "elementos": 0, "fechas": [], "nombres": [],
           "ilegibles": [], "existe": ruta.is_dir()}
    if not out["existe"]:
        return out
    import zipfile
    buscados = {f"memory/{n['ruta']}".replace("\\", "/") for n in notas}
    for z in sorted(ruta.glob("*.zip")):
        out["revisadas"] += 1
        try:
            with zipfile.ZipFile(z) as zf:
                dentro = {n.replace("\\", "/") for n in zf.namelist()}
        except Exception:                                      # noqa: BLE001
            out["ilegibles"].append(z.name)
            continue
        if not (buscados & dentro):
            continue
        out["nombres"].append(z.name)
        try:
            out["fechas"].append(
                dt.datetime.fromtimestamp(z.stat().st_mtime).strftime("%Y-%m-%d"))
        except Exception:                                      # noqa: BLE001
            out["fechas"].append("fecha ilegible")
    out["elementos"] = len(out["nombres"])
    return out


def _espejos_candidatos(notas: list[dict]) -> tuple[list[dict], list[dict]]:
    """Espejos de la ingesta que pertenecen a lo purgado: (casan, omitidos).

    Dos vínculos, los dos comprobables y explicables al operador:
      * la cabecera `origen:` del espejo apunta a un fichero con el MISMO nombre
        que la nota purgada;
      * el cuerpo del espejo CONTIENE una muestra del texto purgado.
    Un enlace simbólico NUNCA se sigue (misma regla que `retirar_nota()`), el
    material de credenciales queda fuera SIEMPRE (la denylist de
    `permissions.denied()` vale también aquí) y nada que resuelva fuera del
    espejo se toca."""
    casan: list[dict] = []
    omitidos: list[dict] = []
    if not DOCUMENTOS_DIR.is_dir():
        return casan, omitidos
    raiz = DOCUMENTOS_DIR.resolve()
    for f in sorted(DOCUMENTOS_DIR.rglob("*.md")):
        if f.is_symlink():
            omitidos.append({"archivo": str(f), "motivo": "symlink: no se sigue ni se mueve"})
            continue
        try:
            resuelto = f.resolve()
        except Exception:                                      # noqa: BLE001
            omitidos.append({"archivo": str(f), "motivo": "no pude resolver la ruta"})
            continue
        if not _dentro(resuelto, raiz):
            omitidos.append({"archivo": str(f),
                             "motivo": "resuelve fuera del espejo: no lo toco"})
            continue
        if permissions.denied(resuelto):
            omitidos.append({"archivo": str(f),
                             "motivo": "material de credenciales: queda fuera SIEMPRE"})
            continue
        try:
            texto = resuelto.read_text(encoding="utf-8", errors="replace")
        except Exception:                                      # noqa: BLE001
            continue
        plano = _plano(texto)
        origen = _origen_de_cabecera(texto)
        casan_aqui: set[str] = set()
        motivos: list[str] = []
        for n in notas:
            if origen and Path(origen).name == n["nombre"]:
                casan_aqui.add(n["ruta"])
                motivos.append(f"su cabecera «origen:» apunta a «{Path(origen).name}», "
                               f"el mismo nombre que la nota «{n['ruta']}»")
                continue
            if plano and any(m in plano for m in n["muestras"]):
                casan_aqui.add(n["ruta"])
                motivos.append(f"contiene el texto de «{n['ruta']}»")
        if casan_aqui:
            casan.append({"ruta": str(f), "casan": casan_aqui,
                          "motivo": "; ".join(sorted(set(motivos)))})
    return casan, omitidos


def _recuento_rag(ruta: Path, notas: list[dict], cat_de: dict) -> tuple[int, dict]:
    total = 0
    por_cat: dict = {}
    for linea in _leer_jsonl(ruta):
        if not linea.strip():
            continue
        try:
            rec = json.loads(linea)
        except Exception:                                      # noqa: BLE001
            continue
        fuente = str((rec.get("meta") or {}).get("source") or "")
        casan = _casar(str(rec.get("text") or ""), fuente, notas)
        if casan:
            total += 1
            _suma_categoria(por_cat, casan, cat_de)
    return total, por_cat


def _recuento_opmem(notas: list[dict]) -> tuple[int, dict]:
    """Recuerdos de la memoria operativa que se llevaría la purga. Solo LEE
    (`opmem.matching`), para que la previsualización pueda prometer un número."""
    from . import opmem
    vistos: set = set()
    por_cat: dict = {}
    for n in notas:
        for m in n["muestras"]:
            if len(m) < _MUESTRA_MIN:
                continue
            for it in opmem.matching(m):
                if it.get("id") in vistos:
                    continue
                vistos.add(it.get("id"))
                por_cat[n["categoria"]] = por_cat.get(n["categoria"], 0) + 1
    return len(vistos), por_cat


def _recuento_json(ruta: Path, notas: list[dict], cat_de: dict,
                   campos: tuple[str, ...]) -> tuple[int, dict]:
    """Recuento en un almacén JSON (lista de dicts o dict de entradas)."""
    try:
        data = json.loads(ruta.read_text(encoding="utf-8")) if ruta.is_file() else None
    except Exception:                                          # noqa: BLE001
        return 0, {}
    por_cat: dict = {}
    total = 0
    if isinstance(data, list):
        for j in data:
            if not isinstance(j, dict):
                continue
            texto = " ".join(str(j.get(c) or "") for c in campos)
            casan = _casar(texto, "", notas)
            if casan:
                total += 1
                _suma_categoria(por_cat, casan, cat_de)
    elif isinstance(data, dict):
        for k, v in data.items():
            cuerpo = v.get("data") if isinstance(v, dict) else v
            casan = _casar(f"{k} {json.dumps(cuerpo, ensure_ascii=False)}", "", notas)
            if casan:
                total += 1
                _suma_categoria(por_cat, casan, cat_de)
    return total, por_cat


def _recuento_jsonl(ruta: Path, notas: list[dict], cat_de: dict) -> tuple[int, dict]:
    por_cat: dict = {}
    total = 0
    for linea in _leer_jsonl(ruta):
        if not linea.strip():
            continue
        casan = _casar(linea, "", notas)
        if casan:
            total += 1
            _suma_categoria(por_cat, casan, cat_de)
    return total, por_cat


def _engram_estado() -> tuple[str, dict]:
    """Estado de Engram SIN red de más (usa su caché de 60 s). `(estado, detalle)`."""
    try:
        from ..infraestructura import engram_bridge
        info = engram_bridge.status_sync({"settings": settings})
    except Exception as exc:                                   # noqa: BLE001
        return "no_disponible", {"motivo": f"no pude consultarlo ({type(exc).__name__})"}
    if not info.get("installed"):
        return "no_disponible", {"url": info.get("url", ""),
                                 "motivo": "Engram no está instalado en este equipo"}
    if not info.get("alive_cached"):
        return "no_disponible", {
            "url": info.get("url", ""),
            "motivo": ("el servidor de Engram no responde ahora mismo"
                       + (f" ({info['last_error']})" if info.get("last_error") else ""))}
    return "en_linea", {"url": info.get("url", "")}


def _inventario_almacenes(notas: list[dict], incluir_logs: bool) -> list[dict]:
    """La LISTA de almacenes que la previsualización enseña y `aplicar()` ejecuta.

    Cada entrada dice qué almacén es, qué se va a hacer con él, cuántos elementos
    lleva lo purgado (por categoría) y por qué. Los que NO se pueden tocar
    también aparecen, con el motivo: un almacén que se cae de la lista sin decirlo
    es exactamente cómo se pierde la confianza en un «olvida esto»."""
    r = rutas_almacenes()
    cat_de = {n["ruta"]: n["categoria"] for n in notas}
    ok, motivo_no = barrido_habilitado()

    def _fuera(aid: str, que: str, accion: str, ruta) -> dict:
        return {"id": aid, "que": que, "ruta": str(ruta), "accion": accion,
                "estado": "fuera_de_alcance", "elementos": 0, "por_categoria": {},
                "motivo": motivo_no or "fuera de alcance"}

    out: list[dict] = []
    que_rag = "almacén vectorial local (knowledge.jsonl)"
    que_doc = "espejo de la ingesta (data/memory/documentos)"
    que_ops = "memoria operativa local (engram_ops.json)"
    que_eng = "memoria de proyecto (Engram)"
    que_web = "caché web (webcache.json)"
    que_log = "registros de conversación y auditoría (interactions/audit/recall)"
    que_job = "resultados de trabajos (jobs.json)"

    if ok:
        n_rag, cat_rag = _recuento_rag(r["rag"], notas, cat_de)
        out.append({"id": "rag", "que": que_rag, "ruta": str(r["rag"]),
                    "accion": "retirar", "estado": "incluido",
                    "elementos": n_rag, "por_categoria": cat_rag,
                    "motivo": ("los registros del texto purgado salen del almacén local y "
                               "su entrada de «ya indexado»; la copia maestra queda en la "
                               "papelera, así que reindexar la restaura mientras exista")})
    else:
        out.append(_fuera("rag", que_rag, "retirar", r["rag"]))

    if ok:
        espejos, omitidos = _espejos_candidatos(notas)
        cat_doc: dict = {}
        for e in espejos:
            _suma_categoria(cat_doc, e["casan"], cat_de)
        out.append({"id": "documentos", "que": que_doc, "ruta": str(r["documentos"]),
                    "accion": "papelera", "estado": "incluido",
                    "elementos": len(espejos), "por_categoria": cat_doc,
                    "omitidos": omitidos,
                    "motivo": ("el espejo va a la MISMA papelera que la nota y se restaura "
                               "con ella (no se borra): no deja media migración")})
    else:
        out.append(_fuera("documentos", que_doc, "papelera", r["documentos"]))

    if ok:
        n_ops, cat_ops = _recuento_opmem(notas)
        out.append({"id": "opmem", "que": que_ops, "ruta": str(r["opmem"]),
                    "accion": "olvidar", "estado": "incluido",
                    "elementos": n_ops, "por_categoria": cat_ops,
                    "motivo": ("un recuerdo de comportamiento que contenga el texto "
                               "purgado se va con `opmem.forget()`: la misma puerta que "
                               "«olvida la regla …», y solo con muestras de 40+ caracteres")})
    else:
        out.append(_fuera("opmem", que_ops, "olvidar", r["opmem"]))

    if ok:
        estado, detalle = _engram_estado()
        motivo = ("se le pide olvidar por la puerta del propio Engram; si el servidor no "
                  "está o no sabe borrar, el resultado se reporta como NO COMPLETADO — "
                  "nunca como hecho")
        if detalle.get("motivo"):
            motivo += f" · ahora: {detalle['motivo']}"
        out.append({"id": "engram", "que": que_eng, "ruta": detalle.get("url", ""),
                    "accion": "olvidar",
                    "estado": "incluido" if estado == "en_linea" else "no_disponible",
                    "elementos": 0, "por_categoria": {}, "motivo": motivo})
    else:
        out.append(_fuera("engram", que_eng, "olvidar", ""))

    if ok:
        n_cache, cat_cache = _recuento_json(r["webcache"], notas, cat_de, ())
        out.append({"id": "webcache", "que": que_web, "ruta": str(r["webcache"]),
                    "accion": "retirar", "estado": "incluido",
                    "elementos": n_cache, "por_categoria": cat_cache,
                    "motivo": ("fuera la entrada de caché cuyo texto (o cuya pregunta) es "
                               "lo purgado; también se invalida la copia en RAM")})
    else:
        out.append(_fuera("webcache", que_web, "retirar", r["webcache"]))

    if ok:
        n_logs, cat_logs = 0, {}
        detalle_logs: dict = {}
        for clave in ("interacciones", "audit", "recall"):
            n, por_cat = _recuento_jsonl(r[clave], notas, cat_de)
            detalle_logs[clave] = {"ruta": str(r[clave]), "elementos": n}
            n_logs += n
            for k, v in por_cat.items():
                cat_logs[k] = cat_logs.get(k, 0) + v
        out.append({"id": "logs", "que": que_log,
                    "ruta": str(Path(r["audit"]).parent), "accion": "opcional",
                    "estado": "incluido" if incluir_logs else "no_incluido",
                    "incluido": bool(incluir_logs), "elementos": n_logs,
                    "por_categoria": cat_logs, "detalle": detalle_logs,
                    "motivo": ("son la TRAZA del incidente: por defecto NO se tocan. Solo se "
                               "quitan si lo pides tú (incluir_logs), y entonces se van "
                               "líneas ENTERAS dejando las demás intactas byte a byte")})
    else:
        out.append(_fuera("logs", que_log, "opcional", Path(r["audit"]).parent))

    if ok:
        n_jobs, cat_jobs = _recuento_json(
            r["jobs"], notas, cat_de, ("request", "result", "error", "reply", "text"))
        out.append({"id": "jobs", "que": que_job, "ruta": str(r["jobs"]),
                    "accion": "opcional",
                    "estado": "incluido" if incluir_logs else "no_incluido",
                    "incluido": bool(incluir_logs), "elementos": n_jobs,
                    "por_categoria": cat_jobs,
                    "motivo": ("el panel guarda hasta 8000 caracteres de cada respuesta: "
                               "misma regla que los registros — solo con incluir_logs")})
    else:
        out.append(_fuera("jobs", que_job, "opcional", r["jobs"]))

    if ok:
        backups = _estado_backups(notas)
        if backups["elementos"]:
            motivo_bk = (f"{backups['elementos']} de {backups['revisadas']} copia(s) de "
                         f"seguridad contienen la nota tal como estaba en su fecha: NO las "
                         f"reescribo ni las borro (son tu única red). Camino documentado: "
                         f"dejar que roten solas (se guardan las 7 últimas diarias) o "
                         f"borrarlas a mano en data/backups/")
        elif backups["revisadas"]:
            motivo_bk = (f"ninguna de las {backups['revisadas']} copia(s) de seguridad "
                         f"contiene esta nota (se revisó el índice de cada zip)")
        else:
            motivo_bk = "no hay copias de seguridad que contengan nada"
        if backups["ilegibles"]:
            motivo_bk += (f" · {len(backups['ilegibles'])} zip(s) no se pudieron leer y "
                          f"quedan sin comprobar: " + ", ".join(backups["ilegibles"][:3]))
        out.append({"id": "backups", "que": "copias de seguridad (data/backups/*.zip)",
                    "ruta": str(r["backups"]), "accion": "no_se_toca",
                    "estado": "no_se_toca", "elementos": backups["elementos"],
                    "revisadas": backups["revisadas"],
                    "fechas": backups["fechas"], "nombres": backups["nombres"],
                    "por_categoria": {}, "motivo": motivo_bk})
    else:
        out.append(_fuera("backups", "copias de seguridad (data/backups/*.zip)",
                          "no_se_toca", r["backups"]))
    return out


def _barrer_rag(notas: list[dict]) -> dict:
    from . import rag
    r = rag.purgar_fuentes(fuentes={n["nombre"] for n in notas},
                           muestras=[m for n in notas for m in n["muestras"]])
    return {"id": "rag",
            "resultado": ("retirado" if r.get("eliminados") else
                          ("no_completado" if not r.get("ok") else "sin_cambios")),
            "elementos": r.get("eliminados", 0), "quedan": r.get("quedan", 0),
            "indexados_limpiados": r.get("indexados_limpiados", 0),
            "error": r.get("error", "")}


def _barrer_documentos(notas: list[dict], lote: str) -> dict:
    """El espejo va a la papelera con la MISMA semántica que la nota.

    No se destruye nada aquí: `borrar_definitivo(lote)` es el único destructor, y
    como el espejo queda apuntado en `papelera.json` con el lote, el paso 2 se lo
    lleva también cuando el operador lo confirma — sin una puerta nueva."""
    espejos, omitidos = _espejos_candidatos(notas)
    movidos, fallos = 0, []
    for e in espejos:
        ruta = Path(e["ruta"])
        try:
            rel = ruta.relative_to(MEMORY_DIR)
        except ValueError:
            fallos.append({"archivo": str(ruta), "motivo": "no está dentro de la memoria"})
            continue
        if (PAPELERA_DIR / lote / ruta.name).exists():
            fallos.append({"archivo": str(ruta),
                           "motivo": "ya hay un fichero con ese nombre en la papelera de "
                                     "este lote: no lo piso"})
            continue
        r = retirar_nota(str(rel), lote)
        if r.get("movido"):
            movidos += 1
        else:
            fallos.append({"archivo": str(ruta), "motivo": r.get("razon", "no se movió")})
    return {"id": "documentos", "resultado": "a_papelera" if movidos else "sin_cambios",
            "elementos": movidos, "omitidos": omitidos + fallos,
            "motivos": [{"archivo": e["ruta"], "motivo": e["motivo"]} for e in espejos]}


def _barrer_opmem(notas: list[dict]) -> dict:
    from . import opmem
    muestras = [m for n in notas for m in n["muestras"] if len(m) >= _MUESTRA_MIN]
    borrados = 0
    for m in dict.fromkeys(muestras):
        borrados += opmem.forget(m)
    return {"id": "opmem", "resultado": "olvidado" if borrados else "sin_cambios",
            "elementos": borrados}


def _consulta_engram(nota: dict) -> str:
    """Con qué se busca en Engram: el nombre de la nota sin extensión es lo que
    el operador diría («divorcio»), no un trozo de 120 caracteres. Si no da, la
    primera muestra."""
    stem = Path(nota["nombre"]).stem.replace("_", " ").replace("-", " ").strip()
    if len(stem) >= 3:
        return stem[:120]
    return (nota["muestras"][0][:120] if nota["muestras"] else "")


def _barrer_engram(notas: list[dict]) -> dict:
    """Pide a Engram que olvide. Si no puede, lo dice: NO COMPLETADO."""
    try:
        from ..infraestructura import engram_bridge
    except Exception as exc:                                   # noqa: BLE001
        return {"id": "engram", "resultado": "no_completado", "elementos": 0,
                "error": f"no pude cargar el puente de Engram: {type(exc).__name__}"}
    ctx = {"settings": settings}
    ok_n = fallos = borrados = 0
    errores: list[str] = []
    for n in notas:
        consulta = _consulta_engram(n)
        if not consulta:
            continue
        try:
            r = engram_bridge.forget_sync(ctx, consulta)
        except Exception as exc:                               # noqa: BLE001
            r = {"ok": False, "no_completado": True, "error": f"{type(exc).__name__}: {exc}"}
        if r.get("ok"):
            ok_n += 1
            borrados += int(r.get("borrados") or 0)
        else:
            fallos += 1
            if r.get("error"):
                errores.append(str(r["error"]))
    if fallos:
        return {"id": "engram", "resultado": "no_completado", "elementos": borrados,
                "ok": ok_n, "fallos": fallos,
                "error": "; ".join(dict.fromkeys(errores))[:300]}
    return {"id": "engram", "resultado": "olvidado" if borrados else "sin_cambios",
            "elementos": borrados, "ok": ok_n}


def _barrer_webcache(notas: list[dict], ruta: Path) -> dict:
    if not ruta.is_file():
        return {"id": "webcache", "resultado": "sin_cambios", "elementos": 0, "existe": False}
    try:
        data = json.loads(ruta.read_text(encoding="utf-8"))
    except Exception as exc:                                   # noqa: BLE001
        return {"id": "webcache", "resultado": "no_completado", "elementos": 0,
                "error": f"no pude leer la caché: {type(exc).__name__}"}
    if not isinstance(data, dict):
        return {"id": "webcache", "resultado": "sin_cambios", "elementos": 0}
    fuera = set()
    for k, v in data.items():
        cuerpo = v.get("data") if isinstance(v, dict) else v
        if _casar(f"{k} {json.dumps(cuerpo, ensure_ascii=False)}", "", notas):
            fuera.add(k)
    if not fuera:
        return {"id": "webcache", "resultado": "sin_cambios", "elementos": 0,
                "quedan": len(data)}
    escribir_json_atomico(ruta, {k: v for k, v in data.items() if k not in fuera})
    _invalidar_cache_web()          # sin esto, la RAM devuelve lo purgado al disco
    return {"id": "webcache", "resultado": "retirado", "elementos": len(fuera),
            "quedan": len(data) - len(fuera)}


def _barrer_jsonl(ruta: Path, notas: list[dict]) -> dict:
    """Quita las LÍNEAS que pertenecen a lo purgado; las demás, byte a byte.

    Se filtran líneas crudas y se concatenan tal cual (no se re-serializa el
    JSON): una línea que no viene al caso tiene que quedar IDÉNTICA, y con
    `json.dumps` dejaría de serlo por el espaciado."""
    if not ruta.is_file():
        return {"existe": False, "elementos": 0, "quedan": 0}
    try:
        lineas = ruta.read_text(encoding="utf-8").splitlines(keepends=True)
    except Exception as exc:                                   # noqa: BLE001
        return {"existe": True, "elementos": 0, "quedan": 0,
                "error": f"no pude leerlo: {type(exc).__name__}"}
    quedan, fuera = [], 0
    for linea in lineas:
        if not linea.strip() or not _casar(linea, "", notas):
            quedan.append(linea)
        else:
            fuera += 1
    if fuera:
        _escribir_texto_atomico(ruta, "".join(quedan))
    return {"existe": True, "elementos": fuera, "quedan": len(quedan)}


def _barrer_logs(notas: list[dict], incluir_logs: bool) -> dict:
    if not incluir_logs:
        return {"id": "logs", "resultado": "no_incluido", "elementos": 0,
                "motivo": ("no lo pediste: los registros son la traza del incidente y se "
                           "quedan («no toques lo que no pediste»)")}
    r = rutas_almacenes()
    detalle = {clave: _barrer_jsonl(r[clave], notas)
               for clave in ("interacciones", "audit", "recall")}
    total = sum(d.get("elementos", 0) for d in detalle.values())
    return {"id": "logs", "resultado": "retirado" if total else "sin_cambios",
            "elementos": total, "detalle": detalle}


def _barrer_jobs(notas: list[dict], incluir_logs: bool) -> dict:
    ruta = rutas_almacenes()["jobs"]
    if not incluir_logs:
        return {"id": "jobs", "resultado": "no_incluido", "elementos": 0,
                "motivo": "misma regla que los registros: solo con incluir_logs"}
    if not ruta.is_file():
        return {"id": "jobs", "resultado": "sin_cambios", "elementos": 0, "existe": False}
    try:
        data = json.loads(ruta.read_text(encoding="utf-8"))
    except Exception as exc:                                   # noqa: BLE001
        return {"id": "jobs", "resultado": "no_completado", "elementos": 0,
                "error": f"no pude leer jobs.json: {type(exc).__name__}"}
    if not isinstance(data, list):
        return {"id": "jobs", "resultado": "sin_cambios", "elementos": 0}
    fuera = []
    for j in data:
        if not isinstance(j, dict):
            continue
        texto = " ".join(str(j.get(c) or "") for c in
                          ("request", "result", "error", "reply", "text"))
        if _casar(texto, "", notas):
            fuera.append(j)
    if not fuera:
        return {"id": "jobs", "resultado": "sin_cambios", "elementos": 0, "quedan": len(data)}
    ids = {j.get("id") for j in fuera}
    escribir_json_atomico(ruta, [j for j in data if j.get("id") not in ids], indent=1)
    en_ram = _olvidar_jobs_en_ram(list(ids))
    return {"id": "jobs", "resultado": "retirado", "elementos": len(fuera),
            "quedan": len(data) - len(fuera), "quitados_de_ram": en_ram}


def _barrer_almacenes(almacenes: list[dict], notas: list[dict], lote: str) -> dict:
    """Ejecuta EXACTAMENTE la lista que enseñó la previsualización.

    Un almacén que la previsualización declaró «no_se_toca», «no_incluido» o
    «fuera_de_alcance» NO se toca aquí aunque ahora parezca buena idea: lo que se
    enseña es lo que se hace. Cada almacén va en su `try`: que uno falle no puede
    dejarse a medias los demás (y las notas ya están en la papelera)."""
    res: dict[str, dict] = {}
    ok, motivo_no = barrido_habilitado()
    if not ok:
        for alm in almacenes:
            res[alm["id"]] = {"id": alm["id"], "resultado": "fuera_de_alcance",
                              "elementos": 0, "motivo": motivo_no}
        return res
    r = rutas_almacenes()
    for alm in almacenes:
        aid = alm.get("id")
        accion = alm.get("accion")
        if accion == "no_se_toca":
            res[aid] = {"id": aid, "resultado": "no_se_toca", "elementos": 0,
                        "fechas": alm.get("fechas") or [], "motivo": alm.get("motivo", "")}
            continue
        if accion == "opcional" and not alm.get("incluido"):
            res[aid] = {"id": aid, "resultado": "no_incluido", "elementos": 0,
                        "motivo": alm.get("motivo", "")}
            continue
        try:
            if aid == "rag":
                res[aid] = _barrer_rag(notas)
            elif aid == "documentos":
                res[aid] = _barrer_documentos(notas, lote)
            elif aid == "opmem":
                res[aid] = _barrer_opmem(notas)
            elif aid == "engram":
                res[aid] = _barrer_engram(notas)
            elif aid == "webcache":
                res[aid] = _barrer_webcache(notas, r["webcache"])
            elif aid == "logs":
                res[aid] = _barrer_logs(notas, bool(alm.get("incluido")))
            elif aid == "jobs":
                res[aid] = _barrer_jobs(notas, bool(alm.get("incluido")))
            else:
                res[aid] = {"id": aid, "resultado": "no_reconocido", "elementos": 0}
        except Exception as exc:                               # noqa: BLE001
            res[aid] = {"id": aid, "resultado": "no_completado", "elementos": 0,
                        "error": f"{type(exc).__name__}: {exc}"}
    return res


def _informe(almacenes: list[dict], barrido: dict, cats: list[str], lote: str) -> dict:
    """El informe HONESTO: qué se retiró, qué es restaurable y qué sobrevive.

    Nada de un «borrado» a secas: el operador tiene que poder leer qué pasó en cada
    sitio y volver atrás donde se pueda."""
    retirado: list[str] = []
    restaurable: list[str] = []
    sobrevive: list[dict] = []
    for alm in almacenes:
        aid = alm.get("id")
        que = alm.get("que", aid)
        r = barrido.get(aid) or {}
        resultado = r.get("resultado", "")
        if resultado in ("retirado", "a_papelera", "olvidado"):
            retirado.append(f"{que}: {r.get('elementos', 0)} elemento(s)")
        if resultado == "a_papelera":
            restaurable.append(f"{que} (lote «{lote}»: se restaura con «restaurar»)")
        elif resultado == "no_completado":
            sobrevive.append({"que": que, "por_que": r.get("error") or "no se pudo completar"})
        elif resultado == "no_incluido":
            sobrevive.append({"que": que, "por_que": "no lo pediste (alcance opt-in)"})
        elif resultado == "no_se_toca":
            fechas = ", ".join(r.get("fechas") or [])
            sobrevive.append({"que": que,
                              "por_que": f"intacto a propósito ({fechas or 'copia sin fecha'})"})
        elif resultado == "fuera_de_alcance":
            sobrevive.append({"que": que, "por_que": r.get("motivo") or "fuera de alcance"})
    lineas = [f"Purga del lote «{lote}» ({', '.join(cats)})."]
    if retirado:
        lineas.append("Retirado — " + "; ".join(retirado) + ".")
    lineas.append("Las notas están en la papelera (restaurables).")
    if sobrevive:
        lineas.append("Sobrevive — "
                      + "; ".join(f"{s['que']}: {s['por_que']}" for s in sobrevive) + ".")
    return {"resumen": " ".join(lineas), "retirado": retirado,
            "restaurable": restaurable, "sobrevive": sobrevive}


# ---------------------------------------------------------------------
#  B3.4 — exportar / borrado definitivo (PASO 2, lo inicia el usuario)
# ---------------------------------------------------------------------
def exportar(lote: str, destino: str | None = None) -> dict:
    from ..comun import permissions
    items = [i for i in _cargar_papelera() if i.get("lote") == lote]
    if not items:
        return {"ok": False, "error": f"no hay nada del lote «{lote}» en la papelera"}
    if destino:
        try:
            dest_dir = Path(destino).expanduser().resolve()
        except Exception:
            return {"ok": False, "error": "ruta de destino inválida"}
        # Traversal en exportar (matriz de amenazas): rechazado con motivo,
        # NUNCA recortado en silencio.
        if not permissions.path_allowed(dest_dir):
            return {"ok": False, "error": (
                f"«{destino}» no está entre las carpetas permitidas "
                f"(⚙ → Permisos) — no exporto ahí.")}
    else:
        dest_dir = EXPORT_DIR / lote
    dest_dir.mkdir(parents=True, exist_ok=True)
    copiados = []
    for it in items:
        origen = Path(it["ruta_papelera"])
        if origen.is_file():
            destino_f = dest_dir / it["nombre"]
            shutil.copy2(origen, destino_f)
            copiados.append(str(destino_f))
    from ..comun import audit
    audit.log(action="purga_exportar", actor="operador", destructive=False, confirmed=True,
              result=f"{len(copiados)} fichero(s) a {dest_dir}", extra={"lote": lote})
    return {"ok": True, "copiados": copiados, "destino": str(dest_dir)}


def retirar_carpeta(carpeta: str, lote: str | None = None) -> dict:
    """Retira TODO lo que declare venir de esa carpeta, lleve marca o no.

    Por qué hace falta, además de `aplicar()`: el vínculo nota↔fila de siempre
    es el prefijo `[fichero]` del texto, y los fragmentos ingeridos de una
    carpeta NO lo llevan —empiezan por `# doc <título>`—. Retirar sus notas
    dejaba las filas vivas y buscables en la memoria vectorial.

    INCIDENTE (02/08/2026): tras purgar «20. FP DAM Euroformac» seguían
    contestando 32 filas de esa carpeta. Las notas estaban en la papelera y las
    filas no: nadie las reclamaba.

    Aquí el vínculo es la procedencia que el propio texto declara
    (`Carpeta: <nombre>`), que es la única que esos fragmentos sí tienen.

    Retira, no destruye: deja el lote en la papelera. Para que desaparezca de
    verdad hay que llamar después a `borrar_definitivo(lote)`, que es el paso
    que exige el «sí» del operador.
    """
    from . import memory
    lote = lote or f"carpeta-{dt.datetime.now():%Y%m%d%H%M%S}"
    filas = 0
    if memory.pg.online:
        ids = [f["id"] for f in memory.pg.filas_de_carpeta(carpeta)]
        filas = memory.pg.retirar_filas(ids, lote) if ids else 0

    # Y las notas que sigan fuera de la papelera declarando esa carpeta.
    notas = 0
    marca = f"Carpeta: {carpeta}"
    for nota in _notas():
        try:
            if marca in nota.read_text(encoding="utf-8", errors="ignore"):
                _exportar_copia_personal(nota, lote)
                if retirar_nota(str(nota.relative_to(MEMORY_DIR)), lote).get("movido"):
                    notas += 1
        except Exception:                                  # noqa: BLE001
            continue

    from ..comun import audit
    audit.log(action="purga_retirar_carpeta", actor="operador", destructive=False,
              confirmed=True, result=f"{notas} nota(s) y {filas} fila(s) a la papelera",
              targets=[{"carpeta": carpeta}], extra={"lote": lote})
    return {"ok": True, "lote": lote, "notas": notas, "filas": filas, "carpeta": carpeta}


def borrar_carpeta_definitivo(carpeta: str) -> dict:
    """Borra de Postgres TODA fila que declare venir de esa carpeta. Irreversible.

    `borrar_definitivo()` trabaja por LOTE, y las filas de una misma carpeta
    acaban repartidas entre varios lotes según cuándo se retiraran. Para
    «que no quede nada de esta ruta» hace falta borrar por procedencia, no por
    lote — si no, o se dejan filas vivas o se arrastran filas de otras carpetas
    que compartían lote.

    CANDADO: exige que quede copia en disco (papelera o exportado). Nunca
    destruye la última copia de algo. Si no la encuentra, no borra y lo dice.
    """
    from . import memory
    from ..comun import audit
    marca = f"Carpeta: {carpeta}"
    copias, corpus = 0, []
    for base in (PAPELERA_DIR, EXPORT_DIR):
        if not base.exists():
            continue
        for f in base.rglob("*.md"):
            try:
                texto = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:                              # noqa: BLE001
                continue
            if marca in texto:
                copias += 1
                corpus.append(" ".join(texto.split()))
    corpus = "\n".join(corpus)
    if not copias:
        return {"ok": False, "carpeta": carpeta, "borradas": 0,
                "razon": "no encuentro ninguna copia en la papelera ni en el exportado, "
                         "así que esto sería la última copia y no la destruyo"}

    if not memory.pg.online:
        return {"ok": False, "carpeta": carpeta, "borradas": 0,
                "razon": "Postgres no responde, así que no he borrado nada"}

    # Se retira antes lo que siga activo: nada se borra sin pasar por la
    # papelera, aunque sea un instante. Así el audit cuenta los dos tiempos.
    pendientes = [f["id"] for f in memory.pg.filas_de_carpeta(carpeta)]
    if pendientes:
        memory.pg.retirar_filas(pendientes, f"carpeta-{dt.datetime.now():%Y%m%d%H%M%S}")

    filas = memory.pg._rows(
        "DELETE FROM memories WHERE content LIKE %s AND retirado_en IS NOT NULL "
        "RETURNING id", (f"%{marca}\n%",))

    # SEGUNDA PASADA — los fragmentos de continuación. Al trocear un documento,
    # la cabecera `Carpeta:` va SOLO en el primer trozo: del segundo en adelante
    # no hay nada que diga de dónde salen. Tras borrar la carpeta «20. FP DAM
    # Euroformac» quedaban 22 fragmentos así, vivos y contestando a las
    # búsquedas, con la normativa y las condiciones de pago del centro.
    #
    # El vínculo se reconstruye COTEJANDO: si el texto del fragmento aparece
    # dentro de un documento de esa carpeta que está en disco, es de esa
    # carpeta. Es una prueba, no una heurística de nombres — y por eso se coge
    # una huella del centro del fragmento, lejos de los bordes del troceo.
    huerfanas = []
    for r in memory.pg._rows(
            "SELECT id, content FROM memories WHERE retirado_en IS NULL"):
        c = " ".join(str(r["content"]).split())
        huella = c[len(c) // 3: len(c) // 3 + 120]
        if len(huella) >= 60 and huella in corpus:
            huerfanas.append(r["id"])
    if huerfanas:
        memory.pg._rows("DELETE FROM memories WHERE id = ANY(%s)", (huerfanas,))

    total = len(filas) + len(huerfanas)
    audit.log(action="purga_borrar_carpeta_definitivo", actor="operador",
              destructive=True, confirmed=True,
              result=f"{total} fila(s) borradas de «{carpeta}» "
                     f"({len(filas)} con marca, {len(huerfanas)} por cotejo)",
              targets=[{"carpeta": carpeta}],
              extra={"copias_en_disco": copias})
    return {"ok": True, "carpeta": carpeta, "borradas": total,
            "con_marca": len(filas), "por_cotejo": len(huerfanas),
            "copias_en_disco": copias}


def borrar_definitivo(lote: str) -> dict:
    """IRREVERSIBLE: destruye físicamente los ficheros de un lote en
    papelera y hace `DELETE` de las filas Postgres de ese lote. El ÚNICO
    `DELETE FROM memories` de todo el cambio 002 — solo lo alcanza quien ya
    tiene el «sí» del operador (ver el endpoint REST, protegido por
    `confirm.request()`). nexus nunca llama a esto por su cuenta."""
    items = [i for i in _cargar_papelera() if i.get("lote") == lote]
    if not items:
        return {"ok": False, "error": f"no hay nada del lote «{lote}» en la papelera"}
    borrados = []
    for it in items:
        p = Path(it["ruta_papelera"])
        try:
            if p.is_file():
                p.unlink()
            borrados.append(it["nombre"])
        except Exception:
            pass
    _guardar_papelera([i for i in _cargar_papelera() if i.get("lote") != lote])
    n_filas = 0
    try:
        from . import memory
        if memory.pg.online:
            rows = memory.pg._rows(
                "DELETE FROM memories WHERE retirado_lote = %s RETURNING id", (lote,))
            n_filas = len(rows)
    except Exception:
        pass
    from ..comun import audit
    audit.log(action="purga_borrar_definitivo", actor="operador", destructive=True,
              confirmed=True, result=f"{len(borrados)} fichero(s), {n_filas} fila(s) DEFINITIVOS",
              targets=[{"nombre": n} for n in borrados], extra={"lote": lote})
    return {"ok": True, "borrados": borrados, "filas": n_filas}
