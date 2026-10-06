# -*- coding: utf-8 -*-
"""ai_media: comando directo para resumir un vídeo de YouTube.

Todo simulado: no se descarga audio/vídeo real ni se ejecuta Whisper real.
Ejecutar: python tests/unit/skills/ai_media/test_youtube_video_command.py
"""
import asyncio
import shutil
import sys
import tempfile
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


def correr(frase):
    r = sl.route(frase)
    assert r and r[0].folder == "ai_media", f"«{frase}» no llega a ai_media: {r and (r[0].folder, r[1])}"
    skill, intent, m = r
    return intent, asyncio.run(skill.module.handle(intent, frase, m, None))


# 1) enruta antes que transcribe ---------------------------------------------------------------------
r = sl.route("resume el vídeo https://www.youtube.com/watch?v=abc123def45")
check(bool(r) and r[0].folder == "ai_media" and r[1] == "video_youtube",
      "router: el resumen directo de YouTube llega a ai_media/video_youtube")
check(list(media.SKILL["patterns"]).index("video_youtube") < list(media.SKILL["patterns"]).index("transcribe"),
      "router: video_youtube está antes que transcribe")


class _PgFalso:
    online = True

    def __init__(self):
        self.filas = []
        self.retiradas = []

    def remember(self, content, kind="note", tags=None, **kw):
        self.filas.append({"id": len(self.filas) + 1, "content": content, "tags": tags,
                           "origen": kw.get("origen"), "origen_tipo": kw.get("origen_tipo"), "vivo": True})
        return {"id": len(self.filas), "duplicado": False}

    def filas_por_origen(self, origen, tipo):
        return [dict(f) for f in self.filas if f["origen"] == origen and f["origen_tipo"] == tipo and f["vivo"]]

    def retirar_filas(self, ids, lote):
        self.retiradas.append((ids, lote))
        return len(ids)


class _GrafoFalso:
    def __init__(self):
        self.notas = []

    def write_note(self, title, content):
        self.notas.append((title, content))
        return "x.md"


def instalar_memoria():
    pg = _PgFalso()
    graph = _GrafoFalso()
    old = (memory.graph, memory.pg)
    memory.graph, memory.pg = graph, pg
    return old, graph, pg


URL = "https://www.youtube.com/watch?v=abc123def45"

# 2) captions: usa youtube.transcripcion, no descarga ni Whisper, prompt con minutos y metadatos ------
llamadas_transcripcion, llamadas_descarga, llamadas_whisper, prompts = [], [], [], []


async def _transcripcion_ok(url):
    llamadas_transcripcion.append(url)
    return {"ok": True, "id": "abc123def45", "title": "Clase de IA", "canal": "Canal Nexus",
            "tipo": "manual", "idioma": "es", "lineas": [(0, "intro"), (75, "idea importante")],
            "texto": "intro idea importante"}


async def _ask(texto, *a, **k):
    prompts.append(texto)
    return "Resumen con [00:00] intro y [01:15] idea.", "ollama"


def _descarga_no(*a, **k):
    llamadas_descarga.append((a, k))
    raise AssertionError("no debe descargar con captions")


def _whisper_no(*a, **k):
    llamadas_whisper.append((a, k))
    raise AssertionError("no debe transcribir con captions")


old_mem, graph, pg = instalar_memoria()
old = (youtube.transcripcion, llm.ask_llm, media._descargar_audio_youtube, media._transcribir_archivo_audio)
youtube.transcripcion, llm.ask_llm = _transcripcion_ok, _ask
media._descargar_audio_youtube, media._transcribir_archivo_audio = _descarga_no, _whisper_no
try:
    intent, res = correr(f"resume este video {URL}")
    check(intent == "video_youtube" and llamadas_transcripcion == [URL], "captions: llama a youtube.transcripcion(url)")
    check(not llamadas_descarga and not llamadas_whisper, "captions: no descarga audio ni llama a Whisper")
    prompt = prompts[-1]
    check("[00:00] intro" in prompt and "[01:15] idea importante" in prompt, "captions: el prompt lleva referencias por minuto")
    check("Clase de IA" in prompt and "Canal Nexus" in prompt and "manual" in prompt, "captions: el prompt lleva metadatos del vídeo")
    check("Resumen con" in res["reply"] and graph.notas and pg.filas, "captions: resume y guarda memoria al transcribir")
