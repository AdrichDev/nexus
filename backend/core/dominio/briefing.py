"""
nexus — BRIEFING matinal proactivo (v19): «buenos días, operador».

A la hora configurada (settings: briefing_hour "08:30", briefing_enabled true),
nexus construye y CANTA el parte del día él solo — sin que se lo pidas — por el
HUD (evento chat → texto + voz) y por Telegram si está enlazado. También se
puede pedir a demanda: la skill coach lo usa en «qué me toca hoy».

Secciones (cada una A PRUEBA DE FALLOS: si una fuente no responde, se omite y
el briefing sale igual con las demás):
  🌤 Clima de hoy (wttr.in, misma fuente que la skill clima)
  ▦ Tablero: vencidas, a punto de vencer y qué hay en marcha
  🪽 Encargos a Hermes pendientes o recién terminados
  📰 Titulares del tema configurado (settings briefing_topics, coma-separado)

Estado en data/briefing_state.json (última fecha enviada) para mandarlo UNA
vez al día aunque el scheduler pregunte cada minuto.
"""
from __future__ import annotations

import datetime as dt
import json
import time

from ..comun.config import DATA_DIR, settings
from ..comun.config import assistant_name as _aname

_STATE = DATA_DIR / "briefing_state.json"

_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


# ─────────────────────────── estado (una vez al día) ───────────────────────────

