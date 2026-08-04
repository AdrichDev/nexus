"""
Minion MEDIA / MÚSICA — nexus reproduce y controla música por voz o texto.

Reproducir (di «pon…», «reproduce…», «ponme…»):
  * YouTube (por defecto): busca y ABRE el primer resultado con autoplay real,
    sin API key (lee el videoId del HTML de resultados).
  * Spotify: AUTOPLAY REAL vía Web API (Premium + Client ID/Secret en ⚙).
    Sin API configurada, abre la app en la búsqueda como plan B.
  * Apple Music / iTunes: abre la búsqueda en music.apple.com (tienda española).

Aleatorio (di «pon algo», «pon música», «sorpréndeme», «pon algo al azar»,
«pon algo de rock», «pon una canción de Quevedo»):
  * El LLM elige UNA canción real (distinta cada vez; recuerda las últimas
    puestas en data/music_history.json para no repetirse). Si el LLM no está
    disponible, tira de un pool interno variado.

Controlar (funciona sobre CUALQUIER reproductor activo — Spotify, YouTube,
navegador, etc. — vía teclas multimedia de Windows):
  * «pausa» / «reanuda»            → play/pausa
  * «siguiente canción» / «salta»  → siguiente
  * «canción anterior»             → anterior
  * «para la música»               → stop

Abrir las apps (Spotify, iTunes, YouTube…) ya lo hace el minion «Sistema/PC»
con tu índice de aplicaciones; esta skill se centra en REPRODUCIR y CONTROLAR.
"""
from __future__ import annotations

import json
import random
import re
import webbrowser
from urllib.parse import quote, quote_plus

import httpx

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Detección ROBUSTA del servicio nombrado, tolerando cómo lo transcribe Whisper
# («espotifai», «yutub», «aitunes»…). Se escanea TODO el texto, no solo el final.
_SERVICES = (
    ("spotify", r"spotif\w*|espotif\w*|es\s?potif\w*|spoti\b"),
    ("apple",   r"itunes|ai\s?tunes|i\s?tunes|apple\s*mus\w*|m[uú]sica\s+de\s+apple|\bapple\b"),
    ("youtube", r"you\s?tube\w*|yutub\w*|yutu\b|\byt\b|youtu\w*"),
)

# Sufijo opcional de servicio para las regex («en spotify», «en el yutub»…)
_SVC_RX = (r"(?:\s+en\s+(?:el\s+|la\s+)?(?:spotif\w*|espotif\w*|you\s?tube\w*|"
           r"yutub\w*|yt|apple\s*mus\w*|itunes|ai\s?tunes|apple))?")


def _detect_service(text: str):
    """Devuelve 'spotify' | 'apple' | 'youtube' si se nombra alguno (con variantes)."""
    t = (text or "").lower()
    for canon, rx in _SERVICES:
        if re.search(rx, t):
            return canon
    return None

