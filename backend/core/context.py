"""
nexus — CONTEXTO MULTI-TURNO (v20): «llama al segundo», «borra la 3», «el último».

Cuando nexus muestra una LISTA (pestañas, contactos, informes, vigilancias,
encargos, tareas), este módulo se queda con los elementos y su orden. Si la
siguiente orden es una referencia («el segundo», «abre la 3», «ese último»),
la traduce a la orden completa ANTES del router, con una plantilla según la
skill que produjo la lista:

  chrome/tabs        → «resume|lee|cierra|cambia a la pestaña N»
  telefono/contactos → «llama a <nombre>»
  research/informes  → «abre el informe de <nombre>»
  vigilancias/lista  → «borra la vigilancia N» (o «mis vigilancias»)
  hermes/encargos    → «resultado del encargo N»
  tasks_board/show   → la frase original con el ordinal sustituido por el título

El contexto caduca a los 10 minutos y solo actúa sobre frases cortas con
referencia clara — nada de adivinar.
"""
from __future__ import annotations

import re
import time

_TTL = 600           # segundos de vida del contexto de lista
# Estado POR CANAL (pc | mobile | telegram…): la lista que viste en el PC no
# debe resolver referencias llegadas por Telegram (revisión v20).
_channels: dict = {}


def _state_for(channel: str) -> dict:
    return _channels.setdefault(channel or "pc",
                                {"source": "", "intent": "", "items": [], "ts": 0.0})

# ── extracción de elementos de una respuesta ──────────────────────────────────

_NUMBERED_RX = re.compile(r"^\s*(\d{1,2})[.)]\s+(.{3,})$")           # «1. Cosa»
_HASH_RX = re.compile(r"^\s*[^\w\s]{0,3}\s*#(\d{1,3})\s+(.{3,})$")   # «🌐 #2 cosa»
_BULLET_RX = re.compile(r"^\s*[•·]\s+(.{3,})$")                      # «• Cosa»


def _clean_item(s: str) -> str:
    """Limpia un elemento de lista: fuera iconos, y corta en — · → ( se queda el título."""
    s = re.sub(r"[^\w\s#(]*", "", s, count=1).strip()
    s = re.split(r"\s+(?:—|·|→|\(|\bvence\b|\bvenció\b)\s*", s)[0]
    return s.strip(" .«»\"'")[:80]


def note_reply(source: str, intent: str, reply: str, channel: str = "pc") -> None:
    """Registra los elementos listados en la respuesta de una skill (si los hay)."""
    try:
        _state = _state_for(channel)
        items: list[tuple[int, str]] = []
        order = 0
        for line in (reply or "").splitlines():
            m = _NUMBERED_RX.match(line)
            if m:
                items.append((int(m.group(1)), _clean_item(m.group(2))))
                continue
            m = _HASH_RX.match(line)
            if m:
                items.append((int(m.group(1)), _clean_item(m.group(2))))
                continue
            m = _BULLET_RX.match(line)
            if m:
                order += 1
                items.append((order, _clean_item(m.group(1))))
        items = [(n, t) for n, t in items if t]
        if len(items) >= 2:
            _state.update({"source": source, "intent": intent,
                           "items": items, "ts": time.time()})
    except Exception:
        pass


# ── resolución de referencias ─────────────────────────────────────────────────

_ORDS = {"primero": 1, "primera": 1, "primer": 1, "segundo": 2, "segunda": 2,
         "tercero": 3, "tercera": 3, "tercer": 3, "cuarto": 4, "cuarta": 4,
         "quinto": 5, "quinta": 5, "sexto": 6, "sexta": 6,
         "séptimo": 7, "septimo": 7, "octavo": 8}

_REF_RX = re.compile(
    r"\b(?:el|la|al|del|ese|esa)\s+(?P<ord>primer[oa]?|segund[oa]|tercer[oa]?|"
    r"cuart[oa]|quint[oa]|sext[oa]|s[eé]ptim[oa]|octav[oa]|[uú]ltim[oa]|"
    r"n[uú]mero\s+\d{1,2}|\d{1,2})\b",
    re.IGNORECASE)


