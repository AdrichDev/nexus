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
import shutil
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
    try:
        f = CONFIG_DIR / "umbrales.json"
        if f.is_file():
            crudo = json.loads(f.read_text(encoding="utf-8")) or {}
            return crudo.get("purga") or {}
    except Exception:
        pass
    return {}


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
#  B2.2 — previsualización obligatoria y previa
# ---------------------------------------------------------------------
def previsualizar() -> dict:
    """`{id, caduca, categorias:[{id, personal, items:[{ruta, motivo,
    filas_pg}]}]}`. NO cambia nada — ni un fichero se mueve, ni una fila se
    toca. Ninguna categoría viene marcada."""
    from . import memory
    clasif = clasificar()
    cfg = _umbrales_purga().get("categorias") or {}
    por_cat: dict[str, list] = {}
    for ruta, info in clasif.items():
        nombre = Path(info["ruta_abs"]).name
        filas_pg = len(memory.pg.filas_ligadas_a_nota(nombre)) if memory.pg.online else 0
        por_cat.setdefault(info["categoria"], []).append({
            "ruta": ruta, "motivo": info["regla"], "filas_pg": filas_pg})

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
                ligadas = [f["id"] for f in memory.pg.filas_ligadas_a_nota(nombre)]
                filas += memory.pg.retirar_filas(ligadas, lote)
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