SKILL = {
    "name": "Media / Música",
    "description": ("Pon canciones por nombre o al azar con autoplay real "
                    "(YouTube sin API key, Spotify Web API, Apple Music) y controla "
                    "pausa/siguiente/anterior/stop de cualquier reproductor"),
    # Orden IMPORTANTE: controles → ALEATORIO → play con nombre. Así «pon otra
    # canción» es siguiente, «para la música» es stop, «pon algo» es aleatorio
    # y «pon Bohemian Rhapsody» sigue siendo play con nombre.
    "patterns": {
        "pause": r"\b(pausa|p[aá]usa(?:la|lo|me)?|reanuda|rean[uú]dala|dale\s+al\s+play|quita\s+la\s+pausa|dale\s+al\s+pause)\b"
                 r"|\b(pon(?:le)?|dale)\s+(la\s+)?pausa\b"
                 r"|\b(pausa|reanuda|contin[uú]a|sigue)\s+(?:con\s+)?(la\s+)?(m[uú]sica|canci[oó]n|reproducci[oó]n|el\s+v[ií]deo|spotify)\b",
        "next": r"\bsiguiente\s+(canci[oó]n|tema|pista)\b|\b(pon\s+)?otra\s+canci[oó]n\b"
                r"|\b(pasa|s[aá]lta(?:me|te)?|cambia|c[aá]mbia(?:me)?)\s+(de\s+|la\s+|esta\s+|este\s+|a\s+la\s+siguiente\s+)?(canci[oó]n|tema|pista)\b"
                r"|\bs[aá]lta(?:te|me)?\s+est[ae]\b|\bp[oó]n(?:me)?\s+la\s+siguiente\b",
        "prev": r"\b(canci[oó]n|tema|pista)\s+anterior\b|\banterior\s+(canci[oó]n|tema)\b"
                r"|\bvuelve\s+a\s+la\s+anterior\b|\bpon\s+(la\s+|el\s+)?(canci[oó]n\s+|tema\s+|pista\s+)?anterior\b"
                r"|\bcanci[oó]n\s+de\s+antes\b|\brep[ií]te(?:me)?\s+la\s+canci[oó]n\b|\bponla\s+otra\s+vez\b",
        "stop_music": r"\b(p[aá]ra|qu[ií]ta|ap[aá]ga|c[oó]rta|det[eé]n|sil[eé]ncia)(?:me|nos)?\s+(la\s+|esa\s+)?(m[uú]sica|canci[oó]n|reproducci[oó]n)\b"
                      r"|\bfuera\s+(la\s+)?m[uú]sica\b",
        # ALEATORIO: «pon algo», «pon música», «pon una canción», «sorpréndeme»,
        # «pon algo de rock al azar», «reproduce cualquier cosa en spotify»…
        # Solo casa con palabras GENÉRICAS (algo, música, una canción, cualquier
        # cosa, lo que quieras…) — nunca roba un título concreto.
        # RESPUESTA a «¿dónde la pongo?»: «spotify», «en youtube», «pues el spotify»…
        "svc_answer": r"^\s*(?:pues\s+)?(?:mejor\s+)?(?:en\s+)?(?:el\s+)?"
                      r"(?P<svcans>spotify|espotif\w*|spoti|youtube|yutub\w*|yt|"
                      r"apple\s*music|apple|itunes|ai\s?tunes)"
                      r"\s*(?:mejor|porfa|por\s+favor)?\s*[.!]*\s*$",
        "random": r"\bsorpr[eé]nde(?:me|nos)\b(?:\s+con\s+(?:m[uú]sica|una\s+canci[oó]n|algo))?"
                  r"(?:\s+de\s+(?P<rq2>.+?))?" + _SVC_RX + r"\s*$"
                  r"|\b(?:pon(?:me|nos|te)?|p[oó]n(?:me)?|reproduce(?:me)?|reprod[uú]ce(?:me)?|suena|pincha|"
                  r"quiero\s+(?:escuchar|o[ií]r))\s+"
                  r"(?:algo|m[uú]sica|una\s+canci[oó]n|un\s+tema|una\s+cancioncilla|"
                  r"una\s+cancioncita|un\s+temita|(?:una\s+)?musiqui(?:lla|ta)|"
                  r"cualquier\s+(?:cosa|canci[oó]n|tema)|"
                  r"lo\s+que\s+(?:quieras|sea|te\s+d[eé]\s+la\s+gana)|random|aleatorio)"
                  r"(?:\s+de\s+(?P<rq>.+?))?"
                  r"(?:\s+(?:al\s+azar|aleatori[oa]|random))?" + _SVC_RX +
                  r"(?:\s+(?:al\s+azar|aleatori[oa]|random))?\s*$"
                  r"|\bme\s+apetece\s+(?:escuchar\s+)?(?:algo\s+de\s+|un\s+poco\s+de\s+)?"
                  r"(?:m[uú]sica|una\s+canci[oó]n|un\s+tema)(?:\s+(?:de\s+)?(?P<rq3>.+?))?" + _SVC_RX + r"\s*$",
        # Reproducir CON NOMBRE: verbo de música + consulta (+ servicio opcional).
        # El lookahead deja fuera lo que «pon …» significa en otras skills:
        # ajustes del PC, avisos, tareas, casa. Sin él, «ponme una alarma a las 8»
        # acababa buscando una canción llamada «una alarma a las 8».
        "play": r"(?:\b(pon|ponme|p[oó]n|reproduce|reprod[uú]ce(?:me)?|suena|pincha|dale\s+a|pon\s+la\s+canci[oó]n)\b"
                r"\s+(?!.*\b(volumen|brillo|alarma|despertador|temporizador|cron[oó]metro|"
                r"recordatorio|aviso|tarea|nota|copia\s+de\s+seguridad|"
                r"web|p[aá]gina|p[aá]gina\s+web|"
                r"modo\s+\w+|tema\s+(?:oscuro|claro)|fondo\s+de\s+pantalla|wallpaper)\b)(?P<q>.+?)"
                r"(?:\s+en\s+(?P<svc>spotify|youtube|yt|apple\s*music|itunes|m[uú]sica\s+de\s+youtube))?\s*$)"
                r"|(?:\b(abre|escucha(?:r)?|quiero\s+(?:escuchar|o[ií]r)|reproduce)\s+(?:una\s+|la\s+|el\s+)?(?:canci[oó]n|tema|m[uú]sica)\s+"
                r"(?:de\s+|llamada\s+|titulada\s+)?(?P<q3>.+?)(?:\s+en\s+(?P<svc3>spotify|youtube|yt|apple\s*music|itunes))?\s*$)",
    },
}


