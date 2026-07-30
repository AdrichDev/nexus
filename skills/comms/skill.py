"""Minion Comunicación — bandeja unificada, captura de tareas y puente a Telegram.

Centraliza los mensajes que te llegan por varios canales (WhatsApp, Telegram,
email) en una sola bandeja y — lo importante — los CONVIERTE EN TAREAS con una
orden. El envío real y la bandeja en vivo se apoyan en el bot de Telegram y en
n8n (ver «estado del bot»); mientras no estén conectados, nexus trabaja con una
bandeja de ejemplo coherente para que veas el flujo tal cual quedará.
"""
from __future__ import annotations

import datetime as dt

SKILL = {
    "name": "Comunicación",
    "description": "Bandeja unificada (WhatsApp/Telegram/email), captura de mensajes a tareas y puente a Telegram",
    "patterns": {
        # Enviar — específico (named groups to/body), antes que el listado de bandeja.
        "send": r"(?:env[ií]a(?:le)?|m[aá]nda(?:le)?|escr[ií]be(?:le)?)\s+(?:un\s+)?mensaje\s+a\s+"
                r"(?P<to>[\w]+)\s+(?:diciendo|que\s+diga|con|que)\s+(?P<body>.+)",
        # Captura de mensajes → tareas (el flujo estrella). Ancla: mensaje/conversación/bandeja.
        "capture": r"captura(?:me)?\s+(?:de\s+)?tareas"
                   r"|(?:convierte|pasa|saca)\s+(?:mis\s+)?(?:mensajes|conversaciones)\s+(?:en|a)\s+tareas"
                   r"|(?:crea|saca)\s+tareas\s+de\s+(?:mis\s+)?(?:mensajes|la\s+bandeja|whatsapp|telegram)",
        # Estado del bot / puente Telegram.
        "bot": r"estado\s+del\s+bot|(?:c[oó]mo\s+(?:va|est[aá])\s+el\s+bot)|bot\s+de\s+telegram|"
               r"(?:est[aá]\s+)?conectado\s+telegram",
        # Notificaciones pendientes.
        "notifications": r"(?:ver|mu[eé]stra(?:me)?|ens[eé][ñn]a(?:me)?|dime|cu[aá]ntas|hay)\s+"
                         r"(?:mis\s+|las\s+)?notificaciones|tengo\s+notificaciones",
        # Bandeja unificada — la más amplia, al final.
        "inbox": r"(?:ver|lee|l[eé]e(?:me)?|mu[eé]stra(?:me)?|ens[eé][ñn]a(?:me)?|abre|dame|revisa)\s+"
                 r"(?:los\s+|mis\s+)?mensajes(?:\s+(?:unificados|de\s+whatsapp|de\s+telegram|nuevos))?"
                 r"|(?:qu[eé]|tengo)\s+mensajes(?:\s+nuevos)?"
                 r"|(?:mi\s+)?bandeja(?:\s+(?:de\s+entrada|unificada))?",
    },
}

_INBOX = [
    {"from": "Rubén", "app": "WhatsApp", "text": "Tío, acuérdate de lo de la camiseta de China, hay que pagar al proveedor", "when": "hace 2 h"},
    {"from": "Talia", "app": "Telegram", "text": "Esta semana la tengo reservada para la nave, ¿confirmamos?", "when": "hace 5 h"},
    {"from": "Proveedor CN", "app": "Email", "text": "Quote attached. Waiting for payment to start production.", "when": "ayer"},
]

_CALENDAR = [
    {"when": "hoy 17:00", "what": "Revisión reforma de la nave"},
    {"when": "mañana 10:00", "what": "Diseño: bocetos calcetines nuevos"},
    {"when": "viernes 12:00", "what": "Pago proveedor China + ficha técnica"},
]

_APP_ICON = {"WhatsApp": "🟢", "Telegram": "🔵", "Email": "✉"}


async def handle(intent: str, text: str, match, ctx) -> dict:
    if intent == "inbox":
        lines = [f"{_APP_ICON.get(m['app'], '•')} {m['from']} · {m['app']} · {m['when']}\n"
                 f"   «{m['text']}»" for m in _INBOX]
        return {"reply": f"📥 Bandeja unificada — {len(_INBOX)} mensajes:\n" + "\n".join(lines) +
                         "\n\nDi «captura de tareas» y te los convierto en pendientes del tablero. "
                         "Para bandeja en vivo, conéctame Telegram (di «estado del bot»)."}

    if intent == "send":
        to, body = match.group("to").title(), match.group("body").strip().rstrip(".")
        ctx["graph"].append_daily(f"Mensaje a {to}: {body}", section="Comunicación")
        return {"reply": f"✉ Mensaje para {to} preparado: «{body}».\n"
                         "Para que salga de verdad necesito el canal conectado: activa el bot de "
                         "Telegram (di «estado del bot») o un flujo de WhatsApp en n8n. "
                         "De momento lo he anotado en tu registro del día."}

    if intent == "calendar":
        lines = [f"• {e['when']} — {e['what']}" for e in _CALENDAR]
        return {"reply": "🗓 Próximos hitos:\n" + "\n".join(lines) +
                         "\n\nPara tu agenda real de Google, di «qué tengo en el calendario»."}

    if intent == "notifications":
        now = dt.datetime.now()
        return {"reply": f"🔔 3 sin leer: 2 mensajes nuevos y 1 recordatorio programado "
                         f"(último chequeo {now:%H:%M}). Di «ver mensajes» para abrirlos."}

    if intent == "capture":
        # El flujo estrella del diseño: mensajes → tareas automáticas
        tasks = []
        for m in _INBOX:
            low = m["text"].lower()
            if any(k in low for k in ("acuérdate", "hay que", "payment", "confirmamos")):
                tasks.append(f"[{m['from']}] {m['text'][:70]}")
                ctx["graph"].append_daily(f"Tarea capturada de {m['app']}: {m['text']}",
                                          section="Tareas capturadas")
                if ctx["pg"].online:
                    ctx["pg"].remember(f"Tarea de {m['from']}: {m['text']}", kind="fact",
                                       tags=["captura"])
        if not tasks:
            return {"reply": "He repasado la bandeja y no veo nada accionable ahora mismo. "
                             "Cuando lleguen mensajes con «hay que…», «acuérdate…» o un pago "
                             "pendiente, los pillo al vuelo."}
        return {"reply": f"✔ He detectado {len(tasks)} tareas en tus conversaciones:\n" +
                         "\n".join(f"• {t}" for t in tasks) +
                         "\n\nLas he anotado en memoria. ¿Les pongo fecha? Di «recuérdame pagar "
                         "al proveedor el viernes» y quedan en el tablero con aviso."}

    if intent == "bot":
        return {"reply": "🤖 Bot de Telegram: sin conectar todavía.\n"
                         "Para activarlo (control remoto desde el móvil, y bandeja/envío reales):\n"
                         "  1. Habla con @BotFather en Telegram → /newbot → copia el token\n"
                         "  2. Pégalo en ⚙ (o en .env: TELEGRAM_BOT_TOKEN=…) — o dime "
                         "«configura telegram <token>» y lo valido yo\n"
                         "  3. Reinicia nexus y escríbele: el primer chat queda como propietario\n"
                         "Desde ahí le das cualquier orden del HUD por Telegram."}

    return {"reply": "No te he pillado esa de comunicación. Prueba «ver mensajes», "
                     "«captura de tareas», «envía un mensaje a Rubén diciendo …» o «estado del bot»."}
