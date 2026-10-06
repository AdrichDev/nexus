# -*- coding: utf-8 -*-
"""research: informes honestos, ningún informe pisado y fuentes reales.

Encontrado leyendo skills/research/skill.py:
  * sin modelo (proveedor «ninguno») el mensaje de error se guardaba como informe y entraba en el histórico;
  * «abierto en tu editor/navegador» sin comprobar que se abrió;
  * el informe se llamaba `tema-fecha.md`: un segundo informe del mismo tema el mismo día PISABA el primero;
  * lee las páginas una tras otra, y los anuncios del buscador ocupaban esas lecturas y se citaban como fuentes;
  * `abre el informe de X` abría la primera coincidencia parcial sin avisar de que había más;
  * el informe económico trataba las facturas EMITIDAS (ingresos) como gastos, sin distinguirlas.

Todo simulado (búsqueda, páginas, modelo, navegador); informes en un directorio temporal. Nivel M.
Ejecutar: python tests/unit/skills/research/test_research_honesty.py
"""
import asyncio
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from backend.core.aplicacion import skills_loader as sl  # noqa: E402
import backend.core.infraestructura.llm as llm  # noqa: E402
import backend.core.infraestructura.websearch as websearch  # noqa: E402

sl.load_skills()
research = sl.get_skills()["research"].module

_fail, _pass = [], 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


TMP = Path(tempfile.mkdtemp(prefix="nexus_research_test_"))
research.REPORTS_DIR = TMP / "reports"

BUENOS = [{"title": f"Fuente {i}", "url": f"https://f{i}.example/p", "snippet": f"fragmento {i}"} for i in range(1, 7)]
PAGINAS = {r["url"]: f"TEXTO-DE-LA-PAGINA-{i}" for i, r in enumerate(BUENOS, 1)}
ANUNCIOS = [{"title": "Compra mqtt en Amazon - Ahorra", "url": "https://duckduckgo.com/y.js?ad_domain=amazon.es", "snippet": "anuncio"},
            {"title": "more info", "url": "https://duckduckgo.com/y.js?x=1", "snippet": ""}]

estado = {"resultados": BUENOS, "paginas": PAGINAS, "retraso": 0.0, "modelo": "ok", "texto": "INFORME-GENERADO",
          "prompts": [], "pedidas": [], "abre": True, "abiertas": []}


async def _buscar(q, n=6, news=None):
    return [dict(r) for r in estado["resultados"]]


async def _pagina(url, max_chars=3500):
    estado["pedidas"].append(url)
    if estado["retraso"]:
        await asyncio.sleep(estado["retraso"])
    return estado["paginas"].get(url, "")[:max_chars]


async def _ask(texto, *a, **k):
    estado["prompts"].append(texto)
    if estado["modelo"] == "ninguno":
        return "Ollama no está en marcha, así que no puedo cargar ningún modelo local.", "ninguno"
    return estado["texto"], "ollama"


def _abrir(url, *a, **k):
    estado["abiertas"].append(url)
    return estado["abre"]


def reset(**cambios):
    estado.update(resultados=BUENOS, paginas=PAGINAS, retraso=0.0, modelo="ok", texto="INFORME-GENERADO",
                  prompts=[], pedidas=[], abre=True, abiertas=[])
    estado.update(cambios)
    for f in research.REPORTS_DIR.glob("*") if research.REPORTS_DIR.exists() else []:
        f.unlink()


def correr(frase, ctx=None):
    r = sl.route(frase)
    assert r and r[0].folder == "research", f"«{frase}» no llega a research: {r and (r[0].folder, r[1])}"
    return asyncio.run(r[0].module.handle(r[1], frase, r[2], ctx or {}))


def informes():
    return sorted(research.REPORTS_DIR.glob("*.md")) if research.REPORTS_DIR.exists() else []


