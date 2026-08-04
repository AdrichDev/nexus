"""Minion VIGILANCIAS — comprueba webs, precios y noticias en segundo plano.

Cada vigilancia se guarda numerada en data/watchers.json y el scheduler la
revisa cada _CHECK_MIN minutos:
  * web      → avisa si CAMBIA el contenido (huella del texto + líneas nuevas).
  * precio   → extrae el precio de la página y avisa si BAJA (si sube, lo dice).
  * noticias → titulares nuevos del tema (Google News vía websearch).
Cuando algo salta, aviso por HUD (notificación + log + chat) y por Telegram.

La lectura de páginas y la búsqueda pasan por el motor central
(backend/core/websearch.py): una sola caché y un solo juego de fuentes.
"""
from __future__ import annotations

import json
import re
import time

SKILL = {
    "name": "Vigilancias",
    "description": "Vigila webs (cambios), precios (bajadas) y noticias de un tema; avisa por HUD y Telegram cuando algo salta",
    "patterns": {
        # listar / borrar (específicos) antes que las altas (amplias)
        "list": r"(?:qu[eé]|cu[aá]les|cu[aá]ntas)\s+vigilancias|(?:ver|mu[eé]strame|lista(?:me)?)\s+"
                r"(?:las\s+|mis\s+)?vigilancias|\bmis\s+vigilancias\b|qu[eé]\s+est[aá]s\s+vigilando",
        "remove": r"(?:deja|para)\s+de\s+vigilar\s+(?P<which>.+)"
                  r"|(?:borra|elimina|quita)\s+la\s+vigilancia\s+#?(?P<num>\d+)",
        # «baja/baje» ya implica precio; «cambia/cambie» exige la palabra
        # «precio» o sería una vigilancia de contenido (intent web).
        "price": r"av[ií]sa(?:me)?\s+(?:si|cuando)\s+(?:baja|baje)\s+"
                 r"(?:de\s+precio\s+|el\s+precio\s+(?:de\s+)?)?(?P<url>https?://\S+)"
                 r"|av[ií]sa(?:me)?\s+(?:si|cuando)\s+(?:cambia|cambie)\s+"
                 r"(?:de\s+precio\s+|el\s+precio\s+(?:de\s+)?)(?P<url3>https?://\S+)"
                 r"|vigila\s+el\s+precio\s+de\s+(?P<url2>https?://\S+)",
        "news": r"av[ií]sa(?:me)?\s+cuando\s+(?:haya|salgan?)\s+(?:noticias?|novedades)\s+"
                r"(?:de|sobre)\s+(?P<topic>.+)"
                r"|vigila\s+las\s+noticias\s+(?:de|sobre)\s+(?P<topic2>.+)",
        "web": r"vigila(?:me)?\s+(?:la\s+(?:web|p[aá]gina)\s+|esta\s+(?:web|p[aá]gina)\s+)?(?P<url>https?://\S+)"
               r"|av[ií]sa(?:me)?\s+si\s+cambia\s+(?:la\s+(?:web|p[aá]gina)\s+)?(?P<url2>https?://\S+)",
    },
}

_CHECK_MIN = 10          # minutos entre comprobaciones de cada vigilancia


def _file():
    from backend.core.comun.config import DATA_DIR
    return DATA_DIR / "watchers.json"


def _load() -> list:
    try:
        d = json.loads(_file().read_text(encoding="utf-8"))
        return d if isinstance(d, list) else []
    except Exception:
        return []


def _save(items: list) -> None:
    f = _file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


def _add(tipo: str, objetivo: str) -> dict:
    items = _load()
    num = max((int(w.get("num") or 0) for w in items), default=0) + 1
    w = {"num": num, "tipo": tipo, "objetivo": objetivo.strip(),
         "estado": {}, "creado": time.time(), "ultima": 0.0}
    items.append(w)
    _save(items)
    return w


# ─────────────────────────── detectores (puros, testeables) ───────────────────────────

# Número con posible separador de MILES («1.234,56», «12 345,00») o simple («99», «45.50»)
_NUM = r"\d{1,3}(?:[. ]\d{3})+(?:,\d{1,2})?|\d{1,6}(?:[.,]\d{1,2})?"
_PRICE_RX = re.compile(
    rf"(?:€\s*({_NUM})|({_NUM})\s*(?:€|eur(?:os?)?\b)|"
    rf"\$\s*({_NUM})|({_NUM})\s*(?:usd|d[oó]lares)\b)",
    re.IGNORECASE)