finally:
    youtube.transcripcion, llm.ask_llm, media._descargar_audio_youtube, media._transcribir_archivo_audio = old
    memory.graph, memory.pg = old_mem

# 3) sin subtítulos: fallback, máximo 90 min, limpia temporales ---------------------------------------
temp_dirs, descargados, transcritos = [], [], []


async def _sin_subtitulos(url):
    return {"ok": False, "id": "abc123def45", "title": "Vídeo sin captions", "motivo": "sin_subtitulos"}


def _descarga_mock(url, tmpdir):
    temp_dirs.append(Path(tmpdir))
    p = Path(tmpdir) / "audio.m4a"
    p.write_bytes(b"audio")
    descargados.append(p)
    return p, 30 * 60


def _whisper_mock(path):
    transcritos.append(Path(path))
    return [(0, "voz del vídeo"), (90, "segunda idea")], 30 * 60


old_mem, graph, pg = instalar_memoria()
old = (youtube.transcripcion, llm.ask_llm, media._descargar_audio_youtube, media._transcribir_archivo_audio)
youtube.transcripcion, llm.ask_llm = _sin_subtitulos, _ask
media._descargar_audio_youtube, media._transcribir_archivo_audio = _descarga_mock, _whisper_mock
try:
    intent, res = correr(f"analiza el vídeo {URL}")
    check(descargados and transcritos, "sin_subtitulos: usa la descarga+Whisper de fallback")
    check("90 min" in res["reply"] or "90 minutos" in res["reply"], "sin_subtitulos: menciona el límite máximo de 90 min")
    check(temp_dirs and all(not p.exists() for p in temp_dirs), "sin_subtitulos: limpia el directorio temporal tras el fallback")
    check(graph.notas and pg.filas, "sin_subtitulos: guarda memoria cuando Whisper transcribe")
finally:
    youtube.transcripcion, llm.ask_llm, media._descargar_audio_youtube, media._transcribir_archivo_audio = old
    memory.graph, memory.pg = old_mem

# 3b) si el metadato ya supera 90 min, no llama a Whisper y también limpia ---------------------------
temp_dirs.clear(); transcritos.clear()


def _descarga_larga(url, tmpdir):
    temp_dirs.append(Path(tmpdir))
    p = Path(tmpdir) / "largo.m4a"
    p.write_bytes(b"audio")
    return p, 91 * 60


old = (youtube.transcripcion, media._descargar_audio_youtube, media._transcribir_archivo_audio)
youtube.transcripcion = _sin_subtitulos
media._descargar_audio_youtube, media._transcribir_archivo_audio = _descarga_larga, _whisper_mock
try:
    intent, res = correr(f"resume el vídeo {URL}")
    check(not transcritos and "90" in res["reply"], "sin_subtitulos: no transcribe vídeos de más de 90 min")
    check(temp_dirs and all(not p.exists() for p in temp_dirs), "sin_subtitulos largo: limpia temporales")
finally:
    youtube.transcripcion, media._descargar_audio_youtube, media._transcribir_archivo_audio = old

# 4) límite/no disponible/error: honesto, sin resumen -------------------------------------------------
for motivo in ("limite", "no_disponible", "error"):
    llamadas_descarga.clear(); prompts.clear()

    async def _fallo(url, _motivo=motivo):
        return {"ok": False, "id": "abc123def45", "title": "X", "motivo": _motivo}

    old = (youtube.transcripcion, llm.ask_llm, media._descargar_audio_youtube)
    youtube.transcripcion, llm.ask_llm, media._descargar_audio_youtube = _fallo, _ask, _descarga_no
    try:
        intent, res = correr(f"resume el vídeo {URL}")
        bajo = res["reply"].lower()
        check(("no puedo" in bajo or "no pude" in bajo) and "resumen" in bajo and not prompts,
              f"{motivo}: respuesta honesta sin llamar al LLM ni inventar resumen")
    finally:
        youtube.transcripcion, llm.ask_llm, media._descargar_audio_youtube = old

shutil.rmtree(tempfile.gettempdir(), ignore_errors=False) if False else None
print(f"\nai_media_youtube: {_pass} OK, {len(_fail)} FAIL")
sys.exit(1 if _fail else 0)
