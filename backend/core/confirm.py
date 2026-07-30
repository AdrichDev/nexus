"""
nexus — CONFIRMACIÓN OBLIGATORIA DE ACCIONES DESTRUCTIVAS (specs v23, TAREA 1).

Regla de arquitectura fijada con Adri: **toda acción destructiva requiere
confirmación previa**. Se consideran destructivas: borrar tareas, archivos o
carpetas, sobrescribir archivos existentes, vaciar listas, borrar recuerdos,
eliminar eventos/correos/documentos, y cualquier operación masiva o difícil de
revertir.

Cómo se usa desde una skill:

    from backend.core import confirm

    pregunta = confirm.request(
        channel=ctx.get("channel", "pc"),
        kind="borrar_tareas",
        summary="He encontrado 4 completadas y 3 pendientes. ¿Borro SOLO las 4 completadas?",
        request_text=text,
        targets=[{"id": t["id"], "title": t["title"], "state": t["state"]} for t in victims],
        action=lambda: board.clear_completed(...),   # se ejecuta SOLO si dice que sí
        cancel_reply="Vale, no toco nada.",
    )
    return {"reply": pregunta}

Y el brain, ANTES del router, llama a `await answer(text, channel)`: si hay una
confirmación pendiente y el operador dice «sí» / «no», la resuelve.

Guardas (aprendidas del incidente del 25/07/2026):
  * TTL de 5 minutos: una confirmación vieja NUNCA dispara nada.
  * Solo se acepta como respuesta una frase CORTA y explícita de sí/no.
  * Cualquier otra cosa DESCARTA la confirmación pendiente (no se queda armada
    esperando un «sí» suelto tres mensajes después) y sigue su curso normal.
  * Estado POR CANAL: lo que confirmas en el PC no dispara nada del móvil.
  * Nada se ejecuta sin dejar traza en la auditoría.
"""
from __future__ import annotations

import inspect
import re
import time
import uuid

TTL = 300                     # segundos de vida de una confirmación pendiente
_MAX_WORDS = 7                # una respuesta sí/no es corta por definición
_pending: dict[str, dict] = {}

# «sí», «vale», «adelante», «confirmo», «hazlo», «dale», «tira»…
_YES_RX = re.compile(
    r"^\s*(?:s[ií]+|sip|si+p|claro|vale|ok(?:ey|ay)?|okay|de\s+acuerdo|adelante|"
    r"confirm[oa]|confirmado|confirmada|hazlo|h[aá]zlo|dale|dele|tira|venga|"
    r"procede|correcto|exacto|eso\s+es|afirmativo|por\s+supuesto|perfecto)\b",
    re.IGNORECASE)
# «no», «cancela», «déjalo», «olvídalo», «para», «mejor no»…
_NO_RX = re.compile(
    r"^\s*(?:no+|nop|nel|qu[eé]\s+va|cancela|canc[eé]lalo|d[eé]jalo|d[eé]jala|"
    r"olv[ií]dalo|olvida|anula|an[uú]lalo|para|espera|quieto|negativo|"
    r"mejor\s+no|ni\s+de\s+co[ñn]a|ni\s+hablar|nada)\b",
    re.IGNORECASE)


def _audit(**kw) -> None:
    try:
        from . import audit as _a
        _a.log(**kw)
    except Exception:
        pass


def _key(channel: str) -> str:
    return channel or "pc"


def pending(channel: str = "pc") -> dict | None:
    """La confirmación pendiente viva de ese canal, o None."""
    p = _pending.get(_key(channel))
    if not p:
        return None
    if time.time() - p["ts"] > TTL:
        _pending.pop(_key(channel), None)
        return None
    return p


def clear(channel: str = "") -> None:
    if channel:
        _pending.pop(_key(channel), None)
    else:
        _pending.clear()


def request(channel: str, kind: str, summary: str, action,
            targets: list | None = None, request_text: str = "",
            cancel_reply: str = "", actor: str = "operador",
            destructive: bool = True) -> str:
    """Deja una acción ARMADA pero SIN EJECUTAR y devuelve la pregunta que hay que
    responder al operador. Sustituye a cualquier confirmación anterior del canal."""
    rid = uuid.uuid4().hex[:8]
    _pending[_key(channel)] = {
        "id": rid, "kind": kind, "summary": summary, "action": action,
        "targets": targets or [], "request_text": request_text or "",
        "cancel_reply": cancel_reply or "Hecho: no he borrado nada.",
        "actor": actor, "destructive": destructive, "ts": time.time(),
    }
    _audit(action=f"confirm_request:{kind}", actor=actor, destructive=destructive,
           confirmed=None, request=request_text, interpreted=summary,
           targets=targets or [], result="a la espera de confirmación",
           run_id=rid, channel=_key(channel))
    return summary


def is_answer(text: str, channel: str = "pc") -> bool:
    """¿Este texto es una respuesta sí/no a una confirmación viva de este canal?"""
    if not pending(channel):
        return False
    t = (text or "").strip()
    if not t or len(t) > 60 or len(t.split()) > _MAX_WORDS:
        return False
    return bool(_YES_RX.match(t) or _NO_RX.match(t))


async def answer(text: str, channel: str = "pc") -> str | None:
    """Resuelve la confirmación pendiente del canal.

    Devuelve el texto de la respuesta si el mensaje ERA un sí/no; None si no
    había nada pendiente o el mensaje no era una respuesta (en ese caso, si
    había algo armado, se DESARMA: jamás se queda esperando)."""
    p = pending(channel)
    if not p:
        return None
    t = (text or "").strip()
    short = bool(t) and len(t) <= 60 and len(t.split()) <= _MAX_WORDS

    if short and _NO_RX.match(t):
        clear(channel)
        _audit(action=f"confirm_denied:{p['kind']}", actor=p["actor"],
               destructive=p["destructive"], confirmed=False,
               request=p["request_text"], interpreted=p["summary"],
               targets=p["targets"], result="cancelado por el operador",
               run_id=p["id"], channel=_key(channel))
        return p["cancel_reply"]

    if short and _YES_RX.match(t):
        clear(channel)
        try:
            res = p["action"]()
            if inspect.isawaitable(res):
                res = await res
            reply = res if isinstance(res, str) else "Hecho."
            _audit(action=f"confirm_executed:{p['kind']}", actor=p["actor"],
                   destructive=p["destructive"], confirmed=True,
                   request=p["request_text"], interpreted=p["summary"],
                   targets=p["targets"], result=reply[:300],
                   run_id=p["id"], channel=_key(channel))
            return reply
        except Exception as exc:                       # noqa: BLE001
            _audit(action=f"confirm_failed:{p['kind']}", actor=p["actor"],
                   destructive=p["destructive"], confirmed=True,
                   request=p["request_text"], interpreted=p["summary"],
                   targets=p["targets"], error=f"{type(exc).__name__}: {exc}",
                   result="FALLÓ", run_id=p["id"], channel=_key(channel))
            return f"Iba a hacerlo y ha fallado: {exc}. No doy por hecho nada."

    # Ni sí ni no → se desarma para que no dispare más tarde por sorpresa.
    clear(channel)
    _audit(action=f"confirm_dropped:{p['kind']}", actor=p["actor"],
           destructive=p["destructive"], confirmed=False,
           request=p["request_text"], interpreted=p["summary"],
           targets=p["targets"], result="descartada: el operador cambió de tema",
           run_id=p["id"], channel=_key(channel))
    return None
