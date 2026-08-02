"""
nexus — Tablero de tareas estilo Notion/kanban.

Estados (columnas): pendiente → progreso → revision → completada
Estados extra (no son columna del HUD): cancelada, archivada
Persistencia: data/board.json (siempre) + espejo en DB si está online.
Papelera:     data/board_trash.json  ← v23
Los "toques de atención" los dispara el scheduler con nudges().

v23 (specs v23, TAREAS 2 y 3) — a raíz del incidente del 25/07/2026, en el que
«limpia las tareas ya realizadas» vació las 15 tareas del tablero:
  * BORRADO LÓGICO: nada se borra de verdad. Todo pasa por la PAPELERA con
    deletedAt / deletedBy / deletionReason / previousStatus / batch, y se puede
    restaurar tal cual estaba (incluida su columna anterior).
  * SELECCIÓN POR ESTADO REAL: select("completadas") jamás devuelve pendientes.
    clear_completed() no puede tocar una tarea que no esté en 'completada'.
  * Cada borrado va con un BATCH (lote) para poder deshacer «lo último» entero.
  * Todo borrado queda en la auditoría (backend/core/audit.py).
"""
from __future__ import annotations

import datetime as dt
import json
import unicodedata
import uuid

from .config import DATA_DIR

BOARD_FILE = DATA_DIR / "board.json"
TRASH_FILE = DATA_DIR / "board_trash.json"

# Columnas del kanban (contrato del HUD y de /api/board: NO se tocan).
STATES = ["pendiente", "progreso", "revision", "completada"]
# Estados válidos que NO son columna: se guardan en la tarea y se respetan.
EXTRA_STATES = ["cancelada", "archivada"]
ALL_STATES = STATES + EXTRA_STATES

# Equivalencia con la nomenclatura de las specs v23 (pending, in_progress…).
STATUS_OF = {"pendiente": "pending", "progreso": "in_progress",
             "revision": "in_review", "completada": "completed",
             "cancelada": "cancelled", "archivada": "archived"}

STATE_ALIAS = {
    "pendiente": "pendiente", "pendientes": "pendiente", "por hacer": "pendiente",
    "progreso": "progreso", "en progreso": "progreso", "haciendo": "progreso",
    "revision": "revision", "en revision": "revision", "en revisión": "revision",
    "revisión": "revision",
    "completada": "completada", "completadas": "completada", "hecha": "completada",
    "hechas": "completada", "terminada": "completada", "terminadas": "completada",
    "done": "completada",
    # Adri trabaja también con los nombres en inglés del kanban:
    "in progress": "progreso", "inprogress": "progreso", "doing": "progreso",
    "en curso": "progreso", "curso": "progreso", "review": "revision",
    "por hacer ya": "pendiente", "to do": "pendiente", "todo": "pendiente",
    # v23: «realizada/finalizada/lista» también son COMPLETADA (el bug del 25/07
    # fue justo este: «las ya realizadas» no casaba con 'completadas' y el
    # handler se iba al borrado TOTAL).
    "realizada": "completada", "realizadas": "completada",
    "finalizada": "completada", "finalizadas": "completada",
    "acabada": "completada", "acabadas": "completada",
    "lista": "completada", "listas": "completada",
    "completed": "completada", "complete": "completada",
    # v23: nomenclatura de las specs y estados extra
    "pending": "pendiente", "in_progress": "progreso", "in progress ": "progreso",
    "in_review": "revision", "cancelada": "cancelada", "canceladas": "cancelada",
    "cancelled": "cancelada", "canceled": "cancelada", "anulada": "cancelada",
    "archivada": "archivada", "archivadas": "archivada", "archived": "archivada",
}

# Ámbitos de selección para borrados masivos (v23 TAREA 2).
SCOPES = {
    "completadas": ["completada"],
    "pendientes": ["pendiente"],
    "progreso": ["progreso"],
    "revision": ["revision"],
    "canceladas": ["cancelada"],
    "archivadas": ["archivada"],
    "activas": ["pendiente", "progreso", "revision"],
    "todas": ALL_STATES,
}


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _audit(**kw) -> None:
    try:
        from . import audit as _a
        _a.log(**kw)
    except Exception:
        pass


