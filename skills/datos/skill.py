"""Minion Datos — BDs externas (SQL/NoSQL), analítica GA4-style y dashboards."""
from __future__ import annotations

import datetime as dt
import json
import re
import webbrowser
from pathlib import Path

REPORTS_DIR = Path(__file__).resolve().parents[2] / "data" / "reports"

SKILL = {
    "name": "Datos / Analítica",
    "description": "Conecta BDs externas (Postgres/MySQL/SQLite/Mongo), consulta en solo lectura y genera dashboards oscuros estilo Power BI (Chart.js)",
    "patterns": {
        "connect": r"con[eé]cta(?:te|me)?\s+a\s+la\s+(?:base\s+de\s+datos|bd)\s+(?P<url>\S+)",
        "disconnect": r"descon[eé]cta(?:te|me)?\s+(?:de\s+)?la\s+(?:base\s+de\s+datos|bd)",
        "which": r"qu[eé]\s+(?:base\s+de\s+datos|bd)\s+(?:est[aá]\s+conectada|tienes|hay\s+conectada)|"
                 r"a\s+qu[eé]\s+(?:base\s+de\s+datos|bd)\s+est[aá]s\s+conectad[oa]",
        "tables": r"qu[eé]\s+tablas\s+(?:hay|tiene|tengo)|"
                  r"(?:l[ií]sta(?:me)?|mu[eé]stra(?:me)?|ens[eé][ñn]a(?:me)?|d[aá]me)\s+(?:las\s+)?tablas|"
                  r"qu[eé]\s+colecciones\s+hay",
        "query": r"(?:consulta|query|ejecuta)[:,]\s*(?P<sql>.+)",
        "profile": r"informe\s+anal[ií]tico\s+de\s+(?:la\s+tabla\s+)?(?P<table>[\w.]+)",
        "dashboard": r"(?:dashboard|panel|cuadro\s+de\s+mando)\s+de\s+(?:la\s+tabla\s+)?(?P<table>[\w.]+)",
        "chart": r"gr[aá]fic[oa]\s+de[:,]?\s+(?P<sql>select\s+.+)",
    },
}

_conn = {"url": None, "kind": None, "handle": None}
FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|truncate|alter|create|grant)\b", re.I)


# ----------------------------------------------------------------------
#  Conexión multi-motor
# ----------------------------------------------------------------------
def _connect(url: str):
    if url.startswith(("postgresql://", "postgres://")):
        import psycopg2
        conn = psycopg2.connect(url, connect_timeout=5)
        conn.autocommit = True
        return "postgres", conn
    if url.startswith("mysql://"):
        try:
            import pymysql
        except ImportError:
            raise RuntimeError("Falta pymysql (pip install pymysql)")
        m = re.match(r"mysql://(?:(?P<u>[^:@]+)(?::(?P<p>[^@]*))?@)?(?P<h>[^:/]+)"
                     r"(?::(?P<port>\d+))?/(?P<db>\w+)", url)
        return "mysql", pymysql.connect(
            host=m["h"], port=int(m["port"] or 3306), user=m["u"] or "root",
            password=m["p"] or "", database=m["db"], connect_timeout=5)
    if url.startswith("sqlite://"):
        import sqlite3
        path = url.replace("sqlite://", "", 1)
        return "sqlite", sqlite3.connect(path, check_same_thread=False)
    if url.startswith("mongodb://") or url.startswith("mongodb+srv://"):
        try:
            from pymongo import MongoClient
        except ImportError:
            raise RuntimeError("Falta pymongo (pip install pymongo)")
        return "mongo", MongoClient(url, serverSelectionTimeoutMS=5000)
    raise RuntimeError("Esquema no soportado (usa postgresql://, mysql://, "
                       "sqlite://ruta, mongodb://)")


def _sql(query: str, limit: int = 50) -> tuple[list[str], list[tuple]]:
    kind, h = _conn["kind"], _conn["handle"]
    cur = h.cursor()
    cur.execute(query)
    cols = [d[0] for d in cur.description] if cur.description else []
    rows = cur.fetchmany(limit) if cur.description else []
    if kind != "sqlite":
        try:
            cur.close()
        except Exception:
            pass
    return cols, rows


def _tables() -> list[str]:
    kind = _conn["kind"]
    if kind == "postgres":
        _c, rows = _sql("SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema='public' ORDER BY 1", 200)
        return [r[0] for r in rows]
    if kind == "mysql":
        _c, rows = _sql("SHOW TABLES", 200)
        return [r[0] for r in rows]
    if kind == "sqlite":
        _c, rows = _sql("SELECT name FROM sqlite_master WHERE type='table'", 200)
        return [r[0] for r in rows]
    if kind == "mongo":
        db = _conn["handle"].get_default_database()
        return db.list_collection_names()
    return []


