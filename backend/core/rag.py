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
import hashlib
import json
import math
import re
import time
import unicodedata

from .comun.config import CONFIG_DIR, DATA_DIR, settings

_DIR = DATA_DIR / "rag"
_STORE = _DIR / "knowledge.jsonl"          # {id, text, kind, meta, vec, ts}
_SEEN = _DIR / "indexed.json"              # notas ya indexadas (para reindex incremental)
_mem: list | None = None                   # cache en memoria

# ─────────────────────────────────────────────────────────────────────────────
# Los números con los que se decide qué merece llamarse «relevante» viven FUERA
# del código, en config/umbrales.json (sección «memoria»). Lo de aquí abajo son
# los valores de reserva, que son EXACTAMENTE los que había escritos a mano: si
# el archivo no existe o está mal puesto, el comportamiento es el de siempre.
# Nadie se queda sin memoria por un JSON roto.
_UMBRALES_RESERVA = {
    "coseno_minimo": 0.42,                 # umbral de coseno para considerar "relevante"
    "solape_minimo_palabras": 0.5,         # qué parte de las palabras clave debe coincidir
    "coseno_minimo_tarea": 0.62,           # más alto: para aplicar una tarea aprendida
    "letras_minimas_palabra_sola": 5,      # cuándo UNA palabra suelta da para buscar
}


def _carga_umbrales() -> dict:
    """Lee la sección «memoria» de config/umbrales.json sobre los de reserva."""
    vals = dict(_UMBRALES_RESERVA)
    try:
        f = CONFIG_DIR / "umbrales.json"
        if f.is_file():
            leido = (json.loads(f.read_text(encoding="utf-8")) or {}).get("memoria") or {}
            for k, v in leido.items():
                if k in vals and isinstance(v, (int, float)) and not isinstance(v, bool):
                    vals[k] = float(v)
    except Exception:
        pass                                # un JSON roto no deja a nexus sin memoria
    return vals


_UMBRALES = _carga_umbrales()
_MIN_SEM = _UMBRALES["coseno_minimo"]
_MIN_PALABRAS = _UMBRALES["solape_minimo_palabras"]
_MIN_TASK = _UMBRALES["coseno_minimo_tarea"]
_MIN_LETRAS_SOLA = int(_UMBRALES["letras_minimas_palabra_sola"])

# 002-memoria-y-conocimiento (bloque C): reserva de troceado, misma política
# que _UMBRALES_RESERVA arriba -- si config/umbrales.json falta o está roto,
# el troceado NO se para, usa estos valores.
_UMBRALES_TROCEADO_RESERVA = {
    "tamano_caracteres": 1200,
    "solape_caracteres": 200,
    "minimo_caracteres": 120,
    "filas_por_trozo": 25,
}


def _umbrales_troceado() -> dict:
    """Lee memoria.troceado de config/umbrales.json sobre los de reserva."""
    vals = dict(_UMBRALES_TROCEADO_RESERVA)
    try:
        f = CONFIG_DIR / "umbrales.json"
        if f.is_file():
            leido = (json.loads(f.read_text(encoding="utf-8")) or {}).get(
                "memoria", {}).get("troceado") or {}
            for k, v in leido.items():
                if k in vals and isinstance(v, (int, float)) and not isinstance(v, bool):
                    vals[k] = int(v)
    except Exception:
        pass
    return vals


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


