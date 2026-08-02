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
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
import unicodedata
import uuid
from pathlib import Path

from .config import CONFIG_DIR, DATA_DIR

MEMORY_DIR = DATA_DIR / "memory"
PAPELERA_DIR = MEMORY_DIR / "papelera"
PAPELERA_FILE = PAPELERA_DIR / "papelera.json"
EXPORT_DIR = DATA_DIR / "exportado_purga"

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
def previsualizar() -> dict:
    """`{id, caduca, categorias:[{id, personal, items:[{ruta, motivo,
    filas_pg, filas:[{id, motivo}]}]}]}`. NO cambia nada — ni un fichero se
    mueve, ni una fila se toca. Ninguna categoría viene marcada.

    Cada fila llega con SU motivo, igual que las notas: o la marca de origen
    la delata, o la casó el vocabulario (y entonces se dice cuánto solapa).
    `aplicar()` retira exactamente estos ids, no los que recalcule después:
    lo que se enseña es lo que se hace."""
    from . import memory
    clasif = clasificar()
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

    if "duplicados-exactos" in cfg:
        grupos = memory.pg.duplicados_exactos() if memory.pg.online else []
        items = [{"ruta": None, "fila_id": fila["id"],
                  "motivo": (f"duplicado exacto de la huella {g['huella'][:12]}… "
                             f"(se conserva id {g['conservar']['id']})")}
                 for g in grupos for fila in g["sobran"]]
        if items:
            por_cat["duplicados-exactos"] = items

    categorias_out = [{"id": cat_id, "personal": bool(cfg.get(cat_id, {}).get("personal", False)),
                       "items": items} for cat_id, items in por_cat.items()]
    plan_id = f"purga-{uuid.uuid4().hex[:10]}"
    minutos = int(_umbrales_purga().get("minutos_vigencia_plan", 30))
    caduca_dt = dt.datetime.now() + dt.timedelta(minutes=minutos)
    plan = {"id": plan_id, "caduca": caduca_dt.isoformat(timespec="seconds"),
            "categorias": categorias_out}
    _planes[plan_id] = {**plan, "_caduca_dt": caduca_dt, "_huella_corpus": _huella_corpus()}
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
            from .events import bus
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
    for item in cat["items"]:
        if item.get("ruta"):
            nombre = Path(item["ruta"]).name
            if cat["personal"]:
                _exportar_copia_personal(MEMORY_DIR / item["ruta"], lote)
            r = retirar_nota(item["ruta"], lote)
            if r["movido"]:
                movidas += 1
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
    return {"notas": movidas, "symlinks_omitidos": symlinks, "filas": filas}


# ---------------------------------------------------------------------
#  B3.1 — aplicar (categoría por categoría, plan vigente y NO rancio)
# ---------------------------------------------------------------------
def aplicar(plan_id: str, categorias: list[str], acepto_personal: bool = False) -> dict:
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
    for cat_id in categorias:
        resultado[cat_id] = _retirar_categoria(cats_plan[cat_id], lote)
        if cat_id == "duplicados-exactos":
            # Orden obligado (diseño §4): el índice único solo se crea DESPUÉS
            # de confirmar la limpieza, y solo si ya no quedan grupos.
            try:
                from . import memory
                memory.pg.crear_indice_huella()
            except Exception:
                pass
    _planes.pop(plan_id, None)
    from . import audit
    audit.log(action="purga_aplicar", actor="operador", destructive=True, confirmed=True,
              request=str(categorias), result=f"lote {lote}: {resultado}",
              extra={"plan_id": plan_id, "lote": lote, "categorias": categorias})
    return {"ok": True, "lote": lote, "categorias": resultado}


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
    from . import audit
    audit.log(action="purga_restaurar", actor="operador", destructive=False, confirmed=True,
              result=f"{len(restauradas)} nota(s), {n_filas} fila(s)", extra={"lote": lote})
    return {"ok": True, "restauradas": restauradas, "filas": n_filas}


# ---------------------------------------------------------------------
#  B3.4 — exportar / borrado definitivo (PASO 2, lo inicia el usuario)
# ---------------------------------------------------------------------
def exportar(lote: str, destino: str | None = None) -> dict:
    from . import permissions
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
    from . import audit
    audit.log(action="purga_exportar", actor="operador", destructive=False, confirmed=True,
              result=f"{len(copiados)} fichero(s) a {dest_dir}", extra={"lote": lote})
    return {"ok": True, "copiados": copiados, "destino": str(dest_dir)}


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
    from . import audit
    audit.log(action="purga_borrar_definitivo", actor="operador", destructive=True,
              confirmed=True, result=f"{len(borrados)} fichero(s), {n_filas} fila(s) DEFINITIVOS",
              targets=[{"nombre": n} for n in borrados], extra={"lote": lote})
    return {"ok": True, "borrados": borrados, "filas": n_filas}
