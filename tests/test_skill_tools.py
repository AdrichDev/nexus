# -*- coding: utf-8 -*-
"""Skill HERRAMIENTAS (tools) — activacion, mates seguras y limites.

Sin red: solo se ejercitan hora, temporizador, alarma, nota y matematicas.
"""
import asyncio
import datetime as dt
import sys
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
    online = False

    def remember(self, *a, **k):
        pass


class GrafoDoble:
    def __init__(self):
        self.diarias = []

    def append_daily(self, t, section=""):
        self.diarias.append((section, t))
        return "diaria.md"


def main():
    from backend.core.aplicacion import skills_loader as sl
    sl.load_skills()

    print("· la skill carga con el cargador REAL")
    sk = sl.get_skills().get("tools")
    check(sk is not None and sk.status != "error",
          "tools carga sin error: " + (sk.description if sk else "no existe"))
    mod = sk.module

    print("· cada intent se activa con frases naturales")
    esperado = {
        "time": ["que hora es", "qué hora es", "dime la hora", "dame la hora",
                 "que dia es", "que fecha es hoy", "que hora tenemos"],
        "timer": ["temporizador de 10 minutos", "pon un temporizador de 10 minutos",
                  "cuenta atras de 5 minutos", "avisame en 10 minutos",
                  "avísame dentro de 20 minutos", "temporizador de 30 segundos"],
        "alarm": ["alarma a las 7:30", "despiertame a las 8", "despiértame a las 8:15",
                  "despertador a las 6", "pon una alarma a las 22:00"],
        "note": ["apunta que tengo que comprar pan"],
        "ping": ["haz ping a google.com", "estado de la red", "hay internet",
                 "funciona el internet", "prueba la conexion", "va el internet"],
        "derive": ["deriva x**3", "derivame x**2", "cual es la derivada de x**3"],
        "integrate": ["integral de x**2", "integra x**2", "cual es la integral de x**2"],
        "solve": ["resuelve x**2 - 4 = 0", "resuelveme x + 2 = 5", "despeja x + 2 = 5"],
        "calc": ["cuanto es 2+2", "cuánto es 2+2*8", "calcula 15*3",
                 "calculame la raiz de 16", "raiz cuadrada de 16", "cuanto vale 3*7"],
    }
    for intent, frases in esperado.items():
        for f in frases:
            r = sl.route(f)
            check(bool(r) and r[0].folder == "tools" and r[1] == intent,
                  f"«{f}» -> tools/{intent}"
                  + (f" (se la queda {r[0].folder}/{r[1]})" if r else " (no casa: al cerebro)"))

    print("· el TIEMPO no es de esta skill: lo lleva 'clima' (y no hay duplicado)")
    check("weather" not in sk.patterns, "tools ya no declara un intent de clima")
    for f in ("que tiempo hace en madrid", "que tiempo hace", "clima", "el clima",
              "dime el tiempo"):
        r = sl.route(f)
        check(bool(r) and r[0].folder == "clima",
              f"«{f}» -> clima" + (f" (la coge {r[0].folder})" if r else " (no casa: al cerebro)"))
    src = (ROOT / "skills" / "tools" / "skill.py").read_text(encoding="utf-8")
    check("open-meteo" not in src.lower(), "y no queda una segunda API del tiempo aqui dentro")

    print("· la hora sale del reloj, no de la imaginacion")
    ctx = {"pg": PgDoble(), "graph": GrafoDoble(), "settings": {}, "channel": "pc"}
    r = asyncio.run(mod.handle("time", "que hora es", sl.route("que hora es")[2], ctx))
    now = dt.datetime.now()
    check(f"{now.day}/{now.month}/{now.year}" in r["reply"], f"la fecha es la de hoy: {r['reply']}")

    print("· temporizador y alarma dejan un aviso REAL en el scheduler")
    from backend.core.aplicacion.scheduler import timers
    timers.clear()
    f = "temporizador de 10 minutos"
    r = asyncio.run(mod.handle("timer", f, sl.route(f)[2], ctx))
    check(len(timers) == 1, "el temporizador se ha armado de verdad")
    check("10 minutos" in r["reply"], "y se anuncia con lo pedido")
    timers.clear()
    f = "alarma a las 7:30"
    r = asyncio.run(mod.handle("alarm", f, sl.route(f)[2], ctx))
    check(len(timers) == 1 and timers[0]["at"].hour == 7 and timers[0]["at"].minute == 30,
          f"la alarma queda a las 07:30: {timers}")
    timers.clear()

    print("· una hora imposible se rechaza, no se redondea a otra")
    f = "alarma a las 99:99"
    r0 = sl.route(f)
    out = asyncio.run(mod.handle("alarm", f, r0[2], ctx))
    check("no es una hora válida" in out["reply"], f"lo dice: {out['reply'][:70]}")
    check(not timers, "y no arma nada")

    print("· la nota va a la diaria del grafo")
    graph = GrafoDoble()
    f = "apunta que tengo que comprar pan"
    out = asyncio.run(mod.handle("note", f, sl.route(f)[2],
                                 {"pg": PgDoble(), "graph": graph, "settings": {}}))
    check(graph.diarias and "tengo que comprar pan" in graph.diarias[0][1],
          f"lo apuntado es literal: {graph.diarias}")

    print("· mates: resultados correctos")
    casos = [("calc", "cuanto es 2+2", "4"),
             ("calc", "calcula 15*3", "45"),
             ("derive", "deriva x**3", "3*x**2"),
             ("integrate", "integra x**2", "x**3/3"),
             ("solve", "resuelve x**2 - 4 = 0", "2")]
    for intent, frase, esperado_txt in casos:
        out = asyncio.run(mod.handle(intent, frase, sl.route(frase)[2], ctx))
        check(esperado_txt in out["reply"], f"«{frase}» -> contiene {esperado_txt}: {out['reply']}")

    print("· mates dichas por VOZ (whisper no transcribe '**')")
    def _sin_espacios(s):
        return mod._es2math(s).replace(" ", "")

    check(_sin_espacios("x al cuadrado") == "x**2", "«x al cuadrado» -> x**2")
    check(_sin_espacios("raiz de 16") == "sqrt(16)", "«raiz de 16» -> sqrt(16)")
    check(_sin_espacios("raíz cuadrada de 16") == "sqrt(16)", "con tilde tambien")
    check(_sin_espacios("dos por tres") == "2*3", "«dos por tres» -> 2*3")
    check(_sin_espacios("x al cubo") == "x**3", "«x al cubo» -> x**3")

    print("· la puerta de seguridad: sympify() hace eval(), y esto NO pasa")
    peligros = ["__import__('os').system('calc')", "open('x').read()",
                "eval('1')", "os.system('dir')", "x; import os",
                "1 if x else __import__('sys')", "'a'*99"]
    for p in peligros:
        check(not mod._expr_matematica(p), f"rechazado: {p!r}")
    inofensivos = ["2+2", "x**3", "sqrt(16)", "sin(x)+cos(x)", "x**2 - 4 = 0", "3.5*2"]
    for e in inofensivos:
        check(mod._expr_matematica(e), f"aceptado: {e!r}")
    check(not mod._expr_matematica("a" * 250), "una expresion absurdamente larga se rechaza")
    check(not mod._expr_matematica("cuanto vale el iva"),
          "lo que no es matematica no llega a sympy (lo contesta el modelo)")

    print("· intent desconocido no revienta")
    r = asyncio.run(mod.handle("inexistente", "loquesea", None, ctx))
    check("No he pillado" in r["reply"], "responde con la ayuda, sin traceback")

    print("· es agnostica")
    doc = (ROOT / "skills" / "tools" / "SKILL.md").read_text(encoding="utf-8")
    for prohibido in ("Adri", "achoz", "D:\\Adrian", "C:\\Users\\"):
        check(prohibido not in src, f"skill.py no lleva «{prohibido}»")
        check(prohibido not in doc, f"SKILL.md no lleva «{prohibido}»")

    print("· el SKILL.md no promete datos simulados")
    check("simulado" not in doc.lower(), "no dice que simule nada (seria inventarse datos)")
    for trozo in ("Qué necesita configurado", "Qué NO hace"):
        check(trozo in doc, f"SKILL.md tiene la seccion «{trozo}»")

    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
