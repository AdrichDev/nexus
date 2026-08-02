"""Minion HERMES — delega trabajos AGÉNTICOS en Hermes Agent (Nous Research).

Hermes Agent (hermes-agent.nousresearch.com, open source MIT) corre en el PC y
sabe navegar, investigar, automatizar el navegador, ejecutar código aislado…
nexus lo usa como SUBAGENTE: tú se lo pides a nexus («hermes: investiga X y
hazme un informe») y nexus se lo encarga por su API local (compatible OpenAI,
http://127.0.0.1:8642) COMO TRABAJO EN 2º PLANO — sigue libre mientras tanto y
te trae el resultado por el MISMO canal (HUD, móvil o Telegram).

CÓMO FUNCIONA LA CONEXIÓN (esto es lo que fallaba y ahora se AUTO-REPARA):
  * El API server de Hermes solo arranca si en ~/.hermes/.env están
    API_SERVER_ENABLED=true y una API_SERVER_KEY FUERTE (>=16 caracteres; si es
    corta o un placeholder, Hermes SE NIEGA a abrir el puerto 8642 aunque el
    gateway esté corriendo → nexus lo veía «apagado» para siempre).
  * nexus ahora lo comprueba y lo PROVISIONA él solo: escribe el .env de
    Hermes (con backup), sincroniza la clave con config/secrets.json
    ("hermes_api_key") y (re)arranca el gateway capturando sus errores en
    data/hermes_gateway.log (antes iban a DEVNULL y nadie sabía por qué moría).
  * «arranca hermes» / «¿está hermes conectado?» / «¿y la respuesta de
    hermes?» son intents PROPIOS — se acabó el bucle de «Hermes está apagado».
"""
from __future__ import annotations

import re
import time

SKILL = {
    "name": "Hermes (subagente)",
    "description": ("Encargos agénticos en 2º plano con Hermes Agent (Nous) por su API local: "
                    "«hermes: investiga X y hazme un informe». Además arranca y auto-repara su "
                    "gateway («arranca hermes»), diagnostica conexión y cerebro («diagnostica "
                    "hermes») y recupera resultados («¿y la respuesta de hermes?»)."),
    "patterns": {
        # ORDEN: lo específico primero; el genérico «hermes: …» al final.
        # Los verbos admiten PRONOMBRE ENCLÍTICO («diagnostícame hermes») y su tilde.
        "hermes_estado": r"(?:est[aá]|anda|sigue|va)\s+hermes\s+(?:conectado|encendido|apagado|vivo|activo|bien|mal|en\s+marcha|operativo|funcionando|corriendo)"
                         r"|hermes\s+(?:est[aá]|anda|va)\s+(?:conectado|encendido|apagado|vivo|activo|bien|mal|funcionando|corriendo|ca[ií]do)"
                         r"|(?:estado|diagn[oó]stico)\s+de(?:l)?\s+hermes"
                         r"|diagn[oó]st[ií]ca(?:me|le|lo|nos)?\s+(?:a\s+|el\s+|la\s+conexi[oó]n\s+(?:con|de)\s+)?hermes\b"
                         r"|(?:rev[ií]sa|compru[eé]ba|chequea|ver[ií]fica|mira)(?:me|nos)?\s+(?:si\s+|c[oó]mo\s+)?(?:est[aá]\s+|la\s+conexi[oó]n\s+(?:con|de)\s+)?hermes\b"
                         r"|qu[eé]\s+tal\s+(?:va|anda|est[aá])\s+hermes"
                         r"|(?:funciona|responde)\s+hermes\b|hermes\s+(?:funciona|responde)\b"
                         r"|(?:va|anda|funciona)\s+(?:bien|mal)\s+hermes\b"
                         r"|c[oó]mo\s+(?:va|est[aá])\s+hermes",
        "hermes_resultado": r"(?:la\s+)?(?:respuesta|resultado|informe|salida)\s+(?:de|que\s+te\s+ha\s+dado)\s+hermes"
                            r"|qu[eé]\s+(?:te|me|nos)\s+ha\s+(?:dicho|dado|contestado|respondido)\s+hermes"
                            r"|(?:ha|habr[aá])\s+(?:terminado|acabado|contestado|respondido)\s+(?:ya\s+)?hermes"
                            r"|hermes\s+(?:ya\s+)?(?:ha\s+)?(?:terminado|acabado|contestado|respondido)"
                            r"|(?:ya\s+)?(?:termin[oó]|acab[oó]|contest[oó]|respondi[oó])\s+(?:ya\s+)?hermes\b"
                            r"|hermes\s+(?:ya\s+)?(?:termin[oó]|acab[oó]|contest[oó]|respondi[oó])\b"
                            r"|c[oó]mo\s+va(?:n)?\s+(?:el\s+encargo|la\s+tarea|el\s+trabajo|los\s+encargos|las\s+tareas|los\s+trabajos)\s+de\s+hermes"
                            r"|qu[eé]\s+ha\s+(?:dicho|encontrado|averiguado|sacado|contestado|respondido)\s+hermes"
                            r"|(?:novedades|algo\s+nuevo)\s+de\s+hermes\b"
                            r"|(?:encargos?|tareas?|trabajos?)\s+de\s+hermes\b"
                            r"|(?:resultado|respuesta|estado)\s+del?\s+encargo\s+#?\d+"
                            r"|c[oó]mo\s+va\s+el\s+encargo\s+#?\d+"
                            r"|\bencargo\s+#?\d+\b",
        "hermes_arranca": r"(?:arr[aá]nca|lev[aá]nta|in[ií]cia|rein[ií]cia|rel[aá]nza|enci[eé]nde|act[ií]va"
                          r"|despi[eé]rta|resuc[ií]ta|l[aá]nza|[aá]bre|con[eé]cta|recon[eé]cta|p[oó]n)"
                          r"(?:me|lo|le|nos)?\s+(?:a\s+|al\s+|el\s+)?(?:gateway\s+de\s+|servidor\s+de\s+)?hermes\b"
                          r"|vuelve\s+a\s+(?:arrancar|lanzar|levantar|encender)\s+(?:a\s+|el\s+)?hermes\b"
                          r"|pon\s+(?:en\s+marcha\s+)?(?:a\s+)?hermes\b|pon(?:me)?\s+hermes\s+en\s+marcha"
                          r"|hermes\s+arriba\b",
        "hermes_tarea": r"(?:m[aá]ndale|env[ií]ale|dale|p[aá]sale|encom[ié]ndale|as[ií]gnale|d[eé]jale)\s+(?:una?\s+|otra\s+|alg[uú]n\s+)?(?:tarea|encargo|trabajo|curro|misi[oó]n|recado)\s+a\s+hermes(?:\s*[:,.]?\s*(?P<orden4>.+))?"
                        r"|(?:manda|env[ií]a|pasa|asigna)\s+(?:una?\s+|otra\s+)?(?:tarea|encargo|trabajo)\s+a\s+hermes(?:\s*[:,.]?\s*(?P<orden5>.+))?",
        "hermes_info": r"(?:qu[eé]\s+(?:sabe[sn]?|puede[sn]?)\s+hacer|capacidades\s+de)\s+hermes\b"
                       r"|para\s+qu[eé]\s+(?:sirve|vale)\s+hermes\b|qu[eé]\s+es\s+hermes\b"
                       r"|qu[eé]\s+(?:skills|herramientas|capacidades)\s+tiene\s+hermes\b"
                       r"|de\s+qu[eé]\s+es\s+capaz\s+hermes\b"
                       r"|\bhermes\b[^.\n]{0,20}qu[eé]\s+sabe[sn]?\s+hacer",
        "hermes": r"^\s*hermes[:,]\s*(?P<orden>.+)$"
                  r"|(?:dile|p[ií]dele|m[aá]ndale|ord[eé]nale|enc[aá]rga(?:le)?|delega(?:\s+en)?)\s+a?\s*hermes(?:\s*[:,]\s*|\s+)(?:que\s+)?(?P<orden2>.+)"
                  r"|que\s+hermes\s+(?P<orden3>.+)",
    },
}


