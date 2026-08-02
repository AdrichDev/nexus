"""
Minion DISCORD — abrir Discord y enviar mensajes a un canal por webhook.

Qué SÍ se puede automatizar (de forma soportada):
  * «abre discord»                         → abre la app
  * «manda a discord: <mensaje>»           → publica en tu canal vía webhook
  * «avisa por discord que <algo>»         → idem

Qué NO permite Discord por automatización (cuentas de usuario): iniciar LLAMADAS
o abrir un DM concreto a una persona sin la app. En esos casos nexus abre Discord
y te lo deja a un clic, y te ofrece el webhook para avisos a un canal.
"""
from __future__ import annotations

import asyncio
import os
import sys

import httpx

SKILL = {
    "name": "Discord",
    "description": "Publica avisos en tu canal de Discord por webhook y abre la app al instante",
    "patterns": {
        # específicos primero: llamada y DM (llevan su palabra clave propia)
        "call": r"\b(?:ll[aá]ma(?:le|lo|la)?(?:r)?|haz\s+una\s+(?:video)?llamada|inicia\s+(?:una\s+)?(?:video)?llamada|videollamada|videollama)\b[^.]{0,25}\bdiscord\b"
                r"|\ben\s+discord\b[^.]{0,15}\b(?:llama|videollama)\b",
        "dm": r"\b(?:inicia|abre|empieza|m[aá]ndale)\b[^.]{0,25}\b(?:conversaci[oó]n|chat|mensaje\s+privado|privado|dm)\b[^.]{0,25}\bdiscord\b"
              r"|\ben\s+discord\b[^.]{0,15}\b(?:habla|chatea|conversa)\b",
        # publicar en canal (el más amplio de los tres con mensaje)
        "notify": r"\b(?:m[aá]nda(?:le|me)?|env[ií]a(?:le)?|escr[ií]be(?:le)?|av[ií]sa(?:me)?|notifica(?:me)?|comunica|anuncia|publica|postea|comparte|suelta|pon|di)\b"
                  r"[^.]{0,30}\b(?:en|por|a|al)\s+(?:el\s+)?(?:canal\s+(?:de\s+)?)?discord\b\s*[:,]?\s*(?:que\s+|de\s+que\s+)?(?P<msg>.+)"
                  r"|\ben\s+(?:el\s+canal\s+de\s+)?discord\b[^.]{0,15}\b(?:escribe|pon|di|publica|manda|avisa|anuncia)\b\s*(?:que\s+)?(?P<msg2>.+)",
        "open": r"\b(?:[aá]bre(?:me)?|arranca(?:me)?|l[aá]nza(?:me)?|inicia|ejecuta)\b\s+(?:el\s+)?discord\b",
    },
}


async def _open_discord() -> str:
    if sys.platform == "win32":
        try:
            os.startfile("discord://")                 # type: ignore[attr-defined]
            return "Abriendo Discord."
        except Exception:
            pass
    try:
        from backend.core.app_index import build_index, find_app, get_index, launch
        if not get_index() and sys.platform == "win32":
            await asyncio.to_thread(build_index)
        hit = find_app("discord")
        if hit:
            launch(hit[1])
            return "Abriendo Discord."
    except Exception:
        pass
    if sys.platform == "win32":
        os.system('start "" "%LOCALAPPDATA%\\Discord\\Update.exe" --processStart Discord.exe')
        return "Abriendo Discord."
    return ("La app de Discord solo la puedo abrir en Windows. Lo que sí puedo desde aquí "
            "es publicar en tu canal: «manda a discord: <mensaje>».")


async def _notify(ctx, msg: str) -> str:
    msg = (msg or "").strip().strip('"\'“”')
    if not msg:
        return "¿Qué mensaje mando a Discord? Dímelo así: «manda a discord: la build está lista»."
    url = ctx["settings"].secret("discord_webhook_url")
    if not url:
        return ("Para publicar en Discord necesito un webhook (es la vía soportada y segura): "
                "en tu servidor → Configuración → Integraciones → Webhooks → Nuevo webhook, "
                "elige el canal, copia la URL y guárdala en ⚙ (campo «Discord webhook»). "
                "Luego repite la orden y lo publico.")
    try:
        async with httpx.AsyncClient(timeout=10) as cli:
            r = await cli.post(url, json={"content": msg[:1900]})
        if r.status_code < 300:
            return (f"Publicado en Discord ✔: «{msg[:120]}». Si quieres otro canal, crea otro "
                    "webhook y cámbialo en ⚙.")
        return (f"Discord ha rechazado el mensaje (HTTP {r.status_code}) ⚠. Lo habitual: el "
                "webhook fue borrado o regenerado — crea uno nuevo en tu servidor y actualízalo en ⚙.")
    except Exception as exc:                                   # noqa: BLE001
        return (f"No he podido publicar en Discord ({type(exc).__name__}: {exc}). "
                "Revisa tu conexión y que la URL del webhook en ⚙ esté completa.")


async def handle(intent: str, text: str, match, ctx) -> dict:
    try:
        if intent == "open":
            base = await _open_discord()
            return {"reply": f"{base} Si quieres que publique yo en un canal: "
                             "«manda a discord: <mensaje>».", "speak": True}
        if intent == "notify":
            gd = match.groupdict() if match else {}
            return {"reply": await _notify(ctx, gd.get("msg") or gd.get("msg2") or ""), "speak": True}
        if intent == "call":
            opened = await _open_discord()
            return {"reply": f"{opened} Ojo: Discord no permite iniciar llamadas por automatización "
                             "(ni API ni deep links para cuentas de usuario), así que te lo dejo abierto "
                             "y pulsa el botón de llamar. Si quieres avisos automáticos a un canal, "
                             "monto un webhook: «manda a discord: <mensaje>».", "speak": True}
        if intent == "dm":
            opened = await _open_discord()
            return {"reply": f"{opened} Abrir un DM concreto a una persona tampoco está permitido "
                             "por automatización; te dejo Discord abierto para que elijas el chat. "
                             "Para avisos a un canal sí puedo, con un webhook («manda a discord: …»).",
                    "speak": True}
    except Exception as exc:                                   # noqa: BLE001
        return {"reply": f"El minion de Discord ha fallado: {type(exc).__name__}: {exc}", "error": True}
    return {"reply": "Orden de Discord no reconocida. Prueba «abre discord», "
                     "«manda a discord: <mensaje>» o «avisa por discord que <algo>»."}