# ---------------------------------------------------------------- utilidades
def _open_url(url: str) -> bool:
    try:
        webbrowser.open(url)
        return True
    except Exception:
        return False


def _clean_query(q: str) -> str:
    q = (q or "").strip().strip('"\'“”')
    q = re.sub(r"^(la\s+canci[oó]n|el\s+tema|la\s+m[uú]sica|m[uú]sica\s+de|algo\s+de|"
               r"una\s+de|una\s+canci[oó]n\s+de)\s+", "", q, flags=re.IGNORECASE)
    q = re.sub(r"\s+(en|por|con|desde)\s+(el\s+|la\s+)?(spotif\w*|espotif\w*|you\s?tube\w*|yutub\w*|"
               r"yt|apple\s*mus\w*|itunes|ai\s?tunes|apple)\s*$", "",
               q, flags=re.IGNORECASE)
    q = re.sub(r"\s+(al\s+azar|aleatori[oa]|random)\s*$", "", q, flags=re.IGNORECASE)
    return q.strip()


def _send_media_key(kind: str) -> bool:
    """Envía una tecla multimedia de Windows (controla el reproductor activo)."""
    vk = {"playpause": 0xB3, "next": 0xB0, "prev": 0xB1, "stop": 0xB2}.get(kind)
    if vk is None:
        return False
    try:
        import ctypes
        u = ctypes.windll.user32          # type: ignore[attr-defined]
        u.keybd_event(vk, 0, 0, 0)
        u.keybd_event(vk, 0, 2, 0)        # KEYEVENTF_KEYUP
        return True
    except Exception:
        return False


# ------------------------------------------------------------- modo aleatorio
# Pool de respaldo si el LLM no está disponible (variado a propósito)
_FALLBACK_POOL = [
    "Queen - Don't Stop Me Now", "Extremoduro - So Payaso", "Quevedo - Columbia",
    "Estopa - Vino Tinto", "AC/DC - Thunderstruck", "Rosalía - Despechá",
    "Fito y Fitipaldis - Soldadito Marinero", "Dire Straits - Sultans of Swing",
    "Bad Bunny - Tití Me Preguntó", "Michael Jackson - Billie Jean",
    "El Canto del Loco - Zapatillas", "Nirvana - Smells Like Teen Spirit",
    "Manuel Carrasco - Uno X Uno", "Daft Punk - Get Lucky",
    "La Oreja de Van Gogh - Rosas", "Coldplay - Viva La Vida",
    "Melendi - Lágrimas Desordenadas", "Red Hot Chili Peppers - Californication",
    "Aitana - Formentera", "The Weeknd - Blinding Lights",
    "Joaquín Sabina - 19 Días y 500 Noches", "Guns N' Roses - Sweet Child O' Mine",
    "C. Tangana - Tú Me Dejaste De Querer", "Eminem - Lose Yourself",
    "Héroes del Silencio - Entre Dos Tierras", "Dua Lipa - Levitating",
    "Camilo Sesto - Vivir Así Es Morir de Amor", "Linkin Park - In the End",
    "Morat - Cómo Te Atreves", "Bruno Mars - Uptown Funk",
]

_HISTORY_MAX = 40


def _hist_file():
    from backend.core.comun.config import DATA_DIR
    return DATA_DIR / "music_history.json"


def _hist_load() -> list:
    try:
        return json.loads(_hist_file().read_text(encoding="utf-8"))
    except Exception:
        return []


def _hist_add(song: str) -> None:
    try:
        h = [s for s in _hist_load() if s.lower() != song.lower()]
        h.append(song)
        f = _hist_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(h[-_HISTORY_MAX:], ensure_ascii=False, indent=1),
                     encoding="utf-8")
    except Exception:
        pass


