"""
nexus — AUTO-REENTRENAMIENTO ("aprende de mí").

Además de recordar órdenes exactas (ver brain._learn_*), nexus DESTILA con el
mejor razonador disponible (Fable / claude-fable-5) un PERFIL del operador a partir
de sus conversaciones y de las órdenes que funcionan. Ese perfil se inyecta en el
system prompt → el asistente responde y decide cada vez más a medida del operador, y se
re-genera SOLO cada N interacciones (o cuando se le dice «reentrénate»).

Ficheros en data/:
  interactions.jsonl   → registro ligero de interacciones (rotado a las últimas N)
  operator_profile.md  → perfil destilado (lo que se inyecta al modelo)
  selflearn.json       → contadores/estado
"""
from __future__ import annotations

import json
import re
import time

from ..comun.config import DATA_DIR, settings

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


# ══════════════════════════════════════════════════════════════════════════
#  EL ANTECEDENTE Y LA GENERALIZACION — lo que este modulo le presta a 004
# ══════════════════════════════════════════════════════════════════════════
# El perfil deja de servir solo para engordar el prompt: aqui expone las dos
# cosas que el proponente de reglas necesita y que no puede sacar de ningun
# otro sitio sin importar el cerebro.

def ultima_orden(excluir: str = "") -> str:
    """La ultima frase del operador que NO es `excluir`, o '' si no hay.

    Es el respaldo de `brain._history` cuando la correccion llega por un canal
    que no comparte ese historial en RAM (el puente de mensajeria, una segunda
    ventana). Se lee de `interactions.jsonl`, que es lo unico que sobrevive a un
    reinicio."""
    fuera = normaliza(excluir)
    for d in reversed(_recent(40)):
        t = (d.get("t") or "").strip()
        if t and (not fuera or normaliza(t) != fuera):
            return t
    return ""


def normaliza(s: str) -> str:
    """Minusculas, espacios colapsados y sin signos en los extremos.

    ES PUBLICA A PROPOSITO. Esta misma linea vivia copiada tres veces —aqui, en
    `brain` y en `aprendizaje`— y las tres se justificaban con «no puedo
    importar la otra». Era verdad y era irrelevante: las dos de `aplicacion` SI
    pueden importar `dominio`, que es donde tiene que vivir una regla de
    normalizacion. Tres copias sin un test que las vigilara es como divergen dos
    frases que deberian ser la misma: `observa()` normaliza para comparar y
    `ultima_orden()` para excluir, asi que separarlas hace que la propia
    correccion vuelva como antecedente de si misma."""
    return re.sub(r"\s+", " ", (s or "").strip().lower().strip("¿?¡!.,;:")).strip()


# Hueco de inversion: quien sepa hablar con el modelo lo rellena desde arriba.
# Sin rellenar NO hay generalizacion, y el proponente se queda con el patron
# literal. Es mas estrecho, pero es valido: el aprendizaje degrada, no
# desaparece.
_generalizador = None


def registrar_generalizador(fn) -> None:
    """Guarda quien sabe ensanchar un patron (el modelo). Opcional a proposito."""
    global _generalizador
    _generalizador = fn


def generaliza_patron(frase: str) -> str:
    """Un patron MAS ANCHO que la frase literal, o '' si no lo hay.

    EL MODELO NO EMITE UN VEREDICTO: lo que devuelve es ENTRADA de las puertas,
    nunca una autorizacion. Aqui solo se comprueban las cuatro cosas que hacen
    que merezca la pena molestar a las puertas con ello:

      1. esta anclado por los dos lados —igual que exige la puerta de forma—,
      2. su FORMA no es peligrosa (se pregunta a `reglas._forma_peligrosa`),
      3. compila,
      4. y CASA LA FRASE QUE LO ORIGINO.

    La cuarta es la que convierte «generalizar» en algo comprobable. Un patron
    que ya no casa su propia frase no es una version ancha de esa regla: es otra
    regla distinta, colada por la puerta de atras y sin que nadie la haya pedido.

    Devolver '' no es un fallo: es el camino normal cuando no hay modelo."""
    frase = (frase or "").strip()
    if not frase or _generalizador is None:
        return ""
    try:
        candidato = str(_generalizador(frase) or "").strip()
    except Exception:                                      # noqa: BLE001
        return ""
    if not candidato:
        return ""
    if not (candidato.startswith("^") and candidato.endswith("$")):
        return ""
    # LA FORMA SE MIRA ANTES DE EJECUTAR EL PATRON, y no despues.
    #
    # La comprobacion de abajo lo hace correr contra la frase. Un patron de
    # retroceso catastrofico salido del modelo colgaria el proceso AQUI, antes
    # de que ninguna puerta llegara a verlo. Se pregunta a la misma funcion que
    # usa la puerta de forma: dos listas de formas peligrosas se separan al
    # primer descubrimiento nuevo.
    from . import reglas as _reglas
    if _reglas._forma_peligrosa(candidato):
        return ""
    try:
        if not re.search(candidato, frase, re.IGNORECASE):
            return ""
    except re.error:
        return ""
    return candidato


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
        from ..infraestructura import llm
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
