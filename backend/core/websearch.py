"""
nexus — Búsqueda web REAL (sin API key), robusta y multi-fuente.

Se usa desde:
  * la skill ai_media («busca en internet …») — respuesta directa.
  * brain.py — augmentación automática del chat: cuando una pregunta necesita
    datos ACTUALES (mundial, resultados, «quién juega», años recientes…), nexus
    busca en la web y le pasa los resultados al modelo para que responda con datos
    frescos en vez de decir «aún no se sabe».

Antes dependía de UN solo scraping (DuckDuckGo HTML). Cuando ese endpoint
bloquea/cambia el HTML devolvía [] EN SILENCIO y el modelo respondía con su
conocimiento caducado. Ahora prueba VARIAS fuentes hasta que una responda:
  1. Google News RSS  → ideal para NOTICIAS y resultados recientes (trae fecha).
  2. DuckDuckGo Lite   → HTML muy simple, difícil de romper.
  3. DuckDuckGo HTML   → el de siempre, como último recurso.
Devuelve la PRIMERA fuente que dé resultados.

v19: CACHÉ con TTL en data/webcache.json — repetir una pregunta en pocos
minutos no vuelve a rascar la web (noticias caducan a los 5 min, el resto a los
30; páginas leídas, 1 h). Y fetch_page extrae MÁS contenido útil: article/main,
titulares h1-h3 y listas, no solo <p>.
"""
from __future__ import annotations

import re

from .comun import net

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_TIMEOUT = 8      # por FUENTE (hay hasta 3: si una cuelga, quedan intentos para las otras)
_HDRS = {"User-Agent": _UA, "Accept-Language": "es-ES,es;q=0.9"}

# ─────────────────────────── caché con TTL (v19) ───────────────────────────
# data/webcache.json: {"q::<query>": {"ts": epoch, "data": [...]},
#                      "p::<url>":   {"ts": epoch, "data": "texto"}}
TTL_SEARCH = 1800      # 30 min para búsquedas normales
TTL_NEWS = 300         # 5 min para noticias (caducan rápido)
TTL_PAGE = 3600        # 1 h para el texto de una página
_CACHE_MAX = 300       # entradas máximas (se poda lo más viejo)


def _cache_file():
    from .comun.config import DATA_DIR
    return DATA_DIR / "webcache.json"


_MEM: dict | None = None          # caché en RAM (el disco solo se lee UNA vez)
_MEM_DIR = None                   # si DATA_DIR cambia (tests), se recarga


def _cache_load() -> dict:
    import json
    try:
        d = json.loads(_cache_file().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _mem() -> dict:
    """Caché viva en RAM; se hidrata del disco la primera vez (o si cambia DATA_DIR)."""
    global _MEM, _MEM_DIR
    here = str(_cache_file())
    if _MEM is None or _MEM_DIR != here:
        _MEM = _cache_load()
        _MEM_DIR = here
    return _MEM


def _cache_save(d: dict) -> None:
    """Vuelca a disco de forma ATÓMICA (tmp + replace): un corte a mitad de
    escritura ya no deja el archivo truncado ni pierde toda la caché."""
    import json
    import os
    global _MEM
    try:
        if len(d) > _CACHE_MAX:            # poda: fuera lo más viejo
            keep = sorted(d.items(), key=lambda kv: kv[1].get("ts", 0))[-_CACHE_MAX:]
            d = dict(keep)
        _MEM = d
        f = _cache_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, f)
    except Exception:
        pass


def cache_get(key: str, ttl: int):
    """Valor cacheado si no ha caducado; None si no está o caducó. Lee de RAM."""
    import time
    e = _mem().get(key)
    if e and (time.time() - e.get("ts", 0)) < ttl:
        return e.get("data")
    return None


def cache_put(key: str, data) -> None:
    import time
    d = _mem()
    d[key] = {"ts": time.time(), "data": data}
    _cache_save(d)


def _clean(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s or "")
    s = (s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
          .replace("&quot;", '"').replace("&#x27;", "'").replace("&#39;", "'")
          .replace("&nbsp;", " ").replace("&#x2019;", "'"))
    return re.sub(r"\s+", " ", s).strip()


