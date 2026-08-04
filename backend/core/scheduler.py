"""
nexus — Scheduler de triggers (el "minion recordador").

Bucle asíncrono que cada 20 s:
  * dispara recordatorios vencidos de la DB (escalonados 1 semana / 2 días / día D)
  * dispara alarmas y temporizadores en RAM (skill tools)
  * publica métricas de sistema al HUD (CPU/RAM/GPU aproximada)
"""
from __future__ import annotations

import asyncio
import datetime as dt

from .comun.events import bus
from .memory import pg

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# Alarmas/temporizadores en memoria: [{"at": datetime, "label": str}]
timers: list[dict] = []


def _umbral_ingesta() -> dict:
    """Lee memoria.ingesta de config/umbrales.json, con reserva si falta."""
    reserva = {"max_bytes": 5_000_000}
    try:
        from .comun.config import CONFIG_DIR
        import json
        f = CONFIG_DIR / "umbrales.json"
        if f.is_file():
            leido = (json.loads(f.read_text(encoding="utf-8")) or {}).get(
                "memoria", {}).get("ingesta") or {}
            if isinstance(leido.get("max_bytes"), (int, float)) and not isinstance(leido.get("max_bytes"), bool):
                reserva["max_bytes"] = int(leido["max_bytes"])
    except Exception:
        pass
    return reserva


async def _ingest_inbox():
    """Absorbe a memoria cualquier archivo dejado en data/memory/inbox/.
    Al terminar lo mueve a data/memory/ingested/ para no repetir.
    002-memoria-y-conocimiento (bloque C):
      * C3.1: ANTES filtraba por una lista fija de extensiones que
        RECHAZABA .docx/.pdf/.xlsx aunque files_io.read_any() ya sabía
        leerlos -- estaban desconectados sin motivo. Ahora usa
        files_io.puede_leer() (todo lo que el lector real entiende) y
        files_io.read_any(f, limite=0) para no perder nada.
      * C2.3: ANTES trozeaba con `text[:20000]` (nota local) y
        `text[i:i+900]` (Postgres) -- el 4º y último de los truncados de
        este bloque. Ahora usa rag.trocear() (o trocear_xlsx_estructurado()
        si es un .xlsx) sobre el texto ENTERO."""
    from .comun.config import DATA_DIR
    from . import rag
    from .infraestructura import files_io
    inbox = DATA_DIR / "memory" / "inbox"
    done = DATA_DIR / "memory" / "ingested"
    inbox.mkdir(parents=True, exist_ok=True)
    max_bytes = _umbral_ingesta()["max_bytes"]
    for f in list(inbox.iterdir()):
        if not f.is_file() or f.stat().st_size > max_bytes:
            continue
        ok, _motivo = files_io.puede_leer(f)
        if not ok:
            continue
        try:
            from .memory import graph, pg
            leido = files_io.read_any(f, limite=0)
            if not leido.get("ok") or leido.get("meta", {}).get("truncado"):
                await bus.emit("log", {"level": "warn",
                    "msg": f"Buzón: {f.name} rechazado ({leido.get('error') or 'truncado'})"})
                continue
            text = leido["texto"]
            graph.write_note(f"doc {f.stem[:40]}",
                             text + "\n\nEnlaces: [[buzon]] [[conocimiento]]")
            if pg.online:
                if f.suffix.lower() == ".xlsx":
                    hojas = files_io.leer_xlsx_estructurado(f)
                    trozos = rag.trocear_xlsx_estructurado(hojas)
                else:
                    trozos = rag.trocear(text)
                for trozo in trozos:
                    pg.remember(f"[{f.name}] {trozo['texto']}", kind="knowledge",
                                tags=["buzon", f.stem], origen=str(f), origen_tipo="buzon",
                                dominio="buzon")
            done.mkdir(parents=True, exist_ok=True)
            f.replace(done / f.name)
            await bus.emit("log", {"level": "ok", "msg": f"Memoria: aprendido «{f.name}» del buzón"})
            await bus.emit("notification", {"title": "Memoria", "body": f"Aprendí {f.name}"})
        except Exception as exc:
            await bus.emit("log", {"level": "warn", "msg": f"Buzón: {f.name} falló ({exc})"})


