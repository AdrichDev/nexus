"""
Minion JUEGOS / STEAM — abrir, instalar, descargar, actualizar y lanzar juegos.

Resuelve el AppID de Steam por NOMBRE (búsqueda en la tienda de Steam, sin API
key) y usa los esquemas steam:// para actuar de verdad:
  * jugar/lanzar : «juega a Elden Ring», «abre el juego Battlefield»  → steam://run/<id>
  * instalar     : «instala Rust en steam», «descárgate Hades»         → steam://install/<id>
  * actualizar   : «actualiza el juego X», «valida X en steam»          → steam://validate/<id>
  * launchers    : «abre steam / epic / gog / battle.net / ea app»

«abre battlefield» a secas lo maneja el minion Sistema (abre app normal y, si no
la encuentra, la lanza por Steam). Este minion cubre las órdenes explícitas de juego.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.parse
import urllib.request
import webbrowser

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

SKILL = {
    "name": "Juegos / Steam",
    "description": "Juega, instala, descarga y valida juegos por nombre en Steam (sin API key) y abre launchers (Epic, GOG, Battle.net…)",
    "patterns": {
        "launcher": r"\b(?:[aá]bre(?:me)?|arranca(?:me)?|l[aá]nza(?:me)?|inicia(?:me)?)\b\s+(?:el\s+|la\s+)?"
                    r"(?P<l>steam|epic(?:\s+games)?|gog(?:\s+galaxy)?|battle\.?net|"
                    r"ea\s+app|origin|uplay|ubisoft\s+connect|xbox|game\s*pass)\b",
        "install": r"\b(inst[aá]la(?:me)?|instalar|desc[aá]rga(?:te|me)?|b[aá]ja(?:te|me)?)\b\s+(el\s+juego\s+)?"
                   r"(?P<g>.+?)\s+(en|de|desde)\s+steam\b"
                   r"|\ben\s+steam\s+(inst[aá]la(?:me)?|desc[aá]rga(?:me|te)?|b[aá]ja(?:me|te)?)\s+(?P<g2>.+)",
        "update": r"\b(actual[ií]za(?:me)?|actualizar|val[ií]da(?:me)?|validar|ver[ií]fica(?:me)?|rep[aá]ra(?:me)?|comprueba(?:me)?)\s+(el\s+juego\s+)(?P<g>.+)"
                  r"|\b(actual[ií]za(?:me)?|val[ií]da(?:me)?|ver[ií]fica(?:me)?|rep[aá]ra(?:me)?|comprueba(?:me)?)\s+(?P<g2>.+?)\s+en\s+steam\b",
        "play": r"\b(juega(?:me)?\s+a[l]?|juguemos\s+a[l]?|[aá]bre(?:me)?\s+el\s+juego|l[aá]nza(?:me)?\s+el\s+juego|"
                r"inicia\s+el\s+juego|arranca\s+el\s+juego|p[oó]n(?:me)?\s+(?:a\s+jugar\s+a|el\s+juego)|"
                r"quiero\s+jugar\s+a[l]?|echamos?\s+una\s+partida\s+a|[eé]chate\s+una\s+partida\s+a)\s+(?P<g>.+)",
    },
}


# --------------------------------------------------------------- Steam helpers
def _steam_appid(name: str):
    """Devuelve (appid, nombre_real) buscando en la tienda de Steam. (None, None) si nada."""
    q = urllib.parse.quote(name)
    url = f"https://store.steampowered.com/api/storesearch/?term={q}&l=spanish&cc=ES"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=6) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
        items = data.get("items", []) or []
        if not items:
            return None, None
        low = name.lower()
        for it in items:                       # prioriza un nombre que encaje
            nm = str(it.get("name", "")).lower()
            if low in nm or any(len(w) > 2 and w in nm for w in low.split()):
                return it.get("id"), it.get("name")
        return items[0].get("id"), items[0].get("name")
    except Exception:
        return None, None


def _steam_do(action: str, appid) -> bool:
    """action: run | install | validate."""
    if sys.platform != "win32":
        return False
    try:
        os.system(f'start "" steam://{action}/{appid}')
        return True
    except Exception:
        return False


LAUNCHER_URI = {
    "steam": "steam://open/main",
    "epic": "com.epicgames.launcher://",
    "epic games": "com.epicgames.launcher://",
    "battle.net": "battlenet://", "battlenet": "battlenet://",
}


async def _open_launcher(ctx, name: str) -> str:
    key = name.lower().strip()
    uri = LAUNCHER_URI.get(key)
    if uri and sys.platform == "win32":
        try:
            os.startfile(uri)                  # type: ignore[attr-defined]
            return f"Abriendo {name.title()}."
        except Exception:
            pass
    # Plan B: índice de aplicaciones instaladas de nexus
    try:
        from backend.core.infraestructura.app_index import build_index, find_app, get_index, launch
        if not get_index() and sys.platform == "win32":
            await asyncio.to_thread(build_index)
        hit = find_app(name)
        if hit:
            launch(hit[1])
            return f"Abriendo {hit[0].title()}."
    except Exception:
        pass
    return (f"No encuentro «{name}» instalado en este PC. Si es un launcher que sí tienes, "
            "dímelo por su nombre exacto; si es un juego, prueba «juega a {name}» y lo busco en Steam.".replace("{name}", name))


async def _resolve_and_do(ctx, name: str, action: str, verbo: str) -> str:
    name = name.strip().rstrip(".?!").strip()
    appid, real = await asyncio.to_thread(_steam_appid, name)
    if appid and _steam_do(action, appid):
        return f"{verbo} «{real or name}» en Steam (appid {appid}). Confirma en la ventana de Steam si te lo pide."
    if appid and sys.platform != "win32":
        return f"Encontré «{real}» (appid {appid}) pero el control de Steam solo va en Windows."
    if appid:      # en Windows: el esquema steam:// no ha arrancado
        return (f"Encontré «{real}» (appid {appid}) pero no he podido abrir Steam. "
                "Comprueba que Steam está instalado y con la sesión iniciada, y repítemelo.")
    webbrowser.open(f"https://store.steampowered.com/search/?term={urllib.parse.quote(name)}")
    return f"No encontré «{name}» en Steam; te abrí la búsqueda de la tienda para que lo elijas."


# -------------------------------------------------------------------- router
async def handle(intent: str, text: str, match, ctx) -> dict:
    try:
        gd = match.groupdict() if match else {}
        if intent == "launcher":
            return {"reply": await _open_launcher(ctx, gd.get("l", "")), "speak": True}
        if intent == "play":
            return {"reply": await _resolve_and_do(ctx, gd.get("g", ""), "run", "Lanzando"), "speak": True}
        if intent == "install":
            game = (gd.get("g") or gd.get("g2") or "").strip()
            return {"reply": await _resolve_and_do(ctx, game, "install", "Instalando"), "speak": True}
        if intent == "update":
            game = (gd.get("g") or gd.get("g2") or "").strip()
            return {"reply": await _resolve_and_do(ctx, game, "validate", "Actualizando/validando"), "speak": True}
    except Exception as exc:                                   # noqa: BLE001
        return {"reply": f"El minion de juegos ha fallado: {type(exc).__name__}: {exc}", "error": True}
    return {"reply": "Orden de juegos no reconocida."}
