# -*- coding: utf-8 -*-
"""Auditoría de la skill ARCHIVOS: activación con frases naturales, enrutado real,
candado anti-Drive, confirmación obligatoria antes de la papelera y honestidad
cuando falta send2trash.

No borra, no crea ni mueve nada del usuario: trabaja sobre un directorio temporal
y send2trash se sustituye por un doble que solo apunta lo que le habrían pedido.

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_skill_files.py
"""
from __future__ import annotations

import asyncio
import os
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


from backend.core.aplicacion import skills_loader as sl
from backend.core.comun import confirm  # noqa: E402

# ------------------------------------------------- 1) carga con el cargador real
print("== 1) la skill carga como la carga nexus (skills_loader) ==")
REG = sl.load_skills()
FSK = REG.get("files")
check(FSK is not None, "skills_loader no registra la carpeta 'files'")
check(FSK is not None and FSK.status != "error",
      f"la skill files no carga: {FSK.description if FSK else ''}")
MOD = FSK.module if FSK else None
check(MOD is not None and hasattr(MOD, "handle"), "files no expone handle()")

INTENTS = list(FSK.patterns.keys()) if FSK else []
for i in ("trash", "trash_confirm", "make_doc", "move", "copy", "rename", "mkdir",
          "update", "versions", "restore_file", "mkfile", "search", "explore",
          "analyze", "summarize", "read"):
    check(i in INTENTS, f"falta el intent «{i}»")

# ------------------------------------------------- 2) activación: frases naturales
print("== 2) activación con frases naturales (tildes, enclíticos, sinónimos) ==")
ACTIVAN = {
    "trash": ["borra el archivo notas.txt", "bórrame el archivo notas.txt",
              "borra la carpeta Pruebas", "elimina el fichero viejo.log",
              "quítame el documento borrador.docx",
              "manda a la papelera el archivo notas.txt",
              "manda el archivo notas.txt a la papelera",
              "tira a la papelera C:/tmp/x.txt"],
    "explore": ["explora la carpeta Documentos", "explórame la carpeta Descargas",
                "ábreme la carpeta Descargas", "qué hay en el escritorio"],
    "search": ["busca informe en mis documentos",
               "búscame factura en la carpeta Descargas"],
    "read": ["lee el archivo notas.txt", "léeme notas.txt"],
    "summarize": ["resume el documento acta.pdf", "resúmeme acta.pdf"],
    "analyze": ["analiza el código skill.py", "analízame el script main.py"],
    "mkdir": ["crea una carpeta llamada Proyectos en Documentos",
              "créame una carpeta Proyectos",
              "haz una carpeta nueva en el escritorio llamada Fotos"],
    "mkfile": ["crea el archivo notas.md que diga hola", "créame un archivo lista.txt"],
    "move": ["mueve el archivo x.txt a Documentos", "muéveme el archivo x.txt a Documentos"],
    "copy": ["copia el archivo x.txt a Documentos", "cópiame el archivo x.txt a Documentos"],
    "rename": ["renombra el archivo x.txt a y.txt", "renómbrame el archivo x.txt a y.txt"],
    "update": ["añade al archivo notas.md que diga hola",
               "actualiza el archivo notas.md con el texto hola"],
    "versions": ["qué versiones tienes de notas.md"],
    "restore_file": ["restaura el archivo notas.md"],
    "make_doc": ["crea un documento en el escritorio que se llame acta",
                 "hazme un documento word en el escritorio"],
}
for intent, frases in ACTIVAN.items():
    for f in frases:
        r = sl.route(f)
        destino = f"{r[0].folder}/{r[1]}" if r else "ningún sitio"
        check(bool(r) and r[0].folder == "files" and r[1] == intent,
              f"«{f}» debería ser files/{intent} y va a {destino}")

# --------------------------------- 3) el patrón entrega SIEMPRE una ruta usable
print("== 3) cada activación entrega una ruta (ningún grupo suelto sin recoger) ==")
GRUPOS = {"trash": ("path", "path2", "path3", "path4"),
          "explore": ("path", "path2"), "read": ("path", "path2"),
          "summarize": ("path", "path2"), "versions": ("path", "path2")}
