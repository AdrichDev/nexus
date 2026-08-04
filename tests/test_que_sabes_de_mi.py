# -*- coding: utf-8 -*-
"""«Qué sabes de mí» son datos TUYOS, contados hablando.

INCIDENTE (03/08/2026). Adrián preguntó qué sabía de él y recibió un volcado con
secciones, emojis y 200 entradas, de las cuales:

  - 60 eran la DOCUMENTACIÓN de las propias skills, indexada para poder decidir
  - varias eran REGISTROS de encargos, con trazas de error dentro
    («[Trabajo] … => RuntimeError: el gateway no ha abierto su API»)
  - y entre medias, tres datos suyos de verdad

Su queja, literal: «hay un montón de cosas que se sacan como información de mí
que no tienen que salir y son irrelevantes», y «responde de manera robótica,
todo como súper clasificado y no parece una conversación».

DOS REGLAS.

1. Lo que se enseña es lo que ÉL ha mandado recordar, más cómo le gusta que se
   trabaje. No hace falta adivinarlo mirando el texto: ya está escrito al
   guardarlo, en el `kind`. Intentar reconocerlo por la forma no funciona — un
   manual partido en trozos parece un montón de frases sueltas.

2. Se cuenta HABLANDO. Sin secciones, sin títulos, sin viñetas y sin emojis. Y
   usando solo lo que hay: redactar no es inventar.

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_que_sabes_de_mi.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.core.aplicacion.skills_loader import load_skills, route      # noqa: E402

MG = load_skills()["memory_graph"].module

_pass = 0
_fail: list[str] = []


def check(cond, msg: str) -> bool:
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print(f"  FALLO: {msg}")
    return bool(cond)


# ============ 1) QUÉ ENTRA Y QUÉ NO ========================================
print("== 1) lo que se enseña es lo que has mandado recordar ==")

TUYO = [
    {"kind": "fact", "content": "me gusta el café solo"},
    {"kind": "fact", "content": "el wifi de casa es lento"},
    {"kind": "procedure", "content": "prefiero que no leas los correos, solo analizarlos"},
    {"kind": "preference", "content": "respuestas cortas y directas"},
]
NO_TUYO = [
    # documentación de las propias skills, indexada para decidir
    {"kind": "knowledge", "content": "# ▦ Skill: Tablero de tareas (kanban estilo Notion)"},
    {"kind": "knowledge", "content": "- «borra el correo 3» / «elimina los correos de Amazon»"},
    {"kind": "knowledge", "content": "el estado vive en backend.core.dominio.board y se guarda en data/"},
    # registros de encargos, con la traza dentro
    {"kind": "hermes", "content": "[Trabajo] dame ideas => RuntimeError: el gateway no abrió"},
    {"kind": "hermes", "content": "[Trabajo] instala npm i -g algo => Se ha instalado."},
    # y trozos de un documento partido por la mitad
    {"kind": "knowledge", "content": "[apuntes › manual.md] amos que falten - «mueve informe.md»"},
]

for fila in TUYO:
    check(MG.es_sobre_el_usuario(fila),
          f"se pierde un dato tuyo: «{fila['content'][:50]}»")
for fila in NO_TUYO:
    check(not MG.es_sobre_el_usuario(fila),
          f"se cuela fontanería como si fuera tuya: «{fila['content'][:50]}»")

# Un `knowledge` no entra AUNQUE su texto parezca una frase normal: lo que manda
# es cómo se guardó, no cómo se lee.
check(not MG.es_sobre_el_usuario({"kind": "knowledge", "content": "me gusta el café solo"}),
      "un knowledge se cuela solo por parecer una frase personal")


# ============ 2) LA RESPUESTA NO ES UNA FICHA ==============================
print("== 2) se cuenta hablando, no en secciones ==")

SRC = (ROOT / "skills" / "memory_graph" / "skill.py").read_text(encoding="utf-8")
i = SRC.find('if intent == "list_knowledge"')
bloque = SRC[i:SRC.find('if intent == "recall"', i)]

for prohibido, porque in (
        ("👤", "un emoji de sección"),
        ("PERFIL (lo que he destilado", "el título robótico del perfil"),
        ("🧠 MEMORIA (Postgres", "el volcado de la base de datos con su recuento"),
        ("📚 CONOCIMIENTO (RAG", "el volcado del RAG"),
        ("🗂️ NOTAS del grafo", "el listado de nombres de fichero"),
        ("Esto es TODO lo que sé de ti", "el encabezado de volcado")):
    check(prohibido not in bloque, f"la respuesta sigue llevando {porque}")

check("ask_llm" in bloque, "ya no lo redacta: vuelve a recitar lo que hay")
check(re.search(r"ÚNICAMENTE|SOLO lo que", bloque) is not None,
      "no le prohíbe al modelo añadir de su cosecha: redactar no es inventar")
check("sin emojis" in bloque.lower() and "sin secciones" in bloque.lower(),
      "no le pide que hable en vez de clasificar")

# Sin modelo tampoco se queda callada.
check("Esto es lo que tengo tuyo" in bloque,
      "sin modelo no enseña nada: quedarse mudo no es una opción")


# ============ 3) LA PREGUNTA SIGUE LLEGANDO ================================
print("== 3) la pregunta sigue llegando a su sitio ==")

for frase in ("qué sabes de mí", "que sabes de mi", "qué sabes de mí ahora",
              "dime todo lo que sabes de mí"):
    r = route(frase)
    check(r is not None and r[0].folder == "memory_graph" and r[1] == "list_knowledge",
          f"«{frase}» ya no llega a list_knowledge ({r[0].folder + '/' + r[1] if r else None})")


print(f"\n{'#' * 54}\ntest_que_sabes_de_mi: {_pass} OK, {len(_fail)} fallos")
for m in _fail:
    print("  -", m)
sys.exit(1 if _fail else 0)
