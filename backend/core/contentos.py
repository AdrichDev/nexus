"""
nexus — CONTENT OS: inteligencia de Instagram (para la marca Nexus).

Reconstruye el panel de Rubén DENTRO de nexus: calendario de publicaciones,
lluvia de ideas, inspiraciones, guiones con IA, métricas de posts/reels, mejores
y peores, seguidores/alcance, aprendizajes y evidencias acumuladas, y datos para
gráficos (línea, barras/histograma, tarta, dispersión/correlación, desviación).

Datos:
  * REALES vía Instagram Graph API si hay token (ig_access_token) e ig_user_id.
    Requiere cuenta Instagram Business/Creator (la profesional de Rubén) vinculada
    a una página de Facebook y una app de Meta con el token.
  * DEMO (mock realista) mientras no haya conexión, para que el panel funcione ya.

Lo editable (calendario, ideas, inspiraciones, aprendizajes) se guarda en
data/contentos.json y persiste entre sesiones.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import httpx

from .config import DATA_DIR, settings

STORE = DATA_DIR / "contentos.json"
GRAPH = "https://graph.facebook.com/v19.0"


# --------------------------------------------------------------- almacenamiento
def _seed() -> dict:
    """Contenido editable inicial (se puede cambiar por voz/HUD y persiste)."""
    return {
        "calendar": [
            {"n": 1, "title": "El error que hace que tus automatizaciones fallen",
             "type": "Reel", "when": "Hoy · 19:30", "status": "Listo"},
            {"n": 2, "title": "3 tareas que nunca deberías automatizar",
             "type": "Carrusel", "when": "Jueves · 13:00", "status": "Borrador"},
            {"n": 3, "title": "Lo que aprendí después de automatizar mi negocio",
             "type": "Reel", "when": "Sábado · 11:30", "status": "Revisar"},
        ],
        "ideas": [
            "Gancho: «el error de automatización que te cuesta clientes»",
            "Carrusel: 5 flujos de n8n que todo negocio debería tener",
            "Reel POV: un día dejando que la IA gestione tu agenda",
        ],
        "inspirations": [
            {"src": "@creador.automatiza", "note": "Gancho de resultado visible en 2 s"},
            {"src": "@marca.saas", "note": "Carruseles con 1 idea por tarjeta"},
        ],
        "learnings": [
            {"text": "Los reels con gancho de resultado en los 2 primeros segundos "
                     "retienen +30% sobre tu mediana.", "conf": "consistente"},
            {"text": "Publicar a las 19:30 supera al mediodía en alcance.", "conf": "prometedora"},
            {"text": "Los carruseles de 6 tarjetas guardan más que los de 10.", "conf": "observación"},
        ],
    }


def _load() -> dict:
    if STORE.exists():
        try:
            return json.loads(STORE.read_text(encoding="utf-8"))
        except Exception:
            pass
    data = _seed()
    _save(data)
    return data


def _save(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def add_item(kind: str, value) -> bool:
    """kind: idea | inspiration | learning | calendar. value: str o dict."""
    data = _load()
    if kind == "idea" and isinstance(value, str):
        data.setdefault("ideas", []).insert(0, value)
    elif kind == "inspiration":
        data.setdefault("inspirations", []).insert(0, value if isinstance(value, dict)
                                                    else {"src": "", "note": str(value)})
    elif kind == "learning":
        data.setdefault("learnings", []).insert(0, value if isinstance(value, dict)
                                                 else {"text": str(value), "conf": "observación"})
    elif kind == "calendar" and isinstance(value, dict):
        data.setdefault("calendar", []).append(value)
    else:
        return False
    _save(data)
    return True


# ------------------------------------------------------------------ IG real
def _ig_creds() -> tuple[str, str]:
    # Mismo número, dos nombres históricos: vale el que esté puesto.
    return (settings.secret("ig_access_token"),
            str(settings.get("ig_user_id", "") or "").strip()
            or str(settings.get("ig_business_account_id", "") or "").strip())


async def ig_connected() -> bool:
    token, uid = _ig_creds()
    if not (token and uid):
        return False
    try:
        async with httpx.AsyncClient(timeout=6) as cli:
            r = await cli.get(f"{GRAPH}/{uid}",
                              params={"fields": "username", "access_token": token})
        return r.status_code == 200 and "error" not in r.json()
    except Exception:
        return False


async def _ig_metrics() -> dict | None:
    """Métricas REALES de Instagram Graph API. None si falla (→ usamos demo)."""
    token, uid = _ig_creds()
    if not (token and uid):
        return None
    try:
        async with httpx.AsyncClient(timeout=12) as cli:
            prof = (await cli.get(f"{GRAPH}/{uid}", params={
                "fields": "username,followers_count,media_count",
                "access_token": token})).json()
            if "error" in prof:
                return None
            # Alcance últimos 28 días
            reach = (await cli.get(f"{GRAPH}/{uid}/insights", params={
                "metric": "reach", "period": "days_28", "access_token": token})).json()
            # Serie diaria de seguidores (30 días)
            since = int((datetime.utcnow() - timedelta(days=30)).timestamp())
            foll = (await cli.get(f"{GRAPH}/{uid}/insights", params={
                "metric": "follower_count", "period": "day",
                "since": since, "access_token": token})).json()
            # Últimas publicaciones
            media = (await cli.get(f"{GRAPH}/{uid}/media", params={
                "fields": "id,caption,media_type,media_product_type,timestamp,"
                          "like_count,comments_count,permalink",
                "limit": 24, "access_token": token})).json()

        followers = prof.get("followers_count", 0)
        reach_val = 0
        try:
            reach_val = reach["data"][0]["values"][0]["value"]
        except Exception:
            pass
        foll_series = []
        try:
            foll_series = [v["value"] for v in foll["data"][0]["values"]]
        except Exception:
            pass
        posts = media.get("data", []) if isinstance(media, dict) else []
        reels = []
        for m in posts:
            eng = (m.get("like_count", 0) or 0) + (m.get("comments_count", 0) or 0)
            reels.append({
                "name": (m.get("caption", "") or m.get("media_type", "post"))[:40] or "post",
                "type": m.get("media_product_type") or m.get("media_type", "IMAGE"),
                "eng": eng, "likes": m.get("like_count", 0) or 0,
                "comments": m.get("comments_count", 0) or 0,
                "when": (m.get("timestamp", "") or "")[:10],
                "hour": _hour_of(m.get("timestamp", "")),
                "url": m.get("permalink", ""),
            })
        return {"username": prof.get("username", ""), "followers": followers,
                "media_count": prof.get("media_count", 0), "reach_month": reach_val,
                "followers_series": foll_series, "posts": reels, "real": True}
    except Exception:
        return None


def _hour_of(ts: str) -> int:
    try:
        return int(ts[11:13])
    except Exception:
        return 12


# ------------------------------------------------------------------ demo
def _demo_metrics() -> dict:
    base = 12840
    series = [base - 420 + int(420 * (i / 29) + 55 * ((i * 7) % 5 - 2)) for i in range(30)]
    reels = [
        {"name": "El error que mata tus automatizaciones", "type": "REELS", "eng": 1840,
         "likes": 1620, "comments": 220, "when": "07-12", "hour": 19, "reach": 24100},
        {"name": "3 tareas que NO deberías automatizar", "type": "CAROUSEL", "eng": 1210,
         "likes": 1090, "comments": 120, "when": "07-09", "hour": 13, "reach": 15600},
        {"name": "POV: la IA gestiona tu agenda", "type": "REELS", "eng": 2260,
         "likes": 1980, "comments": 280, "when": "07-06", "hour": 20, "reach": 31200},
        {"name": "Lo que aprendí automatizando mi negocio", "type": "REELS", "eng": 980,
         "likes": 860, "comments": 120, "when": "07-03", "hour": 12, "reach": 12800},
        {"name": "Mi stack de herramientas 2026", "type": "CAROUSEL", "eng": 1520,
         "likes": 1360, "comments": 160, "when": "06-30", "hour": 19, "reach": 18900},
        {"name": "Automatiza tu Instagram en 5 pasos", "type": "REELS", "eng": 1680,
         "likes": 1490, "comments": 190, "when": "06-27", "hour": 21, "reach": 22400},
    ]
    return {"username": "marca.personal", "followers": base, "media_count": 214,
            "reach_month": 184200, "followers_series": series, "posts": reels, "real": False}


# ------------------------------------------------------------------ ensamblado
def _build_charts(m: dict) -> dict:
    posts = m.get("posts", [])
    # línea de seguidores
    series = m.get("followers_series") or []
    followers_line = {"labels": [f"D{i+1}" for i in range(len(series))], "values": series}
    # barras/histograma de alcance por publicación (proxy si no hay reach real)
    reach_bars = {"labels": [p["name"][:16] for p in posts[:8]],
                  "values": [p.get("reach") or p.get("eng", 0) * 13 for p in posts[:8]]}
    # tarta: mezcla por tipo de contenido
    mix: dict = {}
    for p in posts:
        t = (p.get("type") or "OTRO").replace("REELS", "Reels").replace("CAROUSEL", "Carrusel") \
            .replace("IMAGE", "Foto").replace("VIDEO", "Vídeo")
        mix[t] = mix.get(t, 0) + 1
    pie = [{"label": k, "value": v} for k, v in mix.items()] or [{"label": "Reels", "value": 1}]
    # dispersión: hora de publicación vs engagement (correlación)
    scatter = [{"x": p.get("hour", 12), "y": p.get("eng", 0)} for p in posts]
    # desviación de cada reel respecto a la mediana de engagement
    engs = sorted(p.get("eng", 0) for p in posts)
    median = engs[len(engs) // 2] if engs else 0
    deviation = [{"label": p["name"][:16], "value": p.get("eng", 0), "median": median}
                 for p in posts[:8]]
    return {"followers": followers_line, "reach": reach_bars, "pie": pie,
            "scatter": scatter, "deviation": deviation, "median_eng": median}


def _rank(posts: list[dict]) -> tuple[list, list]:
    ordered = sorted(posts, key=lambda p: p.get("eng", 0), reverse=True)
    best = [{"name": p["name"], "eng": p.get("eng", 0), "type": p.get("type", ""),
             "url": p.get("url", "")} for p in ordered[:3]]
    worst = [{"name": p["name"], "eng": p.get("eng", 0), "type": p.get("type", ""),
              "url": p.get("url", "")} for p in ordered[-3:][::-1]]
    return best, worst


def _pct(cur: int, prev: int) -> float:
    return round((cur - prev) / prev * 100, 1) if prev else 0.0


async def dashboard() -> dict:
    store = _load()
    metrics = await _ig_metrics() or _demo_metrics()
    charts = _build_charts(metrics)
    best, worst = _rank(metrics.get("posts", []))
    series = metrics.get("followers_series") or []
    foll_delta = _pct(series[-1], series[0]) if len(series) > 1 else 3.2
    engs = [p.get("eng", 0) for p in metrics.get("posts", [])]
    retention = 48.6  # proxy; con métricas reales de reel se calcula de avg_watch/length
    learnings = store.get("learnings", [])
    ev = {
        "consistent": sum(1 for l in learnings if l.get("conf") == "consistente"),
        "promising": sum(1 for l in learnings if l.get("conf") == "prometedora"),
        "observations": sum(1 for l in learnings if l.get("conf") == "observación"),
    }
    total = max(1, len(learnings))
    ev["complete_pct"] = round((ev["consistent"] * 1 + ev["promising"] * 0.6) / total * 100)
    # siguiente mejor acción (heurística sobre lo que funciona)
    top = best[0] if best else None
    next_action = {
        "signal": "Señal inicial",
        "title": "Repite el gancho de resultado visible, pero cambia el tema."
        if top else "Publica un reel con gancho en los 2 primeros segundos.",
        "detail": (f"«{top['name']}» va por encima de tu mediana. Sigue siendo una señal, "
                   "no una conclusión: haz un experimento con el mismo gancho y otro tema.")
        if top else "Aún no hay suficientes datos; empieza a acumular señales.",
        "analyzed": len(engs),
    }
    return {
        "connected": bool(metrics.get("real")),
        "username": metrics.get("username", ""),
        "operator": settings.get("operator_name", "Operador"),
        "kpis": {
            "followers": metrics.get("followers", 0), "followers_delta": foll_delta,
            "reach_month": metrics.get("reach_month", 0), "reach_delta": 18.4,
            "retention": retention, "retention_delta": 4.1,
            "experiments": 2, "media_count": metrics.get("media_count", 0),
        },
        "next_action": next_action,
        "calendar": store.get("calendar", []),
        "ideas": store.get("ideas", []),
        "inspirations": store.get("inspirations", []),
        "learnings": learnings,
        "evidence": ev,
        "best": best, "worst": worst,
        "charts": charts,
    }


async def generate(kind: str, topic: str = "") -> str:
    """Genera una idea o un guion con el LLM y (si es idea) la guarda."""
    from . import llm
    topic = (topic or "").strip()
    if kind == "script":
        prompt = (f"Escribe un guion de reel de Instagram para la marca Nexus sobre: "
                  f"{topic or 'automatización y productividad'}. Estructura: GANCHO (2s, "
                  "resultado visible), desarrollo en 3 golpes, y CTA. Tono cercano y directo. "
                  "Español. Máx 120 palabras.")
        text, _ = await llm.ask_llm(prompt)
        return text
    # idea
    prompt = (f"Dame 1 idea de contenido de Instagram para la marca Nexus"
              f"{' sobre ' + topic if topic else ''}: un gancho potente en una frase, "
              "orientado a resultado. Solo la idea, sin preámbulos. Español.")
    text, _ = await llm.ask_llm(prompt)
    idea = text.strip().strip('"').split("\n")[0][:160]
    add_item("idea", idea)
    return idea
