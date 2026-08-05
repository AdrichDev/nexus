# -*- coding: utf-8 -*-
"""Auditoría de la skill TABLERO: activación con frases naturales, enrutado real,
ámbito de los borrados masivos y confirmación obligatoria antes de borrar nada.

No toca el tablero del usuario: `backend.core.dominio.board` se apunta a un data/ temporal
antes de importar la skill, así que las tareas de esta suite son inventadas.

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_skill_tasks_board.py
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_fail = []
_pass = 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  ✖ " + msg)


# El tablero se desvía a un temporal ANTES de que nadie lo lea.
TMP = tempfile.mkdtemp(prefix="nexus_board_test_")
from backend.core.aplicacion import skills_loader as sl
from backend.core.dominio import board
from backend.core.comun import confirm  # noqa: E402

board.BOARD_FILE = __import__("pathlib").Path(TMP) / "board.json"
board.TRASH_FILE = __import__("pathlib").Path(TMP) / "board_trash.json"

# ------------------------------------------------- 1) carga con el cargador real
print("== 1) la skill carga como la carga nexus (skills_loader) ==")
REG = sl.load_skills()
TSK = REG.get("tasks_board")
check(TSK is not None, "skills_loader no registra la carpeta 'tasks_board'")
check(TSK is not None and TSK.status != "error",
      f"la skill tasks_board no carga: {TSK.description if TSK else ''}")
MOD = TSK.module if TSK else None
check(MOD is not None and hasattr(MOD, "handle"), "tasks_board no expone handle()")

INTENTS = list(TSK.patterns.keys()) if TSK else []
for i in ("create", "snooze", "marcar", "move", "start", "late", "organize",
          "restore", "trash", "clear", "delete", "show"):
    check(i in INTENTS, f"falta el intent «{i}»")
check(INTENTS and INTENTS[-1] == "show",
      "«show» ya no es el último intent: es amplísimo y se tragaría a los demás")

# --------------------------------------------- 2) activación: frases naturales
print("== 2) activación con frases naturales (tildes, enclíticos, sinónimos) ==")
ACTIVAN = {
    "create": ["crea la tarea diseñar logo", "créame la tarea diseñar logo",
               "apúntame la tarea comprar pan",
               "añade la tarea revisar el informe para el viernes",
               "apunta la mentoría el jueves a las 18"],
    "move": ["mueve diseñar logo a en progreso", "pasa el informe a review",
             "cambia la web a completadas"],
    "start": ["me pongo con la web del cliente", "arranco con el logo"],
    "marcar": ["marca la compra como hecha", "da por hecha la compra"],
    "show": ["ver tablero", "muéstrame mis tareas", "enséñame las tareas",
             "qué tengo pendiente", "tareas", "cómo van mis tareas"],
    "late": ["qué tareas van retrasadas", "tareas fuera de plazo"],
    "organize": ["organiza mis tareas por urgencia", "prioriza el tablero",
                 "matriz de eisenhower"],
    "delete": ["borra la tarea diseñar logo", "bórrame la tarea diseñar logo",
               "elimina la tarea diseñar logo", "elimíname la tarea diseñar logo",
               "quítame la tarea diseñar logo", "táchame la tarea diseñar logo"],
    "clear": ["borra las tareas completadas", "bórrame las tareas completadas",
              "limpia las ya realizadas", "vacía el tablero", "borra todas las tareas"],
    "restore": ["recupera las tareas borradas", "recupéramelas", "deshaz el borrado",
                "restaura la tarea diseñar logo"],
    "trash": ["ver la papelera", "qué tareas has borrado", "vacía la papelera"],
    "snooze": ["recuérdamelo más tarde", "recuérdamelo en 3 horas",
               "pospón el recordatorio"],
}
for intent, frases in ACTIVAN.items():
    for f in frases:
        r = sl.route(f)
        destino = f"{r[0].folder}/{r[1]}" if r else "ningún sitio"
        check(bool(r) and r[0].folder == "tasks_board" and r[1] == intent,
              f"«{f}» debería ser tasks_board/{intent} y va a {destino}")

print("== 2b) llegar al intent no basta: hay que EXTRAER bien el título ==")
# Medido contra nexus en marcha: «marca como completada X» llegaba a
# `marcar` y contestaba «No encuentro esa tarea». El patrón esperaba el
# orden «marca X como ESTADO», así que con el estado delante el grupo
# perezoso capturaba literalmente «como» y luego buscaba una tarea
# titulada «como». El test de arriba lo daba por bueno porque solo miraba
# a qué intent llegaba, no qué sacaba de la frase.
TITULOS = [
    ("marca la compra como hecha",                 "la compra",  "hecha"),
    ("marca como completada la compra",            "la compra",  "completada"),
    ("marca como hecha la tarea revisar el acta",  "revisar el acta", "hecha"),
    ("da por hecha la compra",                     "la compra",  "hecha"),
    ("marca revisar el acta como completada",      "revisar el acta", "completada"),
]
# PENDIENTE, y ajeno a este arreglo: el verbo «pon» no llega a esta skill.
# «pon como terminada la web del cliente» se la queda `system_pc/open_web` y «pon
# como terminada la propuesta» se la queda `media/play`, porque ambas skills van
# antes por orden alfabetico y sus patrones ven «pon ... la web» y «pon ...». Es
# un choque entre skills ANTERIOR a este arreglo: se deja anotado y no se tapa
# aqui, porque arreglaria una frase y rompería «pon la web de google» y «pon
# musica». Con «marca» no hay disputa, y es lo que se prueba arriba.
for frase, titulo_esperado, estado_esperado in TITULOS:
    r = sl.route(frase)
    if not (r and r[1] == "marcar"):
        check(False, f"«{frase}» ya no llega a tasks_board/marcar: "
                     f"{(r[0].folder + '/' + r[1]) if r else 'ningún sitio'}")
        continue
    g = r[2].groupdict()
    tarea = (g.get("task5") or g.get("task3") or g.get("task4") or "").strip()
    estado = (g.get("state5") or g.get("state3") or g.get("state4") or "").strip()
    # El artículo puede venir o no según la rama; lo que NO puede pasar es
    # que el título se quede con una palabra de la propia orden.
    limpio = tarea.removeprefix("la ").removeprefix("el ").strip()
    esperado = titulo_esperado.removeprefix("la ").removeprefix("el ").strip()
    check(limpio == esperado,
          f"«{frase}»: saca el título «{tarea}» en vez de «{titulo_esperado}». "
          "Con un título así no encuentra la tarea y contesta «No encuentro esa tarea»")
    check(estado == estado_esperado,
          f"«{frase}»: saca el estado «{estado}» en vez de «{estado_esperado}»")

# «restaura la tarea X» tiene que traer el título, no restaurarlo todo
r = sl.route("restaura la tarea diseñar logo")
check(bool(r) and (r[2].groupdict().get("task") or "").strip() == "diseñar logo",
      "«restaura la tarea diseñar logo» no captura el título: restauraría el lote entero")
r = sl.route("recupera las tareas borradas")
check(bool(r) and not (r[2].groupdict().get("task") or "").strip(),
      "«recupera las tareas borradas» captura un título que no existe")

# ------------------------------------------------- 3) fronteras
print("== 3) fronteras: ni roba ni le roban ==")
DE_OTROS = {"borra el archivo notas.txt": "files",
            "borra la carpeta Pruebas": "files",
            "apunta la reunión del lunes a las 10": "google_workspace"}
for f, duenyo in DE_OTROS.items():
    r = sl.route(f)
    check(bool(r) and r[0].folder == duenyo,
          f"«{f}» es de {duenyo} y va a " + (f"{r[0].folder}/{r[1]}" if r else "ningún sitio"))

# ------------------------------------------------- 4) dobles y tablero de prueba
print("== 4) borrar una tarea: previsualiza y NO borra sin confirmación ==")
CTX = {"channel": "pc"}


def _handle(frase):
    r = sl.route(frase)
    assert r and r[0].folder == "tasks_board", f"«{frase}» no llega a tasks_board: {r}"
    return asyncio.run(MOD.handle(r[1], frase, r[2], CTX))


def _tablero_de_prueba():
    board._save([])
    board._save_trash([])
    a = board.add_task("diseñar logo")
    b = board.add_task("comprar pan")
    c = board.add_task("mandar factura")
    board.move_task("comprar pan", "hechas")
    board.move_task("mandar factura", "hechas")
    return a, b, c


_tablero_de_prueba()
confirm.clear()
res = _handle("borra la tarea diseñar logo")
reply = res.get("reply", "")
check(board.counts()["total"] == 3, "¡«borra la tarea X» ha borrado SIN confirmación!")
check(confirm.pending("pc") is not None, "borrar una tarea no arma ninguna confirmación")
check("diseñar logo" in reply, "la pregunta no dice qué tarea se lleva")
check("sí" in reply.lower() and "no" in reply.lower(), "la pregunta no pide un sí/no")

asyncio.run(confirm.answer("no", "pc"))
check(board.counts()["total"] == 3, "un «no» ha borrado la tarea igualmente")

confirm.clear()
_handle("borra la tarea diseñar logo")
respuesta = asyncio.run(confirm.answer("sí", "pc")) or ""
check(board.counts()["total"] == 2, "tras el «sí» no ha borrado la tarea")
check(len(board.trash(limit=10)) == 1, "lo borrado no ha ido a la papelera")
check("papelera" in respuesta.lower(), "no dice que la tarea sea recuperable")
confirm.clear()

# ------------------------------------------------- 5) ámbito de los borrados masivos
print("== 5) borrado masivo: el ámbito sale del estado real, nunca del optimismo ==")
_tablero_de_prueba()
confirm.clear()
res = _handle("limpia las ya realizadas")
reply = res.get("reply", "")
check(res.get("data", {}).get("scope") == "completadas",
      f"«limpia las ya realizadas» no acota a completadas: {res.get('data')}")
check(res.get("data", {}).get("count") == 2,
      f"debería llevarse 2 completadas y dice {res.get('data', {}).get('count')}")
check("diseñar logo" not in reply, "la previsualización incluye una tarea PENDIENTE")
check("comprar pan" in reply and "mandar factura" in reply,
      "la previsualización no enseña las tareas que se va a llevar")
asyncio.run(confirm.answer("sí", "pc"))
check(board.counts()["pendiente"] == 1,
      "el borrado de «las ya realizadas» se ha llevado también las pendientes")
confirm.clear()

# ambiguo → se arma la opción SEGURA y se avisa
_tablero_de_prueba()
confirm.clear()
res = _handle("borra las tareas pendientes")
check(res.get("data", {}).get("scope") == "pendientes",
      "«borra las tareas pendientes» no acota a pendientes")
asyncio.run(confirm.answer("no", "pc"))

# vaciar el tablero entero exige decirlo con todas las letras, y avisa fuerte
confirm.clear()
res = _handle("borra todas las tareas")
check(res.get("data", {}).get("scope") == "todas",
      "«borra todas las tareas» no se reconoce como borrado total")
check("OJO" in res.get("reply", "") or "⚠" in res.get("reply", ""),
      "vaciar el tablero entero no avisa de que es el tablero ENTERO")
asyncio.run(confirm.answer("no", "pc"))
check(board.counts()["total"] == 3, "un «no» ha vaciado el tablero igualmente")
confirm.clear()

# ------------------------------------------------- 6) papelera y restauración
print("== 6) papelera: vaciarla es definitivo y pide una confirmación extra ==")
_tablero_de_prueba()
confirm.clear()
_handle("borra las tareas completadas")
asyncio.run(confirm.answer("sí", "pc"))
check(len(board.trash(limit=10)) == 2, "las completadas no están en la papelera")

confirm.clear()
res = _handle("vacía la papelera")
check(confirm.pending("pc") is not None, "vaciar la papelera no pide confirmación")
check("definitiv" in res.get("reply", "").lower(),
      "vaciar la papelera no avisa de que es definitivo")
asyncio.run(confirm.answer("no", "pc"))
check(len(board.trash(limit=10)) == 2, "un «no» ha vaciado la papelera igualmente")
confirm.clear()

# restaurar por título devuelve SOLO esa tarea
res = _handle("restaura la tarea comprar pan")
check(board.counts()["total"] == 2,
      f"«restaura la tarea comprar pan» debería devolver 1 y el tablero tiene "
      f"{board.counts()['total']}")
check("comprar pan" in res.get("reply", ""), "no dice qué tarea ha recuperado")

# ------------------------------------------------- 7) honestidad
print("== 7) falla con honestidad ==")
board._save([])
board._save_trash([])
res = _handle("borra la tarea que no existe jamas")
check("no encuentro" in res.get("reply", "").lower(),
      "borrar una tarea inexistente no lo dice claramente")
check(confirm.pending("pc") is None, "arma una confirmación para una tarea que no existe")
res = _handle("borra las tareas completadas")
check("vacío" in res.get("reply", "").lower() or "no hay" in res.get("reply", "").lower(),
      "con el tablero vacío no lo dice con claridad")
res = _handle("recupera las tareas borradas")
check("no hay nada" in res.get("reply", "").lower(),
      "con la papelera vacía no lo dice con claridad")
confirm.clear()

# ------------------------------------------------- 8) agnóstica y SKILL.md
print("== 8) agnóstica y SKILL.md fiel ==")
src = open(os.path.join(ROOT, "skills", "tasks_board", "skill.py"), encoding="utf-8").read()
md = open(os.path.join(ROOT, "skills", "tasks_board", "SKILL.md"), encoding="utf-8").read()
_PROPIOS = re.compile(r"\b(achoz|adri[aá]n|C:\\Users\\a)\b", re.I)
check(not _PROPIOS.search(src), "skill.py lleva dentro datos del usuario")
check(not _PROPIOS.search(md), "SKILL.md lleva dentro datos del usuario")

_cuerpo = md.split("## Órdenes de ejemplo")[-1].split("## Seguridad")[0]
for frase in re.findall(r'"([^"\n]+)"', _cuerpo):
    if len(frase.split()) < 2:
        continue
    r = sl.route(frase)
    check(bool(r) and r[0].folder in ("tasks_board", "google_workspace"),
          f"SKILL.md promete «{frase}» pero va a "
          + (f"{r[0].folder}/{r[1]}" if r else "ningún sitio"))

check("confirmación" in md.lower(), "SKILL.md no explica la confirmación de los borrados")

print(f"\n{'#' * 54}\ntest_skill_tasks_board: {_pass} OK, {len(_fail)} fallos")
if _fail:
    for f in _fail:
        print("  - " + f)
sys.exit(1 if _fail else 0)