def _ref_num(text: str, n_items: int) -> tuple[int, re.Match] | tuple[None, None]:
    m = _REF_RX.search(text)
    if not m:
        return None, None
    raw = m.group("ord").lower()
    if raw.startswith(("últim", "ultim")):
        return n_items, m
    mnum = re.search(r"\d{1,2}", raw)
    if mnum:
        n = int(mnum.group(0))
    else:
        n = 0
        for k, v in _ORDS.items():
            if raw.startswith(k[:5]):
                n = v
                break
    if not (1 <= n <= n_items):          # fuera de rango → no es una referencia útil
        return None, None
    return n, m


def _item_of(state: dict, n: int) -> str:
    for num, txt in state["items"]:
        if num == n:
            return txt
    return ""


# Verbos admitidos por fuente (revisión v20: sin whitelist, «pon la primera de
# Bad Bunny» tras una lista de pestañas secuestraba la orden hacia chrome).
_VERBS = {
    "chrome": ("resume", "lee", "lée", "analiza", "cierra", "cambia", "ve",
               "vete", "salta", "abre"),
    "telefono": ("llama", "llá", "marca", "telefonea"),
    "research": ("abre", "ábre", "reabre", "reábre", "enséñame", "ensename",
                 "muéstrame", "muestrame", "lee", "resume", ""),
    "vigilancias": ("borra", "elimina", "quita"),
    "hermes": ("", "dame", "dime", "ver", "muéstrame", "muestrame", "enséñame",
               "ensename", "abre", "resultado", "cómo", "como", "cuéntame", "cuentame"),
    "tasks_board": ("mueve", "marca", "completa", "termina", "borra", "elimina",
                    "quita", "empieza"),
}


def _tail_ok(source: str, tail: str) -> bool:
    """La referencia debe ir al FINAL de la frase («abre el segundo cajón» NO es
    una referencia). Solo el tablero admite cola: el estado de destino."""
    t = tail.strip(" ?!.")
    if not t:
        return True
    if source == "tasks_board":
        return bool(re.fullmatch(
            r"a\s+(?:en\s+)?(?:pendientes?|progreso|curso|revisi[oó]n|"
            r"completadas?|hechas?|terminadas?|done|doing|review)", t, re.I))
    return False


def resolve(text: str, channel: str = "pc") -> str | None:
    """Si 'text' es una referencia a la última lista mostrada EN ESE CANAL,
    devuelve la orden completa reescrita; si no aplica, None. Conservador:
    frase corta, contexto fresco, verbo del dominio, referencia al final y
    número dentro de rango — si algo no cuadra, ni toca."""
    _state = _state_for(channel)
    t = (text or "").strip()
    if not t or len(t) > 70 or not _state["items"]:
        return None
    if time.time() - _state["ts"] > _TTL:
        return None
    # no interferir si la frase YA nombra su dominio (pestaña, informe, tarea…)
    if re.search(r"\b(pesta[ñn]a|informe|vigilancia|encargo|tarea|contacto)\b", t, re.I):
        return None
    n, m = _ref_num(t, max(num for num, _ in _state["items"]))
    if not n:
        return None
    if not _tail_ok(_state["source"], t[m.end():]):
        return None
    item = _item_of(_state, n)
    src = _state["source"]
    lead = t[:m.start()].strip().lower()
    verb = lead.split()[0] if lead else ""
    allowed = _VERBS.get(src, ())
    if (verb or "") not in allowed and not (verb == "" and "" in allowed):
        return None

    if src == "chrome":
        v = ("cierra" if verb == "cierra" else
             "cambia a" if verb in ("cambia", "ve", "vete", "salta", "abre") else
             "lee" if verb in ("lee", "lée") else "resume")
        return f"{v} la pestaña {n}"
    if src == "telefono":
        return f"llama a {item}" if item else None
    if src == "research":
        return f"abre el informe de {item}" if item else None
    if src == "vigilancias":
        return f"borra la vigilancia {n}"
    if src == "hermes":
        return f"resultado del encargo {n}"
    if src == "tasks_board":
        if not item:
            return None
        return (t[:m.start()] + item + t[m.end():]).strip()
    return None


def clear() -> None:
    _channels.clear()
