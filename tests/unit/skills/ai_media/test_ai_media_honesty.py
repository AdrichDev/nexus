# -*- coding: utf-8 -*-
"""ai_media: solo lo que hace de verdad (transcripción y búsqueda web), y bien hecho.

Cubre: que ya NO ofrece generar ni describir imágenes (era un SVG de relleno y metadatos);
la búsqueda web (lee las páginas, fuentes numeradas, admite cuándo no hay respuesta, sin LLM
enseña lo encontrado) y la transcripción (tipo de archivo, errores del decodificador, duración,
marcas de tiempo, análisis por bloques para audios largos, retranscribir sustituye lo anterior,
nada se guarda recortado ni con el error del modelo como si fuera un análisis).

Todo simulado (websearch, LLM, Whisper, memoria); ficheros en un directorio temporal. Nivel M.
Ejecutar: python tests/unit/skills/ai_media/test_ai_media_honesty.py
"""
import asyncio
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from backend.core.aplicacion import skills_loader as sl  # noqa: E402
import backend.core.dominio.memory as memory  # noqa: E402
import backend.core.infraestructura.llm as llm  # noqa: E402
import backend.core.infraestructura.stt as stt  # noqa: E402
import backend.core.infraestructura.websearch as websearch  # noqa: E402
import backend.core.infraestructura.youtube as youtube  # noqa: E402

sl.load_skills()
media = sl.get_skills()["ai_media"].module

_fail, _pass = [], 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


TMP = Path(tempfile.mkdtemp(prefix="nexus_media_test_"))


def correr(frase):
    r = sl.route(frase)
    assert r and r[0].folder == "ai_media", f"«{frase}» no llega a ai_media: {r and (r[0].folder, r[1])}"
    skill, intent, m = r
    return asyncio.run(skill.module.handle(intent, frase, m, None))


# 0) ya no ofrece lo que no hacía -------------------------------------------------------------------
check(set(media.SKILL["patterns"]) == {"video_youtube", "transcribe", "web_search"},
      f"intents: solo video_youtube, transcribe y web_search (hay {sorted(media.SKILL['patterns'])})")
for frase in ("genera una imagen de un dragón", "dibújame un logo para la marca",
              "analiza la imagen D:\\fotos\\logo.png", "descríbeme la foto D:\\a.jpg"):
    r = sl.route(frase)
    check(not (r and r[0].folder == "ai_media"), f"«{frase}» ya no se enruta a ai_media")
doc = (ROOT / "skills" / "ai_media" / "SKILL.md").read_text(encoding="utf-8")
check("gen_image" not in doc and "analyze_image" not in doc and "SVG" not in doc,
      "SKILL.md: ya no documenta la generación ni el análisis de imágenes")
check("Imágenes" not in media.SKILL["name"] and "Multimedia" not in media.SKILL["name"],
      "nombre visible: describe lo que hace ahora")
check("NO generas imágenes" in llm.SYSTEM_PROMPT and "no finj" in llm.SYSTEM_PROMPT.lower(),
      "prompt del sistema: dice que NO genera ni describe imágenes y que no debe fingirlo")
catalogo = (ROOT / "frontend" / "js" / "core" / "catalog.js").read_text(encoding="utf-8")
check("Generar imagen" not in catalogo and "genera una imagen" not in catalogo,
      "frontend: ya no ofrece la acción «Generar imagen…»")

# 1) búsqueda web ------------------------------------------------------------------------------------
RESULTADOS = [
    {"title": "Chelsea gana el Mundial de Clubes", "url": "https://www.uno.example/a", "snippet": "final en Nueva Jersey"},
    {"title": "Crónica de la final", "url": "https://dos.example/b", "snippet": "resumen del partido"},
    {"title": "Reacciones", "url": "https://tres.example/c", "snippet": "opiniones"},
]
PAGINAS = {"https://www.uno.example/a": "TEXTO-LARGO-UNO: el Chelsea venció 3-0 al PSG en la final.",
           "https://dos.example/b": "TEXTO-LARGO-DOS: crónica detallada del partido."}