for intent, frases in ACTIVAN.items():
    if intent not in GRUPOS:
        continue
    for f in frases:
        r = sl.route(f)
        if not r or r[0].folder != "files":
            continue
        gd = r[2].groupdict()
        check(any(gd.get(g) for g in GRUPOS[intent]),
              f"«{f}» casa {intent} pero no rellena ninguna ruta: {gd}")

# ------------------------------------------------- 4) candado anti-Drive
print("== 4) el candado _SIN_DRIVE: nada con «drive» toca el disco local ==")
CON_DRIVE = [
    "borra la carpeta Informes de drive",
    "borra el archivo notas.txt de drive",
    "manda a la papelera el archivo informe.md de drive",
    "manda el archivo informe.md de drive a la papelera",
    "busca contratos en la carpeta Clientes de drive",
    "qué versiones tienes de informe.md en drive",
    "restaura el archivo informe.md de drive",
    "lee el archivo informe.md de drive",
    "resume el documento acta.pdf de drive",
    "mueve el archivo x.txt a la carpeta Y de drive",
    "copia el archivo x.txt a drive",
    "renombra el archivo x.txt a y.txt en drive",
    "crea la carpeta Clientes en drive",
    "crea el archivo notas.md en drive",
    "añade al archivo notas.md de drive que diga hola",
    "crea un documento en el escritorio de drive",
    "explora la carpeta Clientes de drive",
]
for f in CON_DRIVE:
    r = sl.route(f)
    check(not r or r[0].folder != "files",
          f"«{f}» menciona drive y la coge files/{r[1] if r else ''} (borraría del DISCO)")

# el candado tiene que estar puesto en TODOS los intents que pueden chocar
_SIN_DRIVE = getattr(MOD, "_SIN_DRIVE", "")
check(bool(_SIN_DRIVE), "la skill ya no define _SIN_DRIVE")
_sin_candado = [i for i, rx in (FSK.patterns.items() if FSK else [])
                if _SIN_DRIVE and not rx.pattern.startswith(_SIN_DRIVE)]
check(set(_sin_candado) <= {"analyze", "trash_confirm"},
      f"intents sin candado anti-drive que sí lo necesitan: {_sin_candado}")

# ------------------------------------------------- 5) la papelera exige confirmación
print("== 5) mandar a la papelera NO borra: arma confirmación y previsualiza ==")
TMP = tempfile.mkdtemp(prefix="nexus_files_test_")
victima = os.path.join(TMP, "victima.txt")
with open(victima, "w", encoding="utf-8") as fh:
    fh.write("contenido de prueba\n")
carpeta = os.path.join(TMP, "carpeta_victima")
os.makedirs(os.path.join(carpeta, "sub"), exist_ok=True)
with open(os.path.join(carpeta, "sub", "a.txt"), "w", encoding="utf-8") as fh:
    fh.write("x")

_borrados = []


class _Send2TrashDoble:
    """Doble de send2trash: apunta la ruta en vez de tocar el disco."""
    def send2trash(self, ruta):
        _borrados.append(ruta)


sys.modules["send2trash"] = _Send2TrashDoble()


def _ruta_y_handle(frase, canal="pc"):
    r = sl.route(frase)
    assert r and r[0].folder == "files", f"«{frase}» no llega a files: {r}"
    ctx = {"channel": canal, "settings": None}
    return asyncio.run(MOD.handle(r[1], frase, r[2], ctx))


confirm.clear()
res = _ruta_y_handle(f"borra el archivo {victima}")
reply = res.get("reply", "")
check(not _borrados, "¡«borra el archivo X» ha borrado SIN confirmación!")
check(os.path.exists(victima), "el archivo ha desaparecido sin confirmación")
check(confirm.pending("pc") is not None, "no ha quedado ninguna confirmación armada")
check("victima.txt" in reply, "la pregunta no dice qué archivo se lleva")
check("KB" in reply or "bytes" in reply, "la pregunta no dice el tamaño de lo que se lleva")
check("sí" in reply.lower() and "no" in reply.lower(), "la pregunta no pide un sí/no")

