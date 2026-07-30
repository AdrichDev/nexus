"""
Minion MAPAS / VIAJES — Google Maps, rutas y búsquedas de viaje.

Todo abriendo la URL correcta en el navegador (fiable, sin API key):
  * «abre google maps»                          → Maps
  * «cómo llego a X» / «ruta de A a B»          → Maps con la ruta lista
  * «llévame a X» / «cuánto se tarda de A a B»  → Maps con la ruta lista
  * «busca X en el mapa» / «dónde hay Y»        → Maps buscando el sitio
  * «farmacias cerca de mí»                     → Maps buscando cerca
  * «busca vuelos a París» / «billetes de avión a Roma» → Google Flights
  * «busca hoteles en Roma por menos de 90 €»   → Google Hotels (con precio)
  * «busca vídeos de X»                         → YouTube (resultados)
"""
from __future__ import annotations

import webbrowser
from urllib.parse import quote_plus

SKILL = {
    "name": "Mapas / Viajes",
    "description": ("Rutas y sitios en Google Maps, vuelos en Google Flights, hoteles "
                    "con tope de precio y vídeos de YouTube, todo desde el navegador"),
    # Orden: lo específico (vuelos/hoteles/vídeos) antes que rutas/mapa genérico.
    "patterns": {
        "flights": r"\b(busca|b[uú]scame|encuentra|mira|m[ií]rame|quiero|necesito|planea|planifica|comp[aá]rame)\b[^.]{0,15}\b(vuelos?|viajes?)\b\s+(a|para|hacia|hasta)\s+(?P<dest>.+)"
                   r"|\b(vuelos?|viajes?)\s+(a|para|hacia)\s+(?P<dest2>.+)"
                   r"|\bbilletes?\s+de\s+avi[oó]n\s+(a|para|hacia|hasta)\s+(?P<dest3>.+)",
        "hotels": r"\b(?:hoteles?|alojamientos?|un\s+hotel)\b\s+(en|de|para|cerca\s+de)\s+(?P<place>.+?)"
                  r"(?:\s+(?:por\s+menos\s+de|por\s+debajo\s+de|a\s+menos\s+de|menos\s+de|hasta|bajo|m[aá]x(?:imo)?|por|de)\s+(?P<price>\d+)\s*(?:€|euros?|d[oó]lares?|usd|eur)?)?\s*$",
        "videos": r"\b(busca|b[uú]scame|encuentra|mira|ens[eé][ñn]ame|ponme|quiero\s+ver)\b[^.]{0,12}\bv[ií]deos?\b\s+(de|sobre|acerca\s+de)\s+(?P<q>.+)",
        "route_ab": r"\b(?:ruta|camino|trayecto|c[oó]mo\s+(?:llego|voy|ir|llegar)|cu[aá]nto\s+(?:se\s+)?tarda(?:r[ií]a)?)\b[^.]{0,20}?\b(?:de|desde)\s+(?P<from>.+?)\s+(?:a|hasta|hacia)\s+(?P<to>.+)",
        "route_to": r"\b(?:prepara|programa|calcula|calc[uú]lame|planifica|planea|dame|quiero|hazme)\b[^.]{0,15}?\bruta\b[^.]{0,10}?\b(?:a|hasta|hacia|para)\s+(?P<dest>.+)"
                    r"|\bc[oó]mo\s+(?:llego|voy|ir|llegar|se\s+va|se\s+llega)\s+(?:a|hasta)\s+(?P<dest2>.+)"
                    r"|\bruta\s+(?:a|hasta|hacia)\s+(?P<dest3>.+)"
                    r"|\bll[eé]vame\s+(?:a|hasta|hacia)\s+(?P<dest4>.+)",
        "place_search": r"\b(?:busca|b[uú]scame|encuentra|localiza|ens[eé][ñn]ame)\s+(?P<q>.+?)\s+en\s+(?:el\s+)?(?:mapa|google\s+maps|maps)\b"
                        r"|\bd[oó]nde\s+(?:hay|est[aá]n?|queda|cae|puedo\s+encontrar)\s+(?P<q2>.+)"
                        r"|\b(?P<q3>[\wñáéíóú][\wñáéíóú ]{2,40}?)\s+cerca\s+de\s+m[ií]\b",
        "maps_open": r"\babre\b\s+(?:google\s+)?maps\b|\babre\b\s+(?:el\s+)?mapa\b"
                     r"|\bens[eé][ñn]ame\s+el\s+mapa\b",
    },
}


