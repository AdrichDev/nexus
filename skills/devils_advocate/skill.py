"""Minion Devil's Advocate — cuestiona, detecta fallos y corrige sin complacencia."""
from __future__ import annotations

SKILL = {
    "name": "Devil's Advocate",
    "description": "Contrapunto crítico bajo demanda: steelman, puntos débiles, riesgos ocultos y veredicto sobre tus ideas y planes",
    "patterns": {
        # -- modo permanente ON (específico, va antes que critique) --
        "on": r"activa(?:me)?\s+(?:el\s+)?modo\s+(?:abogado\s+del\s+diablo|cr[ií]tico)"
              r"|modo\s+(?:abogado\s+del\s+diablo|cr[ií]tico)\s+on"
              r"|ponte\s+(?:en\s+)?modo\s+(?:abogado\s+del\s+diablo|cr[ií]tico)"
              r"|s[eé]\s+(?:m[aá]s\s+)?cr[ií]tic[oa]\s+conmigo",
        # -- modo permanente OFF --
        "off": r"desactiva(?:me)?\s+(?:el\s+)?modo\s+(?:abogado\s+del\s+diablo|cr[ií]tico)"
               r"|modo\s+(?:abogado\s+del\s+diablo|cr[ií]tico)\s+off"
               r"|quita(?:me)?\s+(?:el\s+)?modo\s+(?:abogado\s+del\s+diablo|cr[ií]tico)"
               r"|deja\s+de\s+ser\s+tan\s+cr[ií]tic[oa]",
        # -- crítica puntual de una idea/plan (el más amplio, al final) --
        "critique": r"(?:abogado\s+del\s+diablo\s*[:,]"
                    r"|haz(?:me)?\s+de\s+abogado\s+del\s+diablo\s+(?:con|sobre)"
                    r"|crit[ií]ca(?:me)?\s+(?:esta\s+|este\s+|mi\s+|el\s+|la\s+)?"
                    r"(?:idea|planes|plan|propuesta|estrategia|decisi[oó]n|enfoque|proyecto|razonamiento|esto)\s*(?:de\s+|sobre\s+|[:,]\s*)?"
                    r"|cuestiona(?:me)?\s+(?:mi|este|esta|el|la)\s+"
                    r"(?:plan|idea|propuesta|estrategia|decisi[oó]n|enfoque|razonamiento)\s*(?:de\s+|sobre\s+|[:,]\s*)?"
                    r"|b[uú]scale\s+(?:las\s+)?pegas\s+a"
                    r"|qu[eé]\s+pegas\s+le\s+ves\s+a"
                    r"|destroza(?:me)?\s+(?:esta\s+|este\s+|mi\s+)?(?:idea|plan|propuesta)\s*[:,]?"
                    r"|pon\s+a\s+prueba\s+(?:mi|esta|este)\s+(?:idea|plan|razonamiento)\s*[:,]?"
                    r")\s*(?P<idea>.+)",
    },
}

CRITIQUE_PROMPT = """Actúa como abogado del diablo profesional. Analiza esta idea/plan
del operador con honestidad brutal pero constructiva:

«{idea}»

Responde EXACTAMENTE con esta estructura, en español, conciso:
**Steelman** — la versión más fuerte de la idea (1-2 frases)
**Puntos débiles** — 2-3 debilidades concretas del razonamiento
**Riesgos ocultos** — 2 riesgos que probablemente no está viendo
**Veredicto** — tu opinión sincera: ¿adelante, adelante con condiciones, o repensar? ¿Por qué?"""


async def critique(idea: str) -> str:
    """Usada también por la skill coach para validar sus specs internas."""
    from backend.core.llm import ask_llm
    reply, _ = await ask_llm(CRITIQUE_PROMPT.format(idea=idea[:3000]))
    return reply


async def handle(intent: str, text: str, match, ctx) -> dict:
    settings = ctx["settings"]

    if intent == "on":
        settings.set("devil_mode", True)
        return {"reply": "Modo abogado del diablo ACTIVADO ⚖. A partir de ahora cada respuesta "
                         "lleva su contrapunto crítico: no esperes que te dé la razón por deporte. "
                         "Di «desactiva el modo abogado del diablo» cuando quieras volver a la paz."}

    if intent == "off":
        settings.set("devil_mode", False)
        return {"reply": "Modo abogado del diablo desactivado ✔. Sigo siendo honesto —si veo un "
                         "error te lo digo—, pero sin contrapunto sistemático. Para retomarlo: "
                         "«activa el modo abogado del diablo»."}

    if intent == "critique":
        idea = match.group("idea").strip()
        try:
            return {"reply": await critique(idea)}
        except Exception as exc:                               # noqa: BLE001
            return {"reply": "No he podido consultar el modelo para la crítica "
                             f"({type(exc).__name__}: {exc}). Revisa el proveedor y la clave "
                             "del núcleo IA en ⚙ y repite la orden: la idea no se ha perdido."}

    return {"reply": "No he pillado qué quieres del abogado del diablo. Prueba: "
                     "«abogado del diablo: <tu idea>», «critica mi plan de <lo que sea>» "
                     "o «activa el modo abogado del diablo» para el contrapunto permanente."}
