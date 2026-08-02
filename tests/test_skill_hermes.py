# -*- coding: utf-8 -*-
"""Auditoría de la skill HERMES: activación, enrutado real, cobertura de intents,
imports bajo el cargador de verdad y honestidad cuando no hay nada montado.

No arranca el gateway de Hermes, no lanza encargos y no toca la configuración del
usuario: la red se sustituye por dobles y HERMES_HOME apunta a un temporal.

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_skill_hermes.py
"""
from __future__ import annotations

import ast
import asyncio
import importlib
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_fail = []
_pass = 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  ✖ " + msg)


SKILL_PY = os.path.join(ROOT, "skills", "hermes", "skill.py")

# ---------------------------------------------------------------- 1) cargador real
print("== 1) la skill carga como la carga nexus (skills_loader) ==")
from backend.core import skills_loader as sl              # noqa: E402

REG = sl.load_skills()
hsk = REG.get("hermes")
check(hsk is not None, "skills_loader no registra la carpeta 'hermes'")
check(hsk is not None and hsk.status != "error",
      f"la skill hermes no carga: {hsk.description if hsk else ''}")
mod = hsk.module if hsk else None
check(mod is not None, "hermes no expone módulo")
INTENTS = list(mod.SKILL["patterns"].keys()) if mod else []
check(set(INTENTS) == set(hsk.patterns.keys()) if hsk else False,
      "los intents registrados no coinciden con SKILL['patterns']")

# ---------------------------------------------- 2) imports (incluidos los diferidos)
print("== 2) todos los imports resuelven (nada de 'from . import <hermano>') ==")
_tree = ast.parse(open(SKILL_PY, encoding="utf-8").read())
_relativos, _modulos = [], set()
for node in ast.walk(_tree):
    if isinstance(node, ast.ImportFrom):
        if (node.level or 0) > 0:
            _relativos.append(f"línea {node.lineno}: from {'.' * node.level}{node.module or ''}")
        elif node.module:
            _modulos.add(node.module)
    elif isinstance(node, ast.Import):
        for a in node.names:
            _modulos.add(a.name)
check(not _relativos,
      "imports RELATIVOS en skill.py (revientan con el cargador real): " + "; ".join(_relativos))
for name in sorted(_modulos):
    if name == "__future__":
        continue
    try:
        importlib.import_module(name)
    except Exception as exc:                                # noqa: BLE001
        check(False, f"import diferido roto: {name} -> {type(exc).__name__}: {exc}")
# los símbolos concretos que la skill saca de esos módulos
try:
    from backend.core import engram_bridge as _eng
    from backend.core import publicvoice as _pv
    from backend.core.jobs import jobs as _jobs
    from backend.core.memory import pg as _pg
    check(hasattr(_pv, "frase_inicio") and hasattr(_pv, "mensaje_fallo"),
          "publicvoice no tiene frase_inicio/mensaje_fallo")
    check(hasattr(_eng, "installed") and hasattr(_eng, "_engram_exe") and hasattr(_eng, "PROJECT"),
          "engram_bridge no tiene installed/_engram_exe/PROJECT")
    check(hasattr(_jobs, "submit") and hasattr(_jobs, "active_duplicate") and hasattr(_jobs, "active"),
          "jobs no tiene submit/active_duplicate/active")
    check(hasattr(_pg, "remember"), "memory.pg no tiene remember")
except Exception as exc:                                    # noqa: BLE001
    check(False, f"no resuelven los símbolos que usa hermes: {exc}")

