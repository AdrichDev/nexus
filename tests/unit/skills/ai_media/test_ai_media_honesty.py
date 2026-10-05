# -*- coding: utf-8 -*-
"""ai_media: salidas honestas, archivos seguros y rutas reales.

Encontrado auditando la ruta real de comandos (Docker) y leyendo el código:
  * el boceto SVG metía el texto del usuario sin escapar (XML roto y <script> en claro);
  * las rutas con espacios no se encontraban y el error nombraba una ruta recortada;
  * un .txt se respondía como si fuera una imagen («0 KB»);
  * la búsqueda web sin LLM tiraba los resultados encontrados y las fuentes no se veían;
  * la transcripción ignoraba que el LLM no estuviera disponible (el mensaje de error se
    guardaba como «análisis»), truncaba en silencio y dos audios con el mismo prefijo de
    nombre se pisaban en la memoria.

Todo simulado (websearch, LLM, Whisper, memoria); ficheros en un directorio temporal. Nivel M.
Ejecutar: python tests/unit/skills/ai_media/test_ai_media_honesty.py
"""
import asyncio
import sys
import tempfile
import types
from pathlib import Path
from xml.dom import minidom

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
media.OUT_DIR = TMP / "captures"


def correr(frase):
    r = sl.route(frase)
    assert r and r[0].folder == "ai_media", f"«{frase}» no llega a ai_media: {r and (r[0].folder, r[1])}"
    skill, intent, m = r
    return asyncio.run(skill.module.handle(intent, frase, m, None))


# 1) SVG seguro ----------------------------------------------------------------------------------
res = correr("genera una imagen de <script>alert(1)</script> & R&D")
svg = Path(res["data"]["file"]).read_text(encoding="utf-8")
try:
    minidom.parseString(svg.encode("utf-8"))
    valido = True
except Exception:
    valido = False
check(valido, "SVG: el boceto es XML válido aunque el texto lleve < > &")
check("<script>" not in svg, "SVG: el texto del usuario no puede inyectar un <script>")
check("R&amp;D" in svg, "SVG: el texto se conserva, escapado")

# 2) rutas ------------------------------------------------------------------------------------------
from PIL import Image  # noqa: E402

carpeta = TMP / "mi carpeta"
carpeta.mkdir()
png = carpeta / "foto roja.png"
Image.new("RGB", (64, 48), (200, 30, 30)).save(png)
for frase, nombre in [(f'analiza la imagen "{png}"', "con comillas"),
                      (f"analiza la imagen {png}", "sin comillas"),
                      (f"analiza la imagen {png} por favor", "con coletilla")]:
    reply = correr(frase)["reply"]
    check("64×48" in reply and "foto roja.png" in reply, f"ruta con espacios {nombre}: la encuentra")
reply = correr(f"analiza la imagen {TMP}/no existe/falta.png")["reply"]
check("falta.png" in reply and "no existe" in reply, "ruta inexistente: el error nombra la ruta completa tal como se escribió")

# 3) archivo que no es imagen ------------------------------------------------------------------
txt = TMP / "notas.txt"
txt.write_text("esto no es una imagen", encoding="utf-8")
reply = correr(f"analiza la imagen {txt}")["reply"]
check("no es una imagen" in reply.lower() or "no puedo abrir" in reply.lower(), "no imagen: lo dice")
check("0 KB" not in reply and "metadatos" not in reply.lower(), "no imagen: no lo presenta como una imagen con metadatos")
reply_png = correr(f"analiza la imagen {png}")["reply"]
check("bytes" in reply_png or "KB" in reply_png, "tamaños legibles (bytes/KB, nunca «0 KB» para algo pequeño)")
check("0 KB" not in reply_png, "tamaño: un archivo pequeño no se redondea a «0 KB»")

# 4) búsqueda web ---------------------------------------------------------------------------------
RESULTADOS = [{"title": "Chelsea gana el Mundial de Clubes", "url": "https://uno.example/a", "snippet": "final"},
              {"title": "Crónica de la final", "url": "https://dos.example/b", "snippet": "resumen"}]


async def _buscar(q, n=6):
    return list(RESULTADOS)


