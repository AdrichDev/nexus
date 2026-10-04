# -*- coding: utf-8 -*-
"""Wrong-answer feedback triggers re-research and contrast (R2).

The operator does not need to know the right answer: saying "that is wrong"
makes Nexus search NEW sources, contrast its previous answer and report
confirm / correct / insufficient. A model verdict counts only when it quotes
literal text from a cited source. A correction is stored as a fact only after
explicit confirmation. Pure logic with fakes: no network, no DB, no model.

Run: .venv\\Scripts\\python.exe tests\\unit\\core\\learning\\test_correcciones_confirmadas.py
"""
import ast
import asyncio
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
MOD_PATH = ROOT / "backend/core/dominio/correcciones.py"
BRAIN = ROOT / "backend/core/aplicacion/brain.py"

_fail = []
_pass = 0


def check(c, m):
    global _pass
    if c:
        _pass += 1
    else:
        _fail.append(m)
        print("  FALLO:", m)


def load():
    spec = importlib.util.spec_from_file_location("correcciones_under_test", MOD_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


Q = "¿Quién ganó el Mundial femenino de 2023?"
OLD = "Lo ganó Estados Unidos. Fuente: https://old.example/usa"
HISTORY = [{"role": "user", "content": Q}, {"role": "assistant", "content": OLD}]
PAGES = {
    "https://old.example/usa": "Estados Unidos ganó el Mundial femenino de 2019.",
    "https://a.example/1": "España ganó la Copa Mundial Femenina de la FIFA 2023 al vencer a Inglaterra.",
    "https://b.example/2": "La selección española se proclamó campeona del mundo en Sídney en 2023.",
    "https://c.example/3": "Inglaterra fue subcampeona del Mundial femenino 2023.",
    "https://d.example/4": "Crónica: España levanta su primera Copa del Mundo femenina.",
    "https://consent.google.com/ml": "Antes de ir a Google, usamos cookies",
}
RESULTS = [{"title": u, "url": u, "snippet": t[:40]} for u, t in PAGES.items()]


def verdict(**kw):
    return json.dumps(kw, ensure_ascii=False)


CORRIGE = verdict(veredicto="corrige", respuesta="Lo ganó España.", fuentes=[1],
                  cita="España ganó la Copa Mundial Femenina de la FIFA 2023")


class Fakes:
    def __init__(self, raw=CORRIGE, results=None, pages=None):
        self.raw = raw
        self.results = RESULTS if results is None else results
        self.pages = PAGES if pages is None else pages
        self.queries, self.fetched, self.prompts, self.stored = [], [], [], []

    async def search(self, query, n=6):
        self.queries.append(query)
        return list(self.results)

    async def fetch(self, url):
        self.fetched.append(url)
        return self.pages.get(url, "")

    async def ask(self, system, user):
        self.prompts.append((system, user))
        return self.raw

    async def store(self, text, kind="knowledge", meta=None):
        self.stored.append({"text": text, "kind": kind, "meta": dict(meta or {})})
        return True

    def kw(self):
        return dict(search=self.search, store=self.store, ask=self.ask, fetch=self.fetch)


def run(coro):
    return asyncio.run(coro)


def h(c, text, f, history=HISTORY, channel="pc"):
    return run(c.handle(text, channel, history, **f.kw()))


def main():
    if not MOD_PATH.exists():
        check(False, "backend/core/dominio/correcciones.py exists")
        return
    c = load()

    print("== detection ==")
    for t in ("esa respuesta no es correcta", "Eso está mal", "no es correcto",
              "te equivocas", "esa respuesta es incorrecta"):
        check(c.es_queja_respuesta(t), f"feedback detected: {t!r}")
    for t in ("apaga la tele", "no quiero que leas correos", "sí", "pon música",
              "¿qué tiempo hace en Madrid?", "lo correcto es apagar la luz"):
        check(not c.es_queja_respuesta(t), f"not feedback: {t!r}")

    print("== nothing pending: no interception ==")
    c.reset()
    f = Fakes()
    for t in ("sí", "confirmo", "no", "lo correcto es España", "apaga la tele"):
        check(h(c, t, f) is None, f"no pending -> {t!r} not intercepted")
    check(not (f.stored or f.queries or f.prompts), "no work without pending state")

    print("== complaint -> re-research NEW sources and correct ==")
    c.reset()
    f = Fakes()
    r = h(c, "esa respuesta no es correcta", f)
    check(f.queries and Q in f.queries[0], "searches the original question itself")
    check(any(q.startswith("Lo gan\u00f3 Estados Unidos") and "http" not in q for q in f.queries),
          "also searches the disputed claim (without URLs)")
    check("https://old.example/usa" not in f.fetched, "source already used is excluded")
    check("https://consent.google.com/ml" not in f.fetched, "consent page excluded")
    check(len(f.fetched) == 3, "reads up to 3 new sources")
    check(f.prompts and OLD in f.prompts[0][1] and "https://a.example/1" in f.prompts[0][1],
          "model contrasts previous answer against fetched sources")
    check("no era correcta" in r and "Lo ganó España." in r, "reports the correction")
    check("https://a.example/1" in r and "España ganó la Copa" in r, "shows source and quote")
    check("guarde" in r, "asks to save")
    check(f.stored == [], "nothing stored before confirmation")
    st = c.estado("pc")
    check(st["estado"] == "propuesta" and st["pregunta"] == Q and st["respuesta"] == OLD,
          "proposal bound to question and previous answer")

    print("== confirmation stores fact with provenance ==")
    r2 = h(c, "sí", f)
    check("Guardada" in r2 and len(f.stored) == 1, "stored once after confirmation")
    rec = f.stored[0] if f.stored else {"meta": {}, "text": "", "kind": ""}
    m = rec["meta"]
    check(rec["kind"] == "fact" and "Lo ganó España." in rec["text"] and Q in rec["text"],
          "fact text has correction and question")
    check(m.get("confirmado_por") == "usuario" and m.get("fuente") == "https://a.example/1",
          "provenance: confirmed by user + source")
    check("España ganó" in m.get("extracto", "") and m.get("respuesta_anterior") == OLD
          and m.get("fecha"), "provenance: quote, previous answer, date")
    check(c.estado("pc") is None and h(c, "sí", f) is None, "state cleared; later 'sí' free")

    print("== diagnostics for the operator log ==")
    c.reset()
    f = Fakes()
    h(c, "esa respuesta no es correcta", f)
    d = c.diagnostico("pc")
    check(d and d["veredicto"] == "corrige" and "https://a.example/1" in d["fuentes"]
          and "corrige" in d["modelo"], "last contrast exposes sources, verdict and raw model output")
    check("correcciones.diagnostico(channel)" in BRAIN.read_text(encoding="utf-8"),
          "brain logs the contrast diagnostics")

    print("== rejection discards ==")
    c.reset()
    f = Fakes()
    h(c, "eso está mal", f)
    check("descarto" in h(c, "no", f) and f.stored == [] and c.estado("pc") is None,
          "'no' discards proposal")

    print("== sources confirm previous answer ==")
    c.reset()
    f = Fakes(raw=verdict(veredicto="confirma", respuesta="Lo ganó España.", fuentes=[2],
                          cita="se proclamó campeona del mundo en Sídney"))
    r3 = h(c, "te equivocas", f)
    check("respaldan" in r3 and "https://b.example/2" in r3, "reports confirmation with source")
    check(c.estado("pc")["estado"] == "pendiente" and f.stored == [],
          "confirmation keeps pending, stores nothing")

    print("== bare 'no' right after a contrast disputes it (real-prod regression) ==")
    hist_c = HISTORY + [{"role": "user", "content": "te equivocas"},
                        {"role": "assistant", "content": r3}]
    n_prompts = len(f.prompts)
    r3b = h(c, "no", f, history=hist_c)
    check(isinstance(r3b, str) and "Sigue sin resolver" in r3b and len(f.prompts) == n_prompts + 1,
          "'no' after a contrast triggers a new contrast instead of the chat model giving in")
    hist_other = hist_c + [{"role": "user", "content": "pon m\u00fasica"},
                           {"role": "assistant", "content": "\u00bfQuieres que siga la lista anterior?"}]
    check(h(c, "no", f, history=hist_other) is None,
          "'no' answering an unrelated question is not intercepted")
    c.reset()
    f = Fakes(raw=verdict(veredicto="confirma", respuesta="Lo gan\u00f3 Espa\u00f1a.", fuentes=[2],
                          cita="se proclam\u00f3 campeona del mundo en S\u00eddney"))
    r3 = h(c, "te equivocas", f)

    print("== repeated complaint searches DIFFERENT sources ==")
    first = set(f.fetched)
    r4 = h(c, "esa respuesta no es correcta", f)
    second = set(f.fetched) - first
    check(c.estado("pc")["veces"] == 2 and "Sigue sin resolver" in r4,
          "repeat counted and reported unresolved")
    check(second and not (second & first), "second contrast reads only unseen sources")
    check(len(f.queries) >= 2 and f.queries[-1] != f.queries[0], "query widened on repeat")
    r5 = h(c, "esa respuesta no es correcta", f)
    check("ninguna utilizable" in r5 and "no doy" in r5.lower(),
          "exhausted sources: honest, does not validate answer")

    print("== hallucinated verdicts are rejected ==")
    bad = {
        "quote not in source": verdict(veredicto="corrige", respuesta="Lo ganó Japón.",
                                       fuentes=[1], cita="Japón ganó el Mundial femenino 2023"),
        "invalid source index": verdict(veredicto="corrige", respuesta="Lo ganó España.",
                                        fuentes=[9], cita="España ganó la Copa Mundial Femenina"),
        "no json": "Creo que fue España.",
        "unknown verdict": verdict(veredicto="seguro", respuesta="España", fuentes=[1],
                                   cita="España ganó la Copa Mundial Femenina"),
        "empty quote": verdict(veredicto="corrige", respuesta="España", fuentes=[1], cita=""),
    }
    for label, raw in bad.items():
        c.reset()
        f = Fakes(raw=raw)
        r6 = h(c, "esa respuesta no es correcta", f)
        check("no bastan" in r6 and "Japón" not in r6, f"{label}: treated as insufficient")
        check(c.estado("pc")["estado"] == "pendiente" and h(c, "sí", f) is None
              and f.stored == [], f"{label}: nothing to confirm or store")

    print("== disputed claim is searched without markdown ==")
    c.reset()
    f = Fakes()
    md = [{"role": "user", "content": "\u00bfCu\u00e1l es el r\u00edo m\u00e1s largo de Espa\u00f1a?"},
          {"role": "assistant", "content": "El r\u00edo m\u00e1s largo es el **Tajo**, aunque pasa por Portugal. \u2014nexus"}]
    h(c, "esa respuesta no es correcta", f, history=md)
    check(any(q.startswith("El r\u00edo m\u00e1s largo es el Tajo, aunque pasa por Portugal") for q in f.queries)
          and not any("*" in q for q in f.queries), f"claim query is clean: {f.queries[:2]}")

    long_claim = c._afirmacion("El r\u00edo m\u00e1s largo de Espa\u00f1a es el **Tajo**; si hablamos del m\u00e1s "
                                "largo que discurre \u00edntegramente por Espa\u00f1a, es el Ebro. \u2014nexus")
    check(long_claim == "El r\u00edo m\u00e1s largo de Espa\u00f1a es el Tajo", f"claim cut at first clause: {long_claim!r}")
    check(len(c._afirmacion("palabra " * 40).split()) <= 14, "claim length bounded")
    check(c._afirmacion("nexus: El **Tajo** es el r\u00edo m\u00e1s largo. M\u00e1s texto.")
          == "El Tajo es el r\u00edo m\u00e1s largo", "assistant-name prefix is not part of the claim")
    job = ("\u2714 Trabajo #26 terminado (#27: dime la capital de Mongolia):\n\n"
           "Ya lo tengo #27 \u2014 \u00abdime la capital de Mongolia\u00bb:\n\n"
           "Ul\u00e1n Bator es la capital de Mongolia.")
    check(c._afirmacion(job) == "Ul\u00e1n Bator es la capital de Mongolia",
          f"job/Hermes headers are not the disputed claim: {c._afirmacion(job)!r}")

    print("== quote matching ignores typography, not content ==")
    c.reset()
    spaced = dict(PAGES)
    spaced["https://a.example/1"] = "El Ebro es un r\u00edo de la pen\u00ednsula ib\u00e9rica , el segundo m\u00e1s largo , tras el Tajo ."
    f = Fakes(raw=verdict(veredicto="corrige", respuesta="El Tajo.", fuentes=[1],
                          cita="\u00abla pen\u00ednsula ib\u00e9rica, el segundo m\u00e1s largo, tras el Tajo.\u00bb"), pages=spaced)
    check("no era correcta" in h(c, "esa respuesta no es correcta", f),
          "spacing before commas and quote marks do not break a literal quote")
    c.reset()
    f = Fakes(raw=verdict(veredicto="corrige", respuesta="El Duero.", fuentes=[1],
                          cita="la pen\u00ednsula ib\u00e9rica, el segundo m\u00e1s largo, tras el Duero"), pages=spaced)
    check("no bastan" in h(c, "esa respuesta no es correcta", f),
          "a changed word still fails the literal-quote check")

    print("== no sources / consent only / failures ==")
    for label, kw in (("no results", {"results": []}),
                      ("consent only", {"results": [RESULTS[-1]]})):
        c.reset()
        f = Fakes(**kw)
        r7 = h(c, "esa respuesta no es correcta", f)
        check("ninguna utilizable" in r7 and f.prompts == [], f"{label}: honest, no model call")
        check(c.estado("pc")["estado"] == "pendiente", f"{label}: stays pending")
    c.reset()
    f = Fakes()

    async def boom(*a, **k):
        raise RuntimeError("offline")
    r8 = run(c.handle("esa respuesta no es correcta", "pc", HISTORY, search=boom,
                      store=f.store, ask=boom, fetch=boom))
    check(isinstance(r8, str) and f.stored == [], "infrastructure failure is honest")

    print("== readable pages win over snippet-only results ==")
    c.reset()
    unreadable = [{"title": "t", "url": f"https://news.example/{i}", "snippet": f"Titular {i} sobre el Mundial"}
                  for i in range(3)]
    f = Fakes(results=unreadable + RESULTS[1:3])
    h(c, "esa respuesta no es correcta", f)
    user = f.prompts[0][1] if f.prompts else ""
    check("https://a.example/1" in user and "https://b.example/2" in user,
          "readable pages are contrasted")
    check(user.count("https://news.example/") == 1, "snippet-only results only fill gaps")
    c.reset()
    f = Fakes(results=unreadable)
    h(c, "esa respuesta no es correcta", f)
    check(f.prompts and "Titular 0" in f.prompts[0][1],
          "snippets used as last resort when nothing is readable")

    print("== page reads are capped ==")
    c.reset()
    many = [{"title": "t", "url": f"https://slow.example/{i}", "snippet": f"s{i}"}
            for i in range(40)]
    f = Fakes(results=many)
    h(c, "esa respuesta no es correcta", f)
    check(len(f.fetched) <= 8, f"at most 8 page fetches per contrast ({len(f.fetched)})")
    check(f.prompts and "s0" in f.prompts[0][1], "falls back to snippets after the cap")

    print("== optional user hint is contrasted, not trusted ==")
    c.reset()
    f = Fakes(raw=verdict(veredicto="insuficiente", respuesta="", fuentes=[], cita=""))
    h(c, "esa respuesta no es correcta", f)
    r9 = h(c, "lo correcto es que ganó Japón", f)
    check(f.prompts and "Japón" in f.prompts[-1][1], "user hint passed to contrast")
    check("no bastan" in r9 and f.stored == [], "unsupported user hint is not stored")

    print("== injected source filter is honoured ==")
    c.reset()
    f = Fakes()
    run(c.handle("esa respuesta no es correcta", "pc", HISTORY, rechazada=lambda **k: True,
                 **f.kw()))
    check(f.fetched == [] and f.prompts == [], "rejected sources never read or contrasted")

    print("== a newer answer gets its own review (real-prod regression) ==")
    c.reset()
    f = Fakes(raw=verdict(veredicto="confirma", respuesta="Lo gan\u00f3 Espa\u00f1a.", fuentes=[2],
                          cita="se proclam\u00f3 campeona del mundo en S\u00eddney"))
    h(c, "esa respuesta no es correcta", f)
    q2 = "\u00bfCu\u00e1l es la capital de Australia?"
    hist_new = HISTORY + [{"role": "user", "content": q2},
                          {"role": "assistant", "content": "La capital de Australia es S\u00eddney."}]
    r11 = h(c, "eso no es correcto", f, history=hist_new)
    st = c.estado("pc")
    check(st["pregunta"] == q2 and st["veces"] == 1, "complaint binds to the latest answer")
    check("Sigue sin resolver" not in r11 and q2 in f.prompts[-1][1]
          and "S\u00eddney." in f.prompts[-1][1], "new review contrasts the newer answer")

    print("== per channel, and no context ==")
    c.reset()
    f = Fakes()
    h(c, "esa respuesta no es correcta", f)
    check(c.estado("mobile") is None, "state is per channel")
    c.reset()
    r10 = h(c, "esa respuesta no es correcta", f, history=[])
    check("qué respuesta" in r10 and c.estado("pc") is None, "no answer to review: asks")

    print("== brain wiring ==")
    src = BRAIN.read_text(encoding="utf-8")
    ast.parse(src)
    check("correcciones.handle(" in src, "brain calls correcciones.handle")
    check("rechazada=websearch._rejected_source_evidence" in src
          and "fetch=websearch.fetch_page" in src
          and "websearch.search(q, n, news=False)" in src,
          "brain injects central search, fetch and consent filter")
    i_conf = src.find("_cf.answer(text, channel)")
    i_corr = src.find("correcciones.handle(")
    i_mem = src.find("mrem = _REMEMBER_RX.match(text)")
    check(0 < i_conf < i_corr < i_mem,
          "handler runs after destructive confirmation, before memory routes")
    blk = src[i_corr:i_mem]
    check("timeout=" in blk and "No he podido completar la revisi" in blk,
          "timeout/failure of a complaint answers honestly instead of falling through")
    dom = MOD_PATH.read_text(encoding="utf-8")
    check("infraestructura" not in dom and "aplicacion" not in dom,
          "domain module does not import upper layers")


if __name__ == "__main__":
    main()
    print("\n" + "=" * 50)
    print(f"{_pass} pasados, {len(_fail)} fallados")
    sys.exit(1 if _fail else 0)