async def _pick_random_song(ctx, seed: str = "") -> str:
    """El LLM elige UNA canción real (formato «Artista - Canción»).
    `seed` es el filtro opcional: género, artista, década, mood…
    Si el LLM no está disponible o falla, tira del pool interno."""
    recent = _hist_load()
    try:
        from backend.core.llm import get_provider_safe
        prov = await get_provider_safe()
        if prov is not None and prov.name != "mock":
            vibe = seed or random.choice(
                ["rock clásico", "pop español", "éxitos actuales", "rock español",
                 "reggaeton", "música de los 80", "música de los 90", "indie",
                 "electrónica", "baladas", "funk", "himnos de estadio", "pop internacional"])
            sys_msg = ("Eres el DJ de nexus. Elige UNA canción REAL y conocida"
                       + (f" de: {seed}." if seed else f". Estilo sugerido para variar: {vibe}.")
                       + " Responde SOLO con el formato exacto «Artista - Título», sin"
                         " comillas ni nada más. Debe existir de verdad (nada inventado)."
                       + ("\nNO repitas ninguna de estas (puestas hace poco):\n- "
                          + "\n- ".join(recent[-20:]) if recent else ""))
            out = await prov.chat([{"role": "system", "content": sys_msg},
                                   {"role": "user", "content": "Dame la canción."}])
            line = (out or "").strip().splitlines()[0].strip().strip('"\'«»*')
            # saneo: ni vacío, ni parrafada, ni repetida
            if line and len(line) <= 80 and line.lower() not in (r.lower() for r in recent):
                return line
    except Exception:
        pass
    pool = [s for s in _FALLBACK_POOL if s.lower() not in (r.lower() for r in recent)]
    if seed:
        seeded = [s for s in pool if seed.lower() in s.lower()]
        pool = seeded or pool
    return random.choice(pool or _FALLBACK_POOL)


# ----------------------------------------------------------------- reproducir
async def _youtube_play(query: str, ctx) -> str:
    search = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True,
                                     headers={"User-Agent": _UA,
                                              "Accept-Language": "es-ES,es;q=0.9"}) as cli:
            r = await cli.get(search)
        m = re.search(r'"videoId":"([A-Za-z0-9_-]{11})"', r.text)
        if m:
            _open_url(f"https://www.youtube.com/watch?v={m.group(1)}")
            return f"Reproduciendo «{query}» en YouTube ▶"
    except Exception as exc:                                   # noqa: BLE001
        await ctx["bus"].emit("log", {"level": "warn", "msg": f"YouTube: {exc}"})
    _open_url(search)
    return f"Abrí YouTube buscando «{query}» (dale al primer resultado)."


async def _spotify_play(query: str, ctx) -> str:
    """Spotify con AUTOPLAY REAL vía Web API (si está configurada en ⚙)."""
    from backend.core import spotify
    if spotify.is_configured() and spotify.is_authorized():
        try:
            ok, detail = await spotify.play_query(query)
            if ok:
                return f"Sonando en Spotify: {detail} ▶"
            await ctx["bus"].emit("log", {"level": "warn", "msg": f"Spotify API: {detail}"})
            spotify.open_search_fallback(query)
            return (f"No he podido darle al play solo ({detail}); te he abierto "
                    f"Spotify en «{query}» para que lo lances tú.")
        except Exception as exc:                               # noqa: BLE001
            await ctx["bus"].emit("log", {"level": "warn", "msg": f"Spotify API: {exc}"})
            spotify.open_search_fallback(query)
            return f"La API de Spotify ha fallado; te he abierto la búsqueda de «{query}»."
    if spotify.is_configured() and not spotify.is_authorized():
        _open_url(spotify.auth_url())
        return ("Falta un paso: he abierto el navegador para que AUTORICES a nexus "
                "en tu Spotify (solo esta primera vez). Cuando lo aceptes, vuelve a "
                "pedirme la canción y sonará sola.")
    # Sin API configurada → plan B clásico
    spotify.open_search_fallback(query)
    return (f"Abrí Spotify en «{query}» — pulsa play sobre el primer resultado. "
            "💡 Si me pones el Client ID/Secret de Spotify en ⚙ (cuenta Premium), "
            "la reproduzco yo solo.")


def _apple_play(query: str) -> str:
    _open_url("https://music.apple.com/es/search?term=" + quote(query))
    return f"Abrí Apple Music buscando «{query}» (dale a reproducir)."