# ¿Este encargo es de los que SOLO Hermes hace bien? (navegación real, investigación
# multipaso, automatización, informe de mercado). nexus delega SOLO — sin que el
# operador diga «hermes» — cuando ninguna skill local casó Y esto pinta agéntico.
# Conservador: si Hermes está apagado, esto ni se consulta y va a conversación normal.
_AGENTIC_RX = re.compile(
    r"\b(autom[aá]tiza|automatizaci[oó]n)\b"
    r"|\bmonitoriza\b|\bvigila\b[^.\n]{0,25}\b(precio|web|p[aá]gina|stock)\b"
    r"|\brellena\b[^.\n]{0,25}\bformulario\b"
    r"|\b(scrapea|rastrea|extrae)\b[^.\n]{0,30}\b(web|internet|tienda|p[aá]gina|datos)\b"
    r"|\b(reserva|compra)\b[^.\n]{0,20}\b(online|en\s+(la\s+web|internet|amazon))\b"
    r"|\b(entra|navega|m[eé]tete|ve)\b[^.\n]{0,20}\b(a\s+la\s+web|en\s+la\s+web|al\s+sitio|a\s+la\s+p[aá]gina|a\s+internet)\b"
    r"|\bestudio\s+de\s+mercado\b|\ban[aá]lisis\s+de\s+mercado\b|\binforme\s+de\s+mercado\b"
    r"|\bmira\s+en\s+(?:internet|la\s+web|varias\s+webs)\b|\bent[eé]rate\s+de\b"
    r"|\bres[uú]me(?:me)?\b[^.\n]{0,40}\b(?:noticias?|portada|la\s+web|una\s+web|p[aá]gina)\b"
    r"|\bcompara\b[^.\n]{0,45}\b(precios?|productos?|proveedores?)\b[^.\n]{0,30}\b(en|entre|varias?|distintas?|tiendas?|webs?)\b",
    re.IGNORECASE)
# verbo de producir/investigar + sustantivo de entregable de investigación
_RESEARCH_RX = re.compile(
    r"\b(investiga|analiza|compara|recopila|rastrea|elabora|prepara|prep[aá]rame|"
    r"h[aá]z(?:me)?|gen[eé]ra(?:me)?|s[aá]came|busca(?:me)?)\b[^.\n]{0,60}"
    r"\b(informe|dossier|comparativa|proveedores?|competencia|an[aá]lisis|estudio|"
    r"tendencias?|rese[ñn]as?|opiniones)\b",
    re.IGNORECASE)
# preguntas factuales cortas → NO son para Hermes (van a conversación/web rápida)
_FACTUAL_RX = re.compile(r"^\s*(qu[eé]|qui[eé]n|cu[aá]ndo|cu[aá]nto|c[oó]mo|d[oó]nde|"
                         r"por\s+qu[eé]|cu[aá]l)\b", re.IGNORECASE)


def should_delegate(text: str) -> bool:
    t = (text or "").strip()
    if len(t.split()) < 4:
        return False
    if _FACTUAL_RX.match(t) and not _AGENTIC_RX.search(t):
        return False
    return bool(_AGENTIC_RX.search(t) or _RESEARCH_RX.search(t))


_ALIVE = {"ok": False, "ts": 0.0}


async def alive_cached(ctx) -> bool:
    """/health con caché de 60 s — NO pinga en cada mensaje (latencia)."""
    now = time.monotonic()
    if now - _ALIVE["ts"] < 60:
        return _ALIVE["ok"]
    url, hdr = _cfg(ctx)
    _ALIVE["ok"] = await _alive(url, hdr)
    _ALIVE["ts"] = now
    return _ALIVE["ok"]


# ======================= REGISTRO DE ENCARGOS =======================
# Lo que le mandamos a Hermes queda APUNTADO (data/hermes_jobs.json): estado
# (encargado → trabajando → hecho/error) y su resultado. Así «¿y la respuesta
# de hermes?» tiene SIEMPRE una respuesta de verdad — se acabó el bucle.
_REG_MAX = 20


def _reg_file():
    from backend.core.config import DATA_DIR
    return DATA_DIR / "hermes_jobs.json"


def _reg_load() -> list:
    import json
    try:
        data = json.loads(_reg_file().read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _reg_save(items: list) -> None:
    import json
    try:
        f = _reg_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(items[-_REG_MAX:], ensure_ascii=False, indent=1),
                     encoding="utf-8")
    except Exception:
        pass


def _reg_add(orden: str, channel: str) -> tuple:
    """Apunta el encargo con un NÚMERO correlativo visible (#1, #2…): es el
    identificador que se le enseña al operador y con el que puede pedir su resultado."""
    import uuid
    jid = uuid.uuid4().hex[:8]
    items = _reg_load()
    num = max((int(it.get("num") or 0) for it in items), default=0) + 1
    items.append({"id": jid, "num": num, "orden": orden[:300], "canal": channel,
                  "estado": "encargado", "resultado": "", "t0": time.time(), "t1": None})
    _reg_save(items)
    return jid, num


def _reg_set(jid: str, **kw) -> None:
    items = _reg_load()
    for it in items:
        if it.get("id") == jid:
            it.update(kw)
            break
    _reg_save(items)


def _fmt_age(secs: float) -> str:
    secs = max(0, int(secs))
    if secs < 90:
        return f"{secs} s"
    if secs < 5400:
        return f"{secs // 60} min"
    return f"{secs // 3600} h {(secs % 3600) // 60} min"


async def delegate(orden: str, ctx, channel: str, request_id: str = "") -> dict:
    """Encarga a Hermes en 2º plano y devuelve el acuse. Compartido por la orden
    explícita («hermes: …») y la delegación AUTOMÁTICA del cerebro.

    v23 (T8/T9): el encargo hereda el requestId de la petición del operador, queda
    registrado que el AGENTE ejecutor es Hermes, y los duplicados vivos se bloquean
    — Hermes no puede acabar haciendo dos veces lo mismo."""
    from backend.core.jobs import jobs as job_mgr
    url, hdr = _cfg(ctx)
    dup = job_mgr.active_duplicate(f"hermes::{orden}", channel)
    if dup:
        return {"reply": "Eso ya lo tengo en marcha, no lo empiezo dos veces. "
                         "Te aviso en cuanto lo tenga."}
    jid, num = _reg_add(orden, channel)
    from backend.core import publicvoice as pv
    await job_mgr.submit(f"#{num}: {orden[:44]}",
                         lambda o=orden, j=jid, n=num: _run_hermes(o, url, hdr, channel, j, n),
                         kind="hermes", agent="hermes", channel=channel,
                         request_id=request_id, request=orden,
                         dedupe_key=f"hermes::{orden}", notify=True)
    # specs v24 (T1/T2/T5): nexus habla en PRIMERA PERSONA. Ni subagente, ni
    # gateway, ni plazos inventados; y la frase cambia según el tipo de tarea.
    activas = len([j for j in job_mgr.active() if j.get("kind") == "hermes"]) - 1
    return {"reply": pv.frase_inicio(orden, activas=max(0, activas))}


_SETTINGS = [None]


def known_about_user() -> list:
    """Lee lo que HERMES sabe del operador (sus ficheros de memoria en disco):
    memories/USER.md + MEMORY.md y desktop-attachments/USER.md. Devuelve
    [(fichero, texto)] — para que nexus pueda listarlo junto a lo suyo."""
    import io as _io
    import os
    home = os.path.expanduser("~")
    cands = [
        os.path.join(home, "AppData", "Local", "hermes", "memories", "USER.md"),
        os.path.join(home, "AppData", "Local", "hermes", "memories", "MEMORY.md"),
        os.path.join(home, ".hermes", "desktop-attachments", "USER.md"),
    ]
    out, seen = [], set()
    for path in cands:
        try:
            if os.path.exists(path):
                txt = _io.open(path, encoding="utf-8", errors="replace").read().strip()
                key = txt[:80]
                if txt and key not in seen:
                    seen.add(key)
                    out.append((os.path.basename(path), txt))
        except Exception:
            pass
    return out


def _cfg(ctx) -> tuple[str, dict]:
    _SETTINGS[0] = ctx["settings"]
    url = (ctx["settings"].get("hermes_url") or "http://127.0.0.1:8642").rstrip("/")
    key = ctx["settings"].secret("hermes_api_key") or ""
    hdr = {"Authorization": f"Bearer {key}"} if key else {}
    return url, hdr


async def _alive(url: str, hdr: dict) -> bool:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=4) as cli:
            r = await cli.get(f"{url}/health", headers=hdr)
            return r.status_code < 500
    except Exception:
        return False


