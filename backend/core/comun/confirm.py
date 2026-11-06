"""
nexus — CONFIRMACIÓN OBLIGATORIA DE ACCIONES DESTRUCTIVAS (specs v23, TAREA 1).

Regla de arquitectura fijada con Adri: **toda acción destructiva requiere
confirmación previa**. Se consideran destructivas: borrar tareas, archivos o
carpetas, sobrescribir archivos existentes, vaciar listas, borrar recuerdos,
eliminar eventos/correos/documentos, y cualquier operación masiva o difícil de
revertir.

Cómo se usa desde una skill:

    from backend.core.comun import confirm

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
  * Los ENVÍOS (correo, WhatsApp) también se arman aquí, aunque no sean
    destructivos: un envío que no querías es un daño igual. Y un envío repetido
    tampoco sale dos veces — para eso está la memoria corta de `ya_enviado()` /
    `marcar_enviado()`, que vive en RAM y por tanto se olvida al reiniciar.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import re
import time
import uuid
from pathlib import Path

TTL = 300                     # segundos de vida de una confirmación pendiente
_MAX_WORDS = 7                # una respuesta sí/no es corta por definición
_pending: dict[str, dict] = {}

# ── MEMORIA CORTA DE ENVÍOS (SEC-05 / P1-4) ──────────────────────────────────
# `clave de envío → cuándo se aceptó`. Sirve para que la misma orden repetida
# (el doble clic, el reintento, la frase mandada dos veces) no mande dos correos
# ni dos WhatsApp.
#
# Vive en RAM, igual que `_pending`: al REINICIAR nexus se olvida. Es aceptable y
# se dice aquí para que nadie lo confunda con una garantía entre arranques: el
# daño que evita ocurre dentro de una misma sesión. Nada de esto se escribe en
# disco porque no es un registro, es una ventana.
_enviados: dict[str, float] = {}

# Reserva si config/umbrales.json falta o está roto. Quien pregunta por la
# ventana lo hace en `umbrales_envios()`: NUNCA se cablea el número en la llamada.
_RESERVA_ENVIOS = {
    "ventana_idempotencia_seg": 300.0,
    "max_caracteres_cuerpo": 600,
}

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


# ───────────────────────── umbrales y huella de un envío ─────────────────────
def umbrales_envios() -> dict:
    """Los umbrales de los envíos: sección «envios» de config/umbrales.json.

    Mismo estilo que el resto del proyecto: la reserva vive en el código y el
    archivo la pisa. Un JSON roto o ausente deja la reserva, nunca revienta.
    """
    vals = dict(_RESERVA_ENVIOS)
    try:
        from .config import CONFIG_DIR
        f = Path(CONFIG_DIR) / "umbrales.json"
        if f.is_file():
            leido = (json.loads(f.read_text(encoding="utf-8")) or {}).get("envios") or {}
            for clave, defecto in _RESERVA_ENVIOS.items():
                v = leido.get(clave)
                if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                    vals[clave] = float(v) if isinstance(defecto, float) else int(v)
    except Exception:
        pass                                  # archivo roto → reserva, nunca reventar
    return vals


def _normaliza(trozo: str) -> str:
    """Minúsculas y espacios colapsados: «Hola  mundo» y «hola mundo» son lo mismo."""
    return " ".join((trozo or "").split()).casefold()


def clave_envio(kind: str, destinatario: str, asunto: str = "", cuerpo: str = "") -> str:
    """Huella del envío: sha256 de tipo + destinatario + asunto + cuerpo.

    Normalizada, para que lo que cambia sin cambiar el envío (mayúsculas, un
    espacio de más) no abra un hueco por el que se cuele el duplicado. Lo que SÍ
    entra es el CONTENIDO: el mismo destinatario con otro cuerpo es otro envío.
    """
    material = "\x1f".join(_normaliza(x) for x in (kind, destinatario, asunto, cuerpo))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def ya_enviado(clave: str, ventana: float | None = None, *, channel: str = "pc",
               kind: str = "", targets: list | None = None) -> bool:
    """¿Se aceptó ya un envío con esta huella dentro de la ventana?

    Si sí, deja la traza del duplicado rechazado y contesta True: quien llama NO
    debe enviar otra vez. La ventana se pasa desde fuera (`umbrales_envios()`)."""
    v = (float(_RESERVA_ENVIOS["ventana_idempotencia_seg"])
         if ventana is None else float(ventana))
    ahora = time.time()
    for k, ts in list(_enviados.items()):     # poda: lo viejo no crece sin fin
        if ahora - ts > v:
            _enviados.pop(k, None)
    ts = _enviados.get(clave)
    if ts is not None and ahora - ts <= v:
        _audit(action=f"envio_duplicado:{kind or 'envio'}", actor="operador",
               destructive=False, confirmed=None,
               interpreted=f"envío repetido {int(ahora - ts)} s después del primero",
               targets=targets or [],
               result="no se envía: ya había salido dentro de la ventana",
               channel=_key(channel))
        return True
    return False


def marcar_enviado(clave: str, *, channel: str = "pc", kind: str = "",
                   targets: list | None = None, result: str = "") -> None:
    """Apunta que este envío se aceptó AHORA. Solo se llama si de verdad salió:
    un envío que falló NO se marca, para que reintentarlo siga siendo posible."""
    _enviados[clave] = time.time()
    _audit(action=f"envio_aceptado:{kind or 'envio'}", actor="operador",
           destructive=False, confirmed=True, targets=targets or [],
           result=(result or "enviado")[:300], channel=_key(channel))


def olvidar_envios() -> None:
    """Olvida la memoria corta de envíos. Un reinicio ya lo hace solo; esto es
    para las pruebas y para reintentar a mano sin esperar la ventana."""
    _enviados.clear()


def recortar(texto: str, maximo: int | None = None) -> str:
    """El texto TAL CUAL, recortado con «…» si no cabe en la vista previa.

    Recortar no es resumir: se enseña lo que se manda, y si se corta se dice que
    se ha cortado. Una paráfrasis en la confirmación sería enseñar otra cosa.
    """
    limite = umbrales_envios()["max_caracteres_cuerpo"] if maximo is None else int(maximo)
    t = texto or ""
    if len(t) <= limite:
        return t
    return t[:limite].rstrip() + "…"


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
