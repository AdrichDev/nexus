# -*- coding: utf-8 -*-
"""ESCRITURAS ATÓMICAS DE LOS ALMACENES JSON — ARQ-05 (roadmap P2-9, tarea T16).

El hallazgo de la auditoría: `comun/config.py` ya guardaba con `.tmp` +
`os.replace` desde el incidente de `settings.json`, pero los almacenes de
runtime escribían con `write_text()` a pelo. Si nexus muere entre el `open()`
y el último byte —o el disco se llena, o el JSON crece— el archivo queda a
medias y la carga siguiente se pierde ENTERA: cada `_load()` devuelve su valor
vacío (lista vacía, `{}`, o la semilla) y el guardado siguiente sobrescribe lo
poco que quedaba. Los almacenes del hallazgo:

  * `data/board.json` (+ `data/board_trash.json` y `data/board_seq.json`, que
    se escriben en la misma operación)
  * `data/jobs.json` — el panel de multitarea
  * `data/contentos.json` — Content OS
  * `data/proactive.json` — el estado de la proactividad
  * `config/settings.json` / `config/secrets.json` — ya lo hacían bien

Lo que se prueba, y por qué:

  A. Un ÚNICO ayudante (`backend/core/comun/atomicos.py`) escribe los JSON de
     runtime: `.tmp` en la misma carpeta y `os.replace`, que es indivisible.
     `config._write_json_atomic` sigue existiendo porque `dominio/reglas.py` lo
     llama, pero ahora delega: no hay dos implementaciones que puedan divergir.
  B. La escritura INTERRUMPIDA (se mata justo entre el `.tmp` y el reemplazo)
     deja el archivo anterior intacto y válido, y no deja basura `.tmp` al lado:
     el `.tmp` se borra donde se creó. Se comprueba almacén por almacén a través
     de su interfaz de verdad (add_task, delete_task, _persist, add_item…).
  C. El formato en disco NO cambia: `contentos.json` y `settings.json` a 2
     espacios, `board*.json`/`jobs.json` a 1, `board_seq.json` y
     `proactive.json` sin indentar, acentos sin escapar. Guardar dos veces deja
     el mismo texto. Nada que migrar: el operador no reescribe nada.
  D. Un archivo corrupto o vacío falla CERRADO como hoy, y cada almacén con SU
     comportamiento (se fija aquí para que no cambie de tapadillo).
  E. Guardia estructural: no aparece un `write_text()` NUEVO sobre un JSON de
     runtime fuera del ayudante. Los que quedan vivos hoy están congelados en
     `_PENDIENTES`, uno por uno: la lista solo puede encoger, y encogerla exige
     tocar este fichero a mano (misma fricción que `CAPAS.md`).

Fuera de este test queda, a propósito, la serialización por ruta: nexus es UN
proceso asyncio y estas escrituras son síncronas, así que dos corrutinas no
pueden solaparse dentro de un `write_text`+`os.replace`. No hay dos escritores
concurrentes del mismo almacén (ver el informe de la tarea T16), así que no se
añade ningún candado.

Lo que SÍ cambió (T13b, advisory del verificador sobre 562c777): el `.tmp` ya no
se llama `<archivo>.tmp`, que era un nombre FIJO y hacía que dos escritores del
mismo almacén se pisaran (en Windows el segundo falla con «WinError 32/5»: seguro,
pero con ruido). Ahora lleva un sufijo único por llamada (pid + `secrets.token_hex`)
en la MISMA carpeta, y sigue borrándose donde se creó. La sección A2 fija lo que
importa: nombres distintos por llamada y dos cortes seguidos sin residuo. No se
lanzan procesos de verdad: la garantía es única + limpieza, no paralelismo.

TODO EN PROCESO y en carpetas de usar y tirar: `NEXUS_DATA_DIR` y
`NEXUS_CONFIG_DIR` se apuntan ANTES de importar el backend, así que no se lee ni
se escribe un solo byte de los datos o la configuración del operador.

Ejecutar:  .venv\\Scripts\\python.exe tests\\unit\\core\\test_escrituras_atomicas.py
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                              # noqa: BLE001
    pass

# ANTES de importar el backend: ni los datos ni la configuración del operador.
_DATA = Path(tempfile.mkdtemp(prefix="nexus_atomico_data_"))
_CFG = Path(tempfile.mkdtemp(prefix="nexus_atomico_cfg_"))
os.environ["NEXUS_DATA_DIR"] = str(_DATA)
os.environ["NEXUS_CONFIG_DIR"] = str(_CFG)

import backend.core.aplicacion.background as background        # noqa: E402
import backend.core.aplicacion.jobs as jobsmod                # noqa: E402
import backend.core.comun.config as configmod                  # noqa: E402
import backend.core.dominio.board as board                     # noqa: E402
import backend.core.dominio.contentos as contentos             # noqa: E402

try:
    from backend.core.comun import atomicos
    _SIN_AYUDANTE = ""
except Exception as exc:                                       # noqa: BLE001
    atomicos = None
    _SIN_AYUDANTE = f"{type(exc).__name__}: {exc}"

AYUDANTE = ROOT / "backend" / "core" / "comun" / "atomicos.py"

# Los módulos que la tarea T16 migra al ayudante. Si uno vuelve a escribir su
# JSON a pelo, aparece como hallazgo nuevo (no está en `_PENDIENTES`) y esto
# falla: es la garantía de que el arreglo no se deshace sin que se note.
_MIGRADOS = (
    "backend/core/comun/config.py",
    "backend/core/aplicacion/background.py",
    "backend/core/aplicacion/jobs.py",
    "backend/core/dominio/board.py",
    "backend/core/dominio/contentos.py",
)

# DEUDA CONGELADA (auditoría ARQ-05, 2026-08-06). Son almacenes JSON de runtime
# que todavía escriben con `write_text()` a pelo, y siguen así porque la tarea
# T16 tiene una superficie de edición cerrada: estos ficheros no están en ella.
# Tres de ellos (vigilancias, websearch, youtube) ya se hicieron atómicos A MANO
# con su propio `.tmp` + replace: funcionan, pero son la copia que este ayudante
# viene a sustituir cuando se toquen.
#
# La lista SOLO puede encoger. Migrar uno de estos = quitarlo de aquí, y este
# test lo exige (si ya no aparece, la lista está mintiendo).
_PENDIENTES = {
    "backend/core/aplicacion/brain.py",
    "backend/core/dominio/briefing.py",
    "backend/core/dominio/memory.py",
    "backend/core/dominio/opmem.py",
    "backend/core/dominio/pm.py",
    "backend/core/dominio/purga.py",
    "backend/core/dominio/rag.py",
    "backend/core/dominio/review.py",
    "backend/core/dominio/selflearn.py",
    "backend/core/infraestructura/app_index.py",
    "backend/core/infraestructura/files_io.py",
    "backend/core/infraestructura/remote.py",
    "backend/core/infraestructura/spotify.py",
    "backend/core/infraestructura/websearch.py",
    "backend/core/infraestructura/youtube.py",
    "skills/google_workspace/skill.py",
    "skills/hermes/skill.py",
    "skills/instagram/scripts/ig.py",
    "skills/instagram/skill.py",
    "skills/media/skill.py",
    "skills/system_pc/skill.py",
    "skills/telefono/skill.py",
    "skills/vigilancias/skill.py",
}

_fail: list[str] = []
_pass = 0


def check(cond, msg: str) -> bool:
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  ✖ " + msg)
    return bool(cond)


def _texto(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _basura_tmp(carpeta: Path) -> list[str]:
    return sorted(x.name for x in carpeta.glob("*.tmp")) if carpeta.exists() else []


def _borra(*rutas: Path) -> None:
    """Un almacén limpio: el fichero, su `.bak` y cualquier `.tmp`."""
    for f in rutas:
        for x in (f, f.with_name(f.name + ".bak"), f.with_name(f.name + ".tmp")):
            if x.exists():
                x.unlink()


@contextmanager
def _corte_entre_el_tmp_y_el_reemplazo(que: str):
    """Simula que nexus MUERE justo cuando el `.tmp` ya está escrito.

    Es el momento exacto del bug: con `write_text()` a pelo ese corte deja el
    archivo bueno truncado; con `.tmp` + `os.replace` el bueno ni se toca. Se
    dobla `os.replace` (que es lo que usa el ayudante) y se restaura pase lo que
    pase, para que un fallo aquí no envenene el resto de la suite."""
    real = os.replace

    def _muere(src, dst):
        raise OSError(f"simulacion de corte a mitad de escritura: {que}")

    os.replace = _muere
    try:
        yield
    finally:
        os.replace = real


def _limpia_board() -> None:
    _borra(board.BOARD_FILE, board.TRASH_FILE, board.SEQ_FILE)


# ══════════════════════════════════════════════════════════════════════════
print("== 0) cada almacén apunta a una carpeta de usar y tirar (nada del operador) ==")
# ══════════════════════════════════════════════════════════════════════════
_ALMACENES = {
    "board.json": board.BOARD_FILE,
    "board_trash.json": board.TRASH_FILE,
    "board_seq.json": board.SEQ_FILE,
    "jobs.json": jobsmod.JOBS_FILE,
    "contentos.json": contentos.STORE,
    "proactive.json": background._STATE,
    "settings.json": configmod.CONFIG_FILE,
}
for nombre, ruta in _ALMACENES.items():
    donde = str(ruta)
    check(donde.startswith(str(_DATA)) or donde.startswith(str(_CFG)),
          f"{nombre} apunta fuera del arenero ({donde}): esta suite no puede tocar datos del operador")


# ══════════════════════════════════════════════════════════════════════════
print("\n== A) el ayudante compartido: .tmp + os.replace, y nadie más lo reimplementa ==")
# ══════════════════════════════════════════════════════════════════════════
check(atomicos is not None,
      f"no existe el ayudante compartido backend/core/comun/atomicos.py ({_SIN_AYUDANTE}): "
      "cada almacén seguiría escribiendo con write_text() a pelo")
check(hasattr(configmod, "_write_json_atomic"),
      "config._write_json_atomic ha desaparecido: dominio/reglas.py lo llama")

if atomicos is not None:
    _sonda = _DATA / "sonda" / "almacen.json"
    _borra(_sonda)
    atomicos.escribir_json_atomico(_sonda, {"a": 1, "ñ": "acento"})
    check(_sonda.exists(), "el ayudante no ha creado el fichero (ni su carpeta)")
    check(_sonda.read_text(encoding="utf-8") == '{"a": 1, "ñ": "acento"}',
          f"el JSON por defecto del ayudante no es el de siempre (sin indentar y sin "
          f"escapar acentos): {_sonda.read_text(encoding='utf-8')!r}")
    atomicos.escribir_json_atomico(_sonda, {"a": 2, "ñ": "acento"}, indent=2)
    check(_sonda.read_text(encoding="utf-8") == '{\n  "a": 2,\n  "ñ": "acento"\n}',
          f"con indent=2 el JSON no sale como el de contentos/settings: "
          f"{_sonda.read_text(encoding='utf-8')!r}")
    check(not _basura_tmp(_sonda.parent), f"el ayudante deja .tmp detrás: {_basura_tmp(_sonda.parent)}")

    # El .bak es contrato de config (y de reglas): respaldo de la versión BUENA.
    atomicos.escribir_json_atomico(_sonda, {"a": 2}, respaldo=True)
    _bak = _sonda.with_name(_sonda.name + ".bak")
    check(_bak.exists() and json.loads(_bak.read_text(encoding="utf-8")) == {"a": 2, "ñ": "acento"},
          "con respaldo=True no queda un .bak con la versión anterior válida")

    # Un archivo corrupto NO se respalda: un .bak con basura es peor que ninguno.
    _borra(_sonda)
    _sonda.parent.mkdir(parents=True, exist_ok=True)
    _sonda.write_text("{roto", encoding="utf-8")
    atomicos.escribir_json_atomico(_sonda, {"a": 3}, respaldo=True)
    check(not _bak.exists(), "se ha respaldado un archivo corrupto en el .bak")
    check(json.loads(_sonda.read_text(encoding="utf-8")) == {"a": 3},
          "el archivo bueno no se ha escrito sobre el corrupto")

    # Y el corte: el original no se toca y no queda basura.
    _sonda.write_text('{"bueno": true}', encoding="utf-8")
    with _corte_entre_el_tmp_y_el_reemplazo("el ayudante"):
        try:
            atomicos.escribir_json_atomico(_sonda, {"bueno": False})
            check(False, "el ayudante se ha tragado el corte en vez de propagar el error")
        except OSError:
            check(True, "")
    check(_texto(_sonda) == '{"bueno": true}',
          f"tras el corte el original ha cambiado: {_texto(_sonda)!r}")
    check(not _basura_tmp(_sonda.parent),
          f"tras el corte queda un .tmp huérfano: {_basura_tmp(_sonda.parent)}")


# ══════════════════════════════════════════════════════════════════════════
print("\n== A2) el .tmp es ÚNICO por llamada: dos escritores no chocan (T13b) ==")
# ══════════════════════════════════════════════════════════════════════════
# El nombre del `.tmp` era fijo (`<archivo>.tmp`), así que dos escritores del
# mismo almacén se pisaban: en Windows el segundo falla con «WinError 32/5» y la
# escritura se rechaza (falla SEGURO, pero con ruido que el operador ve en cuanto
# una herramienta guarda mientras la app está abierta). Con un sufijo único por
# llamada, cada uno publica su propio archivo y el `os.replace` sigue siendo
# indivisible. Lo que se fija aquí es ÚNICO + LIMPIEZA; no se lanzan procesos.
if atomicos is None:
    check(False, "sin ayudante no hay .tmp único que comprobar")
else:
    _sonda2 = _DATA / "sonda" / "unico.json"
    _borra(_sonda2)

    _real_replace = os.replace

    def _nombres_de_tmp(veces: int) -> list[Path]:
        """Los `.tmp` que el ayudante usa de verdad, apuntados al publicar."""
        vistos: list[Path] = []

        def _apunta(src, dst):
            vistos.append(Path(src))
            return _real_replace(src, dst)

        os.replace = _apunta
        try:
            for n in range(veces):
                atomicos.escribir_json_atomico(_sonda2, {"n": n})
        finally:
            os.replace = _real_replace
        return vistos

    _usados = _nombres_de_tmp(2)
    check(len(_usados) == 2, f"el ayudante no publicó dos veces: {_usados}")
    check(_usados[0] != _usados[1],
          f"el .tmp es el MISMO en las dos llamadas ({_usados[0].name}): dos escritores "
          "del mismo almacén chocan en Windows")
    check(all(t.parent == _sonda2.parent for t in _usados),
          f"algún .tmp no está en la carpeta del destino: {[str(t.parent) for t in _usados]}")
    check(all(t.name.startswith(_sonda2.name) and t.name.endswith(".tmp") for t in _usados),
          f"el .tmp ya no se reconoce como el del destino: {[t.name for t in _usados]}")
    check(not any(t.exists() for t in _usados),
          "un .tmp se ha quedado en el disco después de publicar")
    check(not _basura_tmp(_sonda2.parent), f"queda basura .tmp: {_basura_tmp(_sonda2.parent)}")

    # Dos cortes SEGUIDOS (dos intentos de escritura que mueren justo antes del
    # reemplazo): cada uno usa su propio `.tmp`, ninguno deja residuo y el
    # archivo bueno sigue siendo el de antes.
    _borra(_sonda2)
    atomicos.escribir_json_atomico(_sonda2, {"bueno": True})
    _rotos: list[Path] = []

    def _apunta_y_muere(src, dst):
        _rotos.append(Path(src))
        raise OSError("simulacion de corte a mitad de escritura (dos veces)")

    for _intento in (1, 2):
        os.replace = _apunta_y_muere
        try:
            atomicos.escribir_json_atomico(_sonda2, {"bueno": False, "intento": _intento})
            check(False, f"el ayudante se ha tragado el corte del intento {_intento}")
        except OSError:
            check(True, "")
        finally:
            os.replace = _real_replace
    check(len(_rotos) == 2 and _rotos[0] != _rotos[1],
          f"los dos cortes usaron el mismo .tmp ({[t.name for t in _rotos]}): no son únicos")
    check(_texto(_sonda2) == '{"bueno": true}',
          f"tras dos cortes el archivo bueno ha cambiado: {_texto(_sonda2)!r}")
    check(not _basura_tmp(_sonda2.parent),
          f"tras dos cortes queda un .tmp huérfano: {_basura_tmp(_sonda2.parent)}")
    check(not any(t.exists() for t in _rotos),
          "algún .tmp de un corte sigue en el disco")


# ══════════════════════════════════════════════════════════════════════════
print("\n== B) escritura interrumpida: el almacén anterior sigue entero y válido ==")
# ══════════════════════════════════════════════════════════════════════════

print("  · board.json + board_seq.json")
_limpia_board()
board.add_task("Comprar leche")
_antes_board, _antes_seq = _texto(board.BOARD_FILE), _texto(board.SEQ_FILE)
check(json.loads(_antes_board) and _antes_seq == '{"last": 1}',
      "el tablero recién sembrado no está en el disco como se esperaba")
with _corte_entre_el_tmp_y_el_reemplazo("board._save"):
    try:
        board.add_task("Una tarea que llega justo cuando se corta la luz")
        check(False, "board.add_task no propaga el fallo de escritura: se pierde en silencio")
    except OSError:
        check(True, "")
check(_texto(board.BOARD_FILE) == _antes_board,
      "el corte ha modificado board.json: la tarea anterior se ha perdido")
check(json.loads(_texto(board.BOARD_FILE)), "board.json ya no es JSON válido tras el corte")
check(_texto(board.SEQ_FILE) == _antes_seq,
      f"el corte ha modificado board_seq.json: {_texto(board.SEQ_FILE)!r}")
check([t["title"] for t in board.board()["pendiente"]] == ["Comprar leche"],
      f"el tablero no carga la tarea anterior tras el corte: {board.board()}")
check(not _basura_tmp(board.BOARD_FILE.parent),
      f"el corte deja basura .tmp en data/: {_basura_tmp(board.BOARD_FILE.parent)}")

print("  · board_trash.json")
board.add_task("Tarea que se va a la papelera")
_antes_board = _texto(board.BOARD_FILE)
with _corte_entre_el_tmp_y_el_reemplazo("board._to_trash"):
    try:
        board.delete_task("Tarea que se va a la papelera")
        check(False, "board.delete_task no propaga el fallo de escritura de la papelera")
    except OSError:
        check(True, "")
check(board.find_task("Tarea que se va a la papelera") is not None,
      "un corte guardando la papelera ha borrado la tarea del tablero")
check(_texto(board.BOARD_FILE) == _antes_board,
      "un corte guardando la papelera ha modificado board.json (borrado a medias)")

print("  · jobs.json")
_borra(jobsmod.JOBS_FILE)
jm = jobsmod.JobManager(max_concurrent=2)
jm._jobs = {"j1": {"id": "j1", "num": 1, "status": "completed", "request": "hola",
                   "result": "hecho", "seen": True}}
jm._order, jm._counter = ["j1"], 1
jm._persist()
_antes_jobs = _texto(jobsmod.JOBS_FILE)
check(len(json.loads(_antes_jobs)) == 1, "jobs.json no se ha sembrado")
jm._jobs["j2"] = {"id": "j2", "num": 2, "status": "completed", "request": "otra",
                  "result": "hecho", "seen": True}
jm._order.append("j2")
with _corte_entre_el_tmp_y_el_reemplazo("jobs._persist"):
    jm._persist()                       # ningún trabajo puede romperse por un guardado
check(_texto(jobsmod.JOBS_FILE) == _antes_jobs,
      f"el corte ha modificado jobs.json: {_texto(jobsmod.JOBS_FILE)[:120]!r}")
check([j["id"] for j in json.loads(_texto(jobsmod.JOBS_FILE))] == ["j1"],
      "jobs.json ya no conserva el trabajo anterior tras el corte")
check([j["id"] for j in jobsmod.JobManager().snapshot()] == ["j1"],
      "el panel de multitarea no recupera el trabajo anterior tras el corte")
check(not _basura_tmp(jobsmod.JOBS_FILE.parent),
      f"el corte deja basura .tmp en data/: {_basura_tmp(jobsmod.JOBS_FILE.parent)}")

print("  · contentos.json")
_borra(contentos.STORE)
contentos.add_item("idea", "una idea que ya estaba")
_antes_cos = _texto(contentos.STORE)
with _corte_entre_el_tmp_y_el_reemplazo("contentos._save"):
    try:
        contentos.add_item("idea", "una idea que llega con la luz yéndose")
        check(False, "contentos.add_item no propaga el fallo de escritura")
    except OSError:
        check(True, "")
check(_texto(contentos.STORE) == _antes_cos,
      "el corte ha modificado contentos.json: la idea anterior se ha perdido")
check(json.loads(_texto(contentos.STORE))["ideas"] == ["una idea que ya estaba"],
      f"contentos.json no conserva la idea anterior: {_texto(contentos.STORE)[:160]!r}")
check(contentos._load()["ideas"] == ["una idea que ya estaba"],
      "Content OS recarga desde disco algo distinto de lo guardado")

print("  · proactive.json")
_borra(background._STATE)
background._save({"ultimo": "20260101", "avisos": 2})
_antes_pro = _texto(background._STATE)
with _corte_entre_el_tmp_y_el_reemplazo("background._save"):
    background._save({"ultimo": "20260102", "avisos": 0})   # este se traga el fallo
check(_texto(background._STATE) == _antes_pro,
      f"el corte ha modificado proactive.json: {_texto(background._STATE)!r}")
check(background._load() == {"ultimo": "20260101", "avisos": 2},
      "la proactividad recarga un estado distinto del guardado")
check(not _basura_tmp(background._STATE.parent),
      f"el corte deja basura .tmp en data/: {_basura_tmp(background._STATE.parent)}")


# ══════════════════════════════════════════════════════════════════════════
print("\n== C) el formato en disco no cambia (nada que migrar) ==")
# ══════════════════════════════════════════════════════════════════════════
_limpia_board()
board.add_task("Revisar el día 3")             # acento a propósito: ensure_ascii=False
_tareas = json.loads(_texto(board.BOARD_FILE))
check(_texto(board.BOARD_FILE) == json.dumps(_tareas, ensure_ascii=False, indent=1),
      "board.json ya no se escribe con indent=1 y sin escapar acentos")
check("Revisar el día 3" in _texto(board.BOARD_FILE),
      "board.json escapa los acentos (ensure_ascii): el operador ve \\u00ed en el archivo")
check(list(_tareas[0]) == list(board.board()["pendiente"][0]),
      "el orden de claves en disco ya no es el de la tarea en RAM")
check(_texto(board.BOARD_FILE) == json.dumps(json.loads(_texto(board.BOARD_FILE)),
                                            ensure_ascii=False, indent=1),
      "board.json no es idempotente: guardar dos veces cambia el texto")
check(_texto(board.SEQ_FILE) == '{"last": 1}',
      f"board_seq.json ha cambiado de formato: {_texto(board.SEQ_FILE)!r}")

board.delete_task("Revisar el día 3")
_trash = json.loads(_texto(board.TRASH_FILE))
check(_texto(board.TRASH_FILE) == json.dumps(_trash, ensure_ascii=False, indent=1),
      "board_trash.json ya no se escribe con indent=1")

_borra(jobsmod.JOBS_FILE)
jm = jobsmod.JobManager(max_concurrent=2)
jm._jobs = {"j1": {"id": "j1", "num": 1, "status": "completed", "request": "día",
                   "result": "hecho", "seen": True}}
jm._order, jm._counter = ["j1"], 1
jm._persist()
_jobs = json.loads(_texto(jobsmod.JOBS_FILE))
check(_texto(jobsmod.JOBS_FILE) == json.dumps(_jobs, ensure_ascii=False, indent=1),
      "jobs.json ya no se escribe con indent=1 y sin escapar acentos")

_borra(contentos.STORE)
contentos.add_item("learning", "Publicar los días de diario")
_cos = json.loads(_texto(contentos.STORE))
check(_texto(contentos.STORE) == json.dumps(_cos, ensure_ascii=False, indent=2),
      f"contentos.json ya no se escribe con indent=2: {_texto(contentos.STORE)[:120]!r}")
check("días" in _texto(contentos.STORE),
      "contentos.json escapa los acentos (ensure_ascii): cambia el archivo del operador")

_borra(background._STATE)
background._save({"ultimo": "20260101"})
check(_texto(background._STATE) == '{"ultimo": "20260101"}',
      f"proactive.json ha cambiado de formato: {_texto(background._STATE)!r}")


# ══════════════════════════════════════════════════════════════════════════
print("\n== D) un archivo corrupto o vacío sigue fallando CERRADO como hoy ==")
# ══════════════════════════════════════════════════════════════════════════
_limpia_board()
board.BOARD_FILE.parent.mkdir(parents=True, exist_ok=True)
board.BOARD_FILE.write_text("{media tarea", encoding="utf-8")
check(board.board() == {"pendiente": [], "progreso": [], "revision": [], "completada": []},
      "un board.json corrupto ya no cae al tablero vacío")
check(_texto(board.BOARD_FILE) == "{media tarea",
      "un board.json corrupto se reescribe solo (hoy no se toca hasta el próximo guardado)")
check(board.add_task("tras el corte")["key"] == "NX-1",
      "tras un board.json corrupto el tablero no vuelve a funcionar")

_limpia_board()
board.add_task("t1")
board.SEQ_FILE.write_text("no es json", encoding="utf-8")
check(board.add_task("t2")["key"] == "NX-2",
      "con board_seq.json corrupto la clave se reutiliza (hoy la marca se pierde y manda el tablero)")

board.TRASH_FILE.write_text("", encoding="utf-8")
check(board.trash() == [], "una papelera vacía/corrupta ya no cae a lista vacía")

jobsmod.JOBS_FILE.write_text("{", encoding="utf-8")
_vacio = jobsmod.JobManager()
check(_vacio.snapshot() == [] and _vacio._counter == 0,
      "un jobs.json corrupto ya no arranca el panel vacío")

contentos.STORE.parent.mkdir(parents=True, exist_ok=True)
contentos.STORE.write_text("", encoding="utf-8")
_semilla = contentos._seed()
check(contentos._load() == _semilla,
      "un contentos.json vacío ya no cae a la semilla")
check(json.loads(_texto(contentos.STORE)) == _semilla,
      "la semilla de Content OS no se ha vuelto a escribir en el almacén")

background._STATE.write_text("{", encoding="utf-8")
check(background._load() == {}, "un proactive.json corrupto ya no cae a estado vacío")


# ══════════════════════════════════════════════════════════════════════════
print("\n== E) guardia estructural: nadie escribe un JSON de runtime a pelo ==")
# ══════════════════════════════════════════════════════════════════════════
def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def _escrituras_json_a_pelo() -> list[tuple[str, int, str]]:
    """Cada `write_text()` cuyo destino o contenido es un JSON, fuera del ayudante.

    Se mira el AST y no el texto a propósito: un comentario o un docstring que
    mencione `write_text(` no debe contar (ni tapar) nada. El destino se nombra
    en el mensaje para que el hallazgo se pueda arreglar sin buscarlo a mano."""
    fuera: list[tuple[str, int, str]] = []
    for base in ("backend", "skills"):
        for py in sorted((ROOT / base).rglob("*.py")):
            if "__pycache__" in py.parts or py.resolve() == AYUDANTE.resolve():
                continue
            try:
                arbol = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError as exc:
                fuera.append((_rel(py), 0, f"no parsea: {exc}"))
                continue
            for nodo in ast.walk(arbol):
                if not isinstance(nodo, ast.Call):
                    continue
                fn = nodo.func
                if not (isinstance(fn, ast.Attribute) and fn.attr == "write_text"):
                    continue
                destino = ast.unparse(fn.value)
                escrito = " ".join(ast.unparse(a) for a in nodo.args)
                if ".json" in (destino + escrito).lower() or "json.dumps" in escrito:
                    fuera.append((_rel(py), nodo.lineno, destino))
    return fuera


_hallazgos = _escrituras_json_a_pelo()
_nuevos = [h for h in _hallazgos if h[0] not in _PENDIENTES]
check(not _nuevos,
      "hay write_text() nuevos sobre un JSON de runtime: usa "
      f"comun/atomicos.escribir_json_atomico() -> {[(f, n, d) for f, n, d in _nuevos]}")

_de_los_migrados = [h for h in _hallazgos if h[0] in _MIGRADOS]
check(not _de_los_migrados,
      f"un almacén migrado ha vuelto a escribir a pelo: {_de_los_migrados}")

_saldados = sorted(_PENDIENTES - {h[0] for h in _hallazgos})
check(not _saldados,
      f"ya no escriben a pelo, quítalos de _PENDIENTES en este test: {_saldados}")

_solapados = sorted(_PENDIENTES & set(_MIGRADOS))
check(not _solapados,
      f"un almacén migrado está a la vez en _PENDIENTES: {_solapados}")

for modulo, ruta in (("board", ROOT / "backend/core/dominio/board.py"),
                     ("jobs", ROOT / "backend/core/aplicacion/jobs.py"),
                     ("contentos", ROOT / "backend/core/dominio/contentos.py"),
                     ("background", ROOT / "backend/core/aplicacion/background.py"),
                     ("config", ROOT / "backend/core/comun/config.py")):
    check("escribir_json_atomico" in ruta.read_text(encoding="utf-8"),
          f"{modulo} no usa el ayudante compartido: su JSON se puede quedar a medias")


# ══════════════════════════════════════════════════════════════════════════
print("\n== F) lo que ya funcionaba sigue igual: config conserva su .bak ==")
# ══════════════════════════════════════════════════════════════════════════
_borra(configmod.CONFIG_FILE)
configmod.settings.set("operator_name", "Ada")
check(json.loads(_texto(configmod.CONFIG_FILE)).get("operator_name") == "Ada",
      "settings.json ya no guarda lo que se le pide")
configmod.settings.set("operator_name", "Bea")
_bak_cfg = configmod.CONFIG_FILE.with_name(configmod.CONFIG_FILE.name + ".bak")
check(_bak_cfg.exists(), "settings.json ha perdido su .bak: la recuperación de config se queda sin red")
check(json.loads(_texto(_bak_cfg)).get("operator_name") == "Ada",
      "el .bak de settings.json ya no es la versión anterior")
check(_texto(configmod.CONFIG_FILE) ==
      json.dumps(json.loads(_texto(configmod.CONFIG_FILE)), indent=2, ensure_ascii=False),
      "settings.json ya no se escribe con indent=2 y sin escapar acentos")
configmod.CONFIG_FILE.write_text("{truncado", encoding="utf-8")
check(configmod._read_json_safe(configmod.CONFIG_FILE).get("operator_name") == "Ada",
      "con settings.json truncado ya no se recurre al .bak")

# `dominio/reglas.py` llama a config._write_json_atomic: tiene que seguir
# dejando el mismo .bak que antes aunque ahora delegue.
_sonda_reglas = _CFG / "reglas_sonda.json"
_borra(_sonda_reglas)
configmod._write_json_atomic(_sonda_reglas, {"v": 1})
configmod._write_json_atomic(_sonda_reglas, {"v": 2})
check(json.loads(_texto(_sonda_reglas)) == {"v": 2},
      "config._write_json_atomic ya no escribe la versión nueva")
check(json.loads(_texto(_sonda_reglas.with_name(_sonda_reglas.name + ".bak"))) == {"v": 1},
      "config._write_json_atomic ya no deja el .bak de la versión anterior (lo usa reglas)")


# ══════════════════════════════════════════════════════════════════════════
shutil.rmtree(_DATA, ignore_errors=True)
shutil.rmtree(_CFG, ignore_errors=True)

print(f"\n{'#' * 60}\nRESULTADO escrituras atómicas: {_pass} OK / {len(_fail)} fallos "
      f"({'' if not _fail else 'REVISAR'})")
for m in _fail:
    print("  -", m)
sys.exit(1 if _fail else 0)
