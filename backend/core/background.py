"""
nexus — Procesos de FONDO: reentreno cíclico + proactividad (Project Manager).

Dos bucles que arrancan con el servidor (ver app.py lifespan):

  cycle_loop()     — cada N horas: reindexa el RAG (conocimiento) y REENTRENA el
                     perfil del operador con Fable. nexus mejora solo, en ciclo.

  proactive_loop() — nexus toma la INICIATIVA (no solo habla cuando le hablan):
                     • dispara los recordatorios de citas/tareas que vencen
                       (escalonados: 1 semana / 2 días / al vencer);
                     • una vez al día, en horario laboral, suelta un empujón de
                       Project Manager: cómo va el día y por dónde seguir.
                     Los avisos salen al HUD (y se hablan, si proactive_speak).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json

from .comun.config import DATA_DIR, settings
from .comun.events import bus

_STATE = DATA_DIR / "proactive.json"


def _load() -> dict:
    try:
        return json.loads(_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(d: dict) -> None:
    try:
        _STATE.parent.mkdir(parents=True, exist_ok=True)
        _STATE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _in_work_hours() -> bool:
    rng = str(settings.get("proactive_hours", "9-21"))
    try:
        a, b = (int(x) for x in rng.split("-"))
    except Exception:
        a, b = 9, 21
    h = dt.datetime.now().hour
    return a <= h < b


async def _say(text: str, kind: str = "notification", title: str = "nexus") -> None:
    """Emite un aviso proactivo al HUD y, si procede, lo habla."""
    await bus.emit(kind, {"title": title, "body": text})
    await bus.emit("log", {"level": "info", "msg": f"🔔 {text[:120]}"})
    if settings.get("proactive_speak", True):
        try:
            from .infraestructura import tts
            asyncio.create_task(tts.speak(text))
        except Exception:
            pass


# ---------------------------------------------------------------- reentreno cíclico
async def cycle_loop() -> None:
    await asyncio.sleep(90)                      # deja arrancar el sistema
    while True:
        try:
            if settings.get("self_learning", True):
                from . import rag, selflearn
                n = await rag.reindex(limit=40)
                if n:
                    await bus.emit("log", {"level": "info",
                                           "msg": f"📚 RAG: {n} documentos indexados en conocimiento"})
                prof = await selflearn.retrain(force=True)
                if prof:
                    await bus.emit("log", {"level": "ok",
                                           "msg": "🧠 Me he reentrenado solo (perfil actualizado)"})
        except Exception:
            pass
        hours = float(settings.get("retrain_hours", 6) or 6)
        await asyncio.sleep(max(0.5, hours) * 3600)


# ---------------------------------------------------------------- proactividad (PM)
async def proactive_loop() -> None:
    await asyncio.sleep(60)
    while True:
        try:
            if settings.get("proactive", True):
                await _check_reminders()
                await _daily_nudge()
        except Exception:
            pass
        mins = float(settings.get("proactive_minutes", 30) or 30)
        await asyncio.sleep(max(5, mins) * 60)


async def _check_reminders() -> None:
    """Dispara los recordatorios (de citas/tareas) que ya toca avisar."""
    try:
        from .memory import pg
        online = await asyncio.to_thread(lambda: pg.online)
        if not online:
            return
        due = await asyncio.to_thread(pg.due_reminders)
    except Exception:
        return
    for r in due or []:
        title = r.get("task_title", "algo")
        when = str(r.get("due_at", ""))[:16].replace("T", " ")
        await _say(f"Recordatorio: «{title}»" + (f" — vence {when}" if when else "") + ".",
                   kind="reminder", title="Recordatorio")


async def _daily_nudge() -> None:
    """Una vez al día, en horario laboral: empujón de Project Manager.

    En modo PM FUERTE (pm_strong), en vez de un saludo genérico PREGUNTA por una
    tarea concreta («¿cómo vas con X?») y deja preparado el seguimiento: tu respuesta
    la moverá de estado sola (ver pm.apply_followup)."""
    if not _in_work_hours():
        return
    st = _load()
    today = dt.date.today().isoformat()
    if st.get("nudge_day") == today:
        return
    op = settings.get("operator_name", "jefe")
    h = dt.datetime.now().hour
    saludo = "Buenos días" if h < 13 else ("Buenas tardes" if h < 21 else "Buenas noches")
    text = ""

    # MODO PM FUERTE: pregunta por una tarea concreta y arma el seguimiento.
    if settings.get("pm_strong", True):
        try:
            from . import pm
            task = pm.pick_task_for_followup()
        except Exception:
            task = None
        if task:
            title = task.get("title", "")
            hint = ""
            if task.get("due"):
                try:
                    d = (dt.date.fromisoformat(task["due"]) - dt.date.today()).days
                    hint = (f" (venció hace {-d} día{'s' if -d != 1 else ''})" if d < 0
                            else " (vence hoy)" if d == 0
                            else f" (vence en {d} día{'s' if d != 1 else ''})")
                except Exception:
                    hint = ""
            text = (f"{saludo}, {op}. ¿Cómo llevas «{title}»{hint}? Dime si está hecha, "
                    "en marcha o aún no, y la actualizo yo en el tablero.")
            try:
                pm.set_followup(task.get("id", ""), title)
            except Exception:
                pass

    # Modo normal (o sin tareas): empujón genérico con el LLM (como antes).
    if not text:
        try:
            from .infraestructura import llm
            pending = _pending_hint()
            msg = await llm.ask_llm(
                "Eres mi Project Manager. Dame UN empujón corto (2-3 frases, tono cercano) "
                "para encarar el día: salúdame por mi nombre, y si sabes algo pendiente "
                "propón por dónde empezar. Sé concreto y útil, sin relleno." + pending,
                system=("Eres nexus, el asistente/PM de " + op + ". Hablas breve y al grano, "
                        "orientas y priorizas. No te inventes tareas que no conoces."))
            text = (msg[0] if isinstance(msg, tuple) else str(msg)).strip()
        except Exception:
            text = ""
    if not text or len(text) < 8:
        text = f"Buenas, {op}. Arranco el día contigo: dime en qué te ayudo y lo priorizamos."
    await _say(text, kind="notification", title="Tu PM")
    st["nudge_day"] = today
    _save(st)


def _pending_hint() -> str:
    """Pistas de lo pendiente (recordatorios/objetivos) para el empujón, si la DB va."""
    try:
        from .memory import pg
        if not pg.online:
            return ""
        goals = pg.goals()
        if goals:
            g = ", ".join(x.get("title", "") for x in goals[:3])
            return f"\n\nObjetivos activos que conozco: {g}."
    except Exception:
        pass
    return ""