def _embed_sync(text: str, proveedor: str | None = None):
    """Embeddings con EL MODELO QUE SE ELIGIÓ AL INSTALAR (no obliga a Ollama).
    `embed_provider` (⚙/instalación): 'auto' sigue el cerebro configurado; o se fija
    a ollama/openai/gemini. OJO: Anthropic (Claude/Fable) NO ofrece API de embeddings,
    así que si el cerebro es Anthropic se usa OpenAI/Gemini (si hay key) u Ollama local;
    y si no hay ninguno, el RAG cae a búsqueda por palabras.

    `proveedor`: si se pasa EXPLÍCITO, ignora `embed_provider`/el cerebro por
    completo y usa SOLO ese proveedor (sin caer a ningún otro). Así
    `memoria.embedding.proveedor_preferido` (memory.py) queda independiente de
    `embed_provider: auto`, que sigue al cerebro de chat — cambiar el cerebro
    de Gemini a otra nube NUNCA debe arrastrar los embeddings de memoria
    (memoria-embeddings, escenario «Cambio de cerebro de chat no afecta a
    embeddings»)."""
    text = (text or "").strip()
    if not text:
        return None
    fns = {"ollama": _emb_ollama, "openai": _emb_openai, "gemini": _emb_gemini}
    if proveedor:
        fn = fns.get(str(proveedor).lower())
        if fn is None:
            return None
        try:
            return fn(text) or None
        except Exception:
            return None
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


def huella(texto: str) -> str:
    """Huella (hash) estable de un texto, para deduplicación EXACTA
    (memoria-deduplicacion, req. «Identidad canónica del hecho»).

    Normaliza NFKC + casefold + espacios colapsados ANTES de hashear: dos
    hechos con distinto espaciado o mayúsculas dan la MISMA huella. Las
    tildes NO se tocan a propósito: «revisión» y «revision» son hechos
    distintos, no el mismo con una errata (memoria-deduplicacion, escenario
    «Normalización antes de la huella»).

    `memory.py` combina esto con el `kind` (`huella(f"{kind}\n{texto}")`,
    diseño §4: `sha256(kind + "\n" + normalizado(texto))`) para que dos
    hechos idénticos de tipo distinto no colisionen entre sí."""
    t = unicodedata.normalize("NFKC", texto or "")
    t = t.casefold()
    t = re.sub(r"\s+", " ", t).strip()
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def trocear(texto: str) -> list[dict]:
    """Trocea un texto largo en pedazos de `memoria.troceado.tamano_caracteres`
    (reserva 1200) con `solape_caracteres` (reserva 200) de solape entre
    trozo y trozo. 002-memoria-y-conocimiento (bloque C, C2.1): ANTES
    `reindex()` cortaba con `texto[:1500]` y el buzón con `[:900]` -- un
    documento de 26 KB o 224 KB entraba MUTILADO en la memoria, sin avisar.
    Ahora se trocea entero: quitando el solape de cada trozo (salvo el
    primero) y concatenando, se reproduce el texto original CARÁCTER A
    CARÁCTER (invariante probado en test_trocear_reconstruye_original_exacto).

    El corte busca frontera, por prioridad, dentro de una ventana hacia
    atrás desde el límite de tamaño: encabezado markdown > línea en blanco
    > fin de frase > corte duro (si nada de lo anterior aparece).
    Devuelve [{"texto", "indice", "total"}]."""
    umb = _umbrales_troceado()
    tam = umb["tamano_caracteres"]
    solape = umb["solape_caracteres"]
    minimo = umb["minimo_caracteres"]
    n = len(texto)
    if n <= tam:
        return [{"texto": texto, "indice": 0, "total": 1}]
    cortes: list[int] = []
    pos = 0
    while pos < n:
        fin_objetivo = min(pos + tam, n)
        if fin_objetivo >= n:
            cortes.append(n)
            break
        ventana_ini = max(pos + minimo, fin_objetivo - 300)
        ventana = texto[ventana_ini:fin_objetivo]
        corte = None
        m = list(re.finditer(r"\n(?=#{1,6}\s)", ventana))
        if m:
            corte = ventana_ini + m[-1].start() + 1
        if corte is None:
            m = list(re.finditer(r"\n[ \t]*\n", ventana))
            if m:
                corte = ventana_ini + m[-1].end()
        if corte is None:
            m = list(re.finditer(r"[.!?][\"'\)\]]?(?:\s|$)", ventana))
            if m:
                corte = ventana_ini + m[-1].end()
        if corte is None or corte <= pos:
            corte = fin_objetivo
        cortes.append(corte)
        pos = corte
    total = len(cortes)
    trozos = []
    for i, fin in enumerate(cortes):
        inicio = 0 if i == 0 else max(0, cortes[i - 1] - solape)
        trozos.append({"texto": texto[inicio:fin], "indice": i, "total": total})
    return trozos


