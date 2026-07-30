"""Minion Facturación — genera facturas por voz/texto y las registra."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

INVOICE_DIR = Path(__file__).resolve().parents[2] / "data" / "invoices"

_NO_CLIENTE = (r"completad[ao]s?\b|pendientes?\b|progreso\b|revisi[oó]n\b|"
               r"hechas?\b|terminadas?\b|realizadas?\b|done\b")

SKILL = {
    "name": "Facturación",
    "description": "Facturas HTML por voz con numeración automática, registro en Postgres y archivo en data/invoices",
    "patterns": {
        # SIEMPRE ancladas a la palabra «factura»: nada de robar «crea X» genéricos.
        # v23: además, el CLIENTE nunca puede ser una columna del tablero y
        # «…la factura a completadas» no cuenta como facturar — «mueve la tarea
        # enviar la factura a completadas» acababa EMITIENDO UNA FACTURA (lo cazó
        # la prueba end-to-end del tablero).
        "invoice": r"(?:h[aá]z(?:le|me)?|cr[eé]a(?:me)?|gen[eé]ra(?:me)?|em[ií]te(?:me)?|prep[aá]ra(?:me)?|extiende)\s+"
                   r"(?:una?\s+|otra\s+|la\s+)?factura\s+(?:a|para)\s+"
                   r"(?:la\s+empresa\s+|el\s+cliente\s+)?"
                   r"(?P<client>(?!" + _NO_CLIENTE + r")[\wÁÉÍÓÚáéíóúñ]+)(?P<rest>.*)"
                   r"|(?<!la\s)(?<!una\s)(?<!otra\s)(?<!esta\s)(?<!esa\s)"
                   r"fact[uú]ra(?:le|me)?\s+a[l]?\s+(?:la\s+empresa\s+|el\s+cliente\s+)?"
                   r"(?P<client2>(?!" + _NO_CLIENTE + r")[\wÁÉÍÓÚáéíóúñ]+)(?P<rest2>.*)",
        "list": r"(?:ver|ens[eé][ñn]a(?:me)?|mu[eé]stra(?:me)?|dame|dime|lista(?:do)?\s+de?|l[ií]sta(?:me)?|revisa|consulta|c[oó]mo\s+van)\s+"
                r"(?:las?\s+|mis\s+|el\s+)?(?:[uú]ltimas\s+)?facturas"
                r"|qu[eé]\s+facturas\s+(?:hay|tengo|hemos\s+hecho|llevamos)"
                r"|cu[aá]ntas\s+facturas\b",
    },
}

TEMPLATE = """<!doctype html><html lang="es"><meta charset="utf-8">
<title>Factura {number}</title>
<style>
 body{{font-family:Segoe UI,Arial,sans-serif;max-width:720px;margin:40px auto;color:#222}}
 h1{{color:#0a7d55;border-bottom:3px solid #0a7d55;padding-bottom:8px}}
 table{{width:100%;border-collapse:collapse;margin-top:24px}}
 td,th{{border:1px solid #ccc;padding:10px;text-align:left}}
 .total{{font-size:1.3em;font-weight:bold;text-align:right;margin-top:16px}}
 .meta{{color:#666}}
</style>
<h1>nexus · Factura {number}</h1>
<p class="meta">Fecha: {date} — Estado: borrador</p>
<p><b>Cliente:</b> {client}</p>
<table><tr><th>Concepto</th><th>Importe</th></tr>
<tr><td>{concept}</td><td>{amount:.2f} €</td></tr></table>
<p class="total">TOTAL: {amount:.2f} €</p>
<p class="meta">Generada automáticamente por el minion de facturación.</p></html>"""


async def handle(intent: str, text: str, match, ctx) -> dict:
    pg = ctx["pg"]

    if intent == "invoice":
        gd = match.groupdict()
        client = (gd.get("client") or gd.get("client2") or "").strip().title()
        rest = gd.get("rest") or gd.get("rest2") or ""
        m_amount = re.search(r"(\d+(?:[.,]\d{1,2})?)\s*(euros?|€|eur)", rest, re.I)
        amount = float(m_amount.group(1).replace(",", ".")) if m_amount else 100.0
        m_concept = re.search(r"por\s+(?P<c>.+?)(?:\s+de\s+\d|$)", rest, re.I)
        concept = (m_concept.group("c").strip() if m_concept else "Servicios profesionales")

        if pg.online:
            row = pg.save_invoice(client, concept, amount)
            number = row["number"] if row else None
        else:
            number = None
        if not number:
            number = f"WBK-{dt.date.today().year}-LOCAL-{dt.datetime.now():%H%M%S}"

        INVOICE_DIR.mkdir(parents=True, exist_ok=True)
        out = INVOICE_DIR / f"{number}.html"
        out.write_text(TEMPLATE.format(number=number, client=client, concept=concept,
                                       amount=amount, date=f"{dt.date.today():%d/%m/%Y}"),
                       encoding="utf-8")
        ctx["graph"].append_daily(f"Factura {number} → {client}: {concept} ({amount:.2f} €)",
                                  section="Facturación")
        notas = []
        if not m_amount:
            notas.append("No me has dicho importe, así que he puesto 100.00 € provisionales — "
                         "repítemelo con «... de 350 euros» y la regenero con el bueno.")
        if not pg.online:
            notas.append("Postgres está offline: numeración LOCAL y registro en la memoria diaria; "
                         "cuando la base vuelva, las nuevas facturas retoman la serie.")
        notas.append("El envío por email aún no está conectado: cuando pongas el SMTP en ⚙ lo mando yo; "
                     "mientras, el HTML queda listo para imprimir o adjuntar.")
        return {"reply": f"Factura {number} ✔ para {client}: «{concept}», {amount:.2f} €. "
                         f"Guardada en data/invoices/. " + " ".join(notas) +
                         " Di «ver facturas» para el listado.",
                "data": {"number": number, "file": str(out)}}

    if intent == "list":
        if pg.online:
            rows = pg._rows("SELECT number, concept, amount, status FROM invoices "
                            "ORDER BY id DESC LIMIT 8")
            if rows:
                lines = [f"• {r['number']} — {r['concept']} — {r['amount']} € ({r['status']})"
                         for r in rows]
                return {"reply": "🧾 Últimas facturas (Postgres):\n" + "\n".join(lines) +
                                 "\n¿Otra? Di «hazle una factura a <cliente> por <concepto> de <importe> euros»."}
        files = sorted(INVOICE_DIR.glob("*.html"), reverse=True)[:8]
        if files:
            return {"reply": "🧾 Facturas locales (data/invoices/):\n" +
                             "\n".join(f"• {f.stem}" for f in files) +
                             "\nPostgres no responde ahora mismo, así que esto es el archivo local. "
                             "Di «hazle una factura a <cliente> por <concepto> de <importe> euros» para otra."}
        return {"reply": "Todavía no hay ninguna factura. Estrena la serie: «hazle una factura a "
                         "Ubix por el servicio de diseño de 350 euros»."}

    return {"reply": "Orden de facturación no reconocida. Prueba «hazle una factura a <cliente> "
                     "por <concepto> de <importe> euros» o «ver facturas»."}
