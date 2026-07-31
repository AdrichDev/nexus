"""Minion Content OS — Instagram: analítica, inspiración, patrones y guiones."""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import tempfile
from pathlib import Path

import httpx

DATA = Path(__file__).resolve().parents[2] / "data"
INSP_DIR = DATA / "inspiration"
SCRIPTS_DIR = DATA / "scripts"

SKILL = {
    "name": "Content OS",
    "description": "Instagram vía Graph API: métricas reales de tu cuenta, ranking de reels, "
                   "aprendizaje de reels ajenos por transcripción, patrones ganadores y "
                   "guiones gancho+desarrollo+CTA",
    "patterns": {
        # Anclas de dominio: instagram/ig, reel, guion, contenido. Los intents
        # con URL/tema (inspire, script) van antes que los genéricos de listado.
        "connect": r"conecta(?:r)? (?:mi |el )?instagram|vincula (?:mi )?instagram"
                   r"|con[eé]ctame (?:el |a )?instagram|conecta(?:r)? (?:el )?content os"
                   r"|configura (?:mi )?instagram",
        "analytics": r"anal[ií]tica de (?:mi )?instagram|c[oó]mo va (?:mi|el) instagram"
                     r"|c[oó]mo va mi cuenta de instagram|m[ií]s m[eé]tricas de (?:ig|instagram)"
                     r"|(?:m[eé]tricas|estad[ií]sticas|insights|alcance) de (?:mi )?(?:instagram|ig)\b",
        "best": r"m[ií]s mejores (?:reels|v[ií]deos de instagram|posts? de instagram)"
                r"|reels ganadores|qu[eé] reels (?:me )?funcionan mejor"
                r"|top (?:de )?reels|ranking de reels",
        "inspire": r"(?:inspiraci[oó]n de|aprende (?:del|de este|de ese) reel"
                   r"|analiza (?:el|este|ese) reel|f[ií]jate en (?:el|este) reel"
                   r"|estudia (?:el|este) reel)\s+(?P<rest>.+)",
        "patterns": r"analiza (?:los )?patrones(?: de inspiraci[oó]n)?"
                    r"|qu[eé] patrones? (?:hay|ves|se repiten)|patrones ganadores"
                    r"|qu[eé] (?:ganchos?|estructuras?) (?:funcionan|se repiten)",
        "script": r"(?:genera|escribe|crea|hazme|prep[aá]rame|red[aá]ctame)\s+(?:un\s+)?"
                  r"gui[oó]n(?:\s+de\s+reel)?\s+(?:sobre|de|para)\s+(?P<topic>.+)",
        "ideas": r"dame ideas de contenido|(?:dame|quiero|necesito) ideas (?:de|para) "
                 r"(?:reels|contenido|instagram)|ideas para (?:reels|instagram)"
                 r"|qu[eé] (?:subo|publico|puedo subir|puedo publicar) (?:en|a) instagram",
    },
}


def _token(ctx) -> str:
    return ctx["settings"].secret("ig_access_token") if hasattr(
        ctx["settings"], "secret") else ""


def _ig_user(ctx) -> str:
    return (str(ctx["settings"].get("ig_user_id", "") or "").strip()
            or str(ctx["settings"].get("ig_business_account_id", "") or "").strip())


# ---------------------------------------------------------------- inspiración
def _download_and_transcribe(url: str) -> str | None:
    """Descarga un reel público con yt-dlp y lo transcribe con whisper."""
    try:
        import yt_dlp  # noqa: F401
        from faster_whisper import WhisperModel  # noqa: F401
    except ImportError:
        return None
    tmp = Path(tempfile.mkdtemp())
    out = tmp / "clip.%(ext)s"
    try:
        subprocess.run(["yt-dlp", "-x", "--audio-format", "mp3", "-o", str(out), url],
                       capture_output=True, timeout=120, check=True)
        audio = next(tmp.glob("clip.*"), None)
        if not audio:
            return None
        from backend.core.stt import _get_model
        segments, _ = _get_model().transcribe(str(audio), language="es", vad_filter=True)
        return " ".join(s.text.strip() for s in segments)
    except Exception:
        return None


def _load_inspirations() -> list[dict]:
    items = []
    for f in INSP_DIR.glob("*.json"):
        try:
            items.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return items


