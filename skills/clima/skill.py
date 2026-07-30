"""Minion Clima / Tiempo — meteorología real vía wttr.in (sin API key).

Separa el CLIMA («¿qué temperatura hace en Madrid?», «¿va a llover?») de la
temperatura del HARDWARE (esa la lleva la skill system_pc). Va en carpeta
'clima' para ordenarse ANTES que system_pc en el router y así atender el tiempo
primero, pero sus patrones excluyen cpu/gpu/gráfica para no pisar el hardware.
Ojo también con domótica: «hace frío/calor» solo casa como pregunta o a final
de frase, nunca dentro de «enciende el aire que hace calor».
"""
from __future__ import annotations

import re
from urllib.parse import quote

import httpx

SKILL = {
    "name": "Clima / Tiempo",
    "description": ("Meteorología real de cualquier ciudad vía wttr.in (sin API key): "
                    "temperatura, sensación, lluvia, viento y máx/mín de hoy"),
    "patterns": {
        # OJO: la lookahead negativa evita robar «temperatura de la CPU/GPU/gráfica…».
        "weather": (
            r"qu[eé]\s+(tiempo|clima)\s+(hace|va|habr|dan|dar[aá])"
            r"|c[oó]mo\s+est[aá]\s+el\s+(tiempo|clima)"
            r"|qu[eé]\s+tal\s+(est[aá]\s+)?el\s+(tiempo|clima)"
            r"|dime\s+(el\s+)?(tiempo|clima)\b"
            r"|(el\s+|del\s+)?(clima|tiempo)\s+(en|de|para)\s+[a-zñáéíóú]"
            r"|temperatura[s]?\s+(hace|va a hacer|habr[aá]|prevista|m[aá]xima|m[ií]nima)"
            r"|(qu[eé]\s+)?temperatura[s]?\s+(hay\s+)?(en|de|para)\s+"
            r"(?!la\s+cpu\b|el\s+cpu\b|la\s+gpu\b|el\s+gpu\b|la\s+tarjeta|la\s+gr[aá]fica"
            r"|el\s+procesador|los\s+n[uú]cleos|el\s+pc\b|el\s+ordenador|el\s+equipo"
            r"|el\s+sistema|los\s+componentes)"
            r"|va\s+a\s+(llover|nevar|granizar)"
            r"|\bllueve\b|\bllover[aá]\b|\blloviendo\b"
            r"|\bnieva\b|\bnevando\b|\bnevar[aá]\b"
            r"|probabilidad\s+de\s+(lluvia|nieve|precipitaci[oó]n)"
            r"|(qu[eé]\s+)?(fr[ií]o|calor)\s+(hace|va\s+a\s+hacer|har[aá])"
            r"|(?<!que )hace\s+(mucho\s+|much[ií]simo\s+)?(fr[ií]o|calor)\s*[?¿.!]*\s*$"
            r"|\b(necesito|hace\s+falta|har[aá]\s+falta|cojo|llevo|saco)\b[^.]{0,15}\bparaguas\b"
            r"|previsi[oó]n\s+(del\s+tiempo|meteo(rol[oó]gica)?)"
            r"|pron[oó]stico(\s+del\s+tiempo|\s+meteorol[oó]gico)?\b"
            r"|meteorolog[ií]a"
        ),
    },
}

# Palabras que NO forman parte del nombre de la ciudad (para recortar bien).
_STOP = re.compile(
    r"\b(hoy|ma[ñn]ana|ahora|esta\s+tarde|esta\s+noche|este\s+fin|el\s+finde|"
    r"por\s+la\s+(mañana|tarde|noche))\b.*$", re.IGNORECASE)


def _extract_city(text: str) -> str:
    """Saca la ciudad de la frase. Si no hay, '' → wttr.in usa la IP (tu zona)."""
    t = text.strip().rstrip("?.!¿ ")
    m = re.search(r"\b(?:en|de|para|sobre)\s+(.+)$", t, re.IGNORECASE)
    if not m:
        return ""
    city = _STOP.sub("", m.group(1)).strip(" ,.")
    # descarta si en realidad apuntaba a hardware (por si acaso)
    if re.search(r"\b(cpu|gpu|gr[aá]fica|procesador|pc|ordenador|equipo|sistema)\b",
                 city, re.IGNORECASE):
        return ""
    return city


async def handle(intent: str, text: str, match, ctx) -> dict:
    city = _extract_city(text)
    loc = quote(city) if city else ""
    url = f"https://wttr.in/{loc}?format=j1&lang=es"
    try:
        async with httpx.AsyncClient(timeout=10,
                                     headers={"User-Agent": "curl/8.0"}) as cli:
            r = await cli.get(url)
            r.raise_for_status()
            d = r.json()
    except Exception as exc:
        return {"reply": f"⚠ No llego a wttr.in ahora mismo ({type(exc).__name__}). "
                         "Suele ser cosa de red: di «estado de la red» para comprobarla "
                         "y repítemelo en un momento."}

    try:
        cur = d["current_condition"][0]
        area = (d.get("nearest_area") or [{}])[0]
        place = city.title() if city else \
            (area.get("areaName", [{}])[0].get("value", "tu zona"))
        desc_list = cur.get("lang_es") or cur.get("weatherDesc") or [{"value": ""}]
        desc = desc_list[0]["value"].strip().lower()
        temp = cur.get("temp_C", "?")
        feels = cur.get("FeelsLikeC", temp)
        hum = cur.get("humidity", "?")
        wind = cur.get("windspeedKmph", "?")
        # Máx/mín de hoy si están disponibles
        today = (d.get("weather") or [{}])[0]
        maxmin = ""
        if today.get("maxtempC") and today.get("mintempC"):
            maxmin = f" Hoy máxima {today['maxtempC']}°C y mínima {today['mintempC']}°C."
        tail = "" if city else " (ubicación por IP; di «tiempo en <ciudad>» para otra)."
        reply = (f"🌤 En {place}: {desc or 'tiempo actual'}, {temp}°C "
                 f"(sensación {feels}°C), humedad {hum}%, viento {wind} km/h.{maxmin}{tail}")
        return {"reply": reply}
    except Exception:
        return {"reply": "⚠ wttr.in me ha devuelto datos que no sé interpretar para esa zona. "
                         "Prueba con el nombre de una ciudad concreta: «tiempo en Sevilla»."}
