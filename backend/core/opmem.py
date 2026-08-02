"""
nexus — ENGRAM: MEMORIA OPERATIVA Y DE COMPORTAMIENTO (specs v23, TAREAS 4-6).

Corrección de rumbo pedida por Adri: Engram NO es «memoria de código». Es la
memoria con la que nexus recuerda CÓMO tiene que trabajar:

    órdenes permanentes · preferencias · formas de responder · maneras de actuar
    decisiones tomadas · procedimientos acordados · restricciones · correcciones
    errores que no debe repetir · reglas de delegación con Hermes · convenciones
    de organización · acciones relevantes anteriores · contexto para continuar

Y también decisiones técnicas cuando las haya — pero NO se limita a ellas.

Reparto de responsabilidades (TAREA 5), sin mezclar nunca las dos búsquedas:

    opmem (este módulo)  → CÓMO comportarse. Reglas, decisiones, preferencias.
    rag.py               → QUÉ sabe. Documentos, PDF, DOCX, notas, fragmentos.

Contra las respuestas repetitivas (TAREA 6):
  * la búsqueda es por ÁMBITO + relevancia, con tope de resultados y sin duplicados;
  * jamás se guarda una respuesta completa de nexus como si fuera una regla;
  * cada respuesta apunta QUÉ recuerdos usó (data/logs/recall.jsonl), así que se
    puede inspeccionar por qué contestó lo que contestó.

Persistencia: data/engram_ops.json (fuente de verdad, sobrevive a reinicios).
Si el servidor de Engram está levantado, cada recuerdo se ESPEJA allí para
compartirlo con las demás herramientas — pero nexus nunca depende de ello.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
import time
import unicodedata
import uuid

from .config import DATA_DIR

OPS_FILE = DATA_DIR / "engram_ops.json"
RECALL_LOG = DATA_DIR / "logs" / "recall.jsonl"

# Tipos de recuerdo. NO son categorías de código: son maneras de trabajar.
TIPOS = {
    "regla": "orden permanente que nexus debe cumplir siempre",
    "preferencia": "cómo le gusta a Adri que se hagan las cosas",
    "procedimiento": "pasos acordados para una tarea concreta",
    "restriccion": "algo que nexus NO debe hacer",
    "correccion": "corrección explícita del operador (manda sobre lo anterior)",
    "delegacion": "qué hace nexus y qué se le encarga a Hermes",
    "convencion": "convenciones de organización, nombres y carpetas",
    "decision": "decisión tomada y su porqué",
    "tecnico": "decisión técnica, arquitectura o bug conocido",
    "accion": "acción relevante ya realizada (para continuar después)",
}
# Prioridad por defecto de cada tipo (1 = flojito, 5 = manda sobre todo).
_PRIO = {"correccion": 5, "restriccion": 5, "regla": 4, "delegacion": 4,
         "procedimiento": 3, "preferencia": 3, "convencion": 3,
         "decision": 2, "tecnico": 2, "accion": 1}

_MAX = 800                    # recuerdos guardados
_STOP = {"que", "de", "la", "el", "los", "las", "un", "una", "y", "o", "a", "en",
         "para", "por", "con", "del", "al", "se", "me", "te", "lo", "es", "no",
         "si", "mi", "tu", "su", "cuando", "como", "the", "and", "to", "of"}

_cache: dict = {"items": None, "mtime": 0.0}
_last_applied: dict = {}      # por canal: qué recuerdos se usaron en la última respuesta


# ───────────────────────── utilidades ─────────────────────────

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


def _words(s: str) -> set:
    return {w for w in re.findall(r"[a-z0-9ñ]{3,}", _norm(s)) if w not in _STOP}


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _load() -> list[dict]:
    try:
        mt = OPS_FILE.stat().st_mtime
    except Exception:
        _cache.update(items=[], mtime=0.0)
        return []
    if _cache["items"] is not None and _cache["mtime"] == mt:
        return _cache["items"]
    try:
        data = json.loads(OPS_FILE.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else []
    except Exception:
        items = []
    _cache.update(items=items, mtime=mt)
    return items


def _save(items: list[dict]) -> None:
    OPS_FILE.parent.mkdir(parents=True, exist_ok=True)
    OPS_FILE.write_text(json.dumps(items[-_MAX:], ensure_ascii=False, indent=1),
                        encoding="utf-8")
    _cache.update(items=None, mtime=0.0)     # se relee en la próxima consulta


# ───────────────────────── clasificación ─────────────────────────

# Frases con las que Adri fija una MANERA DE TRABAJAR (van a la memoria operativa),
# frente a un HECHO del mundo (que va al RAG documental).
_RULE_RX = re.compile(
    r"\b(?:siempre\s+que|siempre|nunca|jam[aá]s|no\s+(?:vuelvas|me\s+|debes|puedes|quiero\s+que)|"
    r"a\s+partir\s+de\s+ahora|de\s+ahora\s+en\s+adelante|antes\s+de\s+(?:borrar|hacer|ejecutar|"
    r"crear|modificar|responder)|cada\s+vez\s+que|cuando\s+te\s+(?:diga|pida)|"
    r"tienes\s+que|debes|prefiero|me\s+gusta\s+que|no\s+me\s+gusta|"
    r"que\s+quede\s+claro|reg(?:la|las)\b|por\s+norma)\b", re.IGNORECASE)
_CORRECTION_RX = re.compile(
    r"\b(?:no\s+vuelvas\s+a|te\s+he\s+dicho\s+que|ya\s+te\s+dije|otra\s+vez\s+no|"
    r"no\s+era\s+eso|est[aá]\s+mal|te\s+equivocas|mal\s+hecho|no\s+es\s+lo\s+que)\b",
    re.IGNORECASE)
_DELEG_RX = re.compile(r"\bhermes\b", re.IGNORECASE)
_TECH_RX = re.compile(
    r"\b(?:c[oó]digo|funci[oó]n|m[oó]dulo|endpoint|api|bug|refactor|arquitectura|"
    r"clase|variable|regex|test|deploy|commit)\b", re.IGNORECASE)


def clasifica(texto: str) -> str:
    """Tipo de recuerdo a partir de cómo lo dijo el operador."""
    t = texto or ""
    if _CORRECTION_RX.search(t):
        return "correccion"
    if _DELEG_RX.search(t) and _RULE_RX.search(t):
        return "delegacion"
    if re.search(r"\bnunca\b|\bjam[aá]s\b|\bno\s+(?:vuelvas|debes|puedes)\b", t, re.I):
        return "restriccion"
    if re.search(r"\bprefiero\b|\bme\s+gusta\b|\bno\s+me\s+gusta\b", t, re.I):
        return "preferencia"
    if _RULE_RX.search(t):
        return "regla"
    if _TECH_RX.search(t):
        return "tecnico"
    return "decision"


def es_comportamiento(texto: str) -> bool:
    """¿Esto es una MANERA DE TRABAJAR (memoria operativa) o un HECHO (RAG)?
    «no me leas en voz alta lo que escribo» → operativa.
    «la reunión con el cliente fue el martes» → hecho, va al RAG."""
    return bool(_RULE_RX.search(texto or "") or _CORRECTION_RX.search(texto or ""))


# ───────────────────────── escritura ─────────────────────────

def remember(texto: str, kind: str = "", scope: str = "global",
             priority: int = 0, source: str = "operador",
             meta: dict | None = None) -> dict:
    """Guarda una manera de trabajar. Devuelve el recuerdo (o el existente si ya
    estaba). Las CORRECCIONES mandan: dejan obsoletos los recuerdos que chocan
    con ellas en el mismo ámbito (criterio de aceptación de la TAREA 4)."""
    texto = (texto or "").strip()
    if len(texto) < 4:
        return {}
    kind = kind if kind in TIPOS else clasifica(texto)
    prio = priority or _PRIO.get(kind, 2)
    items = list(_load())
    clave = _norm(texto)
    for it in items:                            # ya lo sabía: se refresca
        if it.get("_key") == clave and not it.get("superseded_by"):
            it["updated"] = _now()
            it["priority"] = max(it.get("priority", 1), prio)
            _save(items)
            return it
    rec = {"id": uuid.uuid4().hex[:8], "kind": kind, "scope": scope or "global",
           "text": texto[:600], "priority": prio, "source": source,
           "created": _now(), "updated": _now(), "hits": 0, "last_used": "",
           "superseded_by": "", "meta": meta or {}, "_key": clave}
    if kind == "correccion":
        ws = _words(texto)
        for it in items:
            if it.get("superseded_by") or it.get("kind") == "correccion":
                continue
            if it.get("scope") not in (rec["scope"], "global"):
                continue
            solape = len(ws & _words(it.get("text", "")))
            if solape >= 3:                     # habla de lo mismo → queda obsoleto
                it["superseded_by"] = rec["id"]
                it["updated"] = _now()
    items.append(rec)
    _save(items)
    try:
        from . import audit as _a
        _a.log(action="engram_remember", actor=source, destructive=False,
               request=texto[:200], result=f"{kind} · ámbito {rec['scope']}")
    except Exception:
        pass
    return rec


def matching(query: str) -> list[dict]:
    """Los recuerdos que borraría forget(query). Solo lectura: para enseñarle al
    operador qué se va a perder ANTES de perderlo."""
    q = _norm(query)
    if not q:
        return []
    return [it for it in _load() if q in it.get("_key", "")]


def forget(query: str) -> int:
    """Olvida recuerdos que casen (borrado real: es lo que pide «olvida que…»)."""
    items = _load()
    q = _norm(query)
    if not q:
        return 0
    keep = [it for it in items if q not in it.get("_key", "")]
    n = len(items) - len(keep)
    if n:
        _save(keep)
    return n


async def mirror_to_engram(ctx, rec: dict) -> None:
    """Espeja el recuerdo en el servidor de Engram si está levantado, para
    compartirlo con las demás herramientas. Nunca bloquea ni rompe nada."""
    if not rec:
        return
    try:
        from . import engram_bridge as eng
        tipo = "decision" if rec["kind"] in ("decision", "regla", "preferencia",
                                             "correccion", "restriccion",
                                             "delegacion", "convencion",
                                             "procedimiento", "accion") else "architecture"
        await asyncio.wait_for(
            eng.save(ctx, f"[{rec['kind']}] {rec['text'][:80]}", rec["text"], tipo),
            timeout=8)
    except Exception:
        pass


# ───────────────────────── recuperación ─────────────────────────

def _score(rec: dict, qw: set, scope: str) -> float:
    """Relevancia = solape de términos + prioridad + frescura + ámbito.
    Sin esto, nexus recuperaba SIEMPRE los mismos recuerdos y repetía respuesta."""
    rw = _words(rec.get("text", ""))
    if not rw:
        return 0.0
    solape = len(qw & rw)
    base = solape / max(3.0, len(qw) or 3)
    sc = rec.get("scope", "global")
    if scope and sc == scope:
        base += 0.45                       # del mismo ámbito: manda
    elif sc != "global" and scope and sc != scope:
        return 0.0                         # de OTRO ámbito: no se inyecta jamás
    base += (rec.get("priority", 1) - 1) * 0.18
    try:
        edad = (dt.datetime.now() - dt.datetime.fromisoformat(rec["updated"])).days
        base += 0.20 if edad <= 7 else (0.10 if edad <= 30 else 0.0)
    except Exception:
        pass
    # Las órdenes permanentes aplican aunque no compartan palabras: son
    # «siempre», no «cuando se hable de esto». Las de máxima prioridad, en
    # cualquier ámbito; las importantes, dentro del SUYO.
    prio = rec.get("priority", 1)
    if solape == 0 and not (prio >= 5 or
                            (scope and sc == scope and sc != "global" and prio >= 4)):
        return 0.0
    return round(base, 3)


def relevant(texto: str, scope: str = "", limit: int = 5,
             min_score: float = 0.25) -> list[dict]:
    """Los recuerdos que DE VERDAD tocan aquí, ordenados y sin duplicados.
    Nunca devuelve el histórico entero: eso era lo que hacía que respondiera
    siempre lo mismo (TAREA 6)."""
    qw = _words(texto)
    vivos = [r for r in _load() if not r.get("superseded_by")]
    scored = []
    vistos = set()
    for r in vivos:
        s = _score(r, qw, scope)
        if s < min_score:
            continue
        firma = tuple(sorted(_words(r.get("text", ""))))[:8]
        if firma in vistos:                 # deduplicado de recuerdos casi iguales
            continue
        vistos.add(firma)
        scored.append((s, r))
    scored.sort(key=lambda x: (-x[0], -x[1].get("priority", 1)))
    out = []
    for s, r in scored[:max(1, limit)]:
        rr = dict(r)
        rr["score"] = s
        out.append(rr)
    return out


def as_prompt(recuerdos: list[dict]) -> str:
    """Bloque compacto para el prompt. Solo lo relevante, nunca la memoria entera."""
    if not recuerdos:
        return ""
    lineas = [f"- ({r['kind']}) {r['text']}" for r in recuerdos]
    return ("REGLAS Y PREFERENCIAS DEL OPERADOR (memoria operativa de nexus — cómo "
            "debes comportarte; NO son datos que citar, son órdenes que cumplir):\n"
            + "\n".join(lineas))


def note_use(recuerdos: list[dict], texto: str = "", channel: str = "pc",
             documentos: list | None = None) -> None:
    """Apunta QUÉ se usó para responder (TAREA 6: se puede inspeccionar) y sube
    el contador de uso de cada recuerdo."""
    if recuerdos:
        items = _load()
        ids = {r["id"] for r in recuerdos}
        for it in items:
            if it["id"] in ids:
                it["hits"] = it.get("hits", 0) + 1
                it["last_used"] = _now()
        _save(items)
    _last_applied[channel or "pc"] = {
        "ts": time.time(), "texto": (texto or "")[:200],
        "reglas": [{"id": r["id"], "kind": r["kind"], "text": r["text"],
                    "score": r.get("score")} for r in (recuerdos or [])],
        "documentos": [str(d)[:160] for d in (documentos or [])]}
    try:
        RECALL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with RECALL_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": _now(), "channel": channel,
                                 "texto": (texto or "")[:200],
                                 "reglas": [r["id"] for r in (recuerdos or [])],
                                 "documentos": [str(d)[:120] for d in (documentos or [])]},
                                ensure_ascii=False) + "\n")
    except Exception:
        pass


def explain(channel: str = "pc") -> str:
    """«¿Por qué has hecho eso?» → qué regla se aplicó, sin soltar el historial."""
    d = _last_applied.get(channel or "pc")
    if not d or not (d.get("reglas") or d.get("documentos")):
        return ("En la última respuesta no apliqué ninguna regla de memoria: salió "
                "del propio mensaje y de la conversación reciente.")
    partes = []
    if d.get("reglas"):
        partes.append("Aplicué esto de tu memoria operativa:\n" +
                      "\n".join(f"   · ({r['kind']}) {r['text']}" for r in d["reglas"][:5]))
    if d.get("documentos"):
        partes.append("Y consulté estos documentos: " + ", ".join(d["documentos"][:5]))
    return "\n".join(partes)


def stats() -> dict:
    items = _load()
    vivos = [r for r in items if not r.get("superseded_by")]
    por_tipo: dict = {}
    for r in vivos:
        por_tipo[r["kind"]] = por_tipo.get(r["kind"], 0) + 1
    return {"total": len(items), "vivos": len(vivos),
            "obsoletos": len(items) - len(vivos), "por_tipo": por_tipo,
            "fichero": str(OPS_FILE)}


def all_rules(limit: int = 40, kind: str = "") -> list[dict]:
    vivos = [r for r in _load() if not r.get("superseded_by")]
    if kind:
        vivos = [r for r in vivos if r["kind"] == kind]
    vivos.sort(key=lambda r: (-r.get("priority", 1), r.get("updated", "")))
    return vivos[:limit]