orig_search, orig_ask = websearch.search, llm.ask_llm
websearch.search = _buscar
try:
    async def _ask_ok(*a, **k):
        return ("Ganó el Chelsea.", "ollama")
    llm.ask_llm = _ask_ok
    res = correr("busca en internet quién ganó el mundial de clubes")
    check("Ganó el Chelsea." in res["reply"], "búsqueda: devuelve la respuesta del modelo")
    check("uno.example" in res["reply"] and "dos.example" in res["reply"] and "Fuentes" in res["reply"],
          "búsqueda: las fuentes se VEN en la respuesta, no solo en data")
    check(res.get("speak") is True, "búsqueda: con respuesta real, se puede locutar")

    async def _ask_caido(*a, **k):
        return ("Ollama no está en marcha, así que no puedo cargar ningún modelo local.", "ninguno")
    llm.ask_llm = _ask_caido
    res = correr("busca en internet quién ganó el mundial de clubes")
    check("Chelsea gana el Mundial de Clubes" in res["reply"] and "uno.example/a" in res["reply"],
          "búsqueda sin LLM: enseña los resultados que SÍ encontró")
    check("no pude redactar" in res["reply"].lower(), "búsqueda sin LLM: dice que no pudo redactar la respuesta")
    check(not res.get("speak"), "búsqueda sin LLM: no locuta un mensaje de error")
    check((res.get("data") or {}).get("sources"), "búsqueda sin LLM: sigue devolviendo las fuentes en data")
finally:
    websearch.search, llm.ask_llm = orig_search, orig_ask

# 5) transcripción ----------------------------------------------------------------------------------
class _Seg:
    def __init__(self, text):
        self.text = text


class _Modelo:
    def __init__(self, texto):
        self.texto = texto

    def transcribe(self, path, language="es", vad_filter=True):
        return [_Seg(self.texto)], object()


class _PgFalso:
    online = True

    def __init__(self):
        self.guardado = []

    def remember(self, content, kind="note", tags=None, **kw):
        self.guardado.append(content)
        return {"id": len(self.guardado), "duplicado": False}


notas = []


class _GrafoFalso:
    def write_note(self, title, content):
        notas.append((title, content))
        return "x.md"


def transcribir(ruta, texto, llm_ok=True):
    notas.clear()
    pg = _PgFalso()

    async def _ask(*a, **k):
        return (("Ideas: A, B, C", "ollama") if llm_ok else ("Ollama no está en marcha.", "ninguno"))

    o_ask, o_model, o_graph, o_pg = llm.ask_llm, stt._get_model, memory.graph, memory.pg
    sys.modules["faster_whisper"] = types.SimpleNamespace(WhisperModel=object)
    llm.ask_llm, stt._get_model, memory.graph, memory.pg = _ask, (lambda: _Modelo(texto)), _GrafoFalso(), pg
    try:
        res = correr(f"transcribe el audio {ruta}")
    finally:
        llm.ask_llm, stt._get_model, memory.graph, memory.pg = o_ask, o_model, o_graph, o_pg
        sys.modules.pop("faster_whisper", None)
    return res, pg


audio = TMP / "reunión larga.mp3"
audio.write_bytes(b"x")
largo = "INICIO " + ("palabra " * 3500) + "FINAL-DEL-AUDIO"          # ~28.000 caracteres
res, pg = transcribir(audio, largo)
contenido_nota = notas[0][1] if notas else ""
check("INICIO" in contenido_nota and "FINAL-DEL-AUDIO" in contenido_nota, "transcripción: la nota guarda el audio ENTERO, sin recortar")
todo_pg = " ".join(pg.guardado)
check("INICIO" in todo_pg and "FINAL-DEL-AUDIO" in todo_pg and len(pg.guardado) > 1,
      "transcripción: la base de datos recibe el texto entero, en trozos")
check("Ideas: A, B, C" in res["reply"] and "trozo" in res["reply"].lower(),
      "transcripción: la respuesta dice dónde quedó guardado")

res, pg = transcribir(audio, "hola mundo transcrito", llm_ok=False)
check("Ollama no está en marcha" not in (notas[0][1] if notas else ""), "sin LLM: el mensaje de error NO se guarda como análisis")
check("no pude analizar" in res["reply"].lower() and "hola mundo transcrito" in (notas[0][1] if notas else ""),
      "sin LLM: avisa de que no analizó y conserva la transcripción")

a1 = TMP / ("grabacion_reunion_equipo_ventas_2026_01_resumen_A" + ".mp3")
a2 = TMP / ("grabacion_reunion_equipo_ventas_2026_01_resumen_B" + ".mp3")
a1.write_bytes(b"1"); a2.write_bytes(b"2")
transcribir(a1, "contenido del primero"); t1 = notas[0][0]
transcribir(a2, "contenido del segundo"); t2 = notas[0][0]
check(t1 != t2, "notas: dos audios con el mismo prefijo de nombre NO comparten nota (no se pisan)")

print(f"\nai_media honesty: {_pass} OK, {len(_fail)} FAIL")
sys.exit(1 if _fail else 0)
