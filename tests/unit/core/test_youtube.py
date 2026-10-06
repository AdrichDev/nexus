# -*- coding: utf-8 -*-
"""youtube: leer las TRANSCRIPCIONES de los vídeos (sin descargar vídeo ni audio).

Sustituye las tres costuras de red (`_buscar_sync`, `_info_sync`, `_descargar`): ningún test toca YouTube.
Comprobado en vivo antes de escribir esto: yt-dlp saca un subtítulo de ~4 KB sin el vídeo, y pedir
muchas pistas a la vez (es.*,en.* = ~10 traducciones automáticas) devolvió HTTP 429: por eso aquí se
pide UNA sola pista por vídeo (la original, manual antes que automática) y se cachea.

Ejecutar: python tests/unit/core/test_youtube.py
"""
import asyncio
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

yt = importlib.import_module("backend.core.infraestructura.youtube")

_fail, _pass = [], 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- enlaces
for url, esperado in [("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
                      ("https://youtu.be/dQw4w9WgXcQ?t=42", "dQw4w9WgXcQ"),
                      ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
                      ("https://m.youtube.com/watch?feature=share&v=dQw4w9WgXcQ&t=3", "dQw4w9WgXcQ"),
                      ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
                      ("https://example.com/watch?v=dQw4w9WgXcQ", None),
                      ("hola que tal", None)]:
    check(yt.id_de_url(url) == esperado, f"id_de_url({url!r}) = {esperado!r}")
check(yt.es_url_youtube("mira https://youtu.be/dQw4w9WgXcQ") and not yt.es_url_youtube("mira https://example.com"),
      "es_url_youtube detecta un enlace de YouTube dentro de un texto")

# ---------------------------------------------------------------- json3 -> líneas
data = {"events": [
    {"tStartMs": 0, "dDurationMs": 100, "id": 1},                                  # sin segs
    {"tStartMs": 18640, "dDurationMs": 3000, "segs": [{"utf8": "Conocemos"}, {"utf8": " bien  el\namor"}]},
    {"tStartMs": 21000, "segs": [{"utf8": "\n"}]},                                  # solo salto de línea
    {"tStartMs": 65500, "segs": [{"utf8": "Segundo   minuto"}]},
]}
lineas = yt._parse_json3(data)
check(lineas == [(18.64, "Conocemos bien el amor"), (65.5, "Segundo minuto")],
      f"json3: ignora eventos vacíos, une los trozos y pasa a segundos ({lineas})")

# ---------------------------------------------------------------- elección de pista (UNA)
def pistas(*exts):
    return [{"ext": e, "url": f"https://x/{e}"} for e in exts]


info_manual = {"language": "es", "subtitles": {"es-419": pistas("vtt", "json3"), "en": pistas("json3")},
               "automatic_captions": {"es-orig": pistas("json3"), "es": pistas("json3")}}
p = yt._elegir_pista(info_manual, ("es", "en"))
check(p and p["tipo"] == "manual" and p["idioma"] == "es-419" and p["url"].endswith("json3"),
      f"pista: el subtítulo MANUAL del idioma del vídeo gana a los automáticos ({p})")

info_auto = {"language": "en", "subtitles": {},
             "automatic_captions": {"en-en": pistas("json3"), "es-en": pistas("json3"), "en-orig": pistas("vtt", "json3"),
                                    "en": pistas("json3"), "es": pistas("json3"), "en-de-DE": pistas("json3")}}
p = yt._elegir_pista(info_auto, ("es", "en"))
check(p and p["tipo"] == "automática" and p["idioma"] == "en-orig",
      f"pista: entre los automáticos elige el ORIGINAL (-orig), no una traducción ({p})")

info_traduc = {"automatic_captions": {"es-en": pistas("json3"), "en-de-DE": pistas("json3")}, "subtitles": {}}
check(yt._elegir_pista(info_traduc, ("es", "en")) is None, "pista: solo traducciones automáticas -> no hay pista fiable")
check(yt._elegir_pista({"subtitles": {}, "automatic_captions": {}}, ("es", "en")) is None, "pista: sin subtítulos -> None")
check(yt._elegir_pista({"subtitles": {"fr": pistas("vtt")}, "automatic_captions": {}}, ("es", "en")) is None,
      "pista: sin formato json3 no se inventa otro")

# ---------------------------------------------------------------- transcripción (costuras simuladas)
estado = {"info": 0, "descargas": 0, "buscar": 0}
INFOS = {}
PISTAS = {}


def _info_falsa(vid):
    estado["info"] += 1
    r = INFOS[vid]
    if isinstance(r, Exception):
        raise r
    return r


async def _descargar_falsa(url):
    estado["descargas"] += 1
    r = PISTAS[url]
    if isinstance(r, Exception):
        raise r
    return r


yt._info_sync, yt._descargar = _info_falsa, _descargar_falsa


def video(vid, titulo, **extra):
    base = {"id": vid, "title": titulo, "channel": "Canal " + vid, "duration": 600, "language": "es",
            "subtitles": {"es": [{"ext": "json3", "url": f"https://pista/{vid}"}]}, "automatic_captions": {}}
    base.update(extra)
    INFOS[vid] = base
    PISTAS[f"https://pista/{vid}"] = {"events": [{"tStartMs": 1000, "segs": [{"utf8": f"texto de {vid}"}]},
                                                 {"tStartMs": 90000, "segs": [{"utf8": "otra frase interesante"}]}]}


yt._reset_estado()
video("AAAAAAAAAAA", "Vídeo A")
r = run(yt.transcripcion("https://youtu.be/AAAAAAAAAAA"))
check(r["ok"] and r["tipo"] == "manual" and r["idioma"] == "es" and r["title"] == "Vídeo A" and r["canal"] == "Canal AAAAAAAAAAA",
      f"transcripción: datos del vídeo y tipo de subtítulo ({r.get('tipo')}/{r.get('idioma')})")
check(r["lineas"][0] == (1.0, "texto de AAAAAAAAAAA") and "otra frase interesante" in r["texto"],
      "transcripción: líneas con su segundo y texto plano")
check(estado["descargas"] == 1, f"transcripción: UNA sola descarga de pista por vídeo ({estado['descargas']})")
run(yt.transcripcion("AAAAAAAAAAA"))
check(estado["descargas"] == 1 and estado["info"] == 1, "caché: repetir el mismo vídeo no vuelve a YouTube")

video("BBBBBBBBBBB", "Sin subtítulos", subtitles={}, automatic_captions={})
r = run(yt.transcripcion("BBBBBBBBBBB"))
check(not r["ok"] and r["motivo"] == "sin_subtitulos" and r["title"] == "Sin subtítulos", "sin subtítulos: lo dice con el título")
antes = estado["info"]
run(yt.transcripcion("BBBBBBBBBBB"))
check(estado["info"] == antes, "caché negativa: no vuelve a preguntar por un vídeo sin subtítulos")

INFOS["CCCCCCCCCCC"] = RuntimeError("ERROR: Video unavailable. This video is private")
r = run(yt.transcripcion("CCCCCCCCCCC"))
check(not r["ok"] and r["motivo"] == "no_disponible", "vídeo privado/borrado: motivo no_disponible")

INFOS["DDDDDDDDDDD"] = RuntimeError("HTTP Error 429: Too Many Requests")
r = run(yt.transcripcion("DDDDDDDDDDD"))
check(not r["ok"] and r["motivo"] == "limite", "429 de YouTube: motivo limite")
video("EEEEEEEEEEE", "Otro")
antes = estado["info"]
r = run(yt.transcripcion("EEEEEEEEEEE"))
check(not r["ok"] and r["motivo"] == "limite" and estado["info"] == antes,
      "tras un 429 hay un ENFRIAMIENTO: no se sigue golpeando a YouTube")
yt._reset_estado()

video("FFFFFFFFFFF", "Pista caída")
PISTAS["https://pista/FFFFFFFFFFF"] = yt.Limite("429 en la pista")
r = run(yt.transcripcion("FFFFFFFFFFF"))
check(not r["ok"] and r["motivo"] == "limite", "429 al bajar la pista: motivo limite")
yt._reset_estado()

# ---------------------------------------------------------------- pasajes relevantes
lineas = [(i * 10.0, ("relleno sin interés " * 12) if i != 30 else "aquí se explica cómo funciona el protocolo MQTT con QoS y retención")
          for i in range(60)]
texto, inicio = yt.ventanas_relevantes(lineas, "protocolo MQTT QoS", 1500)
check("protocolo MQTT" in texto and len(texto) <= 1600, f"pasajes: incluye lo relevante y respeta el tope ({len(texto)} caracteres)")
check(250 <= inicio <= 300, f"pasajes: el inicio marca dónde está lo relevante (≈ 300 s, salió {inicio})")
texto2, inicio2 = yt.ventanas_relevantes(lineas, "zzz yyy", 500)
check(texto2 and inicio2 == 0.0, "pasajes: sin coincidencias, se empieza por el principio")

# ---------------------------------------------------------------- búsqueda y fuentes
def _buscar_falsa(q, n):
    estado["buscar"] += 1
    return [{"id": "FFFFFFFFFFF", "title": "Pista caída", "channel": "c", "duration": 300},
            {"id": "BBBBBBBBBBB", "title": "Sin subtítulos", "channel": "c", "duration": 300},
            {"id": "G" * 11, "title": "Directo larguísimo", "channel": "c", "duration": 99999},
            {"id": "AAAAAAAAAAA", "title": "Vídeo A", "channel": "Canal A", "duration": 600},
            {"id": "AAAAAAAAAAA", "title": "Vídeo A (repetido)", "channel": "Canal A", "duration": 600},
            {"id": "HHHHHHHHHHH", "title": "Vídeo H", "channel": "Canal H", "duration": 700}]


yt._buscar_sync = _buscar_falsa
vids = run(yt.buscar_videos("mqtt", 6))
check([v["id"] for v in vids] == ["FFFFFFFFFFF", "BBBBBBBBBBB", "AAAAAAAAAAA", "HHHHHHHHHHH"],
      f"búsqueda: sin duplicados ni directos/vídeos de más de 4 h ({[v['id'] for v in vids]})")
check(vids[2]["url"] == "https://www.youtube.com/watch?v=AAAAAAAAAAA", "búsqueda: cada vídeo lleva su enlace")

yt._reset_estado()
estado.update(info=0, descargas=0)
video("AAAAAAAAAAA", "Vídeo A")
video("HHHHHHHHHHH", "Vídeo H")
video("BBBBBBBBBBB", "Sin subtítulos", subtitles={}, automatic_captions={})
video("FFFFFFFFFFF", "Pista caída")
PISTAS["https://pista/FFFFFFFFFFF"] = RuntimeError("error de red")
fuentes, omitidos = run(yt.fuentes_video("explicame mqtt", n=2, max_chars=300))
check([f["title"] for f in fuentes] == ["Vídeo A", "Vídeo H"], f"fuentes: las 2 primeras con transcripción ({[f['title'] for f in fuentes]})")
check(all(f["kind"] == "youtube" and "&t=" in f["url"] and f["url"].startswith("https://www.youtube.com/watch?v=")
          and f["canal"] and f["tipo"] == "manual" and 0 < len(f["text"]) <= 320 for f in fuentes),
      "fuentes: enlace con minuto, canal, tipo de subtítulo y texto acotado")
check(any("Sin subtítulos" in o and "subtítulos" in o for o in omitidos), f"fuentes: dice qué vídeos omitió y por qué ({omitidos})")
check(any("Pista caída" in o for o in omitidos), "fuentes: un vídeo que falla no tumba a los demás")

yt._reset_estado()
INFOS["AAAAAAAAAAA"] = RuntimeError("HTTP Error 429: Too Many Requests")
fuentes, omitidos = run(yt.fuentes_video("mqtt", n=2))
check(fuentes == [] and any("límite" in o.lower() or "limit" in o.lower() for o in omitidos),
      f"fuentes: ante un 429 corta y lo dice ({omitidos})")

print(f"\nyoutube: {_pass} OK, {len(_fail)} FAIL")
sys.exit(1 if _fail else 0)