# ---------------------------------------------------------------- handler
async def handle(intent: str, text: str, match, ctx) -> dict:
    settings, graph, pg = ctx["settings"], ctx["graph"], ctx["pg"]

    if intent == "connect":
        token = settings.secret("ig_access_token")
        uid = (str(settings.get("ig_user_id", "") or "").strip()
                or str(settings.get("ig_business_account_id", "") or "").strip())
        if not token or not uid:
            return {"reply": "Para conectar Instagram necesito 2 cosas en ⚙: el "
                             "«ig_access_token» (token de la Graph API) y el «ig_user_id» "
                             "(id de tu cuenta business/creator). Se sacan en "
                             "developers.facebook.com con una cuenta Business vinculada a "
                             "una página de Facebook. ¿Te guío paso a paso?"}
        try:
            async with httpx.AsyncClient(timeout=10) as cli:
                r = await cli.get(f"https://graph.facebook.com/v19.0/{uid}",
                                  params={"fields": "username,followers_count,media_count",
                                          "access_token": token})
                d = r.json()
            if "error" in d:
                return {"reply": f"Instagram rechazó el token: {d['error'].get('message')}"}
            return {"reply": f"Instagram conectado: @{d.get('username')} — "
                             f"{d.get('followers_count', '?')} seguidores, "
                             f"{d.get('media_count', '?')} publicaciones. "
                             "Pídeme «analítica de instagram»."}
        except Exception as exc:
            return {"reply": f"No he podido hablar con Instagram: {exc}"}

    if intent == "analytics":
        token, uid = settings.secret("ig_access_token"), (str(settings.get("ig_user_id", "") or "").strip()
                or str(settings.get("ig_business_account_id", "") or "").strip())
        if not token or not uid:
            # Ejemplo coherente (como el panel Content OS) mientras no hay token
            return {"reply": "📊 Instagram (ejemplo — conecta tu cuenta en ⚙ para datos "
                             "reales):\n• Seguidores: 12.840 (+3,2% 30 días)\n"
                             "• Alcance mensual: 184,2K (+18,4%)\n• Retención media Reels: 48,6%\n"
                             "• Señal: el gancho de 'resultado visible' va por encima de tu "
                             "mediana en 4 de 8 reels. Repítelo cambiando el tema."}
        try:
            async with httpx.AsyncClient(timeout=12) as cli:
                prof = (await cli.get(f"https://graph.facebook.com/v19.0/{uid}",
                        params={"fields": "username,followers_count", "access_token": token})).json()
                ins = (await cli.get(f"https://graph.facebook.com/v19.0/{uid}/insights",
                       params={"metric": "reach,impressions,profile_views", "period": "days_28",
                               "access_token": token})).json()
            lines = [f"📊 @{prof.get('username')} — {prof.get('followers_count')} seguidores"]
            for m in ins.get("data", []):
                val = m["values"][-1]["value"] if m.get("values") else "?"
                lines.append(f"• {m['name']}: {val} (28 días)")
            return {"reply": "\n".join(lines)}
        except Exception as exc:
            return {"reply": f"Error leyendo insights: {exc}"}

    if intent == "best":
        token, uid = settings.secret("ig_access_token"), (str(settings.get("ig_user_id", "") or "").strip()
                or str(settings.get("ig_business_account_id", "") or "").strip())
        if not token or not uid:
            return {"reply": "Para el ranking real necesito tu cuenta conectada: pon "
                             "«ig_access_token» e «ig_user_id» en ⚙ (di «conecta mi instagram» "
                             "y te guío). En cuanto estén, te saco los reels ganadores al momento."}
        try:
            async with httpx.AsyncClient(timeout=12) as cli:
                media = (await cli.get(f"https://graph.facebook.com/v19.0/{uid}/media",
                         params={"fields": "caption,like_count,comments_count,media_type,permalink",
                                 "limit": 25, "access_token": token})).json()
            reels = [m for m in media.get("data", []) if m.get("media_type") in ("VIDEO", "REEL")]
            reels.sort(key=lambda m: m.get("like_count", 0) + m.get("comments_count", 0) * 3,
                       reverse=True)
            lines = [f"• {(m.get('caption') or '(sin texto)')[:50]} — "
                     f"❤{m.get('like_count',0)} 💬{m.get('comments_count',0)}"
                     for m in reels[:6]]
            return {"reply": "Tus reels con más interacción:\n" + "\n".join(lines)}
        except Exception as exc:
            return {"reply": f"Error: {exc}"}

    if intent == "inspire":
        rest = match.group("rest").strip()
        url_m = re.search(r"https?://\S+", rest)
        if not url_m:
            return {"reply": "Pásame el enlace del reel: «inspiración de @creador "
                             "https://instagram.com/reel/...»"}
        url = url_m.group(0)
        creator = (re.search(r"@(\w[\w.]+)", rest) or [None, "creador"])[1] \
            if "@" in rest else "creador"
        import asyncio
        transcript = await asyncio.to_thread(_download_and_transcribe, url)
        if not transcript:
            return {"reply": "No he podido descargar/transcribir ese reel. Necesito yt-dlp "
                             "y faster-whisper instalados (pip install yt-dlp faster-whisper), "
                             "y que el reel sea público. ¿Instalo las dependencias?"}
        INSP_DIR.mkdir(parents=True, exist_ok=True)
        rec = {"creator": creator, "url": url, "transcript": transcript,
               "date": dt.date.today().isoformat()}
        fname = INSP_DIR / f"{creator}-{dt.datetime.now():%Y%m%d%H%M%S}.json"
        fname.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        graph.write_note(f"insp {creator} {fname.stem[-6:]}",
                         f"Reel de @{creator} ({url}):\n\n{transcript[:8000]}\n\n"
                         "Enlaces: [[inspiracion]] [[content]]")
        if pg.online:
            pg.remember(f"[reel @{creator}] {transcript[:2000]}", kind="knowledge",
                        tags=["inspiracion", creator])
        return {"reply": f"Aprendido el reel de @{creator} ({len(transcript)} caracteres "
                         "transcritos y guardados). Cuando tengas varios, di «analiza los "
                         "patrones» y te digo qué funciona."}

    if intent == "patterns":
        insp = _load_inspirations()
        if not insp:
            return {"reply": "Aún no he aprendido ningún reel de inspiración. Dame algunos: "
                             "«inspiración de @creador <url del reel>»."}
        from backend.core.llm import ask_llm
        corpus = "\n\n".join(f"[@{i['creator']}] {i['transcript'][:800]}" for i in insp[:12])
        analysis, _ = await ask_llm(
            "Eres analista de contenido viral. De estas transcripciones de reels detecta "
            "PATRONES GANADORES: 1) tipos de gancho que se repiten, 2) estructura común, "
            "3) temas recurrentes, 4) tipo de CTA. Sé concreto y accionable:\n" + corpus[:9000])
        graph.write_note("patrones content", f"Patrones detectados:\n\n{analysis}\n\n"
                                              "Enlaces: [[content]] [[patrones]]")
        return {"reply": f"He analizado {len(insp)} reels de inspiración:\n\n{analysis[:1000]}"
                         "\n\nDi «genera un guion sobre <tema>» y aplico estos patrones a tu contenido."}

    if intent == "script":
        topic = match.group("topic").strip().rstrip(".")
        from backend.core.llm import ask_llm
        insp = _load_inspirations()
        pat_note = graph.search("patrones", 3)
        ctx_txt = "\n".join(n["line"] for n in pat_note)
        if insp and not ctx_txt:
            ctx_txt = "Ejemplos aprendidos:\n" + "\n".join(
                f"[@{i['creator']}] {i['transcript'][:300]}" for i in insp[:5])
        script, _ = await ask_llm(
            f"Escribe un GUION de reel de Instagram sobre «{topic}» aplicando los patrones "
            "ganadores del creador. Estructura: **GANCHO** (primeros 3 seg, brutal), "
            "**DESARROLLO** (3-4 frases con ritmo), **CTA**. Añade sugerencia de texto en "
            f"pantalla. En español, tono directo.\n\nPatrones aprendidos:\n{ctx_txt[:3000]}")
        SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w ]", "", topic)[:30].strip()
        out = SCRIPTS_DIR / f"guion-{safe}-{dt.datetime.now():%H%M%S}.md"
        out.write_text(f"# Guion: {topic}\n\n{script}\n", encoding="utf-8")
        return {"reply": f"Guion sobre «{topic}» listo (data/scripts/{out.name}):\n\n{script[:1000]}"}

    if intent == "ideas":
        from backend.core.llm import ask_llm
        insp = _load_inspirations()
        base = ("Basándote en estos patrones aprendidos:\n" +
                "\n".join(f"- @{i['creator']}: {i['transcript'][:150]}" for i in insp[:6])) \
            if insp else "No hay inspiración aún; usa buenas prácticas de reels."
        ideas, _ = await ask_llm(
            f"{base}\n\nDame 5 IDEAS de reels concretas (título + gancho en una línea) "
            "para el negocio del operador. Numeradas.")
        return {"reply": f"5 ideas de contenido:\n{ideas}\n\n"
                         "¿Alguna te encaja? Di «genera un guion sobre <la idea>» y te lo escribo."}

    return {"reply": "Esa orden de Content OS no la tengo. Prueba: «analítica de instagram», "
                     "«inspiración de @creador <url>», «analiza los patrones» o "
                     "«genera un guion sobre <tema>»."}
