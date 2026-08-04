# -*- coding: utf-8 -*-
"""Auditoría de la skill AUTO-PROVISIÓN: activación con frases naturales,
enrutado real, y que nada de infraestructura se toque sin confirmación.

No levanta contenedores, no descarga modelos, no crea workflows y no toca
variables de entorno: `_run`, `_has` y las llamadas HTTP se sustituyen por
dobles que apuntan lo que se les pide en vez de ejecutarlo.

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_skill_autoprovision.py
"""
from __future__ import annotations

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_fail, _pass = [], 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  ✖ " + msg)


from backend.core import skills_loader as sl
from backend.core.comun import confirm  # noqa: E402

print("== 1) carga con el cargador real ==")
REG = sl.load_skills()
SK = REG.get("autoprovision")
check(SK is not None and SK.status != "error",
      f"autoprovision no carga: {SK.description if SK else 'no registrada'}")
MOD = SK.module if SK else None
check(MOD is not None and hasattr(MOD, "handle"), "autoprovision no expone handle()")
for i in ("diagnose", "docker_up", "n8n_setup", "telegram_setup", "model_ensure", "ollama_fix"):
    check(i in (SK.patterns if SK else {}), f"falta el intent «{i}»")

print("== 2) activación con frases naturales (tildes, enclíticos, sinónimos) ==")
ACTIVAN = {
    "diagnose": ["revisa tu infraestructura", "revísame tu infraestructura",
                 "comprueba tus servicios", "compruébame tus sistemas",
                 "audítame la infraestructura", "haz un diagnóstico de infraestructura",
                 "cómo están tus servicios", "qué tal están tus conexiones",
                 "ponte en marcha", "autoprovisión"],
    "docker_up": ["levanta docker", "levántame docker", "arranca los contenedores",
                  "arráncame los contenedores", "enciende la base de datos",
                  "enciéndeme la base de datos", "sube el stack", "inicia postgres",
                  "arranca la bd", "levanta el pgvector", "pon en marcha el docker"],
    "n8n_setup": ["configura n8n", "configúrame n8n", "crea el flujo", "créame el flujo",
                  "importa el workflow", "prepara el workflow de n8n", "conéctame n8n"],
    "telegram_setup": ["configura telegram", "configúrame telegram", "activa el bot",
                       "actívame el bot", "registra el bot de telegram",
                       "valida el token de telegram"],
    "model_ensure": ["prepara el modelo llama3.1", "prepárame el modelo llama3.1",
                     "instala el modelo qwen3", "descárgame el modelo qwen3",
                     "bájate el modelo gemma2", "asegúrate del modelo llama3"],
    "ollama_fix": ["arregla ollama", "arréglame ollama", "repara ollama",
                   "mis modelos locales no aparecen", "no se detectan los modelos",
                   "conecta los modelos locales"],
}
for intent, frases in ACTIVAN.items():
    for f in frases:
        r = sl.route(f)
        got = f"{r[0].folder}.{r[1]}" if r else "(nada)"
        check(got == f"autoprovision.{intent}", f"«{f}» → {got} (esperado autoprovision.{intent})")

print("== 3) fronteras: lo que NO es suyo ==")
for frase, ajeno in (("pon el volumen al 50", "autoprovision"),
                     ("pon la tele", "autoprovision"),
                     ("pon algo de rock", "autoprovision"),
                     ("conéctate a la base de datos postgresql://u:p@h/db", "autoprovision")):
    r = sl.route(frase)
    check(r is not None and r[0].folder != ajeno, f"«{frase}» se la queda {ajeno}")


class _Settings(dict):
    def get(self, k, d=None):
        return dict.get(self, k, d)

    def set(self, k, v):
        self[k] = v

    def secret(self, k):
        return self.get("__s_" + k, "")

    def set_secret(self, k, v):
        self["__s_" + k] = v


class _Bus:
    async def emit(self, *a, **k):
        return None


def _ctx(**kw):
    s = _Settings(kw.pop("settings", {}))
    return {"settings": s, "bus": _Bus(), "pg": None, "channel": "test", **kw}


print("== 4) docker: sin docker instalado responde qué falta, y nunca borra huérfanos ==")
_cmds = []
MOD._run = lambda cmd, timeout=60: (_cmds.append(list(cmd)) or (True, "ok"))
MOD._has = lambda b: False
r = asyncio.run(MOD.handle("docker_up", "levanta docker", None, _ctx()))
check("no está instalado" in r["reply"] and "Docker Desktop" in r["reply"],
      "sin Docker no dice qué falta ni cómo arreglarlo")