# ----------------------------------------------------------------------
#  Dashboard HTML oscuro estilo Power BI (Chart.js)
# ----------------------------------------------------------------------
DASH_TMPL = """<!doctype html><html lang="es"><meta charset="utf-8">
<title>{title} — nexus Analytics</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
 body{{background:#0d1117;color:#e6edf3;font-family:'Segoe UI',sans-serif;margin:0;padding:24px}}
 h1{{color:#00ff9c;font-size:22px;letter-spacing:1px}} .sub{{color:#8b949e;font-size:12px}}
 .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px;margin-top:18px}}
 .card{{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:16px}}
 .kpi{{font-size:34px;font-weight:700;color:#00ff9c}} .kpi-label{{color:#8b949e;font-size:12px}}
 canvas{{max-height:260px}}
</style>
<h1>▚ {title}</h1><div class="sub">Generado por nexus — {date}</div>
<div class="grid">{kpis}{charts}</div>
<script>
Chart.defaults.color='#8b949e';Chart.defaults.borderColor='#30363d';
const PALETTE=['#00ff9c','#4dd8ff','#ff4ddb','#ffd23e','#ff8c42','#b07dff','#59ff59','#ff5e5e'];
{scripts}
</script></html>"""


def _dash_card(idx: int, kind: str, title: str, labels: list, values: list) -> tuple[str, str]:
    html_part = f'<div class="card"><b>{title}</b><canvas id="c{idx}"></canvas></div>'
    script = f"""
new Chart(document.getElementById('c{idx}'), {{
  type: '{kind}',
  data: {{ labels: {json.dumps(labels[:20], default=str)},
    datasets: [{{ label: '{title}', data: {json.dumps(values[:20], default=str)},
      backgroundColor: PALETTE, borderColor: '#00ff9c',
      fill: {'true' if kind == 'line' else 'false'}, tension: 0.3 }}] }},
  options: {{ plugins: {{ legend: {{ display: {'true' if kind == 'doughnut' else 'false'} }} }} }}
}});"""
    return html_part, script


def _build_dashboard(title: str, kpis: list[tuple[str, str]],
                     cards: list[tuple[str, str, list, list]]) -> Path:
    kpi_html = "".join(f'<div class="card"><div class="kpi">{v}</div>'
                       f'<div class="kpi-label">{k}</div></div>' for k, v in kpis)
    charts_html, scripts = "", ""
    for i, (kind, ctitle, labels, values) in enumerate(cards):
        h, s = _dash_card(i, kind, ctitle, labels, values)
        charts_html += h
        scripts += s
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    safe_title = re.sub(r"[^\w]", "_", title)[:30]
    out = REPORTS_DIR / f"dash-{safe_title}-{dt.datetime.now():%H%M%S}.html"
    out.write_text(DASH_TMPL.format(title=title, date=f"{dt.datetime.now():%d/%m/%Y %H:%M}",
                                    kpis=kpi_html, charts=charts_html, scripts=scripts),
                   encoding="utf-8")
    try:
        webbrowser.open(out.as_uri())
    except Exception:
        pass
    return out


MUESTRA = 200          # filas que se leen para perfilar columnas


def _profile_table(table: str) -> tuple[list[tuple[str, str]], list[tuple], str]:
    """KPIs + tarjetas de gráficos para una tabla SQL (perfil estilo GA4).

    Solo el recuento de filas es de la tabla entera; los repartos por columna
    salen de las primeras `MUESTRA` filas. Cuando la tabla es mayor, cada
    etiqueta lo dice: un «Top país» calculado sobre 200 de 4 millones de filas
    presentado como si fuera el total es un dato falso."""
    if not re.fullmatch(r"[\w.]+", table):
        raise RuntimeError("Nombre de tabla no válido")
    _c, rows = _sql(f"SELECT COUNT(*) FROM {table}")
    total = rows[0][0]
    cols, sample = _sql(f"SELECT * FROM {table} LIMIT {MUESTRA}", MUESTRA)
    parcial = total > len(sample)
    marca = f" (muestra de {len(sample):,})" if parcial else ""
    kpis = [("Filas totales", f"{total:,}"), ("Columnas", str(len(cols)))]
    cards = []
    # columnas categóricas → top valores (barras/donut); fechas → evolución (línea)
    for i, col in enumerate(cols[:8]):
        values = [r[i] for r in sample if r[i] is not None]
        if not values:
            continue
        first = values[0]
        if isinstance(first, (dt.date, dt.datetime)):
            counts: dict = {}
            for v in values:
                key = v.strftime("%Y-%m")
                counts[key] = counts.get(key, 0) + 1
            items = sorted(counts.items())
            cards.append(("line", f"Evolución por {col}{marca}",
                          [k for k, _ in items], [c for _, c in items]))
        elif isinstance(first, (int, float)) and len(set(values)) > 10:
            etiqueta = f"Σ {col}" + (f" en {len(values):,} filas" if parcial else "")
            kpis.append((etiqueta, f"{sum(values):,.0f}"))
        else:
            counts = {}
            for v in values:
                counts[str(v)[:24]] = counts.get(str(v)[:24], 0) + 1
            items = sorted(counts.items(), key=lambda x: -x[1])[:8]
            kind = "doughnut" if len(items) <= 5 else "bar"
            cards.append((kind, f"Top {col}{marca}",
                          [k for k, _ in items], [c for _, c in items]))
        if len(cards) >= 5:
            break
    resumen = f"{total:,} filas, {len(cols)} columnas"
    if parcial:
        resumen += f"; los gráficos salen de una muestra de {len(sample):,} filas"
    return kpis, cards, resumen