def _load() -> list[dict]:
    if BOARD_FILE.exists():
        try:
            return json.loads(BOARD_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save(tasks: list[dict]) -> None:
    BOARD_FILE.parent.mkdir(parents=True, exist_ok=True)
    BOARD_FILE.write_text(json.dumps(tasks, ensure_ascii=False, indent=1),
                          encoding="utf-8")


# ═══════════════════════ PAPELERA (v23 TAREA 3) ═══════════════════════

_TRASH_MAX = 500          # tope de tarjetas guardadas (las más viejas se caen)


def _load_trash() -> list[dict]:
    if TRASH_FILE.exists():
        try:
            data = json.loads(TRASH_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            pass
    return []


def _save_trash(items: list[dict]) -> None:
    TRASH_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRASH_FILE.write_text(json.dumps(items[-_TRASH_MAX:], ensure_ascii=False, indent=1),
                          encoding="utf-8")


def status_of(task: dict) -> str:
    """Estado en la nomenclatura de las specs v23 (pending, completed…)."""
    return STATUS_OF.get(task.get("state", ""), "pending")


def select(scope: str = "completadas") -> list[dict]:
    """Tareas VIVAS que caen dentro de un ámbito. NUNCA devuelve nada de otro
    estado: es la función que evita repetir el incidente del 25/07."""
    states = SCOPES.get(_norm(scope))
    if states is None:
        st = STATE_ALIAS.get(_norm(scope))
        states = [st] if st else []
    return [t for t in _load() if t.get("state") in states]


def counts() -> dict:
    """Recuento por estado + total (para las previsualizaciones de confirmación)."""
    tasks = _load()
    out = {s: 0 for s in ALL_STATES}
    for t in tasks:
        out[t.get("state", "pendiente")] = out.get(t.get("state", "pendiente"), 0) + 1
    out["total"] = len(tasks)
    out["activas"] = out["pendiente"] + out["progreso"] + out["revision"]
    return out


def _to_trash(victims: list[dict], reason: str, by: str, batch: str) -> None:
    trash = _load_trash()
    for t in victims:
        item = dict(t)
        item["previousStatus"] = t.get("state", "pendiente")
        item["previousStatusSpec"] = status_of(t)
        item["deletedAt"] = _now()
        item["deletedBy"] = by or "nexus"
        item["deletionReason"] = (reason or "")[:300]
        item["batch"] = batch
        trash.append(item)
    _save_trash(trash)


def soft_delete(victims: list[dict], reason: str = "", by: str = "operador",
                action: str = "delete") -> dict:
    """Manda a la papelera las tareas indicadas (borrado LÓGICO). Devuelve
    {'count', 'batch', 'titles'}. Si la lista viene vacía, no toca nada."""
    victims = [t for t in (victims or []) if t.get("id")]
    if not victims:
        return {"count": 0, "batch": "", "titles": []}
    ids = {t["id"] for t in victims}
    batch = uuid.uuid4().hex[:8]
    _to_trash(victims, reason, by, batch)
    _save([t for t in _load() if t.get("id") not in ids])
    titles = [t.get("title", "") for t in victims]
    _audit(action=action, actor=by, destructive=True, confirmed=True,
           request=reason, targets=[{"id": t["id"], "title": t.get("title", ""),
                                     "state": t.get("state")} for t in victims],
           result=f"{len(victims)} tarea(s) a la papelera (lote {batch})",
           run_id=batch)
    return {"count": len(victims), "batch": batch, "titles": titles}


def trash(limit: int = 50, batch: str = "") -> list[dict]:
    """Contenido de la papelera, lo último borrado primero."""
    items = _load_trash()
    if batch:
        items = [t for t in items if t.get("batch") == batch]
    return list(reversed(items))[:limit]


def last_batch() -> str:
    """Identificador del último lote borrado ('' si la papelera está vacía)."""
    items = _load_trash()
    return items[-1].get("batch", "") if items else ""


def restore(query: str = "", batch: str = "", limit: int = 0) -> list[dict]:
    """Devuelve tareas de la papelera al tablero, con su estado ANTERIOR.

    * sin argumentos      → restaura el ÚLTIMO lote borrado entero
    * batch='xxxx'        → restaura ese lote
    * query='id o título' → restaura las que casen
    Devuelve la lista de tareas restauradas (vacía si no había nada)."""
    items = _load_trash()
    if not items:
        return []
    if query:
        q = _norm(query)
        chosen = [t for t in items if t.get("id") == query.strip()]
        if not chosen:
            chosen = [t for t in items if q and q in _norm(t.get("title", ""))]
    else:
        b = batch or last_batch()
        chosen = [t for t in items if t.get("batch") == b]
    if limit:
        chosen = chosen[-limit:]
    if not chosen:
        return []
    chosen_ids = {id(t) for t in chosen}
    tasks = _load()
    vivos = {t.get("id") for t in tasks}
    restored = []
    for t in chosen:
        card = {k: v for k, v in t.items()
                if k not in ("deletedAt", "deletedBy", "deletionReason",
                             "previousStatus", "previousStatusSpec", "batch")}
        card["state"] = t.get("previousStatus") or t.get("state") or "pendiente"
        card["restoredAt"] = _now()
        if card.get("id") in vivos:            # ya existe una viva con ese id
            card["id"] = uuid.uuid4().hex[:8]
        tasks.append(card)
        restored.append(card)
    _save(tasks)
    _save_trash([t for t in items if id(t) not in chosen_ids])
    _audit(action="restore", actor="operador", destructive=False, confirmed=True,
           request=query or f"lote {batch or 'último'}",
           targets=[{"id": c["id"], "title": c.get("title", ""),
                     "state": c.get("state")} for c in restored],
           result=f"{len(restored)} tarea(s) restaurada(s)")
    return restored


def purge_trash(batch: str = "") -> int:
    """BORRADO FÍSICO de la papelera (irreversible). Solo debe llamarse tras una
    confirmación EXTRA del operador. Devuelve cuántas tarjetas se destruyeron."""
    items = _load_trash()
    if batch:
        keep = [t for t in items if t.get("batch") != batch]
    else:
        keep = []
    n = len(items) - len(keep)
    _save_trash(keep)
    _audit(action="purge_trash", actor="operador", destructive=True, confirmed=True,
           request=f"lote {batch}" if batch else "papelera entera",
           result=f"{n} tarjeta(s) destruida(s) definitivamente")
    return n


# ═══════════════════════ CRUD del tablero ═══════════════════════

def add_task(title: str, due: str | None = None, priority: str = "media",
             tag: str = "", time_at: str = "", kind: str = "accion",
             description: str = "", reminder_at: str = "",
             source_conversation_id: str = "") -> dict:
    """kind: 'accion' (trabajo a realizar: crear una web) | 'evento' (cita de
    calendario: reunión, mentoría — normalmente con HORA en time_at 'HH:MM').
    No es lo mismo hacer que asistir: se guardan y se muestran distinto."""
    tasks = _load()
    task = {"id": uuid.uuid4().hex[:8], "title": title.strip(),
            "state": "pendiente", "due": due, "priority": priority, "tag": tag,
            "time": time_at or None, "kind": kind if kind in ("accion", "evento") else "accion",
            "created": dt.date.today().isoformat(), "nudged": None,
            # v23 (T14): ficha completa y estructurada, no dependiente de la
            # conversación. `state` es la columna; `status` la nomenclatura de
            # las specs (pending/in_progress/completed…).
            "description": (description or "").strip(),
            "dueDate": due, "reminderAt": reminder_at or None,
            "createdAt": _now(), "updatedAt": _now(), "completedAt": None,
            "deletedAt": None, "sourceConversationId": source_conversation_id or "",
            "snoozedUntil": None, "lastReminder": None}
    tasks.append(task)
    _save(tasks)
    return task


def find_task(query: str) -> dict | None:
    q = _norm(query)
    tasks = _load()
    for t in tasks:                       # id exacto
        if t["id"] == query.strip():
            return t
    for t in tasks:                       # título contiene
        if q in _norm(t["title"]):
            return t
    return None


def find_all(query: str) -> list[dict]:
    """TODAS las tareas vivas que casan (id exacto o título contiene). Se usa para
    PREVISUALIZAR un borrado antes de pedir confirmación (v23 TAREA 1)."""
    q = _norm(query)
    tasks = _load()
    exact = [t for t in tasks if t["id"] == query.strip()]
    if exact:
        return exact
    if not q:
        return []
    return [t for t in tasks if q in _norm(t["title"])]


def move_task(query: str, state_raw: str) -> dict | None:
    state = STATE_ALIAS.get(_norm(state_raw))
    if not state:
        return None
    tasks = _load()
    q = _norm(query)
    for t in tasks:
        if t["id"] == query.strip() or q in _norm(t["title"]):
            t["state"] = state
            t["updatedAt"] = _now()
            # v20: sello de completado — la revisión semanal cuenta por CUÁNDO
            # se terminó, no por cuándo se creó (revisión opus).
            if state == "completada":
                t["completed"] = dt.date.today().isoformat()
                t["completedAt"] = _now()
                t["snoozedUntil"] = None       # una completada ya no recuerda nada
            _save(tasks)
            return t
    return None


# NO HAY «set_meta()» AQUÍ, Y ES A PROPÓSITO (02/08/2026).
# Cambiaba `due` y `priority` de una tarea. Justo debajo, `edit_task()` cambia
# eso Y ADEMÁS el título y el estado, con la misma búsqueda por id-o-título. Un
# análisis de código muerto la delató: no la llamaba nadie, ni el tablero ni las
# rutas de /api/board. Si necesitas tocar metadatos, usa `edit_task()`.
def edit_task(query: str, title: str | None = None, due: str | None = None,
              priority: str | None = None, state: str | None = None) -> dict | None:
    """Edita una tarea (por id exacto o por título). Cambia solo lo que llega."""
    tasks = _load()
    q = _norm(query)
    for t in tasks:
        if t["id"] == query.strip() or (q and q in _norm(t["title"])):
            if title is not None and title.strip():
                t["title"] = title.strip()
            if due is not None:
                t["due"] = due or None          # "" → sin fecha
            if priority:
                t["priority"] = priority
            if state:
                st = STATE_ALIAS.get(_norm(state))
                if st:
                    t["state"] = st
                    if st == "completada":
                        t["completed"] = dt.date.today().isoformat()
                        t["completedAt"] = _now()
            t["updatedAt"] = _now()
            _save(tasks)
            return t
    return None


def delete_task(query: str, reason: str = "", by: str = "operador") -> dict | None:
    """Borra (A LA PAPELERA, v23) por id EXACTO; si no, por título — todas las que
    coincidan, para que los duplicados no se queden. Devuelve la 1ª borrada +
    cuántas + el lote, o None si no hubo ninguna."""
    matched = find_all(query)
    if not matched:
        return None
    res = soft_delete(matched, reason=reason or f"borrar «{query}»", by=by,
                      action="delete_task")
    return {**matched[0], "count": res["count"], "batch": res["batch"]}


def clear_completed(reason: str = "", by: str = "operador") -> int:
    """Manda a la papelera SOLO las tareas en estado 'completada'.
    Garantía v23: es imposible que toque una pendiente, en progreso o en revisión."""
    victims = [t for t in _load() if t.get("state") == "completada"]
    return soft_delete(victims, reason=reason or "borrar las completadas", by=by,
                       action="clear_completed")["count"]


def clear_scope(scope: str, reason: str = "", by: str = "operador") -> int:
    """Manda a la papelera las tareas de un ÁMBITO (ver SCOPES)."""
    victims = select(scope)
    return soft_delete(victims, reason=reason or f"borrar ámbito {scope}", by=by,
                       action=f"clear_{_norm(scope)}")["count"]


def clear_all(reason: str = "", by: str = "operador") -> int:
    """Vacía TODO el tablero (a la papelera). Devuelve cuántas movió.
    OJO: solo debe llamarse cuando el operador ha confirmado EXPLÍCITAMENTE
    que quiere borrar TODAS las tareas, no solo las completadas."""
    return soft_delete(_load(), reason=reason or "vaciar el tablero entero", by=by,
                       action="clear_all")["count"]


def board() -> dict:
    """Las 4 columnas del kanban (contrato estable del HUD y de /api/board)."""
    tasks = _load()
    return {s: [t for t in tasks if t["state"] == s] for s in STATES}


def overdue(days_soon: int = 2) -> tuple[list[dict], list[dict]]:
    """(vencidas, a punto de vencer) entre las no completadas."""
    today = dt.date.today()
    late, soon = [], []
    for t in _load():
        if t["state"] in ("completada", "cancelada", "archivada") or not t.get("due"):
            continue
        try:
            due = dt.date.fromisoformat(t["due"])
        except ValueError:
            continue
        if due < today:
            late.append(t)
        elif (due - today).days <= days_soon:
            soon.append(t)
    return late, soon


def snooze(query: str, hours: float = 2.0) -> dict | None:
    """«recuérdamelo más tarde» (v23 T13): calla los avisos de esa tarea un rato."""
    tasks = _load()
    q = _norm(query)
    hasta = (dt.datetime.now() + dt.timedelta(hours=max(0.25, hours))).isoformat(
        timespec="seconds")
    for t in tasks:
        if t["id"] == query.strip() or (q and q in _norm(t["title"])):
            t["snoozedUntil"] = hasta
            t["updatedAt"] = _now()
            _save(tasks)
            return t
    return None


def snooze_all(hours: float = 2.0) -> int:
    """Silencia TODOS los recordatorios un rato (modo no molestar rápido)."""
    tasks = _load()
    hasta = (dt.datetime.now() + dt.timedelta(hours=max(0.25, hours))).isoformat(
        timespec="seconds")
    n = 0
    for t in tasks:
        if t["state"] in ("completada", "cancelada", "archivada"):
            continue
        t["snoozedUntil"] = hasta
        n += 1
    if n:
        _save(tasks)
    return n


def _en_silencio(now: dt.datetime) -> bool:
    """Horario de descanso: por defecto de 23:00 a 8:00 no se dan toques."""
    try:
        from .config import settings
        ini = int(settings.get("quiet_from", 23))
        fin = int(settings.get("quiet_to", 8))
    except Exception:
        ini, fin = 23, 8
    h = now.hour
    return (h >= ini or h < fin) if ini > fin else (ini <= h < fin)


def nudges() -> list[str]:
    """Toques de atención (v23 T13): nunca de tareas completadas, nunca en
    horario de descanso, nunca si las pospusiste, y como mucho uno por tarea
    cada 4 h. Las tareas que vencen a la vez se agrupan en un solo aviso."""
    now = dt.datetime.now()
    msgs = []
    tasks = _load()
    changed = False
    if _en_silencio(now):
        return []
    for t in tasks:
        if t["state"] in ("completada", "cancelada", "archivada") or not t.get("due"):
            continue
        sn = t.get("snoozedUntil")
        if sn:
            try:
                if dt.datetime.fromisoformat(sn) > now:
                    continue                       # lo pospusiste: silencio
            except ValueError:
                pass
        try:
            due = dt.date.fromisoformat(t["due"])
        except ValueError:
            continue
        last = t.get("nudged")
        if last:
            try:
                if (now - dt.datetime.fromisoformat(last)).total_seconds() < 4 * 3600:
                    continue
            except ValueError:
                pass
        days = (due - now.date()).days
        if days < 0:
            msgs.append(f"⚠️ TOQUE DE ATENCIÓN: «{t['title']}» venció hace {-days} día(s) "
                        f"y sigue en {t['state']}. No la dejes morir.")
        elif days <= 1 and t["state"] == "pendiente":
            when = "HOY" if days == 0 else "mañana"
            msgs.append(f"⏰ «{t['title']}» vence {when} y ni la has empezado. "
                        "¿La movemos a en progreso?")
        else:
            continue
        t["nudged"] = now.isoformat()
        t["lastReminder"] = now.isoformat(timespec="seconds")
        changed = True
    if changed:
        _save(tasks)
    # AGRUPADO: varios avisos seguidos se juntan para no bombardear (T13).
    if len(msgs) > 3:
        resto = len(msgs) - 2
        msgs = msgs[:2] + [f"…y {resto} tarea(s) más pidiendo guerra. "
                           "Di «mis tareas» para verlas o «recuérdamelo más tarde»."]
    return msgs


def eisenhower() -> dict:
    """Matriz urgencia/importancia (urgente = vence en ≤2 días; importante = prioridad alta)."""
    today = dt.date.today()
    quad = {"hacer_ya": [], "planificar": [], "delegar": [], "descartar": []}
    for t in _load():
        if t["state"] in ("completada", "cancelada", "archivada"):
            continue
        urgent = False
        if t.get("due"):
            try:
                urgent = (dt.date.fromisoformat(t["due"]) - today).days <= 2
            except ValueError:
                pass
        important = t.get("priority", "media") == "alta"
        key = ("hacer_ya" if urgent and important else
               "planificar" if important else
               "delegar" if urgent else "descartar")
        quad[key].append(t)
    return quad
