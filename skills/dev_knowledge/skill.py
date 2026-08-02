"""Minion Biblioteca de conocimiento — carga las SKILL.md de openClaw/Gru
bajo demanda y las aplica vía el LLM."""
from __future__ import annotations

from pathlib import Path

KNOWLEDGE = Path(__file__).resolve().parents[2] / "knowledge"

SKILL = {
    "name": "Biblioteca dev (openClaw)",
    "description": ("Guías de desarrollo openClaw/Gru (SDD, PRs, revisión judgment-day...): "
                    "las carga bajo demanda y las aplica a tu encargo con el LLM"),
    # Orden del dict: listar y aplicar (específicos) antes que la detección automática.
    "patterns": {
        "list": r"(qu[eé]|cu[aá]les|lista|ens[eé][ñn]ame|mu[eé]strame)[^.]{0,25}skills?\s+de\s+(desarrollo|dev)\b"
                r"|skills?\s+de\s+(desarrollo|dev)\s+(tienes|hay|conoces)"
                r"|biblioteca\s+de\s+skills?|skills?\s+importad"
                r"|qu[eé]\s+metodolog[ií]as\s+(tienes|conoces|hay)",
        # El \b evita que «usa» o «crea» casen dentro de otra palabra («pausa…»).
        "apply": r"\b(?:apl[ií]ca(?:me)?|usa|sigue)\s+(?:la\s+)?(?:skill|metodolog[ií]a|gu[ií]a)\s+"
                 r"(?P<name>[\w\-]+)\s+(?:a|para|en|sobre|con)\s+(?P<task>.+)",
        "auto": r"(\brev[ií]sa(?:me)?(?:lo)?\s+(?:esto\s+)?como\s+judgment(?:[- ]day)?"
                r"|\bc[oó]mo\s+(?:hago|creo|abro|preparo)\s+un\s+(?:pr|pull\s+request)"
                r"|\bspec[- ]driven"
                r"|\bcr[eé]a(?:me)?\s+una\s+spec(?:\s+sdd)?"
                r"|\bonboarding\s+del\s+(?:proyecto|repo))\s*(?P<task2>.*)",
    },
}


def _catalog() -> dict[str, Path]:
    out = {}
    if KNOWLEDGE.is_dir():
        for md in KNOWLEDGE.rglob("SKILL.md"):
            out[md.parent.name] = md
    return out


def _match_skill(query: str, cat: dict) -> str | None:
    q = query.lower()
    for name in cat:
        if name.replace("-", " ") in q or name in q:
            return name
    keywords = {"pr": "branch-pr", "pull request": "branch-pr", "commit": "work-unit-commits",
                "spec": "sdd-spec", "revisa": "judgment-day", "revisión": "judgment-day",
                "test": "go-testing", "issue": "issue-creation", "onboard": "sdd-onboard",
                "documenta": "cognitive-doc-design", "comenta": "comment-writer",
                "crear skill": "skill-creator", "mejora skill": "skill-improver"}
    for k, v in keywords.items():
        if k in q and v in cat:
            return v
    return None


async def handle(intent: str, text: str, match, ctx) -> dict:
    cat = _catalog()
    if not cat:
        return {"reply": "⚠ La biblioteca de conocimiento está vacía: no hay ninguna carpeta "
                         "con SKILL.md dentro de `knowledge/` (en la raíz del proyecto). "
                         "Copia ahí las skills de openClaw/Gru (una carpeta por skill, cada "
                         "una con su SKILL.md) y vuelve a preguntarme «qué skills de dev tienes»."}

    if intent == "list":
        names = sorted(cat.keys())
        return {"reply": f"📚 Tengo {len(names)} skills de desarrollo importadas de openClaw/Gru:\n"
                         + " · ".join(names) +
                         "\n\nDi «aplica la skill <nombre> a <tu encargo>» y la sigo al pie de "
                         "la letra (ej.: «aplica la skill sdd-spec a mi sistema de login»)."}

    name = None
    task = ""
    if intent == "apply":
        name = match.group("name")
        task = match.group("task")
    else:
        name = _match_skill(text, cat)
        task = match.groupdict().get("task2") or text

    if not name or name not in cat:
        return {"reply": f"⚠ No tengo ninguna skill llamada así en la biblioteca. "
                         f"Las que hay: {', '.join(sorted(cat))}. "
                         "Di «aplica la skill <una de esas> a <tu encargo>»."}

    guide = cat[name].read_text(encoding="utf-8", errors="replace")[:6000]
    from backend.core.llm import ask_llm
    reply, _ = await ask_llm(
        f"Aplica esta metodología/skill al encargo del operador.\n\n"
        f"=== SKILL: {name} ===\n{guide}\n\n=== ENCARGO ===\n{task}\n\n"
        "Responde siguiendo la skill, en español, accionable.")
    return {"reply": f"📚 [skill: {name}]\n{reply}"}
