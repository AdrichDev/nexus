"""Minion Comunicación — puente con Telegram y captura de mensajes a tareas.

INCIDENTE DEL 02/08/2026, y por eso este fichero se reescribió entero.

Esta skill servía una «bandeja unificada» con tres mensajes INVENTADOS escritos
a fuego, con nombres reales del entorno del usuario (un amigo, una socia, un
proveedor chino) y textos plausibles. No llevaban ninguna marca: se pintaban
como «📥 Bandeja unificada — 3 mensajes». Igual el calendario, con tres hitos
falsos. Y las notificaciones decían «🔔 3 sin leer» con la hora real pegada
detrás para que pareciera vivo.

Lo más grave no era enseñarlos. Era que «captura de tareas» los recorría y los
ESCRIBÍA EN LA MEMORIA REAL: `pg.remember(...)` guardaba «Tarea de Rubén:
acuérdate de lo de la camiseta de China» como un hecho, y `append_daily` lo
metía en el registro del día. Contenido inventado contaminando la base de datos
del usuario, con aspecto de recuerdo suyo.

La regla del proyecto es que no se inventan cifras ni descripciones. Aquí se
estaba incumpliendo de la peor manera: con datos verosímiles y personales.

Ahora esta skill LEE EL ESTADO REAL (¿hay token de Telegram?, ¿hay propietario
registrado?) y dice lo que sabe. Cuando no hay canal conectado no hay bandeja
que enseñar, y eso se cuenta tal cual en vez de rellenarlo.
"""
from __future__ import annotations

SKILL = {
    "name": "Comunicación",
    "description": "Puente con Telegram: estado del bot, envío y captura de mensajes a tareas",
    "patterns": {
        # Enviar — específico (grupos to/body), antes que el listado de bandeja.
        "send": r"(?:env[ií]a(?:le)?|m[aá]nda(?:le)?|escr[ií]be(?:le)?)\s+(?:un\s+)?mensaje\s+a\s+"
                r"(?P<to>[\w]+)\s+(?:diciendo|que\s+diga|con|que)\s+(?P<body>.+)",
        # Captura de mensajes → tareas. Ancla: mensaje/conversación/bandeja.
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
                 # 02/08/2026, INCIDENTE DE ENRUTADO: aquí ponía `bandeja` A SECAS, y
                 # como skills_loader recorre las carpetas por orden ALFABÉTICO («comms»
                 # va antes que «google_workspace») esta skill se quedaba CUALQUIER frase
                 # con la palabra «bandeja»: «qué tengo en la bandeja», «algo urgente en
                 # la bandeja», «hazme un resumen de la bandeja»… todas ejemplos LITERALES
                 # del SKILL.md de Google. En español «bandeja» y «bandeja de entrada»
                 # son el correo; lo de aquí es la bandeja UNIFICADA de mensajería.
                 r"|(?:mi\s+)?bandeja\s+(?:unificada|de\s+mensajes)\b"
                 r"|\bbandeja\s+de\s+(?:whatsapp|telegram)\b",
    },
}

# NO HAY «_INBOX» NI «_CALENDAR» AQUÍ, Y ES A PROPÓSITO. Ver el incidente del
# encabezado: eran datos inventados que se servían como reales y que además
# acababan escritos en la memoria del usuario. Si algún día hay bandeja de
# verdad, saldrá del puente de Telegram, no de una lista escrita a mano.


def _estado_telegram() -> dict:
    """Qué se sabe DE VERDAD del puente, leído, no supuesto.

    La regla del proyecto es que las preguntas sobre la propia configuración se
    LEEN. Antes esta skill respondía «sin conectar todavía» a fuego, y resultaba
    que el usuario sí tenía el token puesto: la respuesta era falsa por pereza."""
    from backend.core import telegram_bridge as tg
    from backend.core.config import settings
    token = bool(settings.secret("telegram_bot_token"))
    try:
        propietario = tg.OWNER_FILE.is_file() and tg.OWNER_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        propietario = ""
    return {"token": token, "propietario": bool(propietario)}