def trocear_xlsx_estructurado(hojas: list[dict], *, filas_por_trozo: int | None = None) -> list[dict]:
    """Trocea la salida de `files_io.leer_xlsx_estructurado()` POR HOJA,
    `memoria.troceado.filas_por_trozo` (reserva 25) filas cada vez, con el
    nombre de hoja y las cabeceras repetidas en cada trozo y cada fila como
    pares `columna: valor`. 002-memoria-y-conocimiento: memoria-ingesta-
    documentos, req. «.xlsx por hojas y columnas» -- NUNCA se aplana por
    caracteres (eso partía filas por la mitad). Devuelve [{"texto",
    "indice", "total", "hoja"}]."""
    umb = _umbrales_troceado()
    tam = int(filas_por_trozo if filas_por_trozo is not None else umb["filas_por_trozo"])
    tam = max(1, tam)
    trozos = []
    for hoja in hojas:
        cabeceras = hoja.get("cabeceras") or []
        filas = hoja.get("filas") or []
        if not filas:
            continue
        bloques = [filas[i:i + tam] for i in range(0, len(filas), tam)]
        for bi, bloque in enumerate(bloques):
            inicio_fila = bi * tam + 1
            lineas = [f"## Hoja: {hoja.get('hoja', '')} "
                      f"(filas {inicio_fila}-{inicio_fila + len(bloque) - 1} de {len(filas)})"]
            for fila in bloque:
                pares = ", ".join(f"{c}: {'' if v is None else v}"
                                   for c, v in zip(cabeceras, fila))
                lineas.append(pares)
            trozos.append({"texto": "\n".join(lineas), "indice": bi, "total": len(bloques),
                            "hoja": hoja.get("hoja", "")})
    return trozos


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


# Palabras que están en CUALQUIER frase y no distinguen nada. Sin quitarlas, la
# búsqueda por palabras casaba «Que es lo que ves» con una nota sobre una persona
# solo porque las dos llevaban «que» — y esa nota se le inyectaba al modelo como
# «conocimiento relevante». De ahí salió que le contestara sobre alguien que no
# venía a cuento (31/07/2026).
_VACIAS = {
    "que", "los", "las", "una", "uno", "por", "para", "con", "sin", "del", "esto",
    "eso", "esa", "ese", "como", "cuando", "donde", "porque", "pero", "mas", "muy",
    "todo", "toda", "hay", "ser", "estar", "tener", "hacer", "dime", "dame", "sabes",
    "puedes", "quiero", "necesito", "ahora", "aqui", "esta", "este", "estos", "vale",
    "the", "and", "you", "for", "with", "this", "that", "what", "have",
}


def _words(q: str) -> list:
    """Las palabras que de verdad distinguen una frase de otra."""
    return [w for w in re.findall(r"\w+", (q or "").lower())
            if len(w) > 2 and w not in _VACIAS]


