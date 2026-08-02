"""Minion IA/Multimedia — imágenes, visión, transcripción Whisper y búsqueda web.

OJO ROUTER: esta carpeta es la PRIMERA en orden alfabético, así que sus
patrones se prueban antes que los de TODAS las demás skills. Toda regex
lleva ancla de dominio (imagen/foto, audio, «en internet»...) para no robar
frases ajenas: «haz una foto» (webcam, system_pc), «busca X en google maps»
(places), «investiga X» (research)... quedan fuera a propósito.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path


OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "captures"

SKILL = {
    "name": "IA / Multimedia",
    "description": "Bocetos de imagen IA, análisis de fotos, transcripción de audios con Whisper y respuestas con búsqueda web real multi-fuente",
    # ORDEN: específico arriba, amplio abajo (web_search es el más ancho y va último).
    "patterns": {
        # Generar imagen: exige un sustantivo de imagen tras el verbo. El lookahead
        # evita robar «haz una foto con la webcam» (system_pc) o «...de la pantalla».
        "gen_image": r"(?:g[eé]n[eé]ra(?:me)?|cr[eé]a(?:me)?|dib[uú]ja(?:me)?|dis[eé][ñn]a(?:me)?|haz(?:me)?)\s+"
                     r"(?:una?\s+)?(?:imagen|ilustraci[oó]n|dibujo|logo(?:tipo)?|cartel|p[oó]ster|foto)\s+"
                     r"(?:de|con|sobre|para)\s+"
                     r"(?!(?:la\s+)?(?:webcam|c[aá]mara|pantalla)\b)(?P<prompt>.+)",
        # Analizar imagen: necesita la RUTA del archivo (named group path).
        "analyze_image": r"(?:anal[ií]za(?:me)?|descr[ií]be(?:me)?|exam[ií]na(?:me)?|interpreta(?:me)?|qu[eé]\s+(?:hay|ves|sale))\s+"
                         r"(?:en\s+)?(?:la\s+|esta\s+|el\s+)?(?:imagen|foto(?:graf[ií]a)?|captura)\s+(?P<path>\S+)",
        # Transcribir audio (Whisper local): ruta obligatoria, coletilla opcional.
        "transcribe": r"(?:transcr[ií]be(?:me)?|p[aá]sa(?:me)?\s+a\s+texto)\s+"
                      r"(?:el\s+|la\s+|este\s+|esta\s+)?(?:audio|nota\s+de\s+voz|grabaci[oó]n|memo\s+de\s+voz)\s+"
                      r"(?P<path>.+?)(\s+y\s+(?P<extra>.+))?$",
        # Búsqueda web: SIEMPRE con ancla explícita («en internet/la web/google»,
        # «googlea», «qué dice internet de...»). google(?!\s*maps) deja los mapas
        # a la skill places; «investiga...» se queda en research (informes).
        "web_search": r"(?:\b(?:busca|b[uú]scame|buscar|consulta(?:me)?|mira(?:me)?)\s+(?:r[aá]pido\s+)?"
                      r"en\s+(?:internet|la\s+web|la\s+red|google(?!\s*maps)|el\s+buscador|duckduckgo)\s+"
                      r"|\bgoogl[eé]a(?:me)?\s+"
                      r"|qu[eé]\s+dice\s+(?:internet|google|la\s+web)\s+(?:de|sobre)\s+)"
                      r"(?P<q>.+)",
    },
}

SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512">
<rect width="512" height="512" fill="#02120a"/>
<circle cx="256" cy="256" r="140" fill="none" stroke="#00ff9c" stroke-width="3" opacity="0.8"/>
<circle cx="256" cy="256" r="90" fill="none" stroke="#00ff9c" stroke-width="1.5" opacity="0.5"/>
<text x="50%" y="47%" fill="#00ff9c" font-family="monospace" font-size="20"
 text-anchor="middle">nexus IMAGE ENGINE</text>
<text x="50%" y="55%" fill="#7dffce" font-family="monospace" font-size="13"
 text-anchor="middle">{prompt}</text>
<text x="50%" y="92%" fill="#0a7d55" font-family="monospace" font-size="11"
 text-anchor="middle">boceto — conecta SD/DALL-E en skills/ai_media</text></svg>"""