prompts, estado = [], {"proveedor": "ollama", "respuesta": "Ganó el Chelsea [1]."}


async def _buscar(q, n=6, news=None):
    return [dict(r) for r in RESULTADOS]


async def _pagina(url, max_chars=3500):
    return PAGINAS.get(url, "")[:max_chars]


async def _ask(texto, *a, **k):
    prompts.append(texto)
    return estado["respuesta"], estado["proveedor"]


orig = (websearch.search, websearch.fetch_page, llm.ask_llm, youtube.fuentes_video)
websearch.search, websearch.fetch_page, llm.ask_llm = _buscar, _pagina, _ask
try:
    res = correr("busca en internet quién ganó el mundial de clubes")
    prompt = prompts[-1]
    check("TEXTO-LARGO-UNO" in prompt and "TEXTO-LARGO-DOS" in prompt, "búsqueda: el modelo recibe el CONTENIDO de las páginas, no solo títulos")
    check("[1]" in prompt and "[2]" in prompt and "[3]" in prompt, "búsqueda: las fuentes van numeradas")
    check("resumen del partido" in prompt or "opiniones" in prompt, "búsqueda: si una página no se pudo leer, usa su fragmento")
    check("no" in prompt.lower() and "fuentes" in prompt.lower() and "cita" in prompt.lower(),
          "búsqueda: el prompt pide citar y admitir cuando las fuentes no responden")
    check("Ganó el Chelsea [1]." in res["reply"], "búsqueda: devuelve la respuesta del modelo")
    check("[1] uno.example — Chelsea gana el Mundial de Clubes" in res["reply"]
          and "[2] dos.example" in res["reply"] and "[3] tres.example" in res["reply"],
          "búsqueda: lista de fuentes compacta (dominio — título), sin URLs larguísimas")
    check(res.get("speak") is True and (res.get("data") or {}).get("sources"), "búsqueda: data.sources sigue disponible")

    # los anuncios / redirecciones de buscador no cuentan como fuentes ni gastan lecturas
    async def _con_anuncios(q, n=6, news=None):
        return ([{"title": "Compra mqtt en Amazon - Ahorra", "url": "https://duckduckgo.com/y.js?ad_domain=amazon.es", "snippet": "anuncio"},
                 {"title": "more info", "url": "https://duckduckgo.com/y.js?x=1", "snippet": ""}]
                + [dict(r) for r in RESULTADOS])
    websearch.search = _con_anuncios
    res = correr("busca en internet qué es mqtt")
    check("Compra mqtt" not in prompts[-1] and "more info" not in prompts[-1] and "duckduckgo" not in res["reply"],
          "búsqueda: los anuncios de DuckDuckGo no entran en el prompt ni en las fuentes")
    check("TEXTO-LARGO-UNO" in prompts[-1] and "[1] Chelsea gana" in prompts[-1],
          "búsqueda: tras filtrar anuncios, las páginas leídas son las de los resultados buenos y se renumeran")
    websearch.search = _buscar

    # YouTube/transcripciones: solo como fuente explícita o suplemento si hay pocas páginas leídas.
    llamadas_youtube = []

    async def _videos(q, n=2, max_chars=1200):
        llamadas_youtube.append((q, n, max_chars))
        return ([{"kind": "youtube", "title": "Vídeo táctico del Chelsea", "url": "https://www.youtube.com/watch?v=abc123def45&t=42s",
                  "canal": "Canal Fútbol", "tipo": "automática", "idioma": "es",
                  "text": "[00:42] análisis del partido y del Chelsea"}], [])

    youtube.fuentes_video = _videos
    prompts.clear(); llamadas_youtube.clear()
    res = correr("busca en internet vídeos de youtube sobre quién ganó el mundial de clubes")
    prompt = prompts[-1]
    check(len(llamadas_youtube) == 1, "YouTube: si la consulta pide vídeo/youtube, busca transcripciones")
    check("[4]" in prompt and "VÍDEO" in prompt and "transcripción" in prompt.lower(),
          "YouTube: la fuente de vídeo se añade después de las web y se etiqueta en el prompt")
    check("automáticas" in prompt.lower() and "menor fiabilidad" in prompt.lower(),
          "YouTube: el prompt advierte que las captions automáticas son menos fiables que páginas/artículos")
    check("Vídeo táctico del Chelsea" in res["reply"] and "youtube.com" in res["reply"],
          "YouTube: la lista compacta de fuentes incluye título/dominio del vídeo")

    async def _solo_una_pagina(url, max_chars=3500):
        return ("TEXTO-LARGO-UNO: el Chelsea venció 3-0 al PSG en la final."
                if url == "https://www.uno.example/a" else "")

    websearch.fetch_page = _solo_una_pagina
    prompts.clear(); llamadas_youtube.clear()
    correr("busca en internet quién ganó el mundial de clubes")
    check(len(llamadas_youtube) == 1, "YouTube: si hay menos de 2 páginas legibles, usa vídeos como suplemento")
    websearch.fetch_page = _pagina

    prompts.clear(); llamadas_youtube.clear()
    correr("busca en internet quién ganó el mundial de clubes")
    check(not llamadas_youtube, "YouTube: una búsqueda normal con 2+ páginas legibles NO consulta YouTube")

    async def _videos_omitidos(q, n=2, max_chars=1200):
        llamadas_youtube.append((q, n, max_chars))
        return ([], ["Vídeo sin captions: sin subtítulos", "Vídeo privado: no disponible"])

    youtube.fuentes_video = _videos_omitidos
    prompts.clear(); llamadas_youtube.clear()
    res = correr("busca en internet vídeo youtube sobre el mundial de clubes")
    check("Vídeos omitidos" in res["reply"] and "Vídeo sin captions" in res["reply"] and "Vídeo privado" in res["reply"],
          "YouTube: los vídeos omitidos se muestran cuando aplica")

    async def _videos_roto(q, n=2, max_chars=1200):
        llamadas_youtube.append((q, n, max_chars))
        raise RuntimeError("yt-dlp roto")

    youtube.fuentes_video = _videos_roto
    prompts.clear(); llamadas_youtube.clear()
    res = correr("busca en internet vídeo youtube sobre el mundial de clubes")
    check("Ganó el Chelsea [1]." in res["reply"] and "yt-dlp roto" in res["reply"],
          "YouTube: si el lector de transcripciones revienta, la búsqueda web sigue y lo dice")

    async def _sin_videos(q, n=2, max_chars=1200):
        return ([], [])

    youtube.fuentes_video = _sin_videos

    # una página lentísima no cuelga la respuesta
    async def _lenta(url, max_chars=3500):
        await asyncio.sleep(30)
        return "nunca"
    websearch.fetch_page = _lenta
    media._TIMEOUT_PAGINA = 0.2
    t0 = time.time()
    res = correr("busca en internet quién ganó el mundial de clubes")
    check(time.time() - t0 < 5, "búsqueda: una página lenta no bloquea (tiempo máximo por página)")
    check("Ganó el Chelsea [1]." in res["reply"], "búsqueda: responde igualmente con los fragmentos")
    websearch.fetch_page = _pagina

    # sin LLM: enseña lo encontrado, sin locutar el error
    estado.update(proveedor="ninguno", respuesta="Ollama no está en marcha.")
    res = correr("busca en internet quién ganó el mundial de clubes")
    check("no pude redactar" in res["reply"].lower() and "Chelsea gana el Mundial de Clubes" in res["reply"]
          and "uno.example/a" in res["reply"], "búsqueda sin LLM: enseña los resultados encontrados")
    check(not res.get("speak"), "búsqueda sin LLM: no locuta un mensaje de error")

    # sin resultados
    async def _vacio(q, n=6, news=None):
        return []
    websearch.search = _vacio
    res = correr("busca en internet algo rarísimo")
    check("No he podido buscar" in res["reply"] or "no he podido buscar" in res["reply"].lower(),
          "búsqueda sin resultados: lo dice")
