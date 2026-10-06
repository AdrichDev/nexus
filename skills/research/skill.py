"""Minion Investigación — informes web con fuentes y análisis económico."""
from __future__ import annotations

import datetime as dt
import re
import webbrowser
from pathlib import Path


REPORTS_DIR = Path(__file__).resolve().parents[2] / "data" / "reports"

SKILL = {
    "name": "Investigación",
    "description": "Investiga en la web (sin API key), redacta informes con fuentes citadas, guarda el histórico y analiza tus gastos/facturas",
    "patterns": {
        "research": r"(?:investiga(?:me)?|indaga|documenta(?:me)?)\s+(?:sobre\s+)?(?P<topic>.+?)"
                    r"(?:\s+y\s+(?:hazme|haz|escr[ií]beme|red[aá]ctame|prep[aá]rame)\s+(?:un\s+)?informe)?$"
                    r"|(?:hazme|red[aá]ctame|escr[ií]beme|prep[aá]rame)\s+(?:un\s+)?informe\s+(?:sobre|de)\s+(?P<topic2>.+)",
        "trends": r"tendencias\s+(?:de|en|del|sobre)\s+(?P<topic>.+)|qu[eé]\s+se\s+lleva\s+(?:ahora\s+)?en\s+(?P<topic2>.+)",
        "economy": r"informe\s+econ[oó]mico|d[oó]nde\s+(?:puedo|podr[ií]a)\s+(?:apurar|recortar|ahorrar|optimizar)"
                   r"|optimiza(?:me)?\s+(?:mis\s+|los\s+|el\s+)?(?:gastos|gasto|presupuesto)"
                   r"|an[aá]lisis\s+(?:de\s+)?(?:mis\s+|los\s+)?(?:gastos|finanzas)|"
                   r"c[oó]mo\s+(?:van|est[aá]n)\s+mis\s+(?:gastos|finanzas|cuentas)",
        # Histórico de informes generados (v19). «abre el informe de X» reabre uno.
        "open_report": r"(?:abre(?:me)?|re[aá]bre(?:me)?|ens[eé][ñn]ame|mu[eé]strame)\s+"
                       r"(?:el\s+|otra\s+vez\s+el\s+)?informe\s+(?:de|sobre|del)\s+(?P<which>.+)",
        "history": r"(?:qu[eé]|cu[aá]ntos)\s+informes\s+(?:tienes|hay|me\s+has\s+hecho|tengo|llevas)"
                   r"|(?:lista|ver|mu[eé]strame|ens[eé][ñn]ame)\s+(?:de\s+|los\s+|mis\s+)?informes"
                   r"|\bmis\s+informes\b|historial\s+de\s+informes",
    },
}

# La búsqueda y la lectura de páginas pasan por el motor central de nexus
# (backend/core/websearch.py): Google News RSS + DDG Lite + DDG HTML, caché con
# TTL y extracción del contenido. Aquí no hay scraping propio.

async def _ddg_search(query: str, n: int = 6) -> list[dict]:
    from backend.core.infraestructura import websearch
    return await websearch.search(query, n)


async def _fetch_text(url: str, limit: int = 4000) -> str:
    from backend.core.infraestructura import websearch
    return await websearch.fetch_page(url, max_chars=limit)


def md_to_docx(md_text: str, out_path) -> bool:
    """Convierte un informe markdown SENCILLO (encabezados #/##/###, viñetas,
    negritas) a un .docx con estilos de Word. Devuelve False si python-docx
    no está instalado (run.bat lo instala; el .md siempre queda igualmente)."""
    try:
        import docx  # python-docx
    except ImportError:
        return False
    try:
        d = docx.Document()
        for raw in (md_text or "").splitlines():
            line = raw.rstrip()
            if not line.strip():
                continue
            plain = re.sub(r"\*\*(.+?)\*\*", r"\1", line)     # fuera negritas md
            if plain.startswith("### "):
                d.add_heading(plain[4:].strip(), level=3)
            elif plain.startswith("## "):
                d.add_heading(plain[3:].strip(), level=2)
            elif plain.startswith("# "):
                d.add_heading(plain[2:].strip(), level=1)
            elif re.match(r"^\s*[-•*]\s+", plain):
                d.add_paragraph(re.sub(r"^\s*[-•*]\s+", "", plain), style="List Bullet")
            elif plain.startswith("_") and plain.endswith("_"):
                p = d.add_paragraph()
                r = p.add_run(plain.strip("_"))
                r.italic = True
            else:
                d.add_paragraph(plain)
        d.save(str(out_path))
        return True
    except Exception:
        return False


