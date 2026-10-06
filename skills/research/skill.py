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


def _save_report(title: str, body_md: str) -> Path:
    """Guarda el informe SIN pisar nunca uno anterior (mismo tema y día -> -2, -3…)."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\- ]", "", title)[:40].strip() or "informe"
    base = f"{safe}-{dt.date.today().isoformat()}"
    out, n = REPORTS_DIR / f"{base}.md", 2
    while out.exists():
        out = REPORTS_DIR / f"{base}-{n}.md"
        n += 1
    out.write_text(f"# {title}\n\n_{dt.datetime.now():%d/%m/%Y %H:%M} — "
                   f"generado por nexus_\n\n{body_md}\n", encoding="utf-8")
    return out


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
        # Las facturas son las EMITIDAS a clientes (billing): dinero que ENTRA. Los apuntes de
        # gasto son lo que SALE. No se mezclan sin etiquetar: recortar sobre ingresos no tiene sentido.
        ingresos, totales = [], {}
        db_falla = False
        if pg.online:
            try:
                rows = pg._rows("SELECT number, concept, amount, status FROM invoices "
                                "ORDER BY id DESC LIMIT 20")
                for r in rows:
                    ingresos.append(f"INGRESO — Factura {r['number']}: {r['concept']} — "
                                    f"{r['amount']}€ ({r['status']})")
                    try:
                        totales[r["status"]] = totales.get(r["status"], 0.0) + float(r["amount"])
                    except (TypeError, ValueError):
                        pass
            except Exception:
                db_falla = True      # tabla ausente o DB caída: se dice, no se calla
        notas = ctx["graph"].search("gasto", 6) + ctx["graph"].search("pago", 6)
        gastos, vistos = [], set()
        for n in notas:
            if n["line"] not in vistos:
                vistos.add(n["line"])
                gastos.append(f"GASTO — {n['line']}")
        aviso_db = "⚠ No he podido leer la tabla de facturas de la DB. " if db_falla else ""
        if not ingresos and not gastos:
            return {"reply": aviso_db + "No tengo datos económicos aún. Aliméntame: crea "
                             "facturas, apunta gastos («apunta que he pagado 200€ de luz») o "
                             "conéctame a tu base de datos con la skill de datos."}
        if not gastos:
            total = sum(totales.values())
            desglose = ", ".join(f"{estado}: {importe:.2f} €" for estado, importe in totales.items())
            return {"reply": aviso_db + f"📊 Tengo {len(ingresos)} factura(s) emitida(s) (las últimas 20 como "
                             f"máximo), es decir INGRESOS: {total:.2f} € en total"
                             + (f" ({desglose})" if desglose else "") + ". No tengo gastos registrados, "
                             "así que no puedo decirte dónde recortar. Apunta tus gastos («apunta que he "
                             "pagado 200€ de luz») y lo analizo."}
        alcance = (f"{len(ingresos)} factura(s) emitida(s) (ingresos) y {len(gastos)} apunte(s) de gasto")
        analysis, prov = await ask_llm(
            "Como asesor financiero de una pyme, analiza estos datos y di: dónde se puede APURAR "
            "(recortar), dónde NO conviene recortar, y 2 acciones concretas esta semana. Cada dato va "
            "etiquetado: INGRESO = factura emitida a un cliente (dinero que entra; NO se recorta, "
            "solo sirve de contexto) y GASTO = dinero que sale. Recomienda recortes SOLO sobre los "
            "GASTO. Usa SOLO las cifras de abajo, no añadas otras. Sé directo:\n"
            + "\n".join((gastos + ingresos)[:30]))
        if prov == "ninguno":
            return {"reply": aviso_db + f"No pude analizar tus datos (el modelo no está disponible): "
                             f"{analysis}\nDatos que he leído: {alcance}."}
        cabecera = (f"📊 Análisis sobre {alcance}"
                    + (" (⚠ la tabla de facturas de la DB no ha respondido, "
                       "van solo los apuntes del grafo)" if db_falla else "") + ":\n\n")
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
