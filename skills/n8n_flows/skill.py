"""Minion n8n — lanza flujos de n8n por webhook y envía WhatsApp a través de ellos."""
from __future__ import annotations

import httpx

SKILL = {
    # QUÉ EFECTO tiene cada intent del enrutador (ARQ-03, task T8b): lo decide
    # `canales.EFECTOS` para permitir, preguntar o denegar; sin declarar, destructive.
    "effects": {
        "whatsapp": "external_send",
        "flow": "external_send",
    },
    # Los que YA preguntan con confirm.request antes de su efecto: `brain`
    # no los vuelve a preguntar (T8c).
    "confirma": ("whatsapp",),
    "name": "n8n / WhatsApp",
    "description": "Dispara tus flujos de n8n por webhook y envía WhatsApp a través de ellos (Evolution API, Twilio, Cloud API)",
    "patterns": {
        # -- whatsapp (siempre anclado a la palabra whatsapp/wasap) --
        "whatsapp": r"(?:env[ií]a(?:le)?|m[aá]nda(?:le)?|escr[ií]be(?:le)?)\s+(?:un\s+)?(?:whats?app?|wasap|guasap)\s+a[l]?\s+"
                    r"(?P<to>[\wÁÉÍÓÚáéíóúñ]+)\s+"
                    r"(?:diciendo|que\s+diga|que\s+dice|que\s+ponga|con\s+el\s+(?:mensaje|texto))\s*[:,]?\s*(?:que\s+)?(?P<body>.+)"
                    r"|(?:env[ií]a(?:le)?|m[aá]nda(?:le)?|escr[ií]be(?:le)?|dile?)\s+(?:un\s+(?:whats?app?|wasap|mensaje)\s+)?a[l]?\s+"
                    r"(?P<to2>[\wÁÉÍÓÚáéíóúñ]+)\s+por\s+(?:whats?app?|wasap|guasap)\s*[:,]?\s*"
                    r"(?:que\s+diga\s+|que\s+|diciendo\s+)?(?P<body2>.+)"
                    r"|whats?app?\s+(?:a|para)\s+(?P<to3>[\wÁÉÍÓÚáéíóúñ]+)\s*[:,]\s*(?P<body3>.+)",
        # -- flujos (anclado a flujo/workflow o a n8n) --
        "flow": r"\b(?:l[aá]nza(?:me)?|ej[eé]cuta(?:me)?|dispara(?:me)?|corre|arranca(?:me)?|inicia)\s+(?:el\s+|mi\s+)?(?:flujo|workflow|flow)\s+"
                r"(?:de\s+n8n\s+)?(?P<flow>[\w\- ]+)"
                r"|\ben\s+n8n\s+(?:l[aá]nza(?:me)?|ej[eé]cuta(?:me)?|dispara(?:me)?|corre)\s+(?:el\s+flujo\s+)?(?P<flow2>[\w\- ]+)",
    },
}


async def _post(url: str, payload: dict) -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.post(url, json=payload)
            return r.status_code < 300, f"HTTP {r.status_code}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


async def _whatsapp_via_movil(to: str, body: str, ctx) -> dict | None:
    """RESPALDO estilo Android Auto: sin webhook de n8n pero CON móvil vinculado,
    el WhatsApp sale por tu propio teléfono — nexus manda el evento y en el móvil
    se abre WhatsApp con el chat y el texto ya escritos (solo le das a enviar).
    El número se resuelve con la agenda de nexus (skill teléfono). Devuelve la
    respuesta, o None si no hay móvil vinculado."""
    from backend.core.infraestructura import remote
    from backend.core.comun.events import bus
    if not remote.devices():
        return None
    number = ""
    try:
        import importlib.util
        from backend.core.comun.config import SKILLS_DIR
        spec = importlib.util.spec_from_file_location(
            "tel_agenda", SKILLS_DIR / "telefono" / "skill.py")
        tel = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tel)
        _real, number = tel.resolve_contact(to)
    except Exception:
        number = ""
    wa = ""
    if number:
        from urllib.parse import quote
        wa = "https://wa.me/" + __import__("re").sub(r"\D", "", number) + \
             ("?text=" + quote(body) if body else "")
    await bus.emit("whatsapp", {"to": to, "number": number, "text": body, "url": wa})
    ctx["graph"].append_daily(f"WhatsApp→{to} vía móvil: {body}", section="Comunicación")
    if number:
        return {"reply": f"📲 Te lo dejo listo en el móvil: se abre WhatsApp con el chat de "
                         f"{to} ({number}) y el mensaje escrito — solo dale a enviar. "
                         "Para envío 100% automático sin tocar el móvil, conecta n8n (⚙ → n8n)."}
    return {"reply": f"📲 No tengo el número de {to} en mi agenda, así que en el móvil se abre "
                     f"WhatsApp para que elijas el chat (el texto va copiado en el aviso). "
                     f"Arréglalo para siempre: di «apunta el teléfono de {to} 612…» y la "
                     "próxima se abre su chat directo."}