async def _auth_ok(url: str, hdr: dict) -> bool:
    """¿La clave que tiene nexus VALE para la API? (/health/detailed va autenticado).
    True también si el endpoint no existe (versiones viejas) — solo 401/403 es 'no'."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=4) as cli:
            r = await cli.get(f"{url}/health/detailed", headers=hdr)
            return r.status_code not in (401, 403)
    except Exception:
        return True


async def _port_open(url: str) -> bool:
    """¿Hay ALGO escuchando en el puerto del API de Hermes? (sin HTTP, solo TCP)."""
    import asyncio as _a
    from urllib.parse import urlparse
    try:
        u = urlparse(url)
        host, port = (u.hostname or "127.0.0.1"), (u.port or 8642)
        fut = _a.open_connection(host, port)
        _r, w = await _a.wait_for(fut, timeout=1.5)
        w.close()
        try:
            await w.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False


def _hermes_exe(ctx) -> str:
    """Ruta al CLI de Hermes (venv\\Scripts\\hermes.exe). Configurable en ⚙
    (hermes_exe); si no, se busca en la instalación por defecto del usuario."""
    import os
    p = (ctx["settings"].get("hermes_exe") or "").strip()
    if p and os.path.exists(p):
        return p
    cand = os.path.join(os.path.expanduser("~"), "AppData", "Local", "hermes",
                        "hermes-agent", "venv", "Scripts", "hermes.exe")
    if os.path.exists(cand):
        return cand
    cand2 = os.path.join(os.path.expanduser("~"), ".hermes", "hermes-agent",
                         "venv", "bin", "hermes")
    return cand2 if os.path.exists(cand2) else ""


def installed(ctx) -> bool:
    """¿Está Hermes instalado en el PC? (para decidir si merece la pena delegar
    aunque su gateway esté ahora apagado — lo arrancamos nosotros)."""
    return bool(_hermes_exe(ctx))


# ================= AUTOPROVISIÓN del .env de Hermes =================
# El API server de Hermes SE NIEGA a arrancar sin API_SERVER_ENABLED=true y una
# API_SERVER_KEY fuerte (>=16 chars, sin placeholders). Esto era LA CAUSA de que
# nexus lo viera «apagado» incluso con Hermes abierto. nexus lo deja fino solo.
def _key_strong(key: str) -> bool:
    """Autocontenida (la testea test_routing extrayéndola por AST)."""
    import re as _re
    key = (key or "").strip()
    if len(key) < 16:
        return False
    return not _re.search(r"change|placeholder|your[-_]|xxx|ejemplo|example", key, _re.IGNORECASE)


def _hermes_env_path() -> str:
    import os
    home = os.environ.get("HERMES_HOME") or os.path.join(os.path.expanduser("~"), ".hermes")
    return os.path.join(home, ".env")


def _read_env_file(path: str) -> dict:
    """Parsea un .env sencillo (KEY=valor). Tolerante: líneas raras se ignoran."""
    import io
    import os
    out = {}
    try:
        if os.path.exists(path):
            for line in io.open(path, encoding="utf-8", errors="replace"):
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return out


def _env_apply(text: str, key: str) -> tuple:
    """PURA (testeable): devuelve el texto del .env con API_SERVER_ENABLED=true y
    API_SERVER_KEY=<key> aplicados (respetando el resto de líneas), y la lista de
    cambios hechos. Si ya estaba todo bien, cambios = []."""
    lines = (text or "").splitlines()
    changes = []
    seen_en, seen_key = False, False
    out = []
    for line in lines:
        s = line.strip()
        if s.startswith("API_SERVER_ENABLED"):
            seen_en = True
            val = s.split("=", 1)[1].strip().lower() if "=" in s else ""
            if val not in ("1", "true", "yes", "on"):
                out.append("API_SERVER_ENABLED=true")
                changes.append("API_SERVER_ENABLED=true (estaba desactivado)")
                continue
        elif s.startswith("API_SERVER_KEY"):
            seen_key = True
            cur = s.split("=", 1)[1].strip().strip('"').strip("'") if "=" in s else ""
            if cur != key:
                out.append("API_SERVER_KEY=" + key)
                changes.append("API_SERVER_KEY (la que había era débil o distinta)")
                continue
        out.append(line)
    if not seen_en:
        out.append("API_SERVER_ENABLED=true")
        changes.append("API_SERVER_ENABLED=true (no existía)")
    if not seen_key:
        out.append("API_SERVER_KEY=" + key)
        changes.append("API_SERVER_KEY nueva (no existía)")
    new = "\n".join(out)
    if new and not new.endswith("\n"):
        new += "\n"
    return new, changes


def provision_env(ctx) -> tuple:
    """Deja el ~/.hermes/.env listo para el API server y SINCRONIZA la clave con
    config/secrets.json (hermes_api_key). Devuelve (cambió_algo, lista_de_cambios).
    Regla de claves: si el .env ya tiene una clave FUERTE, se adopta (no se rota);
    si no, se usa la de nexus si es fuerte; si tampoco, se genera una nueva."""
    import io
    import os
    import secrets as _secrets
    path = _hermes_env_path()
    envv = _read_env_file(path)
    env_key = envv.get("API_SERVER_KEY", "")
    wab_key = ctx["settings"].secret("hermes_api_key")
    if _key_strong(env_key):
        final = env_key
    elif _key_strong(wab_key):
        final = wab_key
    else:
        final = _secrets.token_hex(32)
    old_text = ""
    try:
        if os.path.exists(path):
            old_text = io.open(path, encoding="utf-8", errors="replace").read()
    except Exception:
        old_text = ""
    new_text, changes = _env_apply(old_text, final)
    if changes:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if old_text:
                with io.open(path + ".bak_nexus", "w", encoding="utf-8") as f:
                    f.write(old_text)
            with io.open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(new_text)
        except Exception as exc:
            return False, [f"no pude escribir {path}: {exc}"]
    if final != wab_key:
        try:
            ctx["settings"].set_secret("hermes_api_key", final)
            changes.append("clave sincronizada en config/secrets.json")
        except Exception:
            pass
    return bool(changes), changes


def _clean_env() -> dict:
    """Entorno LIMPIO para lanzar Hermes. CAUSA REAL de los 500 (23-jul, visto en
    data/hermes_gateway.log): el proceso de nexus corre con PYTHONPATH/VIRTUAL_ENV
    apuntando a SU .venv (Python 3.12); el python de Hermes (3.11) los HEREDA e
    importa el pydantic de nexus → «No module named pydantic_core._pydantic_core»
    → todos los encargos devolvían 500. Si ese PYTHONPATH es global de Windows,
    contamina TAMBIÉN al Hermes de escritorio (por eso fallaba hasta abierto)."""
    import os
    env = dict(os.environ)
    for k in list(env):
        if k.upper() in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP",
                         "PYTHONEXECUTABLE", "PYTHONUSERBASE", "VIRTUAL_ENV"):
            env.pop(k, None)
    return env


# ============= CONFIGURAR EL CEREBRO de Hermes (proveedor+modelo+clave) =============
# Mapa proveedor (UI) -> (var de entorno que Hermes lee, provider de Hermes, base_url).
# Con esto nexus deja el .env y el config.yaml de Hermes listos para que su modelo
# interno funcione — arregla el 401 «Missing Authentication header».
_PROV_MAP = {
    "openai":     {"env": "OPENAI_API_KEY",     "hp": "custom",     "base": "https://api.openai.com/v1", "secret": "openai_api_key"},
    "anthropic":  {"env": "ANTHROPIC_API_KEY",  "hp": "anthropic",  "base": "",                          "secret": "anthropic_api_key"},
    "gemini":     {"env": "GEMINI_API_KEY",     "hp": "gemini",     "base": "",                          "secret": "gemini_api_key"},
    "openrouter": {"env": "OPENROUTER_API_KEY", "hp": "openrouter", "base": "",                          "secret": "openrouter_api_key"},
}


def _env_set_var(text: str, key: str, value: str) -> str:
    """PURA: pone/reemplaza una línea KEY=value en el texto de un .env, respetando
    el resto. (Reutilizable para claves de proveedor en ~/.hermes/.env.)"""
    lines = (text or "").splitlines()
    out, seen = [], False
    for line in lines:
        if line.strip().startswith(key + "=") or line.strip().startswith(key + " ="):
            out.append(f"{key}={value}")
            seen = True
        else:
            out.append(line)
    if not seen:
        out.append(f"{key}={value}")
    new = "\n".join(out)
    return new + ("\n" if new and not new.endswith("\n") else "")


def _hermes_config_path() -> str:
    import os
    home = os.environ.get("HERMES_HOME") or os.path.join(os.path.expanduser("~"), ".hermes")
    return os.path.join(home, "config.yaml")


def _yaml_set_model(text: str, hp: str, model: str, base: str) -> str:
    """Best-effort SIN dependencia de PyYAML: deja el bloque `model:` con provider,
    default y (si custom) base_url. Si ya existe un bloque model:, reescribe esas
    claves; si no, lo añade al principio. Conserva el resto del fichero."""
    import re as _re
    block = "model:\n  default: \"" + model + "\"\n  provider: \"" + hp + "\"\n"
    if base:
        block += "  base_url: \"" + base + "\"\n"
    if not text or not _re.search(r"(?m)^model:\s*$", text):
        return block + (text or "")
    # sustituye el bloque model: (hasta la próxima clave de nivel 0) por el nuevo.
    # OJO: (?m) SIN DOTALL — si no, «.*» se comería las secciones siguientes.
    return _re.sub(r"(?m)^model:[ \t]*\n(?:[ \t]+[^\n]*\n?)*", block, text, count=1)


def configure_brain(ctx, provider: str, model: str, api_key: str) -> dict:
    """Deja el CEREBRO de Hermes operativo: escribe la clave del proveedor en
    ~/.hermes/.env (con backup) y el modelo/proveedor en ~/.hermes/config.yaml.
    Guarda también la elección en los settings de nexus. Devuelve un resumen."""
    import io
    import os
    provider = (provider or "").strip().lower()
    m = _PROV_MAP.get(provider)
    if not m:
        return {"ok": False, "error": f"proveedor no soportado: {provider}"}
    changes = []
    # 1) settings de nexus (para la UI y para saber qué modelo pedimos)
    try:
        ctx["settings"].set("hermes_provider", provider)
        if model:
            ctx["settings"].set("hermes_model", model)
    except Exception:
        pass
    # 2) clave del proveedor en ~/.hermes/.env (lo que arregla el 401)
    key = (api_key or "").strip()
    env_path = _hermes_env_path()
    try:
        old = io.open(env_path, encoding="utf-8", errors="replace").read() if os.path.exists(env_path) else ""
    except Exception:
        old = ""
    if key:
        new_env = _env_set_var(old, m["env"], key)
        try:
            os.makedirs(os.path.dirname(env_path), exist_ok=True)
            if old:
                io.open(env_path + ".bak_nexus", "w", encoding="utf-8").write(old)
            io.open(env_path, "w", encoding="utf-8", newline="\n").write(new_env)
            changes.append(f"{m['env']} escrita en ~/.hermes/.env")
        except Exception as exc:
            return {"ok": False, "error": f"no pude escribir el .env de Hermes: {exc}"}
        # 2b) persistir la clave en los SECRETS de nexus (config/secrets.json) para que
        #     la UI marque «conectada ✓»: has_<provider>_api_key pasa a true. Si no lo
        #     guardábamos aquí, la clave vivía SOLO en ~/.hermes/.env y el HUD nunca
        #     se enteraba de que ya estaba puesta → parecía que «no se guardaba».
        try:
            ctx["settings"].set_secret(m["secret"], key)
            changes.append(f"clave recordada en nexus ({m['secret']})")
        except Exception:
            pass
    # 3) modelo + provider en ~/.hermes/config.yaml
    cfg_path = _hermes_config_path()
    if model:
        try:
            oldc = io.open(cfg_path, encoding="utf-8", errors="replace").read() if os.path.exists(cfg_path) else ""
            newc = _yaml_set_model(oldc, m["hp"], model, m["base"])
            os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
            if oldc:
                io.open(cfg_path + ".bak_nexus", "w", encoding="utf-8").write(oldc)
            io.open(cfg_path, "w", encoding="utf-8", newline="\n").write(newc)
            changes.append(f"modelo «{model}» (provider {m['hp']}) en config.yaml")
        except Exception as exc:
            changes.append(f"(no pude escribir config.yaml: {exc}; la clave sí quedó puesta)")
    _ALIVE.update(ok=False, ts=0.0)          # forzar recomprobación
    return {"ok": True, "provider": provider, "model": model,
            "hermes_provider": m["hp"], "changes": changes,
            "note": "Reinicia el gateway de Hermes para que cargue el modelo nuevo: "
                    "dilo con «arranca hermes» o yo lo relanzo en el próximo encargo."}


# ============= ENGANCHAR HERMES A ENGRAM (memoria de proyecto por MCP) =============
# nexus y Hermes comparten la MISMA memoria de proyecto (Engram).
# nexus la usa por HTTP (backend/core/engram_bridge.py); a Hermes lo enganchamos por
# su vía nativa: un servidor MCP 'engram' en ~/.hermes/config.yaml que arranca
# «engram mcp --project nexus» por stdio. Así Hermes obtiene las tools mem_save/
# mem_search/mem_context sobre la MISMA base (~/.engram, proyecto «nexus») — lo que
# él decide/averigua queda en la memoria de proyecto, y ve lo que decidió nexus.
# nexus deja esa config él solo (como ya provisiona el .env y el modelo de Hermes).
def _strip_bom(text: str) -> str:
    """Quita un BOM UTF-8 inicial si lo hay (leemos con utf-8 normal, así que un
    fichero con BOM llega como «\\ufeffmcp_servers:…» y rompería el anclaje ^)."""
    return text[1:] if text and text[0] == chr(0xFEFF) else text


def _has_mcp_engram(text: str) -> bool:
    """PURA: ¿hay un servidor 'engram' como HIJO DIRECTO de mcp_servers? (no vale
    un «engram:» anidado más profundo — p.ej. dentro del env: de otro server)."""
    import re as _re
    lines = _strip_bom(text or "").splitlines()
    ms = None
    for k, ln in enumerate(lines):
        r = ln.rstrip()
        if _re.match(r"^mcp_servers\s*:\s*(#.*)?$", r):     # forma bloque
            ms = k
            break
        if _re.match(r"^mcp_servers\s*:", r):               # {} vacío o inline: sin hijos de bloque
            return False
    if ms is None:
        return False
    child_indent = None
    for ln in lines[ms + 1:]:
        s = ln.strip()
        if s == "" or s.startswith("#"):                    # blanco o comentario: NUNCA cierra el bloque
            continue
        indent = len(ln) - len(ln.lstrip(" \t"))
        if indent == 0:                                     # línea de contenido a nivel 0: fin del bloque
            break
        if child_indent is None:
            child_indent = indent                           # 1er hijo fija la indentación de servidor
        if indent == child_indent and _re.match(r"engram\s*:", ln.lstrip()):
            return True
    return False


def _yaml_add_mcp_engram(text: str, engram_cmd: str, project: str = "nexus") -> tuple:
    """PURA (testeable): asegura un servidor MCP 'engram' bajo `mcp_servers:` que
    arranca «<engram_cmd> mcp --project <project>» por stdio. Devuelve (texto, cambió).
    Cirugía de texto SIN PyYAML (no reordena ni borra comentarios del resto del
    fichero, igual que _yaml_set_model). Idempotente: si ya está, cambió=False.
    Robusto: respeta la indentación REAL de los hijos de mcp_servers (2, 4, tabs…)
    para NO absorber servidores existentes; quita BOM; y si mcp_servers está en un
    formato inline no editable, NO toca nada en vez de arriesgarse a corromper YAML."""
    import re as _re
    raw = text or ""
    txt = _strip_bom(raw)
    if _has_mcp_engram(txt):
        return raw, False
    lines = txt.splitlines()
    ms_idx, form = None, None
    for i, ln in enumerate(lines):
        r = ln.rstrip()
        if _re.match(r"^mcp_servers\s*:\s*(#.*)?$", r):
            ms_idx, form = i, "block"
            break
        if _re.match(r"^mcp_servers\s*:\s*\{\s*\}\s*(#.*)?$", r):
            ms_idx, form = i, "empty_flow"
            break
        if _re.match(r"^mcp_servers\s*:\s*\S", r):          # inline no editable (p.ej. {a: b})
            return raw, False
    # indentación con la que insertar el server engram (igual que sus hermanos)
    child_indent = 2
    if form == "block":
        for ln in lines[ms_idx + 1:]:
            s = ln.strip()
            if s == "" or s.startswith("#"):                # blanco o comentario: NO cierra el bloque
                continue
            lead = ln[:len(ln) - len(ln.lstrip(" \t"))]
            if lead == "":                                  # línea de contenido a nivel 0: fin del bloque
                break
            if "\t" in lead:
                # el bloque usa TABS para indentar (YAML inválido de origen, Hermes
                # no lo cargaría): no lo edito, para no mezclar tabs y espacios.
                return raw, False
            child_indent = len(lead)
            break
    ci = " " * child_indent
    pi = " " * (child_indent + 2)
    # command en comillas SIMPLES: en YAML respetan las barras de Windows tal cual
    # (dobles comillas interpretarían \U, \b… como escapes → ruta rota).
    cmd_q = "'" + str(engram_cmd).replace("'", "''") + "'"
    child = [f"{ci}engram:",
             f"{pi}command: {cmd_q}",
             f'{pi}args: ["mcp", "--project", "{project}"]',
             f"{pi}enabled: true"]
    if ms_idx is None:
        new_lines = lines + ["mcp_servers:"] + child
    elif form == "empty_flow":
        new_lines = lines[:ms_idx] + ["mcp_servers:"] + child + lines[ms_idx + 1:]
    else:                                                   # bloque: conserva la cabecera (y su comentario) e inserta debajo
        new_lines = lines[:ms_idx + 1] + child + lines[ms_idx + 1:]
    new = "\n".join(new_lines)
    return (new if new.endswith("\n") else new + "\n"), True


def provision_engram_mcp(ctx) -> tuple:
    """Deja en ~/.hermes/config.yaml el servidor MCP 'engram' (stdio) para que
    HERMES comparta la memoria de proyecto de nexus. Solo actúa si el binario de
    engram está instalado (si no, no configura un MCP que no existe → rompería el
    arranque de servidores MCP de Hermes). Best-effort: NUNCA lanza. Devuelve
    (cambió, detalle)."""
    import io
    import os
    try:
        from backend.core import engram_bridge as eng
    except Exception as exc:                                   # noqa: BLE001
        return False, f"no pude importar engram_bridge: {exc}"
    try:
        if not eng.installed(ctx):
            return False, "engram no está instalado; no configuro su MCP en Hermes"
        exe = eng._engram_exe(ctx)
        path = _hermes_config_path()
        exists = os.path.exists(path)
        if exists:
            try:
                old = io.open(path, encoding="utf-8", errors="replace").read()
            except Exception as exc:
                # EXISTE pero no puedo leerlo (lock de Windows, antivirus, permiso
                # transitorio): NO lo toco. Sobrescribir a ciegas borraría la config
                # real de Hermes (modelo, otros servers MCP) sin vuelta atrás.
                return False, f"no pude leer {path} ({type(exc).__name__}); lo dejo intacto"
        else:
            old = ""
        if _has_mcp_engram(old):
            return False, "Hermes ya tenía el MCP de engram configurado"
        new, changed = _yaml_add_mcp_engram(old, exe, eng.PROJECT)
        if not changed:
            return False, ("no pude añadir el MCP de engram (mcp_servers está en un "
                           "formato que no edito por seguridad); añádelo a mano")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Backup SIEMPRE que ya existiera un fichero (aunque viniera vacío): si no
        # consigo respaldarlo, NO escribo — sin backup no hay marcha atrás.
        if exists:
            try:
                io.open(path + ".bak_nexus", "w", encoding="utf-8").write(old)
            except Exception as exc:
                return False, f"no pude respaldar {path} ({type(exc).__name__}); no lo sobrescribo"
        io.open(path, "w", encoding="utf-8", newline="\n").write(new)
        return True, (f"añadido el servidor MCP 'engram' a ~/.hermes/config.yaml "
                      f"(«engram mcp --project {eng.PROJECT}»)")
    except Exception as exc:                                   # noqa: BLE001
        return False, f"no pude provisionar el MCP de engram en Hermes: {exc}"


def _gateway_log():
    from backend.core.config import DATA_DIR
    return DATA_DIR / "hermes_gateway.log"


def _gateway_log_tail(n: int = 12) -> str:
    try:
        lines = _gateway_log().read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except Exception:
        return ""


async def diagnose(ctx) -> dict:
    """Radiografía COMPLETA de la conexión con Hermes — para responder con
    CAUSAS, no con el eterno «está apagado»."""
    import asyncio as _a
    import io
    import os
    url, hdr = _cfg(ctx)
    exe = _hermes_exe(ctx)
    env_path = _hermes_env_path()
    envv = await _a.to_thread(_read_env_file, env_path)
    env_key = envv.get("API_SERVER_KEY", "")
    enabled = envv.get("API_SERVER_ENABLED", "").lower() in ("1", "true", "yes", "on")
    wab_key = ctx["settings"].secret("hermes_api_key")
    port = await _port_open(url)
    health = await _alive(url, hdr) if port else False
    auth = await _auth_ok(url, hdr) if health else False
    jobs = _reg_load()
    # Engram (memoria de proyecto compartida con nexus): ¿está engram instalado y
    # enganchado a Hermes por MCP en su config.yaml?
    engram_installed, engram_mcp = False, False
    try:
        from backend.core import engram_bridge as _eng
        engram_installed = _eng.installed(ctx)
        cfg_path = _hermes_config_path()

        def _read_cfg():
            return io.open(cfg_path, encoding="utf-8", errors="replace").read() \
                if os.path.exists(cfg_path) else ""
        engram_mcp = _has_mcp_engram(await _a.to_thread(_read_cfg))
    except Exception:
        pass
    return {"url": url, "exe": exe, "installed": bool(exe),
            "env_path": env_path, "env_exists": os.path.exists(env_path),
            "api_enabled": enabled, "key_in_env": bool(env_key),
            "key_strong": _key_strong(env_key),
            "keys_match": bool(env_key) and env_key == wab_key,
            "port_open": port, "health": health, "auth_ok": auth,
            "engram_installed": engram_installed, "engram_mcp": engram_mcp,
            "pythonpath": os.environ.get("PYTHONPATH", ""),
            "jobs": jobs[-6:], "log_tail": _gateway_log_tail(6)}


_LAUNCH = {"ts": 0.0}
_LAST = {"err": ""}


def _win_hidden_kw() -> dict:
    """kwargs para Popen que EVITAN cualquier ventana de consola en Windows al
    lanzar el gateway. CREATE_NO_WINDOW ya oculta la consola del proceso; añadimos
    un STARTUPINFO con SW_HIDE por si el ejecutable intentase mostrar una ventana.
    NO usamos DETACHED_PROCESS: con un .exe de consola, «detached» hace que el hijo
    cree su PROPIA consola VISIBLE — justo el CMD que saltaba al guardar la clave.
    Con CREATE_NO_WINDOW el gateway sigue en su propia consola OCULTA y sobrevive
    aunque nexus se cierre."""
    import subprocess
    import sys
    if sys.platform != "win32":
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    si.wShowWindow = 0  # SW_HIDE
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
            "startupinfo": si}


async def ensure_up(ctx, force: bool = False) -> bool:
    """Garantiza que el gateway de Hermes está EN MARCHA con su API utilizable.
    1) Si /health ya responde y la clave vale → listo (salvo force=True).
    2) Provisiona ~/.hermes/.env (API_SERVER_ENABLED + clave fuerte) si hace falta.
    3) Lanza «hermes gateway run --replace» con ENTORNO LIMPIO (_clean_env: sin el
       PYTHONPATH/VIRTUAL_ENV de nexus, que le rompía el agente con 500) y su
       salida a data/hermes_gateway.log; espera hasta ~60 s a que /health conteste.
    force=True: relanza AUNQUE /health responda — para sustituir un gateway
    envenenado (arrancado con el entorno sucio) o con la clave vieja."""
    import asyncio as _a
    import subprocess
    import sys
    import time as _t
    url, hdr = _cfg(ctx)
    # ENGRAM: deja a Hermes enganchado a la MISMA memoria de proyecto que usa nexus
    # (servidor MCP 'engram' en su config.yaml). Se hace ANTES del early-return por
    # /health para que también un Hermes YA arrancado quede con la config en disco
    # (la cargará en el próximo (re)arranque; en arranque en frío entra ya lista).
    # Best-effort, en un hilo (I/O); si engram no está instalado, no toca nada.
    try:
        eng_changed, eng_detail = await _a.to_thread(provision_engram_mcp, ctx)
        if eng_changed:
            from backend.core.events import bus
            await bus.emit("log", {"level": "info",
                                   "msg": "🧠🪽 Hermes enganchado a Engram: " + eng_detail
                                          + " (activo tras (re)arrancar su gateway)."})
    except Exception:
        pass
    changed = False
    if not force and await _alive(url, hdr):
        if await _auth_ok(url, hdr):
            _ALIVE.update(ok=True, ts=_t.monotonic())
            return True
        # vivo pero con OTRA clave → provisionar y reiniciar con --replace
        changed, _acts = await _a.to_thread(provision_env, ctx)
        url, hdr = _cfg(ctx)
    if not ctx["settings"].get("hermes_autostart", True):
        _LAST["err"] = "hermes_autostart está desactivado en ⚙"
        return False
    exe = _hermes_exe(ctx)
    if not exe:
        _LAST["err"] = ("no encuentro hermes.exe (ni en ⚙ hermes_exe ni en "
                        "%LOCALAPPDATA%\\hermes\\hermes-agent\\venv\\Scripts)")
        return False
    if not changed:
        changed, _acts = await _a.to_thread(provision_env, ctx)
        url, hdr = _cfg(ctx)
    # no relanzar en ráfaga: si acabamos de lanzarlo, solo esperar (force lo salta)
    proc = None
    if force or _t.monotonic() - _LAUNCH["ts"] > 45:
        _LAUNCH["ts"] = _t.monotonic()
        try:
            logf = open(_gateway_log(), "ab")
            logf.write(("\n===== lanzamiento " + time.strftime("%Y-%m-%d %H:%M:%S")
                        + (" (force)" if force else "") + " =====\n").encode("utf-8"))
            # «run --replace»: si había un gateway viejo (env sucio o .env antiguo),
            # lo sustituye — así los cambios entran SIEMPRE. Sin ventana de consola
            # (CREATE_NO_WINDOW + SW_HIDE) → ya no salta el CMD al guardar la clave.
            proc = subprocess.Popen([exe, "gateway", "run", "--replace"],
                                    stdout=logf, stderr=logf,
                                    stdin=subprocess.DEVNULL, close_fds=True,
                                    env=_clean_env(), **_win_hidden_kw())
            from backend.core.events import bus
            await bus.emit("log", {"level": "info",
                                   "msg": "🪽 Arrancando el gateway de Hermes con entorno limpio "
                                          "(log en data/hermes_gateway.log)…"})
        except Exception as exc:
            _LAST["err"] = f"no pude lanzar el gateway: {type(exc).__name__}: {exc}"
            return False
    for i in range(60):                      # ~60 s de margen a que levante
        await _a.sleep(1.0)
        if await _alive(url, hdr):
            _ALIVE.update(ok=True, ts=_t.monotonic())
            return True
        # si el proceso murió nada más nacer (p. ej. CLI viejo sin «run --replace»),
        # reintenta UNA vez con el comando pelado.
        if proc is not None and i == 6 and proc.poll() is not None:
            try:
                logf2 = open(_gateway_log(), "ab")
                proc = subprocess.Popen([exe, "gateway"],
                                        stdout=logf2, stderr=logf2,
                                        stdin=subprocess.DEVNULL, close_fds=True,
                                        env=_clean_env(), **_win_hidden_kw())
            except Exception:
                pass
    tail = _gateway_log_tail(8)
    _LAST["err"] = ("el gateway no ha abierto su API en 60 s"
                    + (f". Últimas líneas de su log:\n{tail}" if tail else ""))
    return False


# Mensaje CLARO cuando el 401 NO es de nuestra clave al gateway, sino del proveedor
# LLM que Hermes usa POR DENTRO para pensar (su "cerebro" sin credenciales). Es lo que
# significa «Missing Authentication header»: viene del upstream, no de nexus.
_UPSTREAM_AUTH_MSG = (
    "Hermes SÍ se conecta conmigo (tu clave del gateway es correcta), pero su MODELO DE "
    "IA interno no tiene credenciales para funcionar. El error «Missing Authentication "
    "header» lo devuelve el proveedor LLM que Hermes usa por dentro, NO nexus — yo ya le "
    "entrego el encargo autenticado. Arréglalo en el propio Hermes: abre una terminal y "
    "ejecuta «hermes model» (elige proveedor y modelo) y «hermes auth add <proveedor>» con "
    "tu API key (OpenAI / OpenRouter / Nous), o «hermes setup». Cuando Hermes tenga su "
    "modelo con clave, el encargo funcionará sin tocar nada más.")


def _is_upstream_auth_error(status: int, body: str) -> bool:
    """¿El 401/403 es del proveedor LLM interno de Hermes (sin credenciales) y NO de
    nuestra clave al gateway? El gateway propio responde «invalid_api_key»; el upstream,
    «Missing Authentication header» u otros mensajes del proveedor."""
    low = (body or "").lower()
    if status not in (401, 403):
        return False
    if "invalid_api_key" in low or "invalid api key" in low:
        return False           # eso es NUESTRA clave al gateway → re-provisionar
    return True                # cualquier otro 401/403 = el cerebro de Hermes sin creds


# Hermes puede responder 200 con un error del proveedor DENTRO del texto («HTTP 400:
# Your organization must be verified…»). Sin este reconocimiento, un encargo fallido
# se cantaría como terminado.
_RESPUESTA_ES_ERROR = re.compile(
    r"^\s*HTTP\s+[45]\d\d\b"
    r"|\bmust\s+be\s+verified\b"
    r"|\binvalid_api_key\b|\bincorrect\s+api\s+key\b"
    r"|\binsufficient_quota\b|\brate[_\s]limit\b"
    r"|\bmissing\s+authentication\b"
    r"|\b(?:error|failed)\s*:\s*\{?\s*[\"']?(?:type|code|message)[\"']?\s*:",
    re.IGNORECASE)


def respuesta_es_error(texto: str) -> str:
    """'' si la respuesta es buena; si no, el motivo en una línea."""
    t = (texto or "").strip()
    if not t:
        return "Hermes cerró el encargo sin devolver nada"
    m = _RESPUESTA_ES_ERROR.search(t[:400])
    return t[:200].replace("\n", " ") if m else ""


async def _run_hermes(orden: str, url: str, hdr: dict, channel: str, jid: str = "", num: int = 0) -> dict:
    """El encargo de verdad (puede tardar MINUTOS): corre como job en 2º plano.
    - 5xx (gateway envenenado por PYTHONPATH) → relanza limpio y reintenta 1 vez.
    - 401 «invalid_api_key» (nuestra clave al gateway) → re-provisiona y reintenta 1 vez.
    - 401 «Missing Authentication header» (el MODELO interno de Hermes sin credenciales)
      → mensaje claro y accionable; reintentar no sirve, es config del propio Hermes."""
    import asyncio as _a
    import httpx
    from backend.core.events import bus
    error = False
    _intentos = [0]
    try:
        # ARRANQUE BAJO DEMANDA: si el gateway está apagado, nexus lo levanta él
        # solo y espera a que esté listo antes de entregar el encargo.
        if not await ensure_up({"settings": _SETTINGS[0]}):
            raise RuntimeError(_LAST["err"] or
                               "no pude arrancar/alcanzar el gateway de Hermes en " + url)
        if jid:
            _reg_set(jid, estado="trabajando")
        out = None
        for intento in (1, 2):
            _intentos[0] = intento
            url2, hdr2 = _cfg({"settings": _SETTINGS[0]})   # la clave puede haberse re-provisionado
            async with httpx.AsyncClient(timeout=900) as cli:
                r = await cli.post(f"{url2}/v1/chat/completions", headers=hdr2,
                                   json={"model": "hermes-agent",
                                         "messages": [{"role": "user", "content": orden}]})
            if r.status_code < 400:
                out = (r.json().get("choices") or [{}])[0].get("message", {}).get("content", "")
                out = out or "He terminado, pero sin texto de respuesta."
                break
            detalle = (r.text or "")[:400]
            # 401/403 del CEREBRO interno de Hermes (sin credenciales) → mensaje claro, sin reintento
            if _is_upstream_auth_error(r.status_code, detalle):
                raise RuntimeError(_UPSTREAM_AUTH_MSG)
            if intento == 1 and r.status_code >= 500:
                await bus.emit("log", {"level": "warn",
                               "msg": f"🪽 Hermes devolvió {r.status_code}; relanzo su gateway "
                                      "con entorno limpio y reintento el encargo…"})
                if await ensure_up({"settings": _SETTINGS[0]}, force=True):
                    continue
            if intento == 1 and r.status_code in (401, 403):
                # nuestra clave al gateway no vale → re-provisionar y reintentar 1 vez
                await bus.emit("log", {"level": "warn",
                               "msg": "🪽 Hermes rechaza mi clave del gateway; re-provisiono y reintento…"})
                await _a.to_thread(provision_env, {"settings": _SETTINGS[0]})
                if await ensure_up({"settings": _SETTINGS[0]}, force=True):
                    continue
            raise RuntimeError(f"Hermes devolvió HTTP {r.status_code}: {detalle}")
        motivo = respuesta_es_error(out)
        if motivo:
            # el gateway respondió 200 pero el contenido ES un error: NO es «hecho»
            raise RuntimeError(motivo)
        if jid:
            _reg_set(jid, estado="hecho", resultado=out[:4000], t1=time.time())
    except Exception as exc:                                   # noqa: BLE001
        error = True
        out = (f"{type(exc).__name__}: {exc}. "
               "Mira data/hermes_gateway.log o dime «diagnostica hermes».")
        if jid:
            _reg_set(jid, estado="error", resultado=str(exc)[:500], t1=time.time())
    tag = f" #{num}" if num else ""
    # v23 (T8): la respuesta final dice SIEMPRE en qué estado acabó — terminado,
    # fallido o incompleto. Nada de dar por bueno lo que no se ha verificado.
    from backend.core import publicvoice as pv
    if error:
        # Un único mensaje FUNCIONAL: el detalle técnico se queda en el log.
        reply = pv.mensaje_fallo(out, intentos=_intentos[0])
        await bus.emit("log", {"level": "error",
                               "msg": f"[trabajo {tag or ''}] {out[:400]}"})
    elif not (out or "").strip():
        reply = (f"No he podido terminar «{orden[:70]}». No lo doy por hecho ni he "
                 "cambiado nada.")
    else:
        reply = f"Ya lo tengo{tag} — «{orden[:80]}»:\n\n" + out[:3500]
    # PUENTE DE MEMORIA: lo que Hermes averigua queda TAMBIÉN en la memoria de
    # nexus (Postgres) — nexus es el hub y su memoria, la fuente de verdad.
    try:
        import asyncio as _a
        from backend.core.memory import pg
        # El PREFIJO va neutro a propósito: esto se recupera con «qué recuerdas
        # de X» y se le enseña al operador tal cual. Quién ejecutó el encargo ya
        # queda marcado en `kind="hermes"`, que es interno y no se pinta nunca.
        await _a.to_thread(pg.remember, f"[Trabajo] {orden} => {out[:600]}", "hermes")
    except Exception:
        pass
    # La notificación de fin la publica el GESTOR DE TRABAJOS (notify=True en el
    # submit), no esta función: así el aviso es único y está garantizado.
    if error:
        raise RuntimeError(out[:300])          # que el trabajo conste como FALLIDO
    return {"reply": reply}


# ---------------- respuestas de estado (SIN bucles de frase fija) ----------------
# Resumen de respaldo para cuando su API no contesta: se anuncia como lo que es
# (la documentación del producto), no como una consulta en vivo.
_BASE_CAPS = ("Según su documentación: navegar y automatizar el navegador (con visión), "
              "investigar en profundidad, ejecutar código aislado (local/Docker/SSH), "
              "generar imágenes, memoria propia, subagentes y skills que se auto-genera.")


def _down_reason(d: dict) -> str:
    """La CAUSA concreta de que no haya conexión, en una frase (nada de «apagado» a secas)."""
    if not d["installed"]:
        return ("no encuentro Hermes instalado en este PC (ni ⚙ hermes_exe ni la ruta "
                "por defecto). Instálalo desde hermes-agent.nousresearch.com")
    if d["port_open"] and not d["health"]:
        return (f"hay algo escuchando en {d['url']} pero no contesta al /health — "
                "puede ser otro programa en ese puerto o un gateway a medio arrancar")
    if not d["api_enabled"] or not d["key_strong"]:
        return ("su gateway no tiene el API server activo: en ~/.hermes/.env faltaba "
                "API_SERVER_ENABLED=true o una API_SERVER_KEY fuerte (Hermes se NIEGA "
                "a abrir el puerto con clave débil). Lo dejo provisionado al arrancarlo")
    return "su gateway no está en marcha ahora mismo"


async def _que_sabe(ctx) -> dict:
    """«¿Qué sabe hacer Hermes?» → se lo PREGUNTAMOS a su API en vivo
    (/v1/capabilities y /v1/skills); si está apagado, resumen honesto CON causa."""
    import httpx
    url, hdr = _cfg(ctx)
    if not await _alive(url, hdr):
        d = await diagnose(ctx)
        return {"reply": "🪽 Ahora mismo no tengo línea con Hermes: " + _down_reason(d) +
                         ". " + _BASE_CAPS + " Di «arranca hermes» y lo levanto yo, o "
                         "encárgale algo directamente («hermes: …») y lo arranco de paso."}
    partes = []
    try:
        async with httpx.AsyncClient(timeout=8) as cli:
            r = await cli.get(f"{url}/v1/capabilities", headers=hdr)
            if r.status_code == 200:
                caps = r.json()
                ks = caps.get("capabilities") if isinstance(caps, dict) else caps
                if isinstance(ks, dict):
                    ks = list(ks.keys())
                if isinstance(ks, list) and ks:
                    partes.append("Capacidades: " + ", ".join(str(k) for k in ks[:14]))
            r2 = await cli.get(f"{url}/v1/skills", headers=hdr)
            if r2.status_code == 200:
                sk = r2.json()
                items = sk if isinstance(sk, list) else (sk.get("skills") or [])
                names = [str(x.get("name", x)) if isinstance(x, dict) else str(x) for x in items]
                if names:
                    partes.append("Skills instaladas: " + ", ".join(names[:16]))
    except Exception:
        pass
    if not partes:
        partes = ["Está vivo pero no expone el detalle por API. " + _BASE_CAPS]
    return {"reply": "🪽 Hermes ahora mismo (conectado ✔):\n" + "\n".join(partes) +
                     "\nEncárgale algo: di «hermes: …» y te traigo el resultado sin que esperes."}


async def _probe_brain(ctx) -> tuple[str, str]:
    """Prueba REAL del cerebro de Hermes: le manda un «ping» mínimo. Distingue
    el gateway (mi clave) del MODELO INTERNO sin credenciales (el 401 «Missing
    Authentication header»). Devuelve (estado, detalle). Timeout corto: el fallo
    de credenciales es INSTANTÁNEO (no hay inferencia)."""
    import httpx
    url, hdr = _cfg(ctx)
    try:
        async with httpx.AsyncClient(timeout=25) as cli:
            r = await cli.post(f"{url}/v1/chat/completions", headers=hdr,
                               json={"model": "hermes-agent", "max_tokens": 1,
                                     "messages": [{"role": "user", "content": "ping"}]})
        if r.status_code < 400:
            return "ok", ""
        body = (r.text or "")[:300]
        if _is_upstream_auth_error(r.status_code, body):
            return "no_brain", body
        if r.status_code in (401, 403):
            return "gateway_key", body
        return "error", f"HTTP {r.status_code}: {body}"
    except httpx.ReadTimeout:
        return "slow", "el modelo tardó >25 s en el ping (parece configurado pero lento)"
    except Exception as exc:                                    # noqa: BLE001
        return "down", f"{type(exc).__name__}: {exc}"


async def _estado(ctx) -> dict:
    d = await diagnose(ctx)
    ok = d["health"]
    lines = []
    if ok:
        lines.append(f"✔ CONECTADO — su API contesta en {d['url']}"
                     + ("" if d["auth_ok"] else
                        " (⚠ pero mi clave no le vale: di «arranca hermes» y la re-sincronizo)"))
        # PRUEBA DEL CEREBRO: ¿tiene Hermes un modelo con credenciales para pensar?
        estado_cerebro, detalle_c = await _probe_brain(ctx)
        if estado_cerebro == "ok":
            lines.append("· Cerebro (modelo interno): ✔ responde — listo para encargos.")
        elif estado_cerebro == "slow":
            lines.append("· Cerebro (modelo interno): ⏳ responde pero lento; parece configurado.")
        elif estado_cerebro == "no_brain":
            lines.append("· Cerebro (modelo interno): ✖ SIN CREDENCIALES. Este es el fallo real: "
                         "Hermes se conecta conmigo pero su modelo de IA no tiene clave "
                         "(«Missing Authentication header» = del proveedor LLM, no de nexus). "
                         "Configúralo en Hermes: «hermes model» + «hermes auth add <proveedor>» "
                         "con tu API key, o «hermes setup». Yo ya le entrego el encargo autenticado.")
        elif estado_cerebro == "gateway_key":
            lines.append("· Cerebro: ⚠ mi clave del gateway ha dejado de valer; di «arranca hermes» "
                         "y la re-sincronizo.")
        else:
            lines.append(f"· Cerebro (modelo interno): ✖ {detalle_c}")
    else:
        lines.append("✖ SIN CONEXIÓN — " + _down_reason(d))
    lines.append("· Instalación: " + (("✔ " + d["exe"]) if d["installed"] else "✖ no encontrada"))
    lines.append("· Config (~/.hermes/.env): "
                 + ("✔ API activada y clave fuerte" if (d["api_enabled"] and d["key_strong"])
                    else "✖ incompleta — la provisiono yo al arrancarlo")
                 + ("" if d["keys_match"] or not d["key_in_env"] else " (⚠ clave distinta a la mía)"))
    lines.append(f"· Puerto {d['url'].rsplit(':', 1)[-1]}: {'abierto' if d['port_open'] else 'cerrado'}")
    # Engram: memoria de proyecto compartida entre nexus y Hermes
    if d.get("engram_installed"):
        lines.append("· Engram (memoria de proyecto): "
                     + ("✔ enganchado por MCP — Hermes comparte memoria de proyecto con nexus"
                        if d.get("engram_mcp") else
                        "engram instalado pero aún sin enganchar a Hermes; lo dejo configurado "
                        "en su config.yaml la próxima vez que lo arranque"))
    else:
        lines.append("· Engram (memoria de proyecto): — no instalado (opcional; si lo instalas, "
                     "engancho a Hermes solo)")
    jobs = d.get("jobs") or []
    if jobs:
        j = jobs[-1]
        eta = _fmt_age(time.time() - j.get("t0", time.time()))
        est = j.get("estado", "?")
        ntag = f"#{j['num']} " if j.get("num") else ""
        lines.append(f"· Último encargo: {ntag}«{j.get('orden', '')[:80]}» → {est} (hace {eta})")
    if d.get("pythonpath"):
        lines.append("⚠ Tu sistema tiene PYTHONPATH=" + d["pythonpath"][:120] + " — eso "
                     "contamina cualquier Python que se abra (incluido el Hermes de "
                     "escritorio). Yo ya lanzo su gateway con entorno limpio, pero si no "
                     "sabes quién lo puso, bórralo: reg delete \"HKCU\\Environment\" "
                     "/v PYTHONPATH /f (y cierra sesión de Windows).")
    if not ok and d["installed"]:
        lines.append("Di «arranca hermes» y lo levanto ahora mismo.")
    return {"reply": "🪽 Estado de Hermes:\n" + "\n".join(lines)}


async def _arranca(ctx) -> dict:
    url, hdr = _cfg(ctx)
    if await _alive(url, hdr) and await _auth_ok(url, hdr):
        return {"reply": f"🪽 Hermes ya estaba en marcha y me responde en {url}. "
                         "Encárgale algo: «hermes: investiga X y hazme un informe»."}
    from backend.core.events import bus
    await bus.emit("log", {"level": "info", "msg": "🪽 Orden recibida: levantar Hermes"})
    t0 = time.time()
    ok = await ensure_up(ctx)
    if ok:
        return {"reply": f"🪽 Hecho: gateway de Hermes ARRIBA y con la API respondiendo "
                         f"(ha tardado {_fmt_age(time.time() - t0)}). Ya puedes encargarle "
                         "trabajo: «hermes: …»."}
    d = await diagnose(ctx)
    return {"reply": "🪽 No he podido dejarlo operativo: " + (_LAST["err"] or _down_reason(d)) +
                     "\nDime «diagnostica hermes» para ver la radiografía completa."}


async def _resultado(ctx, text: str = "") -> dict:
    items = _reg_load()
    if not items:
        return {"reply": "🪽 No tengo encargos a Hermes apuntados todavía (quedan registrados "
                         "en data/hermes_jobs.json). Mándale uno: di «hermes: investiga X y "
                         "hazme un informe» — cuando termine te lo canto y queda guardado aquí."}
    m = re.search(r"(?:encargo|tarea|trabajo|n[uú]mero)\s*#?\s*(\d+)|#(\d+)", text or "")
    want = int(m.group(1) or m.group(2)) if m else None
    # Sin número concreto, SOLO el último encargo con detalle; los anteriores van
    # resumidos en una línea al final.
    pick = [j for j in items if int(j.get("num") or 0) == want] if want else items[-1:]
    if want is not None and not pick:
        return {"reply": f"🪽 No tengo ningún encargo #{want} apuntado. Di «¿y la respuesta "
                         "de hermes?» y te enseño los últimos."}
    out = []
    for j in reversed(pick):
        est = j.get("estado", "?")
        ntag = f"#{j['num']} " if j.get("num") else ""
        orden = j.get("orden", "")[:90]
        if est == "hecho":
            res = (j.get("resultado") or "").strip()
            out.append(f"✔ {ntag}«{orden}» (terminado hace "
                       f"{_fmt_age(time.time() - (j.get('t1') or time.time()))}):\n{res[:1200]}")
        elif est == "error":
            det = " ".join((j.get("resultado", "") or "").split())[:160]
            out.append(f"✖ {ntag}«{orden}» FALLÓ: {det}")
        elif est == "trabajando":
            out.append(f"⏳ {ntag}«{orden}» — Hermes lleva "
                       f"{_fmt_age(time.time() - j.get('t0', time.time()))} con ello; te aviso al terminar.")
        else:
            out.append(f"📨 {ntag}«{orden}» — encargado hace "
                       f"{_fmt_age(time.time() - j.get('t0', time.time()))}, aún arrancando.")
    cabecera = (f"🪽 Encargo #{want}:" if want else "🪽 Tu último encargo a Hermes:")
    resto = [j for j in items if j not in pick][-4:]
    if not want and resto:
        _ic = {"hecho": "✔", "error": "✖", "trabajando": "⏳"}
        cola = ", ".join(f"{_ic.get(j.get('estado'), '📨')} #{j.get('num')}"
                         for j in reversed(resto))
        out.append(f"(Antes: {cola}. Di «resultado del encargo N» para ver uno.)")
    return {"reply": cabecera + "\n\n" + "\n\n".join(out)}


# specs v24 (T18): estos intents son DIAGNÓSTICO — el operador los pide a
# propósito, así que pueden enseñar el detalle técnico. Se marcan admin=True y el
# bus de eventos no los sanea. Todo lo demás va por la voz pública.
_ADMIN = ("hermes_estado", "hermes_arranca", "hermes_info")


async def handle(intent: str, text: str, match, ctx) -> dict:
    if intent in _ADMIN:
        r = await _handle_admin(intent, text, match, ctx)
        r["admin"] = True
        return r
    return await _handle_publico(intent, text, match, ctx)


async def _handle_admin(intent: str, text: str, match, ctx) -> dict:
    if intent == "hermes_info":
        return await _que_sabe(ctx)
    if intent == "hermes_estado":
        return await _estado(ctx)
    if intent == "hermes_arranca":
        return await _arranca(ctx)
    return {"reply": "Esa orden de diagnóstico no la tengo."}


async def _handle_publico(intent: str, text: str, match, ctx) -> dict:
    if intent == "hermes_resultado":
        return await _resultado(ctx, text)
    orden = ""
    for g in ("orden", "orden2", "orden3", "orden4", "orden5"):
        try:
            orden = (match.group(g) or "").strip()
        except Exception:
            orden = ""
        if orden:
            break
    if intent == "hermes_tarea" and not orden:
        return {"reply": "Dime qué quieres que haga y me pongo con ello."}
    url, hdr = _cfg(ctx)
    if not await _alive(url, hdr) and not installed(ctx):
        # specs v24 (T2): al usuario, mensaje funcional. El detalle de qué falta
        # instalar y dónde va al LOG y al diagnóstico, no al chat.
        from backend.core.events import bus as _bus
        await _bus.emit("log", {"level": "warn",
                                "msg": f"Ejecutor no disponible en {url} y sin instalación "
                                       "local: instálalo desde hermes-agent.nousresearch.com "
                                       "o pon su ruta en ⚙ hermes_exe"})
        return {"reply": "No puedo ponerme con eso ahora mismo: me falta una pieza para "
                         "hacerlo. Dime «diagnostica hermes» y te digo exactamente qué."}
    if not orden:
        return {"reply": "Dime qué quieres que investigue y me pongo con ello."}
    return await delegate(orden, ctx, ctx.get("channel", "pc"))