async def handle(intent: str, text: str, match, ctx) -> dict:
    if intent == "gen_image":
        prompt = match.group("prompt").strip().rstrip(".")
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = OUT_DIR / f"gen-{dt.datetime.now():%Y%m%d-%H%M%S}.svg"
        out.write_text(SVG.format(prompt=prompt[:48]), encoding="utf-8")
        return {"reply": f"🎨 Boceto de «{prompt}» listo en data/captures/{out.name}.\n"
                         "Aún no tengo un motor de imagen real conectado: es una tarjeta SVG "
                         "de previsualización. Para arte de verdad, conecta Stable Diffusion "
                         "(API de Automatic1111) o DALL·E en skills/ai_media/skill.py — el "
                         "hueco está marcado. Di «analiza la imagen <ruta>» y te examino "
                         "cualquier archivo que ya tengas.",
                "data": {"file": str(out)}}

    if intent == "analyze_image":
        path = Path(match.group("path").strip().strip('"')).expanduser()
        if not path.is_file():
            return {"reply": f"✖ No encuentro la imagen {path}. Pásame la ruta completa "
                             "(p. ej. «analiza la imagen D:\\fotos\\logo.png») y voy."}
        size_kb = path.stat().st_size / 1024
        dims = ""
        try:
            from PIL import Image
            with Image.open(path) as im:
                dims = f", {im.width}×{im.height}px, modo {im.mode}"
        except Exception:
            pass
        return {"reply": f"🖼 {path.name}: {size_kb:.0f} KB{dims}.\n"
                         "Eso es lo que veo sin ojos: metadatos. Para describir el CONTENIDO "
                         "necesito un modelo de visión — instala llava en Ollama "
                         "(«ollama pull llava») y conéctalo en skills/ai_media/skill.py. "
                         "Mientras, si es un audio lo que tienes, di «transcribe el audio "
                         "<ruta>» y eso sí lo hago entero."}

    if intent == "transcribe":
        # Transcripción de archivos de audio (wav/mp3/ogg/m4a) + ideas principales
        import asyncio
        raw = match.group("path").strip().strip('"').strip("'")
        path = Path(raw).expanduser()
        if not path.is_file():
            return {"reply": f"✖ No encuentro el audio {path}. Dame la ruta completa "
                             "(«transcribe el audio D:\\notas\\reunion.mp3») y lo paso a texto."}
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            return {"reply": "⚠ Me falta el motor de transcripción. Se arregla en un minuto: "
                             "«pip install faster-whisper» en el entorno de nexus y repite "
                             "la orden — el resto ya está listo."}

        def _run():
            from backend.core.stt import _get_model
            segments, info = _get_model().transcribe(str(path), language="es",
                                                     vad_filter=True)
            return " ".join(s.text.strip() for s in segments)

        texto = await asyncio.to_thread(_run)
        if not texto.strip():
            return {"reply": f"El audio {path.name} no contiene voz reconocible. Si es música "
                             "o ruido, ahí no hay nada que transcribir."}

        from backend.core.llm import ask_llm
        analysis, _ = await ask_llm(
            "De esta transcripción extrae en español: **Ideas principales** (3-5 puntos), "
            "**Tareas detectadas** (si las hay) y **Lluvia de ideas** (2-3 ideas que se "
            f"derivan de lo dicho):\n\n{texto[:5000]}")
        # Persistir en memoria
        from backend.core.memory import graph, pg
        graph.write_note(f"audio {path.stem[:36]}",
                         f"Transcripción de {path.name}:\n\n{texto[:15000]}\n\n"
                         f"---\n{analysis}\n\nEnlaces: [[audios]] [[conocimiento]]")
        if pg.online:
            pg.remember(f"[audio {path.name}] {texto[:2000]}", kind="knowledge",
                        tags=["audio"])
        return {"reply": f"✔ Transcrito {path.name} ({len(texto)} caracteres) y guardado en "
                         f"memoria:\n\n{analysis[:900]}\n\nDi «qué recuerdas de "
                         f"{path.stem[:20]}» cuando quieras volver sobre esto."}

    if intent == "web_search":
        q = match.group("q").strip().rstrip("?¿.")
        from backend.core import websearch
        results = await websearch.search(q, 6)
        if not results:
            return {"reply": f"✖ No he podido buscar «{q}»: o no hay conexión o los tres "
                             "buscadores que pruebo (Google News, DDG Lite, DDG HTML) no han "
                             "respondido. Reintenta en un momento; si persiste, revisa la red."}
        from backend.core.llm import ask_llm
        answer, _prov = await ask_llm(
            "Con estos RESULTADOS DE BÚSQUEDA WEB responde de forma concreta y ACTUAL a la "
            f"pregunta: «{q}». Da nombres, fechas y datos si los hay; no digas que no se sabe "
            f"si la información está en los resultados. Sé breve.\n\nRESULTADOS:\n"
            + websearch.summarize(results))
        return {"reply": answer, "speak": True,
                "data": {"sources": [r.get("url") for r in results if r.get("url")][:5]}}

    return {"reply": "Orden multimedia no reconocida. Prueba «genera una imagen de X», "
                     "«analiza la imagen <ruta>», «transcribe el audio <ruta>» o "
                     "«busca en internet X»."}