finally:
    websearch.search, websearch.fetch_page, llm.ask_llm, youtube.fuentes_video = orig
    estado.update(proveedor="ollama", respuesta="Ganó el Chelsea [1].")

# 2) transcripción ------------------------------------------------------------------------------------
class _Seg:
    def __init__(self, start, text):
        self.start, self.end, self.text = start, start + 5, text


class _Info:
    def __init__(self, duration):
        self.duration, self.language = duration, "es"


class _Modelo:
    def __init__(self, segmentos, duracion=60.0, error=None):
        self.segmentos, self.duracion, self.error, self.llamadas = segmentos, duracion, error, 0

    def transcribe(self, path, language="es", vad_filter=True):
        self.llamadas += 1
        if self.error:
            raise self.error
        return list(self.segmentos), _Info(self.duracion)


class _PgFalso:
    online = True

    def __init__(self):
        self.filas = []
        self.retiradas = []

    def remember(self, content, kind="note", tags=None, **kw):
        for f in self.filas:
            if f["vivo"] and f["content"] == content:
                return {"id": f["id"], "duplicado": True}
        self.filas.append({"id": len(self.filas) + 1, "content": content, "vivo": True,
                           "origen": kw.get("origen"), "origen_tipo": kw.get("origen_tipo")})
        return {"id": len(self.filas), "duplicado": False}

    def filas_por_origen(self, origen, tipo):
        return [dict(f) for f in self.filas if f["vivo"] and f["origen"] == origen and f["origen_tipo"] == tipo]

    def retirar_filas(self, ids, lote):
        for f in self.filas:
            if f["id"] in ids:
                f["vivo"] = False
        self.retiradas.append((list(ids), lote))
        return len(ids)