# --------------------------------------------------------------- 3) activación real
print("== 3) activación con frases naturales (enrutador real) ==")
FRASES = {
    "hermes_estado": [
        "¿está hermes conectado?", "esta hermes conectado", "hermes está conectado?",
        "diagnostica hermes", "diagnóstica hermes", "diagnostícame hermes",
        "estado de hermes", "diagnóstico de hermes", "¿qué tal va hermes?",
        "¿cómo va hermes?", "como esta hermes", "revisa hermes",
        "revísame la conexión con hermes", "comprueba la conexión con hermes",
        "¿sigue hermes vivo?", "¿hermes funciona?", "¿funciona hermes?",
        "hermes está caído", "¿hermes está bien?", "¿va bien hermes?",
        "hazme un diagnóstico de hermes",
    ],
    "hermes_arranca": [
        "arranca hermes", "arranca a hermes", "arráncame hermes", "arrancame hermes",
        "reinicia hermes", "reiníciame hermes", "relanza hermes",
        "levanta hermes", "levántame hermes", "enciende hermes", "enciéndeme hermes",
        "pon hermes en marcha", "ponme hermes en marcha", "lanza hermes",
        "lánzame hermes", "vuelve a arrancar hermes", "inicia hermes",
        "reinicia el gateway de hermes", "arranca el gateway de hermes",
        "conecta hermes", "despierta hermes",
    ],
    "hermes_info": [
        "¿qué sabe hacer hermes?", "que sabe hacer hermes", "¿qué puede hacer hermes?",
        "para qué sirve hermes", "qué es hermes", "¿qué skills tiene hermes?",
        "capacidades de hermes", "¿qué herramientas tiene hermes?",
        "¿de qué es capaz hermes?", "dime qué sabe hacer hermes",
    ],
    "hermes_resultado": [
        "¿y la respuesta de hermes?", "la respuesta de hermes",
        "¿qué ha averiguado hermes?", "¿ha terminado ya hermes?",
        "¿hermes ha terminado?", "¿ya terminó hermes?", "¿acabó ya hermes?",
        "novedades de hermes", "encargo #3", "resultado del encargo 2",
        "cómo va el encargo 1", "¿qué te ha dicho hermes?", "¿qué me ha dicho hermes?",
        "enséñame el resultado de hermes", "dame el informe de hermes",
        "cómo van los encargos de hermes", "dime qué ha encontrado hermes",
    ],
    "hermes_tarea": [
        "mándale una tarea a hermes: resume las noticias del día",
        "mandale una tarea a hermes",
        "envíale un encargo a hermes: busca proveedores",
        "dale trabajo a hermes", "pásale una tarea a hermes",
        "asígnale una misión a hermes: investiga el mercado",
        "manda una tarea a hermes", "encomiéndale un recado a hermes",
        "mándale otra tarea a hermes",
    ],
    "hermes": [
        "hermes: investiga la competencia y hazme un informe",
        "hermes, busca proveedores de cajas de cartón",
        "dile a hermes que busque proveedores",
        "dile a hermes que me busque proveedores",
        "dile a hermes: investiga esto",
        "pídele a hermes que compare precios",
        "mándale a hermes que compare precios de portátiles",
        "encárgale a hermes que investigue el mercado",
        "encarga a hermes que investigue el mercado",
        "ordénale a hermes que rastree la web",
        "delega en hermes la investigación de mercado",
        "que hermes investigue la competencia",
    ],
}
check(set(FRASES) == set(INTENTS),
      f"hay intents sin frases de prueba: {sorted(set(INTENTS) - set(FRASES))}")
for esperado, frases in FRASES.items():
    for f in frases:
        r = sl.route(f)
        destino = f"{r[0].folder}/{r[1]}" if r else "NADA (cae al planificador)"
        check(bool(r) and r[0].folder == "hermes" and r[1] == esperado,
              f"«{f}» debía ir a hermes/{esperado} y fue a {destino}")

# --------------------------------------------------------------- 4) no roba frases
print("== 4) no se queda con frases que no son suyas ==")
AJENAS = [
    "qué tal va el día", "arranca chrome", "estado del tablero",
    "qué sabes hacer", "manda un correo a Ana", "reinicia el ordenador",
    "novedades del tablero", "cómo va el proyecto", "enciende la tele",
    "investiga la competencia y hazme un informe",
]
for f in AJENAS:
    r = sl.route(f)
    check(not r or r[0].folder != "hermes",
          f"hermes se queda con «{f}», que no menciona a hermes")
# toda regex de hermes exige la palabra literal: sin ella no puede activarse
for intent, rx in (hsk.patterns.items() if hsk else []):
    check("hermes" in mod.SKILL["patterns"][intent].lower(),
          f"el patrón de {intent} no exige la palabra «hermes»")

