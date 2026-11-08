# -*- coding: utf-8 -*-
"""T8b: cada skill declara el EFECTO de sus intents (SEC-01 / SEC-06, ARQ-01 / ARQ-03).

T8a (`comun/canales.py`) dejó escrito el vocabulario y la matriz canal × efecto:
`read`, `write_local`, `external_send`, `destructive`, y un veredicto
(`permitir` / `confirmar` / `denegar`) por clase de canal. Pero la matriz no sabe
qué hace cada intent: eso solo lo sabe la skill. Y un intent SIN efecto declarado
cuenta como `destructive` (EFECTO_POR_DEFECTO), así que sin declaraciones la
matriz no puede distinguir un correo que sale de una consulta que no toca nada.

Por eso cada skill que enruta declara, en su propio `SKILL`:

    "effects": {intent: nivel}    # TODOS los intents de `patterns`, sin sobras
    "confirma": (intent, ...)     # los que YA preguntan (confirm.request)

`confirma` existe para que `brain` (T8c) no pregunte dos veces lo que la skill ya
pregunta. Por eso solo lista intents cuyo handler LLAMA a `confirm.request` antes
de su efecto, y por eso un intent de solo lectura nunca va ahí.

Lo que se comprueba aquí, para las 32 carpetas de `skills/` que enrutan:

  1. el contrato del `SKILL` (name, description, patterns, effects, confirma);
  2. COMPLETITUD: los intents de `effects` son EXACTAMENTE los de `patterns` —
     ni uno sin declarar (caería en `destructive` por defecto, que es preguntar
     de más o denegar de más) ni uno inventado (una errata que no enruta nunca);
  3. el nivel está en `canales.EFECTOS` (y el módulo sigue siendo la única
     fuente del vocabulario: no hay listas paralelas aquí);
  4. `confirma` ⊆ `effects`, sin ningún intent de lectura, y cada skill con
     `confirma` no vacío tiene `confirm.request` en su código (si no, promete una
     pregunta que no hace);
  5. las clasificaciones que el dueño decidió en `odd/tasks/security-audit-remediation.md`
     L59, clavadas una por una (un envío de correo, una tele que se apaga, un
     borrado, una tarea del tablero, una búsqueda, WhatsApp, Hermes, MCP...);
  6. los tres pares de la lista blanca de n8n siguen siendo de LECTURA: la lista
     es una INTERSECCIÓN (listado Y de lectura, `canales.politica`), así que
     declarar `write_local` un par listado lo cerraría por la puerta de atrás.

En proceso y sin tocar nada: se lee el FUENTE de cada `skill.py` con `ast` (nada
de importar 32 skills ni de leer el `settings.json`/`data/` del operador) y
config/datos apuntan a carpetas de usar y tirar ANTES de importar el backend.
`comun/canales.py` no lee config, ni datos, ni red: son constantes y funciones
puras.

Ejecutar:  python tests/unit/core/runtime/test_efectos_declarados.py   (desde nexus)
"""
import ast
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

_fail = []
_pass = 0

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Hermetismo ANTES de tocar el backend: ni config, ni datos, ni `.env` del
# operador (T44). Carpetas de usar y tirar que se borran al terminar.
_TMP = []
for _var in ("NEXUS_CONFIG_DIR", "NEXUS_DATA_DIR"):
    _dir = tempfile.mkdtemp(prefix="nexus_efectos_")
    _TMP.append(_dir)
    os.environ[_var] = _dir
os.environ["NEXUS_DOTENV"] = "0"


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


from backend.core.comun import canales  # noqa: E402


# ── Lector de `SKILL` por AST: el literal, sin ejecutar la skill ─────────────
# Las regex de `patterns` se escriben como sumas de cadenas y constantes
# (BinOp/Name), así que de ahí solo se leen las CLAVES: los valores importan al
# enrutador, no a este contrato.
_SOLO_CLAVES = ("patterns", "intents")


def _literal(nodo, que):
    """El valor de un literal de Python (dict / set / tuple / list / str)."""
    if isinstance(nodo, ast.Dict):
        salida = {}
        for clave, valor in zip(nodo.keys, nodo.values):
            k = _literal(clave, que)
            if k in _SOLO_CLAVES and isinstance(valor, ast.Dict):
                salida[k] = {_literal(c, que): "" for c in valor.keys}
                continue
            salida[k] = _literal(valor, que)
        return salida
    if isinstance(nodo, (ast.Set, ast.Tuple, ast.List)):
        items = [_literal(e, que) for e in nodo.elts]
        return tuple(items) if isinstance(nodo, ast.Tuple) else items
    if isinstance(nodo, ast.Constant):
        return nodo.value
    raise ValueError(f"{que}: no es un literal ({type(nodo).__name__}, "
                     f"línea {getattr(nodo, 'lineno', '?')})")


