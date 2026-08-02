"""
nexus — Autonomía de PROJECT MANAGER (modo «pm_strong», ⚙).

Dos capacidades que hacen que nexus gestione tareas por su cuenta, no solo cuando
se lo pides:

  1) AUTO-CAPTURA — detecta COMPROMISOS en lo que hablas ("tengo que llamar al
     proveedor", "hay que preparar el pedido", "debería enviar la factura")
     y crea la tarea SOLO en el tablero, avisándote con transparencia.

  2) SEGUIMIENTO — cuando el empujón diario te pregunta "¿cómo vas con «X»?", tu
     respuesta ("ya está" / "voy a medias" / "aún no") la interpreta y MUEVE la
     tarea de estado él solo (completada / en progreso / revisión).

El MODELO razona (no listas fijas): un pre-filtro barato evita gastar una llamada al
LLM en cada frase. Todo está bajo el interruptor settings.pm_strong; si está apagado,
nexus vuelve a solo avisar/sugerir sin tocar el tablero por su cuenta.
"""
from __future__ import annotations

import datetime as dt
import json
import re

from . import board, llm
from .config import DATA_DIR, settings
from .events import bus

_FOLLOWUP = DATA_DIR / "pm_followup.json"


def pm_on() -> bool:
    return bool(settings.get("pm_strong", True))


def _today() -> str:
    return dt.date.today().isoformat()


async def _ask(system: str, user: str) -> str:
    """Una consulta limpia al modelo (sin el system enorme de JARVIS). Sin modelo
    real (mock) devuelve '' → la autonomía no hace nada raro."""
    try:
        prov = await llm.get_provider_safe()      # None = no hay cerebro vivo
        if prov is None or getattr(prov, "name", "mock") == "mock":
            return ""
        out = await prov.chat([{"role": "system", "content": system},
                               {"role": "user", "content": user}])
        return (out or "").strip()
    except Exception:
        return ""


# ============================================================ 1) AUTO-CAPTURA
# Pistas BARATAS de compromiso: solo si aparecen gastamos una llamada al LLM.
_COMMIT_RX = re.compile(
    r"\b(tengo que|teng[oa] que|hay que|debo\b|deber[ií]a(?:mos)?|me toca|"
    r"tengo pendiente|pendiente de|no me olvides de|acu[eé]rdate de|"
    r"necesito\s+(?:hacer|llamar|enviar|mandar|comprar|preparar|terminar|acabar|"
    r"revisar|escribir|pedir|reservar|pagar|arreglar|hablar|contactar|mirar)|"
    r"a ver si\s+(?:hago|llamo|env[ií]o|preparo|termino|acabo|escribo)|"
    r"quiero\s+(?:hacer|terminar|preparar|acabar|montar))\b", re.IGNORECASE)


async def capture_commitment(text: str) -> str | None:
    """Si el usuario expresa un COMPROMISO accionable, crea la tarea sola y devuelve
    el aviso ('📋 Te lo he apuntado…'). None si no hay tarea. Solo llama al LLM cuando
    hay una pista de compromiso → no encarece la conversación normal."""
    if not pm_on() or not text or not _COMMIT_RX.search(text):
        return None
    op = settings.get("operator_name", "el jefe")
    sysp = (
        f"Eres el detector de tareas de nexus, el asistente de {op}. Lee el mensaje y "
        "decide si contiene un COMPROMISO o PENDIENTE accionable que convenga APUNTAR "
        "(algo que {o} hará en el futuro: llamar, enviar, preparar, comprar, terminar, "
        "revisar…). ".format(o=op)
        + f"Hoy es {_today()}. "
        'Si SÍ, responde SOLO un JSON en una línea: '
        '{"task":"<título corto, imperativo>","due":"<YYYY-MM-DD o vacío>","priority":"<alta|media|baja>"}. '
        "Pon 'due' solo si el usuario menciona una fecha o plazo; si no, déjalo vacío. "
        "Prioridad alta solo si suena urgente/importante. "
        "Si NO es una tarea (charla, saludo, pregunta, opinión, o una orden que ya se "
        "ejecuta como 'pon música' o 'apaga la tele'), responde EXACTAMENTE: NONE.")
    out = await _ask(sysp, text)
    if not out or out.strip().upper().startswith("NONE"):
        return None
    m = re.search(r"\{.*\}", out, re.DOTALL)       # extrae el JSON aunque venga rodeado
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return None
    title = (obj.get("task") or "").strip().rstrip(".")
    if not title or len(title) < 3:
        return None
    due = (obj.get("due") or "").strip() or None
    if due and not re.match(r"^\d{4}-\d{2}-\d{2}$", due):
        due = None
    prio = (obj.get("priority") or "media").strip().lower()
    if prio not in ("alta", "media", "baja"):
        prio = "media"
    try:
        board.add_task(title, due=due, priority=prio)
    except Exception:
        return None
    extra = f" (para el {due})" if due else ""
    try:
        await bus.emit("log", {"level": "ok", "msg": f"📋 Tarea auto-creada: «{title}»{extra}"})
    except Exception:
        pass
    return f"📋 Te lo he apuntado como tarea: «{title}»{extra} — está en PENDIENTES del tablero."


