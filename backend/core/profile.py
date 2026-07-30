"""
nexus — PERFIL DEL OPERADOR + consolidación nocturna de memoria (v20/v21).

Dos piezas:

1. build_profile(): «quién soy» / «mi perfil» / «háblame de mí» — respuesta
   CORTA y NATURAL, como la daría alguien que te conoce, no una ficha de
   estadísticas. Usa el perfil destilado por el auto-reentrenamiento
   (selflearn) si lo hay, reescrito en prosa corrida (sin cabeceras
   markdown ni viñetas). Los NÚMEROS de actividad (tareas, contactos,
   vigilancias, encargos, informes...) NO salen aquí: eso se pregunta aparte
   («cuántas tareas tengo», «mis informes»...) y ya lo cubren otras skills;
   mezclarlo en «quién soy» es precisamente lo que lo hacía sonar a informe
   robótico.

2. consolidate_daily(): de madrugada, el registro diario del grafo de AYER se
   RESUME con el LLM en una nota «resumen AAAA-MM-DD» (y a la memoria RAG si
   hay DB). El diario queda marcado para no re-consolidarlo. Así la memoria
   mejora con el uso en vez de solo engordar.
"""
from __future__ import annotations

import datetime as dt
import re

from .config import DATA_DIR, settings

_MARK = "<!--consolidado-->"


# ─────────────────────────────── perfil ───────────────────────────────

# Una línea que ES solo una cabecera de sección («**Tono y estilo**», a
# veces con «:» final) y NADA más → es una etiqueta, se descarta entera.
_MD_HEADER_ONLY_RX = re.compile(r"^\*\*[^*]+\*\*:?\s*$")
# Cabecera + contenido en la MISMA línea («**Tono y estilo**: cercano») →
# se queda solo el contenido, la etiqueta sobra.
_MD_HEADER_INLINE_RX = re.compile(r"^\*\*[^*]+\*\*:\s+(.+)$")
# Negrita DENTRO de una frase («Prefiere respuestas **cortas** y directas»,
# o una expresión citada «**"está todo arrancado"**») → se DESENNEGRECE
# (se conserva el texto, solo se quitan los `**`); nunca se borra el
# contenido, que es justo lo que antes se perdía.
_MD_BOLD_RX = re.compile(r"\*\*([^*]+)\*\*")
_MD_BULLET_RX = re.compile(r"^[\-•*]\s*")


def _perfil_natural(md: str, max_chars: int = 260) -> str:
    """Convierte el perfil markdown destilado (cabeceras **X** + viñetas) en
    frases corridas, SIN cabeceras ni viñetas — para que suene a algo que
    diría una persona, no a un informe. A diferencia de un simple "borra los
    **", las cabeceras PURAS (sin contenido en su línea) se descartan porque
    son solo una etiqueta, pero la negrita DENTRO de una frase se conserva
    (se desennegrece, no se borra) para no perder lo que dice. Si no hay
    nada aprendido, devuelve ''."""
    texto = (md or "").strip()
    if not texto:
        return ""
    frases = []
    for linea in texto.splitlines():
        l = linea.strip()
        if not l or _MD_HEADER_ONLY_RX.match(l):
            continue
        m = _MD_HEADER_INLINE_RX.match(l)
        if m:
            l = m.group(1).strip()
        # OJO al orden: la negrita se desennegrece ANTES de tocar viñetas.
        # Al revés, un «**Odia**...» sin guión delante lo pillaba el regex de
        # viñeta «[\-•*]» (que también matchea UN solo «*»), comiéndose solo
        # el primer «*» del «**» y dejando un «*Odia**» roto sin desenvolver
        # (hallazgo de la QA sonnet — el bug de negrita-borrada de opus no
        # quedaba cerrado del todo).
        l = _MD_BOLD_RX.sub(r"\1", l)
        l = _MD_BULLET_RX.sub("", l).strip(" .")
        if l:
            frases.append(l)
    resumen = ". ".join(frases)
    if len(resumen) > max_chars:
        corte = resumen[:max_chars]
        if " " in corte:               # no partir una palabra por la mitad
            corte = corte.rsplit(" ", 1)[0]
        return corte.rstrip(",;: ") + "…"
    return resumen.rstrip(",;: ")


