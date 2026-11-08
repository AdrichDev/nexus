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

PRECEDENCIA DEL ENRUTADO (ARQ-04, tarea T23): cuando dos intents casan la misma
frase, gana el que tenga más prioridad declarada en `SKILL["priority"] =
{intent: entero}` (opcional, por defecto 0). Si empatan —el caso normal, porque
nadie declara nada— se queda el ORDEN DECLARADO: carpetas por orden alfabético y,
dentro de cada una, los intents en el orden en que están escritos en el dict. Ese
orden es determinista y está a la vista en el código; lo que NO es una decisión es
que una carpeta nueva llamada «aaa» se cuele por delante de todas sin querer.
"""
from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass, field

from ..comun.config import SKILLS_DIR


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
    priority: dict = field(default_factory=dict)   # intent -> entero (ARQ-04)


_registry: dict[str, Skill] = {}


def _prioridades(meta: dict) -> dict:
    """`SKILL["priority"] = {intent: entero}`: precedencia declarada del enrutado.

    Es OPCIONAL y tolerante a propósito: un intent sin declarar vale 0, y un valor
    que no sea un entero (o un `priority` que no sea un dict) se ignora en vez de
    marcar la skill entera como `error` — una errata en un número no puede dejar
    una skill sin atender.
    """
    bruto = meta.get("priority")
    if not isinstance(bruto, dict):
        return {}
    limpias = {}
    for intent, valor in bruto.items():
        if isinstance(valor, bool):          # True/False no son prioridades
            continue
        try:
            limpias[str(intent)] = int(valor)
        except (TypeError, ValueError):
            continue
    return limpias


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
                priority=_prioridades(meta),
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


def _en_orden_de_prioridad(skills):
    """Las (prioridad, skill, intent, regex) en el orden en que hay que probarlas.

    Ordena de más prioridad a menos y deja los empates como estaban (el `sort` de
    Python es estable): el orden del registro, que es el declarado. Con todo a 0
    —lo normal— la lista sale exactamente en el orden de siempre.
    """
    entradas = []
    for skill in skills:
        if skill.status == "error":
            continue
        prioridades = getattr(skill, "priority", None) or {}
        for intent, rx in skill.patterns.items():
            entradas.append((prioridades.get(intent, 0), skill, intent, rx))
    entradas.sort(key=lambda entrada: -entrada[0])
    return entradas


def route(text: str):
    """Devuelve (skill, intent, match) del intent de MÁS prioridad que case, o None.

    Dentro de la misma prioridad gana el orden declarado (carpetas alfabéticas,
    intents como están escritos). Sin prioridades declaradas esto es, byte a byte,
    la primera regex que casa en el orden de siempre (ARQ-04, tarea T23).
    """
    for _prioridad, skill, intent, rx in _en_orden_de_prioridad(get_skills().values()):
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
