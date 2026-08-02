# -*- coding: utf-8 -*-
"""Auditoría de la skill CONTENT OS: activación con frases naturales, enrutado
real, frontera con la skill `instagram`, y que sin cuenta conectada diga lo que
falta en vez de enseñar cifras de ejemplo.

También fija que la vía de descargar y transcribir reels ajenos sigue retirada:
es scraping de terceros y va contra la regla del proyecto.

No habla con la Graph API ni con el LLM: la skill se llama sin credenciales, que
es justo el camino que se audita.

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_skill_content_os.py
"""
from __future__ import annotations

import asyncio
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_fail, _pass = [], 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  ✖ " + msg)


from backend.core import skills_loader as sl                 # noqa: E402

print("== 1) carga con el cargador real ==")
REG = sl.load_skills()
SK = REG.get("content_os")
check(SK is not None and SK.status != "error",
      f"content_os no carga: {SK.description if SK else 'no registrada'}")
MOD = SK.module if SK else None
check(MOD is not None and hasattr(MOD, "handle"), "content_os no expone handle()")
for i in ("connect", "analytics", "best", "inspire", "patterns", "script", "ideas"):
    check(i in (SK.patterns if SK else {}), f"falta el intent «{i}»")

print("== 2) activación con frases naturales (tildes, enclíticos, sinónimos) ==")
ACTIVAN = {
    "connect": ["conecta mi instagram", "conéctame el instagram", "vincula mi instagram",
                "vincúlame mi instagram", "configura mi instagram",
                "configúrame mi instagram", "conecta el content os"],
    "analytics": ["analítica de instagram", "analítica de mi instagram",
                  "cómo va mi instagram", "qué tal va mi instagram",
                  "mis métricas de ig", "métricas de mi instagram",
                  "estadísticas de instagram", "alcance de mi ig"],
    "best": ["mis mejores reels", "reels ganadores", "qué reels me funcionan mejor",
             "top de reels", "ranking de reels", "mis mejores vídeos de instagram"],
    "patterns": ["analiza los patrones", "analízame los patrones", "patrones ganadores",
                 "qué patrones se repiten", "qué ganchos funcionan",
                 "qué estructuras se repiten"],
    "script": ["genera un guion sobre morning routines", "escríbeme un guion sobre café",
               "créame un guion de reel sobre viajes", "hazme un guion de reel para captar clientes",
               "prepárame un guion sobre fitness", "redáctame un guion para instagram"],
    "ideas": ["dame ideas de contenido", "dame ideas de reels", "ideas para reels",
              "quiero ideas para instagram", "qué subo a instagram",
              "qué publico en instagram"],
    "inspire": ["aprende de este reel https://instagram.com/reel/abc",
                "analiza el reel https://instagram.com/reel/abc",
                "estudia este reel https://x", "fíjate en el reel https://x"],
}
for intent, frases in ACTIVAN.items():
    for f in frases:
        r = sl.route(f)
        got = f"{r[0].folder}.{r[1]}" if r else "(nada)"
        check(got == f"content_os.{intent}", f"«{f}» → {got} (esperado content_os.{intent})")

print("== 3) frontera con la skill instagram: content_os solo se queda «mi/mis» ==")
DE_INSTAGRAM = ["cómo va el instagram", "analiza la cuenta de instagram de nasa",
                "analiza @nasa", "analiza la competencia", "qué hacen mis competidores"]
for f in DE_INSTAGRAM:
    r = sl.route(f)
    got = r[0].folder if r else "(nada)"
    check(got == "instagram", f"«{f}» → {got}: content_os se traga algo de instagram")


class _Settings(dict):
    def get(self, k, d=None):
        return dict.get(self, k, d)

    def secret(self, k):
        return self.get("__s_" + k, "")


class _Graph:
    def write_note(self, *a, **k):
        return None

    def search(self, *a, **k):
        return []


CTX = {"settings": _Settings(), "graph": _Graph(), "pg": None, "channel": "test"}
CIFRA = re.compile(r"\d[\d.,]*\s*(?:seguidores|%|K\b|reels)", re.IGNORECASE)


def run(intent, texto):
    m = SK.patterns[intent].search(texto)
    return asyncio.run(MOD.handle(intent, texto, m, CTX))


print("== 4) sin cuenta conectada: dice qué falta y NO enseña cifras ==")
for intent, texto in (("analytics", "analítica de instagram"),
                      ("best", "mis mejores reels")):
    r = run(intent, texto)
    check("ig_access_token" in r["reply"], f"{intent} no dice qué credencial falta")
    check(not CIFRA.search(r["reply"]), f"{intent} enseña cifras sin cuenta conectada: {r['reply'][:120]}")
    check("Traceback" not in r["reply"], f"{intent} suelta traceback")
r = run("analytics", "analítica de instagram")
check("no me lo voy a inventar" in r["reply"], "la analítica no deja claro que no inventa")
check("developers.facebook.com" in r["reply"], "no dice dónde se saca el token")

print("== 5) la vía de descargar reels ajenos sigue retirada ==")
try:
    MOD._download_and_transcribe("https://instagram.com/reel/x")
    check(False, "_download_and_transcribe vuelve a descargar reels ajenos")
except RuntimeError as exc:
    check("scraping" in str(exc), "la vía retirada no explica por qué está retirada")
except Exception as exc:
    check(False, f"_download_and_transcribe falla con algo raro: {type(exc).__name__}")

r = run("inspire", "aprende de este reel https://instagram.com/reel/abc")
check("scraping" in r["reply"], "«aprende de este reel» no explica por qué no lo hace")
check("business_discovery" in r["reply"], "no ofrece la vía legítima (Graph API)")
check("yt-dlp" not in r["reply"], "sigue ofreciendo yt-dlp")

print("== 6) sin transcripciones, los patrones no se inventan ==")
_insp = MOD._load_inspirations
MOD._load_inspirations = lambda: []
r = run("patterns", "analiza los patrones")
check("No tengo ninguna transcripción" in r["reply"], "sin material no lo dice")
check("business_discovery" in r["reply"], "sin material no ofrece la vía legítima")
MOD._load_inspirations = _insp

print("== 7) SKILL.md: sin promesas de scraping ni de cifras de ejemplo ==")
doc = SK.doc or ""
check("pip install yt-dlp" not in doc and "necesita yt-dlp" not in doc,
      "el SKILL.md sigue pidiendo instalar yt-dlp como requisito")
check("retirada" in doc, "el SKILL.md no dice que la vía de descargar reels está retirada")
check("los descarga y transcribe" not in doc, "el SKILL.md sigue prometiendo descargar reels ajenos")
check("ejemplo coherente" not in doc, "el SKILL.md sigue prometiendo cifras de ejemplo")
check("Qué NO hace" in doc, "el SKILL.md no dice qué NO hace")
check("ig_access_token" in doc and "ig_user_id" in doc, "el SKILL.md no dice qué hay que configurar")
for propio in ("Adri", "achoz", "@adri"):
    check(propio not in doc, f"el SKILL.md nombra algo del usuario: {propio}")

print(f"\n{'#'*54}\n{_pass} comprobaciones OK, {len(_fail)} fallos")
for m in _fail:
    print("  -", m)
sys.exit(1 if _fail else 0)