def _state_load() -> dict:
    try:
        d = json.loads(_STATE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _state_save(d: dict) -> None:
    try:
        _STATE.parent.mkdir(parents=True, exist_ok=True)
        _STATE.write_text(json.dumps(d), encoding="utf-8")
    except Exception:
        pass


def briefing_due(now: dt.datetime, enabled: bool, hour_str: str,
                 last_sent_date: str) -> bool:
    """¿Toca mandar el briefing? PURA (testeable): activado + ya pasó la hora
    configurada + hoy aún no se ha mandado."""
    if not enabled:
        return False
    try:
        hh, mm = (hour_str or "08:30").strip().split(":")
        target = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    except Exception:
        return False
    return now >= target and last_sent_date != now.date().isoformat()


# ───────────────────────────── secciones (con red) ─────────────────────────────

async def weather_now() -> dict:
    """Tiempo ACTUAL en datos (specs v23, T15: la temperatura vive en el header).
    Devuelve {} si el servicio falla — un fallo del tiempo NO bloquea nada más."""
    try:
        from ..comun import net
        city = settings.get("briefing_city", "") or ""
        from urllib.parse import quote
        url = f"https://wttr.in/{quote(city) if city else ''}?format=j1&lang=es"
        r = await net.client().get(url, headers={"User-Agent": "curl/8.0"}, timeout=8)
        d = r.json()
        cur = d["current_condition"][0]
        desc = (cur.get("lang_es") or cur.get("weatherDesc") or [{"value": ""}])[0]["value"].strip()
        hoy = (d.get("weather") or [{}])[0]
        area = ((d.get("nearest_area") or [{}])[0].get("areaName") or [{}])[0].get("value", "")
        code = str(cur.get("weatherCode", ""))
        return {"ciudad": city or area or "", "temp": cur.get("temp_C", ""),
                "desc": desc, "max": hoy.get("maxtempC", ""), "min": hoy.get("mintempC", ""),
                "icono": _wx_icon(code, desc), "sensacion": cur.get("FeelsLikeC", "")}
    except Exception:
        return {}


def _wx_icon(code: str, desc: str) -> str:
    d = (desc or "").lower()
    if "torment" in d or "truen" in d:
        return "⛈"
    if "nieve" in d or "nev" in d:
        return "❄"
    if "lluvia" in d or "llov" in d or "chubasc" in d:
        return "🌧"
    if "niebla" in d or "brum" in d:
        return "🌫"
    if "despejado" in d or "solead" in d or "sol" == d.strip():
        return "☀"
    if "nub" in d or "cubierto" in d:
        return "☁"
    return "🌤"


async def _sec_clima() -> str:
    try:
        from ..comun import net
        city = settings.get("briefing_city", "") or ""
        from urllib.parse import quote
        url = f"https://wttr.in/{quote(city) if city else ''}?format=j1&lang=es"
        r = await net.client().get(url, headers={"User-Agent": "curl/8.0"}, timeout=8)
        d = r.json()
        cur = d["current_condition"][0]
        desc = (cur.get("lang_es") or cur.get("weatherDesc") or [{"value": ""}])[0]["value"].strip()
        today = (d.get("weather") or [{}])[0]
        mm = (f", máx {today['maxtempC']}° / mín {today['mintempC']}°"
              if today.get("maxtempC") else "")
        return f"🌤 {desc or 'Tiempo'}, {cur.get('temp_C', '?')}°C ahora{mm}."
    except Exception:
        return ""


def _sec_tablero() -> str:
    try:
        from . import board
        late, soon = board.overdue()
        b = board.board()
        doing = b.get("progreso", [])
        bits = []
        if late:
            bits.append("🔴 " + "; ".join(f"«{t['title']}» venció {t.get('due', '')}"
                                          for t in late[:3]))
        if soon:
            bits.append("🟡 " + "; ".join(f"«{t['title']}» vence {t.get('due', '')}"
                                          for t in soon[:3]))
        if doing:
            bits.append("▶ En marcha: " + ", ".join(f"«{t['title']}»" for t in doing[:3]))
        if not bits:
            total = sum(len(v) for v in b.values())
            bits.append("Tablero al día" + (f" ({total} tareas en total)." if total else ": vacío."))
        return "▦ Tareas: " + " · ".join(bits)
    except Exception:
        return ""


def _sec_hermes() -> str:
    try:
        d = json.loads((DATA_DIR / "hermes_jobs.json").read_text(encoding="utf-8"))
        if not isinstance(d, list) or not d:
            return ""
        activos = [j for j in d if j.get("estado") in ("encargado", "trabajando")]
        recientes = [j for j in d if j.get("estado") == "hecho"
                     and (time.time() - (j.get("t1") or 0)) < 86400]
        bits = []
        if activos:
            bits.append("en marcha " + ", ".join(f"#{j.get('num', '?')}" for j in activos[:4]))
        if recientes:
            bits.append("terminados ayer/hoy " + ", ".join(f"#{j.get('num', '?')}"
                                                           for j in recientes[:4])
                        + " (di «resultado del encargo N»)")
        return ("🪽 Hermes: " + " · ".join(bits)) if bits else ""
    except Exception:
        return ""


async def _sec_noticias() -> str:
    topics = [t.strip() for t in str(settings.get("briefing_topics", "") or "").split(",")
              if t.strip()]
    if not topics:
        return ""
    try:
        from ..infraestructura import websearch
        heads: list[str] = []
        for topic in topics[:2]:
            res = await websearch.search(f"noticias {topic} hoy", 3)
            heads += [f"• {r['title'][:90]}" for r in res[:2] if r.get("title")]
        return ("📰 Titulares:\n" + "\n".join(heads[:4])) if heads else ""
    except Exception:
        return ""


# ───────────────────────────────── ensamblado ─────────────────────────────────

async def build_briefing() -> str:
    now = dt.datetime.now()
    quien = settings.get("operator_name", "") or "operador"
    saludo = ("Buenos días" if now.hour < 14 else
              "Buenas tardes" if now.hour < 21 else "Buenas noches")
    head = (f"{saludo}, {quien}. {_DIAS[now.weekday()].capitalize()} "
            f"{now.day} de {_MESES[now.month - 1]}, {now:%H:%M}. Parte del día:")
    secs = [head]
    clima = await _sec_clima()
    if clima:
        secs.append(clima)
    tab = _sec_tablero()
    if tab:
        secs.append(tab)
    her = _sec_hermes()
    if her:
        secs.append(her)
    news = await _sec_noticias()
    if news:
        secs.append(news)
    secs.append("A sus órdenes. Di «organiza mis tareas por urgencia» si quieres plan de ataque.")
    return "\n".join(secs)


async def today_payload() -> dict:
    """Datos ESTRUCTURADOS del panel HOY del HUD (v20): lo mismo que el briefing
    pero en JSON para pintar tarjetas. Cada bloque es a prueba de fallos."""
    now = dt.datetime.now()
    out: dict = {"fecha": f"{_DIAS[now.weekday()].capitalize()} {now.day} de "
                          f"{_MESES[now.month - 1]}",
                 "hora": f"{now:%H:%M}",
                 "operador": settings.get("operator_name", "") or "operador"}
    out["clima"] = await _sec_clima()
    try:
        from . import board
        late, soon = board.overdue()
        b = board.board()
        out["tareas"] = {
            "vencidas": [{"title": t["title"], "due": t.get("due", "")} for t in late[:5]],
            "proximas": [{"title": t["title"], "due": t.get("due", "")} for t in soon[:5]],
            "en_marcha": [{"title": t["title"]} for t in b.get("progreso", [])[:5]],
            "pendientes": len(b.get("pendiente", [])),
        }
    except Exception:
        out["tareas"] = {}
    try:
        jobs = json.loads((DATA_DIR / "hermes_jobs.json").read_text(encoding="utf-8"))
        out["hermes"] = [{"num": j.get("num"), "estado": j.get("estado"),
                          "orden": (j.get("orden") or "")[:70]}
                         for j in jobs[-6:]][::-1]
    except Exception:
        out["hermes"] = []
    try:
        ws = json.loads((DATA_DIR / "watchers.json").read_text(encoding="utf-8"))
        out["vigilancias"] = [{"num": w.get("num"), "tipo": w.get("tipo"),
                               "objetivo": (w.get("objetivo") or "")[:60]}
                              for w in ws[:6]]
    except Exception:
        out["vigilancias"] = []
    try:
        rep = DATA_DIR / "reports"
        files = sorted(rep.glob("*.md"), key=lambda f: f.stat().st_mtime,
                       reverse=True)[:4] if rep.exists() else []
        out["informes"] = [f.stem for f in files]
    except Exception:
        out["informes"] = []
    return out


_sent_ram = {"last": ""}    # respaldo en RAM: si el disco no deja persistir el
                            # estado, NO se reenvía el parte cada minuto igualmente


async def maybe_send() -> bool:
    """Llamado por el scheduler cada ~1 min: manda el briefing si toca (una vez
    al día, a partir de la hora configurada). Devuelve True si lo mandó."""
    now = dt.datetime.now()
    st = _state_load()
    last = st.get("last", "") or _sent_ram["last"]
    if not briefing_due(now, bool(settings.get("briefing_enabled", False)),
                        str(settings.get("briefing_hour", "08:30")),
                        last):
        return False
    txt = await build_briefing()
    from ..comun.events import bus
    await bus.emit("chat", {"user": "[briefing automático]", "reply": txt,
                            "provider": "nexus", "skill": "coach", "channel": "pc"})
    await bus.emit("notification", {"title": f"☀ Briefing de {_aname()}",
                                    "body": "Tu parte del día está en el chat."})
    try:
        from ..infraestructura.telegram_bridge import send_telegram
        await send_telegram(txt)
    except Exception:
        pass
    st["last"] = now.date().isoformat()
    _sent_ram["last"] = st["last"]
    _state_save(st)
    return True