_PAGINAS_CANDIDATAS = 5      # páginas que se leen (en paralelo); las 4 primeras con texto se citan
_PAGINAS_CITADAS = 4
_CHARS_PAGINA = 2500
_TIMEOUT_PAGINA = 8.0        # segundos máximos por página: una lenta no bloquea el informe


def _abrir(path: Path) -> bool:
    """True solo si el navegador/editor SE ABRIÓ (`webbrowser.open` devuelve False si no puede)."""
    try:
        return bool(webbrowser.open(path.as_uri()))
    except Exception:
        return False


# Nombres que Windows no deja usar como archivo (con o sin extensión).
_RESERVADOS = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}

# Apuntes de la memoria: ¿es un gasto, un ingreso o no está claro? (lo ambiguo NO se usa)
_APUNTES_POR_PALABRA = 20     # cuántos apuntes se piden al grafo por cada palabra clave
_MAX_GASTOS_PROMPT = 20       # tope por lista de lo que se manda al modelo
_MAX_INGRESOS_PROMPT = 10
_RX_GASTO = re.compile(
    r"\b(?:gast\w*|he\s+pagado|pagu[eé]|pagado\s+(?:por|de|a)\b|compr[eé]|(?:he|hemos)\s+comprado|"
    r"alquiler|suscripci[oó]n|cuota\s+de\s+aut[oó]nomos|n[oó]mina|seguro\s+de|"
    r"factura\s+de\s+(?:la\s+)?(?:luz|agua|gas|internet))",
    re.IGNORECASE)
_RX_INGRESO = re.compile(
    r"\b(?:cobr\w*|ingres\w*|me\s+(?:ha|han)\s+pagado|me\s+pag(?:ó|o|aron)\b|he\s+facturado|venta\w*)",
    re.IGNORECASE)
_NUM = r"\d{1,3}(?:[. ]\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_RX_IMPORTE = re.compile(rf"(?:(?<![\w.,])({_NUM})\s*(?:€|eur(?:os?)?\b)|€\s*({_NUM}))", re.IGNORECASE)


def _tipo_apunte(linea: str) -> str:
    """'gasto' | 'ingreso' | '' (ambiguo o sin relación: no se usa)."""
    g, i = bool(_RX_GASTO.search(linea)), bool(_RX_INGRESO.search(linea))
    return "gasto" if g and not i else "ingreso" if i and not g else ""


def _importe(linea: str) -> float | None:
    """Primer importe en euros de la línea («1.234,50 €», «200€», «€ 45»), o None."""
    m = _RX_IMPORTE.search(linea or "")
    if not m:
        return None
    raw = (m.group(1) or m.group(2)).strip().replace(" ", "")
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", raw):
        raw = raw.replace(".", "")
    try:
        return float(raw)
    except ValueError:
        return None


def _nombre_seguro(title: str) -> str:
    safe = re.sub(r"[^\w\- ]", "", title)[:40].strip(" .-")
    if not safe:
        return "informe"
    return f"informe-{safe}" if safe.lower() in _RESERVADOS else safe


