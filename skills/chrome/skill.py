"""Minion Chrome — pestañas y páginas en vivo vía Chrome DevTools Protocol.

Misma técnica que chrome-devtools-mcp (github.com/ChromeDevTools/chrome-devtools-mcp)
pero nativa en nexus, sin Node: hablamos directamente con el puerto de
depuración de Chrome (CDP, 127.0.0.1:9222).

⚠ Desde Chrome 136 (2025) el perfil POR DEFECTO no admite depuración remota:
hay que arrancar Chrome con un perfil aparte. Por eso existe el «modo nexus»:
  di «conecta con chrome» → nexus lanza Chrome con el puerto abierto y un
  perfil propio (data/chrome_nexus). La primera vez inicia sesión en Google ahí
  y actívale la sincronización: tendrás tus marcadores/contraseñas de siempre.
Lo que navegues en ESA ventana es lo que nexus puede ver.

Qué sabe hacer:
  * «conecta con chrome» — arranca Chrome en modo nexus (o comprueba el enlace)
  * «qué pestañas tengo abiertas» — lista numerada de pestañas
  * «resume la pestaña 2» / «lee la pestaña de youtube» / «qué estoy viendo
    en chrome» — extrae el TEXTO REAL de la página y lo analiza con el LLM
  * «cambia a la pestaña de gmail» — la trae al frente
  * «abre una pestaña con el tiempo en madrid» / «abre marca.com en chrome»
  * «cierra la pestaña de twitter»
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from pathlib import Path

from backend.core import net
from backend.core.config import DATA_DIR

try:
    import websockets
    HAS_WS = True
except ImportError:
    HAS_WS = False

CDP = "http://127.0.0.1:9222"
PROFILE = DATA_DIR / "chrome_nexus"
MAX_PAGE_CHARS = 12000          # texto de página que pasamos al LLM

SKILL = {
    "name": "Chrome",
    "description": "Navegador en vivo: leer y resumir tus pestañas abiertas, cambiar, abrir y cerrar (CDP, como chrome-devtools-mcp)",
    # Qué hace cada intent, EN PALABRAS. Es lo que lee el planificador para
    # elegir: con solo el nombre («read») estaba adivinando.
    "intents": {
        "connect": "arrancar Chrome en modo nexus y vincularlo para poder leerlo",
        "close": "cerrar una pestaña",
        "switch": "traer al frente una pestaña que ya está abierta",
        "open": "abrir una pestaña nueva con una URL o una búsqueda",
        "read": "LEER DE VERDAD el contenido de una pestaña abierta y analizarlo o "
                "resumirlo. Úsalo SIEMPRE que pidan analizar, resumir, mirar o "
                "contar qué hay en una página, pestaña o pantalla del navegador",
        "tabs": "listar qué pestañas hay abiertas",
    },
    # Los verbos van con enclítico («ábreme», «ciérrame», «vincúlame») porque es
    # como se piden de viva voz.
    "patterns": {
        # Conectar / estado. «modo nexus» del navegador.
        "connect": r"(?:con[eé]cta(?:te|me)?\s+(?:con|a)\s+chrome|vinc[uú]la(?:me)?\s+chrome|"
                   r"(?:rein[ií]cia|arr[aá]nca|l[aá]nza|in[ií]cia)(?:me)?\s+chrome(?:\s+en\s+modo\s+(?:nexus|depuraci[oó]n|debug))?|"
                   r"chrome\s+en\s+modo\s+nexus|estado\s+de\s+chrome)",
        # Cerrar una pestaña — ANTES que read/switch por si acaso, y muy específica.
        "close": r"ci[eé]rra(?:me)?\s+(?:la\s+)?pesta[ñn]a\s*(?P<which>.*)",
        # Traer una pestaña al frente.
        "switch": r"(?:c[aá]mbia(?:me)?|vete|ve|salta|mu[eé]vete)\s+a\s+(?:la\s+)?pesta[ñn]a\s+(?P<which>.+)"
                  r"|act[ií]va(?:me)?\s+la\s+pesta[ñn]a\s+(?P<which2>.+)",
        # Abrir pestaña nueva (URL o búsqueda).
        "open": r"[aá]bre(?:me)?\s+una\s+(?:nueva\s+)?pesta[ñn]a(?:\s+(?:con|de|para|y\s+busca))?\s*(?P<what>.*)"
                r"|[aá]bre(?:me)?\s+(?P<what2>\S.{0,120}?)\s+en\s+(?:chrome|el\s+navegador)",
        # Leer/resumir el contenido REAL de una pestaña. Tiene que ser ancha:
        # cualquier petición de analizar algo del navegador debe llegar a quien
        # lee el navegador de verdad, no al planificador.
        "read": r"(?:lee|l[eé]e(?:me)?|resume|res[uú]me(?:me)?|anal[ií]za(?:me)?|expl[ií]ca(?:me)?|traduce|trad[uú]ce(?:me)?|de\s+qu[eé]\s+va)"
                r"[^.\n]{0,40}\bpesta[ñn]a\b(?P<sel>[^.\n]{0,60})?"
                r"|(?:lee|l[eé]e(?:me)?|resume|res[uú]me(?:me)?|anal[ií]za(?:me)?|mira|d[ií]me)[^.\n]{0,40}\b(?:p[aá]gina|web|pantalla)\b"
                r"[^.\n]{0,30}\b(?:abierta|actual|activa|de\s+chrome|del\s+navegador|"
                r"que\s+(?:tengo|estoy)\s+(?:abierta|viendo|mirando|leyendo))"
                r"|(?:lee|l[eé]e(?:me)?|resume|res[uú]me(?:me)?|anal[ií]za(?:me)?|mira)\s+(?:lo\s+que\s+(?:ves|hay|pone)\s+)?"
                r"(?:en\s+)?(?:la\s+|el\s+)?(?:p[aá]gina|pesta[ñn]a|pantalla)?\s*(?:de\s+)?"
                r"(?:chrome|el\s+navegador)\b"
                r"|qu[eé]\s+(?:estoy\s+(?:viendo|mirando|leyendo)|ves|hay|pone)\s+"
                r"en\s+(?:chrome|el\s+navegador|la\s+pantalla)",
        # Listado de pestañas — la más amplia, al final del dict.
        "tabs": r"(?:qu[eé]|cu[aá]les|cu[aá]ntas)\s+pesta[ñn]as|"
                r"(?:ver|mu[eé]stra(?:me)?|ens[eé][ñn]a(?:me)?|l[ií]sta(?:me)?|d[ií]me|d[aá]me)\s+(?:las\s+|mis\s+)?pesta[ñn]as|"
                r"pesta[ñn]as\s+abiertas|\bmis\s+pesta[ñn]as\b|"
                r"qu[eé]\s+tengo\s+abierto\s+en\s+(?:chrome|el\s+navegador)",
    },
}


# ─────────────────────────── CDP: utilidades ───────────────────────────

async def _tabs() -> list[dict] | None:
    """Pestañas reales (type=page). None si Chrome no está en modo nexus."""
    try:
        r = await net.client().get(f"{CDP}/json/list", timeout=3)
        pages = [t for t in r.json() if t.get("type") == "page"
                 and not t.get("url", "").startswith(("devtools://", "chrome-extension://"))]
        return pages
    except Exception:
        return None


async def _cdp_action(path: str) -> bool:
    """GET con respaldo PUT (Chrome moderno exige PUT en /json/new)."""
    cli = net.client()
    for method in ("get", "put"):
        try:
            r = await getattr(cli, method)(f"{CDP}{path}", timeout=4)
            if r.status_code < 400:
                return True
        except Exception:
            pass
    return False


async def _page_text(tab: dict) -> dict | None:
    """Extrae título/URL/texto visible de la pestaña vía WebSocket CDP."""
    if not HAS_WS:
        return None
    expr = ("JSON.stringify({title: document.title, url: location.href, "
            "text: (document.body ? document.body.innerText : '').slice(0, 60000)})")
    try:
        async with websockets.connect(tab["webSocketDebuggerUrl"],
                                      max_size=20_000_000, open_timeout=5) as ws:
            await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                      "params": {"expression": expr, "returnByValue": True}}))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                if msg.get("id") == 1:
                    val = msg.get("result", {}).get("result", {}).get("value")
                    return json.loads(val) if val else None
    except Exception:
        return None


_GENERICO = ("", "actual", "activa", "abierta", "esta", "esa", "ésta", "de chrome",
             "del navegador", "que tengo abierta", "que estoy viendo")


def _pick(tabs: list[dict], sel: str) -> dict:
    """Elige pestaña por número («la 2»), por término («de youtube») o la 1ª."""
    t = _pick_strict(tabs, sel)
    return t if t is not None else tabs[0]


def _pick_strict(tabs: list[dict], sel: str) -> dict | None:
    """Como `_pick`, pero devuelve None si el selector no señala ninguna pestaña.

    Lo usan cerrar y cambiar: caer en la pestaña 1 cuando «de twitter» no existe
    significa cerrar una pestaña que nadie pidió cerrar."""
    sel = (sel or "").strip().lower()
    m = re.search(r"\b(\d{1,2})\b", sel)
    if m:
        n = int(m.group(1))
        return tabs[n - 1] if 1 <= n <= len(tabs) else None
    term = re.sub(r"^(?:de|del|la|el|n[uú]mero|actual|activa|abierta)\s+", "", sel).strip(" ¿?.")
    if term and term not in _GENERICO:
        for t in tabs:
            if term in (t.get("title", "") + " " + t.get("url", "")).lower():
                return t
        return None
    return tabs[0] if not sel or sel in _GENERICO or term in _GENERICO else None


def _chrome_exe() -> str | None:
    for p in (os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
              os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
              os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe")):
        if Path(p).exists():
            return p
    return None


def _no_encaja(sel: str, tabs: list[dict]) -> str:
    """Mensaje cuando el selector no señala ninguna pestaña abierta."""
    lista = "\n".join(f"  {i}. {(t.get('title') or t.get('url') or '')[:60]}"
                      for i, t in enumerate(tabs, 1))
    return (f"No tengo ninguna pestaña que encaje con «{sel.strip()}». "
            f"Estas son las {len(tabs)} abiertas:\n{lista}\n"
            "Dime el número o un trozo del título.")


NO_LINK = ("Chrome no está en modo nexus (puerto de depuración cerrado). "
           "Di «conecta con chrome» y te lo arranco listo para leerte las pestañas. "
           "Ojo: es una ventana de Chrome con perfil propio de nexus — la primera vez "
           "inicia sesión en Google ahí y activa la sincronización para tener tus "
           "marcadores y contraseñas.")


# ─────────────────────────────── handler ───────────────────────────────

async def handle(intent: str, text: str, match, ctx) -> dict:

    if intent == "connect":
        tabs = await _tabs()
        if tabs is not None:
            return {"reply": f"Chrome ya está vinculado: veo {len(tabs)} pestaña(s). "
                             "Pídeme «qué pestañas tengo» o «resume la pestaña de …»."}
        exe = _chrome_exe()
        if not exe:
            return {"reply": "No encuentro chrome.exe en las rutas habituales. "
                             "¿Está instalado Google Chrome?"}
        PROFILE.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.Popen([exe, "--remote-debugging-port=9222",
                              f"--user-data-dir={PROFILE}",
                              "--restore-last-session", "--no-first-run"],
                             creationflags=0x00000008)   # DETACHED_PROCESS
        except Exception as exc:
            return {"reply": f"No pude lanzar Chrome: {exc}"}
        for _ in range(10):
            await asyncio.sleep(0.6)
            tabs = await _tabs()
            if tabs is not None:
                extra = "" if HAS_WS else ("\n⚠ Falta la librería websockets (se instala sola "
                                           "en el próximo arranque de nexus): hasta entonces puedo "
                                           "listar pestañas pero no leer su contenido.")
                return {"reply": "Chrome en modo nexus arrancado y vinculado. ✔ "
                                 "Lo que navegues en esa ventana puedo verlo: pídeme "
                                 "«qué pestañas tengo» o «resume la pestaña de …»." + extra}
        return {"reply": "He lanzado Chrome pero el puerto de depuración no responde. "
                         "Cierra todas las ventanas de Chrome y vuelve a decir «conecta con chrome»."}

    tabs = await _tabs()
    if tabs is None:
        return {"reply": NO_LINK}
    if not tabs:
        return {"reply": "Chrome está vinculado pero no hay ninguna pestaña abierta."}

    if intent == "tabs":
        lines = [f"🌐 {len(tabs)} pestaña(s) abiertas:"]
        for i, t in enumerate(tabs, 1):
            host = re.sub(r"^https?://(www\.)?", "", t.get("url", "")).split("/")[0]
            title = (t.get("title") or host or "sin título")[:70]
            lines.append(f"  {i}. {title}  ·  {host}")
        lines.append("Di «resume la pestaña N» (o «…la pestaña de youtube») y te la leo.")
        return {"reply": "\n".join(lines), "data": [{"title": t.get("title"), "url": t.get("url")} for t in tabs]}

    if intent == "read":
        sel = ""
        try:
            sel = match.group("sel") or ""
        except Exception:
            pass
        tab = _pick(tabs, sel or text)
        if not HAS_WS:
            return {"reply": "Me falta la librería «websockets» para leer el contenido "
                             "(se instala sola en el próximo arranque de nexus). De momento: "
                             f"esa pestaña es «{tab.get('title')}» — {tab.get('url')}"}
        page = await _page_text(tab)
        if not page or not page.get("text", "").strip():
            return {"reply": f"No he podido extraer el texto de «{tab.get('title')}» "
                             "(¿página protegida o aún cargando?). Prueba otra vez en unos segundos."}
        from backend.core.llm import ask_llm
        contenido = page["text"][:MAX_PAGE_CHARS]
        prompt = (f"El operador ha pedido: «{text}».\n"
                  f"Página abierta en su navegador: «{page.get('title')}» ({page.get('url')}).\n"
                  f"CONTENIDO REAL de la página:\n{contenido}\n\n"
                  "Responde a lo que pide basándote SOLO en este contenido, en español, "
                  "directo y útil (resumen con lo esencial si no pidió otra cosa).")
        answer, _prov = await ask_llm(prompt)
        return {"reply": f"«{page.get('title')}» — {page.get('url')}\n\n{answer}"}

    if intent == "switch":
        sel = ""
        for g in ("which", "which2"):
            try:
                sel = match.group(g) or sel
            except Exception:
                pass
        tab = _pick_strict(tabs, sel)
        if tab is None:
            return {"reply": _no_encaja(sel, tabs)}
        ok = await _cdp_action(f"/json/activate/{tab['id']}")
        return {"reply": f"Al frente: «{tab.get('title')}». ✔" if ok
                else "No he podido activar esa pestaña."}

    if intent == "open":
        what = ""
        for g in ("what", "what2"):
            try:
                what = (match.group(g) or "").strip(" .¡!¿?") or what
            except Exception:
                pass
        if not what:
            url = "about:blank"
        elif re.match(r"^https?://", what) or ("." in what.split()[0] and " " not in what):
            url = what if what.startswith("http") else f"https://{what}"
        else:
            from urllib.parse import quote_plus
            url = f"https://www.google.com/search?q={quote_plus(what)}"
        ok = await _cdp_action(f"/json/new?{url}")
        return {"reply": f"Pestaña abierta: {url} ✔" if ok
                else "No he podido abrir la pestaña (¿Chrome sigue en modo nexus?)."}

    if intent == "close":
        sel = ""
        try:
            sel = (match.group("which") or "").strip()
        except Exception:
            pass
        if not sel:
            return {"reply": "Dime cuál: «cierra la pestaña 2» o «cierra la pestaña de twitter»."}
        tab = _pick_strict(tabs, sel)
        if tab is None:
            return {"reply": _no_encaja(sel, tabs) + "\nNo he cerrado ninguna."}
        ok = await _cdp_action(f"/json/close/{tab['id']}")
        return {"reply": f"Pestaña «{tab.get('title')}» cerrada. ✔" if ok
                else "No he podido cerrar esa pestaña."}

    return {"reply": "Orden de Chrome no reconocida."}