def _to_float(raw: str) -> float | None:
    """«1.234,56»→1234.56 · «12 345»→12345 · «45.50»→45.5 · «99»→99."""
    raw = raw.strip().replace(" ", "")
    if "," in raw:                       # coma = decimales (formato ES) → puntos son miles
        raw = raw.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", raw):   # solo puntos de miles
        raw = raw.replace(".", "")
    try:
        return float(raw)
    except ValueError:
        return None


def extract_price(text: str) -> float | None:
    """Primer precio plausible del texto («1.234,56 €», «€99», «120 euros»…).
    Devuelve None si no hay ninguno."""
    for m in _PRICE_RX.finditer(text or ""):
        raw = next(g for g in m.groups() if g)
        v = _to_float(raw)
        if v is not None and 0 < v < 1_000_000:
            return v
    return None


def text_digest(text: str) -> str:
    """Huella del contenido (para detectar cambios sin guardar la página entera)."""
    import hashlib
    norm = re.sub(r"\s+", " ", (text or "").strip().lower())
    return hashlib.sha256(norm.encode()).hexdigest()[:16]


def diff_lines(old: str, new: str, n: int = 3) -> list[str]:
    """Líneas que aparecen en 'new' y no estaban en 'old' (resumen del cambio)."""
    old_set = {line.strip() for line in (old or "").splitlines() if line.strip()}
    fresh = [line.strip() for line in (new or "").splitlines()
             if line.strip() and line.strip() not in old_set and len(line.strip()) > 15]
    return fresh[:n]


# ─────────────────────────── comprobación periódica ───────────────────────────

async def _notify(msg: str) -> None:
    from backend.core.comun.events import bus
    await bus.emit("notification", {"title": "👁 Vigilancia", "body": msg[:200]})
    await bus.emit("log", {"level": "alert", "msg": "👁 " + msg})
    await bus.emit("chat", {"user": "[vigilancia]", "reply": "👁 " + msg,
                            "provider": "nexus", "skill": "vigilancias", "channel": "pc"})
    try:
        from backend.core.infraestructura.telegram_bridge import send_telegram
        await send_telegram("👁 " + msg)
    except Exception:
        pass


async def _check_one(w: dict) -> str | None:
    """Comprueba UNA vigilancia. Devuelve el aviso si algo saltó, o None."""
    from backend.core.infraestructura import websearch
    est = w.setdefault("estado", {})
    if w["tipo"] == "web":
        text = await websearch.fetch_page(w["objetivo"], max_chars=6000)
        if not text:
            return None
        dig = text_digest(text)
        prev_dig, prev_text = est.get("digest"), est.get("texto", "")
        est["digest"], est["texto"] = dig, text[:3000]   # diff basta; JSON ligero
        if prev_dig and dig != prev_dig:
            cambios = diff_lines(prev_text, text)
            detalle = (" Novedades: " + " | ".join(cambios)) if cambios else ""
            return f"La web de la vigilancia #{w['num']} ha cambiado ({w['objetivo'][:60]}).{detalle}"
        return None
    if w["tipo"] == "precio":
        text = await websearch.fetch_page(w["objetivo"], max_chars=6000)
        price = extract_price(text)
        if price is None:
            return None
        prev = est.get("precio")
        est["precio"] = price
        if prev is not None and price < prev:
            return (f"¡PRECIO A LA BAJA! Vigilancia #{w['num']}: de {prev:.2f} a "
                    f"{price:.2f} ({w['objetivo'][:60]}).")
        if prev is not None and price > prev:
            return (f"Precio al alza en la vigilancia #{w['num']}: de {prev:.2f} a "
                    f"{price:.2f} ({w['objetivo'][:60]}).")
        return None
    if w["tipo"] == "noticias":
        res = await websearch.search(f"noticias {w['objetivo']} hoy", 5)
        titles = [r["title"] for r in res if r.get("title")]
        vistos = est.get("vistos", [])
        seen = set(vistos)
        nuevos = [t for t in titles if t not in seen]
        # Lista, no set: el recorte a 60 tira siempre los titulares más viejos.
        est["vistos"] = (vistos + nuevos)[-60:]
        if seen and nuevos:          # la primera pasada solo siembra, no avisa
            return (f"Noticias nuevas de «{w['objetivo']}» (vigilancia #{w['num']}): "
                    + " | ".join(n[:80] for n in nuevos[:3]))
        return None
    return None


