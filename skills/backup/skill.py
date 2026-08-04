"""Minion BACKUP — copias de seguridad de la memoria y datos de nexus.

Lo importante de nexus vive en data/ (memoria en grafo, tablero, contactos,
agenda de vigilancias, facturas, informes). Este minion:
  * hace una COPIA DIARIA automática (la dispara el scheduler) en
    data/backups/nexus-data-AAAAMMDD.zip, y rota: guarda las últimas KEEP;
  * copia AHORA bajo orden («haz una copia de seguridad»);
  * lista los zips que hay y su tamaño («qué copias de seguridad hay»);
  * ARCHIVA los backups manuales *.bak_vXX sueltos del proyecto en un zip y
    borra los originales — pidiendo confirmación y solo tras verificar el zip;
  * explica cómo RESTAURAR, pero no restaura por su cuenta.
"""
from __future__ import annotations

import datetime as dt
import zipfile
from pathlib import Path

SKILL = {
    "name": "Backup",
    "description": "Copia diaria automática de data/ (memoria, tablero, contactos) con rotación de 7, backup bajo orden y archivado de los .bak sueltos",
    # 'restore' va antes que 'make': «restaura la copia de seguridad» contiene
    # «copia de seguridad» y si no, 'make' se lo llevaría.
    "patterns": {
        "restore": r"(?:restaura(?:me)?|restablece(?:me)?|recupera(?:me)?|revierte|vuelve\s+a)\s+"
                   r"(?:la\s+|el\s+|una\s+|un\s+)?(?:copia\s+de\s+seguridad|backups?|"
                   r"copia\s+de\s+ayer)",
        "list": r"(?:qu[eé]|cu[aá]ntas)\s+copias\s+de\s+seguridad|(?:ver|lista(?:me)?|mu[eé]strame)\s+"
                r"(?:las\s+|los\s+)?(?:copias\s+de\s+seguridad|backups?)\b|\bmis\s+backups?\b",
        "baks": r"(?:archiva|recoge|limpia|empaqueta)\s+(?:los\s+)?(?:\.?bak(?:s)?|backups?\s+manuales|"
                r"archivos\s+bak)\b",
        "make": r"(?:haz(?:me)?|crea(?:me)?|genera(?:me)?)\s+(?:una\s+|la\s+)?copia\s+de\s+seguridad"
                r"|\bhaz(?:me)?\s+(?:un\s+)?backup\b|\bbackup\s+ahora\b",
    },
}

KEEP = 7                     # rotación: cuántas copias diarias se conservan
_EXCLUDE_DIRS = {"backups", "chrome_nexus"}      # no auto-anidar ni perfiles de Chrome
_MAX_FILE = 50 * 1024 * 1024                     # por archivo (los gordos no van al zip)


def _dirs():
    from backend.core.comun.config import DATA_DIR
    root = Path(DATA_DIR)
    dest = root / "backups"
    return root, dest


def make_backup() -> tuple[Path, int]:
    """Zipea data/ (sin data/backups ni perfiles) → (ruta_zip, nº archivos)."""
    root, dest = _dirs()
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"nexus-data-{dt.date.today():%Y%m%d}.zip"
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        if root.exists():
            for f in root.rglob("*"):
                if not f.is_file() or f.stat().st_size > _MAX_FILE:
                    continue
                rel = f.relative_to(root)
                if rel.parts and rel.parts[0] in _EXCLUDE_DIRS:
                    continue
                z.write(f, str(rel))
                count += 1
    rotate_backups()
    return out, count


def rotate_backups(keep: int = KEEP) -> int:
    """Borra las copias diarias más viejas dejando las últimas `keep`."""
    _root, dest = _dirs()
    zips = sorted(dest.glob("nexus-data-*.zip"))
    removed = 0
    for old in zips[:-keep] if len(zips) > keep else []:
        try:
            old.unlink()
            removed += 1
        except Exception:
            pass
    return removed