async def _play(ctx, raw_q: str, svc: str | None) -> str:
    q = _clean_query(raw_q)
    if not q:
        return "¿Qué canción pongo? Dime «pon <canción> de <artista>»."
    svc = (svc or ctx["settings"].get("music_service", "youtube") or "youtube")
    svc = svc.lower().replace(" ", "")
    if "spoti" in svc or "espotif" in svc:
        return await _spotify_play(q, ctx)
    if "apple" in svc or "itunes" in svc or "aitunes" in svc:
        return _apple_play(q)
    return await _youtube_play(q, ctx)          # youtube / yt / por defecto


# -------------------------------------------------------------------- router
# PETICIÓN PENDIENTE de servicio: Adri pide música SIN decir dónde → se le
# PREGUNTA (Spotify o YouTube) y su siguiente respuesta corta la resuelve.
_PENDING_SVC = {"ts": 0.0, "intent": "", "q": "", "seed": ""}


def _ask_service(intent: str, q: str = "", seed: str = "") -> dict:
    import time as _t
    _PENDING_SVC.update(ts=_t.monotonic(), intent=intent, q=q, seed=seed)
    que = f"«{q}»" if q else ("algo de " + seed if seed else "la música")
    return {"reply": f"🎵 ¿Dónde pongo {que}: Spotify o YouTube?", "speak": True}


async def handle(intent: str, text: str, match, ctx) -> dict:
    import time as _t
    try:
        if intent == "svc_answer":
            svc = _detect_service(text) or "spotify"
            if not _PENDING_SVC["intent"] or _t.monotonic() - _PENDING_SVC["ts"] > 120:
                return {"reply": "¿El qué? Pídeme una canción o música y te pregunto dónde ponerla."}
            pend = dict(_PENDING_SVC)
            _PENDING_SVC["intent"] = ""
            if pend["intent"] == "random":
                song = await _pick_random_song(ctx, pend["seed"])
                _hist_add(song)
                reply = await _play(ctx, song, svc)
                return {"reply": reply + " 🎲", "speak": True}
            return {"reply": await _play(ctx, pend["q"], svc), "speak": True}
        if intent == "random":
            gd = match.groupdict() if match else {}
            seed = _clean_query(gd.get("rq") or gd.get("rq2") or gd.get("rq3") or "")
            svc = _detect_service(text)
            if not svc:
                return _ask_service("random", seed=seed)   # SIN servicio → PREGUNTAR
            song = await _pick_random_song(ctx, seed)
            _hist_add(song)
            reply = await _play(ctx, song, svc)
            return {"reply": reply + f" 🎲 (al azar{' de ' + seed if seed else ''})",
                    "speak": True}
        if intent == "play":
            gd = match.groupdict() if match else {}
            q = gd.get("q") or gd.get("q3") or ""
            svc = gd.get("svc") or gd.get("svc3") or _detect_service(text)
            if not svc:
                return _ask_service("play", q=q)           # SIN servicio → PREGUNTAR
            return {"reply": await _play(ctx, q, svc), "speak": True}
        _no_keys = ("Las teclas multimedia solo existen en Windows y aquí no las tengo. "
                    "Puedo seguir poniendo música: di «pon <canción> en youtube» y la lanzo.")
        if intent == "pause":
            ok = _send_media_key("playpause")
            return {"reply": "Play/Pausa ⏯" if ok else "⚠ " + _no_keys}
        if intent == "next":
            ok = _send_media_key("next")
            return {"reply": "Siguiente canción ⏭" if ok else "⚠ " + _no_keys}
        if intent == "prev":
            ok = _send_media_key("prev")
            return {"reply": "Canción anterior ⏮" if ok else "⚠ " + _no_keys}
        if intent == "stop_music":
            ok = _send_media_key("stop")
            return {"reply": "Música detenida ⏹. Cuando quieras más, di «pon algo» y elijo yo."
                    if ok else "⚠ " + _no_keys}
    except Exception as exc:                                   # noqa: BLE001
        return {"reply": f"✖ El minion de música ha fallado: {type(exc).__name__}: {exc}. "
                         "Repítemelo; si persiste, mira el log del HUD.", "error": True}
    return {"reply": "🎵 Esa orden de música no la tengo. Prueba «pon <canción> en spotify», "
                     "«pon algo de rock» o «siguiente canción»."}