notas, prompts_llm = [], []


class _GrafoFalso:
    def write_note(self, title, content):
        notas.append((title, content))
        return "x.md"


def transcribir(ruta, segmentos, *, pg=None, proveedor="ollama", duracion=60.0, error=None):
    notas.clear()
    prompts_llm.clear()
    pg = pg or _PgFalso()
    modelo = _Modelo(segmentos, duracion, error)

    async def _llm(texto, *a, **k):
        prompts_llm.append(texto)
        return (("Ideas: A, B, C" if proveedor != "ninguno" else "Ollama no está en marcha."), proveedor)

    o = (llm.ask_llm, stt._get_model, memory.graph, memory.pg)
    sys.modules["faster_whisper"] = types.SimpleNamespace(WhisperModel=object)
    llm.ask_llm, stt._get_model, memory.graph, memory.pg = _llm, (lambda: modelo), _GrafoFalso(), pg
    try:
        res = correr(f"transcribe el audio {ruta}")
    finally:
        llm.ask_llm, stt._get_model, memory.graph, memory.pg = o
        sys.modules.pop("faster_whisper", None)
    return res, pg, modelo


audio = TMP / "mi carpeta" / "reunión larga.mp3"
audio.parent.mkdir()
audio.write_bytes(b"x")

# ruta con espacios (el archivo vive en «mi carpeta») y vídeo
res, pg, modelo = transcribir(audio, [_Seg(0, "hola"), _Seg(65, "adiós")], duracion=754.0)
check("reunión larga.mp3" in res["reply"] and modelo.llamadas == 1, "ruta con espacios: transcribe el archivo correcto")
check("12:34" in res["reply"], "transcripción: informa de la duración del audio (mm:ss)")
contenido = notas[0][1] if notas else ""
check("[00:00] hola" in contenido and "[01:05] adiós" in contenido, "transcripción: la nota lleva marcas de tiempo")
check("[00:00]" not in " ".join(f["content"] for f in pg.filas), "transcripción: la base de datos recibe texto limpio, sin marcas")
video = TMP / "clase.mp4"
video.write_bytes(b"x")
r = sl.route(f"transcribe el vídeo {video}")
check(bool(r) and r[0].folder == "ai_media" and r[1] == "transcribe", "transcripción: acepta «transcribe el vídeo …»")