orig = (websearch.search, websearch.fetch_page, llm.ask_llm, webbrowser.open)
websearch.search, websearch.fetch_page, llm.ask_llm, webbrowser.open = _buscar, _pagina, _ask, _abrir
try:
    # ---- 1) sin modelo no hay informe ---------------------------------------------------------
    reset()
    res = correr("investiga el protocolo MQTT y hazme un informe")
    check(len(informes()) == 1 and "INFORME-GENERADO" in informes()[0].read_text(encoding="utf-8"),
          "base: con modelo se guarda el informe")
    historial = correr("mis informes")["reply"]
    check("Informes generados (1)" in historial and "protocolo MQTT" in historial,
          "base: el histórico lista EL informe recién creado (1 informe, con su tema)")

    reset(modelo="ninguno")
    res = correr("investiga el protocolo MQTT y hazme un informe")
    check(not informes(), "sin modelo: NO se guarda ningún informe (ni el error como si lo fuera)")
    check("no pude redactar" in res["reply"].lower() and "Fuente 1" in res["reply"] and "https://f1.example/p" in res["reply"],
          "sin modelo: dice que no pudo redactar y enseña las fuentes que SÍ leyó")
    check("Informe sobre" not in res["reply"] and "generado con" not in res["reply"],
          "sin modelo: no presenta nada como «informe generado»")
    check("Aún no te he hecho ningún informe" in correr("mis informes")["reply"], "sin modelo: el histórico sigue vacío")

    reset(modelo="ninguno", resultados=[], paginas={})
    res = correr("investiga el protocolo MQTT")
    check("conocimiento general" not in res["reply"] and "el modelo no está disponible" in res["reply"],
          "sin fuentes y sin modelo: lo dice, sin fingir conocimiento del modelo")
    check(not informes(), "sin fuentes y sin modelo: no guarda nada")

    reset(resultados=[], paginas={})
    res = correr("investiga el protocolo MQTT")
    check("NO está contrastado" in res["reply"] and not informes(), "sin fuentes pero con modelo: sigue avisando y sin guardar")

    # ---- 2) navegador honesto -----------------------------------------------------------------
    reset(abre=False)
    res = correr("investiga el protocolo MQTT y hazme un informe")
    check("abierto en tu editor" not in res["reply"] and "no pude abrir" in res["reply"].lower() and "data/reports/" in res["reply"],
          "navegador: si no se abrió, no dice «abierto» y da la ruta")
    res = correr("abre el informe de mqtt")
    check("no pude abrir" in res["reply"].lower() and "Reabierto" not in res["reply"], "navegador: reabrir sin navegador lo dice")
    reset(abre=True)
    res = correr("investiga el protocolo MQTT y hazme un informe")
    check("abierto" in res["reply"].lower(), "navegador: con navegador sigue diciendo que está abierto")

    # ---- 3) ningún informe se pisa ---------------------------------------------------------------
    reset(texto="PRIMERA-VERSION")
    correr("investiga el protocolo MQTT y hazme un informe")
    estado["texto"] = "SEGUNDA-VERSION"
    correr("investiga el protocolo MQTT y hazme un informe")
    textos = [f.read_text(encoding="utf-8") for f in informes()]
    check(len(textos) == 2, f"nombres: dos informes del mismo tema el mismo día son DOS archivos (hay {len(textos)})")
    check(any("PRIMERA-VERSION" in t for t in textos) and any("SEGUNDA-VERSION" in t for t in textos),
          "nombres: el primer informe sigue intacto")

    # ---- 3b) guardado atómico y nombres seguros ------------------------------------------------------
    reset()
    orig_exists = Path.exists
    Path.exists = lambda self, *a, **k: False if self.suffix == ".md" else orig_exists(self, *a, **k)   # simula la carrera
    try:
        a = research._save_report("Tema de la carrera", "UNO")
        b = research._save_report("Tema de la carrera", "DOS")
    finally:
        Path.exists = orig_exists
    check(a != b and a.read_text(encoding="utf-8").count("UNO") == 1 and "DOS" in b.read_text(encoding="utf-8"),
          "guardado: aunque `exists()` mienta (otra petición a la vez), la creación es exclusiva y no pisa")
    for titulo in ("CON", "nul", "com1", "  ...  ", "tema. "):
        ruta = research._save_report(titulo, "x")
        nombre = ruta.stem.split("-")[0].lower()
        check(nombre not in {"con", "prn", "aux", "nul", "com1", "lpt1"} and not ruta.name.startswith((" ", "."))
              and not ruta.stem.endswith((" ", ".")), f"guardado: «{titulo}» no genera un nombre reservado ni acabado en punto/espacio ({ruta.name})")

    # ---- 4) fuentes: anuncios fuera, lectura en paralelo, timeout, numeración -----------------------
    reset(resultados=ANUNCIOS + BUENOS)
    correr("investiga el protocolo MQTT y hazme un informe")
    check(not any("duckduckgo.com" in u for u in estado["pedidas"]), "fuentes: no se pierden lecturas en anuncios del buscador")
    prompt = estado["prompts"][-1]
    check("Compra mqtt" not in prompt and "more info" not in prompt, "fuentes: los anuncios no entran en el prompt")
    check("[1]" in prompt and "[4]" in prompt and "cita" in prompt.lower(), "fuentes: numeradas [n] y se pide citar")
    check("las fuentes no cubren" in prompt and "dilo en lugar de suponer" in prompt,
          "fuentes: el prompt pide admitir lo que las fuentes no cubren")
    texto = informes()[-1].read_text(encoding="utf-8")
    check("[1] [Fuente 1](https://f1.example/p)" in texto, "fuentes: la sección «Fuentes» del informe va numerada")

    reset(retraso=0.4)
    t0 = time.time()
    correr("investiga el protocolo MQTT y hazme un informe")
    check(time.time() - t0 < 1.3, f"velocidad: las páginas se leen en paralelo ({time.time() - t0:.1f}s)")

    reset(retraso=30.0)
    research._TIMEOUT_PAGINA = 0.2
    t0 = time.time()
    res = correr("investiga el protocolo MQTT y hazme un informe")
    check(time.time() - t0 < 5, "velocidad: una página lentísima no cuelga el informe")
    research._TIMEOUT_PAGINA = 8.0

    # helpers compartidos
    limpios = websearch.sin_ruido(ANUNCIOS + BUENOS[:2] + [{"title": "", "url": "https://x.example"}])
    check([r["title"] for r in limpios] == ["Fuente 1", "Fuente 2"], "helper sin_ruido: quita anuncios y resultados sin título")
    reset(retraso=0.0)
    leidas = asyncio.run(websearch.leer_paginas(BUENOS[:3], n=2, max_chars=10, timeout=1.0))
    check(leidas == ["TEXTO-DE-L", "TEXTO-DE-L"], f"helper leer_paginas: n y max_chars respetados ({leidas})")

    # ---- 5) abrir un informe con varias coincidencias -----------------------------------------------
    reset()
    correr("investiga el protocolo MQTT y hazme un informe")
    correr("investiga MQTT en domótica y hazme un informe")
    res = correr("abre el informe de mqtt")
    check("también" in res["reply"].lower() or "otros" in res["reply"].lower(),
          "abrir: si varios informes coinciden, lo dice")

    # ---- 6) informe económico: ingresos vs gastos ----------------------------------------------------
    class PgFalso:
        online = True

        def __init__(self, filas, falla=False):
            self.filas, self.falla = filas, falla

        def _rows(self, sql, params=()):
            if self.falla:
                raise RuntimeError("tabla ausente")
            return list(self.filas)

    class GrafoFalso:
        def __init__(self, lineas):
            self.lineas = lineas

        def search(self, q, n=6):
            return [{"line": l} for l in self.lineas if q in l.lower()]

    facturas = [{"number": "F-1", "concept": "diseño web", "amount": 1200, "status": "pagada"},
                {"number": "F-2", "concept": "mentoría", "amount": 500, "status": "pendiente"}]
    reset()
    res = correr("informe económico", {"pg": PgFalso(facturas), "graph": GrafoFalso([])})
    check(not estado["prompts"], "economía: solo facturas emitidas (ingresos) -> NO pide consejos de recorte al modelo")
    check("1700" in res["reply"] and "ingresos" in res["reply"].lower() and "no tengo gastos" in res["reply"].lower(),
          "economía: da el total de ingresos y dice que no tiene gastos registrados")
    check("recortar" not in res["reply"].lower() or "no puedo" in res["reply"].lower(), "economía: no inventa dónde recortar")

    reset()
    res = correr("dónde puedo recortar gastos", {"pg": PgFalso(facturas), "graph": GrafoFalso(["he pagado 200€ de luz (gasto)"])})
    prompt = estado["prompts"][-1]
    check("INGRESO" in prompt and "GASTO" in prompt and "he pagado 200€ de luz" in prompt,
          "economía: con gastos reales, el prompt distingue INGRESO de GASTO")
    check("2 factura" in res["reply"] and "1 apunte" in res["reply"], "economía: la cabecera dice cuántas facturas y apuntes de gasto usó")

    # los apuntes se CLASIFICAN: un cobro no es un gasto, y lo ambiguo no se usa
    reset()
    notas_mixtas = ["he pagado 200€ de luz (gasto)", "Acme me ha pagado 500€ por la web (cobro)",
                    "pago pendiente de revisar", "gasto 1.234,50 € de alquiler del local", "gasto en café sin importe"]
    res = correr("dónde puedo recortar gastos", {"pg": PgFalso(facturas), "graph": GrafoFalso(notas_mixtas)})
    prompt = estado["prompts"][-1]
    check("GASTO — he pagado 200€ de luz" in prompt and "GASTO — gasto 1.234,50 € de alquiler" in prompt,
          "economía: los apuntes que son gastos van como GASTO")
    check("GASTO — Acme me ha pagado" not in prompt and "INGRESO — Acme me ha pagado 500€" in prompt,
          "economía: «Acme me ha pagado 500€» es un INGRESO, nunca un gasto")
    check("pago pendiente de revisar" not in prompt, "economía: un apunte ambiguo no se usa para aconsejar")
    check("3 apunte(s) de gasto" in res["reply"] and "ignorado" in res["reply"].lower(),
          "economía: la cabecera dice cuántos gastos usó y cuántos apuntes ignoró")
    check("1434.50" in res["reply"], "economía: total determinista de los gastos con importe (200 + 1.234,50)")
    check("sin importe" in res["reply"].lower(), "economía: avisa de los gastos que no llevan importe")

    # importes: sin falsos positivos por la izquierda («A200€», «ref12345€», «v1.5€»)
    check(research._importe("pagué A200€ de luz") is None and research._importe("ref12345€ de algo") is None,
          "importe: un número pegado a letras NO es un importe (A200€, ref12345€)")
    check(research._importe("he pagado 200€ de luz") == 200.0 and research._importe("gasto de 1.234,50 € de alquiler") == 1234.5
          and research._importe("pago € 45 de agua") == 45.0 and research._importe("compra (200€)") == 200.0,
          "importe: los formatos válidos siguen funcionando (200€, 1.234,50 €, € 45, entre paréntesis)")

    # clasificación: lo que parece pero no es un gasto no se usa
    check(research._tipo_apunte("cuota de mercado del 20%") == "" and research._tipo_apunte("Acme hizo una compra de 500€") == "",
          "clasificación: «cuota de mercado» y «compra de un cliente» NO son gastos (se ignoran)")
    check(research._tipo_apunte("compré material por 80€") == "gasto" and research._tipo_apunte("pago de la cuota de autónomos 300€") == "gasto",
          "clasificación: «compré…» y «cuota de autónomos» siguen siendo gastos")

    # solo apuntes de ingreso y ninguna factura ni gasto: no dice «0 facturas… 0,00 €»
    reset()
    res = correr("informe económico", {"pg": PgFalso([]), "graph": GrafoFalso(["Acme me ha pagado 500€ por la web (cobro)"])})
    check("0 factura" not in res["reply"] and "0.00" not in res["reply"] and "1 apunte(s) de ingreso" in res["reply"]
          and "no tengo gastos" in res["reply"].lower() and not estado["prompts"],
          "economía: solo apuntes de ingreso -> los cuenta, no inventa «0 facturas / 0,00 €» y no pide recortes")

    # tope por lista (no cortar ingresos o gastos en silencio)
    reset()
    muchos_gastos = [f"gasto número {i} de {i}€ en material" for i in range(1, 31)]
    muchas_facturas = [{"number": f"F-{i}", "concept": "x", "amount": 10, "status": "pagada"} for i in range(1, 16)]

    class GrafoTodo(GrafoFalso):
        def search(self, q, n=6):                       # ignora n: devuelve todo lo que casa
            return [{"line": l} for l in self.lineas if "gasto" in l.lower()] if q == "gasto" else []
    res = correr("dónde puedo recortar gastos", {"pg": PgFalso(muchas_facturas), "graph": GrafoTodo(muchos_gastos)})
    prompt = estado["prompts"][-1]
    check(prompt.count("GASTO —") == 20 and prompt.count("INGRESO —") == 10,
          f"economía: tope por lista (20 gastos y 10 ingresos), no un corte global ({prompt.count('GASTO —')}/{prompt.count('INGRESO —')})")
    check("20 de 30" in res["reply"] and "10 de 15" in res["reply"], "economía: dice que se enseñaron 20 de 30 gastos y 10 de 15 facturas")

    reset(modelo="ninguno")
    res = correr("dónde puedo recortar gastos", {"pg": PgFalso(facturas), "graph": GrafoFalso(["he pagado 200€ de luz (gasto)"])})
    check("Análisis sobre" not in res["reply"] and "no pude analizar" in res["reply"].lower(),
          "economía sin modelo: no presenta el error como análisis")

    reset()
    res = correr("informe económico", {"pg": PgFalso([], falla=True), "graph": GrafoFalso([])})
    check("No he podido leer la tabla de facturas" in res["reply"], "economía: sigue avisando si la tabla falla")
finally:
    websearch.search, websearch.fetch_page, llm.ask_llm, webbrowser.open = orig

print(f"\nresearch honesty: {_pass} OK, {len(_fail)} FAIL")
sys.exit(1 if _fail else 0)
