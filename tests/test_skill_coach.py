# -*- coding: utf-8 -*-
"""Skill COACH / SECRETARIO — activacion, fronteras del router y honestidad.

Sin LLM, sin DB y sin escribir nada real: pg y graph son dobles.
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
    def __init__(self, online=False):
        self.online = online
        self.recordatorios = []

    def goals(self):
        return []

    def save_goal(self, title, steps):
        return 1

    def add_reminder(self, what, when):
        self.recordatorios.append((what, when))
        return [1, 2, 3]


class GrafoDoble:
    def __init__(self):
        self.notas = []
        self.diarias = []

    def write_note(self, t, b):
        self.notas.append((t, b))

    def append_daily(self, t, section=""):
        self.diarias.append((section, t))
        return "diaria.md"


def main():
    from backend.core import skills_loader as sl
    sl.load_skills()

    print("· la skill carga con el cargador REAL")
    sk = sl.get_skills().get("coach")
    check(sk is not None and sk.status != "error",
          "coach carga sin error: " + (sk.description if sk else "no existe"))
    mod = sk.module

    print("· cada intent se activa con frases naturales")
    esperado = {
        "briefing": ["que me toca hoy", "qué me toca hoy", "que tengo que hacer hoy",
                     "plan de hoy", "plan del dia", "resumen del dia", "briefing",
                     "como viene el dia", "arrancamos el dia"],
        "weekly": ["revision semanal", "balance de la semana", "como ha ido la semana",
                   "resumen de la semana"],
        "new_goal": ["nuevo objetivo: fabricar camisetas", "mi objetivo es correr 10k",
                     "me propongo: leer mas", "quiero conseguir mas clientes",
                     "en tiktok mi objetivo es crecer"],
        "goals": ["mis objetivos", "como van mis objetivos", "muestrame mis objetivos",
                  "objetivos activos", "cual es el estado de mis objetivos"],
        "new_checklist": ["crea un checklist semanal revisar emails",
                          "hazme una lista de control para la mudanza",
                          "creame un checklist de la mudanza",
                          "prepárame un checklist mensual de facturas"],
        "checklists": ["mis checklists", "que checklists tengo", "muestrame mis checklists",
                       "enseñame los checklists", "ver checklists"],
        "add_item": ["añade al checklist llamar al gestor",
                     "apunta en el checklist comprar cinta",
                     "añademe al checklist revisar el coche",
                     "mete en el checklist pagar la luz"],
        "remind": ["recuerdame renovar el dni el 3 de agosto",
                   "recuérdame renovar el DNI el 3 de agosto",
                   "recuerdame llamar a mama mañana",
                   "avisame de la itv el viernes",
                   "ponme un aviso para la reunion el lunes",
                   "no me dejes olvidar el cumple el 12/09"],
        "reorganize": ["me ha surgido un imprevisto", "reorganiza", "replanifica",
                       "ha surgido un problema"],
        "coaching": ["estoy agobiado", "estoy agobiada", "no doy abasto",
                     "no me da la vida", "me siento superado", "estoy bloqueado"],
        "spec": ["planifica el proyecto tienda online", "crea una spec para el bot de ventas",
                 "hazme una spec de la web"],
    }
    for intent, frases in esperado.items():
        for f in frases:
            r = sl.route(f)
            check(bool(r) and r[0].folder == "coach" and r[1] == intent,
                  f"«{f}» -> coach/{intent}"
                  + (f" (se la queda {r[0].folder}/{r[1]})" if r else " (no casa: al cerebro)"))

    print("· fronteras: el coach va antes por alfabeto y NO puede tragarselo todo")
    ajenas = {
        "en instagram mi objetivo es vender mi curso": "instagram",
        "recuerda que entrego el jueves": "memory_graph",
        "que hora es": "tools",
        "haz una copia de seguridad": "backup",
        "llama a mama": "telefono",
    }
    for f, dueno in ajenas.items():
        r = sl.route(f)
        check(bool(r) and r[0].folder == dueno,
              f"«{f}» es de {dueno}" + (f" (la coge {r[0].folder}/{r[1]})" if r else " (no casa)"))
        check(not (r and r[0].folder == "coach"), f"«{f}» NO cae en coach")

    print("· fechas: entiende las que promete y NO se inventa las que no")
    hoy = dt.date.today()
    check(mod._parse_date("mañana").date() == hoy + dt.timedelta(days=1), "«mañana»")
    check(mod._parse_date("manana").date() == hoy + dt.timedelta(days=1), "«manana» sin tilde")
    check(mod._parse_date("pasado mañana").date() == hoy + dt.timedelta(days=2), "«pasado mañana»")
    check(mod._parse_date("3 de agosto") is not None, "«3 de agosto»")
    check(mod._parse_date("25/07") is not None, "«25/07»")
    check(mod._parse_date("viernes") is not None, "«viernes»")
    check(mod._parse_date("cuando pueda") is None, "lo que no entiende devuelve None")
    check(mod._parse_date("32/13") is None, "una fecha imposible no se convierte en otra")

    print("· un «cuando» ininteligible se dice, no se inventa una fecha")
    pg, graph = PgDoble(), GrafoDoble()
    ctx = {"pg": pg, "graph": graph, "settings": {"operator_name": "operador"}, "channel": "pc"}
    f = "recuerdame llamar al gestor el dia treinta y tantos"
    r = sl.route(f)
    if r and r[1] == "remind":
        out = asyncio.run(mod.handle("remind", f, r[2], ctx))
        check("No he entendido la fecha" in out["reply"], "avisa de que no entiende la fecha")
        check(not pg.recordatorios, "y NO deja un recordatorio a una fecha inventada")
    else:
        check(False, f"«{f}» deberia llegar a coach/remind")

    print("· sin DB, el recordatorio avisa de que es volatil")
    f2 = "recuerdame renovar el dni mañana"
    out2 = asyncio.run(mod.handle("remind", f2, sl.route(f2)[2], ctx))
    check("memoria local" in out2["reply"], "dice que vive en memoria local")
    check("pierde" in out2["reply"], "y que se pierde al reiniciar")

    print("· con DB dice el numero REAL de avisos que ha creado")
    pg3 = PgDoble(online=True)
    out3 = asyncio.run(mod.handle("remind", f2, sl.route(f2)[2],
                                  {"pg": pg3, "graph": GrafoDoble(),
                                   "settings": {"operator_name": "operador"}}))
    check("3 veces" in out3["reply"], f"3 avisos creados, 3 anunciados: {out3['reply'][:90]}")
    check(len(pg3.recordatorios) == 1, "y se ha pedido uno solo a la DB")

    print("· checklists: se pueden ver, y se avisa de que son volatiles")
    mod._local_checklists.clear()
    fc = "hazme un checklist de la mudanza"
    rc = asyncio.run(mod.handle("new_checklist", fc, sl.route(fc)[2], ctx))
    check("pierden al reiniciar" in rc["reply"], "el aviso de volatilidad esta en la respuesta")
    fa = "añade al checklist llamar al gestor"
    asyncio.run(mod.handle("add_item", fa, sl.route(fa)[2], ctx))
    fl = "mis checklists"
    rl = asyncio.run(mod.handle("checklists", fl, sl.route(fl)[2], ctx))
    check("llamar al gestor" in rl["reply"], f"el item se puede consultar: {rl['reply'][:120]}")
    mod._local_checklists.clear()
    rl2 = asyncio.run(mod.handle("checklists", fl, sl.route(fl)[2], ctx))
    check("ningún checklist" in rl2["reply"], "sin checklists lo dice y propone como crear uno")

    print("· sin objetivos no se inventa ninguno")
    rg = asyncio.run(mod.handle("goals", "mis objetivos", sl.route("mis objetivos")[2], ctx))
    check("Cero objetivos activos" in rg["reply"], "dice que no hay ninguno")

    print("· intent desconocido no revienta")
    r = asyncio.run(mod.handle("inexistente", "loquesea", None, ctx))
    check("no la tengo" in r["reply"], "responde con la ayuda, sin traceback")

    print("· es agnostica: el nombre del operador sale de settings")
    src = (ROOT / "skills" / "coach" / "skill.py").read_text(encoding="utf-8")
    doc = (ROOT / "skills" / "coach" / "SKILL.md").read_text(encoding="utf-8")
    check('settings"].get("operator_name")' in src, "el nombre se lee de la configuracion")
    for prohibido in ("Adri", "achoz", "D:\\Adrian", "C:\\Users\\"):
        check(prohibido not in src, f"skill.py no lleva «{prohibido}»")
        check(prohibido not in doc, f"SKILL.md no lleva «{prohibido}»")

    print("· el SKILL.md documenta los checklists y sus limites")
    check("Qué NO hace" in doc, "SKILL.md tiene la seccion «Qué NO hace»")
    check("mis checklists" in doc, "documenta el intent de listar checklists")
    check("memoria" in doc and "reiniciar" in doc, "avisa de que los checklists son volatiles")

    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