def _leer_skill(py: Path) -> dict:
    """El `SKILL` de una skill, leído del fuente. {} si no hay ninguno."""
    arbol = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
    for nodo in arbol.body:
        if isinstance(nodo, ast.Assign) and any(
                getattr(t, "id", "") == "SKILL" for t in nodo.targets):
            try:
                return _literal(nodo.value, f"{py.name}:SKILL")
            except ValueError as exc:
                print(f"  AVISO: {py.parent.name}: {exc}")
                return {}
    return {}


CARPETAS = sorted(p.name for p in (ROOT / "skills").iterdir()
                  if (p / "skill.py").exists())
SKILLS = {}
RUTAS = {}
for nombre in CARPETAS:
    py = ROOT / "skills" / nombre / "skill.py"
    RUTAS[nombre] = py
    SKILLS[nombre] = _leer_skill(py)

CON_PATRONES = [n for n in CARPETAS if SKILLS[n].get("patterns")]

print("== T8b: el vocabulario es el de `canales`, no una lista paralela ==")
check(tuple(canales.EFECTOS) == ("read", "write_local", "external_send", "destructive"),
      f"canales.EFECTOS sigue siendo el vocabulario de T8a (dio {canales.EFECTOS!r})")
check(canales.EFECTO_POR_DEFECTO in canales.EFECTOS,
      "el efecto por defecto está en el vocabulario")

print("== T8b: 32 skills con patrones (el censo que se audita) ==")
check(len(CON_PATRONES) >= 30,
      f"hay al menos 30 carpetas de skill con patrones (hay {len(CON_PATRONES)}: "
      f"{CON_PATRONES})")
_TOTAL_INTENTS = sum(len(SKILLS[n]["patterns"]) for n in CON_PATRONES)
check(_TOTAL_INTENTS >= 200,
      f"los intents declarados en `patterns` pasan de 200 (hay {_TOTAL_INTENTS})")

# ── 1-4) el contrato, skill por skill ───────────────────────────────────────
for nombre in CON_PATRONES:
    meta = SKILLS[nombre]
    intents = set(meta["patterns"])
    fuente = RUTAS[nombre].read_text(encoding="utf-8")

    for clave in ("name", "description", "patterns", "effects", "confirma"):
        check(isinstance(meta.get(clave), (dict, str, list, tuple)),
              f"{nombre}: SKILL declara «{clave}» "
              f"(dio {type(meta.get(clave)).__name__})")

    effects = meta.get("effects")
    if not isinstance(effects, dict):
        check(False, f"{nombre}: SKILL['effects'] es un diccionario {{intent: nivel}} "
                     f"(dio {effects!r})")
        continue

    declarados = set(effects)
    faltan = sorted(intents - declarados)
    sobran = sorted(declarados - intents)
    check(not faltan,
          f"{nombre}: todos los intents de patterns declaran efecto (sin declarar: "
          f"{faltan} — caerían en «{canales.EFECTO_POR_DEFECTO}» por defecto)")
    check(not sobran,
          f"{nombre}: no hay claves inventadas en effects (sobran: {sobran})")

    malos = sorted(f"{i}={effects[i]!r}" for i in declarados
                   if effects[i] not in canales.EFECTOS)
    check(not malos,
          f"{nombre}: cada nivel está en canales.EFECTOS (fuera: {malos})")

    confirma = meta.get("confirma")
    if not isinstance(confirma, (list, tuple, set)):
        check(False, f"{nombre}: SKILL['confirma'] es una tupla/set de intents "
                     f"(dio {confirma!r})")
        continue
    confirma = set(confirma)
    fuera = sorted(confirma - declarados)
    check(not fuera,
          f"{nombre}: confirma ⊆ effects (fuera: {fuera})")
    lecturas = sorted(i for i in confirma if effects.get(i) == "read")
    check(not lecturas,
          f"{nombre}: un intent de solo lectura nunca está en confirma (sobran: {lecturas})")
    if confirma:
        # La LLAMADA, no la mención: `confirm.request(...)` o el alias con el que
        # la importan (hermes y MCP usan `_cf.request(...)`).
        _pregunta = re.search(r"\b(?:confirm|_cf|_confirm|cf)\.request\(", fuente)
        check(_pregunta is not None,
              f"{nombre}: declara confirma {sorted(confirma)} y su código llama a "
              "confirm.request (si no, promete una pregunta que no hace)")