check("Traceback" not in r["reply"], "el fallo de docker suelta traceback")

MOD._has = lambda b: True
_cmds.clear()
asyncio.run(MOD.handle("docker_up", "levanta docker", None, _ctx()))
up = [c for c in _cmds if "up" in c]
check(up and "--remove-orphans" not in up[0],
      "`docker compose up` sigue llevando --remove-orphans (borra contenedores)")

print("== 5) n8n: no crea el workflow sin confirmar ==")
confirm.clear()


async def _vivo(base):
    return True


MOD._n8n_alive = _vivo
_posts = []


async def _post_spy(url, body=None, headers=None, timeout=25):
    _posts.append(url)
    raise AssertionError("no debería llamarse sin confirmación")


MOD._post = _post_spy
ctx = _ctx(settings={"__s_n8n_api_key": "k"})
cfg = os.path.join(ROOT, "config", "n8n_flujo_nexus.json")
tiene_wf = os.path.isfile(cfg) or os.path.isfile(
    os.path.join(ROOT, "config", "n8n_flujo_ejemplo.json"))
r = asyncio.run(MOD.handle("n8n_setup", "configura n8n", None, ctx))
if tiene_wf:
    check(confirm.pending("test") is not None, "crear el workflow de n8n no pide confirmación")
    check("?" in r["reply"], "la confirmación de n8n no es una pregunta")
else:
    check("No encuentro el JSON" in r["reply"], "sin JSON de workflow no lo dice claro")
check(not _posts, "n8n_setup ha llamado a la API antes de confirmar")
confirm.clear()

print("== 6) ollama: no sobrescribe OLLAMA_MODELS ya puesta sin confirmar ==")
confirm.clear()
_setx = []
MOD._setx_models = lambda t: (_setx.append(t) or "fijada")


async def _live(ctx):
    return ["llama3:latest"]


MOD._ollama_live = _live
os.environ["OLLAMA_MODELS"] = r"C:\ruta\vieja"
carpeta = os.path.join(ROOT, "tests")
r = asyncio.run(MOD.handle("ollama_fix", "arregla ollama",
                           None, _ctx(settings={"model_scan_paths": [carpeta]})))
check(not _setx, "ha sobrescrito OLLAMA_MODELS sin preguntar")
check(confirm.pending("test") is not None, "sobrescribir OLLAMA_MODELS no pide confirmación")
check(r"C:\ruta\vieja" in r["reply"], "no dice qué valor iba a sobrescribir")
confirm.clear()
os.environ.pop("OLLAMA_MODELS", None)

print("== 7) sin carpeta de modelos configurada lo dice, no se inventa nada ==")
r = asyncio.run(MOD.handle("ollama_fix", "arregla ollama", None, _ctx(settings={})))
check("No tienes carpeta de modelos configurada" in r["reply"],
      "sin model_scan_paths no explica qué falta")
check(not _setx, "ha tocado OLLAMA_MODELS sin carpeta configurada")

print("== 8) telegram: sin token pide el token, no inventa un bot ==")
r = asyncio.run(MOD.handle("telegram_setup", "configura telegram", None, _ctx()))
check("BotFather" in r["reply"] and "@" in r["reply"],
      "sin token no explica de dónde sacarlo")
check("validado" not in r["reply"], "dice que validó un bot que no existe")

print("== 9) SKILL.md: sin datos del usuario y sin promesas falsas ==")
doc = (SK.doc or "")
check("--remove-orphans" in doc and "sin" in doc.lower(),
      "el SKILL.md no aclara que no se borran huérfanos")
check("pregunta antes" in doc or "te pregunta antes" in doc,
      "el SKILL.md no menciona las confirmaciones")
check("Qué NO hace" in doc, "el SKILL.md no dice qué NO hace")
for propio in ("Adri", "achoz", "D:\\LLMs", "D:\\Modelos"):
    check(propio not in doc, f"el SKILL.md nombra algo del usuario: {propio}")

print(f"\n{'#'*54}\n{_pass} comprobaciones OK, {len(_fail)} fallos")
for m in _fail:
    print("  -", m)
sys.exit(1 if _fail else 0)
