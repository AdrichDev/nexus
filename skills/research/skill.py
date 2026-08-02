"""Minion Investigación — informes web con fuentes y análisis económico."""
from __future__ import annotations

import datetime as dt
import re
import webbrowser
from pathlib import Path


REPORTS_DIR = Path(__file__).resolve().parents[2] / "data" / "reports"

SKILL = {
    "name": "Investigación",
    "description": "Investiga en la web (DuckDuckGo, sin API key), redacta informes con fuentes citadas y analiza tus gastos/facturas",
    "patterns": {
        "research": r"(?:investiga(?:me)?|indaga|documenta(?:me)?)\s+(?:sobre\s+)?(?P<topic>.+?)"
                    r"(?:\s+y\s+(?:hazme|haz|escr[ií]beme|red[aá]ctame|prep[aá]rame)\s+(?:un\s+)?informe)?$"
                    r"|(?:hazme|red[aá]ctame|escr[ií]beme|prep[aá]rame)\s+(?:un\s+)?informe\s+(?:sobre|de)\s+(?P<topic2>.+)",
        "trends": r"tendencias\s+(?:de|en|del|sobre)\s+(?P<topic>.+)|qu[eé]\s+se\s+lleva\s+(?:ahora\s+)?en\s+(?P<topic2>.+)",
        "economy": r"informe\s+econ[oó]mico|d[oó]nde\s+(?:puedo|podr[ií]a)\s+(?:apurar|recortar|ahorrar|optimizar)"
                   r"|optimiza(?:me)?\s+(?:mis\s+)?gastos|an[aá]lisis\s+(?:de\s+)?(?:mis\s+)?(?:gastos|finanzas)|"
                   r"c[oó]mo\s+(?:van|est[aá]n)\s+mis\s+(?:gastos|finanzas|cuentas)",
        # Histórico de informes generados (v19). «abre el informe de X» reabre uno.
        "open_report": r"(?:abre(?:me)?|re[aá]bre(?:me)?|ens[eé][ñn]ame|mu[eé]strame)\s+"
                       r"(?:el\s+|otra\s+vez\s+el\s+)?informe\s+(?:de|sobre|del)\s+(?P<which>.+)",
        "history": r"(?:qu[eé]|cu[aá]ntos)\s+informes\s+(?:tienes|hay|me\s+has\s+hecho|tengo|llevas)"
                   r"|(?:lista|ver|mu[eé]strame|ens[eé][ñn]ame)\s+(?:de\s+|los\s+|mis\s+)?informes"
                   r"|\bmis\s+informes\b|historial\s+de\s+informes",
    },
}

# v19: la búsqueda y la lectura de páginas usan el MOTOR CENTRAL de nexus
# (backend/core/websearch.py): multi-fuente (Google News RSS + DDG Lite + DDG
# HTML), caché con TTL y extracción de contenido real. Se acabó el scraping
# duplicado y frágil que teníamos aquí.

async def _ddg_search(query: str, n: int = 6) -> list[dict]:
    from backend.core import websearch
    return await websearch.search(query, n)


async def _fetch_text(url: str, limit: int = 4000) -> str:
    from backend.core import websearch
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


def _save_report(title: str, body_md: str) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\- ]", "", title)[:40].strip() or "informe"
    out = REPORTS_DIR / f"{safe}-{dt.date.today().isoformat()}.md"
    out.write_text(f"# {title}\n\n_{dt.datetime.now():%d/%m/%Y %H:%M} — "
                   f"generado por nexus_\n\n{body_md}\n", encoding="utf-8")
    return out


async def _full_report(topic: str, angle: str) -> dict:
    from backend.core.llm import ask_llm
    results = await _ddg_search(f"{topic} 2026", 6)
    sources_txt, cited = "", []
    for res in results[:4]:
        content = await _fetch_text(res["url"])
        if content:
            cited.append(res)
            sources_txt += f"\n\n--- FUENTE: {res['title']} ({res['url']}) ---\n{content[:2500]}"
    if not sources_txt:
        reply, _ = await ask_llm(
            f"{angle} sobre «{topic}». No hay fuentes web disponibles ahora mismo: "
            "usa tu conocimiento general y dilo claramente al principio.")
        return {"reply": reply[:1200], "sources": []}
    report, _ = await ask_llm(
        f"{angle} sobre «{topic}» usando SOLO estas fuentes. Estructura: "
        "**Resumen ejecutivo** (3 frases), **Hallazgos clave** (4-6 puntos con datos), "
        "**Oportunidades** (2-3), **Recomendación**. Cita las fuentes por título.\n"
        f"{sources_txt[:9000]}")
    src_md = "\n".join(f"- [{s['title']}]({s['url']})" for s in cited)
    path = _save_report(topic, report + "\n\n## Fuentes\n" + src_md)
    docx_path = path.with_suffix(".docx")
    full_md = (f"# {topic}\n\n_{dt.datetime.now():%d/%m/%Y %H:%M} — generado por nexus_\n\n"
               + report + "\n\n## Fuentes\n" + src_md)
    has_docx = md_to_docx(full_md, docx_path)
    try:
        webbrowser.open(path.as_uri())
    except Exception:
        pass
    extra = f" + Word ({docx_path.name})" if has_docx else ""
    return {"reply": f"Informe sobre «{topic}» generado con {len(cited)} fuentes "
                     f"(data/reports/{path.name}{extra}, abierto en tu editor/navegador). "
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
        from backend.core.llm import ask_llm
        pg = ctx["pg"]
        facts = []
        if pg.online:
            rows = pg._rows("SELECT number, concept, amount, status FROM invoices "
                            "ORDER BY id DESC LIMIT 20")
            facts += [f"Factura {r['number']}: {r['concept']} — {r['amount']}€ ({r['status']})"
                      for r in rows]
        notes = ctx["graph"].search("gasto", 6) + ctx["graph"].search("pago", 6)
        facts += [n["line"] for n in notes]
        if not facts:
            return {"reply": "No tengo datos económicos aún. Aliméntame: crea facturas, "
                             "apunta gastos («apunta que he pagado 200€ de luz») o "
                             "conéctame a tu base de datos con la skill de datos."}
        analysis, _ = await ask_llm(
            "Como asesor financiero de una pyme, analiza estos datos y di: dónde se "
            "puede APURAR (recortar), dónde NO conviene recortar, y 2 acciones "
            "concretas esta semana. Sé directo:\n" + "\n".join(facts[:30]))
        return {"reply": analysis}

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
        hit = next((f for f in files if which in f.stem.lower()), None)
        if not hit:
            return {"reply": f"📚 No encuentro ningún informe sobre «{which}». "
                             "Di «mis informes» para ver los que hay, o "
                             f"«investiga {which} y hazme un informe» y lo creo."}
        target = hit.with_suffix(".docx") if hit.with_suffix(".docx").exists() else hit
        try:
            webbrowser.open(target.as_uri())
        except Exception:
            pass
        return {"reply": f"📚 Reabierto: «{hit.stem}» ({target.name})."}

    return {"reply": "Orden de investigación no reconocida."}