# ----------------------------------------------------------------------
async def handle(intent: str, text: str, match, ctx) -> dict:
    if intent == "connect":
        url = match.group("url").strip()
        try:
            kind, handle = _connect(url)
        except Exception as exc:
            return {"reply": f"No he podido conectar: {exc}"}
        _conn.update({"url": url, "kind": kind, "handle": handle})
        safe_url = re.sub(r":[^:@/]+@", ":****@", url)
        return {"reply": f"Conectado a {kind.upper()} ({safe_url}). "
                         "Pídeme «qué tablas hay» o «dashboard de la tabla X»."}

    if intent == "disconnect":
        _conn.update({"url": None, "kind": None, "handle": None})
        return {"reply": "Base de datos externa desconectada."}

    if intent == "which":
        if not _conn["url"]:
            return {"reply": "Ninguna BD externa conectada (la memoria interna pgvector "
                             "va por su lado). Conéctame: «conéctate a la base de datos <url>»."}
        return {"reply": f"Conectado a {_conn['kind'].upper()}: "
                         f"{re.sub(r':[^:@/]+@', ':****@', _conn['url'])}"}

    if not _conn["handle"]:
        return {"reply": "Primero conéctame a una base de datos: "
                         "«conéctate a la base de datos postgresql://user:pass@host/db» "
                         "(también mysql://, sqlite://ruta, mongodb://)."}

    try:
        if intent == "tables":
            tables = _tables()
            return {"reply": f"{len(tables)} tablas/colecciones: " + " · ".join(tables[:30])}

        if intent == "query":
            sql = match.group("sql").strip().rstrip(";")
            if FORBIDDEN.search(sql):
                return {"reply": "Solo lectura: esa consulta modifica datos y la rechazo "
                                 "por seguridad."}
            if _conn["kind"] == "mongo":
                return {"reply": "Para Mongo usa «informe analítico de <colección>» "
                                 "(las consultas SQL no aplican)."}
            cols, rows = _sql(sql)
            head = " | ".join(cols)
            body = "\n".join(" | ".join(str(c)[:28] for c in r) for r in rows[:12])
            return {"reply": f"{len(rows)} filas:\n{head}\n{body}"}

        if intent in ("profile", "dashboard"):
            table = match.group("table")
            if _conn["kind"] == "mongo":
                db = _conn["handle"].get_default_database()
                coll = db[table]
                total = coll.estimated_document_count()
                sample = list(coll.find().limit(100))
                fields: dict = {}
                for doc in sample:
                    for k in doc:
                        fields[k] = fields.get(k, 0) + 1
                items = sorted(fields.items(), key=lambda x: -x[1])[:8]
                out = _build_dashboard(f"{table} (Mongo)",
                                       [("Documentos", f"{total:,}"),
                                        ("Campos", str(len(fields)))],
                                       [("bar", "Presencia de campos",
                                         [k for k, _ in items], [v for _, v in items])])
                return {"reply": f"Dashboard de «{table}» generado y abierto en el navegador "
                                 f"({total:,} documentos). Archivo: data/reports/{out.name}"}
            kpis, cards, summary = _profile_table(table)
            out = _build_dashboard(table, kpis, cards)
            from backend.core.llm import ask_llm
            insight, _ = await ask_llm(
                f"Datos de la tabla «{table}»: {summary}. KPIs medidos: {kpis}. "
                "Da 2 observaciones en 2 frases usando SOLO esas cifras. "
                "No inventes métricas, porcentajes, tendencias ni comparaciones "
                "que no estén ahí; si esos datos no dan para una observación "
                "útil, dilo y propón qué consulta haría falta.")
            return {"reply": f"Dashboard de «{table}» abierto en el navegador "
                             f"({summary}). {insight}\nArchivo: data/reports/{out.name}"}

        if intent == "chart":
            sql = match.group("sql").strip().rstrip(";")
            if FORBIDDEN.search(sql):
                return {"reply": "Solo lectura: consulta rechazada."}
            cols, rows = _sql(sql)
            if not rows or len(cols) < 2:
                return {"reply": "La consulta debe devolver al menos 2 columnas "
                                 "(etiqueta, valor) y alguna fila."}
            labels = [str(r[0])[:24] for r in rows]
            values = [float(r[1]) if r[1] is not None else 0 for r in rows]
            kind = "line" if len(rows) > 12 else "bar"
            out = _build_dashboard("Consulta", [("Filas", str(len(rows)))],
                                   [(kind, f"{cols[1]} por {cols[0]}", labels, values)])
            return {"reply": f"Gráfico generado y abierto en el navegador "
                             f"(data/reports/{out.name})."}

    except Exception as exc:
        return {"reply": f"Error de datos: {type(exc).__name__}: {exc}"}

    return {"reply": "Orden de datos no reconocida."}
