"""
nexus — RAG local (memoria y fuente de conocimiento REAL, sin depender de Docker).

Antes el RAG semántico solo existía con Postgres+pgvector levantado. Aquí hay un
almacén VECTORIAL LOCAL (data/rag/knowledge.jsonl) que funciona con solo Ollama
(embeddings nomic-embed-text) y degrada a búsqueda por palabras si no hay embeddings.
Es la base para:
  • CONOCIMIENTO: hechos/documentos/notas que nexus guarda y recupera por SIGNIFICADO.
  • TAREAS APRENDIDAS: cuando entiende una petición nueva, la guarda como «tarea»
    (frase → orden canónica) con su vector; la próxima vez la reconoce por semejanza
    SIN volver a gastar el LLM → aprende tareas nuevas de verdad.

Todo tolera fallos: si algo va mal, devuelve vacío y el resto sigue.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import time

from .config import DATA_DIR, settings

_DIR = DATA_DIR / "rag"
_STORE = _DIR / "knowledge.jsonl"          # {id, text, kind, meta, vec, ts}
_SEEN = _DIR / "indexed.json"              # notas ya indexadas (para reindex incremental)
_mem: list | None = None                   # cache en memoria
_MIN_SEM = 0.42                            # umbral de coseno para considerar "relevante"
_MIN_TASK = 0.62                           # umbral (más alto) para aplicar una tarea aprendida


def _emb_ollama(text: str):
    import httpx
    r = httpx.post(f"{settings.get('ollama_url').rstrip('/')}/api/embeddings",
                   json={"model": settings.get("embed_model", "nomic-embed-text"),
                         "prompt": text[:2000]}, timeout=8)
    r.raise_for_status()
    return r.json().get("embedding")


def _emb_openai(text: str):
    key = settings.secret("openai_api_key") or settings.secret("cloud_llm_api_key")
    if not key:
        return None
    base = "https://api.openai.com/v1"
    if not settings.secret("openai_api_key") and settings.secret("cloud_llm_api_key"):
        base = settings.get("cloud_base_url", base).rstrip("/")
    import httpx
    r = httpx.post(f"{base}/embeddings", headers={"Authorization": f"Bearer {key}"},
                   json={"model": settings.get("embed_model_openai", "text-embedding-3-small"),
                         "input": text[:8000]}, timeout=15)
    r.raise_for_status()
    return r.json()["data"][0]["embedding"]


def _emb_gemini(text: str):
    key = settings.secret("gemini_api_key")
    if not key:
        return None
    import httpx
    model = settings.get("embed_model_gemini", "text-embedding-004")
    r = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent",
        params={"key": key}, json={"content": {"parts": [{"text": text[:8000]}]}}, timeout=15)
    r.raise_for_status()
    return r.json()["embedding"]["values"]


def _embed_sync(text: str):
    """Embeddings con EL MODELO QUE SE ELIGIÓ AL INSTALAR (no obliga a Ollama).
    `embed_provider` (⚙/instalación): 'auto' sigue el cerebro configurado; o se fija
    a ollama/openai/gemini. OJO: Anthropic (Claude/Fable) NO ofrece API de embeddings,
    así que si el cerebro es Anthropic se usa OpenAI/Gemini (si hay key) u Ollama local;
    y si no hay ninguno, el RAG cae a búsqueda por palabras."""
    text = (text or "").strip()
    if not text:
        return None
    fns = {"ollama": _emb_ollama, "openai": _emb_openai, "gemini": _emb_gemini}
    choice = str(settings.get("embed_provider", "auto")).lower()
    order = []
    if choice in fns:                         # elección EXPLÍCITA de la instalación
        order.append(fns[choice])
    else:                                     # AUTO: sigue el cerebro elegido + lo disponible
        prov = settings.get("llm_provider", "ollama")
        if prov == "ollama" or settings.get("llm_local"):
            order.append(_emb_ollama)
        if prov in ("openai", "cloud"):
            order.append(_emb_openai)
        if prov == "gemini":
            order.append(_emb_gemini)
        # Anthropic no tiene embeddings → el mejor que haya por sus keys/instalación
        if settings.secret("openai_api_key") or settings.secret("cloud_llm_api_key"):
            order.append(_emb_openai)
        if settings.secret("gemini_api_key"):
            order.append(_emb_gemini)
        order.append(_emb_ollama)             # último recurso: Ollama local
    seen = set()
    for fn in order:
        if fn in seen:
            continue
        seen.add(fn)
        try:
            v = fn(text)
            if v:
                return v
        except Exception:
            continue
    return None


async def embed(text: str):
    return await asyncio.to_thread(_embed_sync, text)


def _load() -> list:
    global _mem
    if _mem is not None:
        return _mem
    _mem = []
    try:
        for line in _STORE.read_text(encoding="utf-8").splitlines():
            try:
                _mem.append(json.loads(line))
            except Exception:
                pass
    except Exception:
        pass
    return _mem


def list_knowledge(limit: int = 300) -> list:
    """Hechos/conocimiento del almacén vectorial local (para auditar qué sabe nexus)."""
    out = []
    for r in _load():
        if r.get("kind") in ("knowledge", "fact"):
            out.append({"text": r.get("text", ""), "kind": r.get("kind"),
                        "meta": r.get("meta", {})})
    return out[:limit]


def _append(rec: dict) -> None:
    _DIR.mkdir(parents=True, exist_ok=True)
    with _STORE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if _mem is not None:
        _mem.append(rec)


def _cos(a, b) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    s = da = db = 0.0
    for x, y in zip(a, b):
        s += x * y; da += x * x; db += y * y
    if da == 0 or db == 0:
        return 0.0
    return s / math.sqrt(da * db)


def _words(q: str) -> list:
    return [w for w in re.findall(r"\w+", (q or "").lower()) if len(w) > 2]


def _pg():
    """Devuelve pg si la DB (Docker/pgvector) está montada y online; si no, None.
    El CONOCIMIENTO se guarda ahí (almacén elegido); local es solo respaldo."""
    try:
        from .memory import pg
        if pg.online:
            return pg
    except Exception:
        pass
    return None


async def add(text: str, kind: str = "knowledge", meta: dict | None = None,
              dedup: bool = True) -> bool:
    """Guarda conocimiento/tarea. El conocimiento va a la DB (pgvector) si está
    montada; las tareas y el respaldo van al store local."""
    text = (text or "").strip()
    if not text:
        return False
    # CONOCIMIENTO → base de datos elegida (pgvector) cuando esté disponible
    if kind in ("knowledge", "fact"):
        pg = _pg()
        if pg is not None:
            try:
                await asyncio.to_thread(pg.remember, text, kind, None)
                return True
            except Exception:
                pass                            # si la DB falla, cae al store local
    store = _load()
    if dedup:
        low = text.lower()
        for r in store:
            if r.get("kind") == kind and r.get("text", "").strip().lower() == low:
                return False
    vec = await embed(text)
    _append({"id": f"{kind}:{abs(hash(text)) % 10**9}", "text": text, "kind": kind,
             "meta": meta or {}, "vec": vec, "ts": time.time()})
    return True


async def search(query: str, k: int = 4, kinds: tuple | None = None) -> list[dict]:
    """Recupera lo más relevante por SIGNIFICADO. Conocimiento desde la DB (pgvector)
    si está montada; tareas y respaldo desde el store local (coseno o palabras)."""
    want_knowledge = (kinds is None) or any(x in ("knowledge", "fact") for x in kinds)
    if want_knowledge and (kinds is None or "task" not in kinds):
        pg = _pg()
        if pg is not None:
            try:
                rows = await asyncio.to_thread(pg.recall, query, k)
                if rows:
                    return [{"text": r.get("content", ""), "kind": r.get("kind", "knowledge"),
                             "score": round(r.get("score", 0.0) or 0.0, 3), "meta": {}}
                            for r in rows]
            except Exception:
                pass
    store = _load()
    if not store:
        return []
    cand = [r for r in store if not kinds or r.get("kind") in kinds]
    if not cand:
        return []
    qv = await embed(query)
    scored: list[tuple] = []
    if qv:
        for r in cand:
            if r.get("vec") and len(r["vec"]) == len(qv):
                sc = _cos(qv, r["vec"])
                if sc > _MIN_SEM:
                    scored.append((sc, r))
    if not scored:                              # degradación a palabras
        ws = _words(query)
        if ws:
            for r in cand:
                hit = sum(1 for w in ws if w in r.get("text", "").lower())
                if hit:
                    scored.append((hit / len(ws), r))
    scored.sort(key=lambda x: -x[0])
    return [{"text": r["text"], "kind": r["kind"], "score": round(s, 3),
             "meta": r.get("meta", {})} for s, r in scored[:k]]


# --------------------------------------------------------- tareas aprendidas
async def learn_task(phrase: str, order: str, skill: str = "") -> bool:
    """Aprende una TAREA NUEVA: la petición en lenguaje natural → orden canónica que
    funcionó. Se guarda con su vector para reconocerla por semejanza la próxima vez."""
    phrase = (phrase or "").strip()
    order = (order or "").strip()
    if not phrase or not order or phrase.lower() == order.lower():
        return False
    return await add(phrase, kind="task", meta={"order": order, "skill": skill}, dedup=True)


async def find_task(phrase: str) -> str:
    """Si una tarea aprendida se parece MUCHO a esta petición, devuelve su orden
    canónica (para ejecutarla sin gastar el LLM). '' si no hay match fiable."""
    hits = await search(phrase, k=1, kinds=("task",))
    if hits and hits[0]["score"] >= _MIN_TASK:
        return (hits[0].get("meta") or {}).get("order", "")
    return ""


# --------------------------------------------------------- indexación de notas
def _seen() -> dict:
    try:
        return json.loads(_SEEN.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_seen(d: dict) -> None:
    try:
        _DIR.mkdir(parents=True, exist_ok=True)
        _SEEN.write_text(json.dumps(d), encoding="utf-8")
    except Exception:
        pass


async def reindex(limit: int = 40) -> int:
    """Indexa en el RAG las notas de conocimiento y los SKILL.md (fuente de
    conocimiento) que aún no estén indexados. Incremental para no saturar."""
    from .memory import MEMORY_DIR
    from .config import SKILLS_DIR
    seen = _seen()
    done = 0
    paths = []
    try:
        paths += [p for p in MEMORY_DIR.rglob("*.md") if p.parent.name != "daily"]
    except Exception:
        pass
    try:
        paths += list(SKILLS_DIR.rglob("SKILL.md"))
    except Exception:
        pass
    for p in paths:
        if done >= limit:
            break
        key = str(p)
        try:
            mtime = p.stat().st_mtime
        except Exception:
            continue
        if seen.get(key) == mtime:
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            continue
        if len(txt) > 40:
            await add(txt[:1500], kind="knowledge",
                      meta={"source": p.name}, dedup=True)
            done += 1
        seen[key] = mtime
    if done:
        _save_seen(seen)
    return done


def stats() -> dict:
    store = _load()
    kinds: dict = {}
    for r in store:
        kinds[r.get("kind", "?")] = kinds.get(r.get("kind", "?"), 0) + 1
    return {"total": len(store),
            "vectorized": sum(1 for r in store if r.get("vec")),
            "by_kind": kinds}