def _sin_canal(que_pedias: str) -> str:
    """El mensaje honesto cuando no hay de dónde sacar mensajes."""
    e = _estado_telegram()
    if not e["token"]:
        falta = ("Falta el token del bot. Habla con @BotFather en Telegram, haz /newbot, "
                 "copia el token y pégalo en ⚙ → APIS (o dime «configura telegram <token>»).")
    elif not e["propietario"]:
        falta = ("El token está puesto pero nadie ha reclamado el bot todavía: escríbele por "
                 "Telegram y ese primer chat queda como propietario.")
    else:
        falta = ("El puente está montado, pero nexus no guarda un histórico de lo que llega: "
                 "solo responde en el momento. Una bandeja con historial es trabajo pendiente.")
    return (f"De {que_pedias} no tengo nada que enseñarte, y no me lo voy a inventar.\n{falta}\n\n"
            "Para tu correo de verdad, que ese sí está conectado, di «lee mis correos».")


async def handle(intent: str, text: str, match, ctx) -> dict:
    if intent == "inbox":
        return {"reply": "📥 " + _sin_canal("tu bandeja de mensajería")}

    if intent == "notifications":
        # Antes: «🔔 3 sin leer: 2 mensajes nuevos y 1 recordatorio», a fuego, con
        # la hora real detrás para que colara. Tres números inventados.
        return {"reply": "🔔 " + _sin_canal("tus notificaciones")}

    if intent == "capture":
        # Antes recorría los mensajes INVENTADOS y los escribía en la memoria
        # real. Sin fuente no hay nada que capturar, y desde luego no se escribe
        # nada: contaminar la base con contenido falso es peor que no responder.
        return {"reply": "🧲 " + _sin_canal("mensajes que convertir en tareas") +
                         "\n\nSi la tarea la tienes tú en la cabeza, dímela directamente: "
                         "«apunta pagar al proveedor el viernes» y va al tablero con aviso."}

    if intent == "send":
        to, body = match.group("to").title(), match.group("body").strip().rstrip(".")
        e = _estado_telegram()
        ctx["graph"].append_daily(f"Mensaje a {to}: {body}", section="Comunicación")
        if e["token"] and e["propietario"]:
            aviso = ("El puente de Telegram está activo, pero solo sabe escribirte a TI, "
                     "no a terceros: para eso hace falta un flujo de WhatsApp o Telegram en n8n.")
        else:
            aviso = ("Para que salga de verdad necesito el canal conectado: di «estado del bot» "
                     "y te digo qué falta.")
        return {"reply": f"✉ Mensaje para {to} anotado en tu registro del día: «{body}».\n{aviso}"}

    if intent == "bot":
        e = _estado_telegram()
        if e["token"] and e["propietario"]:
            return {"reply": "🤖 Bot de Telegram: **conectado**, con propietario registrado. "
                             "Puedes darle por Telegram cualquier orden del HUD."}
        if e["token"]:
            return {"reply": "🤖 Bot de Telegram: token puesto, pero **sin propietario**.\n"
                             "Escríbele por Telegram: el primer chat que le hable queda como "
                             "dueño y a partir de ahí te responde solo a ti."}
        return {"reply": "🤖 Bot de Telegram: **sin token**.\n"
                         "  1. Habla con @BotFather en Telegram → /newbot → copia el token\n"
                         "  2. Pégalo en ⚙ → APIS (o dime «configura telegram <token>»)\n"
                         "  3. Reinicia nexus y escríbele: el primer chat queda como propietario"}

    return {"reply": "No te he pillado esa de comunicación. Prueba «ver mensajes», "
                     "«captura de tareas», «envía un mensaje a Rubén diciendo …» o «estado del bot»."}