# ----------------------------------------- 5) ningún intent se pierde en el reparto
print("== 5) _ADMIN + _handle_publico cubren TODOS los intents ==")
ADMIN = set(mod._ADMIN) if mod else set()
check(ADMIN <= set(INTENTS), f"_ADMIN nombra intents que no existen: {sorted(ADMIN - set(INTENTS))}")


class _FakeSettings:
    """Doble de settings: ni lee ni escribe config/. hermes_autostart apagado para
    que ninguna prueba lance el gateway de verdad."""

    def __init__(self):
        self.data = {"hermes_url": "http://127.0.0.1:8642", "hermes_autostart": False}

    def get(self, k, d=None):
        return self.data.get(k, d)

    def set(self, k, v):
        self.data[k] = v

    def secret(self, k):
        return ""

    def set_secret(self, k, v):
        self.data["secret:" + k] = v


async def _no(*a, **k):
    return False


async def _si(*a, **k):
    return True


def _instalar_dobles():
    """Todo caído y nada instalado: el peor escenario, sin red ni ficheros del usuario."""
    mod._alive = _no
    mod._port_open = _no
    mod._auth_ok = _si
    mod.installed = lambda ctx: False
    mod._hermes_exe = lambda ctx: ""          # diagnose() mira el exe, no installed()
    mod._reg_load = lambda: []
    mod._reg_save = lambda items: None
    mod.provision_engram_mcp = lambda ctx: (False, "doble de prueba")
    mod._gateway_log_tail = lambda n=12: ""

    async def _cerebro(ctx):
        return "down", "sin gateway"
    mod._probe_brain = _cerebro


os.environ["HERMES_HOME"] = tempfile.mkdtemp(prefix="hermes_test_")
_instalar_dobles()
CTX = {"settings": _FakeSettings(), "channel": "pc"}


def _responder(intent, texto):
    r = sl.route(texto)
    assert r and r[1] == intent, f"la frase de prueba de {intent} ya no enruta"
    return asyncio.run(mod.handle(intent, texto, r[2], CTX))


RESPUESTAS = {}
for intent, frases in FRASES.items():
    try:
        RESPUESTAS[intent] = _responder(intent, frases[0])
    except Exception as exc:                                # noqa: BLE001
        check(False, f"handle('{intent}') revienta sin gateway: {type(exc).__name__}: {exc}")
        RESPUESTAS[intent] = {}
for intent in INTENTS:
    rep = (RESPUESTAS.get(intent) or {}).get("reply", "")
    check(bool(rep.strip()), f"el intent {intent} no devuelve respuesta (se pierde en el reparto)")
    check("no la tengo" not in rep,
          f"el intent {intent} cae en el 'no la tengo' de _handle_admin")
    check(bool(RESPUESTAS.get(intent, {}).get("admin")) == (intent in ADMIN),
          f"el intent {intent} no marca admin como debe (admin={intent in ADMIN})")

# --------------------------------------------------------------- 6) falla honesto
print("== 6) sin ejecutable, sin clave y sin gateway: dice QUÉ falta y CÓMO se arregla ==")
est = RESPUESTAS["hermes_estado"]["reply"]
check("SIN CONEXIÓN" in est, "el estado no dice que no hay conexión")
check("no encuentro Hermes instalado" in est,
      "el estado no da la causa concreta (Hermes no instalado)")
check("hermes-agent.nousresearch.com" in est, "el estado no dice de dónde se instala")
check("✔ CONECTADO" not in est, "el estado se inventa una conexión que no existe")

arr = RESPUESTAS["hermes_arranca"]["reply"]
check("No he podido" in arr, "«arranca hermes» no admite que no ha podido")
check("diagnostica hermes" in arr, "«arranca hermes» no dice cómo seguir")
check("ARRIBA" not in arr, "«arranca hermes» canta un arranque que no ha ocurrido")

