# -*- coding: utf-8 -*-
"""Auditoría de la skill DATOS/ANALÍTICA: activación con frases naturales,
enrutado real, solo lectura de verdad y de dónde salen las cifras que enseña.

No toca ninguna base de datos del usuario: se conecta a un SQLite en memoria
creado por el propio test, y ni abre el navegador ni escribe en data/reports/.

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_skill_datos.py
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_fail, _pass = [], 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  ✖ " + msg)


from backend.core.aplicacion import skills_loader as sl  # noqa: E402

print("== 1) carga con el cargador real ==")
REG = sl.load_skills()
SK = REG.get("datos")
check(SK is not None and SK.status != "error",
      f"datos no carga: {SK.description if SK else 'no registrada'}")
MOD = SK.module if SK else None
check(MOD is not None and hasattr(MOD, "handle"), "datos no expone handle()")
for i in ("connect", "disconnect", "which", "tables", "query", "profile", "dashboard", "chart"):
    check(i in (SK.patterns if SK else {}), f"falta el intent «{i}»")

print("== 2) activación con frases naturales (tildes, enclíticos, sinónimos) ==")
ACTIVAN = {
    "connect": ["conéctate a la base de datos sqlite://x.db",
                "conéctame a la base de datos sqlite://x.db",
                "conecta a la base de datos sqlite://x.db",
                "conéctate a la bd sqlite://x.db"],
    "disconnect": ["desconecta la base de datos", "desconéctate de la base de datos",
                   "desconéctame de la bd"],
    "which": ["qué base de datos está conectada", "a qué base de datos estás conectado",
              "qué bd tienes", "qué base de datos hay conectada"],
    "tables": ["qué tablas hay", "qué tablas tengo", "lista las tablas",
               "lístame las tablas", "muéstrame las tablas", "dame las tablas",
               "qué colecciones hay"],
    "query": ["consulta: SELECT * FROM ventas", "query: SELECT 1", "ejecuta: SELECT 1"],
    "profile": ["informe analítico de la tabla ventas", "informe analítico de ventas",
                "sácame un informe analítico de ventas"],
    "dashboard": ["dashboard de la tabla ventas", "panel de la tabla ventas",
                  "cuadro de mando de ventas", "hazme un dashboard de la tabla ventas"],
    "chart": ["gráfico de: select pais, total from ventas",
              "gráfica de select pais, total from ventas"],
}
for intent, frases in ACTIVAN.items():
    for f in frases:
        r = sl.route(f)
        got = f"{r[0].folder}.{r[1]}" if r else "(nada)"
        check(got == f"datos.{intent}", f"«{f}» → {got} (esperado datos.{intent})")

CTX = {"settings": {}, "channel": "test"}


def run(intent, texto):
    m = SK.patterns[intent].search(texto)
    return asyncio.run(MOD.handle(intent, texto, m, CTX))


print("== 3) sin conexión no finge datos: dice cómo conectarse ==")
MOD._conn.update({"url": None, "kind": None, "handle": None})
r = run("tables", "qué tablas hay")
check("Primero conéctame" in r["reply"], "sin BD conectada no dice qué hacer")
check("Traceback" not in r["reply"], "sin BD conectada suelta traceback")
r = run("which", "qué base de datos está conectada")
check("Ninguna BD externa conectada" in r["reply"], "«qué bd hay» miente cuando no hay ninguna")

print("== 4) esquema no soportado: error honesto, no excepción cruda ==")
r = run("connect", "conéctate a la base de datos redis://localhost")
check("No he podido conectar" in r["reply"] and "Esquema no soportado" in r["reply"],
      "un esquema desconocido no se explica")

# BD de juguete en memoria, del test: 300 filas para que la muestra sea parcial.
db = sqlite3.connect(":memory:", check_same_thread=False)
db.execute("CREATE TABLE ventas (pais TEXT, importe INTEGER)")
db.executemany("INSERT INTO ventas VALUES (?, ?)",
               [("ES" if i % 2 else "PT", i) for i in range(300)])
db.commit()
MOD._conn.update({"url": "sqlite://:memory:", "kind": "sqlite", "handle": db})

print("== 5) solo lectura: rechaza lo que modifica ==")
for sql in ("DELETE FROM ventas", "DROP TABLE ventas", "UPDATE ventas SET importe=0",
            "INSERT INTO ventas VALUES ('X',1)", "TRUNCATE TABLE ventas",
            "ALTER TABLE ventas ADD c INT", "GRANT ALL ON ventas TO x"):
    r = run("query", "consulta: " + sql)
    check("Solo lectura" in r["reply"], f"acepta «{sql}»")
_c, filas = MOD._sql("SELECT COUNT(*) FROM ventas")
check(filas[0][0] == 300, "la tabla de prueba ha cambiado: algo escribió de verdad")

print("== 6) consultas de lectura: filas reales, nada inventado ==")
r = run("query", "consulta: SELECT pais, importe FROM ventas WHERE pais='PT'")
check("pais | importe" in r["reply"], "no muestra las columnas consultadas")
check(r["reply"].startswith("50 filas") or "50 filas" in r["reply"],
      f"el recuento de filas no cuadra: {r['reply'][:60]}")

print("== 7) el perfil distingue el total real de la muestra ==")
kpis, cards, resumen = MOD._profile_table("ventas")
check(("Filas totales", "300") in kpis, f"el total no sale de COUNT(*): {kpis}")
check("muestra de 200" in resumen, f"el resumen no avisa de que hay muestra: {resumen}")
etiquetas = [c[1] for c in cards]
check(all("muestra de" in e for e in etiquetas if e.startswith("Top") or e.startswith("Evolución")),
      f"un gráfico de muestra se presenta como si fuera el total: {etiquetas}")
sumas = [k for k, _v in kpis if k.startswith("Σ")]
check(all("filas" in s for s in sumas), f"una suma parcial se presenta como total: {sumas}")

print("== 8) tabla pequeña: sin muestra, sin coletilla que sobre ==")
db.execute("CREATE TABLE mini (pais TEXT)")
db.executemany("INSERT INTO mini VALUES (?)", [("ES",), ("PT",)])
db.commit()
_k, _c2, resumen_mini = MOD._profile_table("mini")
check("muestra" not in resumen_mini, f"avisa de muestra sin haberla: {resumen_mini}")

print("== 9) nombre de tabla inválido: se rechaza, no se interpola ==")
try:
    MOD._profile_table("ventas; DROP TABLE ventas")
    check(False, "acepta un nombre de tabla con SQL dentro")
except RuntimeError as exc:
    check("no válido" in str(exc), "el rechazo del nombre de tabla no se explica")

print("== 10) SKILL.md: sin modos que no existen ==")
doc = SK.doc or ""
check("modo escritura de datos" not in doc,
      "el SKILL.md promete un «modo escritura de datos» que no existe")
check("De dónde salen las cifras" in doc, "el SKILL.md no explica de dónde salen las cifras")
check("200" in doc, "el SKILL.md no dice el tamaño de la muestra")
check("Qué NO hace" in doc, "el SKILL.md no dice qué NO hace")

MOD._conn.update({"url": None, "kind": None, "handle": None})
print(f"\n{'#'*54}\n{_pass} comprobaciones OK, {len(_fail)} fallos")
for m in _fail:
    print("  -", m)
sys.exit(1 if _fail else 0)
