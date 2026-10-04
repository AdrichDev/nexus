# -*- coding: utf-8 -*-
"""Google results through a headless browser: parsing, block detection, order.

The browser itself is not launched here (no network); `_google_browser` is
replaced by fakes. Real Google is exercised in production checks.

Run: .venv\\Scripts\\python.exe tests\\unit\\skills\\research\\test_google_browser.py
"""
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
os.environ.setdefault("NEXUS_DATA_DIR", tempfile.mkdtemp(prefix="nexus_gbrowser_"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.infraestructura import websearch as w   # noqa: E402

_fail = []
_pass = 0


def check(c, m):
    global _pass
    if c:
        _pass += 1
    else:
        _fail.append(m)
        print("  FALLO:", m)


SERP = """
<html><body><div id="search">
 <div class="g"><div><a href="https://es.wikipedia.org/wiki/Tajo" ping="/url?x"><br><h3 class="LC20lb">Tajo - Wikipedia, la enciclopedia libre</h3></a></div>
  <div class="VwiC3b">El <em>Tajo</em> es el río más largo de la península ibérica, con 1007 km.</div></div>
 <div class="g"><a href="/url?q=https://www.iagua.es/rios-espana&amp;sa=U"><h3>Los ríos más largos de España</h3></a>
  <div class="VwiC3b">Ranking de los ríos más largos de España.</div></div>
 <div class="g"><a jsname="UWckNb" class="zReHs" href="/goto?url=CAESabc&amp;ved=1"><h3>Fundación Aquae: el río más largo</h3></a>
  <div class="VwiC3b"><span>El río más largo de España es el Ebro.</span></div></div>
 <div class="g"><a href="https://www.google.com/search?q=related"><h3>Búsquedas relacionadas</h3></a></div>
 <div class="g"><a href="https://maps.google.com/x"><h3>Maps</h3></a></div>
 <div class="g"><a href="https://es.wikipedia.org/wiki/Tajo"><h3>Tajo duplicado</h3></a></div>
</div></body></html>
"""


def main():
    print("== parse Google result page ==")
    res = w._parse_google_results(SERP, 10)
    urls = [r["url"] for r in res]
    check(urls == ["https://es.wikipedia.org/wiki/Tajo", "https://www.iagua.es/rios-espana",
                   "https://www.google.com/goto?url=CAESabc&ved=1"],
          f"organic results only, /url?q= unwrapped, /goto kept for resolution, google links and duplicates dropped: {urls}")
    check(w._is_google_goto(urls[-1]) and not w._is_google_goto(urls[0]), "goto links recognised")
    check(res[-1]["snippet"] == "El río más largo de España es el Ebro.", "goto result keeps its snippet")

    print("== resolve /goto redirects to real destinations ==")

    async def fake_resolver(url):
        return {"https://www.google.com/goto?url=CAESabc&ved=1": "https://www.fundacionaquae.org/rio"}.get(url)
    final = asyncio.run(w._resolve_google_results(res, fake_resolver, 10))
    check([r["url"] for r in final] == ["https://es.wikipedia.org/wiki/Tajo", "https://www.iagua.es/rios-espana",
                                        "https://www.fundacionaquae.org/rio"],
          f"goto replaced by its real destination: {[r['url'] for r in final]}")

    async def failing_resolver(url):
        return None
    final = asyncio.run(w._resolve_google_results(res, failing_resolver, 10))
    check(all(not w._is_google_goto(r["url"]) for r in final) and len(final) == 2,
          "unresolvable goto links are dropped, never shown as sources")

    async def to_google(url):
        return "https://www.google.com/maps"
    final = asyncio.run(w._resolve_google_results(res, to_google, 10))
    check(len(final) == 2, "a goto that resolves back into Google is dropped")
    check(len(asyncio.run(w._resolve_google_results(res, fake_resolver, 1))) == 1, "respects n after resolution")
    check(res and res[0]["title"] == "Tajo - Wikipedia, la enciclopedia libre", "title from h3")
    check(res and "río más largo de la península" in res[0]["snippet"] and "<em>" not in res[0]["snippet"],
          "snippet text extracted without markup")
    check(len(w._parse_google_results(SERP, 1)) == 1, "respects n")
    check(w._parse_google_results("", 5) == [], "empty page -> no results")

    print("== block detection ==")
    check(w._google_blocked("https://www.google.com/sorry/index?continue=x", ""), "/sorry/ URL is a block")
    check(w._google_blocked("https://www.google.com/search?q=x",
                            "Our systems have detected unusual traffic from your computer network"),
          "unusual-traffic page is a block")
    check(w._google_blocked("https://www.google.com/search?q=x",
                            "Nuestros sistemas han detectado tráfico inusual procedente de tu red"),
          "Spanish unusual-traffic page is a block")
    check(not w._google_blocked("https://www.google.com/search?q=x", SERP), "normal SERP is not a block")
    sorry = "https://www.google.com/sorry/index?continue=https://www.google.com/search%3Fq%3Dx"
    check(w._google_page_state(sorry, "") == "blocked",
          "a /sorry/ page is a block even though it carries continue= (was mistaken for consent)")
    check(w._google_page_state("https://consent.google.com/ml?continue=x", "") == "consent",
          "consent page detected")
    check(w._google_page_state("https://www.google.com/search?q=x", SERP) == "ok", "results page ok")

    print("== browser launch: real Chrome, off-screen window (headless is CAPTCHA-blocked) ==")
    opts = w._google_launch_options()
    check(opts[0].get("channel") == "chrome" and opts[0].get("headless") is False,
          "first choice is the installed Chrome with a normal (off-screen) window")
    check(any("--window-position=" in a for a in opts[0].get("args", [])), "window placed off-screen")
    check(len(opts) >= 2 and "channel" not in opts[1], "falls back to bundled Chromium")

    print("== search order and fallback ==")
    calls = []

    def src(name, out):
        async def f(q, n):
            calls.append(name)
            if isinstance(out, Exception):
                raise out
            return out
        return f
    orig = (w._google_browser, w._ddg_lite, w._ddg_html, w._wikipedia, w._google_news)
    try:
        w._MEM = {}
        w._cache_save = lambda d: None
        w._google_browser = src("google", [{"title": "g", "snippet": "s", "url": "https://g.example"}])
        w._ddg_lite, w._ddg_html = src("lite", []), src("html", [])
        w._wikipedia, w._google_news = src("wiki", []), src("news", [])
        got = asyncio.run(w.search("rio mas largo de Espana", 5, news=False))
        check(calls == ["google"] and got[0]["url"] == "https://g.example",
              f"general web search tries real Google first: {calls}")

        calls.clear()
        w._MEM = {}
        w._google_browser = src("google", w.GoogleBlocked("captcha"))
        w._ddg_lite = src("lite", [{"title": "d", "snippet": "s", "url": "https://d.example"}])
        got = asyncio.run(w.search("otra consulta", 5, news=False))
        check(calls == ["google", "lite"] and got[0]["url"] == "https://d.example",
              f"blocked Google falls back to the next source: {calls}")
        check(w._google_cooldown_until[0] > time.time() + 60, "a block starts a cooldown")
        calls.clear()
        w._MEM = {}
        asyncio.run(w.search("tercera consulta", 5, news=False))
        check(calls and calls[0] == "lite", f"during cooldown Google is not hammered: {calls}")
        w._google_cooldown_until[0] = 0.0
    finally:
        (w._google_browser, w._ddg_lite, w._ddg_html, w._wikipedia, w._google_news) = orig


if __name__ == "__main__":
    main()
    print("\n" + "=" * 50)
    print(f"{_pass} pasados, {len(_fail)} fallados")
    sys.exit(1 if _fail else 0)
