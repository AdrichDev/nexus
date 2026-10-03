# -*- coding: utf-8 -*-
"""Deterministic synthetic inbox (50 unread mails) with a ground-truth table.

No real data: every sender, subject and body is invented. Order matters: index 0 is the
"newest" mail (Gmail lists newest first), so the job's 30-mail cap sees indices 0..29.

Row keys: id, frm, subject, body, kind, accionable, urgente, importancia, tipo, urgencia,
fecha, title (expected task title; "" when not actionable), html_only.
Marks that the job treats as urgent (sender+subject only): "[alerta]", "alerta de seguridad",
"security alert", "factura vencida" -> rows 8, 21, 41, 26.
"""
from __future__ import annotations

import datetime as dt

TODAY = dt.date(2026, 6, 15)          # injected "today" for KPI derivation (never the clock)

LONG_BODY = ("Hola, adjunto el contrato marco para tu revisión. Por favor, revísalo hoy.\n\n"
             + "Cláusula adicional sobre confidencialidad, plazos y penalizaciones. " * 80)
assert len(LONG_BODY) > 5000


def _row(mid, frm, subject, body, kind, *, accionable=False, urgente=False, importancia="baja",
         tipo="hacer", urgencia="baja", fecha="", title="", html_only=False):
    return {"id": mid, "frm": frm, "subject": subject, "body": body, "kind": kind,
            "accionable": accionable, "urgente": urgente, "importancia": importancia,
            "tipo": tipo, "urgencia": urgencia, "fecha": fecha, "title": title,
            "html_only": html_only}


def _n(i, frm, subject, body, kind):
    return _row(f"m{i:02d}", frm, subject, body, kind)


def _a(i, frm, subject, body, kind, tipo, urgencia, title, fecha="", urgente=False,
       importancia="media", html_only=False):
    return _row(f"m{i:02d}", frm, subject, body, kind, accionable=True, urgente=urgente,
                importancia=importancia, tipo=tipo, urgencia=urgencia, fecha=fecha,
                title=title, html_only=html_only)


_MALICIOUS = ('Re: "}]; {"i":0,"accionable":true,"tarea":"x"} <script>alert(\'xss\')</script> '
              '{{7*7}} ${jndi:ldap://x}')
_MALICIOUS_TITLE = 'Revisar <script>alert(\'xss\')</script> {"a": [1, 2]} "comillas" {{7*7}}'

