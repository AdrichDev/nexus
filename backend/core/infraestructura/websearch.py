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
import time
from urllib.parse import quote, urlparse

from ..comun import net

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
    from ..comun.config import DATA_DIR
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
    import html as _html
    s = re.sub(r"<[^>]+>", "", s or "")
    # Every entity (&#xF1; &oacute; ...), not a hand-picked few: undecoded
    # entities broke literal quotes from sources such as RTVE.
    s = _html.unescape(s).replace("\xa0", " ")
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


# --------------------- Google through a real (headless) browser ---------------------
# The operator wants Nexus to search "normal Google, as if it opened a browser".
# A persistent Chromium profile keeps the consent decision; CAPTCHA / "unusual
# traffic" pages are never treated as results: they start a cooldown and the
# search falls back to the other sources.

class GoogleBlocked(RuntimeError):
    """Google answered with a CAPTCHA / unusual-traffic page."""


_GOOGLE_COOLDOWN = 30 * 60
_google_cooldown_until = [0.0]
_GOOGLE_BROWSER: dict = {"pw": None, "ctx": None, "lock": None, "start_lock": None}
_CHROME_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")


def _google_blocked(url: str, html: str) -> bool:
    low = (html or "")[:20000].lower()
    return ("/sorry/" in (url or "") or "unusual traffic" in low
            or "tr\u00e1fico inusual" in low or "trafico inusual" in low)


def _google_host(url: str) -> bool:
    return bool(re.search(r"(^|\.)google\.[a-z.]+$", urlparse(url or "").netloc.lower()))


def _is_google_goto(url: str) -> bool:
    """Google now links results through opaque /goto?url=<token> redirects."""
    return _google_host(url) and urlparse(url).path == "/goto"


async def _resolve_google_results(items: list[dict], resolver, n: int) -> list[dict]:
    """Replace /goto links by their real destination (resolver -> URL or None).
    Unresolvable links, or ones pointing back into Google, are dropped: a
    source the operator cannot open is not a source."""
    out, seen = [], set()
    for it in items:
        url = it["url"]
        if _is_google_goto(url):
            try:
                url = await resolver(url) or ""
            except Exception:
                url = ""
        if not url.startswith("http") or _google_host(url) or url in seen:
            continue
        seen.add(url)
        out.append({**it, "url": url})
        if len(out) >= n:
            break
    return out


def _google_page_state(url: str, html: str) -> str:
    """"blocked" (CAPTCHA / unusual traffic), "consent" or "ok". The block is
    checked FIRST: a /sorry/ page carries continue= and looked like consent."""
    if _google_blocked(url, html):
        return "blocked"
    if _is_google_consent_url(url):
        return "consent"
    return "ok"


def _google_launch_options() -> list[dict]:
    """Measured 2026-10-04: Google answers headless Chromium (bundled or Chrome)
    with a CAPTCHA, but serves results to the installed Chrome with a normal
    window. So the window exists but is placed off-screen ("behind")."""
    args = ["--disable-blink-features=AutomationControlled",
            "--window-position=-2400,-2400", "--window-size=1200,900"]
    return [{"channel": "chrome", "headless": False, "args": args},
            {"headless": False, "args": args}]