def build_profile() -> str:
    """«Quién soy» — una respuesta breve y cercana, no una ficha técnica."""
    quien = (settings.get("operator_name", "") or "").strip()
    try:
        from . import selflearn
        aprendido = _perfil_natural(selflearn.operator_profile())
    except Exception:
        aprendido = ""
    punto = "" if aprendido.endswith((".", "…", "!", "?")) else "."

    if quien and aprendido:
        return f"Eres {quien}. {aprendido}{punto}"
    if quien:
        return (f"Eres {quien}. Todavía no tengo mucho aprendido de ti — cuanto más "
                "hablemos, mejor te conoceré (o di «reentrénate» para forzarlo ya).")
    if aprendido:
        return f"{aprendido}{punto} (No tengo tu nombre configurado en ⚙ → operador todavía.)"
    return ("Aún no sé gran cosa de ti: ni te tengo configurado en ⚙ → operador ni he "
           "aprendido un perfil todavía. Sigue hablándome con naturalidad y me voy afinando.")


# ───────────────────────── consolidación nocturna ─────────────────────────

def _daily_file(day: dt.date):
    # mismo convenio que NoteGraph._daily_path (data/memory/diario-AAAA-MM-DD.md)
    from .memory import graph
    try:
        return graph._daily_path(day)
    except Exception:
        return DATA_DIR / "memory" / "daily" / f"{day.isoformat()}.md"


def consolidation_pending(now: dt.datetime | None = None) -> bool:
    """¿Hay un diario de AYER sin consolidar y ya es de madrugada (>=4h)? PURA
    respecto al reloj que se le pase (testeable)."""
    now = now or dt.datetime.now()
    if now.hour < 4:
        return False
    f = _daily_file(now.date() - dt.timedelta(days=1))
    try:
        if not f.exists():
            return False
        txt = f.read_text(encoding="utf-8")
        return _MARK not in txt and len(txt.strip()) > 300
    except Exception:
        return False


_busy = {"on": False}     # anti-doble disparo si el LLM tarda más que el ciclo


async def consolidate_daily(now: dt.datetime | None = None) -> bool:
    """Resume el diario de ayer en una nota permanente + memoria RAG. Marca el
    diario para no repetir. Devuelve True si consolidó."""
    now = now or dt.datetime.now()
    if _busy["on"] or not consolidation_pending(now):
        return False
    _busy["on"] = True
    try:
        return await _consolidate(now)
    finally:
        _busy["on"] = False


async def _consolidate(now: dt.datetime) -> bool:
    day = now.date() - dt.timedelta(days=1)
    f = _daily_file(day)
    try:
        raw = f.read_text(encoding="utf-8")
    except Exception:
        return False
    try:
        import asyncio as _a
        from .llm import ask_llm
        summary, _prov = await _a.wait_for(ask_llm(
            "Resume este registro diario del operador en 4-6 viñetas CONCRETAS "
            "(decisiones, datos, personas, pendientes que sigan vivos). Sin relleno, "
            "en español:\n\n" + raw[:8000]), timeout=180)
    except Exception:
        return False
    if not (summary or "").strip():
        return False
    try:
        import asyncio as _a
        from .memory import graph, pg
        await _a.to_thread(graph.write_note, f"resumen {day.isoformat()}",
                           summary.strip() + f"\n\nEnlaces: [[diario-{day.isoformat()}]]")
        if pg.online:
            await _a.to_thread(pg.remember,
                               f"[Resumen del {day.isoformat()}] {summary.strip()[:800]}",
                               "knowledge", ["resumen-diario"])
        await _a.to_thread(lambda: f.write_text(raw.rstrip() + f"\n\n{_MARK}\n",
                                                encoding="utf-8"))
    except Exception:
        return False
    try:
        from .events import bus
        await bus.emit("log", {"level": "ok",
                               "msg": f"🧠 Memoria consolidada: resumen del {day:%d/%m} guardado"})
    except Exception:
        pass
    return True
