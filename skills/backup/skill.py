"""Minion BACKUP — copias de seguridad de la memoria y datos de nexus (v19).

Lo importante de nexus vive en data/ (memoria en grafo, tablero, contactos,
agenda de vigilancias, facturas, informes…). Este minion:
  * hace una COPIA DIARIA automática (el scheduler la dispara) en
    data/backups/nexus-data-AAAAMMDD.zip, y rota: guarda las últimas 7;
  * bajo orden, copia AHORA («haz una copia de seguridad»);
  * lista las copias que hay y su tamaño («qué copias de seguridad hay»);
  * ARCHIVA la morralla de backups manuales *.bak_vXX que siembra el proyecto
    («archiva los bak») en un zip y borra los sueltos — SOLO tras verificar
    que el zip los contiene íntegros.
"""
from __future__ import annotations

import datetime as dt
import zipfile
from pathlib import Path

SKILL = {
    "name": "Backup",
    "description": "Copia diaria automática de data/ (memoria, tablero, contactos) con rotación de 7, backup bajo orden y archivado de los .bak sueltos",
    "patterns": {
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
    from backend.core.config import DATA_DIR
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


def archive_baks(project_root: Path | None = None) -> tuple[int, Path | None]:
    """Recoge los *.bak* sueltos del proyecto (backend/, frontend/, skills/,
    tests/ y raíz) en data/backups/baks-<fecha>.zip y BORRA los originales —
    solo si el zip se verifica íntegro. Devuelve (nº archivados, ruta_zip)."""
    from backend.core.config import DATA_DIR
    root = Path(project_root) if project_root else Path(DATA_DIR).parent
    _r, dest = _dirs()
    dest.mkdir(parents=True, exist_ok=True)
    baks: list[Path] = []
    for sub in ("backend", "frontend", "skills", "tests", "."):
        base = root / sub
        if not base.exists():
            continue
        import re as _re
        it = base.rglob("*.bak*") if sub != "." else base.glob("*.bak*")
        for f in it:
            # SOLO backups de verdad: «x.py.bak», «x.py.bak_v75», «x.bak_voz»…
            # (no toca un hipotético «receta.baking.md»)
            if (f.is_file() and _re.search(r"\.bak(?:_[A-Za-z0-9]+)?$", f.name)
                    and ".venv" not in f.parts and "backups" not in f.parts):
                baks.append(f)
    baks = sorted(set(baks))
    if not baks:
        return 0, None
    out = dest / f"baks-{dt.date.today():%Y%m%d}.zip"
    with zipfile.ZipFile(out, "a", zipfile.ZIP_DEFLATED) as z:
        existing = set(z.namelist())
        for f in baks:
            # BUG v23 (Windows): `str(ruta_relativa)` usa «\» y zipfile guarda
            # el nombre con «/», así que la verificación de abajo NUNCA casaba y
            # archive_baks devolvía 0 sin archivar nada. as_posix() lo arregla.
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
        from backend.core.events import bus
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
        lines = [f"  • {b['name']} — {b['mb']} MB ({b['date']})" for b in items[:10]]
        return {"reply": f"🛟 Copias de seguridad ({len(items)}):\n" + "\n".join(lines) +
                         "\nEstán en data/backups/. La diaria se hace sola y roto a 7."}

    if intent == "baks":
        n, out = archive_baks()
        if not n and out is None:
            return {"reply": "🛟 No he encontrado archivos .bak sueltos: el proyecto está limpio."}
        if not n:
            return {"reply": f"⚠ He preparado {out.name} pero la verificación no cuadró: "
                             "NO he borrado nada. Revisa data/backups/ y repite."}
        return {"reply": f"🛟 {n} archivos .bak archivados en {out.name} y eliminados de las "
                         "carpetas de trabajo. El proyecto queda limpio (y todo recuperable del zip)."}

    return {"reply": "Orden de backup no reconocida. Prueba «haz una copia de seguridad», "
                     "«qué copias de seguridad hay» o «archiva los bak»."}