def list_backups() -> list[dict]:
    _root, dest = _dirs()
    out = []
    for f in sorted(dest.glob("*.zip"), reverse=True):
        out.append({"name": f.name, "mb": round(f.stat().st_size / 1e6, 2),
                    "date": dt.datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m %H:%M")})
    return out


def project_root(explicit: Path | None = None) -> Path:
    from backend.core.comun.config import DATA_DIR
    return Path(explicit) if explicit else Path(DATA_DIR).parent


def find_baks(root: Path) -> list[Path]:
    """Los *.bak* sueltos de backend/, frontend/, skills/, tests/ y la raíz.
    Solo backups de verdad («x.py.bak», «x.py.bak_v75»), no «receta.baking.md»."""
    import re as _re
    baks: list[Path] = []
    for sub in ("backend", "frontend", "skills", "tests", "."):
        base = root / sub
        if not base.exists():
            continue
        it = base.rglob("*.bak*") if sub != "." else base.glob("*.bak*")
        for f in it:
            if (f.is_file() and _re.search(r"\.bak(?:_[A-Za-z0-9]+)?$", f.name)
                    and ".venv" not in f.parts and "backups" not in f.parts):
                baks.append(f)
    return sorted(set(baks))


def archive_baks(project_root_dir: Path | None = None) -> tuple[int, Path | None]:
    """Recoge los *.bak* sueltos en data/backups/baks-<fecha>.zip y BORRA los
    originales — solo si el zip se verifica íntegro. Devuelve (nº, ruta_zip).
    Destructivo: desde el chat solo se llama detrás de confirm.request()."""
    root = project_root(project_root_dir)
    _r, dest = _dirs()
    dest.mkdir(parents=True, exist_ok=True)
    baks = find_baks(root)
    if not baks:
        return 0, None
    out = dest / f"baks-{dt.date.today():%Y%m%d}.zip"
    with zipfile.ZipFile(out, "a", zipfile.ZIP_DEFLATED) as z:
        existing = set(z.namelist())
        for f in baks:
            # as_posix(): zipfile guarda los nombres con «/» y en Windows
            # str(ruta_relativa) da «\», con lo que la verificación no casaría.
            arc = f.relative_to(root).as_posix()
            if arc not in existing:
                z.write(f, arc)
    # verificación: el zip abre, no está corrupto y contiene TODO con su tamaño
    with zipfile.ZipFile(out) as z:
        if z.testzip() is not None:
            return 0, out
        names = set(z.namelist())
        for f in baks:
            arc = f.relative_to(root).as_posix()
            if arc not in names or z.getinfo(arc).file_size != f.stat().st_size:
                return 0, out
    for f in baks:
        try:
            f.unlink()
        except Exception:
            pass
    return len(baks), out


# ───────────── automático (lo llama el scheduler una vez al día) ─────────────

async def auto_backup() -> bool:
    """Copia diaria si aún no existe la de hoy. Silenciosa salvo en el log."""
    _root, dest = _dirs()
    today = dest / f"nexus-data-{dt.date.today():%Y%m%d}.zip"
    if today.exists():
        return False
    try:
        import asyncio as _aio
        out, n = await _aio.to_thread(make_backup)   # el zip NO congela el HUD
        from backend.core.comun.events import bus
        await bus.emit("log", {"level": "ok",
                               "msg": f"🛟 Backup diario: {out.name} ({n} archivos)"})
        return True
    except Exception:
        return False


async def handle(intent: str, text: str, match, ctx) -> dict:
    if intent == "make":
        import asyncio as _aio
        out, n = await _aio.to_thread(make_backup)
        mb = round(out.stat().st_size / 1e6, 2)
        return {"reply": f"🛟 Copia de seguridad hecha: {out.name} — {n} archivos, {mb} MB "
                         f"(data/backups/). Guardo las últimas {KEEP} copias diarias."}

    if intent == "list":
        items = list_backups()
        if not items:
            return {"reply": "🛟 No hay copias todavía. Di «haz una copia de seguridad» "
                             "(además, cada día hago una sola)."}
        lines = [f"  • {b['name']} — {b['mb']} MB ({b['date']})"
                 + (" [archivo de .bak, no rota]" if b["name"].startswith("baks-") else "")
                 for b in items[:10]]
        return {"reply": f"🛟 Zips en data/backups/ ({len(items)}):\n" + "\n".join(lines) +
                         f"\nLa copia diaria (nexus-data-*) se hace sola y roto a {KEEP}. "
                         "Di «restaura la copia de seguridad» y te explico cómo volver atrás."}

    if intent == "baks":
        # Archivar BORRA los originales: no se hace sin un sí explícito.
        from backend.core.comun import confirm
        root = project_root()
        baks = find_baks(root)
        if not baks:
            return {"reply": "🛟 No he encontrado archivos .bak sueltos: el proyecto está limpio."}

        def _ejecutar():
            n, out = archive_baks()
            if not n:
                return (f"⚠ He preparado {out.name} pero la verificación no cuadró: "
                        "NO he borrado nada. Revisa data/backups/ y repite.")
            return (f"🛟 {n} archivos .bak archivados en {out.name} y eliminados de las "
                    "carpetas de trabajo. Todo recuperable del zip.")

        muestra = "\n".join(f"    • {f.relative_to(root).as_posix()}" for f in baks[:12])
        resto = f"\n    … y {len(baks) - 12} más" if len(baks) > 12 else ""
        pregunta = (f"🛟 Voy a meter {len(baks)} archivo(s) .bak en un zip y BORRAR los "
                    f"originales:\n{muestra}{resto}\n"
                    "Solo borro si el zip se verifica íntegro. ¿Lo confirmas? «sí» o «no».")
        return {"reply": confirm.request(
            channel=(ctx.get("channel") or "pc"), kind="archivar_baks", summary=pregunta,
            action=_ejecutar, request_text=text,
            targets=[{"path": f.relative_to(root).as_posix()} for f in baks],
            cancel_reply="Vale, no toco ningún .bak."),
            "data": {"confirm": True, "count": len(baks)}}

    if intent == "restore":
        # Restaurar sobrescribiría data/ en caliente (memoria, tablero, agenda)
        # con nexus corriendo encima: se explica cómo hacerlo, no se hace.
        items = list_backups()
        if not items:
            return {"reply": "🛟 No tengo ninguna copia que restaurar. Di «haz una copia de "
                             "seguridad» y a partir de ahí habrá algo a lo que volver."}
        lines = "\n".join(f"    • {b['name']} — {b['mb']} MB ({b['date']})" for b in items[:5])
        return {"reply": "🛟 Restaurar NO lo hago yo: sobrescribiría tu memoria, tu tablero y "
                         "tu agenda mientras nexus está en marcha, y eso no tiene vuelta "
                         "atrás.\nHazlo tú en 3 pasos, con nexus cerrado:\n"
                         "  1. Cierra nexus.\n"
                         "  2. Renombra la carpeta `data/` a `data_viejo/` (no la borres).\n"
                         "  3. Descomprime encima el zip que quieras de `data/backups/`.\n"
                         f"Copias disponibles:\n{lines}\n"
                         "Si algo no cuadra, `data_viejo/` sigue ahí intacta."}

    return {"reply": "Orden de backup no reconocida. Prueba «haz una copia de seguridad», "
                     "«qué copias de seguridad hay», «archiva los bak» (te pido "
                     "confirmación) o «restaura la copia de seguridad»."}