async def _safe_whatsapp_via_movil(to: str, body: str, ctx) -> dict | None:
    """Envoltorio blindado de _whatsapp_via_movil: si algo revienta ahí dentro
    (agenda corrupta, bus caído...) esto NO debe convertirse en el error
    técnico en crudo que precisamente queríamos dejar de dar — se trata igual
    que «no hay móvil vinculado» y el llamante sigue con su propio mensaje."""
    try:
        return await _whatsapp_via_movil(to, body, ctx)
    except Exception:
        return None


# ── WHATSAPP: VISTA PREVIA + CONFIRMACIÓN + IDEMPOTENCIA (SEC-05, P1-4) ──────
# Incidencia SEC-05: `handle("whatsapp", …)` hacía el POST al webhook de n8n —o
# abría WhatsApp en el móvil— en la misma llamada, sin que nadie viera el mensaje
# antes de que saliera, y sin nada que impidiera que la misma orden repetida lo
# mandara dos veces. El correo tenía el mismo agujero; la asimetría con lo que sí
# pedía confirmación era el hallazgo.
#
# Ahora el mensaje se ARMA enseñándolo tal cual y la cadena de siempre (n8n
# primero, móvil después) vive DENTRO del `action`. La pregunta se arma antes de
# intentar n8n: enseñar el mensaje no puede depender de que n8n conteste.
#
def _vista_whatsapp(to: str, body: str, hay_n8n: bool) -> str:
    """La pregunta que ve el operador: el WhatsApp TAL CUAL va a salir."""
    from backend.core.comun import confirm
    via = ("Sale por tu flujo n8n si contesta; si no, por el móvil vinculado."
           if hay_n8n else "Sale por el móvil vinculado (no hay webhook de n8n).")
    return "\n".join(["📲 Voy a mandar este WhatsApp, tal cual:",
                      f"Para: {to}",
                      "Mensaje:",
                      confirm.recortar(body),
                      via + " ¿Lo mando? Responde «sí» o «no»."])