async def _google_news(query: str, n: int) -> list[dict]:
    """Google News RSS: noticias recientes CON FECHA. Sin API key, muy estable."""
    url = "https://news.google.com/rss/search"
    params = {"q": query, "hl": "es-419", "gl": "ES", "ceid": "ES:es"}
    r = await net.client().get(url, params=params, headers=_HDRS, timeout=_TIMEOUT)
    xml = r.text or ""
    out: list[dict] = []
    for m in re.finditer(r"<item>(.*?)</item>", xml, re.DOTALL):
        block = m.group(1)
        t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", block, re.DOTALL)
        link = re.search(r"<link>(.*?)</link>", block, re.DOTALL)
        pub = re.search(r"<pubDate>(.*?)</pubDate>", block, re.DOTALL)
        title = _clean(t.group(1)) if t else ""
        if not title:
            continue
        fecha = _clean(pub.group(1))[:16] if pub else ""     # «Sat, 19 Jul 2026»
        out.append({"title": title,
                    "snippet": (f"({fecha}) " if fecha else "") + title,
                    "url": _clean(link.group(1)) if link else ""})
        if len(out) >= n:
            break
    return out


async def _ddg_lite(query: str, n: int) -> list[dict]:
    """DuckDuckGo Lite: HTML minimalista en tabla, muy tolerante al scraping."""
    r = await net.client().post("https://lite.duckduckgo.com/lite/", data={"q": query},
                                headers=_HDRS, timeout=_TIMEOUT)
    html = r.text or ""
    out: list[dict] = []
    # ancla que contenga result-link, con href y class en CUALQUIER orden
    links = []
    for m in re.finditer(r'<a\s+([^>]*?result-link[^>]*?)>(.*?)</a>', html, re.DOTALL):
        href = re.search(r'href="([^"]+)"', m.group(1))
        links.append((href.group(1) if href else "", m.group(2)))
    snips = re.findall(r'class=["\']result-snippet["\'][^>]*>(.*?)</td>', html, re.DOTALL)
    for i, (url, title) in enumerate(links[:n]):
        t = _clean(title)
        if not t:
            continue
        out.append({"title": t,
                    "snippet": _clean(snips[i]) if i < len(snips) else "",
                    "url": url})
    return out


async def _ddg_html(query: str, n: int) -> list[dict]:
    """DuckDuckGo HTML clásico."""
    r = await net.client().get("https://html.duckduckgo.com/html/",
                               params={"q": query, "kl": "es-es"},
                               headers=_HDRS, timeout=_TIMEOUT)
    html = r.text or ""
    out: list[dict] = []
    for m in re.finditer(
            r'result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
            r'result__snippet[^>]*>(.*?)</a>', html, re.DOTALL):
        title = _clean(m.group(2))
        if title:
            out.append({"title": title, "snippet": _clean(m.group(3)),
                        "url": m.group(1)})
        if len(out) >= n:
            break
    if not out:
        for s in re.findall(r'result__snippet[^>]*>(.*?)</a>', html, re.DOTALL)[:n]:
            txt = _clean(s)
            if txt:
                out.append({"title": "", "snippet": txt, "url": ""})
    return out


# Palabras que delatan una pregunta de NOTICIAS/actualidad → probar Google News primero.
_NEWS_RX = re.compile(
    r"\b(noticia|resultado|marcador|final|gan[oó]|mundial|champions|liga|partido|"
    r"elecciones|hoy|ayer|anoche|reciente|[uú]ltim|actualidad|pas[oó]|ocurri[oó]|"
    r"muri[oó]|fichaj|derbi|clasific)", re.IGNORECASE)


async def search(query: str, n: int = 6) -> list[dict]:
    """Resultados web [{title, snippet, url}]. Prueba varias fuentes hasta que una
    responda; [] solo si TODAS fallan. Para noticias antepone Google News.
    Con CACHÉ: repetir la misma búsqueda dentro del TTL no vuelve a la web."""
    query = (query or "").strip()
    if not query:
        return []
    is_news = bool(_NEWS_RX.search(query))
    ttl = TTL_NEWS if is_news else TTL_SEARCH
    key = f"q::{query.lower()}::{n}"
    hit = cache_get(key, ttl)
    if hit:
        return hit
    if is_news:
        sources = (_google_news, _ddg_lite, _ddg_html)
    else:
        sources = (_ddg_lite, _ddg_html, _google_news)
    for src in sources:
        try:
            res = await src(query, n)
            if res:
                cache_put(key, res)
                return res
        except Exception:
            continue
    return []