# ...y con «no» no se borra nada
respuesta = asyncio.run(confirm.answer("no", "pc"))
check(not _borrados, "un «no» ha acabado borrando igualmente")
check(isinstance(respuesta, str) and "victima.txt" in respuesta,
      "al cancelar no dice qué ha dejado en paz")

# ...y con «sí» se ejecuta, y solo entonces
confirm.clear()
_ruta_y_handle(f"borra el archivo {victima}")
respuesta = asyncio.run(confirm.answer("sí", "pc"))
check(_borrados == [victima], f"tras el «sí» no se ha mandado a la papelera: {_borrados}")
check("papelera" in (respuesta or "").lower(), "no dice que esté en la papelera")

# la previsualización de una CARPETA dice cuánto se lleva
confirm.clear()
_borrados.clear()
res = _ruta_y_handle(f"borra la carpeta {carpeta}")
check("elemento" in res.get("reply", ""),
      "borrar una carpeta no avisa de cuántos elementos se lleva")
check(not _borrados, "borrar una carpeta ha actuado sin confirmar")
confirm.clear()

# ------------------------------------------------- 6) honestidad
print("== 6) falla con honestidad: dice qué falta y no se inventa el resultado ==")
_borrados.clear()
res = _ruta_y_handle(os.path.join("borra el archivo " + TMP, "no_existe_jamas.txt"))
check("no existe" in res.get("reply", "").lower(),
      "borrar algo inexistente no lo dice claramente")
check("borrado" not in res.get("reply", "").lower() or
      "no he borrado" in res.get("reply", "").lower(),
      "dice haber borrado algo que no existe")

sys.modules["send2trash"] = None        # simula que send2trash NO está instalado
confirm.clear()
_ruta_y_handle(f"borra el archivo {victima}")
respuesta = asyncio.run(confirm.answer("sí", "pc")) or ""
check("send2trash" in respuesta, "sin send2trash no dice qué falta instalar")
check("no he borrado" in respuesta.lower() or "sigue donde estaba" in respuesta.lower(),
      "sin send2trash no deja claro que NO ha borrado")
confirm.clear()

# «confirmo papelera» sin nada armado no puede disparar un borrado antiguo
res = _ruta_y_handle("confirmo papelera")
check("no hay nada pendiente" in res.get("reply", "").lower(),
      "«confirmo papelera» sin nada armado no responde con honestidad")

# ------------------------------------------------- 7) agnóstica
print("== 7) agnóstica: sin nombres propios ni rutas del usuario ==")
import re as _re                                            # noqa: E402

src = open(os.path.join(ROOT, "skills", "files", "skill.py"), encoding="utf-8").read()
md = open(os.path.join(ROOT, "skills", "files", "SKILL.md"), encoding="utf-8").read()
_PROPIOS = _re.compile(r"\b(achoz|adri|adri[aá]n|C:\\Users\\a)\b", _re.I)
check(not _PROPIOS.search(src), "skill.py lleva dentro datos del usuario")
check(not _PROPIOS.search(md), "SKILL.md lleva dentro datos del usuario")

# ------------------------------------------------- 8) SKILL.md dice la verdad
print("== 8) SKILL.md: lo que promete se activa de verdad ==")
for frase in _re.findall(r"«([^»\n]+)»", md):
    if frase.startswith(("_", "sí", "no", "Restaurar")) or " " not in frase:
        continue
    if "drive" in frase.lower():                            # esas son de Google, a propósito
        continue
    r = sl.route(frase)
    check(bool(r) and r[0].folder == "files",
          f"SKILL.md promete «{frase}» pero va a "
          + (f"{r[0].folder}/{r[1]}" if r else "ningún sitio"))

check("confirmación" in md.lower() and "papelera" in md.lower(),
      "SKILL.md no explica la confirmación antes de mandar a la papelera")

print(f"\n{'#' * 54}\ntest_skill_files: {_pass} OK, {len(_fail)} fallos")
if _fail:
    for f in _fail:
        print("  - " + f)
sys.exit(1 if _fail else 0)
