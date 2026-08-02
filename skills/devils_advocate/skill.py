"""Minion Devil's Advocate — cuestiona, detecta fallos y corrige sin complacencia."""
from __future__ import annotations

SKILL = {
    "name": "Devil's Advocate",
    "description": "Contrapunto crítico bajo demanda: steelman, puntos débiles, riesgos ocultos y veredicto sobre tus ideas y planes",
    "patterns": {
        # OJO AL \b: sin él «desactiva el modo…» casa dentro con «activa» y el
        # apagado se vuelve inalcanzable. Por eso «off» va además ANTES que «on».
        "off": r"\bdesact[ií]va(?:me)?\s+(?:el\s+)?modo\s+(?:abogado\s+del\s+diablo|cr[ií]tico)"
               r"|modo\s+(?:abogado\s+del\s+diablo|cr[ií]tico)\s+off"
               r"|\bqu[ií]ta(?:me)?\s+(?:el\s+)?modo\s+(?:abogado\s+del\s+diablo|cr[ií]tico)"
               r"|\bdeja\s+de\s+ser\s+tan\s+cr[ií]tic[oa]",
        "on": r"\bact[ií]va(?:me)?\s+(?:el\s+)?modo\s+(?:abogado\s+del\s+diablo|cr[ií]tico)"
              r"|modo\s+(?:abogado\s+del\s+diablo|cr[ií]tico)\s+on\b"
              r"|\bponte\s+(?:en\s+)?modo\s+(?:abogado\s+del\s+diablo|cr[ií]tico)"
              r"|\bs[eé]\s+(?:m[aá]s\s+)?cr[ií]tic[oa]\s+conmigo",
        # -- crítica puntual de una idea/plan (el más amplio, al final) --
        "critique": r"(?:\babogado\s+del\s+diablo\s*[:,]"
                    r"|\bhaz(?:me)?\s+de\s+abogado\s+del\s+diablo\s+(?:con|sobre)"
                    r"|\bcrit[ií]ca(?:me)?\s+(?:esta\s+|este\s+|mi\s+|el\s+|la\s+)?"
                    r"(?:idea|planes|plan|propuesta|estrategia|decisi[oó]n|enfoque|proyecto|razonamiento|esto)\s*(?:de\s+|sobre\s+|[:,]\s*)?"
                    r"|\bcuesti[oó]na(?:me)?\s+(?:mi|este|esta|el|la)\s+"
                    r"(?:plan|idea|propuesta|estrategia|decisi[oó]n|enfoque|razonamiento)\s*(?:de\s+|sobre\s+|[:,]\s*)?"
                    r"|\bb[uú]scale\s+(?:las\s+)?pegas\s+a"
                    r"|\bqu[eé]\s+pegas\s+le\s+ves\s+a"
                    r"|\bdestroza(?:me)?\s+(?:esta\s+|este\s+|mi\s+)?(?:idea|plan|propuesta)\s*[:,]?"
                    r"|\bpon\s+a\s+prueba\s+(?:mi|esta|este)\s+(?:idea|plan|razonamiento)\s*[:,]?"
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
    if intent == "on":
        return {"reply": "El modo abogado del diablo ya va puesto SIEMPRE ⚖: la instrucción está "
                         "en mi prompt de sistema, así que antes de contestarte cuestiono mis "
                         "propias suposiciones y te corrijo si partes de un dato equivocado. "
                         "No hay nada que encender. Lo que sí puedo darte a demanda es el "
                         "análisis completo en cuatro partes: «abogado del diablo: <tu idea>»."}

    if intent == "off":
        return {"reply": "Eso no se apaga ⚖: el contrapunto crítico es parte de cómo razono, no "
                         "un extra opcional (⚙ Configuración lo dice: «SIEMPRE ACTIVO, no "
                         "apagable»). Lo que no hago es soltarte un informe crítico sin venir a "
                         "cuento: el análisis en cuatro partes solo sale si lo pides con "
                         "«abogado del diablo: <tu idea>»."}

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
