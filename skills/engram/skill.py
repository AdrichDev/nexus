"""Minion Engram — memoria de PROYECTO/código, compartida con tus otras
herramientas de IA (Claude Code, Cursor, Codex...) a través de Engram
(github.com/Gentleman-Programming/engram). Distinto de tu memoria PERSONAL
(skill Memoria) — ver backend/core/engram_bridge.py para el porqué."""
from __future__ import annotations

SKILL = {
    "name": "Engram (memoria de proyecto)",
    "description": ("MEMORIA OPERATIVA de nexus (Engram): cómo quiere trabajar Adri — órdenes "
                    "permanentes, preferencias, procedimientos, restricciones, correcciones, "
                    "errores que no repetir y reglas de delegación con Hermes — y también "
                    "decisiones técnicas del proyecto, compartida con tus otras "
                    "herramientas de IA (Claude Code, Cursor, Codex...) si también las conectaste "
                    "a Engram. Guarda decisiones/bugs/features con «recuerda en el proyecto que...», "
                    "consúltalas con «qué se decidió sobre...» o «contexto del proyecto», y comprueba "
                    "la conexión con «está engram conectado». Es OPCIONAL: si no tienes Engram "
                    "instalado, nexus sigue funcionando igual sin él. Para tu memoria PERSONAL usa "
                    "la skill de Memoria, no esta."),
    # Orden: estado (palabras cerradas) -> guardar (verbo+anclaje) -> contexto
    # (frases cerradas, con $) -> buscar (lo más amplio, captura libre al final).
    "patterns": {
        "status": r"(?:est[aá]|anda|sigue)\s+engram\s+(?:conectado|encendido|apagado|vivo|activo|en\s+marcha|operativo|funcionando|corriendo)"
                  r"|engram\s+(?:est[aá]|anda)\s+(?:conectado|encendido|apagado|vivo|activo|funcionando|corriendo|ca[ií]do)"
                  r"|(?:estado|diagn[oó]stico)\s+de(?:l)?\s+engram|diagn[oó]stica\s+(?:a\s+)?engram"
                  r"|qu[eé]\s+tal\s+(?:va|anda|est[aá])\s+engram"
                  r"|(?:funciona|responde)\s+engram\b|engram\s+(?:funciona|responde)\b"
                  r"|c[oó]mo\s+(?:va|est[aá])\s+engram",
        # v23 (T4): la memoria operativa se puede consultar y corregir de viva voz.
        "rules": r"(?:qu[eé]|cu[aá]les)\s+(?:reglas|normas)\s+(?:tienes|sigues|te\s+he\s+dado|hay)"
                 r"|\bmis\s+reglas\b|reglas\s+de\s+comportamiento"
                 r"|c[oó]mo\s+sabes\s+(?:c[oó]mo\s+)?(?:que\s+)?(?:trabajo|quiero\s+trabajar)"
                 r"|qu[eé]\s+(?:has\s+)?aprendido\s+de\s+c[oó]mo\s+trabajo"
                 r"|memoria\s+operativa",
        "forget_rule": r"olvida\s+(?:la\s+|esa\s+|esta\s+)?(?:regla|norma|preferencia|"
                       r"restricci[oó]n|correcci[oó]n)\s*(?:de\s+|que\s+|:)?\s*(?P<q>.+)",
        "save": r"(?:recuerda|apunta|anota|guarda)\s+"
               r"(?:un[a]?\s+(?P<tipo>bug(?:fix)?|decisi[oó]n(?:\s+de\s+arquitectura)?|arquitectura|feature|funcionalidad)\s+)?"
               r"(?:en\s+(?:el\s+)?|del?\s+)(?:proyecto|c[oó]digo|engram|nexus)(?:\s+(?:de\s+)?nexus)?"
               r"[\s,:]*(?:que\s+)?[\s,:]*(?P<hecho>.+)",
        "context": r"contexto\s+del\s+proyecto(?:\s+nexus)?\s*\??\s*$"
                  r"|resumen\s+del\s+proyecto(?:\s+nexus)?\s*\??\s*$"
                  r"|qu[eé]\s+sabe\s+engram(?:\s+del\s+proyecto)?\s*\??\s*$"
                  r"|qu[eé]\s+(?:se\s+ha\s+|se\s+)?decidido\s+[uú]ltimamente\s+en\s+el\s+proyecto\s*\??\s*$",
        "search": r"qu[eé]\s+(?:se\s+)?decidi[oó]\s+(?:en\s+el\s+proyecto\s+)?sobre\s+(?P<q1>.+)"
                 r"|busca\s+en\s+(?:el\s+)?(?:proyecto|c[oó]digo|engram)[\s,:]+(?P<q2>.+)"
                 r"|qu[eé]\s+sabe\s+engram\s+(?:del\s+proyecto\s+)?sobre\s+(?P<q3>.+)",
    },
}


def _map_tipo(tipo_raw: str) -> str:
    """Heurística tolerante a acentos/variantes: del texto capturado (tal
    cual lo escribió Adri) al vocabulario fijo que usa Engram."""
    t = (tipo_raw or "").lower()
    if "bug" in t:
        return "bugfix"
    if "arquitect" in t:
        return "architecture"
    if "decisi" in t:
        return "decision"
    if "feature" in t or "funcionalidad" in t:
        return "feature"
    return "note"


