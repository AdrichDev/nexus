# -*- coding: utf-8 -*-
"""places: las respuestas dicen la verdad.

Encontrado auditando la ruta real de comandos en un contenedor:
  * sin navegador `webbrowser.open` devuelve False y la skill decía igualmente «abierto»;
  * «menos de 90 dólares» salía como «90 €»;
  * «cuánto se tarda de A a B» respondía «ruta lista» sin decir que no da la duración;
  * «hablemos de viajes a la luna» abría Google Flights.

Mocks de webbrowser: no se abre nada. Nivel M.
Ejecutar: python tests/unit/skills/places/test_places_honesty.py
"""
import asyncio
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from backend.core.aplicacion import skills_loader as sl  # noqa: E402

sl.load_skills()

_fail, _pass = [], 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


def correr(frase, abre=True):
    """Enruta como el router real y ejecuta la skill. Devuelve (skill, intent, reply, urls)."""
    r = sl.route(frase)
    if not r:
        return None, None, "", []
    skill, intent, m = r
    urls = []
    orig = webbrowser.open
    webbrowser.open = lambda url, *a, **k: (urls.append(url) or abre)
    try:
        res = asyncio.run(skill.module.handle(intent, frase, m, None))
    finally:
        webbrowser.open = orig
    return skill.folder, intent, res.get("reply", ""), urls


FRASES = ["abre google maps", "ruta de Madrid a Valencia", "cómo llego a Toledo",
          "busca vuelos a París", "busca hoteles en Roma por menos de 90 euros",
          "busca vídeos de gatos", "busca una farmacia en el mapa"]

# 1) sin navegador: no se miente
for f in FRASES:
    folder, intent, reply, urls = correr(f, abre=False)
    low = reply.lower()
    check(folder == "places", f"sin navegador: «{f}» sigue llegando a places")
    check("no pude abrir" in low, f"sin navegador: «{f}» admite que no pudo abrir el navegador")
    check(urls and urls[0] in reply, f"sin navegador: «{f}» deja el enlace en la respuesta")
    check("abierto" not in low and "abiertos" not in low and " lista " not in low,
          f"sin navegador: «{f}» no afirma que está abierto/lista")

# con navegador todo sigue igual
folder, intent, reply, urls = correr("busca vuelos a París", abre=True)
check("abiertos en Google Flights" in reply and urls, "con navegador: vuelos sigue diciendo que están abiertos")

# 2) moneda
_, _, reply, urls = correr("busca hoteles en Roma por menos de 90 dólares")
check("$" in reply and "€" not in reply, "moneda: «90 dólares» se responde en $, no en €")
check(urls and "curr=USD" in urls[0], "moneda: Google Hotels recibe curr=USD")
_, _, reply, urls = correr("busca hoteles en Roma por menos de 90 euros")
check("€" in reply and urls and "curr=EUR" in urls[0], "moneda: «90 euros» sigue en € y curr=EUR")
_, _, reply, urls = correr("hoteles en Sevilla por menos de 120")
check("€" in reply and urls and "curr=EUR" in urls[0], "moneda: sin unidad, por defecto € (como siempre)")

# 3) preguntas de tiempo
_, _, reply, urls = correr("cuánto se tarda de Madrid a Valencia")
low = reply.lower()
check("no puedo" in low and ("tiempo" in low or "duración" in low or "duracion" in low),
      "tiempo: dice que no puede calcular la duración")
check(urls, "tiempo: aun así abre la ruta en el mapa")
_, _, reply, urls = correr("cuánto se tarda de Madrid a Valencia", abre=False)
check("no puedo calcular" in reply.lower() and "no pude abrir" in reply.lower() and urls[0] in reply,
      "tiempo + sin navegador: da ambos avisos y el enlace")
_, _, reply, _u = correr("ruta de Madrid a Valencia")
check("no puedo" not in reply.lower(), "tiempo: una ruta normal no lleva ese aviso")

# 4) «viajes a» dentro de una conversación no abre vuelos
r = sl.route("hablemos de viajes a la luna")
check(not (r and r[0].folder == "places" and r[1] == "flights"), "falso positivo: «hablemos de viajes a la luna» no abre vuelos")
for f in ("viajes a Madrid", "vuelos a París", "dame viajes a Roma", "busca vuelos a Lisboa"):
    r = sl.route(f)
    check(bool(r) and r[0].folder == "places" and r[1] == "flights", f"vuelos: «{f}» sigue llegando a flights")

print("\n== 5) el navegador solo recibe URLs que construye la propia skill (T20b) ==")
# SEC-11 cerró lo que nexus PIDE; esto es lo que nexus manda ABRIR. En places el
# equipo y el esquema son LITERALES (`https://www.google.com/…`,
# `https://www.youtube.com/…`) y lo que viene del texto va por `quote_plus`
# dentro de la consulta, así que el destino no puede venir del texto. Se fija
# con una prueba en vez de confiar en la lectura: si mañana alguien pasa texto
# crudo a `_responder`, esto se pone rojo. Aquí NO se mete la guarda de destino
# a propósito: cada «abre google maps» pagaría una consulta DNS y sin conexión
# dejaría de abrirse Google Maps.
import urllib.parse as _urlparse                              # noqa: E402

_fuente = (ROOT / "skills" / "places" / "skill.py").read_text(encoding="utf-8")
check(_fuente.count("webbrowser.open(") == 1,
      "places llama a `webbrowser.open` en más de un sitio: el destino ya no lo decide un solo embudo")
check("webbrowser.open(url)" in _fuente,
      "el único `webbrowser.open` de places ya no es el de `_open(url)`")

_FLUJOS = ["abre google maps", "ruta de Madrid a Valencia", "cómo llego a Toledo",
           "llévame a Segovia", "busca vuelos a París",
           "busca hoteles en Roma por menos de 90 euros", "busca vídeos de gatos",
           "busca una farmacia en el mapa", "dónde hay un cajero",
           # el texto HOSTIL viaja dentro de la consulta y no cambia el destino
           "busca vídeos de http://127.0.0.1:8177/api/command"]
for f in _FLUJOS:
    folder, intent, reply, urls = correr(f, abre=True)
    check(folder == "places", f"«{f}» ya no llega a places")
    check(len(urls) == 1, f"«{f}» debería abrir UN enlace y abre {urls}")
    partes = _urlparse.urlsplit(urls[0]) if urls else None
    check(partes is not None and partes.scheme == "https",
          f"«{f}» abre algo que no es https: {urls}")
    check(partes is not None and partes.hostname in ("www.google.com", "www.youtube.com"),
          f"«{f}» abre un equipo que places no fija: {urls}")
_, _, _, urls = correr("abre google maps")
check(urls == ["https://www.google.com/maps"], f"«abre google maps» abre {urls}")
_, _, _, urls = correr("ruta de Madrid a Valencia")
check(urls == ["https://www.google.com/maps/dir/?api=1&origin=Madrid&destination=Valencia"
               "&travelmode=driving"],
      f"la ruta ya no es la misma URL de Google Maps: {urls}")

print(f"\nplaces honesty: {_pass} OK, {len(_fail)} FAIL")
sys.exit(1 if _fail else 0)