# ── 5) las clasificaciones del L59, clavadas ────────────────────────────────
print("== T8b: clasificaciones fijadas (decisiones del dueño, L59) ==")
FIJADAS = [
    # (carpeta, intent, nivel, por qué)
    ("google_workspace", "send_email", "external_send", "un correo sale del equipo"),
    ("n8n_flows", "whatsapp", "external_send", "un WhatsApp llega a una persona"),
    ("discord", "notify", "external_send", "un mensaje se publica en un canal"),
    ("domotica", "tv_off", "external_send", "apagar la tele es controlar un aparato"),
    ("domotica", "wol", "external_send", "un paquete mágico enciende una máquina"),
    ("media", "play", "external_send", "poner música es controlar la reproducción"),
    ("hermes", "hermes", "external_send", "delegar es entregar el trabajo fuera"),
    ("mcp_hands", "call", "external_send", "una herramienta MCP actúa por su cuenta"),
    ("system_pc", "kill", "external_send", "cerrar un programa es actuar en el equipo"),
    ("google_workspace", "drive_upload", "external_send", "subir a Drive es sacar el archivo"),
    ("google_workspace", "create_event", "external_send",
     "crear un evento toca el calendario del operador"),
    ("engram", "forget_rule", "destructive", "olvidar una regla no se deshace"),
    ("memory_graph", "olvidar", "destructive", "la purga borra recuerdos del operador"),
    ("files", "trash", "destructive", "un archivo fuera de su sitio es un borrado"),
    ("tasks_board", "delete", "destructive", "borrar una tarea la saca del tablero"),
    ("google_workspace", "delete_email", "destructive", "un correo a la papelera es un borrado"),
    ("google_workspace", "drive_delete", "destructive", "un archivo de Drive puede no volver"),
    ("telefono", "del_contact", "destructive", "un contacto borrado no se recupera"),
    ("system_pc", "shutdown", "destructive", "apagar el equipo corta la sesión"),
    ("system_pc", "restart", "destructive", "reiniciar el equipo corta la sesión"),
    ("tasks_board", "create", "write_local", "una tarea escribe el tablero"),
    ("tools", "note", "write_local", "una nota escribe la nota diaria"),
    ("memory_graph", "remember", "write_local", "recordar escribe la memoria"),
    ("files", "mkdir", "write_local", "crear una carpeta escribe en el disco"),
    ("ai_media", "web_search", "read", "buscar en internet es leer"),
    ("google_workspace", "emails", "read", "listar correos es leer"),
    ("system_pc", "volume_ask", "read", "preguntar de qué es el volumen no toca nada"),
    ("tools", "ping", "read", "un ping es leer el enlace"),
]
for carpeta, intent, nivel, por_que in FIJADAS:
    _effects = SKILLS.get(carpeta, {}).get("effects")
    _effects = _effects if isinstance(_effects, dict) else {}
    check(_effects.get(intent) == nivel,
          f"{carpeta}/{intent} = {nivel} ({por_que}); dio {_effects.get(intent)!r}")

# ── 6) la lista blanca de n8n solo lleva pares de LECTURA ───────────────────
print("== T8b: la intersección de n8n sigue siendo de lectura ==")
_LISTA = getattr(canales, "_LISTA_BLANCA", {})
for canal, pares in _LISTA.items():
    for par in sorted(pares):
        carpeta, _, intent = par.partition("/")
        _effects = SKILLS.get(carpeta, {}).get("effects")
        _effects = _effects if isinstance(_effects, dict) else {}
        check(_effects.get(intent) == "read",
              f"{canal}: el par listado {par} está declarado «read» (dio "
              f"{_effects.get(intent)!r}) — si no, la intersección lo deniega")

# ── Resumen por nivel (lo que este test APORTA, no solo lo que niega) ───────
print("== T8b: resumen de efectos declarados ==")
_conteo = {nivel: 0 for nivel in canales.EFECTOS}
_por_skill = {}
for nombre in CON_PATRONES:
    effects = SKILLS[nombre].get("effects")
    if not isinstance(effects, dict):
        continue
    cuenta = {nivel: 0 for nivel in canales.EFECTOS}
    for intent, nivel in effects.items():
        if nivel in _conteo:
            _conteo[nivel] += 1
            cuenta[nivel] += 1
    _por_skill[nombre] = cuenta
for nivel in canales.EFECTOS:
    print(f"  {nivel:<14} {_conteo[nivel]:>4} intent(s)")
print(f"  {'TOTAL':<14} {sum(_conteo.values()):>4}")
check(all(v > 0 for v in _conteo.values()),
      f"los cuatro niveles se usan de verdad (dio {_conteo})")

_CON_CONFIRMA = sorted(n for n in CON_PATRONES
                       if set(SKILLS[n].get("confirma") or ()))
print(f"  skills con confirma: {len(_CON_CONFIRMA)}")
for nombre in _CON_CONFIRMA:
    print(f"    · {nombre}: {sorted(set(SKILLS[nombre]['confirma']))}")

_DESTRUCTIVOS = sorted(f"{n}/{i}" for n in CON_PATRONES
                       if isinstance(SKILLS[n].get("effects"), dict)
                       for i, nivel in SKILLS[n]["effects"].items()
                       if nivel == "destructive")
print(f"  destructivos ({len(_DESTRUCTIVOS)}): " + ", ".join(_DESTRUCTIVOS))

# Un nivel que no usa nadie suele ser una clasificación perezosa: si TODO fuera
# `read` o todo `external_send`, la matriz no protegería nada.
check(len(_DESTRUCTIVOS) >= 5,
      f"hay al menos 5 intents destructivos declarados (hay {len(_DESTRUCTIVOS)})")

for _dir in _TMP:
    shutil.rmtree(_dir, ignore_errors=True)

print(f"\n{_pass} OK / {len(_fail)} FALLOS")
sys.exit(1 if _fail else 0)
