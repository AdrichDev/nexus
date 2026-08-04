# -*- coding: utf-8 -*-
"""Minion Núcleo IA — qué cerebro tiene nexus puesto AHORA MISMO.

Qué modelo y qué proveedor usa nexus es un dato de HECHO que está en su propia
configuración: se LEE de `settings` y se contesta. No pasa por el LLM, así que
no se puede razonar mal ni inventar. «Núcleo IA» es la sección del HUD donde se
elige el cerebro, no una plataforma externa.
"""
from __future__ import annotations

# ── Vocabulario ──────────────────────────────────────────────────────────────
# Los sustantivos que SÍ hablan del cerebro de nexus. «núcleo» a secas entra
# porque es el nombre literal que sale en la barra lateral («Núcleo IA»), pero
# se descarta si detrás viene «del problema», «de la cuestión», «del procesador»…
_NUCLEO = (r"n[uú]cleo(?!s)(?:\s+de\s+(?:ia|inteligencia\s+artificial))?"
           r"(?!\s+(?:del?\s+)?(?:problema|asunto|cuesti[oó]n|tema|debate|"
           r"procesador|cpu|gpu|gr[aá]fica|equipo|kernel))")
_MODELO = r"modelo(?!\s+de\s+(?:coche|moto|negocio|datos|neg|3d|ropa|avi[oó]n))"

SKILL = {
    "name": "Núcleo IA",
    "description": ("Qué cerebro (proveedor y modelo) tiene nexus puesto ahora mismo, "
                    "leído de la configuración real — nunca supuesto"),
    "intents": {
        "cual": "dice qué proveedor y qué modelo de IA está usando nexus en este momento, "
                "si está verificado y cómo cambiarlo",
    },
    "patterns": {
        # Tres formas de preguntar lo mismo. La primera NO exige verbo: «pero
        # qué modelo de IA» es una frase entera para un humano.
        "cual": (
            # a) sustantivo inequívoco, con o sin verbo detrás
            r"\b(?:qu[eé]|cu[aá]l)\s+(?:es\s+)?(?:el\s+|la\s+|tu\s+|ese\s+|este\s+)?"
            r"(?:" + _NUCLEO + r"|" + _MODELO + r"\s+de\s+(?:ia|lenguaje|inteligencia\s+artificial)"
            r"|cerebro|llm|motor\s+de\s+ia)\b"
            # b) sustantivo más genérico, pero con verbo de uso detrás
            r"|\b(?:con\s+|en\s+|de\s+)?(?:qu[eé]|cu[aá]l)\s+(?:es\s+)?(?:el\s+|la\s+|tu\s+)?"
            r"(?:" + _MODELO + r"|ia|inteligencia\s+artificial|proveedor)\b[^?\n]{0,30}?"
            r"\b(?:usas?|utilizas?|est[aá]s?\s+(?:usando|utilizando|trabajando|corriendo|"
            r"ejecutando|tirando)|tienes|llevas|corres|trabajas|funcionas|eres|hay|va)\b"
            # c) la pregunta directa de identidad
            r"|\bqu[eé]\s+(?:ia|modelo|llm)\s+eres\b"
            r"|\bqui[eé]n\s+te\s+(?:mueve|hace\s+funcionar)\b"
        ),
    },
}

# Cómo se llama cada proveedor para un humano, y de qué ajuste sale su modelo.
_PROVEEDORES = {
    "ollama":    ("Ollama", "en tu propio equipo, sin coste por mensaje y sin salir a internet", "ollama_model"),
    "openai":    ("OpenAI", "en la nube, con tu clave de OpenAI", "openai_model"),
    "anthropic": ("Anthropic (Claude)", "en la nube, con tu clave de Anthropic", "anthropic_model"),
    "gemini":    ("Google Gemini", "en la nube, con tu clave de Google", "gemini_model"),
    "cloud":     ("OpenRouter (u otro compatible con OpenAI)", "en la nube, con tu clave de OpenRouter", "cloud_model"),
    "mock":      ("Simulado", "NO es una IA de verdad: devuelve respuestas de prueba", "cloud_model"),
}


def _ajustes(ctx):
    s = (ctx or {}).get("settings")
    if s is not None:
        return s
    from backend.core.comun.config import settings
    return settings


def datos(ctx=None) -> dict:
    """Lo que hay puesto, tal cual. Sin red y sin interpretación."""
    s = _ajustes(ctx)
    prov = str(s.get("llm_provider", "") or "").strip().lower()
    nombre, donde, campo = _PROVEEDORES.get(prov, (prov or "sin definir", "", ""))
    modelo = str(s.get(campo, "") or "").strip() if campo else ""
    d = {"proveedor": prov, "proveedor_nombre": nombre, "donde": donde,
         "modelo": modelo, "campo_modelo": campo,
         "verificado": False, "latencia_ms": 0, "error": "", "modelo_probado": ""}
    try:
        from backend.core import llm_runtime
        st = llm_runtime.status()
        d["verificado"] = bool(st.active and st.verified)
        d["latencia_ms"] = int(st.latency_ms or 0)
        d["error"] = str(st.error_public or "")
        d["modelo_probado"] = str(st.model or "")
    except Exception:
        pass
    return d


def texto(d: dict) -> str:
    """El parte, en cristiano. Cada línea sale de un ajuste real."""
    if not d["proveedor"]:
        return ("No tengo ningún núcleo de IA puesto: el ajuste está vacío. "
                "Elige uno en ⚙ Configuración → Núcleo IA y lo pruebo al momento.")

    lineas = ["◈ **Núcleo IA** — esto es lo que tengo puesto ahora mismo:", ""]
    lineas.append(f"· **Proveedor**: {d['proveedor_nombre']}"
                  + (f" — {d['donde']}" if d["donde"] else ""))
    lineas.append(f"· **Modelo**: {d['modelo'] or '(sin elegir)'}")

    if d["verificado"]:
        lineas.append(f"· **Probado**: sí, ha contestado de verdad"
                      + (f" ({d['latencia_ms']} ms)" if d["latencia_ms"] else ""))
    elif d["error"]:
        lineas.append(f"· **Probado**: NO — {d['error']}")
    else:
        lineas.append("· **Probado**: todavía no ha contestado a ninguna prueba, "
                      "así que no te lo doy por bueno.")

    # Si el que respondió no es el que pone la configuración, se dice.
    probado = d["modelo_probado"]
    if probado and d["modelo"] and probado != d["modelo"]:
        lineas.append(f"· ⚠ Ojo: el que ha contestado de verdad es «{probado}», "
                      f"no «{d['modelo']}».")

    if d["proveedor"] == "mock":
        lineas.append("· ⚠ «Simulado» no piensa nada: devuelve texto de relleno. "
                      "No te fíes de nada de lo que conteste.")

    lineas += ["",
               "Núcleo IA no es ninguna plataforma externa: es la sección de nexus "
               "donde eliges el cerebro. Para cambiarlo, ⚙ Configuración → Núcleo IA."]
    return "\n".join(lineas)


async def handle(intent: str, text: str, match, ctx) -> dict:
    d = datos(ctx)
    return {"reply": texto(d), "data": {"nucleo": d}}