async def handle(intent: str, text: str, match, ctx) -> dict:
    from backend.core import engram_bridge as eng

    if intent == "status":
        info = eng.status_sync(ctx)
        if not info["installed"]:
            return {"reply": "🧠 Engram no está instalado — es opcional (memoria de proyecto "
                             "compartida con Claude Code/Cursor/Codex si lo usas). Instálalo si "
                             "te interesa; mientras tanto sigo con mi memoria normal, sin problema."}
        if await eng.alive_cached(ctx):
            n = await eng.count(ctx)
            return {"reply": f"🧠 Engram conectado ✔ ({info['url']}) — {n} recuerdos de proyecto "
                             "guardados hasta ahora."}
        if await eng.ensure_up(ctx):          # diagnóstico fresco: intenta levantarlo YA
            return {"reply": f"🧠 Engram estaba parado, lo acabo de arrancar ✔ ({info['url']})."}
        return {"reply": f"🧠 Engram está instalado ({info['exe']}) pero no consigo levantarlo: "
                         f"{eng.status_sync(ctx)['last_error'] or 'sin más detalle'}."}

    if intent == "save":
        gd = match.groupdict() if match else {}
        hecho = (gd.get("hecho") or "").strip().rstrip(".")
        if not hecho:
            return {"reply": "¿Qué apunto exactamente en la memoria del proyecto?"}
        tipo = _map_tipo(gd.get("tipo") or "")
        # v23 (T4): la fuente de verdad es la memoria operativa LOCAL (sobrevive
        # aunque Engram no esté levantado); el servidor de Engram es el espejo
        # para compartirlo con Claude Code/Cursor/Codex.
        from backend.core import opmem
        rec = opmem.remember(hecho, kind=("tecnico" if tipo in ("architecture", "bugfix")
                                          else opmem.clasifica(hecho)),
                             scope="global", source="operador")
        r = await eng.save(ctx, hecho[:60], hecho, kind=tipo)
        espejo = ("Tus otras herramientas de IA conectadas a Engram también lo verán."
                  if r["ok"] else
                  f"(El servidor de Engram no está disponible ahora — {r['error'][:80]} — "
                  "pero lo tengo guardado igual en mi memoria y lo aplicaré.)")
        return {"reply": f"🧠 Guardado como {rec.get('kind', tipo)}: «{hecho[:160]}». {espejo}"}

    if intent == "rules":
        from backend.core import opmem
        reglas = opmem.all_rules(limit=12)
        if not reglas:
            return {"reply": "🧠 Todavía no me has fijado ninguna regla de trabajo. Dime cosas "
                             "como «a partir de ahora, antes de borrar enséñame qué vas a borrar» "
                             "y las aplico siempre."}
        st = opmem.stats()
        lines = [f"🧠 Así es como sé que quieres trabajar ({st['vivos']} recuerdos vivos):"]
        for r in reglas:
            lines.append(f"   · [{r['kind']}] {r['text'][:150]}")
        lines.append("Para quitar una: «olvida la regla ...».")
        return {"reply": "\n".join(lines), "data": st}

    if intent == "forget_rule":
        from backend.core import opmem
        gd = match.groupdict() if match else {}
        q = (gd.get("q") or "").strip().rstrip(".?¿")
        if not q:
            return {"reply": "¿Qué regla quieres que olvide? Dime un trozo de su texto."}
        n = opmem.forget(q)
        return {"reply": (f"🧠 Olvidadas {n} regla(s) que casaban con «{q}»." if n else
                          f"No tengo ninguna regla que case con «{q}». Di «mis reglas» para verlas.")}

    if intent == "context":
        texto = await eng.context(ctx)
        if texto:
            return {"reply": "🧠 " + texto.strip()}
        if not eng.installed(ctx):
            return {"reply": "🧠 Engram no está instalado todavía, así que no tengo memoria de "
                             "proyecto que enseñarte."}
        return {"reply": "🧠 Engram está conectado pero todavía no hay nada guardado del proyecto. "
                         "Dime «recuerda en el proyecto que...» y empiezo a apuntar."}

    if intent == "search":
        gd = match.groupdict() if match else {}
        query = (gd.get("q1") or gd.get("q2") or gd.get("q3") or "").strip().rstrip("?¿.")
        if not query:
            return {"reply": "¿Sobre qué quieres que busque en la memoria del proyecto?"}
        hits = await eng.search(ctx, query)
        if not hits:
            if not eng.installed(ctx):
                return {"reply": "🧠 Engram no está instalado, así que no puedo buscar en la "
                                 "memoria de proyecto."}
            return {"reply": f"🧠 No encuentro nada guardado sobre «{query}» en la memoria del "
                             "proyecto. Dímelo con «recuerda en el proyecto que...» y lo fijo."}
        lines = [f"🧠 Esto encontré sobre «{query}» en la memoria del proyecto:"]
        for h in hits:
            lines.append(f"• [{h.get('type', 'nota')}] {h.get('title', '')}: "
                         f"{(h.get('content', '') or '')[:180]}")
        return {"reply": "\n".join(lines)}

    return {"reply": "🧠 Esa orden de Engram no la tengo. Prueba «mis reglas», «recuerda en el proyecto que...», "
                     "«qué se decidió sobre...», «contexto del proyecto» o «está engram conectado»."}
