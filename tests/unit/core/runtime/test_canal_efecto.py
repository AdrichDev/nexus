# -*- coding: utf-8 -*-
"""T8a: matriz canal × efecto (SEC-01 / SEC-06, ARQ-01 / ARQ-03, roadmap P2-1).

Hasta ahora `comun/canales.py` solo sabía una cosa: un canal restringido (n8n)
solo ejecuta los pares `carpeta/intent` de su lista blanca. Eso no distingue un
canal que LEE de uno que ESCRIBE, ni un envío externo de un borrado. La auditoría
pedía una política central: el vocabulario de efectos, la clase de canal y el
veredicto (`permitir` / `confirmar` / `denegar`), decididos en UN sitio y no
repartidos por cada skill.

Las decisiones del dueño están en `odd/tasks/security-audit-remediation.md` L59:

    efecto          local       remoto      restringido (n8n)
    read            permitir    permitir    solo si está en la lista blanca
    write_local     permitir    permitir    denegar
    external_send   permitir    confirmar   denegar
    destructive     confirmar   confirmar   denegar

Y un intent SIN efecto declarado se trata como `destructive` (lo prudente: si
nadie dijo qué hace, se pregunta o se deniega, nunca se ejecuta a ciegas).

Reglas que se comprueban aquí:
  1. el vocabulario y los tres veredictos son los del L59, y el efecto por
     defecto es `destructive`;
  2. `clase_de_canal` clasifica bien y normaliza mayúsculas y espacios;
  3. las 12 celdas de la matriz (4 efectos × 3 clases), con los dos casos del
     `read` restringido (está en la lista / no está);
  4. la intersección de n8n: de la lista blanca Y de lectura;
  5. un efecto desconocido, vacío o None cae en `destructive`;
  6. lo de antes sigue igual: `es_restringido`, `permitido` con la tupla del
     enrutador y el texto exacto de `rechazo` (los usan `brain.py` y dos suites);
  7. el módulo sigue sin importar nada de `core/` (vive en `comun` a propósito).

En proceso y sin tocar nada: `canales` no lee config, ni datos, ni red, ni
escribe un byte. Solo constantes y funciones puras.

Ejecutar:  python tests/unit/core/runtime/test_canal_efecto.py   (desde nexus)
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

_fail = []
_pass = 0

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


from backend.core.comun import canales  # noqa: E402


def _politica(*args, **kwargs):
    """`canales.politica` sin reventar si todavía no existe (así se ve el RED)."""
    fn = getattr(canales, "politica", None)
    if fn is None:
        return "<no existe canales.politica>"
    return fn(*args, **kwargs)


def _clase(*args):
    fn = getattr(canales, "clase_de_canal", None)
    if fn is None:
        return "<no existe canales.clase_de_canal>"
    return fn(*args)


class _Ruta:
    """Lo que devuelve `skills_loader.route`: una tupla con .folder y nombre."""

    def __init__(self, folder, intent):
        self.folder = folder
        self.intent = intent


def _ruta(folder, intent):
    """La forma real de `routed`: (skill, intent, match)."""
    return (_Ruta(folder, intent), intent, None)


# Canales de ejemplo por clase. El vacío y el «job»/«sub» también son locales:
# el operador no está delante, pero el texto tampoco viene de fuera.
_MUESTRAS = {
    "local": [("text", "pc"), ("voice", "pc"), ("text", ""), ("trigger", "job"),
              ("text", "sub"), ("text", "voice")],
    "remoto": [("text", "mobile"), ("voice", "telegram")],
    "restringido": [("n8n", "pc"), ("text", "n8n")],
}

# Verdad de la matriz para local y remoto, tal cual L59.
_MATRIZ = {
    "read": {"local": "permitir", "remoto": "permitir"},
    "write_local": {"local": "permitir", "remoto": "permitir"},
    "external_send": {"local": "permitir", "remoto": "confirmar"},
    "destructive": {"local": "confirmar", "remoto": "confirmar"},
}

# El par que SÍ está en la lista blanca de n8n, y el que no.
_LISTADO = ("instagram", "ig_estado")
_NO_LISTADO = ("mcp_hands", "call")


print("== T8a: vocabulario de efectos y veredictos ==")
check(getattr(canales, "EFECTOS", None) == ("read", "write_local", "external_send", "destructive"),
      f"EFECTOS es la tupla del L59 (dio {getattr(canales, 'EFECTOS', None)!r})")
check(getattr(canales, "EFECTO_POR_DEFECTO", None) == "destructive",
      f"un efecto no declarado se trata como destructive "
      f"(dio {getattr(canales, 'EFECTO_POR_DEFECTO', None)!r})")
check(getattr(canales, "PERMITIR", None) == "permitir",
      f"PERMITIR == 'permitir' (dio {getattr(canales, 'PERMITIR', None)!r})")
check(getattr(canales, "CONFIRMAR", None) == "confirmar",
      f"CONFIRMAR == 'confirmar' (dio {getattr(canales, 'CONFIRMAR', None)!r})")
check(getattr(canales, "DENEGAR", None) == "denegar",
      f"DENEGAR == 'denegar' (dio {getattr(canales, 'DENEGAR', None)!r})")
check(set(getattr(canales, "EFECTOS", ())) >= {"read", "write_local", "external_send", "destructive"},
      "los cuatro efectos del L59 están en EFECTOS")

print("== T8a: clase_de_canal clasifica y normaliza ==")
for esperada, muestras in _MUESTRAS.items():
    for source, channel in muestras:
        check(_clase(source, channel) == esperada,
              f"clase_de_canal({source!r}, {channel!r}) == {esperada!r} "
              f"(dio {_clase(source, channel)!r})")
check(_clase("n8n", "pc") == "restringido",
      f"n8n llega como source='n8n' y el canal es restringido (dio {_clase('n8n', 'pc')!r})")
check(_clase("text", "n8n") == "restringido",
      f"un payload con channel 'n8n' también es restringido (dio {_clase('text', 'n8n')!r})")
for channel in (" Mobile ", "MOBILE", "TELEGRAM", " telegram\t", "\tTelegram "):
    check(_clase("text", channel) == "remoto",
          f"clase_de_canal normaliza {channel!r} como remoto (dio {_clase('text', channel)!r})")
for channel in ("pc", "PC", " voice ", "", "  ", "job", "sub"):
    check(_clase("text", channel) == "local",
          f"clase_de_canal trata {channel!r} como local (dio {_clase('text', channel)!r})")
check(_clase("", "") == "local", "sin source ni channel se decide local (dio "
      f"{_clase('', '')!r})")
check(_clase(None, None) == "local", f"None/None no revienta y es local (dio {_clase(None, None)!r})")
check(_clase(" N8N ", "pc") == "restringido",
      f"el source restringido se normaliza (dio {_clase(' N8N ', 'pc')!r})")

print("== T8a: las 12 celdas de la matriz ==")
for efecto in ("read", "write_local", "external_send", "destructive"):
    for clase, muestras in _MUESTRAS.items():
        esperado = _MATRIZ[efecto].get(clase, "denegar")
        for source, channel in muestras:
            # El `read` restringido es condicional: se prueba en los dos sentidos.
            carpeta, intent = (_LISTADO if efecto == "read" else _NO_LISTADO)
            if clase == "restringido" and efecto == "read":
                valor = _politica(source, channel, efecto, carpeta, intent)
                check(valor == "permitir",
                      f"{efecto} desde {source!r}/{channel!r} con {carpeta}/{intent}: "
                      f"permitir (dio {valor!r})")
                valor = _politica(source, channel, efecto, *_NO_LISTADO)
                check(valor == "denegar",
                      f"{efecto} desde {source!r}/{channel!r} con "
                      f"{'/'.join(_NO_LISTADO)}: denegar (dio {valor!r})")
                continue
            valor = _politica(source, channel, efecto, carpeta, intent)
            check(valor == esperado,
                  f"{efecto} desde {source!r}/{channel!r}: {esperado} (dio {valor!r})")

print("== T8a: la intersección de n8n (lista blanca Y lectura) ==")
for source, channel in _MUESTRAS["restringido"]:
    valor = _politica(source, channel, "read", *_LISTADO)
    check(valor == "permitir",
          f"n8n leyendo un par de su lista: permitir (dio {valor!r})")
    valor = _politica(source, channel, "read", *_NO_LISTADO)
    check(valor == "denegar",
          f"n8n leyendo un par que NO está en su lista: denegar (dio {valor!r})")
    valor = _politica(source, channel, "read")
    check(valor == "denegar",
          f"n8n leyendo sin declarar par: denegar (dio {valor!r})")
    for efecto in ("write_local", "external_send", "destructive"):
        valor = _politica(source, channel, efecto, *_LISTADO)
        check(valor == "denegar",
              f"n8n con un par listado pero efecto {efecto}: denegar (dio {valor!r})")
check(canales._LISTA_BLANCA.get("n8n"), "la lista blanca de n8n sigue existiendo")

print("== T8a: efecto desconocido = None, vacío o mal escrito -> destructive ==")
for raro in (None, "", "   ", "BORRAR", "read_only", "write", 0, 7, [], {}):
    esperado = "confirmar"       # destructive desde el equipo del operador
    valor = _politica("text", "pc", raro)
    check(valor == esperado,
          f"efecto {raro!r} desde local: {esperado} (dio {valor!r})")
    valor = _politica("text", "mobile", raro)
    check(valor == "confirmar",
          f"efecto {raro!r} desde remoto: confirmar (dio {valor!r})")
    valor = _politica("n8n", "pc", raro)
    check(valor == "denegar",
          f"efecto {raro!r} desde n8n: denegar (dio {valor!r})")
valor = _politica("text", "pc", " READ ")
check(valor == "permitir", f"el efecto se normaliza (mayúsculas/espacios) (dio {valor!r})")
valor = _politica("text", "mobile", " Read ")
check(valor == "permitir", f"y también desde remoto (dio {valor!r})")
valor = _politica("text", "mobile", " EXTERNAL_SEND ")
check(valor == "confirmar", f"external_send normalizado desde remoto confirma (dio {valor!r})")

print("== T8a: la API de antes sigue igual (brain.py y dos suites) ==")
check(tuple(canales.CANALES_RESTRINGIDOS) == ("n8n",),
      f"CANALES_RESTRINGIDOS no cambia (dio {canales.CANALES_RESTRINGIDOS!r})")
check(canales.es_restringido("n8n") is True, "es_restringido('n8n') sigue siendo True")
check(canales.es_restringido(" N8N ") is True, "es_restringido normaliza el canal")
check(canales.es_restringido("text") is False, "es_restringido('text') sigue siendo False")
check(canales.es_restringido("mobile") is False, "mobile NO es un canal restringido")
check(canales.es_restringido("") is False, "el canal vacío no está restringido")

_ruta_mcp = _ruta("mcp_hands", "call")
check(canales.permitido("n8n", _ruta_mcp) is False, "permitido('n8n', mcp_hands/call) sigue False")
check(canales.permitido("text", _ruta_mcp) is True, "permitido('text', mcp_hands/call) sigue True")
_ruta_listada = _ruta("instagram", "ig_estado")
check(canales.permitido("n8n", _ruta_listada) is True,
      "permitido('n8n', instagram/ig_estado) sigue True")
check(canales.permitido("n8n", None) is False, "sin ruta no hay permiso en un canal restringido")
check(canales.permitido("text", None) is True,
      "un canal del operador puede con todo (como siempre)")
check(canales.permitido("n8n", _ruta_listada[:2]) is True,
      "solo se usan los dos primeros elementos de la tupla (de siempre)")
check(canales.permitido("n8n", (object(), "ig_estado", None)) is False,
      "una tupla mal formada no revienta y se rechaza")
for folder in ("instagram", "content_os"):
    for intent in ("ig_estado", "ig_analizar", "ideas"):
        par = f"{folder}/{intent}"
        if par in canales._LISTA_BLANCA["n8n"]:
            check(canales.permitido("n8n", _ruta(folder, intent)) is True,
                  f"el par listado {par} sigue pasando")
            check(_politica("n8n", "pc", "read", folder, intent) == "permitir",
                  f"y la matriz lo deja LEER ({par})")

_esperado_rechazo = {"reply": "Esa orden no está permitida desde n8n.",
                     "skill": None, "provider": "canal", "data": None}
check(canales.rechazo("n8n") == _esperado_rechazo,
      f"rechazo('n8n') devuelve el texto exacto de siempre (dio {canales.rechazo('n8n')!r})")

print("== T8a: el módulo no importa nada de core/ (vive en comun) ==")
_arbol = ast.parse((ROOT / "backend" / "core" / "comun" / "canales.py").read_text(encoding="utf-8"))
_imports = []
for _nodo in ast.walk(_arbol):
    if isinstance(_nodo, ast.Import):
        _imports.extend(_alias.name for _alias in _nodo.names)
    elif isinstance(_nodo, ast.ImportFrom):
        _imports.append("." * (_nodo.level or 0) + (_nodo.module or ""))
_malos = [n for n in _imports
          if n.startswith(".") or n.startswith("backend") or n.split(".")[0] == "core"]
check(_malos == [], f"canales.py solo usa la biblioteca estándar (imports de más: {_malos!r})")

print(f"\n{_pass} OK / {len(_fail)} FALLOS")
sys.exit(1 if _fail else 0)