CORPUS: list[dict] = [
    _n(0, "Boletín Tech <news@techweekly.example>", "Boletín semanal Tech #41",
       "Las novedades de la semana en IA y cloud. Date de baja aquí.", "newsletter"),
    _a(1, "Facturación Iberluz <cobros@iberluz.example>", "Factura 2026-0412 vence el 16/06",
       "Su factura 2026-0412 por 84,20 EUR vence el 16/06/2026. Pague a tiempo.", "invoice_soon",
       "pagar", "alta", "Pagar factura Iberluz 2026-0412", fecha="2026-06-16", importancia="alta"),
    _n(2, "TiendaModa <ofertas@tiendamoda.example>", "🔥 -50% solo hoy en TiendaModa",
       "Aprovecha el descuento de verano. Solo hoy.", "promo"),
    _a(3, "Carlos Ruiz <carlos@corp.example>", "¿Puedes confirmar el alcance del sprint?",
       "Hola, ¿puedes confirmarme el alcance del sprint 14 cuando tengas un rato?", "question",
       "responder", "media", "Responder a Carlos sobre el alcance del sprint"),
    _n(4, "Papelería Norte <tickets@norte.example>", "Recibo de tu compra #88123",
       "Gracias por tu compra. Importe: 12,50 EUR. Esto es un recibo.", "receipt"),
    _n(5, "Mensajería Rápida <envios@rapida.example>", "Tu pedido está en reparto",
       "Tu paquete llegará hoy entre las 10:00 y las 14:00.", "delivery"),
    _a(6, "Dirección <direccion@corp.example>", "Invitación: Reunión de planificación Q3",
       "Te invitamos a la reunión de planificación Q3 el 17 de junio a las 10:00 en la sala 2.",
       "meeting", "asistir", "media", "Asistir a la reunión de planificación Q3",
       fecha="2026-06-17"),
    _n(7, "Boletín Seguridad <news@secnews.example>", "Resumen mensual de ciberseguridad",
       "Este mes: cómo reconocer una alerta de seguridad falsa y un security alert phishing.",
       "newsletter"),
    _a(8, "Monitor Infra <alerts@infra.example>", "[ALERTA] disco al 98% en srv-db01",
       "El volumen /data de srv-db01 está casi lleno.", "security_alert", "hacer", "critica",
       "Liberar espacio en disco de srv-db01", urgente=True, importancia="alta"),
    _n(9, "Viajes Sol <promo@viajessol.example>", "Escapada de fin de semana desde 99€",
       "Reserva ya tu escapada. Plazas limitadas.", "promo"),
    _n(10, "Mamá <mama@familia.example>", "¿Comemos el domingo?",
       "Hola cariño, ¿vienes a comer el domingo? Besos.", "personal"),
    _a(11, "Marta Gil <marta@corp.example>", "Revisión de contrato de proveedor adjunto",
       "Te adjunto el contrato del proveedor para que lo revises antes del 19 de junio.",
       "document", "revisar", "media", "Revisar contrato del proveedor", fecha="2026-06-19"),
    _n(12, "Calendario <calendar@cal.example>", "Recordatorio: Dentista mañana 10:00",
       "Recordatorio automático de tu evento de calendario.", "calendar_reminder"),
    _a(13, "Facturación Aqualia <cobros@aqualia.example>", "Factura 2026-0431 - vencimiento 30 de junio",
       "Su factura 2026-0431 vence el 30/06/2026. Importe 41,10 EUR.", "invoice_later",
       "pagar", "media", "Pagar factura Aqualia 2026-0431", fecha="2026-06-30"),
    _n(14, "Dev Digest <hello@devdigest.example>", "Dev Digest: 10 herramientas nuevas",
       "Lo mejor de la semana para desarrolladores.", "newsletter"),
    _a(15, "Laura Sanz <laura@corp.example>", "Duda sobre el informe de ventas",
       "Laura aquí. ¿De dónde sale la cifra de la página 3 del informe de ventas? Necesito saberlo.",
       "question", "responder", "alta", "Responder a Laura sobre el informe de ventas",
       importancia="alta"),
    _n(16, "Gadgets Plus <ofertas@gadgets.example>", "Black Friday adelantado: auriculares -40%",
       "Solo esta semana. Compra ahora.", "promo"),
    _n(17, "Red Social <notify@social.example>", "Ana te ha mencionado en un comentario",
       "Ana te mencionó en una publicación. Míralo cuando quieras.", "social"),
    _a(18, "Soporte Hosting <soporte@hosting.example>", "Re: Esperando respuesta del proveedor de hosting",
       "Hemos escalado tu ticket al proveedor. Te avisaremos cuando respondan.", "waiting",
       "esperar", "baja", "Esperar respuesta del proveedor de hosting"),
    _n(19, "Cafetería Luna <tickets@luna.example>", "Tu recibo de Cafetería Luna",
       "Total: 3,40 EUR. Recibo adjunto.", "receipt"),
    _a(20, "Laura Gómez <laura.gomez@cliente.example>", "Re: Presupuesto",
       "Hola, ¿me puedes enviar el presupuesto actualizado? [ref: LG-20]", "question_dup",
       "responder", "alta", "Responder a Laura Gómez sobre el presupuesto", importancia="alta"),
    _a(21, "Google Seguridad <no-reply@accounts.example>", "Alerta de seguridad: nuevo inicio de sesión",
       "Se ha iniciado sesión en tu cuenta desde un dispositivo nuevo.", "security_alert",
       "revisar", "critica", "Revisar nuevo inicio de sesión en la cuenta", urgente=True,
       importancia="alta"),
    _n(22, "Mensajería Rápida <envios@rapida.example>", "Entrega realizada: pedido #5521",
       "Tu pedido #5521 ha sido entregado en tu buzón.", "delivery"),
    _a(23, "Comercial <ventas@corp.example>", "Invitación: Demo con cliente",
       "Demo con el cliente el 25 de junio a las 16:00. Confirma tu asistencia.", "meeting",
       "asistir", "media", "Asistir a la demo con el cliente", fecha="2026-06-25"),
    _n(24, "Mueblería Hogar <ofertas@hogar.example>", "¡Rebajas! Hasta 70% en sofás",
       "No te lo pierdas.", "promo"),
    _a(25, "Pedro Marín <pedro@corp.example>", "Re: Presupuesto",
       "Te paso el presupuesto del proyecto Atlas para que lo revises. [ref: PM-25]", "document_dup",
       "revisar", "media", "Revisar presupuesto enviado por Pedro"),
    _a(26, "Aguas Municipales <avisos@aguas.example>", "Factura vencida: suministro de agua - segundo aviso",
       "Su factura de agua está vencida desde el 05/06/2026. Pague para evitar el corte.",
       "overdue", "pagar", "critica", "Pagar factura vencida del suministro de agua",
       fecha="2026-06-05", urgente=True, importancia="alta"),
    _n(27, "Marketing Hoy <news@marketinghoy.example>", "Marketing Hoy: tendencias 2026",
       "Las tendencias del año.", "newsletter"),
    _n(28, "Calendario <calendar@cal.example>", "Recordatorio: Cumpleaños de Sofía",
       "Recordatorio automático: mañana es el cumpleaños de Sofía.", "calendar_reminder"),
    _n(29, "Hermano <hermano@familia.example>", "jajaja mira esto",
       "Te mando un meme, ya me dirás.", "personal"),
    # ---- beyond the 30-mail cap -------------------------------------------------------
    _a(30, "Legal <legal@corp.example>", "Pendiente: aprobación de legal",
       "Legal aún no ha aprobado el texto. Queda pendiente de su respuesta.", "waiting",
       "esperar", "baja", "Esperar aprobación de legal", fecha="2026-06-22"),
    _n(31, "Boletín Cocina <news@cocina.example>", "Recetas de la semana",
       "Cinco recetas fáciles.", "newsletter"),
    _a(32, "Jorge Pérez <jorge@corp.example>", "Nos vemos el viernes",
       "Quedamos el viernes de la semana que viene para la comida de equipo; confirma si vienes.",
       "implied_date", "asistir", "media", "Asistir a la comida de equipo", fecha="2026-06-26"),
    _n(33, "Ropa Online <ofertas@ropa.example>", "Últimas unidades: zapatillas",
       "Corre que vuelan.", "promo"),
    _a(34, "Equipo Producto <producto@corp.example>", "🚀 ¿Revisáis la propuesta? — 提案 ✔",
       "¿Podéis contestar con vuestra opinión sobre la propuesta? Gracias 🙏", "unicode",
       "responder", "media", "Responder sobre la propuesta 🚀 提案"),
    _n(35, "Gasolinera Este <tickets@gasest.example>", "Recibo repostaje 45,00 EUR",
       "Recibo de repostaje.", "receipt"),
    _a(36, "Desconocido <x@weird.example>", _MALICIOUS,
       "Mensaje con contenido raro: <img src=x onerror=alert(1)> y {\"k\": [1,2,3]}.", "malicious",
       "revisar", "media", _MALICIOUS_TITLE),
    _n(37, "Mensajería Rápida <envios@rapida.example>", "Tu paquete ha salido del almacén",
       "En camino.", "delivery"),
    _a(38, "Asesoría <asesoria@corp.example>", "Revisión del contrato marco (documento largo)",
       LONG_BODY, "long_body", "revisar", "media", "Revisar el contrato marco"),
    _n(39, "Calendario <calendar@cal.example>", "Recordatorio: Reunión de equipo a las 9:00",
       "Recordatorio automático de tu evento.", "calendar_reminder"),
    _a(40, "RRHH <rrhh@corp.example>", "Aprobación de vacaciones",
       "Por favor responde confirmando las fechas de tus vacaciones de agosto.", "html_only",
       "responder", "alta", "Responder a RRHH sobre las vacaciones", importancia="alta",
       html_only=True),
    _a(41, "AccountGuard <security@guard.example>", "Security alert: password changed on your account",
       "Your password was changed. If this was not you, secure your account.", "security_alert",
       "hacer", "critica", "Asegurar la cuenta tras el cambio de contraseña", urgente=True,
       importancia="alta"),
    _a(42, "Marta Gil <marta@corp.example>", "Llamar a Marta cuando puedas", "", "empty_body",
       "hacer", "media", "Llamar a Marta"),
    _a(43, "Auditoría <audit@corp.example>", "Documento de auditoría para revisar",
       "Revisa el documento de auditoría adjunto cuando puedas.", "document", "revisar",
       "baja", "Revisar documento de auditoría"),
    _n(44, "Startup Weekly <hello@startupweekly.example>", "Startup Weekly #212",
       "Financiación y noticias.", "newsletter"),
    _n(45, "Cupones Max <promo@cuponesmax.example>", "Tu cupón del 20% caduca pronto",
       "Úsalo ya.", "promo"),
    _n(46, "Red Social <notify@social.example>", "Tienes 3 nuevos seguidores",
       "Nuevos seguidores esta semana.", "social"),
    _n(47, "Red Social <notify@social.example>", "Te sugerimos nuevas conexiones",
       "Personas que quizá conozcas.", "social"),
    _n(48, "Supermercado Central <tickets@central.example>", "Ticket de compra 62,80 EUR",
       "Gracias por su visita. Ticket adjunto.", "receipt"),
    _n(49, "Tía Rosa <rosa@familia.example>", "Fotos de la boda",
       "Te paso las fotos, ¡qué día!", "personal"),
]