def _save_report(title: str, body_md: str) -> Path:
    """Guarda el informe SIN pisar nunca uno anterior (mismo tema y día -> -2, -3…). La creación es
    EXCLUSIVA (`open(..., 'x')`): si dos peticiones coinciden, la segunda pasa al siguiente nombre."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    base = f"{_nombre_seguro(title)}-{dt.date.today().isoformat()}"
    contenido = (f"# {title}\n\n_{dt.datetime.now():%d/%m/%Y %H:%M} — "
                 f"generado por nexus_\n\n{body_md}\n")
    n = 1
    while True:
        out = REPORTS_DIR / (f"{base}.md" if n == 1 else f"{base}-{n}.md")
        try:
            with open(out, "x", encoding="utf-8") as fh:
                fh.write(contenido)
            return out
        except FileExistsError:
            n += 1


async def _full_report(topic: str, angle: str) -> dict:
    from backend.core.infraestructura import websearch
    from backend.core.infraestructura.llm import ask_llm
    # Sin anuncios del buscador; se leen en PARALELO y se citan las primeras con texto.
    results = websearch.sin_ruido(await _ddg_search(topic, 8))[:6]
    candidatas = results[:_PAGINAS_CANDIDATAS]
    textos = await websearch.leer_paginas(candidatas, n=len(candidatas), max_chars=_CHARS_PAGINA,
                                          timeout=_TIMEOUT_PAGINA)
    leidas = [(r, t) for r, t in zip(candidatas, textos) if t][:_PAGINAS_CITADAS]
    cited = [r for r, _t in leidas]
    if not leidas:
        reply, prov = await ask_llm(
            f"{angle} sobre «{topic}». No hay fuentes web disponibles ahora mismo: "
            "usa tu conocimiento general y dilo claramente al principio.")
        if prov == "ninguno":
            return {"reply": f"⚠ No he podido leer NINGUNA fuente web sobre «{topic}» (¿sin red o las "
                             "fuentes bloquean?) y el modelo no está disponible, así que no tengo nada "
                             f"que ofrecerte ahora. Motivo del modelo: {reply}", "sources": []}
        # Sin fuentes no hay informe: se dice antes del texto y no se guarda
        # nada en data/reports/ para que el histórico solo tenga informes reales.
        return {"reply": "⚠ No he podido leer NINGUNA fuente web sobre "
                         f"«{topic}» (¿sin red o las fuentes bloquean?). Esto de abajo "
                         "sale del conocimiento general del modelo, NO está contrastado "
                         "y no lo guardo como informe:\n\n" + reply[:1200],
                "sources": []}
    sources_txt = "\n\n".join(f"--- FUENTE [{i}]: {r['title']} ({r['url']}) ---\n{t[:_CHARS_PAGINA]}"
                              for i, (r, t) in enumerate(leidas, 1))
    report, prov = await ask_llm(
        f"{angle} sobre «{topic}» usando SOLO estas fuentes. Estructura: "
        "**Resumen ejecutivo** (3 frases), **Hallazgos clave** (4-6 puntos con datos), "
        "**Oportunidades** (2-3), **Recomendación**. Cita cada dato con el número de su fuente "
        "entre corchetes, p. ej. [1]. Si las fuentes no cubren algún punto, dilo en lugar de "
        f"suponer.\n{sources_txt[:9000]}")
    if prov == "ninguno":
        # Sin modelo no hay informe: el mensaje de error NO se guarda como si lo fuera.
        lista = "\n".join(f"• {r['title']} — {r['url']}" for r in cited)
        return {"reply": f"No pude redactar el informe sobre «{topic}» (el modelo no está disponible), "
                         f"pero estas son las fuentes que sí leí:\n{lista}\nMotivo: {report}",
                "sources": cited}
    src_md = "\n".join(f"[{i}] [{s['title']}]({s['url']})" for i, s in enumerate(cited, 1))
    path = _save_report(topic, report + "\n\n## Fuentes\n" + src_md)
    docx_path = path.with_suffix(".docx")
    full_md = (f"# {topic}\n\n_{dt.datetime.now():%d/%m/%Y %H:%M} — generado por nexus_\n\n"
               + report + "\n\n## Fuentes\n" + src_md)
    has_docx = md_to_docx(full_md, docx_path)
    abierto = _abrir(path)
    extra = f" + Word ({docx_path.name})" if has_docx else ""
    donde = (f"(data/reports/{path.name}{extra}, abierto en tu editor/navegador)" if abierto else
             f"en data/reports/{path.name}{extra}, pero no pude abrir el navegador ni el editor: "
             "ábrelo tú desde esa ruta")
    return {"reply": f"Informe sobre «{topic}» generado con {len(cited)} fuentes {donde}. "
                     "Di «mis informes» para ver el histórico.\n\n"
                     f"{report[:800]}...", "sources": cited}


async def handle(intent: str, text: str, match, ctx) -> dict:
    if intent == "research":
        topic = (match.group("topic") or match.group("topic2") or "").strip().rstrip(".?")
        return await _full_report(topic, "Redacta un informe de investigación completo")

    if intent == "trends":
        topic = (match.group("topic") or match.group("topic2") or "").strip().rstrip(".?")
        return await _full_report(f"tendencias {topic}",
                                  "Redacta un informe de TENDENCIAS actuales")

    if intent == "economy":
        from backend.core.infraestructura.llm import ask_llm
        pg = ctx["pg"]
        # Las facturas son las EMITIDAS a clientes (billing): dinero que ENTRA. Los apuntes se
        # CLASIFICAN uno a uno (gasto / ingreso / ambiguo) y lo ambiguo no se usa para aconsejar.
        facturas, totales = [], {}
        db_falla = False
        if pg.online:
            try:
                rows = pg._rows("SELECT number, concept, amount, status FROM invoices "
                                "ORDER BY id DESC LIMIT 20")
                for r in rows:
                    facturas.append(f"INGRESO — Factura {r['number']}: {r['concept']} — "
                                    f"{r['amount']}€ ({r['status']})")
                    try:
                        totales[r["status"]] = totales.get(r["status"], 0.0) + float(r["amount"])
                    except (TypeError, ValueError):
                        pass
            except Exception:
                db_falla = True      # tabla ausente o DB caída: se dice, no se calla
        gastos, ingresos_notas, ignorados, vistos = [], [], 0, set()
        gasto_total, con_importe = 0.0, 0
        for clave in ("gasto", "pago", "cobro", "ingreso"):
            for n in ctx["graph"].search(clave, _APUNTES_POR_PALABRA):
                linea = n["line"]
                if linea in vistos:
                    continue
                vistos.add(linea)
                tipo = _tipo_apunte(linea)
                if tipo == "gasto":
                    gastos.append(linea)
                    importe = _importe(linea)
                    if importe is not None:
                        gasto_total += importe
                        con_importe += 1
                elif tipo == "ingreso":
                    ingresos_notas.append(f"INGRESO — {linea}")
                else:
                    ignorados += 1
        ingresos = facturas + ingresos_notas
        aviso_db = "⚠ No he podido leer la tabla de facturas de la DB. " if db_falla else ""
        if not ingresos and not gastos:
            return {"reply": aviso_db + "No tengo datos económicos aún. Aliméntame: crea "
                             "facturas, apunta gastos («apunta que he pagado 200€ de luz») o "
                             "conéctame a tu base de datos con la skill de datos."}
        if not gastos:
            total = sum(totales.values())
            desglose = ", ".join(f"{estado}: {importe:.2f} €" for estado, importe in totales.items())
            partes = []
            if facturas:
                partes.append(f"{len(facturas)} factura(s) emitida(s) (las últimas 20 como máximo) por "
                              f"{total:.2f} € en total" + (f" ({desglose})" if desglose else ""))
            if ingresos_notas:
                partes.append(f"{len(ingresos_notas)} apunte(s) de ingreso")
            return {"reply": aviso_db + "📊 Tengo " + " y ".join(partes) + " (todo INGRESOS). No tengo "
                             "gastos registrados, así que no puedo decirte dónde recortar. Apunta tus "
                             "gastos («apunta que he pagado 200€ de luz») y lo analizo."}
        # Tope POR LISTA (antes un corte global podía tirar todos los ingresos o todos los gastos).
        envio_gastos = [f"GASTO — {g}" for g in gastos[:_MAX_GASTOS_PROMPT]]
        envio_ingresos = ingresos[:_MAX_INGRESOS_PROMPT]
        alcance = (f"{len(facturas)} factura(s) emitida(s) (ingresos)"
                   + (f", {len(ingresos_notas)} apunte(s) de ingreso" if ingresos_notas else "")
                   + f" y {len(gastos)} apunte(s) de gasto")
        notas = []
        if ignorados:
            notas.append(f"{ignorados} apunte(s) ignorado(s) por no ser claramente un gasto ni un ingreso")
        if len(gastos) > len(envio_gastos) or len(ingresos) > len(envio_ingresos):
            notas.append(f"al modelo le mando {len(envio_gastos)} de {len(gastos)} gastos y "
                         f"{len(envio_ingresos)} de {len(ingresos)} ingresos")
        fijos = (f"Total de gastos con importe: {gasto_total:.2f} € en {con_importe} apunte(s)"
                 + (f"; {len(gastos) - con_importe} sin importe" if len(gastos) > con_importe else "") + ".")
        analysis, prov = await ask_llm(
            "Como asesor financiero de una pyme, analiza estos datos y di: dónde se puede APURAR "
            "(recortar), dónde NO conviene recortar, y 2 acciones concretas esta semana. Cada dato va "
            "etiquetado: INGRESO = dinero que entra (factura emitida a un cliente o cobro; NO se "
            "recorta, solo sirve de contexto) y GASTO = dinero que sale. Recomienda recortes SOLO "
            "sobre los GASTO. Usa SOLO las cifras de abajo, no añadas otras. Sé directo:\n"
            + "\n".join(envio_gastos + envio_ingresos))
        extra = (" (" + "; ".join(notas) + ")") if notas else ""
        if prov == "ninguno":
            return {"reply": aviso_db + f"No pude analizar tus datos (el modelo no está disponible): "
                             f"{analysis}\nDatos que he leído: {alcance}{extra}. {fijos}"}
        cabecera = (f"📊 Análisis sobre {alcance}{extra}"
                    + (" (⚠ la tabla de facturas de la DB no ha respondido, "
                       "van solo los apuntes del grafo)" if db_falla else "") + f". {fijos}\n\n")
        return {"reply": cabecera + analysis}

    if intent == "history":
        files = sorted(REPORTS_DIR.glob("*.md"), key=lambda f: f.stat().st_mtime,
                       reverse=True) if REPORTS_DIR.exists() else []
        if not files:
            return {"reply": "📚 Aún no te he hecho ningún informe. Estrena el archivo: "
                             "«investiga <tema> y hazme un informe»."}
        lines = []
        for f in files[:10]:
            fecha = dt.datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m %H:%M")
            word = " (+Word)" if f.with_suffix(".docx").exists() else ""
            lines.append(f"  • {f.stem}{word} — {fecha}")
        return {"reply": f"📚 Informes generados ({len(files)}), los más recientes:\n"
                         + "\n".join(lines)
                         + "\nDi «abre el informe de <tema>» y te lo reabro."}

    if intent == "open_report":
        which = (match.group("which") or "").strip(" .?!").lower()
        files = sorted(REPORTS_DIR.glob("*.md"), key=lambda f: f.stat().st_mtime,
                       reverse=True) if REPORTS_DIR.exists() else []
        coinciden = [f for f in files if which in f.stem.lower()]
        hit = coinciden[0] if coinciden else None          # el más reciente
        if not hit:
            return {"reply": f"📚 No encuentro ningún informe sobre «{which}». "
                             "Di «mis informes» para ver los que hay, o "
                             f"«investiga {which} y hazme un informe» y lo creo."}
        target = hit.with_suffix(".docx") if hit.with_suffix(".docx").exists() else hit
        otros = ""
        if len(coinciden) > 1:
            otros = (" También coinciden: " + ", ".join(f.stem for f in coinciden[1:4])
                     + (f" y {len(coinciden) - 4} más" if len(coinciden) > 4 else "")
                     + ". Dime el nombre completo para abrir otro.")
        if not _abrir(target):
            return {"reply": f"📚 No pude abrir el navegador ni el editor: el informe «{hit.stem}» "
                             f"está en data/reports/{target.name}.{otros}"}
        return {"reply": f"📚 Reabierto: «{hit.stem}» ({target.name}).{otros}"}

    return {"reply": "Orden de investigación no reconocida."}