def extract_text(html: str, max_chars: int = 3500) -> str:
    """Extrae el TEXTO legible de un HTML (sin red). LINEAL a propósito: nada de
    patrones «<p>.*?</p>» que con etiquetas sin cerrar (HTML5 minificado las
    omite) se vuelven cuadráticos y congelan el event loop (revisión v19).
    Estrategia: quitar bloques basura, convertir límites de bloque en saltos de
    línea, pelar el resto de tags y filtrar líneas con sustancia."""
    html = (html or "")[:1_500_000]                    # tope duro de entrada
    # script/style/…: si no cierran, el resto del doc es basura → hasta el cierre o el final
    html = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>[\s\S]*?(?:</\1\s*>|$)", " ", html)
    # contenedores de adorno bien cerrados y acotados (nav/menús/pies); si no cierran, se dejan
    html = re.sub(r"(?is)<(header|footer|nav|aside|form)[^>]*>(?:(?!</\1)[\s\S]){0,20000}?</\1\s*>",
                  " ", html)
    # si hay article/main, el contenido de verdad suele vivir ahí (acotado)
    m = re.search(r"(?is)<(article|main)\b[^>]*>([\s\S]{0,200000}?)</\1\s*>", html)
    core = m.group(2) if m else html
    # límites de bloque → salto de línea; resto de tags → espacio (ambos lineales)
    core = re.sub(r"(?is)</?(p|div|li|ul|ol|h[1-6]|br|tr|td|table|section|article|main|blockquote)\b[^>]*>",
                  "\n", core)
    core = re.sub(r"<[^>]{0,300}>", " ", core)
    lines = [_clean(line) for line in core.split("\n")]
    parts = [line for line in lines if len(line) > 25]
    text = "\n".join(parts)
    if len(text) < 120:            # página sin estructura útil → texto plano
        text = _clean(html)
    return text[:max_chars]


async def fetch_page(url: str, max_chars: int = 3500) -> str:
    """Descarga una página y extrae su TEXTO legible. Con caché (1 h por URL).
    El troceo del HTML y la escritura de la caché van a un HILO: el event loop
    (HUD, voz, métricas) no se congela ni con páginas enormes."""
    import asyncio as _aio
    key = f"p::{url}"
    hit = cache_get(key, TTL_PAGE)
    if hit is not None:
        return hit[:max_chars]
    try:
        r = await net.client().get(url, headers=_HDRS, timeout=_TIMEOUT)
        html = (r.text or "")[:1_500_000]          # tope de descarga procesada
    except Exception:
        return ""
    text = await _aio.to_thread(extract_text, html, max_chars)
    if text:
        await _aio.to_thread(cache_put, key, text)
    return text


async def research(question: str, n_results: int = 6, n_pages: int = 3) -> str:
    """PROTOCOLO tipo buscador (como Google o un analista): 1) BUSCA en varias
    fuentes, 2) ABRE y LEE las mejores páginas (scraping real, no solo titulares),
    3) devuelve un DOSSIER de evidencia con título/fecha/URL + contenido leído,
    para que el modelo responda SOLO con esto y citando la fuente."""
    import asyncio as _aio
    res = await search(question, n_results)
    if not res:
        return ""
    dossier: list[str] = []
    for i, r in enumerate(res[:n_results]):
        head = f"[FUENTE {i + 1}] {r.get('title') or '(sin título)'}"
        if r.get("snippet") and r.get("snippet") != r.get("title"):
            head += f" — {r['snippet'][:200]}"
        if r.get("url"):
            head += f"\n  URL: {r['url']}"
        dossier.append(head)
    # abrir las mejores páginas EN PARALELO (lo que convierte titulares en datos)
    cand = [r for r in res if str(r.get("url", "")).startswith("http")][:n_pages]
    try:
        pages = await _aio.gather(*[fetch_page(r["url"]) for r in cand],
                                  return_exceptions=True)
    except Exception:
        pages = []
    for r, p in zip(cand, pages):
        if isinstance(p, str) and p:
            dossier.append(f"[CONTENIDO LEÍDO de «{(r.get('title') or r['url'])[:70]}»]\n{p[:2500]}")
    return "\n\n".join(dossier)


def summarize(results: list[dict], limit: int = 6) -> str:
    """Convierte los resultados en un bloque de texto para el contexto del modelo."""
    lines = []
    for r in results[:limit]:
        piece = r.get("title", "")
        if r.get("snippet"):
            piece = f"{piece}: {r['snippet']}" if piece else r["snippet"]
        if piece:
            lines.append("- " + piece[:300])
    return "\n".join(lines)
