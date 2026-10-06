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
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse

SKILL = {
    "name": "Audio y búsqueda web",
    "description": "Transcribe audios y vídeos con Whisper local (marcas de tiempo y análisis) y responde con búsqueda web leyendo las páginas y citando las fuentes",
    # ORDEN: específico arriba, amplio abajo (web_search es el más ancho y va último).
    "patterns": {
        # Resumen directo de UN vídeo de YouTube. Va antes de transcribe para no tratar la URL como ruta.
        "video_youtube": r"(?:resume(?:me)?|res[uú]meme|analiza(?:me)?|anal[ií]zame|"
                         r"extrae(?:me)?\s+(?:las\s+)?ideas(?:\s+principales)?\s+de)\s+"
                         r"(?:el\s+|este\s+|esta\s+)?v[ií]deo\s+"
                         r"(?P<url>https?://(?:www\.)?(?:youtube\.com|youtu\.be)/\S+)$",
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
    return await websearch.leer_paginas(results, n=_PAGINAS_A_LEER, max_chars=_CHARS_PAGINA,
                                        timeout=_TIMEOUT_PAGINA)


def _limpiar(results: list[dict]) -> list[dict]:
    from backend.core.infraestructura import websearch
    return websearch.sin_ruido(results)


_VIDEO_RE = re.compile(r"\b(?:v[ií]deo|videos|vídeos|video|youtube)\b", re.IGNORECASE)


def _menciona_video(q: str) -> bool:
    return bool(_VIDEO_RE.search(q or ""))


def _fuente_compacta(i: int, r: dict) -> str:
    titulo = (r.get("title") or r.get("url") or "").strip()
    if r.get("kind") == "youtube":
        tipo = f"transcripción {r.get('tipo')}" if r.get("tipo") else "transcripción"
        canal = f" — {r.get('canal')}" if r.get("canal") else ""
        return f"[{i}] VÍDEO ({tipo}) {_dominio(r.get('url')) or 'youtube.com'}{canal} — {titulo}"
    return f"[{i}] {_dominio(r.get('url')) or 'web'} — {titulo}"


def _lista_fuentes(results: list[dict]) -> str:
    return "\n".join(_fuente_compacta(i, r) for i, r in enumerate(results, 1))


def _lista_omitidos_video(omitidos: list[str]) -> str:
    if not omitidos:
        return ""
    return "\n\nVídeos omitidos (no se descargó audio/vídeo):\n" + "\n".join(f"• {x}" for x in omitidos[:5])


async def _buscar_y_responder(q: str) -> dict:
    from backend.core.infraestructura import websearch
    from backend.core.infraestructura.llm import ask_llm
    results = _limpiar(await websearch.search(q, 8))[:6]     # se piden 8 por si caen anuncios
    if not results:
        return {"reply": f"✖ No he podido buscar «{q}»: o no hay conexión o los buscadores que pruebo "
                         "no han respondido. Reintenta en un momento; si persiste, revisa la red."}
    paginas = await _leer_paginas(results)
    leidas = sum(1 for p in paginas[:len(results)] if p)
    videos: list[dict] = []
    omitidos_video: list[str] = []
    if _menciona_video(q) or leidas < 2:
        try:
            from backend.core.infraestructura import youtube
            videos, omitidos_video = await youtube.fuentes_video(q, n=2, max_chars=1200)
        except Exception as e:
            omitidos_video = [f"YouTube: no se pudieron leer transcripciones ({e})"]

    fuentes_prompt = []
    for i, r in enumerate(results, 1):
        leido = paginas[i - 1] if i - 1 < len(paginas) else ""
        cuerpo = leido or (r.get("snippet") or "")      # si la página no se pudo leer, su fragmento
        fuentes_prompt.append(f"[{i}] {r.get('title') or ''} ({_dominio(r.get('url'))})\n{cuerpo}")
    for j, v in enumerate(videos, len(results) + 1):
        tipo = f"transcripción {v.get('tipo')}" if v.get("tipo") else "transcripción"
        meta = "; ".join(x for x in (_dominio(v.get("url")) or "youtube.com", v.get("canal") or "", tipo,
                                     v.get("idioma") or "") if x)
        fuentes_prompt.append(f"[{j}] VÍDEO — {v.get('title') or ''} ({meta})\n{v.get('text') or ''}")
    aviso_video = (" Las fuentes marcadas VÍDEO son evidencia de transcripción; las captions "
                   "automáticas tienen menor fiabilidad que páginas o artículos, así que úsalas "
                   "solo como apoyo y no como prueba principal."
                   if videos else "")
    answer, prov = await ask_llm(
        f"Hoy es {dt.date.today():%d/%m/%Y}. Responde a la pregunta «{q}» usando SOLO las FUENTES "
        "numeradas de abajo. Cita cada dato con su número entre corchetes, p. ej. [1]. Si las fuentes "
        "no contienen la respuesta, di claramente que no la has encontrado en ellas en lugar de "
        f"suponer.{aviso_video} Sé breve (máximo 6 líneas) y responde en español.\n\nFUENTES:\n"
        + "\n\n".join(fuentes_prompt))
    todas_fuentes = results + videos
    urls = [r.get("url") for r in todas_fuentes if r.get("url")][:8]
    if prov == "ninguno":
        # Sin modelo no hay respuesta: se enseña lo que SÍ se encontró, no solo el error.
        lista = "\n".join(f"• {r.get('title') or r.get('url')} — {r.get('url')}" for r in todas_fuentes[:6])
        return {"reply": f"No pude redactar la respuesta (el modelo no está disponible), pero esto es lo "
                         f"que encontré sobre «{q}»:\n{lista}{_lista_omitidos_video(omitidos_video)}\nMotivo: {answer}",
                "data": {"sources": urls}}
    return {"reply": f"{answer}\n\nFuentes:\n{_lista_fuentes(todas_fuentes)}{_lista_omitidos_video(omitidos_video)}", "speak": True,
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


def _titulo_memoria(prefijo: str, nombre: str, origen: str) -> str:
    base = re.sub(r"\s+", " ", (nombre or prefijo).strip())[:28]
    huella = hashlib.sha1(origen.encode("utf-8")).hexdigest()[:6]
    return f"{prefijo} {base} {huella}"


def _guardar_transcripcion(*, origen: str, origen_tipo: str, nombre: str, con_tiempos: str,
                           texto_limpio: str, duracion: float | None, analisis: str,
                           con_analisis: bool, tags: list[str]) -> tuple[str, int, int, str]:
    """Guarda una transcripción completa en nota y memoria vectorial.

    Devuelve (titulo, trozos, sustituidas, dur_txt). Reutilizado por audio local y vídeo YouTube
    para que ambos sustituyan reintentos por origen y no guarden análisis falsos.
    """
    from backend.core.comun.secretos import redactar
    from backend.core.dominio import rag
    from backend.core.dominio.memory import graph, pg

    dur_txt = f", {_mmss(duracion)}" if duracion else ""
    titulo = _titulo_memoria(origen_tipo, nombre, origen)
    cuerpo_analisis = (f"---\n{analisis}\n\n" if con_analisis
                       else "---\n(sin análisis: el modelo no estaba disponible)\n\n")
    graph.write_note(titulo, f"Transcripción de {nombre}{dur_txt}:\n\n{con_tiempos}\n\n"
                             f"{cuerpo_analisis}Enlaces: [[audios]] [[conocimiento]]")
    trozos, sustituidas = 0, 0
    if pg.online:
        nuevos = set()
        for t in rag.trocear(texto_limpio):
            contenido = redactar(f"[{origen_tipo} {nombre}] {t['texto']}")[0]
            nuevos.add(contenido)
            pg.remember(contenido, kind="knowledge", tags=tags, origen=origen, origen_tipo=origen_tipo)
            trozos += 1
        viejas = [f["id"] for f in pg.filas_por_origen(origen, origen_tipo) if f["content"] not in nuevos]
        if viejas:
            huella = hashlib.sha1(origen.encode("utf-8")).hexdigest()[:6]
            lote = f"{origen_tipo}-{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}-{huella}"
            sustituidas = pg.retirar_filas(viejas, lote)
    return titulo, trozos, sustituidas, dur_txt


def _transcribir_archivo_audio(path: Path) -> tuple[list[tuple[float, str]], float | None]:
    from backend.core.infraestructura.stt import _get_model
    segmentos, info = _get_model().transcribe(str(path), language="es", vad_filter=True)
    return [(s.start, s.text.strip()) for s in segmentos if s.text.strip()], getattr(info, "duration", None)


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

    try:
        segs, duracion = await asyncio.to_thread(_transcribir_archivo_audio, path)
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
    origen = str(path.resolve())
    titulo, trozos, sustituidas, dur_txt = _guardar_transcripcion(
        origen=origen, origen_tipo="audio", nombre=path.name, con_tiempos=con_tiempos,
        texto_limpio=texto, duracion=duracion, analisis=analisis, con_analisis=con_analisis,
        tags=["audio"])
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


_MAX_YOUTUBE_FALLBACK = 90 * 60


def _lineas_con_tiempos(lineas: list[tuple[float, str]]) -> str:
    return "\n".join(f"[{_mmss(ini)}] {t}" for ini, t in lineas if t)


def _descargar_audio_youtube(url: str, tmpdir: Path) -> tuple[Path, float | None]:
    """Descarga solo audio para el fallback explícito de un vídeo directo."""
    from backend.core.infraestructura import youtube
    if youtube.yt_dlp is None:  # type: ignore[attr-defined]
        raise RuntimeError("yt-dlp no está disponible")
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": "bestaudio/best",
        "outtmpl": str(tmpdir / "%(id)s.%(ext)s"),
    }
    with youtube.yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[attr-defined]
        info = ydl.extract_info(url, download=True)
    duration = float(info.get("duration") or 0) or None
    requested = (info.get("requested_downloads") or [{}])[0].get("filepath")
    if requested:
        return Path(requested), duration
    video_id = info.get("id") or "*"
    candidatos = sorted(tmpdir.glob(f"{video_id}.*")) or sorted(tmpdir.iterdir())
    if not candidatos:
        raise RuntimeError("yt-dlp no dejó un archivo de audio")
    return candidatos[0], duration


def _mensaje_youtube_fallo(motivo: str | None) -> str:
    if motivo == "limite":
        return ("No puedo hacer un resumen honesto de ese vídeo ahora: YouTube está limitando "
                "temporalmente el acceso a la transcripción. No voy a inventarlo; prueba más tarde.")
    if motivo == "no_disponible":
        return ("No puedo hacer un resumen de ese vídeo porque no está disponible públicamente o la URL "
                "no es válida. No hay transcripción que pueda leer.")
    return ("No pude leer la transcripción de ese vídeo por un error de YouTube/yt-dlp. "
            "No voy a fingir un resumen sin contenido verificable.")


async def _video_youtube(match) -> dict:
    from backend.core.infraestructura import youtube
    from backend.core.infraestructura.llm import ask_llm

    url = match.group("url").strip().rstrip(". ,;)")
    tr = await youtube.transcripcion(url)
    fallback = False
    duracion: float | None = None
    if tr.get("ok"):
        lineas = [(float(s), str(t).strip()) for s, t in (tr.get("lineas") or []) if str(t).strip()]
        titulo = tr.get("title") or tr.get("id") or "vídeo de YouTube"
    elif tr.get("motivo") == "sin_subtitulos":
        fallback = True
        titulo = tr.get("title") or tr.get("id") or "vídeo de YouTube"
        try:
            with tempfile.TemporaryDirectory(prefix="nexus_youtube_") as tmp:
                audio, duracion = await asyncio.to_thread(_descargar_audio_youtube, url, Path(tmp))
                if duracion and duracion > _MAX_YOUTUBE_FALLBACK:
                    return {"reply": "Ese vídeo no tiene subtítulos y dura más de 90 minutos. Para no "
                                     "bloquear Nexus ni hacer una transcripción enorme, el fallback de "
                                     "Whisper del comando directo está limitado a 90 min."}
                lineas, duracion_whisper = await asyncio.to_thread(_transcribir_archivo_audio, audio)
                duracion = duracion or duracion_whisper
        except Exception as exc:  # noqa: BLE001
            return {"reply": f"El vídeo no tiene subtítulos y no pude aplicar el fallback de Whisper "
                             f"(máximo 90 min): {type(exc).__name__}. No voy a inventar un resumen."}
        if duracion and duracion > _MAX_YOUTUBE_FALLBACK:
            return {"reply": "El audio transcrito supera el límite de 90 min del fallback directo; "
                             "no guardo ni resumo una transcripción parcial como si fuera completa."}
        if not lineas:
            return {"reply": "El vídeo no tiene subtítulos y Whisper no detectó voz reconocible. "
                             "No hay contenido suficiente para resumir."}
    else:
        return {"reply": _mensaje_youtube_fallo(tr.get("motivo"))}

    texto = " ".join(t for _, t in lineas)
    con_tiempos = _lineas_con_tiempos(lineas)
    meta = "; ".join(x for x in (titulo, tr.get("canal") or "", tr.get("tipo") or "",
                                  tr.get("idioma") or "") if x)
    aviso_fallback = ("\nEste vídeo no tenía subtítulos; usé Whisper como fallback directo "
                      "(máximo 90 min) y borré los temporales." if fallback else "")
    resumen, prov = await ask_llm(
        "Resume en español este vídeo de YouTube usando SOLO la transcripción. Incluye referencias "
        "por minuto con el formato [MM:SS] o [H:MM:SS] en cada idea importante. No inventes nada "
        f"fuera del texto. Metadatos: {meta or 'YouTube'}.{aviso_fallback}\n\nTRANSCRIPCIÓN:\n{con_tiempos}")
    con_analisis = prov != "ninguno"
    titulo_mem, trozos, sustituidas, dur_txt = _guardar_transcripcion(
        origen=url, origen_tipo="youtube", nombre=titulo, con_tiempos=con_tiempos,
        texto_limpio=texto, duracion=duracion, analisis=resumen, con_analisis=con_analisis,
        tags=["audio", "youtube"])
    donde = (f"en la nota «{titulo_mem}» y en la memoria de conocimiento ({trozos} trozo(s))" if trozos
             else f"en la nota «{titulo_mem}» (la base de datos no está disponible: solo quedó la nota)")
    extra = "; sustituye a una transcripción anterior" if sustituidas else ""
    if not con_analisis:
        return {"reply": f"Leí y guardé la transcripción de {titulo}{dur_txt} {donde}{extra}, "
                         f"pero no pude resumirla porque el modelo no está disponible: {resumen}"}
    return {"reply": f"✔ Resumen de {titulo}{dur_txt} guardado {donde}{extra}."
                     f"{aviso_fallback}\n\n{resumen[:1200]}"}


async def handle(intent: str, text: str, match, ctx) -> dict:
    if intent == "video_youtube":
        return await _video_youtube(match)

    if intent == "transcribe":
        return await _transcribir(match)

    if intent == "web_search":
        q = match.group("q").strip().rstrip("?¿.")
        return await _buscar_y_responder(q)

    return {"reply": "Orden no reconocida. Prueba «transcribe el audio <ruta>» o "
                     "«busca en internet X»."}
