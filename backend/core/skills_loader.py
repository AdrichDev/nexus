"""
nexus — Cargador de skills modulares.

Cada skill es una CARPETA dentro de /skills con:
  * SKILL.md   — descripción legible (el cerebro la carga bajo demanda como contexto)
  * skill.py   — código con dos elementos obligatorios:
        SKILL = {"name": str, "description": str, "patterns": {intent: regex}}
        async def handle(intent, text, match, ctx) -> dict
           → {"reply": str, "data": ..., "speak": bool}

Para AÑADIR una skill: crea la carpeta, escribe ambos archivos y reinicia
(o llama a reload_skills()). Nada más — el router la registra solo.
"""
from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass, field

from .config import SKILLS_DIR


@dataclass
class Skill:
    name: str
    folder: str
    description: str
    patterns: dict            # intent -> regex compilada
    module: object
    doc: str = ""             # SKILL.md
    status: str = "ready"     # ready | active | error
    calls: int = 0
    extra: dict = field(default_factory=dict)


_registry: dict[str, Skill] = {}


def load_skills() -> dict[str, Skill]:
    _registry.clear()
    for folder in sorted(SKILLS_DIR.iterdir()):
        py = folder / "skill.py"
        if not folder.is_dir() or not py.exists():
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"skills.{folder.name}", py)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            meta = getattr(mod, "SKILL")
            doc_file = folder / "SKILL.md"
            skill = Skill(
                name=meta["name"],
                folder=folder.name,
                description=meta.get("description", ""),
                patterns={
                    intent: re.compile(rx, re.IGNORECASE)
                    for intent, rx in meta.get("patterns", {}).items()
                },
                module=mod,
                doc=doc_file.read_text(encoding="utf-8") if doc_file.exists() else "",
            )
            _registry[folder.name] = skill
        except Exception as exc:
            _registry[folder.name] = Skill(
                name=folder.name, folder=folder.name,
                description=f"ERROR al cargar: {exc}", patterns={}, module=None,
                status="error",
            )
    return _registry


def get_skills() -> dict[str, Skill]:
    return _registry or load_skills()


def route(text: str):
    """Devuelve (skill, intent, match) para la primera regex que case, o None."""
    for skill in get_skills().values():
        if skill.status == "error":
            continue
        for intent, rx in skill.patterns.items():
            m = rx.search(text)
            if m:
                return skill, intent, m
    return None


def skills_summary() -> list[dict]:
    return [
        {"folder": s.folder, "name": s.name, "description": s.description,
         "status": s.status, "calls": s.calls, "intents": list(s.patterns.keys())}
        for s in get_skills().values()
    ]
