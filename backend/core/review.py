"""
nexus — REVISIÓN SEMANAL del tablero (v20): el cierre del ciclo de tareas.

El domingo (configurable) nexus repasa la semana ÉL SOLO y te lo canta por el
HUD y Telegram: qué se completó, qué lleva demasiado tiempo muerto en
pendientes (¿matar o replanificar?), qué venció sin hacerse, qué informes y
encargos salieron, y una propuesta de foco para la semana entrante.
También a demanda: «revisión semanal» / «balance de la semana» (skill coach).

Settings: weekly_review_enabled (false por defecto), weekly_review_day (6 =
domingo; 0 = lunes), weekly_review_hour ("19:00"). Estado en
data/review_state.json (semana ISO ya enviada).
"""
from __future__ import annotations

import datetime as dt
import json
import time

from .config import DATA_DIR, settings

_STATE = DATA_DIR / "review_state.json"
STALE_DAYS = 14


def _state_load() -> dict:
    try:
        d = json.loads(_STATE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _state_save(d: dict) -> None:
    try:
        _STATE.parent.mkdir(parents=True, exist_ok=True)
        _STATE.write_text(json.dumps(d), encoding="utf-8")
    except Exception:
        pass


def review_due(now: dt.datetime, enabled: bool, day: int, hour_str: str,
               last_week: str) -> bool:
    """¿Toca la revisión? PURA: activada + es el día configurado + pasó la hora
    + esta semana ISO aún no se mandó."""
    if not enabled or now.weekday() != int(day):
        return False
    try:
        hh, mm = (hour_str or "19:00").strip().split(":")
        target = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    except Exception:
        return False
    week = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
    return now >= target and last_week != week


def _parse_date(s: str):
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except Exception:
        return None


def build_weekly_review(today: dt.date | None = None) -> str:
    """Construye el balance de la semana con datos REALES del tablero, los
    informes y los encargos. Cada sección es a prueba de fallos."""
    today = today or dt.date.today()
    week_ago = today - dt.timedelta(days=7)
    lines = [f"📋 REVISIÓN SEMANAL — semana del {week_ago:%d/%m} al {today:%d/%m}"]

    # Tablero
    try:
        from . import board
        b = board.board()
        done = b.get("completada", [])
        done_week = [t for t in done
                     if (_parse_date(t.get("completed") or t.get("created"))
                         or week_ago) >= week_ago]
        pend = b.get("pendiente", []) + b.get("progreso", [])
        stale = [t for t in pend
                 if (_parse_date(t.get("created")) or today)
                 <= today - dt.timedelta(days=STALE_DAYS)]
        late, _soon = board.overdue()
        lines.append(f"✔ Completadas: {len(done_week)} esta semana ({len(done)} en total)."
                     + ((" Últimas: " + ", ".join(f"«{t['title']}»" for t in done_week[:3]))
                        if done_week else ""))
        if late:
            lines.append("🔴 Vencidas sin hacer: "
                         + "; ".join(f"«{t['title']}» ({t.get('due', '')})" for t in late[:4]))
        if stale:
            lines.append(f"🪦 Muertas +{STALE_DAYS} días: "
                         + "; ".join(f"«{t['title']}»" for t in stale[:4])
                         + " — ¿las mato o les pongo fecha? Di «borra la tarea X» o "
                           "«mueve X a en progreso».")
        if not late and not stale:
            lines.append("🟢 Nada vencido ni estancado. Semana limpia.")
    except Exception:
        pass

    # Informes generados
    try:
        reports = DATA_DIR / "reports"
        recent = [f for f in reports.glob("*.md")
                  if f.stat().st_mtime >= time.time() - 7 * 86400] if reports.exists() else []
        if recent:
            lines.append(f"📚 Informes de la semana: {len(recent)} "
                         f"({', '.join(f.stem[:30] for f in recent[:3])}…). Di «mis informes».")
    except Exception:
        pass

    # Encargos a Hermes
    try:
        jobs = json.loads((DATA_DIR / "hermes_jobs.json").read_text(encoding="utf-8"))
        hechos = [j for j in jobs if j.get("estado") == "hecho"
                  and (time.time() - (j.get("t1") or 0)) < 7 * 86400]
        if hechos:
            lines.append(f"🪽 Encargos terminados: {len(hechos)} "
                         f"({', '.join('#' + str(j.get('num', '?')) for j in hechos[:5])}).")
    except Exception:
        pass

    # Propuesta de foco
    try:
        from . import board as _b
        quad = _b.eisenhower()
        focus = quad.get("hacer_ya") or quad.get("planificar") or []
        if focus:
            lines.append("🎯 Foco propuesto para la semana: "
                         + "; ".join(f"«{t['title']}»" for t in focus[:3])
                         + ". Empieza por la primera el lunes a primera hora.")
    except Exception:
        pass

    lines.append("Di «organiza mis tareas por urgencia» para el plan de ataque completo.")
    return "\n".join(lines)


async def maybe_send() -> bool:
    """Llamado por el scheduler cada ~1 min: manda la revisión si toca."""
    now = dt.datetime.now()
    st = _state_load()
    if not review_due(now, bool(settings.get("weekly_review_enabled", False)),
                      int(settings.get("weekly_review_day", 6)),
                      str(settings.get("weekly_review_hour", "19:00")),
                      st.get("last_week", "")):
        return False
    txt = build_weekly_review()
    from .events import bus
    await bus.emit("chat", {"user": "[revisión semanal automática]", "reply": txt,
                            "provider": "nexus", "skill": "coach", "channel": "pc"})
    await bus.emit("notification", {"title": "📋 Revisión semanal",
                                    "body": "El balance de tu semana está en el chat."})
    try:
        from .telegram_bridge import send_telegram
        await send_telegram(txt)
    except Exception:
        pass
    st["last_week"] = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
    _state_save(st)
    return True