inf = RESPUESTAS["hermes_info"]["reply"]
check("no tengo línea con Hermes" in inf, "«qué sabe hacer hermes» no dice que está sin línea")
check("conectado ✔" not in inf, "«qué sabe hacer hermes» finge estar conectado")
check("Según su documentación" in inf,
      "el resumen de capacidades no se presenta como documentación (parecería consulta en vivo)")

res = RESPUESTAS["hermes_resultado"]["reply"]
check("No tengo encargos" in res, "sin registro, «¿y la respuesta de hermes?» debería decirlo")
check("✔" not in res, "sin encargos, la respuesta enseña un resultado que no existe")

for intent in ("hermes", "hermes_tarea"):
    rep = RESPUESTAS[intent]["reply"]
    check("No puedo ponerme con eso" in rep,
          f"{intent} sin Hermes instalado no avisa de que no puede")
    check("diagnostica hermes" in rep, f"{intent} no ofrece salida al usuario")
# la salida que ofrece TIENE que enrutar de verdad
r = sl.route("diagnostica hermes")
check(bool(r) and r[0].folder == "hermes" and r[1] == "hermes_estado",
      "la skill remite a «diagnostica hermes» pero esa frase no enruta a ningún sitio")

# ------------------------------------------- 7) no da por bueno lo que no lo es
print("== 7) no se inventa resultados ==")
check(mod.respuesta_es_error("HTTP 400: Your organization must be verified") != "",
      "una respuesta 200 con un error dentro se daría por buena")
check(mod.respuesta_es_error("Missing Authentication header") != "",
      "un 'Missing Authentication header' en el texto se daría por bueno")
check(mod.respuesta_es_error("") != "", "una respuesta vacía se daría por buena")
check(mod.respuesta_es_error("Aquí tienes el informe de proveedores: ...") == "",
      "una respuesta buena se marca como error")
check(mod._is_upstream_auth_error(401, "Missing Authentication header"),
      "no distingue el 401 del modelo interno de Hermes")
check(not mod._is_upstream_auth_error(401, '{"error":"invalid_api_key"}'),
      "confunde nuestra clave del gateway con el modelo interno")
check(not mod._is_upstream_auth_error(500, "boom"), "un 5xx no es un fallo de credenciales")
check(mod._key_strong("a" * 32) and not mod._key_strong("corta")
      and not mod._key_strong("change-me-please-now"),
      "_key_strong no filtra claves débiles o de plantilla")

# ------------------------------------------------------------------ 8) agnóstica
print("== 8) agnóstica: sin nombres propios ni datos del usuario ==")
_src = open(SKILL_PY, encoding="utf-8").read()
_md = open(os.path.join(ROOT, "skills", "hermes", "SKILL.md"), encoding="utf-8").read()
for aguja in ("Adri", "achoz", "C:\\Users\\", "D:\\Adrian"):
    check(aguja not in _src, f"skill.py contiene «{aguja}»")
    check(aguja not in _md, f"SKILL.md contiene «{aguja}»")

# ------------------------------------------ 9) SKILL.md: sus frases se activan
print("== 9) las frases que promete SKILL.md se activan de verdad ==")
import re as _re                                            # noqa: E402

# solo las frases de la TABLA de intents: son las que SKILL.md vende como órdenes
_filas = [ln for ln in _md.splitlines() if ln.startswith("| `hermes")]
check(len(_filas) == len(INTENTS), "la tabla de SKILL.md no lista todos los intents")
_prometidas = [(m.group(1), ln) for ln in _filas for m in _re.finditer(r"«([^»]+)»", ln)]
for frase, fila in _prometidas:
    esperado = fila.split("`")[1]
    r = sl.route(frase)
    check(bool(r) and r[0].folder == "hermes" and r[1] == esperado,
          f"SKILL.md promete «{frase}» como {esperado} pero va a "
          + (f"{r[0].folder}/{r[1]}" if r else "ningún sitio"))

print(f"\n{'#' * 54}\ntest_skill_hermes: {_pass} OK, {len(_fail)} fallos")
if _fail:
    for f in _fail:
        print("  - " + f)
sys.exit(1 if _fail else 0)
