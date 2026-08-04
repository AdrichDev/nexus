# -*- coding: utf-8 -*-
"""Las doce skills pequeñas: COMPORTAMIENTO — que no inventen datos, que fallen
diciendo la verdad y que no borren ni emitan nada sin permiso.

Todo con dobles: no se llama a ninguna API, no se lanza ningún flujo, no se
instala ningún juego, no se emite ninguna factura de verdad y no se escribe en
la memoria. Sin red, la suite pasa igual.
"""
import asyncio
import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_fail = []; _pass = 0
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass


def check(c, m):
    global _pass
    if c: _pass += 1
    else: _fail.append(m); print("  FALLO:", m)


def carga(folder):
    """Carga una skill como lo hace el cargador real (ruta de fichero)."""
    py = ROOT / "skills" / folder / "skill.py"
    spec = importlib.util.spec_from_file_location(f"skills.{folder}", py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Ajustes:
    """Configuración de mentira: la suite no lee ni escribe la de verdad."""
    def __init__(self, **kw): self.d = kw; self.escrituras = []
    def get(self, k, d=None): return self.d.get(k, d)
    def set(self, k, v): self.escrituras.append((k, v)); self.d[k] = v
    def secret(self, k, d=""): return self.d.get(k, d)


class Grafo:
    def __init__(self): self.notas = []
    def append_daily(self, texto, section=""): self.notas.append((section, texto))
    def write_note(self, *a, **k): self.notas.append(a)


class PgOffline:
    online = False
    def save_invoice(self, *a): return None
    def _rows(self, *a): return []


def rutar(mod, frase):
    """(intent, match) del primer patrón de ESTA skill que case."""
    import re
    for intent, rx in mod.SKILL["patterns"].items():
        m = re.search(rx, frase, re.IGNORECASE)
        if m:
            return intent, m
    return None, None


def main():
    # ══════════════════ nucleo: se LEE la configuración, no se razona ══════
    print("· nucleo lee el modelo de settings, no se lo inventa ni lo pregunta")
    nucleo = carga("nucleo")
    src = (ROOT / "skills" / "nucleo" / "skill.py").read_text(encoding="utf-8")
    check("ask_llm" not in src, "nucleo no llama al LLM para saber qué modelo hay")
    for prov, campo, modelo in (("ollama", "ollama_model", "un-modelo-local"),
                                ("openai", "openai_model", "un-modelo-nube"),
                                ("anthropic", "anthropic_model", "un-claude")):
        ctx = {"settings": Ajustes(llm_provider=prov, **{campo: modelo})}
        r = asyncio.run(nucleo.handle("cual", "qué modelo de ia usas", None, ctx))
        check(modelo in r["reply"], f"nucleo dice el modelo de {prov} tal cual está puesto")
        check(r["data"]["nucleo"]["modelo"] == modelo, f"data trae el modelo de {prov}")
    r = asyncio.run(nucleo.handle("cual", "qué modelo", None, {"settings": Ajustes()}))
    check("vacío" in r["reply"] or "ningún núcleo" in r["reply"],
          "sin proveedor puesto lo dice, no se inventa uno")
    r = asyncio.run(nucleo.handle("cual", "qué modelo", None,
                                  {"settings": Ajustes(llm_provider="mock", cloud_model="x")}))
    check("Simulado" in r["reply"] and "no piensa" in r["reply"],
          "avisa de que el proveedor simulado no es una IA de verdad")

    # ══════════════════ billing: ni importes ni datos fiscales inventados ══
    print("· billing no inventa importes ni datos fiscales")
    billing = carga("billing")
    with tempfile.TemporaryDirectory() as tmp:
        billing.INVOICE_DIR = Path(tmp)          # nunca se toca data/invoices
        ctx = {"pg": PgOffline(), "graph": Grafo(), "settings": Ajustes()}
        intent, m = rutar(billing, "hazle una factura a Acme por el diseño")
        r = asyncio.run(billing.handle(intent, "hazle una factura a Acme por el diseño", m, ctx))
        check("importe" in r["reply"].lower(), "sin importe, lo pide")
        check("no me lo invento" in r["reply"].lower(), "dice explícitamente que no lo inventa")
        check(not list(Path(tmp).glob("*.html")), "sin importe NO emite ninguna factura")
        check("100" not in r["reply"], "no cuela un importe provisional")

        intent, m = rutar(billing, "hazle una factura a Acme por el diseño de 350 euros")
        r = asyncio.run(billing.handle(intent, "hazle una factura a Acme por el diseño de 350 euros",
                                       m, ctx))
        check("350.00" in r["reply"], "con importe, usa el que le han dicho")
        emitidas = list(Path(tmp).glob("*.html"))
        check(len(emitidas) == 1, "emite exactamente una factura")
        html = emitidas[0].read_text(encoding="utf-8") if emitidas else ""
        check("350.00" in html, "el HTML lleva el importe dicho")
        for inventado in ("NIF", "IVA", "B-", "IRPF"):
            check(inventado not in html, f"el HTML no se inventa un dato fiscal ({inventado})")
        check("BORRADOR" in r["reply"] and "NIF" in r["reply"],
              "avisa de que es un borrador sin datos fiscales")
        check("LOCAL" in r["reply"], "con Postgres caído avisa de la numeración local")

    # ══════════════════ engram: no borra sin preguntar ══════════════════════
    print("· engram enseña qué va a olvidar y NO borra hasta el «sí»")
    engram = carga("engram")
    from backend.core.dominio import opmem
    from backend.core.comun import confirm
    reglas = [{"id": "a1", "kind": "regla", "text": "nunca borres sin enseñar"},
              {"id": "a2", "kind": "preferencia", "text": "resúmenes cortos, sin florituras"}]
    borrados = []
    orig_match, orig_forget = opmem.matching, opmem.forget
    try:
        opmem.matching = lambda q: reglas
        opmem.forget = lambda q: (borrados.append(q), len(reglas))[1]
        intent, m = rutar(engram, "olvida la regla de los resúmenes")
        check(intent == "forget_rule", "«olvida la regla…» es forget_rule")
        r = asyncio.run(engram.handle(intent, "olvida la regla de los resúmenes", m,
                                      {"channel": "test_pequenas"}))
        check(not borrados, "NO ha borrado nada todavía")
        check("¿" in r["reply"] or "confirm" in r["reply"].lower(), "pregunta antes de borrar")
        for regla in reglas:
            check(regla["text"][:20] in r["reply"], "enseña la regla que se llevaría por delante")
        check(confirm.pending("test_pequenas") is not None, "deja la acción armada, sin ejecutar")
        asyncio.run(confirm.answer("no", "test_pequenas"))
        check(not borrados, "con un «no» sigue sin borrar nada")
        opmem.matching = lambda q: []
        intent, m = rutar(engram, "olvida la regla de algo que no existe")
        r = asyncio.run(engram.handle(intent, "olvida la regla de algo que no existe", m,
                                      {"channel": "test_pequenas"}))
        check("mis reglas" in r["reply"], "si no casa nada, dice cómo ver las que hay")
    finally:
        opmem.matching, opmem.forget = orig_match, orig_forget

    print("· «mis reglas» sale de la memoria operativa local, no del LLM")
    esrc = (ROOT / "skills" / "engram" / "skill.py").read_text(encoding="utf-8")
    check("ask_llm" not in esrc, "engram no le pide al modelo lo que tiene guardado")

    # ══════════════════ devils_advocate: la promesa es cierta ══════════════
    print("· devils_advocate va SIEMPRE puesto de verdad (no es una promesa vacía)")
    from backend.core.infraestructura import llm
    check("DEVIL_INSTRUCTION" in llm.__dict__, "existe la instrucción")
    lsrc = (ROOT / "backend" / "core" / "infraestructura" / "llm.py").read_text(encoding="utf-8")
    check("base += DEVIL_INSTRUCTION" in lsrc,
          "la instrucción se CONCATENA al prompt de sistema, no se queda de adorno")
    diablo = carga("devils_advocate")
    ajustes = Ajustes()
    for frase, intent in (("activa el modo abogado del diablo", "on"),
                          ("desactiva el modo abogado del diablo", "off")):
        i, m = rutar(diablo, frase)
        check(i == intent, f"«{frase}» va a {intent}")
        r = asyncio.run(diablo.handle(i, frase, m, {"settings": ajustes}))
        check(not ajustes.escrituras, f"«{frase}» no conmuta ningún ajuste fantasma")
        check("SIEMPRE" in r["reply"] or "no se apaga" in r["reply"],
              f"«{frase}» contesta la verdad: va siempre puesto")

    # ══════════════════ clima: mañana es mañana, no hoy ════════════════════
    print("· clima da la previsión del día pedido, no la de hoy disfrazada")
    clima = carga("clima")
    HOY = {"temp_C": "20", "FeelsLikeC": "20", "humidity": "50", "windspeedKmph": "5",
           "weatherDesc": [{"value": "Sunny"}]}
    FALSO = {"current_condition": [HOY],
             "nearest_area": [{"areaName": [{"value": "Ciudad"}]}],
             "weather": [{"date": "2026-08-02", "maxtempC": "30", "mintempC": "18", "hourly": []},
                         {"date": "2026-08-03", "maxtempC": "35", "mintempC": "21",
                          "hourly": [{"weatherDesc": [{"value": "Rain"}], "chanceofrain": "80"}]}]}

    class RespFalsa:
        def raise_for_status(self): pass
        def json(self): return FALSO

    class ClienteFalso:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): self.url = url; return RespFalsa()

    orig_cli = clima.httpx.AsyncClient
    try:
        clima.httpx.AsyncClient = ClienteFalso
        r = asyncio.run(clima.handle("weather", "qué tiempo hace en Sevilla", None, {}))
        check("20°C" in r["reply"], "hoy da la temperatura actual")
        r = asyncio.run(clima.handle("weather", "qué tiempo hace en Sevilla mañana", None, {}))
        check("mañana" in r["reply"] and "35" in r["reply"],
              "mañana usa la previsión de mañana")
        check("20°C (sensación" not in r["reply"], "mañana NO cuela el dato de ahora mismo")
        FALSO["weather"] = FALSO["weather"][:1]
        r = asyncio.run(clima.handle("weather", "qué tiempo hace pasado mañana", None, {}))
        check("no tengo" in r["reply"].lower(), "sin previsión de ese día lo dice, no la inventa")
    finally:
        clima.httpx.AsyncClient = orig_cli
        FALSO["weather"] = []

    print("· clima falla con honestidad si no llega a wttr.in")
    class ClienteRoto:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): raise OSError("sin red")
    try:
        clima.httpx.AsyncClient = ClienteRoto
        r = asyncio.run(clima.handle("weather", "qué tiempo hace", None, {}))
        check("wttr.in" in r["reply"] and "°C" not in r["reply"],
              "sin red dice que no llega, no se inventa la temperatura")
        check("Traceback" not in r["reply"], "sin traceback en la cara del usuario")
    finally:
        clima.httpx.AsyncClient = orig_cli

    # ══════════════════ falta de credencial: se dice qué falta y dónde ═════
    print("· sin credenciales dicen QUÉ falta y CÓMO se arregla (y no fingen)")
    discord = carga("discord")
    r = asyncio.run(discord.handle("notify", "manda a discord: hola",
                                   rutar(discord, "manda a discord: hola")[1],
                                   {"settings": Ajustes()}))
    check("webhook" in r["reply"].lower() and "⚙" in r["reply"],
          "discord explica el webhook y dónde guardarlo")
    check("Publicado" not in r["reply"], "no dice que lo publicó cuando no puede")

    n8n = carga("n8n_flows")
    intent, m = rutar(n8n, "lanza el flujo backup")
    r = asyncio.run(n8n.handle(intent, "lanza el flujo backup", m,
                               {"settings": Ajustes(n8n_webhook_url="")}))
    check("n8n_webhook_url" in r["reply"], "n8n dice el ajuste exacto que falta")
    check("disparado" not in r["reply"], "no dice que disparó el flujo cuando no lo hizo")

    mcp = carga("mcp_hands")
    mcp.CONFIG = Path(tempfile.gettempdir()) / "no_existe_mcp_servers.json"
    r = asyncio.run(mcp.handle("list", "qué manos tienes", None, {}))
    check("mcp_servers.example.json" in r["reply"], "mcp_hands manda a la plantilla que EXISTE")
    check((ROOT / "config" / "mcp_servers.example.json").is_file(),
          "y esa plantilla existe de verdad en el repo")

    # ══════════════════ las instrucciones de arreglo son reales ════════════
    print("· cada fichero/orden que citan las skills existe de verdad")
    citados = {
        "config/mcp_servers.example.json": ROOT / "config" / "mcp_servers.example.json",
        "config/n8n_flujo_ejemplo.json": ROOT / "config" / "n8n_flujo_ejemplo.json",
        "knowledge/": ROOT / "knowledge",
    }
    for nombre, ruta in citados.items():
        check(ruta.exists(), f"«{nombre}» existe (lo cita una de las doce)")

    from backend.core import skills_loader as sl
    sl.load_skills()
    print("· las órdenes que las skills sugieren al fallar SÍ se enrutan")
    for sugerida, destino in (("recarga los conectores", "mcp_hands"),
                              ("mis reglas", "engram"),
                              ("ver facturas", "billing"),
                              ("manda a discord: hola", "discord"),
                              ("qué modelo de IA estás usando", "nucleo"),
                              ("busca en internet el tema", "ai_media"),
                              ("analiza la imagen D:\\x.png", "ai_media"),
                              ("transcribe el audio D:\\x.mp3", "ai_media"),
                              ("abogado del diablo: mi idea", "devils_advocate"),
                              ("qué skills de dev tienes", "dev_knowledge"),
                              ("tiempo en Sevilla", "clima")):
        r = sl.route(sugerida)
        check(r is not None and r[0].folder == destino,
              f"«{sugerida}» (sugerida por una skill) llega a {destino}")

    # ══════════════════ nada de scraping ni de datos de terceros ═══════════
    print("· ni ai_media ni games hacen scraping")
    for folder, permitidos in (("games", ("store.steampowered.com/api/",)),
                               ("ai_media", ())):
        s = (ROOT / "skills" / folder / "skill.py").read_text(encoding="utf-8")
        for prohibido in ("BeautifulSoup", "bs4", "lxml", "html.parser", "selenium"):
            check(prohibido not in s, f"{folder} no usa un parser de HTML ({prohibido})")

    print("· places abre la URL y no se inventa precios ni duraciones")
    places = carga("places")
    abiertas = []
    places.webbrowser.open = lambda u: abiertas.append(u) or True
    for frase, trozo in (("busca vuelos a París", "travel/flights"),
                         ("ruta de Madrid a Toledo", "maps/dir"),
                         ("busca vídeos de gatos", "youtube.com/results")):
        intent, m = rutar(places, frase)
        r = asyncio.run(places.handle(intent, frase, m, {}))
        check(abiertas and trozo in abiertas[-1], f"«{frase}» abre la URL correcta")
        check("€" not in r["reply"] or "menos de" in r["reply"],
              f"«{frase}» no se saca un precio de la manga")
        check("minutos" not in r["reply"] and "km" not in r["reply"],
              f"«{frase}» no se inventa distancia ni duración")

    print("· dev_knowledge no se inventa metodologías que no tiene")
    devk = carga("dev_knowledge")
    devk.KNOWLEDGE = Path(tempfile.gettempdir()) / "knowledge_que_no_existe"
    r = asyncio.run(devk.handle("list", "qué skills de dev tienes", None, {}))
    check("vacía" in r["reply"] and "knowledge/" in r["reply"],
          "sin biblioteca lo dice y explica dónde ponerla")

    print("· ai_media no describe una imagen que no puede ver")
    ai = carga("ai_media")
    intent, m = rutar(ai, "analiza la imagen D:\\no\\existe.png")
    r = asyncio.run(ai.handle(intent, "analiza la imagen D:\\no\\existe.png", m, {}))
    check("No encuentro" in r["reply"], "si el archivo no está, lo dice")
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "x.png"; f.write_bytes(b"no soy un png")
        intent, m = rutar(ai, f"analiza la imagen {f}")
        r = asyncio.run(ai.handle(intent, f"analiza la imagen {f}", m, {}))
        check("metadatos" in r["reply"], "sin modelo de visión solo promete metadatos")
        check("modelo de visión" in r["reply"] or "llava" in r["reply"],
              "dice que le falta un modelo de visión para ver el contenido")
        check("CONTENIDO" in r["reply"], "deja claro que el contenido NO lo está describiendo")

    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