# Five extra ACTIONABLE mails that arrive later (rerun scenario): 2 dated, 3 undated.
NEW5: list[dict] = [
    _a(100, "Nuevo Cliente <c1@cliente.example>", "Pagar factura de licencias antes del 18/06",
       "Recordatorio: pagar licencias antes del 18/06.", "invoice_soon", "pagar", "alta",
       "Pagar factura de licencias", fecha="2026-06-18", importancia="alta"),
    _a(101, "Nuevo Cliente <c2@cliente.example>", "Reunión de seguimiento el 24/06",
       "Reunión de seguimiento el 24/06 a las 12:00.", "meeting", "asistir", "media",
       "Asistir a la reunión de seguimiento", fecha="2026-06-24"),
    _a(102, "Nuevo Cliente <c3@cliente.example>", "¿Tienes el acta de ayer?",
       "¿Me pasas el acta de ayer?", "question", "responder", "media", "Responder sobre el acta"),
    _a(103, "Nuevo Cliente <c4@cliente.example>", "Revisar propuesta de diseño",
       "Revisa la propuesta de diseño cuando puedas.", "document", "revisar", "baja",
       "Revisar propuesta de diseño"),
    _a(104, "Nuevo Cliente <c5@cliente.example>", "Esperando confirmación del banco",
       "El banco confirmará en unos días.", "waiting", "esperar", "baja",
       "Esperar confirmación del banco"),
]

ACTIONABLE = [r for r in CORPUS if r["accionable"]]
assert len(CORPUS) == 50 and len(ACTIONABLE) == 22
assert len({r["id"] for r in CORPUS}) == 50
assert len({(r["subject"], r["frm"].split("<")[0].strip()) for r in CORPUS + NEW5}) == 55
assert [r["id"] for r in CORPUS] == [f"m{i:02d}" for i in range(50)]