async def handle(intent: str, text: str, match, ctx) -> dict:
    url = ctx["settings"].get("n8n_webhook_url", "").strip()
    gd = match.groupdict() if match else {}

    if intent == "whatsapp":
        to = (gd.get("to") or gd.get("to2") or gd.get("to3") or "").strip()
        body = (gd.get("body") or gd.get("body2") or gd.get("body3") or "").strip()
        from backend.core.comun import confirm
        canal = ctx.get("channel", "pc")
        ventana = confirm.umbrales_envios()["ventana_idempotencia_seg"]
        clave = confirm.clave_envio("envio_whatsapp", to, "", body)
        destinos = [{"id": to, "title": body[:80]}]

        def _ya_salio() -> str:
            return (f"Ese WhatsApp a {to} ya ha salido hace un momento. No lo mando otra "
                    "vez: si de verdad quieres repetirlo, cambia el texto y te lo vuelvo "
                    "a pedir confirmar.")

        if confirm.ya_enviado(clave, ventana, channel=canal, kind="envio_whatsapp",
                              targets=destinos):
            return {"reply": _ya_salio()}

        async def _enviar() -> str:
            """La cadena de siempre, pero ya confirmada: n8n es OPCIONAL y el móvil
            vinculado (estilo Android Auto) es la vía que siempre funciona. Si hay
            webhook se intenta primero; si falla —n8n caído, flujo inactivo, URL
            vieja, 404…— se cae al móvil EN LUGAR de devolver un error técnico: lo
            único que de verdad importa es que el WhatsApp salga."""
            if confirm.ya_enviado(clave, ventana, channel=canal,
                                  kind="envio_whatsapp", targets=destinos):
                return _ya_salio()
            if url:
                ok, detail = await _post(url, {"action": "whatsapp", "to": to,
                                              "message": body})
                if ok:
                    ctx["graph"].append_daily(
                        f"WhatsApp→{to} vía n8n ({detail}): {body}", section="Comunicación")
                    confirm.marcar_enviado(clave, channel=canal, kind="envio_whatsapp",
                                           targets=destinos,
                                           result=f"WhatsApp a {to} vía n8n ({detail})")
                    return (f"WhatsApp para {to} entregado a tu flujo n8n ✔ ({detail}): "
                            f"«{body}». El envío final lo hace tu nodo de WhatsApp "
                            "(Evolution, Twilio, Cloud API...). Di «lanza el flujo "
                            "<nombre>» para disparar otra automatización.")
                via_movil = await _safe_whatsapp_via_movil(to, body, ctx)
                if via_movil:
                    confirm.marcar_enviado(clave, channel=canal, kind="envio_whatsapp",
                                           targets=destinos,
                                           result=f"WhatsApp a {to} vía móvil "
                                                  f"(n8n: {detail})")
                    return via_movil["reply"]
                return (f"No llego al webhook de n8n ({detail}) y no tengo el móvil "
                        "vinculado a mano, así que no puedo mandarlo. Abre la app de nexus "
                        "en el móvil (✔ VINCULADO) o revisa que n8n esté arrancado y el "
                        "flujo activo, y repite la orden.")
            via_movil = await _safe_whatsapp_via_movil(to, body, ctx)
            if via_movil:
                confirm.marcar_enviado(clave, channel=canal, kind="envio_whatsapp",
                                       targets=destinos,
                                       result=f"WhatsApp a {to} vía móvil")
                return via_movil["reply"]
            return ("Para mandar WhatsApp necesito una de dos: tu MÓVIL vinculado "
                    "(abre la app de nexus y comprueba el ✔ VINCULADO — el mensaje "
                    "sale por tu propio WhatsApp) o un flujo de n8n con webhook "
                    "(⚙ → n8n; ejemplo importable en config/n8n_flujo_ejemplo.json).")

        return {"reply": confirm.request(
            channel=canal, kind="envio_whatsapp",
            summary=_vista_whatsapp(to, body, hay_n8n=bool(url)),
            action=_enviar, request_text=text, targets=destinos,
            cancel_reply="Vale, no he enviado nada.", destructive=False)}

    if not url:
        return {"reply": "n8n no está conectado todavía: pega la URL de tu webhook en ⚙ "
                         "(campo n8n) o en config/settings.json → n8n_webhook_url "
                         "(ej.: http://localhost:5678/webhook/nexus). Tienes un flujo de "
                         "ejemplo importable en config/n8n_flujo_ejemplo.json. En cuanto "
                         "la guardes, repite la orden y disparo."}

    if intent == "flow":
        flow = (gd.get("flow") or gd.get("flow2") or "").strip()
        ok, detail = await _post(url, {"action": "flow", "flow": flow, "text": text})
        if ok:
            return {"reply": f"Flujo «{flow}» disparado en n8n ✔ ({detail}). Si el flujo quiere "
                             "contestarme, que llame a POST /api/n8n con {\"text\": \"...\"} "
                             "y proceso la orden al vuelo."}
        return {"reply": f"El webhook de n8n no responde ({detail}). Arranca n8n, activa el "
                         "flujo y revisa la URL en ⚙ → n8n; después vuelve a pedírmelo."}

    return {"reply": "Orden de n8n no reconocida. Prueba «lanza el flujo <nombre>» o "
                     "«envía un whatsapp a <contacto> diciendo <mensaje>»."}
