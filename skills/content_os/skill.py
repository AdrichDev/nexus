"""Minion Content OS — Instagram: analítica, patrones y guiones.

01/08/2026: se retiró la vía de «aprender» reels ajenos descargándolos con
yt-dlp y transcribiéndolos. Era scraping de contenido de terceros, o sea justo
lo que prohíbe la regla del proyecto. Lo ya transcrito en `data/inspiration/`
NO se borra (borrar exige confirmación explícita) y se puede seguir leyendo,
pero avisando de su origen. Ver `_download_and_transcribe` y `_aviso_origen`.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import httpx

DATA = Path(__file__).resolve().parents[2] / "data"
INSP_DIR = DATA / "inspiration"
SCRIPTS_DIR = DATA / "scripts"

SKILL = {
    "name": "Content OS",
    "description": "Instagram vía Graph API: métricas reales de tu cuenta, ranking de reels, "
                   "patrones ganadores sobre material propio y guiones "
                   "gancho+desarrollo+CTA. No descarga ni transcribe contenido ajeno.",
    "patterns": {
        # Anclas de dominio: instagram/ig, reel, guion, contenido. Los intents
        # con URL/tema (inspire, script) van antes que los genéricos de listado.
        "connect": r"conecta(?:r)? (?:mi |el )?instagram|vinc[uú]la(?:me)? (?:mi )?instagram"
                   r"|con[eé]ctame (?:el |a )?instagram"
                   r"|con[eé]cta(?:r|me)? (?:el |al )?content os"
                   r"|config[uú]ra(?:me)? (?:mi )?instagram",
        # COLISIÓN AUDITADA (01/08/2026). `skills_loader` recorre las carpetas
        # por orden ALFABÉTICO y gana la primera regex que case (rx.search, sin
        # anclar): «content_os» va antes que «instagram» y se tragaba
        # `instagram.ig_estado`. «cómo va EL instagram» pregunta por la
        # integración («¿está eso funcionando?») y lo contesta ig_estado con la
        # lista de lo que falta; «cómo va MI instagram» pregunta por la cuenta y
        # lo contesta esto. Por eso aquí se queda «mi» y se suelta «el».
        # Se suelta SOLO esa: quitar más mandaría frases al planificador del
        # cerebro, que es donde se inventa cosas.
        "analytics": r"anal[ií]tica de (?:mi )?instagram|(?:c[oó]mo|qu[eé] tal) va mi instagram"
                     r"|(?:c[oó]mo|qu[eé] tal) va mi cuenta de instagram|m[ií]s m[eé]tricas de (?:ig|instagram)"
                     r"|(?:m[eé]tricas|estad[ií]sticas|insights|alcance) de (?:mi )?(?:instagram|ig)\b",
        "best": r"m[ií]s mejores (?:reels|v[ií]deos de instagram|posts? de instagram)"
                r"|reels ganadores|qu[eé] reels (?:me )?funcionan mejor"
                r"|top (?:de )?reels|ranking de reels",
        "inspire": r"(?:inspiraci[oó]n de|aprende (?:del|de este|de ese) reel"
                   r"|analiza (?:el|este|ese) reel|f[ií]jate en (?:el|este) reel"
                   r"|estudia (?:el|este) reel)\s+(?P<rest>.+)",
        "patterns": r"anal[ií]za(?:me)? (?:los )?patrones(?: de inspiraci[oó]n)?"
                    r"|qu[eé] patrones? (?:hay|ves|se repiten)|patrones ganadores"
                    r"|qu[eé] (?:ganchos?|estructuras?) (?:funcionan|se repiten)",
        # El tema es OPCIONAL: «hazme un guion» a secas es una peticion legitima
        # y antes acababa en el planificador. Sin tema, el handler lo saca del
        # plan de contenido.
        # «genérame» lleva la tilde en la SEGUNDA e (g-e-n-é-r-a-m-e), no en la
        # primera: el patrón viejo solo aceptaba «génera» y se perdía la forma
        # que se escribe de verdad.
        "script": r"(?:g[eé]n[eé]ra(?:me)?|escr[ií]be(?:me)?|cr[eé]a(?:me)?|h[aá]z(?:me)?|"
                  r"prep[aá]ra(?:me)?|red[aá]cta(?:me)?|dame|quiero|necesito)\s+"
                  r"(?:un\s+|unos\s+|el\s+|los\s+)?"
                  r"gui[oó]n(?:es)?(?:\s+de\s+reels?)?"
                  r"(?:\s+(?:sobre|de|para)\s+(?P<topic>.+))?$",
        # IDEAS. Antes exigia ancla de dominio («ideas DE CONTENIDO», «ideas PARA
        # INSTAGRAM»), y las formas que se dicen de verdad —«dame ideas»,
        # «proponme ideas», «lluvia de ideas», «que publico esta semana»— no
        # casaban con nada y las resolvia el planificador, que es donde se
        # inventa cosas. nexus es el asistente de contenido de su dueño: pedirle
        # ideas a secas es pedirle ideas de contenido.
        "ideas": r"(?:dame|proponme|prop[oó]n(?:me)?|sugi[eé]re(?:me)?|quiero|necesito|"
                 r"escupe(?:me)?|s[aá]came|tira(?:me)?)\s+"
                 r"(?:m[aá]s\s+|otras\s+|unas\s+|algunas\s+)?ideas\b"
                 # O termina ahi —«dame ideas» a secas, que es lo que se dice— o
                 # lleva complemento DE CONTENIDO. Sin esta segunda condicion,
                 # «dame ideas de cena» acabaria en el plan de publicaciones.
                 r"(?:\s*[?¿!.]*$"
                 r"|\s+(?:de|para|sobre)\s+(?:reels?|contenido|instagram|ig|publicar|"
                 r"la\s+semana|el\s+canal|el\s+perfil|v[ií]deos?|posts?|publicaciones|"
                 r"tiktok|youtube|guiones?|redes(?:\s+sociales)?))"
                 r"|\blluvia de ideas\b|\bbrainstorm\w*\b"
                 # Sin verbo delante: «ideas para reels» es una orden completa.
                 r"|^\s*ideas\s+(?:de|para|sobre)\s+(?:reels?|contenido|instagram|ig|"
                 r"publicar|la\s+semana|el\s+canal|el\s+perfil|v[ií]deos?|posts?|"
                 r"publicaciones|tiktok|youtube|guiones?|redes(?:\s+sociales)?)"
                 r"|(?:sugi[eé]re(?:me)?|dame|proponme|prop[oó]n(?:me)?)\s+(?:m[aá]s\s+)?contenido\b"
                 r"|qu[eé] (?:subo|publico|puedo subir|puedo publicar|cuelgo|saco)"
                 r"(?:\s+(?:en|a)\s+instagram)?"
                 r"(?:\s+(?:esta\s+semana|hoy|ma[ñn]ana|ahora))?\s*[?¿!.]*$",
    },
}


def _token(ctx) -> str:
    return ctx["settings"].secret("ig_access_token") if hasattr(
        ctx["settings"], "secret") else ""


# NO HAY «_ig_user(ctx)» AQUÍ, Y ES A PROPÓSITO (02/08/2026).
# Resolvía el «ig_user_id o si no ig_business_account_id». No la llamaba NADIE:
# los tres sitios de este fichero que necesitan ese id se escriben esa misma línea
# a mano, y `backend/core/contentos.py:_ig_creds()` también. El ayudante nació
# muerto al lado de su propia duplicación. Si algún día se unifica, el sitio es
# `contentos._ig_creds()`, que sí está vivo.


# ---------------------------------------------------------------- inspiración
# LA VÍA OFICIAL, para no repetirla en cuatro sitios.
_VIA_LEGITIMA = (
    "La vía que sí tengo es la oficial: la Graph API. Con «analiza la cuenta de "
    "instagram de <usuario>» consulto `business_discovery` y te doy lo que Meta "
    "publica de esa cuenta (seguidores, publicaciones, interacción de sus posts) "
    "sin descargar nada. Y si quieres trabajar sobre un reel concreto, "
    "cuéntamelo tú: pégame el gancho o lo que dice, y lo analizo contigo.")


def _download_and_transcribe(url: str) -> str | None:
    """RETIRADA. Descargaba un reel ajeno con yt-dlp y lo transcribía.

    01/08/2026: esto es scraping de contenido de terceros, que es justo lo que
    prohíbe la política del propio proyecto («Nada de scraping de terceros ni de
    datos de sus audiencias. Instagram se consulta por la Graph API»). Llevaba
    meses en el código porque nadie la había mirado con esa regla delante.

    Falla CERRADO en la primera línea, no se limita a quedarse sin llamadas:
    dejarla operativa «por si acaso» es dejar la puerta abierta a que alguien la
    vuelva a enchufar sin darse cuenta de lo que enchufa. El cuerpo se queda de
    testigo, comentado, hasta que se borre con confirmación explícita."""
    raise RuntimeError(
        "vía retirada por política (nada de scraping de terceros); "
        "pendiente de borrado con tu confirmación")


def _aviso_origen() -> str:
    """De dónde salió lo que hay en data/inspiration/.

    Son transcripciones descargadas ANTES de retirar esa vía. No se borran (eso
    exige confirmación explícita del usuario, regla del proyecto: solo lectura
    por defecto) y se pueden seguir leyendo, pero quien lea un análisis basado
    en ellas tiene derecho a saber de dónde vienen y que ese material ya no
    crece."""
    return ("⚠ Ojo con el origen: esto sale de transcripciones heredadas, "
            "descargadas antes de retirar esa vía por política. Ni se amplían ni "
            "se descargan más. ")


def _load_inspirations() -> list[dict]:
    items = []
    for f in INSP_DIR.glob("*.json"):
        try:
            items.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return items


def _proximo_del_plan() -> str:
    """Titulo de lo primero que queda por publicar, para «hazme un guion» sin tema.

    Se mira el calendario de contenido y, si no queda nada pendiente ahi, la
    lista de ideas. Devuelve cadena vacia si no hay de donde sacarlo: entonces
    se pregunta, que es mejor que elegir un tema al azar.
    """
    try:
        from backend.core.dominio import contentos
        datos = contentos._load()
    except Exception:                                      # noqa: BLE001
        return ""
    for item in (datos.get("calendar") or []):
        if str(item.get("status", "")).lower() != "publicado" and item.get("title"):
            return str(item["title"]).strip()
    for idea in (datos.get("ideas") or []):
        if str(idea).strip():
            return str(idea).strip()
    return ""


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
            # AQUÍ SE CONTABA LA MENTIRA (hasta el 01/08/2026). Esto devolvía
            # «12.840 seguidores (+3,2%)», «alcance 184,2K», «retención 48,6%» y,
            # lo peor de todo, «el gancho de resultado visible va por encima de
            # tu mediana en 4 de 8 reels»: una conclusión estadística sobre una
            # mediana que nadie había calculado y ocho reels que no existían.
            # Iba precedido de «(ejemplo — conecta tu cuenta…)», que no salva
            # nada: el resto del texto contradice la coletilla, y esto sale por
            # el chat, que es donde el usuario más habla. Se contesta como
            # `ig_estado`: qué falta y cómo se consigue.
            falta = []
            if not token:
                falta.append("«ig_access_token» (el token de la Graph API)")
            if not uid:
                falta.append("«ig_user_id» (el id de tu cuenta business/creator)")
            return {"reply": "📊 De tu Instagram no sé nada todavía, y no me lo voy a "
                             "inventar: no tengo la cuenta conectada.\n"
                             "Me falta en ⚙: " + " y ".join(falta) + ".\n"
                             "Se sacan en developers.facebook.com con una cuenta Business "
                             "vinculada a una página de Facebook. Di «conecta mi instagram» "
                             "y te guío paso a paso; en cuanto estén, te saco seguidores, "
                             "alcance y ranking de reels de verdad."}
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
        # ESTE INTENT YA NO DESCARGA NADA (01/08/2026). Antes bajaba el reel con
        # yt-dlp y lo transcribía con whisper: scraping de contenido ajeno, o
        # sea justo lo que prohíbe la regla del proyecto. La REGEX SE QUEDA a
        # propósito: si se retirase, la frase caería al planificador del
        # cerebro, que es donde se inventa cosas. Mejor una puerta que contesta
        # la verdad que ninguna puerta.
        rest = (match.group("rest").strip() if match else "").strip()
        creator = (re.search(r"@([\w.]+)", rest) or [None, ""])[1] if "@" in rest else ""
        cabeza = (f"De ese reel de @{creator} no te puedo sacar nada por esa vía: "
                  if creator else "De ese reel no te puedo sacar nada por esa vía: ")
        return {"reply": cabeza + "descargarlo y transcribirlo es scraping de "
                         "contenido de otra persona, y este proyecto no hace eso.\n\n"
                         + _VIA_LEGITIMA}

    if intent == "patterns":
        insp = _load_inspirations()
        if not insp:
            # Ya no hay forma de darle más material por aquí: no se ofrece.
            return {"reply": "No tengo ninguna transcripción de la que sacar patrones.\n\n"
                             + _VIA_LEGITIMA}
        from backend.core.infraestructura.llm import ask_llm
        corpus = "\n\n".join(f"[@{i['creator']}] {i['transcript'][:800]}" for i in insp[:12])
        analysis, _ = await ask_llm(
            "Eres analista de contenido viral. De estas transcripciones de reels detecta "
            "PATRONES GANADORES: 1) tipos de gancho que se repiten, 2) estructura común, "
            "3) temas recurrentes, 4) tipo de CTA. Sé concreto y accionable:\n" + corpus[:9000])
        graph.write_note("patrones content", f"Patrones detectados:\n\n{analysis}\n\n"
                                              "Enlaces: [[content]] [[patrones]]")
        return {"reply": _aviso_origen()
                         + f"\n\nHe analizado {len(insp)} reels de inspiración:\n\n{analysis[:1000]}"
                         "\n\nDi «genera un guion sobre <tema>» y aplico estos patrones a tu contenido."}

    if intent == "script":
        # El tema es opcional: «hazme un guion» a secas es una peticion legitima.
        # Sin tema se coge la primera idea del plan de contenido; si tampoco hay
        # plan, se pide el tema en vez de inventarse uno.
        topic = (match.groupdict().get("topic") or "").strip().rstrip(".")
        aviso_tema = ""
        if not topic:
            topic = _proximo_del_plan()
            if not topic:
                return {"reply": "¿Sobre qué? Dime el tema —«hazme un guion sobre X»— o "
                                 "pídeme antes «dame ideas» y escribo el guion de la que elijas."}
            aviso_tema = ("No me has dicho el tema, así que he cogido lo primero que "
                          f"tienes en el plan: «{topic}».\n\n")
        from backend.core.infraestructura.llm import ask_llm
        insp = _load_inspirations()
        pat_note = graph.search("patrones", 3)
        ctx_txt = "\n".join(n["line"] for n in pat_note)
        # Si el guion se apoya en las transcripciones heredadas, se dice. El
        # aviso va DELANTE del guion, no en un pie que nadie lee.
        aviso = ""
        if insp and not ctx_txt:
            ctx_txt = "Ejemplos aprendidos:\n" + "\n".join(
                f"[@{i['creator']}] {i['transcript'][:300]}" for i in insp[:5])
            aviso = _aviso_origen() + "\n\n"
        script, _ = await ask_llm(
            f"Escribe un GUION de reel de Instagram sobre «{topic}» aplicando los patrones "
            "ganadores del creador. Estructura: **GANCHO** (primeros 3 seg, brutal), "
            "**DESARROLLO** (3-4 frases con ritmo), **CTA**. Añade sugerencia de texto en "
            f"pantalla. En español, tono directo.\n\nPatrones aprendidos:\n{ctx_txt[:3000]}")
        SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w ]", "", topic)[:30].strip()
        out = SCRIPTS_DIR / f"guion-{safe}-{dt.datetime.now():%H%M%S}.md"
        out.write_text(f"# Guion: {topic}\n\n{script}\n", encoding="utf-8")
        return {"reply": aviso_tema + aviso + f"Guion sobre «{topic}» listo "
                                              f"(data/scripts/{out.name}):\n\n{script[:1000]}"}

    if intent == "ideas":
        from backend.core.infraestructura.llm import ask_llm
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
                     "«mis mejores reels», «analiza los patrones» o "
                     "«genera un guion sobre <tema>»."}
