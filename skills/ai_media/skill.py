"""Minion Audio y búsqueda web — transcribe audios/vídeos con Whisper y responde con la web.

Hace SOLO dos cosas, las dos reales:
  * transcribir un audio o vídeo local con Whisper (marcas de tiempo, análisis, memoria);
  * responder una pregunta con búsqueda web: lee las mejores páginas y cita las fuentes.
(La generación de imágenes y la «visión» se eliminaron: eran un SVG de relleno y metadatos.)

OJO ROUTER: esta carpeta es la PRIMERA en orden alfabético, así que sus patrones se prueban
antes que los de TODAS las demás skills. Toda regex lleva ancla de dominio (audio, «en
internet»...) para no robar frases ajenas: «busca X en google maps» (places), «investiga X»
(research)... quedan fuera a propósito.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
from pathlib import Path
from urllib.parse import urlparse

SKILL = {
    "name": "Audio y búsqueda web",
    "description": "Transcribe audios y vídeos con Whisper local (marcas de tiempo y análisis) y responde con búsqueda web leyendo las páginas y citando las fuentes",
    # ORDEN: específico arriba, amplio abajo (web_search es el más ancho y va último).
    "patterns": {
        # Transcribir audio/vídeo (Whisper local): la ruta es TODO lo que sigue (puede llevar
        # espacios); `_resolver_ruta` recorta coletillas («... y guárdala») hasta dar con el archivo.
        "transcribe": r"(?:transcr[ií]be(?:me)?|p[aá]sa(?:me)?\s+a\s+texto)\s+"
                      r"(?:el\s+|la\s+|este\s+|esta\s+)?(?:audio|nota\s+de\s+voz|grabaci[oó]n|memo\s+de\s+voz|v[ií]deo)\s+"
                      r"(?P<path>.+)$",
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

# ----------------------------------------------------------------------------------------------
#  Rutas
# ----------------------------------------------------------------------------------------------
_COMILLAS = "\"'“”‘’"
_EXT_AUDIO = {".mp3", ".wav", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".flac", ".wma",
              ".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"}


def _resolver_ruta(raw: str) -> tuple[Path | None, str]:
    """(archivo existente, ruta tal como se escribió). Admite comillas y espacios en la ruta, y
    recorta coletillas («… por favor», «… y guárdala») hasta dar con un archivo que exista."""
    escrito = raw.strip().strip(_COMILLAS).strip()
    palabras = escrito.split(" ")
    for n in range(len(palabras), 0, -1):
        cand = " ".join(palabras[:n]).strip(_COMILLAS).strip()
        if cand:
            p = Path(cand).expanduser()
            if p.is_file():
                return p, escrito
    return None, escrito


def _mmss(segundos: float) -> str:
    s = int(max(0, segundos))
    h, resto = divmod(s, 3600)
    m, s = divmod(resto, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _dominio(url: str | None) -> str:
    return urlparse(url or "").netloc.removeprefix("www.")


# ----------------------------------------------------------------------------------------------
#  Búsqueda web: lee las páginas, cita las fuentes
# ----------------------------------------------------------------------------------------------
_PAGINAS_A_LEER = 3          # cuántas de las primeras páginas se leen de verdad
_CHARS_PAGINA = 1800         # cuánto de cada página se le pasa al modelo
_TIMEOUT_PAGINA = 8.0        # segundos máximos por página: una lenta no bloquea la respuesta


async def _leer_paginas(results: list[dict]) -> list[str]:
    from backend.core.infraestructura import websearch

    async def una(r: dict) -> str:
        url = r.get("url") or ""
        if not url:
            return ""
        try:
            return await asyncio.wait_for(websearch.fetch_page(url, max_chars=_CHARS_PAGINA),
                                          _TIMEOUT_PAGINA)
        except Exception:
            return ""

    return list(await asyncio.gather(*[una(r) for r in results[:_PAGINAS_A_LEER]]))


def _lista_fuentes(results: list[dict]) -> str:
    return "\n".join(f"[{i}] {_dominio(r.get('url')) or 'web'} — {(r.get('title') or r.get('url') or '').strip()}"
                     for i, r in enumerate(results, 1))


async def _buscar_y_responder(q: str) -> dict:
    from backend.core.infraestructura import websearch
    from backend.core.infraestructura.llm import ask_llm
    results = await websearch.search(q, 6)
    if not results:
        return {"reply": f"✖ No he podido buscar «{q}»: o no hay conexión o los buscadores que pruebo "
                         "no han respondido. Reintenta en un momento; si persiste, revisa la red."}
    paginas = await _leer_paginas(results)
    fuentes_prompt = []
    for i, r in enumerate(results, 1):
        leido = paginas[i - 1] if i - 1 < len(paginas) else ""
        cuerpo = leido or (r.get("snippet") or "")      # si la página no se pudo leer, su fragmento
        fuentes_prompt.append(f"[{i}] {r.get('title') or ''} ({_dominio(r.get('url'))})\n{cuerpo}")
    answer, prov = await ask_llm(
        f"Hoy es {dt.date.today():%d/%m/%Y}. Responde a la pregunta «{q}» usando SOLO las FUENTES "
        "numeradas de abajo. Cita cada dato con su número entre corchetes, p. ej. [1]. Si las fuentes "
        "no contienen la respuesta, di claramente que no la has encontrado en ellas en lugar de "
        "suponer. Sé breve (máximo 6 líneas) y responde en español.\n\nFUENTES:\n"
        + "\n\n".join(fuentes_prompt))
    urls = [r.get("url") for r in results if r.get("url")][:6]
    if prov == "ninguno":
        # Sin modelo no hay respuesta: se enseña lo que SÍ se encontró, no solo el error.
        lista = "\n".join(f"• {r.get('title') or r.get('url')} — {r.get('url')}" for r in results[:5])
        return {"reply": f"No pude redactar la respuesta (el modelo no está disponible), pero esto es lo "
                         f"que encontré sobre «{q}»:\n{lista}\nMotivo: {answer}",
                "data": {"sources": urls}}
    return {"reply": f"{answer}\n\nFuentes:\n{_lista_fuentes(results)}", "speak": True,
            "data": {"sources": urls}}


# ----------------------------------------------------------------------------------------------
#  Transcripción: audio ENTERO, análisis por bloques, memoria sin duplicados
# ----------------------------------------------------------------------------------------------
_BLOQUE = 6000               # caracteres de transcripción por llamada de análisis
_MAX_BLOQUES = 6             # tope de bloques analizados (el resto se guarda, pero no se analiza)
_PEDIDO = ("extrae en español: **Ideas principales** (3-5 puntos), **Tareas detectadas** (si las "
           "hay) y **Lluvia de ideas** (2-3 ideas que se derivan de lo dicho)")


async def _analizar(texto: str) -> tuple[str, str, int]:
    """(análisis, proveedor, caracteres analizados). Recorre el texto por bloques y consolida."""
    from backend.core.infraestructura.llm import ask_llm
    cuerpo = texto[:_BLOQUE * _MAX_BLOQUES]
    bloques = [cuerpo[i:i + _BLOQUE] for i in range(0, len(cuerpo), _BLOQUE)]
    if len(bloques) == 1:
        analisis, prov = await ask_llm(f"De esta transcripción {_PEDIDO}:\n\n{bloques[0]}")
        return analisis, prov, len(cuerpo)
    parciales = []
    for i, b in enumerate(bloques, 1):
        a, prov = await ask_llm(f"Parte {i} de {len(bloques)} de una transcripción larga. De esta parte "
                                f"{_PEDIDO}:\n\n{b}")
        if prov == "ninguno":
            return a, prov, len(cuerpo)
        parciales.append(f"Parte {i}:\n{a}")
    final, prov = await ask_llm("Estos son los análisis parciales de una misma transcripción. "
                                f"Consolídalos sin repetir: {_PEDIDO}.\n\n" + "\n\n".join(parciales))
    return final, prov, len(cuerpo)


async def _transcribir(match) -> dict:
    path, escrito = _resolver_ruta(match.group("path"))
    if path is None:
        return {"reply": f"✖ No encuentro el audio {escrito}. Dame la ruta completa "
                         "(«transcribe el audio D:\\notas\\reunion.mp3») y lo paso a texto."}
    if path.suffix.lower() not in _EXT_AUDIO:
        return {"reply": f"✖ El formato «{path.suffix or 'sin extensión'}» de {path.name} no es de audio ni "
                         f"de vídeo que sepa transcribir ({', '.join(sorted(_EXT_AUDIO))})."}
    try:
        from faster_whisper import WhisperModel  # noqa: F401
    except ImportError:
        return {"reply": "⚠ Me falta el motor de transcripción. Se arregla en un minuto: "
                         "«pip install faster-whisper» en el entorno de nexus y repite "
                         "la orden — el resto ya está listo."}

    def _run():
        from backend.core.infraestructura.stt import _get_model
        segmentos, info = _get_model().transcribe(str(path), language="es", vad_filter=True)
        return [(s.start, s.text.strip()) for s in segmentos if s.text.strip()], getattr(info, "duration", None)

    try:
        segs, duracion = await asyncio.to_thread(_run)
    except Exception as exc:                                    # noqa: BLE001
        return {"reply": f"✖ No pude transcribir {path.name}: el archivo no se pudo decodificar "
                         f"({type(exc).__name__}). ¿Está dañado o falta un códec (ffmpeg)?"}
    if not segs:
        return {"reply": f"El audio {path.name} no contiene voz reconocible. Si es música "
                         "o ruido, ahí no hay nada que transcribir."}
    texto = " ".join(t for _, t in segs)
    con_tiempos = "\n".join(f"[{_mmss(ini)}] {t}" for ini, t in segs)
    dur_txt = f", {_mmss(duracion)}" if duracion else ""

    analisis, prov, analizados = await _analizar(texto)
    con_analisis = prov != "ninguno"       # proveedor «ninguno» = el texto es un error, no un análisis

    # Memoria: nota con la transcripción ENTERA (y marcas de tiempo) + base de datos en trozos.
    from backend.core.comun.secretos import redactar
    from backend.core.dominio import rag
    from backend.core.dominio.memory import graph, pg
    origen = str(path.resolve())
    huella = hashlib.sha1(origen.encode("utf-8")).hexdigest()[:6]
    titulo = f"audio {path.stem[:28]} {huella}"            # la huella evita que dos audios se pisen
    cuerpo_analisis = (f"---\n{analisis}\n\n" if con_analisis
                       else "---\n(sin análisis: el modelo no estaba disponible)\n\n")
    graph.write_note(titulo, f"Transcripción de {path.name}{dur_txt}:\n\n{con_tiempos}\n\n"
                             f"{cuerpo_analisis}Enlaces: [[audios]] [[conocimiento]]")
    trozos, sustituidas = 0, 0
    if pg.online:
        nuevos = set()
        for t in rag.trocear(texto):
            contenido = redactar(f"[audio {path.name}] {t['texto']}")[0]    # como se guarda de verdad
            nuevos.add(contenido)
            pg.remember(contenido, kind="knowledge", tags=["audio"], origen=origen, origen_tipo="audio")
            trozos += 1
        # Retranscribir el mismo archivo SUSTITUYE lo anterior (se retira a la papelera, no se borra).
        viejas = [f["id"] for f in pg.filas_por_origen(origen, "audio") if f["content"] not in nuevos]
        if viejas:
            lote = f"audio-{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}-{huella}"
            sustituidas = pg.retirar_filas(viejas, lote)
    donde = (f"en la nota «{titulo}» y en la memoria de conocimiento ({trozos} trozo(s))" if trozos
             else f"en la nota «{titulo}» (la base de datos no está disponible: solo quedó la nota)")
    cabecera = f"✔ Transcrito {path.name}{dur_txt} ({len(texto):,} caracteres) y guardado {donde}".replace(",", ".")
    if sustituidas:
        cabecera += f"; sustituye a la transcripción anterior de este archivo ({sustituidas} trozo(s) retirados)"
    aviso = ""
    if analizados < len(texto):
        aviso = (f"\n(Analicé los primeros {analizados:,} caracteres; la transcripción completa está "
                 "guardada.)").replace(",", ".")
    if not con_analisis:
        return {"reply": f"{cabecera}.\n\nNo pude analizarlo (el modelo no está disponible): "
                         f"{analisis}\nCuando lo esté, di «qué recuerdas de {path.stem[:20]}»."}
    return {"reply": f"{cabecera}:\n\n{analisis[:900]}{aviso}\n\nDi «qué recuerdas de "
                     f"{path.stem[:20]}» cuando quieras volver sobre esto."}


async def handle(intent: str, text: str, match, ctx) -> dict:
    if intent == "transcribe":
        return await _transcribir(match)

    if intent == "web_search":
        q = match.group("q").strip().rstrip("?¿.")
        return await _buscar_y_responder(q)

    return {"reply": "Orden no reconocida. Prueba «transcribe el audio <ruta>» o "
                     "«busca en internet X»."}