# tipo de archivo no soportado
txt = TMP / "notas.txt"
txt.write_text("no es audio", encoding="utf-8")
res, pg, modelo = transcribir(txt, [_Seg(0, "x")])
check("formato" in res["reply"].lower() and modelo.llamadas == 0 and not notas,
      "tipo no soportado: lo dice y no intenta transcribir ni guarda nada")

# el decodificador falla
res, pg, modelo = transcribir(audio, [], error=RuntimeError("codec no soportado"))
check("no pude" in res["reply"].lower() and not notas and not pg.filas,
      "error del decodificador: mensaje honesto y no se guarda nada")

# audio sin voz
res, pg, modelo = transcribir(audio, [])
check("no contiene voz" in res["reply"].lower() and not notas, "audio sin voz: se dice y no se guarda nada")

# análisis por bloques en audios largos
parrafo = ("palabra " * 750)                                    # ~6.000 caracteres
medio = [_Seg(i * 10, parrafo) for i in range(4)]                # ~24.000 caracteres
res, pg, modelo = transcribir(audio, medio)
check(len(prompts_llm) >= 4, f"audio largo: el análisis recorre TODO el texto por bloques ({len(prompts_llm)} llamadas)")
check(any("Ideas: A, B, C" in p for p in prompts_llm[-1:]), "audio largo: hay una consolidación final de los análisis parciales")
check("primeros" not in res["reply"].lower(), "audio largo (dentro del tope): no dice que dejó algo fuera")
enorme = [_Seg(i * 10, parrafo) for i in range(14)]             # ~84.000 caracteres
res, pg, modelo = transcribir(audio, enorme)
check("primeros 36.000 caracteres" in res["reply"], "audio enorme: avisa de hasta dónde llegó el análisis")
check(len(notas[0][1]) > 80000, "audio enorme: aun así la transcripción se guarda ENTERA")

# sin LLM: no se guarda el error como análisis
res, pg, modelo = transcribir(audio, [_Seg(0, "hola mundo transcrito")], proveedor="ninguno")
check("Ollama no está en marcha" not in (notas[0][1] if notas else ""), "sin LLM: el error NO se guarda como análisis")
check("no pude analizar" in res["reply"].lower() and "hola mundo transcrito" in (notas[0][1] if notas else ""),
      "sin LLM: avisa y conserva la transcripción")

# retranscribir sustituye lo anterior (sin duplicados ni restos)
pg = _PgFalso()
transcribir(audio, [_Seg(0, "primera versión del texto")], pg=pg)
vivas1 = [f["content"] for f in pg.filas if f["vivo"]]
transcribir(audio, [_Seg(0, "primera versión del texto")], pg=pg)
check([f["content"] for f in pg.filas if f["vivo"]] == vivas1 and not pg.retiradas,
      "retranscribir lo mismo: no duplica ni retira")
transcribir(audio, [_Seg(0, "segunda versión distinta")], pg=pg)
vivas2 = " ".join(f["content"] for f in pg.filas if f["vivo"])
check("segunda versión distinta" in vivas2 and "primera versión" not in vivas2 and pg.retiradas,
      "retranscribir distinto: sustituye lo anterior (lo viejo se retira, no se borra)")

# dos audios con el mismo prefijo de nombre no se pisan
a1 = TMP / "grabacion_reunion_equipo_ventas_2026_01_resumen_A.mp3"
a2 = TMP / "grabacion_reunion_equipo_ventas_2026_01_resumen_B.mp3"
a1.write_bytes(b"1"); a2.write_bytes(b"2")
transcribir(a1, [_Seg(0, "contenido del primero")]); t1 = notas[0][0]
transcribir(a2, [_Seg(0, "contenido del segundo")]); t2 = notas[0][0]
check(t1 != t2, "notas: dos audios con el mismo prefijo de nombre NO comparten nota")

print(f"\nai_media: {_pass} OK, {len(_fail)} FAIL")
sys.exit(1 if _fail else 0)