def system_metrics() -> dict:
    if not HAS_PSUTIL:
        import random
        return {"cpu": random.randint(8, 35), "ram": random.randint(40, 70),
                "disk": 61, "procs": 180, "mock": True}
    vm = psutil.virtual_memory()
    return {
        "cpu": psutil.cpu_percent(interval=None),
        "ram": vm.percent,
        "disk": psutil.disk_usage("/").percent,
        "procs": len(psutil.pids()),
        "mock": False,
    }


async def scheduler_loop():
    tick = 0
    # Cebar el contador de CPU: la primera llamada de psutil siempre devuelve 0
    if HAS_PSUTIL:
        psutil.cpu_percent(interval=None)
    while True:
        try:
            now = dt.datetime.now()

            # 1) Métricas al HUD — CADA 5 s (antes 20 s, se veía congelado)
            await bus.emit("metrics", system_metrics())

            # 2) Temporizadores en RAM
            for t in [t for t in timers if t["at"] <= now]:
                timers.remove(t)
                await bus.emit("notification", {"title": "⏰ Temporizador",
                                                "body": t["label"]})
                await bus.emit("log", {"level": "alert", "msg": f"ALARMA: {t['label']}"})

            # 3) Recordatorios escalonados en DB (cada ~20 s)
            if tick % 4 == 0 and pg.online:
                for r in pg.due_reminders():
                    days = (r["due_at"].replace(tzinfo=None) - now).days if r["due_at"] else 0
                    when = "¡HOY!" if days <= 0 else f"vence en {days} día(s)"
                    await bus.emit("reminder", {"title": r["task_title"], "when": when})
                    await bus.emit("log", {"level": "alert",
                                           "msg": f"RECORDATORIO: {r['task_title']} — {when}"})

            # 3.5) Buzón de memoria: ingiere archivos dejados en data/memory/inbox/
            if tick % 4 == 0:
                await _ingest_inbox()

            # 4) Toques de atención del tablero (cada ~1 min)
            if tick % 12 == 0:
                from . import board
                from .infraestructura.telegram_bridge import send_telegram
                for msg in board.nudges():
                    await bus.emit("notification", {"title": "Tablero", "body": msg})
                    await bus.emit("log", {"level": "alert", "msg": msg})
                    await send_telegram(msg)  # también al móvil si está enlazado

            # 5) Briefing matinal proactivo (v19): comprobación cada ~1 min;
            #    él decide si toca (hora configurada, una vez al día).
            if tick % 12 == 3:                   # desfasado del arranque
                from . import briefing
                await briefing.maybe_send()

            # 6) Vigilancias (v19): webs, precios y noticias — cada ~5 min el
            #    barrido; cada vigilancia respeta su propio intervalo interno.
            if tick % 60 == 24:                  # desfasado del arranque
                try:
                    from .skills_loader import get_skills
                    _v = get_skills().get("vigilancias")
                    if _v and _v.module:
                        await _v.module.check_watchers()
                except Exception:
                    pass

            # 6.5) Revisión semanal (v20) y consolidación nocturna de memoria:
            #      comprobaciones baratas; ellos deciden si toca.
            if tick % 12 == 9:
                from . import review
                await review.maybe_send()
            if tick % 120 == 84:
                try:
                    from . import profile
                    # tarea suelta: si el LLM tarda, el scheduler NO se retrasa
                    asyncio.create_task(profile.consolidate_daily())
                except Exception:
                    pass

            # 7) Backup diario de data/ (v19): comprobación cada ~10 min; solo
            #    crea el zip si aún no existe el de hoy (rotación de 7).
            if tick % 120 == 48:                 # desfasado del arranque (~4 min)
                try:
                    from .skills_loader import get_skills
                    _b = get_skills().get("backup")
                    if _b and _b.module:
                        await _b.module.auto_backup()
                except Exception:
                    pass
        except Exception as exc:
            await bus.emit("log", {"level": "error", "msg": f"Scheduler: {exc}"})
        tick += 1
        await asyncio.sleep(5)