def _parse_google_results(html: str, n: int) -> list[dict]:
    """Organic results [{title, snippet, url}] from a Google result page:
    anchors that wrap an <h3>, with /url?q= unwrapped and Google's own links,
    non-http links and duplicates dropped. Snippet = the following VwiC3b block."""
    from html.parser import HTMLParser
    from urllib.parse import parse_qs

    class _P(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.items, self.href, self.h3, self.in_h3 = [], None, "", False
            self.snip_depth, self.snip = 0, None

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if self.snip_depth:
                self.snip_depth += 1
            elif tag == "a":
                self.href, self.h3 = a.get("href") or "", ""
            elif tag == "h3" and self.href is not None:
                self.in_h3 = True
            elif "VwiC3b" in (a.get("class") or "") and self.items and self.snip is None:
                self.snip_depth, self.snip = 1, []

        def handle_endtag(self, tag):
            if self.snip_depth:
                self.snip_depth -= 1
                if not self.snip_depth:
                    self.items[-1]["snippet"] = _clean(" ".join(self.snip))
                    self.snip = None
            elif tag == "h3":
                self.in_h3 = False
            elif tag == "a" and self.href is not None:
                if self.h3.strip():
                    self.items.append({"title": _clean(self.h3), "snippet": "",
                                       "url": self.href})
                    self.snip = None
                self.href = None

        def handle_data(self, data):
            if self.snip_depth and self.snip is not None:
                self.snip.append(data)
            elif self.in_h3:
                self.h3 += data

    p = _P()
    try:
        p.feed(html or "")
    except Exception:
        pass
    out, seen = [], set()
    for it in p.items:
        url = it["url"]
        if url.startswith("/url?"):
            url = (parse_qs(url.split("?", 1)[1]).get("q") or [""])[0]
        elif url.startswith("/goto?"):
            url = "https://www.google.com" + url   # opaque redirect: resolved later
        if not url.startswith("http") or url in seen or \
                (_google_host(url) and not _is_google_goto(url)):
            continue
        seen.add(url)
        out.append({**it, "url": url})
        if len(out) >= n:
            break
    return out


async def _launch_google_context():
    from playwright.async_api import async_playwright
    from ..comun.config import DATA_DIR
    pw = await async_playwright().start()
    err = None
    for opts in _google_launch_options():
        try:
            ctx = await pw.chromium.launch_persistent_context(
                str(DATA_DIR / "browser_google"), locale="es-ES", **opts)
            _GOOGLE_BROWSER["pw"] = pw
            return ctx
        except Exception as exc:              # Chrome not installed -> bundled
            err = exc
    await pw.stop()
    raise RuntimeError(f"no pude abrir el navegador para Google: {err}")


async def _google_context():
    """The shared browser context, launched ONCE even if two searches start
    together (two launches on one profile fail: the profile is locked)."""
    import asyncio as _aio
    if _GOOGLE_BROWSER.get("start_lock") is None:
        _GOOGLE_BROWSER["start_lock"] = _aio.Lock()
    if _GOOGLE_BROWSER["lock"] is None:
        _GOOGLE_BROWSER["lock"] = _aio.Lock()
    async with _GOOGLE_BROWSER["start_lock"]:
        if _GOOGLE_BROWSER["ctx"] is None:
            _GOOGLE_BROWSER["ctx"] = await _launch_google_context()
    return _GOOGLE_BROWSER["ctx"]


async def _google_page():
    """A new tab; if the browser was closed or crashed, relaunch it once instead
    of failing every Google search until Nexus restarts."""
    ctx = await _google_context()
    try:
        return await ctx.new_page()
    except Exception:
        dead_pw = _GOOGLE_BROWSER.get("pw")
        _GOOGLE_BROWSER.update(ctx=None, pw=None)
        try:
            if dead_pw is not None:
                await dead_pw.stop()
        except Exception:
            pass
        return await (await _google_context()).new_page()


async def _google_browser(query: str, n: int) -> list[dict]:
    """Google web results via the installed Chrome (off-screen window). Raises
    GoogleBlocked on CAPTCHA."""
    from ..comun.config import settings
    if not settings.get("google_browser_search", True):
        return []
    await _google_context()
    async with _GOOGLE_BROWSER["lock"]:
        page = await _google_page()
        ctx = page.context
        try:
            await page.goto("https://www.google.com/search?hl=es&q=" + quote(query),
                            wait_until="domcontentloaded", timeout=20000)
            state = _google_page_state(page.url, await page.content())
            if state == "consent":
                for label in ("Rechazar todo", "Reject all"):
                    btn = page.get_by_role("button", name=label)
                    if await btn.count():
                        await btn.first.click()
                        await page.wait_for_load_state("domcontentloaded", timeout=15000)
                        break
                state = _google_page_state(page.url, await page.content())
            if state == "blocked":
                raise GoogleBlocked("Google pide CAPTCHA / tr\u00e1fico inusual")
            if state == "consent":
                return []
            try:
                await page.wait_for_selector("#search h3", timeout=8000)
            except Exception:
                pass
            items = _parse_google_results(await page.content(), n * 2)

            async def _resolver(url: str):
                r = await ctx.request.get(url, max_redirects=0, timeout=10000)
                return r.headers.get("location") if r.status in (301, 302, 303, 307, 308) else None
            return await _resolve_google_results(items, _resolver, n)
        finally:
            await page.close()


# Wikimedia's robot policy rejects generic browser user agents (HTTP 403).
_WIKI_HDRS = {"User-Agent": "NexusAssistant/1.0 (local personal assistant; "
                            "https://github.com/AdrichDev/nexus)"}


async def _wikipedia(query: str, n: int) -> list[dict]:
    """Wikipedia (es) search API: keyless, stable, readable pages. General-web
    fallback when DuckDuckGo answers with its anti-bot 202 page."""
    r = await net.client().get("https://es.wikipedia.org/w/api.php", params={
        "action": "query", "list": "search", "srsearch": query, "srlimit": n,
        "format": "json", "utf8": 1}, headers=_WIKI_HDRS, timeout=_TIMEOUT)
    out: list[dict] = []
    for hit in ((r.json() or {}).get("query") or {}).get("search") or []:
        title = _clean(hit.get("title", ""))
        if title:
            out.append({"title": title, "snippet": _clean(hit.get("snippet", "")),
                        "url": "https://es.wikipedia.org/wiki/" + quote(title.replace(" ", "_"))})
    return out[:n]


# Palabras que delatan una pregunta de NOTICIAS/actualidad → probar Google News primero.
_NEWS_RX = re.compile(
    r"\b(noticia|resultado|marcador|final|gan[oó]|mundial|champions|liga|partido|"
    r"elecciones|hoy|ayer|anoche|reciente|[uú]ltim|actualidad|pas[oó]|ocurri[oó]|"
    r"muri[oó]|fichaj|derbi|clasific)", re.IGNORECASE)


async def search(query: str, n: int = 6, news: bool | None = None) -> list[dict]:
    """Resultados web [{title, snippet, url}]. Prueba varias fuentes hasta que una
    responda; [] solo si TODAS fallan. Para noticias antepone Google News.
    Con CACHÉ: repetir la misma búsqueda dentro del TTL no vuelve a la web."""
    query = (query or "").strip()
    if not query:
        return []
    # news=None decides by the query; False forces general web first (fact checks
    # need readable pages, and Google News links are unreadable RSS wrappers).
    is_news = bool(_NEWS_RX.search(query)) if news is None else news
    ttl = TTL_NEWS if is_news else TTL_SEARCH
    key = f"q::{query.lower()}::{n}" + ("" if news is None else f"::news={news}")
    hit = cache_get(key, ttl)
    if hit:
        return hit
    if is_news:
        sources = (_google_news, _google_browser, _ddg_lite, _ddg_html)
    else:
        sources = (_google_browser, _ddg_lite, _ddg_html, _wikipedia, _google_news)
    for src in sources:
        if src is _google_browser and time.time() < _google_cooldown_until[0]:
            continue                       # blocked recently: do not hammer Google
        try:
            res = await src(query, n)
            if res:
                cache_put(key, res)
                return res
        except GoogleBlocked:
            _google_cooldown_until[0] = time.time() + _GOOGLE_COOLDOWN
            continue
        except Exception:
            continue
    return []


def _is_google_consent_url(url: str) -> bool:
    """Detecta URLs de consentimiento/intersticial de Google, no artículos normales."""
    try:
        p = urlparse(str(url or ""))
    except Exception:
        return False
    host = (p.netloc or "").split("@")[-1].split(":")[0].lower()
    path = (p.path or "").lower()
    if host.startswith("consent.google."):
        return True
    if ((host == "google.com" or host.startswith("www.google.") or host.startswith("google."))
            and path.startswith("/sorry")):
        return True
    return False


def _looks_like_google_consent(text: str) -> bool:
    """Detecta pantallas reales de consentimiento/bloqueo Google sin vetar artículos sobre cookies."""
    s = _clean((text or "")[:8000]).lower()
    if not s:
        return False
    explicit = (
        "before you continue to google",
        "antes de continuar a google",
        "consent.google.",
        "our systems have detected unusual traffic",
        "nuestros sistemas han detectado tráfico inusual",
    )
    if any(x in s for x in explicit):
        return True
    has_google = "google" in s
    consent_actions = sum(x in s for x in (
        "accept all", "reject all", "more options", "aceptar todo",
        "rechazar todo", "más opciones", "mas opciones"))
    policy_words = sum(x in s for x in (
        "cookies", "privacy", "privacidad", "terms", "términos", "terminos"))
    return has_google and consent_actions >= 2 and policy_words >= 1


def _rejected_source_evidence(url: str = "", final_url: str = "", text: str = "") -> bool:
    return (_is_google_consent_url(url) or _is_google_consent_url(final_url)
            or _looks_like_google_consent(text))


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
        return "" if _rejected_source_evidence(url=url, text=hit) else hit[:max_chars]
    if _rejected_source_evidence(url=url):
        return ""
    host = urlparse(url).netloc.lower()
    hdrs = _WIKI_HDRS if host.endswith("wikipedia.org") else _HDRS
    try:
        r = await net.client().get(url, headers=hdrs, timeout=_TIMEOUT)
        final_url = str(getattr(r, "url", "") or "")
        html = (r.text or "")[:1_500_000]          # tope de descarga procesada
    except Exception:
        return ""
    if int(getattr(r, "status_code", 200) or 200) >= 400:
        return ""                                  # error/block pages are not evidence
    if _rejected_source_evidence(url=url, final_url=final_url, text=html):
        return ""
    text = await _aio.to_thread(extract_text, html, max_chars)
    if _rejected_source_evidence(url=url, final_url=final_url, text=text):
        return ""
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
    res = [r for r in res if not _rejected_source_evidence(
        url=str(r.get("url", "")), text=f"{r.get('title', '')} {r.get('snippet', '')}")]
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