def _palabras_de_busqueda(q: str) -> list:
    """Como _words(), pero además decide si la frase DA para buscar por palabras.

    El filtro de relevancia es una proporción: «que coincida más de la mitad de
    lo que distingue a la frase». Con UNA sola palabra clave esa cuenta no dice
    nada — el denominador es 1, sale 1.0 y pasa siempre. Así fue como
    «Que es lo que ves», que se queda en ["ves"], se trajo el manual entero de
    Gmail por la línea «el mismo número que ves en tu app de Gmail» (31/07/2026).
    Es el mismo fallo que ya se tapó para «que»: se quitó esa palabra de en medio
    y el agujero siguió abierto para la siguiente.

    Una palabra suelta solo vale si distingue algo por sí misma: «wabiksco»
    busca, «ves» no. La medida es la longitud, que es lo único que hay a mano sin
    inventarse un diccionario.
    """
    ws = _words(q)
    if len(ws) == 1 and len(ws[0]) < _MIN_LETRAS_SOLA:
        return []
    return ws


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
                # memory-y-conocimiento (A4.4): remember() YA deduplica por
                # huella (índice único si existe, comprobación de aplicación
                # si no) — esto sustituye al `dedup` local de aquí abajo, que
                # solo miraba el almacén de ficheros y dejaba pasar CUALQUIER
                # cosa por el camino de Postgres sin comprobar nada.
                res = await asyncio.to_thread(pg.remember, text, kind, None)
                return not (isinstance(res, dict) and res.get("duplicado"))
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
                # Con umbral, igual que la búsqueda local. Sin él se devolvían
                # SIEMPRE los k más cercanos por lejos que estuvieran, y el
                # modelo los recibía como «conocimiento relevante».
                # OJO: recall() tiene DOS caminos y solo el semántico trae
                # «score»; el de respaldo (solape de palabras) lo deja a None.
                # Descartar esas filas por no tener score dejaba la memoria muda
                # entera con la DB montada. A ellas se les pide lo mismo que a la
                # búsqueda local por palabras.
                ws = _palabras_de_busqueda(query)
                utiles: list[tuple] = []
                for r in (rows or []):
                    sc = r.get("score")
                    if sc is not None:
                        sc = float(sc or 0.0)
                        if not (sc >= _MIN_SEM):
                            continue
                    else:
                        # Palabras ENTERAS del documento, no subcadenas: contra un
                        # README largo, «ves» casaba dentro de «claves» y colaba el
                        # documento entero como si viniera a cuento.
                        suyas = set(re.findall(r"\w+", str(r.get("content", "") or "").lower()))
                        hit = sum(1 for w in ws if w in suyas)
                        # Estricto: empatar con el listón no basta. «que ves ahora
                        # mismo» deja «ves» y «mismo», y con media palabra suelta
                        # se colaban READMEs enteros.
                        if not ws or not hit or not (hit / len(ws) > _MIN_PALABRAS):
                            continue
                        sc = hit / len(ws)
                    utiles.append((sc, r))
                if utiles:
                    utiles.sort(key=lambda x: -x[0])
                    return [{"text": r.get("content", ""), "kind": r.get("kind", "knowledge"),
                             "score": round(sc, 3), "meta": {}}
                            for sc, r in utiles[:k]]
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
        ws = _palabras_de_busqueda(query)
        if ws:
            for r in cand:
                # Palabras ENTERAS, no subcadenas: «ves» dentro de «claves» daba
                # por relevante un documento que no hablaba de nada de eso.
                suyas = set(re.findall(r"\w+", str(r.get("text", "") or "").lower()))
                hit = sum(1 for w in ws if w in suyas)
                # Antes bastaba UNA palabra en común para colar una nota como
                # relevante. Ahora tiene que coincidir MÁS de la mitad de lo que
                # distingue a la frase, y empatar con el listón no vale: es
                # preferible no recordar nada que recordar algo que no viene a
                # cuento.
                if hit and hit / len(ws) > _MIN_PALABRAS:
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
    conocimiento) que aún no estén indexados. Incremental para no saturar.
    002-memoria-y-conocimiento (bloque C, C2.2): ANTES cada nota se cortaba
    con `add(txt[:1500], ...)` -- una nota larga entraba mutilada, sin
    avisar (2º de los cuatro truncados de este bloque). AHORA se trocea con
    `trocear()` y cada trozo se indexa por separado, entero."""
    from .memory import MEMORY_DIR
    from .comun.config import SKILLS_DIR
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
            for trozo in trocear(txt):
                await add(trozo["texto"], kind="knowledge",
                          meta={"source": p.name, "trozo_indice": trozo["indice"],
                                "trozo_total": trozo["total"]}, dedup=True)
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
