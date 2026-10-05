"""Minion IA/Multimedia — imágenes, visión, transcripción Whisper y búsqueda web.

OJO ROUTER: esta carpeta es la PRIMERA en orden alfabético, así que sus
patrones se prueban antes que los de TODAS las demás skills. Toda regex
lleva ancla de dominio (imagen/foto, audio, «en internet»...) para no robar
frases ajenas: «haz una foto» (webcam, system_pc), «busca X en google maps»
(places), «investiga X» (research)... quedan fuera a propósito.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
from pathlib import Path
from urllib.parse import urlparse


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
                         r"(?:en\s+)?(?:la\s+|esta\s+|el\s+)?(?:imagen|foto(?:graf[ií]a)?|captura)\s+(?P<path>.+)",
        # Transcribir audio (Whisper local): ruta obligatoria, coletilla opcional.
        "transcribe": r"(?:transcr[ií]be(?:me)?|p[aá]sa(?:me)?\s+a\s+texto)\s+"
                      r"(?:el\s+|la\s+|este\s+|esta\s+)?(?:audio|nota\s+de\s+voz|grabaci[oó]n|memo\s+de\s+voz)\s+"
                      r"(?P<path>.+)$",
        # Búsqueda web: con ancla explícita («en internet/la web/google»,
        # «googlea», «qué dice internet de...»). google(?!\s*maps) deja los mapas
        # a la skill places; «investiga...» se queda en research (informes).
        # La cuarta alternativa se ancla en el SUSTANTIVO («busca información
        # sobre X»): sin ella esa frase, que es de las normales, caía al
        # planificador. El lookahead devuelve a su dueño lo que se busca en un
        # sitio concreto: carpetas (files), notas (memory_graph) y mapas (places).
        "web_search": r"(?:\b(?:busca|b[uú]scame|buscar|consulta(?:me)?|mira(?:me)?)\s+(?:r[aá]pido\s+)?"
                      r"en\s+(?:internet|la\s+web|la\s+red|google(?!\s*maps)|el\s+buscador|duckduckgo)\s+"
                      r"|\bgoogl[eé]a(?:me)?\s+"
                      r"|qu[eé]\s+dice\s+(?:internet|google|la\s+web)\s+(?:de|sobre)\s+"
                      r"|\b(?:busca|b[uú]scame|buscar|consulta(?:me)?|inf[oó]rmame)\s+"
                      r"(?:informaci[oó]n|info|datos|referencias)\s+(?:sobre|de|acerca\s+de)\s+"
                      r"(?!.*\ben\s+(?:la\s+carpeta|el\s+(?:mapa|grafo|disco|directorio)|"
                      r"mis?\s+(?:notas|apuntes|documentos|archivos)|drive|google\s*maps|maps)\b))"
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


_COMILLAS = "\"'“”‘’"


def _resolver_ruta(raw: str) -> tuple[Path | None, str]:
    """(archivo existente, ruta tal como se escribió). Admite comillas y espacios en la ruta, y
    recorta coletillas («... por favor», «... y guárdala») hasta dar con un archivo que exista."""
    escrito = raw.strip().strip(_COMILLAS).strip()
    palabras = escrito.split(" ")
    for n in range(len(palabras), 0, -1):
        cand = " ".join(palabras[:n]).strip(_COMILLAS).strip()
        if cand:
            p = Path(cand).expanduser()
            if p.is_file():
                return p, escrito
    return None, escrito


_EXT_IMAGEN = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".ico", ".svg"}


def _tam(n: int) -> str:
    if n < 1024:
        return f"{n} bytes"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _fuentes(results: list[dict]) -> str:
    """Dominios de las fuentes, sin repetir (lo que el usuario puede VER; `data` no se muestra)."""
    vistos: list[str] = []
    for r in results:
        d = urlparse(r.get("url") or "").netloc.removeprefix("www.")
        if d and d not in vistos:
            vistos.append(d)
    return ", ".join(vistos[:5])


async def handle(intent: str, text: str, match, ctx) -> dict:
    if intent == "gen_image":
        prompt = match.group("prompt").strip().rstrip(".")
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = OUT_DIR / f"gen-{dt.datetime.now():%Y%m%d-%H%M%S}.svg"
        out.write_text(SVG.format(prompt=html.escape(prompt[:48])), encoding="utf-8")   # el texto del usuario NO es SVG
        return {"reply": f"🎨 Boceto de «{prompt}» listo en data/captures/{out.name}.\n"
                         "Aún no tengo un motor de imagen real conectado: es una tarjeta SVG "
                         "de previsualización. Para arte de verdad, conecta Stable Diffusion "
                         "(API de Automatic1111) o DALL·E en skills/ai_media/skill.py — el "
                         "hueco está marcado. Di «analiza la imagen <ruta>» y te examino "
                         "cualquier archivo que ya tengas.",
                "data": {"file": str(out)}}

    if intent == "analyze_image":
        path, escrito = _resolver_ruta(match.group("path"))
        if path is None:
            return {"reply": f"✖ No encuentro la imagen {escrito}. Pásame la ruta completa "
                             "(p. ej. «analiza la imagen D:\\fotos\\logo.png») y voy."}
        tam = _tam(path.stat().st_size)
        dims = ""
        try:
            from PIL import Image
            with Image.open(path) as im:
                dims = f", {im.width}×{im.height}px, modo {im.mode}"
        except ImportError:
            pass                                    # sin Pillow: solo el tamaño
        except Exception:
            if path.suffix.lower() not in _EXT_IMAGEN:
                return {"reply": f"📄 {path.name} ({tam}) no es una imagen que pueda abrir. Con "
                                 "imágenes (png, jpg, gif, webp…) te doy tamaño y dimensiones."}
            dims = " (no he podido abrirla como imagen: ¿archivo dañado?)"
        return {"reply": f"🖼 {path.name}: {tam}{dims}.\n"
                         "Eso es lo que veo sin ojos: metadatos. Para describir el CONTENIDO "
                         "necesito un modelo de visión — instala llava en Ollama "
                         "(«ollama pull llava») y conéctalo en skills/ai_media/skill.py. "
                         "Mientras, si es un audio lo que tienes, di «transcribe el audio "
                         "<ruta>» y eso sí lo hago entero."}

    if intent == "transcribe":
        # Transcripción de archivos de audio (wav/mp3/ogg/m4a) + ideas principales
        import asyncio
        path, escrito = _resolver_ruta(match.group("path"))
        if path is None:
            return {"reply": f"✖ No encuentro el audio {escrito}. Dame la ruta completa "
                             "(«transcribe el audio D:\\notas\\reunion.mp3») y lo paso a texto."}
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            return {"reply": "⚠ Me falta el motor de transcripción. Se arregla en un minuto: "
                             "«pip install faster-whisper» en el entorno de nexus y repite "
                             "la orden — el resto ya está listo."}

        def _run():
            from backend.core.infraestructura.stt import _get_model
            segments, info = _get_model().transcribe(str(path), language="es",
                                                     vad_filter=True)
            return " ".join(s.text.strip() for s in segments)

        texto = await asyncio.to_thread(_run)
        if not texto.strip():
            return {"reply": f"El audio {path.name} no contiene voz reconocible. Si es música "
                             "o ruido, ahí no hay nada que transcribir."}

        from backend.core.infraestructura.llm import ask_llm
        analysis, prov = await ask_llm(
            "De esta transcripción extrae en español: **Ideas principales** (3-5 puntos), "
            "**Tareas detectadas** (si las hay) y **Lluvia de ideas** (2-3 ideas que se "
            f"derivan de lo dicho):\n\n{texto[:5000]}")
        # Proveedor «ninguno» = NO hay respuesta del modelo: su mensaje de error no es un análisis.
        con_analisis = prov != "ninguno"
        # Persistir en memoria: el audio ENTERO (nota completa y base de datos en trozos).
        from backend.core.dominio import rag
        from backend.core.dominio.memory import graph, pg
        huella = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:6]
        titulo = f"audio {path.stem[:28]} {huella}"      # la huella evita que dos audios se pisen
        cuerpo_analisis = f"---\n{analysis}\n\n" if con_analisis else "---\n(sin análisis: el modelo no estaba disponible)\n\n"
        graph.write_note(titulo, f"Transcripción de {path.name}:\n\n{texto}\n\n"
                                 f"{cuerpo_analisis}Enlaces: [[audios]] [[conocimiento]]")
        trozos = 0
        if pg.online:
            for t in rag.trocear(texto):
                pg.remember(f"[audio {path.name}] {t['texto']}", kind="knowledge", tags=["audio"])
                trozos += 1
        donde = (f"en la nota «{titulo}» y en la memoria de conocimiento ({trozos} trozo(s))"
                 if trozos else f"en la nota «{titulo}» (la base de datos no está disponible: "
                                "solo quedó la nota)")
        cabecera = f"✔ Transcrito {path.name} ({len(texto)} caracteres) y guardado {donde}"
        if not con_analisis:
            return {"reply": f"{cabecera}.\n\nNo pude analizarlo (el modelo no está disponible): "
                             f"{analysis}\nCuando lo esté, di «qué recuerdas de {path.stem[:20]}»."}
        return {"reply": f"{cabecera}:\n\n{analysis[:900]}\n\nDi «qué recuerdas de "
                         f"{path.stem[:20]}» cuando quieras volver sobre esto."}

    if intent == "web_search":
        q = match.group("q").strip().rstrip("?¿.")
        from backend.core.infraestructura import websearch
        results = await websearch.search(q, 6)
        if not results:
            return {"reply": f"✖ No he podido buscar «{q}»: o no hay conexión o los tres "
                             "buscadores que pruebo (Google News, DDG Lite, DDG HTML) no han "
                             "respondido. Reintenta en un momento; si persiste, revisa la red."}
        from backend.core.infraestructura.llm import ask_llm
        answer, prov = await ask_llm(
            "Con estos RESULTADOS DE BÚSQUEDA WEB responde de forma concreta y ACTUAL a la "
            f"pregunta: «{q}». Da nombres, fechas y datos si los hay; no digas que no se sabe "
            f"si la información está en los resultados. Sé breve.\n\nRESULTADOS:\n"
            + websearch.summarize(results))
        fuentes = [r.get("url") for r in results if r.get("url")][:5]
        if prov == "ninguno":
            # Sin modelo no hay respuesta: se enseña lo que SÍ se encontró, no solo el error.
            lista = "\n".join(f"• {r.get('title') or r.get('url')} — {r.get('url')}" for r in results[:5])
            return {"reply": f"No pude redactar la respuesta (el modelo no está disponible), pero "
                             f"esto es lo que encontré sobre «{q}»:\n{lista}\nMotivo: {answer}",
                    "data": {"sources": fuentes}}
        return {"reply": f"{answer}\n\nFuentes: {_fuentes(results)}", "speak": True,
                "data": {"sources": fuentes}}

    return {"reply": "Orden multimedia no reconocida. Prueba «genera una imagen de X», "
                     "«analiza la imagen <ruta>», «transcribe el audio <ruta>» o "
                     "«busca en internet X»."}