def _clean(s: str) -> str:
    return (s or "").strip().strip('"\'“”.?!').strip()


def _open(url: str) -> bool:
    try:
        webbrowser.open(url)
        return True
    except Exception:
        return False


async def handle(intent: str, text: str, match, ctx) -> dict:
    gd = match.groupdict() if match else {}
    try:
        if intent == "flights":
            dest = _clean(gd.get("dest") or gd.get("dest2") or gd.get("dest3") or "")
            _open(f"https://www.google.com/travel/flights?q={quote_plus('vuelos a ' + dest)}&curr=EUR&hl=es")
            return {"reply": f"✈ Vuelos a {dest} abiertos en Google Flights, ordénalos por precio ahí. "
                             f"Si también quieres cama, di «busca hoteles en {dest}»."}

        if intent == "hotels":
            place = _clean(gd.get("place") or "")
            price = gd.get("price")
            q = f"hoteles en {place}" + (f" por menos de {price} euros" if price else "")
            _open(f"https://www.google.com/travel/search?q={quote_plus(q)}&curr=EUR&hl=es")
            extra = f" por menos de {price} €" if price else ""
            return {"reply": f"🏨 Hoteles en {place}{extra} abiertos en Google Hotels. "
                             "El filtro de precio va en la búsqueda; afínalo en la página si quieres hilar fino."}

        if intent == "videos":
            q = _clean(gd.get("q") or "")
            _open(f"https://www.youtube.com/results?search_query={quote_plus(q)}")
            return {"reply": f"🎬 Vídeos de «{q}» abiertos en YouTube. Elige uno en la página."}

        if intent == "route_ab":
            frm, to = _clean(gd.get("from")), _clean(gd.get("to"))
            _open(f"https://www.google.com/maps/dir/?api=1&origin={quote_plus(frm)}"
                  f"&destination={quote_plus(to)}&travelmode=driving")
            return {"reply": f"🗺 Ruta de {frm} a {to} lista en Google Maps, en coche por defecto "
                             "(cámbialo a pie o transporte en la página)."}

        if intent == "route_to":
            dest = _clean(gd.get("dest") or gd.get("dest2") or gd.get("dest3") or gd.get("dest4") or "")
            _open(f"https://www.google.com/maps/dir/?api=1&destination={quote_plus(dest)}&travelmode=driving")
            return {"reply": f"🗺 Ruta a {dest} lista en Google Maps desde tu ubicación actual. "
                             "Si el origen es otro, di «ruta de <origen> a <destino>»."}

        if intent == "place_search":
            q = _clean(gd.get("q") or gd.get("q2") or gd.get("q3") or "")
            _open(f"https://www.google.com/maps/search/?api=1&query={quote_plus(q)}")
            return {"reply": f"📍 Buscando «{q}» en el mapa. Cuando elijas uno, "
                             "di «cómo llego a <sitio>» y te preparo la ruta."}

        if intent == "maps_open":
            _open("https://www.google.com/maps")
            return {"reply": "🗺 Google Maps abierto. Di «cómo llego a <sitio>» o "
                             "«busca <algo> en el mapa» y sigo yo."}
    except Exception as exc:                                   # noqa: BLE001
        return {"reply": f"✖ El minion de mapas/viajes ha fallado: {type(exc).__name__}: {exc}. "
                         "Repítemelo; si persiste, comprueba que hay un navegador por defecto.",
                "error": True}
    return {"reply": "No he pillado esa orden de mapas/viajes. Prueba «ruta a <sitio>», "
                     "«busca vuelos a <ciudad>» o «hoteles en <ciudad>»."}