# ============================================================ 2) SEGUIMIENTO
def _load_followup() -> dict:
    try:
        return json.loads(_FOLLOWUP.read_text(encoding="utf-8"))
    except Exception:
        return {}


def set_followup(task_id: str, title: str) -> None:
    """Recuerda por qué tarea preguntó el empujón, para interpretar la respuesta."""
    try:
        _FOLLOWUP.parent.mkdir(parents=True, exist_ok=True)
        _FOLLOWUP.write_text(json.dumps(
            {"id": task_id, "title": title, "tries": 0, "at": dt.datetime.now().isoformat()},
            ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def clear_followup() -> None:
    try:
        _FOLLOWUP.unlink(missing_ok=True)
    except Exception:
        pass


# Pistas baratas de «respuesta de avance» (para no interceptar órdenes normales).
_ANSWER_RX = re.compile(
    r"\b(ya\b|hecho|hecha|termin|acab|complet|list[oa]|finiquit|"
    r"en ello|a medias|a medio|empezad|empec|empez|voy|progres|haci[eé]ndo|metido|"
    r"revis|repas|"
    r"a[uú]n no|todav[ií]a no|no he|no la he|no lo he|sin empezar|ma[ñn]ana|"
    r"m[aá]s tarde|luego|no he podido|nada)\b", re.IGNORECASE)

_STATE_OF = {"DONE": "completada", "PROGRESS": "progreso",
             "REVIEW": "revision", "PENDING": "pendiente"}


async def apply_followup(text: str) -> str | None:
    """Si hay un follow-up pendiente y el mensaje parece una respuesta de avance,
    interpreta y MUEVE la tarea. Devuelve la confirmación, o None si no aplica (para
    que el mensaje siga su curso normal como orden/charla)."""
    if not pm_on() or not text:
        return None
    fu = _load_followup()
    if not fu or not fu.get("id"):
        return None
    # pre-filtro: si no suena a respuesta de avance y no es corta, NO interceptamos
    if len(text.split()) > 6 and not _ANSWER_RX.search(text):
        return None
    title = fu.get("title", "esa tarea")
    op = settings.get("operator_name", "el jefe")
    sysp = (
        f"nexus preguntó a {op} cómo va la tarea «{title}». Clasifica su RESPUESTA en UNA "
        "sola palabra: DONE (terminada/hecha/lista), PROGRESS (en ello, a medias, empezada), "
        "REVIEW (en revisión, repasando), PENDING (aún no, no ha podido, la deja para luego), "
        "NONE (la respuesta NO habla de esa tarea, cambia de tema o es otra orden distinta). "
        "Responde SOLO con esa palabra, sin nada más.")
    raw = (await _ask(sysp, text)).strip().upper()
    verdict = re.sub(r"[^A-Z]", "", raw.split()[0]) if raw.split() else ""
    if verdict not in _STATE_OF:
        # gasta un intento; a los 2 fallidos soltamos el follow-up para no insistir
        fu["tries"] = int(fu.get("tries", 0)) + 1
        if fu["tries"] >= 2:
            clear_followup()
        else:
            try:
                _FOLLOWUP.write_text(json.dumps(fu, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
        return None
    clear_followup()
    if verdict == "PENDING":
        return (f"Vale, dejo «{title}» en pendientes. Cuando la arranques dime «muévela a "
                "en progreso» y la actualizo. ¿Te la reprogramo para otro día?")
    t = board.move_task(fu["id"], _STATE_OF[verdict])
    if not t:
        return None
    label = {"completada": "COMPLETADAS 🎉", "progreso": "EN PROGRESO",
             "revision": "EN REVISIÓN"}[_STATE_OF[verdict]]
    return f"Anotado: muevo «{title}» → {label}."


# ============================================================ empujón diario
def pick_task_for_followup() -> dict | None:
    """Elige la tarea sobre la que preguntar en el empujón diario: primero vencidas,
    luego a punto de vencer, luego en progreso / pendientes / revisión. None si el
    tablero está limpio."""
    try:
        late, soon = board.overdue()
    except Exception:
        late, soon = [], []
    if late:
        return late[0]
    if soon:
        return soon[0]
    try:
        b = board.board()
    except Exception:
        return None
    for st in ("progreso", "pendiente", "revision"):
        if b.get(st):
            return b[st][0]
    return None
