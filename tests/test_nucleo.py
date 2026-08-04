# -*- coding: utf-8 -*-
"""NÚCLEO IA — «¿qué modelo de IA estás usando?» se contesta LEYENDO, no razonando.

Incidente del 31/07/2026 (capturas de Adri):
  1. «Que nucleo de ia estas trabajando ahora» → nexus se inventó que Núcleo IA
     era «una plataforma central para acceder a herramientas de IA orientadas a
     la productividad profesional». Falso: es una sección de este mismo HUD.
  2. «Pero que modelo de IA» → «No encuentro «tarea crear el prototipo de IA»».
     La frase no casaba con NINGÚN patrón, caía al cerebro, y el planificador
     se inventó una llamada al tablero con una tarea que no existe.

Estos tests fijan las dos mitades del arreglo: la skill determinista y la regla
del prompt que le prohíbe inventarse lo que es.
"""
import sys
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


class Ajustes:
    """Configuración de mentira, para no depender de la máquina que ejecuta."""
    def __init__(self, **kw): self.d = kw
    def get(self, k, d=None): return self.d.get(k, d)


def main():
    import asyncio
    from backend.core import skills_loader as sl
    sl.load_skills()

    print("· las frases REALES de Adri llegan a la skill (no al cerebro)")
    # La primera columna es literal de sus capturas, con sus faltas de tilde.
    frases = [
        "Que nucleo de ia estas trabajando ahora",
        "Pero que modelo de IA",
        "que modelo de ia estas usando",
        "que modelo estas usando",
        "con que ia trabajas",
        "cual es tu cerebro",
        "que llm usas",
        "que ia eres",
        "en que modelo estas trabajando",
        "¿qué núcleo de IA tienes puesto?",
        "quien te mueve",
        "cuál es el modelo de lenguaje que usas",
    ]
    for f in frases:
        r = sl.route(f)
        check(bool(r) and r[0].folder == "nucleo",
              f"«{f}» la atiende la skill Núcleo IA"
              + (f" (se la ha quedado {r[0].folder}/{r[1]})" if r else " (no casa con nada: se iría al cerebro)"))

    print("· y NO le roba la frase a nadie")
    ajenas = {
        "cual es el nucleo del problema": None,
        "temperatura de los nucleos": "system_pc",
        "cuantos nucleos tiene la cpu": None,
        "que modelo de coche te gusta": None,
        "crea una tarea de prototipo de IA": "tasks_board",
        "marca la velada como realizada": "tasks_board",
        "apunta que tengo que comprar pan": "tools",
        "que hora es": "tools",
        "pon el volumen al 40": "system_pc",
    }
    for f, esperada in ajenas.items():
        r = sl.route(f)
        check(not (r and r[0].folder == "nucleo"), f"«{f}» NO cae en Núcleo IA")
        if esperada:
            check(bool(r) and r[0].folder == esperada,
                  f"«{f}» sigue yendo a {esperada}")

    print("· la respuesta sale de la configuración, no de la imaginación")
    sk = sl.get_skills()["nucleo"]
    mod = sk.module

    d = mod.datos({"settings": Ajustes(llm_provider="openai", openai_model="gpt-5.5")})
    check(d["proveedor"] == "openai" and d["modelo"] == "gpt-5.5",
          "con OpenAI puesto, lee openai_model")
    t = mod.texto(d)
    check("gpt-5.5" in t and "OpenAI" in t, "y lo dice tal cual")

    d2 = mod.datos({"settings": Ajustes(llm_provider="ollama", ollama_model="qwen3:8b",
                                        openai_model="gpt-5.5")})
    check(d2["modelo"] == "qwen3:8b",
          "con Ollama puesto lee ollama_model, NO el de OpenAI que también está guardado")

    for prov, campo, val in (("anthropic", "anthropic_model", "claude-sonnet-5"),
                             ("gemini", "gemini_model", "gemini-2.5-flash"),
                             ("cloud", "cloud_model", "deepseek/deepseek-chat")):
        dd = mod.datos({"settings": Ajustes(**{"llm_provider": prov, campo: val})})
        check(dd["modelo"] == val, f"con {prov} puesto lee {campo}")

    print("· si no hay nada puesto, lo dice; no se lo inventa")
    vacio = mod.texto(mod.datos({"settings": Ajustes()}))
    check("no tengo" in vacio.lower() or "vacío" in vacio.lower(),
          "sin proveedor, admite que no hay núcleo")
    check("⚙" in vacio, "y dice dónde se pone")

    print("· «simulado» se avisa: no es una IA de verdad")
    mock = mod.texto(mod.datos({"settings": Ajustes(llm_provider="mock")}))
    check("no piensa" in mock.lower() or "relleno" in mock.lower(),
          "el proveedor mock lleva su aviso")

    print("· deja claro que Núcleo IA es una sección de nexus, no una plataforma")
    t3 = mod.texto(mod.datos({"settings": Ajustes(llm_provider="ollama", ollama_model="x")}))
    check("no es ninguna plataforma externa" in t3.lower(),
          "el texto desmiente lo que se inventó")
    check("plataforma central" not in t3.lower(), "y no repite el invento")

    print("· el handler responde y devuelve el dato aparte")
    r = asyncio.run(mod.handle("cual", "Pero que modelo de IA", None,
                               {"settings": Ajustes(llm_provider="openai",
                                                    openai_model="gpt-5.4")}))
    check("gpt-5.4" in r.get("reply", ""), "el handler contesta con el modelo real")
    check(r.get("data", {}).get("nucleo", {}).get("proveedor") == "openai",
          "y expone el dato crudo para quien lo quiera pintar")

    print("· el planificador sabe para qué sirve (si algún día llega por ahí)")
    check("cual" in (getattr(mod, "SKILL", {}).get("intents") or {}),
          "el intent está descrito para el cerebro")

    print("· la regla del prompt le prohíbe inventarse lo que es")
    src = (ROOT / "backend" / "core" / "infraestructura" / "llm.py").read_text(encoding="utf-8")
    check("TAMPOCO TE INVENTAS LO QUE ERES" in src, "la regla está en el prompt")
    check("Núcleo IA" in src and "SECCIONES Y PIEZAS DE ESTA APLICACIÓN" in src,
          "y nombra las secciones como lo que son")
    from backend.core.infraestructura import llm
    sp = llm._build_messages([{"role": "user", "content": "hola"}])[0]["content"]
    check("TAMPOCO TE INVENTAS LO QUE ERES" in sp, "y llega de verdad al system prompt")
    check("LAS CIFRAS NO SE INVENTAN" in sp, "sin haberse cargado la regla anterior")


    print("· «levanta docker» busca el compose donde de verdad está")
    # Hallado el 31/07/2026 al revisar la carpeta hermana «nexus_stack»: estaba
    # vacía (solo un directorio «init.sql» que dejó Docker al montar un archivo
    # que no existía), pero era LO PRIMERO que se miraba. El compose bueno lo
    # escribe nexus en config/docker-compose.yml y no se miraba nunca.
    import importlib.util as _u
    _sp = _u.spec_from_file_location("ap", ROOT / "skills" / "autoprovision" / "skill.py")
    _ap = _u.module_from_spec(_sp); _sp.loader.exec_module(_ap)
    src = (ROOT / "skills" / "autoprovision" / "skill.py").read_text(encoding="utf-8")
    i_cfg = src.find('ROOT / "config" / "docker-compose.yml"')
    i_gru = src.find('GRU / "docker-compose.nexus.yml"')
    check(i_cfg > 0, "se busca en config/docker-compose.yml")
    check(0 < i_cfg < i_gru, "y ANTES que en la carpeta hermana nexus_stack")
    check("nexus_stack" in src, "nexus_stack se conserva de respaldo, sin mandar")


    print("· el .gitignore tapa el estado de las herramientas, no la configuración del proyecto")
    # 31/07/2026: al abrir Claude Code aparecieron .claude/, .atl/ y .tokensave/
    # (esta ultima con una base de datos SQLite de ~15 MB). Ninguna estaba
    # ignorada. Un commit con 15 MB dentro no se arregla luego.
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for patron in (".atl/", ".tokensave/", ".claude/*", "!.claude/settings.json",
                   "!.claude/skills/", ".claude/settings.local.json",
                   "*.db-shm", "*.db-wal"):
        check(patron in gi, f"el .gitignore contiene «{patron}»")
    # El orden importa: la negacion tiene que ir DESPUES del patron que la tapa.
    check(gi.find(".claude/*") < gi.find("!.claude/settings.json"),
          "y la excepcion de settings.json va despues de .claude/*, o no aplicaria")

    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
