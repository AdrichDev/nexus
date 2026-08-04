# -*- coding: utf-8 -*-
"""Skill MEMORIA (memory_graph) — activacion, enrutado y que NO contamine.

La memoria real NUNCA se toca: pg y graph son dobles que solo apuntan lo que
se les pide, y se comprueba que lo grabado es el texto LITERAL del operador.
"""
import asyncio
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
    """Postgres de mentira: apunta lo que le mandan, no escribe en ningun sitio."""

    def __init__(self, online=True):
        self.online = online
        self.grabado = []

    def remember(self, content, kind="fact", tags=None):
        self.grabado.append({"content": content, "kind": kind, "tags": tags or []})

    def recall(self, topic, n=4):
        return []

    def all_knowledge(self, n=60):
        return []


class GrafoDoble:
    def __init__(self):
        self.diarias = []
        self.notas = []

    def append_daily(self, text, section=""):
        self.diarias.append((section, text))
        return "diaria.md"

    def write_note(self, title, body):
        self.notas.append((title, body))

    def search(self, topic, n=4):
        return []

    def graph(self):
        return {"nodes": [], "edges": []}


def main():
    from backend.core import skills_loader as sl
    sl.load_skills()

    print("· la skill carga con el cargador REAL")
    sk = sl.get_skills().get("memory_graph")
    check(sk is not None and sk.status != "error",
          "memory_graph carga sin error: " + (sk.description if sk else "no existe"))
    mod = sk.module

    print("· cada intent se activa con frases naturales (con y sin clitico)")
    esperado = {
        "remember": ["recuerda que entrego el jueves",
                     "acuerdate de que el cliente cobra los viernes",
                     "acuérdate que el cliente cobra los viernes",
                     "no olvides que la clave esta en el nas",
                     "apuntame que el proveedor responde por telegram",
                     "memoriza que la reunion es a las 9",
                     "ten en cuenta que no trabajo los lunes",
                     "guarda en memoria que uso python 3.12"],
        "learn": ["aprende que los despliegues se hacen con run.bat"],
        "learn_doc": ["aprendete el documento C:\\docs\\apuntes.pdf",
                      "indexa el archivo notas.md",
                      "estudia el pdf D:\\facturas\\contrato.pdf"],
        "learn_folder": ["aprendete la carpeta D:\\apuntes",
                         "ingiere el directorio C:\\proyectos\\docs"],
        "recall": ["que recuerdas de ana",
                   "que sabes sobre el proyecto helios",
                   "que te he contado de la nave",
                   "busca en la memoria facturas",
                   "búscame en la memoria las facturas",
                   "buscame en mis notas las facturas",
                   "encuentra en la memoria china",
                   "encuéntrame en tus apuntes lo del contrato",
                   "busca en tus notas china"],
        "list_knowledge": ["que sabes de mi", "cuanto sabes de mi",
                           "que has aprendido de mi"],
        "graph": ["muestrame el grafo", "enseñame el grafo", "grafo de notas",
                  "mapa de memoria"],
        "status": ["estado de la memoria", "como va la memoria"],
        "profile": ["mi perfil", "quien soy", "hablame de mi", "háblame de mí"],
    }
    for intent, frases in esperado.items():
        for f in frases:
            r = sl.route(f)
            check(bool(r) and r[0].folder == "memory_graph" and r[1] == intent,
                  f"«{f}» -> memory_graph/{intent}"
                  + (f" (se la queda {r[0].folder}/{r[1]})" if r else " (no casa: al cerebro)"))

    print("· fronteras: lo que NO es suyo")
    ajenas = {
        "recuerdame renovar el dni el 3 de agosto": "coach",   # recordatorio con fecha
        "que hora es": "tools",
        "haz una copia de seguridad": "backup",
    }
    for f, dueno in ajenas.items():
        r = sl.route(f)
        check(bool(r) and r[0].folder == dueno,
              f"«{f}» es de {dueno}" + (f" (la coge {r[0].folder})" if r else " (no casa)"))

    print("· graba el texto LITERAL, no una version reinterpretada")
    pg, graph = PgDoble(), GrafoDoble()
    ctx = {"pg": pg, "graph": graph, "settings": {}, "channel": "pc"}
    frase = "recuerda que el proveedor cobra a 60 dias."
    m = sl.route(frase)[2]
    r = asyncio.run(mod.handle("remember", frase, m, ctx))
    check(pg.grabado and pg.grabado[0]["content"] == "el proveedor cobra a 60 dias",
          f"lo grabado es el hecho tal cual: {pg.grabado}")
    check(graph.diarias and "el proveedor cobra a 60 dias" in graph.diarias[0][1],
          "y tambien va al grafo, literal")
    check("el proveedor cobra a 60 dias" in r["reply"], "y lo repite para que lo veas")

    print("· sin DB lo dice y explica como arreglarlo (sin inventarse un .bat)")
    pg2, graph2 = PgDoble(online=False), GrafoDoble()
    r2 = asyncio.run(mod.handle("remember", frase, m,
                                {"pg": pg2, "graph": graph2, "settings": {}}))
    check("offline" in r2["reply"].lower(), "avisa de que la DB esta offline")
    check("levanta docker" in r2["reply"].lower(),
          f"y da la orden que EXISTE de verdad: {r2['reply']}")
    check(not pg2.grabado, "con la DB offline no finge haber escrito en ella")

    print("· nexus_up.bat NO existe: no se puede mandar ejecutarlo")
    check(not (ROOT / "nexus_up.bat").exists(), "efectivamente no existe en el proyecto")
    src = (ROOT / "skills" / "memory_graph" / "skill.py").read_text(encoding="utf-8")
    doc = (ROOT / "skills" / "memory_graph" / "SKILL.md").read_text(encoding="utf-8")
    check("nexus_up.bat" not in src, "skill.py ya no lo menciona")
    check("nexus_up.bat" not in doc, "SKILL.md ya no lo menciona")

    print("· recall sin resultados no se inventa un recuerdo")
    rec = asyncio.run(mod.handle("recall", "que recuerdas de zzzz",
                                 sl.route("que recuerdas de zzzz")[2],
                                 {"pg": PgDoble(), "graph": GrafoDoble(), "settings": {}}))
    check("No tengo nada" in rec["reply"], f"dice que no tiene nada: {rec['reply'][:80]}")

    print("· rutas fuera de lo permitido: se deniega, no se lee a la brava")
    check("permissions" in src, "learn_doc/learn_folder pasan por backend.core.comun.permissions")
    check(src.count("P.path_allowed") >= 2, "las dos ingestas comprueban la ruta")

    print("· intent desconocido no revienta")
    r = asyncio.run(mod.handle("inexistente", "loquesea", None,
                               {"pg": PgDoble(), "graph": GrafoDoble(), "settings": {}}))
    check("no la tengo" in r["reply"], "responde con la ayuda, sin traceback")

    print("· es agnostica")
    for prohibido in ("Adri", "achoz", "D:\\Adrian"):
        check(prohibido not in src, f"skill.py no lleva «{prohibido}»")
        check(prohibido not in doc, f"SKILL.md no lleva «{prohibido}»")

    print("· el SKILL.md dice tambien lo que NO hace")
    check("Qué NO hace" in doc, "SKILL.md tiene la seccion «Qué NO hace»")
    check("mi perfil" in doc.lower(), "documenta el intent de perfil")

    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
