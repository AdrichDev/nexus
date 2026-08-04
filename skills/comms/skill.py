"""Puente de mensajería: estado del bot de Telegram, envío y captura de tareas.

No inventa contenido: si no hay canal conectado, lo dice y explica qué falta.
"""
from __future__ import annotations

SKILL = {
    "name": "Comunicación",
    "description": "Puente con Telegram: estado del bot, envío de mensajes y captura de tareas",
    "patterns": {
        # `send` va primero: es el único con grupos (to/body) y el más específico.
        "send": r"(?:env[ií]a(?:le)?|m[aá]nda(?:le)?|escr[ií]be(?:le)?)\s+(?:un\s+)?mensaje\s+a\s+"
                r"(?P<to>[\w]+)\s+(?:diciendo|que\s+diga|con|que)\s+(?P<body>.+)",
        "capture": r"captura(?:me)?\s+(?:de\s+)?tareas"
                   r"|(?:convierte|pasa|saca)\s+(?:mis\s+)?(?:mensajes|conversaciones)\s+(?:en|a)\s+tareas"
                   r"|(?:crea|saca)\s+tareas\s+de\s+(?:mis\s+)?(?:mensajes|la\s+bandeja|whatsapp|telegram)",
        "bot": r"estado\s+del\s+bot|(?:c[oó]mo\s+(?:va|est[aá])\s+el\s+bot)|bot\s+de\s+telegram|"
               r"(?:est[aá]\s+)?conectado\s+telegram",
        "notifications": r"(?:ver|mu[eé]stra(?:me)?|ens[eé][ñn]a(?:me)?|dime|cu[aá]ntas|hay)\s+"
                         r"(?:mis\s+|las\s+)?notificaciones|tengo\s+notificaciones",
        # «bandeja» a secas NO se reclama aquí: en español es el correo, y lo
        # atiende `google_workspace`. Esta skill solo cubre la bandeja de
        # mensajería. Importa porque `comms` gana por orden alfabético.
        "inbox": r"(?:ver|lee|l[eé]e(?:me)?|mu[eé]stra(?:me)?|ens[eé][ñn]a(?:me)?|abre|dame|revisa)\s+"
                 r"(?:los\s+|mis\s+)?mensajes(?:\s+(?:unificados|de\s+whatsapp|de\s+telegram|nuevos))?"
                 r"|(?:qu[eé]|tengo)\s+mensajes(?:\s+nuevos)?"
                 r"|(?:mi\s+)?bandeja\s+(?:unificada|de\s+mensajes)\b"
                 r"|\bbandeja\s+de\s+(?:whatsapp|telegram)\b",
    },
}


def _estado_telegram() -> dict:
    """Lee si hay token del bot y si alguien lo ha reclamado como propietario."""
    from backend.core import telegram_bridge as tg
    from backend.core.comun.config import settings
    try:
        propietario = bool(tg.OWNER_FILE.is_file()
                           and tg.OWNER_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        propietario = False
    return {"token": bool(settings.secret("telegram_bot_token")), "propietario": propietario}


def _sin_canal(que: str) -> str:
    """Explica qué falta para tener ese canal, según el estado real."""
    e = _estado_telegram()
    if not e["token"]:
        falta = ("Falta el token del bot: habla con @BotFather en Telegram, haz /newbot y pega "
                 "el token en ⚙ → APIS.")
    elif not e["propietario"]:
        falta = ("El token está puesto, pero nadie ha reclamado el bot: escríbele por Telegram "
                 "y ese primer chat queda como propietario.")
    else:
        falta = ("El puente responde en el momento, pero no guarda histórico: una bandeja con "
                 "historial está pendiente.")
    return (f"De {que} no tengo nada que enseñarte.\n{falta}\n\n"
            "Para el correo, que sí está conectado, di «lee mis correos».")


async def handle(intent: str, text: str, match, ctx) -> dict:
    if intent == "inbox":
        return {"reply": "📥 " + _sin_canal("tu bandeja de mensajería")}

    if intent == "notifications":
        return {"reply": "🔔 " + _sin_canal("tus notificaciones")}

    if intent == "capture":
        return {"reply": "🧲 " + _sin_canal("mensajes que convertir en tareas") +
                         "\n\nSi la tarea ya la tienes clara, dímela directamente: "
                         "«apunta llamar al taller el viernes» y va al tablero con aviso."}

    if intent == "send":
        destino = match.group("to").title()
        cuerpo = match.group("body").strip().rstrip(".")
        e = _estado_telegram()
        ctx["graph"].append_daily(f"Mensaje a {destino}: {cuerpo}", section="Comunicación")
        if e["token"] and e["propietario"]:
            aviso = ("El puente de Telegram solo sabe escribirte a ti, no a terceros: para eso "
                     "hace falta un flujo en n8n.")
        else:
            aviso = "Para que salga de verdad, di «estado del bot» y te digo qué falta."
        return {"reply": f"✉ Mensaje para {destino} anotado en tu registro del día: «{cuerpo}».\n{aviso}"}

    if intent == "bot":
        e = _estado_telegram()
        if e["token"] and e["propietario"]:
            return {"reply": "🤖 Bot de Telegram: conectado y con propietario. "
                             "Puedes darle por Telegram las mismas órdenes que por el HUD."}
        if e["token"]:
            return {"reply": "🤖 Bot de Telegram: token puesto, sin propietario.\n"
                             "Escríbele por Telegram: el primer chat que le hable queda como dueño."}
        return {"reply": "🤖 Bot de Telegram: sin token.\n"
                         "  1. @BotFather en Telegram → /newbot → copia el token\n"
                         "  2. Pégalo en ⚙ → APIS\n"
                         "  3. Reinicia y escríbele: el primer chat queda como propietario"}

    return {"reply": "Prueba «ver mensajes», «captura de tareas», "
                     "«envía un mensaje a Ana diciendo que llego tarde» o «estado del bot»."}
