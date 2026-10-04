# -*- coding: utf-8 -*-
"""Research source evidence regressions: no live imports, no network."""
import asyncio
import importlib.util
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]

_fail = []
_pass = 0


def check(c, m):
    global _pass
    if c:
        _pass += 1
    else:
        _fail.append(m)
        print("  FALLO:", m)


class Resp:
    def __init__(self, text, url=None):
        self.text = text
        self.url = url


class FakeHTTP:
    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    async def get(self, url, **kw):
        self.calls.append((url, kw))
        return self.resp


def load_websearch(resp=None):
    pkg_names = ["backend", "backend.core", "backend.core.infraestructura", "backend.core.comun"]
    old = {name: sys.modules.get(name) for name in pkg_names + ["backend.core.comun.net"]}
    for name in pkg_names:
        sys.modules[name] = types.ModuleType(name)
    fake = FakeHTTP(resp or Resp(""))
    net = types.ModuleType("backend.core.comun.net")
    net.client = lambda: fake
    sys.modules["backend.core.comun.net"] = net
    mod = types.ModuleType("backend.core.infraestructura.websearch")
    mod.__file__ = str(ROOT / "backend/core/infraestructura/websearch.py")
    mod.__package__ = "backend.core.infraestructura"
    sys.modules[mod.__name__] = mod
    code = (ROOT / "backend/core/infraestructura/websearch.py").read_text(encoding="utf-8")
    exec(compile(code, mod.__file__, "exec"), mod.__dict__)
    mod._TEST_OLD_MODULES = old
    mod._TEST_FAKE_HTTP = fake
    mod._MEM = {}
    mod._cache_file = lambda: ROOT / "data" / "__test_webcache_never_used.json"
    mod._cache_save = lambda d: setattr(mod, "_MEM", d)
    return mod


def load_skill():
    spec = importlib.util.spec_from_file_location("research_skill_under_test", ROOT / "skills/research/skill.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def test_fetch_page_rejects_consent_cache_request_final_and_html():
    consent_text = "Before you continue to Google, accept all cookies or reject all."
    mod = load_websearch(Resp("<article>Real article body with enough useful words to keep extraction happy.</article>"))
    mod._MEM = {"p::https://example.test/a": {"ts": time.time(), "data": consent_text}}
    mod._MEM_DIR = str(mod._cache_file())
    got = await mod.fetch_page("https://example.test/a")
    check(got == "", "cached Google consent text is not returned as page evidence")

    mod = load_websearch(Resp("<article>Real article body with enough useful words to keep extraction happy.</article>",
                              url="https://consent.google.com/m?continue=https://example.test/a"))
    got = await mod.fetch_page("https://example.test/a")
    check(got == "", "redirect final URL on consent.google is rejected")
    check(mod._MEM == {}, "redirect consent page is not cached")

    html = "<main>Antes de continuar a Google Aceptar todo Rechazar todo Más opciones</main>"
    mod = load_websearch(Resp(html, url="https://example.test/a"))
    got = await mod.fetch_page("https://example.test/a")
    check(got == "", "Spanish Google consent/interstitial HTML is rejected")

    mod = load_websearch(Resp("<main>" + "This ordinary article discusses cookie consent banners in Europe. " * 8 + "</main>"))
    got = await mod.fetch_page("https://example.test/article")
    check("ordinary article discusses cookie consent" in got,
          "ordinary articles mentioning cookie consent are still accepted")


async def test_research_dossier_omits_rejected_snippet_fallback():
    mod = load_websearch(Resp("Before you continue to Google accept all cookies reject all"))

    async def fake_search(q, n):
        return [
            {"title": "Consent page", "snippet": "Before you continue to Google", "url": "https://consent.google.com/m"},
            {"title": "Useful result", "snippet": "A normal snippet", "url": "https://example.test/useful"},
        ]

    async def fake_fetch(url):
        return "Useful article body with verified source evidence." if "useful" in url else ""

    mod.search = fake_search
    mod.fetch_page = fake_fetch
    dossier = await mod.research("anything", n_results=2, n_pages=2)
    check("Consent page" not in dossier and "consent.google" not in dossier,
          "rejected consent result cannot reappear through snippet fallback")
    check("Useful result" in dossier and "Useful article body" in dossier,
          "non-rejected useful result remains in dossier")


async def test_full_report_preserves_query_and_no_sources_when_fetches_rejected():
    mod = load_skill()
    seen = []

    async def fake_search(q, n=6):
        seen.append(q)
        return [
            {"title": "Consent", "url": "https://consent.google.com/m", "snippet": "Before you continue"},
            {"title": "Empty", "url": "https://example.test/empty", "snippet": "empty"},
        ]

    async def fake_fetch(url, limit=4000):
        return ""

    async def fake_llm(prompt):
        return ("modelo sin fuentes", None)

    llm = types.ModuleType("backend.core.infraestructura.llm")
    llm.ask_llm = fake_llm
    old_llm = sys.modules.get(llm.__name__)
    sys.modules[llm.__name__] = llm
    old_browser = mod.webbrowser.open
    mod.webbrowser.open = lambda *a, **k: None
    mod._ddg_search = fake_search
    mod._fetch_text = fake_fetch
    try:
        out = await mod._full_report("fifa 2022 stadiums", "Redacta")
    finally:
        mod.webbrowser.open = old_browser
        if old_llm is None:
            sys.modules.pop(llm.__name__, None)
        else:
            sys.modules[llm.__name__] = old_llm
    check(seen == ["fifa 2022 stadiums"], f"query temporal exacta preservada: {seen}")
    check(out["sources"] == [], "no useful fetched source means no cited sources")
    check("Consent" not in out["reply"] and "Empty" not in out["reply"],
          "no source listing appears when all candidate pages are unusable")
    check("No he podido leer NINGUNA fuente" in out["reply"],
          "zero useful sources is reported as a limitation")


def main():
    print("· source evidence rejects consent without rejecting normal articles")
    asyncio.run(test_fetch_page_rejects_consent_cache_request_final_and_html())
    print("· snippets from rejected pages are not evidence")
    asyncio.run(test_research_dossier_omits_rejected_snippet_fallback())
    print("· full report preserves user time intent and stays honest with zero useful sources")
    asyncio.run(test_full_report_preserves_query_and_no_sources_when_fetches_rejected())
    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