async def check_watchers(force: bool = False) -> int:
    """Recorre las vigilancias que toquen (cada {_CHECK_MIN} min) y avisa de lo
    que salte. La llama el scheduler; devuelve cuántos avisos mandó."""
    items = _load()
    if not items:
        return 0
    now = time.time()
    fired = 0
    changed = False
    for w in items:
        if not force and (now - w.get("ultima", 0)) < _CHECK_MIN * 60:
            continue
        try:
            msg = await _check_one(w)
            w["ultima"] = now
            changed = True
            if msg:
                await _notify(msg)
                fired += 1
        except Exception:
            w["ultima"] = now
            changed = True
    if changed:
        _save(items)
    return fired


# ─────────────────────────────────── handler ───────────────────────────────────

_TIPO_ICON = {"web": "🌐", "precio": "💶", "noticias": "📰"}


async def handle(intent: str, text: str, match, ctx) -> dict:
    gd = match.groupdict() if match else {}

    if intent == "web":
        url = (gd.get("url") or gd.get("url2") or "").strip().rstrip(".,)")
        w = _add("web", url)
        return {"reply": f"👁 Vigilancia #{w['num']} activada: cambios en {url}. "
                         f"La compruebo cada ~{_CHECK_MIN} min y te aviso por HUD y "
                         "Telegram si algo se mueve. «mis vigilancias» para verlas."}

    if intent == "price":
        url = (gd.get("url") or gd.get("url2") or gd.get("url3") or "").strip().rstrip(".,)")
        w = _add("precio", url)
        return {"reply": f"👁 Vigilancia #{w['num']} activada: precio de {url}. "
                         "Te aviso en cuanto BAJE (y si sube, también te lo digo). "
                         f"Chequeo cada ~{_CHECK_MIN} min."}

    if intent == "news":
        topic = (gd.get("topic") or gd.get("topic2") or "").strip(" .?!")
        w = _add("noticias", topic)
        return {"reply": f"👁 Vigilancia #{w['num']} activada: noticias de «{topic}». "
                         "En cuanto salga un titular nuevo, te lo canto."}

    if intent == "list":
        items = _load()
        if not items:
            return {"reply": "👁 No estoy vigilando nada. Dame trabajo: «vigila la web "
                             "https://…», «avísame si baja el precio de https://…» o "
                             "«avísame cuando haya noticias de X»."}
        lines = []
        for w in items:
            ic = _TIPO_ICON.get(w["tipo"], "•")
            est = w.get("estado") or {}
            if not w.get("ultima"):
                extra = " (aún sin comprobar)"
            elif w["tipo"] == "precio":
                # Si la página no lleva un precio legible NUNCA saltará el aviso:
                # se dice aquí en vez de dejar al operador esperando.
                extra = (f" (último: {est['precio']:.2f})" if est.get("precio") is not None
                         else " (⚠ no encuentro un precio en esa página: no podré avisarte)")
            elif w["tipo"] == "noticias":
                extra = f" ({len(est.get('vistos') or [])} titulares vistos)"
            else:
                extra = " (contenido registrado)" if est.get("digest") else \
                        " (⚠ no consigo leer esa página)"
            lines.append(f"  {ic} #{w['num']} {w['tipo']}: {w['objetivo'][:70]}{extra}")
        return {"reply": f"👁 Vigilando {len(items)} cosa(s):\n" + "\n".join(lines) +
                         "\nDi «borra la vigilancia N» para quitar una."}

    if intent == "remove":
        items = _load()
        which = (gd.get("which") or "").strip(" .?!")
        num = gd.get("num")
        target = None
        if num:
            target = next((w for w in items if w.get("num") == int(num)), None)
        elif which:
            m = re.search(r"#?(\d+)$", which)
            if m:
                target = next((w for w in items if w.get("num") == int(m.group(1))), None)
            if not target:
                target = next((w for w in items if which.lower() in w["objetivo"].lower()), None)
        if not target:
            return {"reply": f"👁 No encuentro esa vigilancia. «mis vigilancias» te "
                             "enseña la lista con sus números."}
        items.remove(target)
        _save(items)
        return {"reply": f"👁 Vigilancia #{target['num']} ({target['tipo']}: "
                         f"{target['objetivo'][:50]}) eliminada."}

    return {"reply": "Orden de vigilancia no reconocida. Prueba «vigila la web https://…» "
                     "o «mis vigilancias»."}
