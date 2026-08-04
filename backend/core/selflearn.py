"""
nexus — AUTO-REENTRENAMIENTO ("aprende de mí").

Además de recordar órdenes exactas (ver brain._learn_*), nexus DESTILA con el
mejor razonador disponible (Fable / claude-fable-5) un PERFIL del operador a partir
de sus conversaciones y de las órdenes que funcionan. Ese perfil se inyecta en el
system prompt → el asistente responde y decide cada vez más a medida de Adri, y se
re-genera SOLO cada N interacciones (o cuando se le dice «reentrénate»).

Ficheros en data/:
  interactions.jsonl   → registro ligero de interacciones (rotado a las últimas N)
  operator_profile.md  → perfil destilado (lo que se inyecta al modelo)
  selflearn.json       → contadores/estado
"""
from __future__ import annotations

import json
import time

from .comun.config import DATA_DIR, settings

_INTER = DATA_DIR / "interactions.jsonl"
_PROFILE = DATA_DIR / "operator_profile.md"
_STATE = DATA_DIR / "selflearn.json"
_MAX_INTER = 400            # se conservan las últimas N interacciones
_RETRAIN_EVERY = 25         # auto-reentrena cada N interacciones nuevas
_MIN_INTER = 6              # mínimo para que valga la pena destilar
_retraining = False


def _load_state() -> dict:
    try:
        return json.loads(_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"since": 0, "total": 0, "last": 0.0}


def _save_state(s: dict) -> None:
    try:
        _STATE.parent.mkdir(parents=True, exist_ok=True)
        _STATE.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _rotate() -> None:
    try:
        lines = _INTER.read_text(encoding="utf-8").splitlines()
        if len(lines) > _MAX_INTER:
            _INTER.write_text("\n".join(lines[-_MAX_INTER:]) + "\n", encoding="utf-8")
    except Exception:
        pass


def record_interaction(text: str, reply: str, skill, ok: bool = True) -> bool:
    """Apunta una interacción. Devuelve True si ya toca auto-reentrenar."""
    text = (text or "").strip()
    if not text:
        return False
    try:
        _INTER.parent.mkdir(parents=True, exist_ok=True)
        with _INTER.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": text, "r": (reply or "")[:300],
                                "skill": skill or "", "ok": bool(ok)},
                               ensure_ascii=False) + "\n")
        _rotate()
    except Exception:
        pass
    s = _load_state()
    s["since"] = s.get("since", 0) + 1
    s["total"] = s.get("total", 0) + 1
    _save_state(s)
    return s["since"] >= _RETRAIN_EVERY


def _recent(n: int = 150) -> list[dict]:
    out = []
    try:
        for line in _INTER.read_text(encoding="utf-8").splitlines()[-n:]:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    except Exception:
        pass
    return out


def operator_profile() -> str:
    """El perfil destilado, para inyectar en el system prompt. '' si no hay."""
    try:
        return _PROFILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def stats() -> dict:
    s = _load_state()
    return {"total": s.get("total", 0), "since": s.get("since", 0),
            "has_profile": bool(operator_profile()), "last": s.get("last", 0.0)}


async def retrain(force: bool = False) -> str:
    """Destila (con Fable si hay key) un perfil del operador a partir de las
    interacciones. Devuelve el nuevo perfil, o '' si no procede/falla."""
    global _retraining
    if _retraining:
        return ""
    s = _load_state()
    if not force and s.get("since", 0) < _RETRAIN_EVERY:
        return ""
    inter = _recent(150)
    if len(inter) < _MIN_INTER and not force:
        return ""
    if len(inter) < 2:
        return ""
    _retraining = True
    try:
        from . import llm
        op = settings.get("operator_name", "el operador")
        muestras = "\n".join(
            f'- «{d.get("t", "")[:120]}»' + (f' → [{d["skill"]}]' if d.get("skill") else "")
            for d in inter[-120:])
        prev = operator_profile()
        sysmsg = (
            "Eres el módulo de AUTO-MEJORA de nexus, un asistente personal tipo JARVIS. "
            f"DESTILA un perfil útil de {op} a partir de sus interacciones, para que el "
            "asistente responda y decida cada vez más a su medida. Devuelve SOLO el perfil "
            "en markdown BREVE (máx 12 líneas), con estas secciones: "
            "**Tono y estilo** (cómo habla y cómo quiere que le hablen); "
            "**Temas y proyectos recurrentes**; "
            "**Atajos y formas propias de pedir cosas** (mapea sus expresiones a lo que quiere); "
            "**Preferencias y cosas a evitar**. "
            "Nada de relleno ni de explicar lo que haces: SOLO el perfil, concreto y accionable.")
        usermsg = (f"PERFIL ACTUAL (mejóralo e incorpóralo, no lo repitas literal):\n"
                   f"{prev or '(todavía vacío)'}\n\n"
                   f"ÚLTIMAS INTERACCIONES de {op} (frase → skill/minion usado):\n{muestras}")
        profile = await llm.distill(sysmsg, usermsg, max_tokens=900)
        if profile and len(profile.strip()) > 30:
            _PROFILE.parent.mkdir(parents=True, exist_ok=True)
            _PROFILE.write_text(profile.strip(), encoding="utf-8")
            s["since"] = 0
            s["last"] = time.time()
            _save_state(s)
            return profile.strip()
        return ""
    finally:
        _retraining = False
