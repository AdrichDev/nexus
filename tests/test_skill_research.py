# -*- coding: utf-8 -*-
"""Skill INVESTIGACION (research) — activacion, fronteras, cero scraping.

Sin red y sin LLM: la busqueda y el modelo se sustituyen por dobles, y el
histórico se lee de un directorio temporal.
"""
import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_fail = []
_pass = 0


def check(c, m):
    global _pass
    if c:
        _pass += 1
    else:
        _fail.append(m)
        print("  FALLO:", m)


class PgDoble:
    def __init__(self, online=False, revienta=False):
        self.online = online
        self.revienta = revienta

    def _rows(self, sql):
        if self.revienta:
            raise RuntimeError('relation "invoices" does not exist')
        return []


class GrafoDoble:
    def __init__(self, hits=None):
        self.hits = hits or []

    def search(self, q, n=4):
        return list(self.hits)


def main():
    from backend.core import skills_loader as sl
    sl.load_skills()

    print("· la skill carga con el cargador REAL")
    sk = sl.get_skills().get("research")
    check(sk is not None and sk.status != "error",
          "research carga sin error: " + (sk.description if sk else "no existe"))
    mod = sk.module

    print("· cada intent se activa con frases naturales")
    esperado = {
        "research": ["investiga el mercado del cafe", "investigame el mercado del cafe",
                     "investiga sobre la energia solar y hazme un informe",
                     "indaga sobre los precios del acero",
                     "documentame sobre la ley de ia",
                     "hazme un informe sobre el mercado del pan",
                     "redactame un informe de la competencia",
                     "escribeme un informe sobre los drones",
                     "preparame un informe sobre el turismo"],
        "trends": ["tendencias de moda", "tendencias en marketing",
                   "que se lleva ahora en zapatillas"],
        "economy": ["informe economico", "donde puedo apurar",
                    "donde puedo recortar gastos", "optimiza mis gastos",
                    "optimizame los gastos", "optimiza el gasto",
                    "analisis de mis gastos", "analisis de los gastos",
                    "como van mis gastos", "como estan mis finanzas"],
        "history": ["mis informes", "que informes tienes", "cuantos informes me has hecho",
                    "lista de informes", "muestrame los informes", "historial de informes"],
        "open_report": ["abre el informe de moda", "abreme el informe del cafe",
                        "reabre el informe de drones", "enseñame el informe de moda"],
    }
    for intent, frases in esperado.items():
        for f in frases:
            r = sl.route(f)
            check(bool(r) and r[0].folder == "research" and r[1] == intent,
                  f"«{f}» -> research/{intent}"
                  + (f" (se la queda {r[0].folder}/{r[1]})" if r else " (no casa: al cerebro)"))

    print("· fronteras: no roba a hermes ni a ai_media")
    ajenas = {
        "dile a hermes: investiga esto": "hermes",
        "dile a hermes que investigue el mercado": "hermes",
        "hermes, investiga la competencia": "hermes",
        "busca en internet el precio del oro": "ai_media",
    }
    for f, dueno in ajenas.items():
        r = sl.route(f)
        check(bool(r) and r[0].folder == dueno,
              f"«{f}» es de {dueno}" + (f" (la coge {r[0].folder})" if r else " (no casa)"))
        check(not (r and r[0].folder == "research"), f"«{f}» NO cae en research")

    print("· NADA de scraping propio: solo el motor central")
    src = (ROOT / "skills" / "research" / "skill.py").read_text(encoding="utf-8")
    check("websearch" in src, "usa backend.core.websearch")
    for lib in ("BeautifulSoup", "selenium", "playwright", "lxml.html",
                "httpx.get", "requests.get", "urlopen"):
        check(lib not in src, f"no usa {lib} por su cuenta")
    check("instagram.com" not in src and "tiktok.com" not in src,
          "no toca redes sociales directamente")

    print("· sin fuentes NO se inventa un informe ni se guarda en el historico")
    async def _sin_fuentes(q, n=6):
        return []

    async def _llm_falso(prompt):
        return ("Segun mi conocimiento general el mercado crece.", None)

    orig_search, orig_fetch = mod._ddg_search, mod._fetch_text
    import backend.core.llm as _llm
    orig_ask = _llm.ask_llm
    tmpdir = Path(tempfile.mkdtemp())
    orig_reports = mod.REPORTS_DIR
    try:
        mod.REPORTS_DIR = tmpdir
        mod._ddg_search = _sin_fuentes
        _llm.ask_llm = _llm_falso
        out = asyncio.run(mod._full_report("mercado del cafe", "Redacta"))
        check("No he podido leer NINGUNA fuente" in out["reply"],
              f"lo dice en la primera linea: {out['reply'][:90]}")
        check("no lo guardo como informe" in out["reply"], "y avisa de que no lo archiva")
        check(out["sources"] == [], "cero fuentes citadas")
        check(not list(tmpdir.glob("*.md")),
              "y efectivamente NO ha dejado un informe falso en el historico")

        print("· el historico vacio se dice, no se rellena")
        h = asyncio.run(mod.handle("history", "mis informes",
                                   sl.route("mis informes")[2], {"pg": PgDoble()}))
        check("Aún no te he hecho ningún informe" in h["reply"], "historico vacio, honesto")

        print("· «abre el informe de X» que no existe no abre otro cualquiera")
        (tmpdir / "moda-2026-01-01.md").write_text("# moda", encoding="utf-8")
        f = "abre el informe de zzzz"
        o = asyncio.run(mod.handle("open_report", f, sl.route(f)[2], {"pg": PgDoble()}))
        check("No encuentro ningún informe" in o["reply"],
              f"dice que no lo tiene: {o['reply'][:80]}")

        print("· el historico lista lo que hay DE VERDAD")
        h2 = asyncio.run(mod.handle("history", "mis informes",
                                    sl.route("mis informes")[2], {"pg": PgDoble()}))
        check("moda-2026-01-01" in h2["reply"] and "(1)" in h2["reply"],
              f"un informe, uno contado: {h2['reply'][:120]}")
    finally:
        mod._ddg_search, mod._fetch_text = orig_search, orig_fetch
        mod.REPORTS_DIR = orig_reports
        _llm.ask_llm = orig_ask

    print("· economico: sin datos no se inventan cifras")
    e = asyncio.run(mod.handle("economy", "informe economico",
                               sl.route("informe economico")[2],
                               {"pg": PgDoble(), "graph": GrafoDoble()}))
    check("No tengo datos económicos" in e["reply"], "lo dice claro")

    print("· economico: si la DB falla se avisa, no se calla")
    e2 = asyncio.run(mod.handle("economy", "informe economico",
                                sl.route("informe economico")[2],
                                {"pg": PgDoble(online=True, revienta=True),
                                 "graph": GrafoDoble()}))
    check("no he podido leer la tabla de facturas" in e2["reply"].lower(),
          f"avisa del fallo de la DB: {e2['reply'][:110]}")
    check("Traceback" not in e2["reply"], "y no escupe un traceback")

    print("· md_to_docx sin python-docx devuelve False, no miente")
    ok = mod.md_to_docx("# hola", tmpdir / "x.docx")
    check(ok in (True, False), "devuelve un booleano honesto")
    if not ok:
        check(not (tmpdir / "x.docx").exists(), "si dice False, no ha dejado un docx a medias")

    print("· intent desconocido no revienta")
    r = asyncio.run(mod.handle("inexistente", "loquesea", None, {"pg": PgDoble()}))
    check("no reconocida" in r["reply"].lower(), "responde sin traceback")

    print("· es agnostica")
    doc = (ROOT / "skills" / "research" / "SKILL.md").read_text(encoding="utf-8")
    for prohibido in ("Adri", "achoz", "D:\\Adrian", "C:\\Users\\"):
        check(prohibido not in src, f"skill.py no lleva «{prohibido}»")
        check(prohibido not in doc, f"SKILL.md no lleva «{prohibido}»")

    print("· el SKILL.md documenta el historico y la regla de no scraping")
    for trozo in ("mis informes", "abre el informe", "Qué necesita configurado",
                  "Qué NO hace", "No hace scraping"):
        check(trozo in doc, f"SKILL.md menciona «{trozo}»")

    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
