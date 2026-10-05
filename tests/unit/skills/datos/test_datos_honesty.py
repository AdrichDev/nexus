# -*- coding: utf-8 -*-
"""datos: solo lectura REAL y cifras honestas.

Encontrado auditando la ruta real de comandos (SQLite de prueba, sin red):
  * `REPLACE INTO` escribía, `ATTACH` creaba ficheros y `PRAGMA` se ejecutaba, aunque
    SKILL.md promete «no escribe en la base de datos» (la lista negra de palabras no los cubría);
  * `SELECT 'please update me'` se rechazaba (falso positivo con texto entre comillas);
  * una ruta con errata creaba una BD vacía y decía «Conectado»;
  * una tabla de 120 filas respondía «50 filas:»;
  * el gráfico dibujaba 20 etiquetas con un KPI de 50 filas, sin avisar;
  * «abierto en el navegador» aunque el navegador no se abriera.

SQLite temporal, webbrowser y LLM simulados. Nivel M.
Ejecutar: python tests/unit/skills/datos/test_datos_honesty.py
"""
import asyncio
import re
import sqlite3
import sys
import tempfile
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from backend.core.aplicacion import skills_loader as sl  # noqa: E402

sl.load_skills()
datos = sl.get_skills()["datos"].module

_fail, _pass = [], 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


TMP = Path(tempfile.mkdtemp(prefix="nexus_datos_test_"))
datos.REPORTS_DIR = TMP / "reports"
DB = TMP / "t.db"
_c = sqlite3.connect(DB)
_c.execute("CREATE TABLE t (id INTEGER, name TEXT)")
_c.executemany("INSERT INTO t VALUES (?, ?)", [(i, f"fila-{i}") for i in range(120)])
_c.execute("CREATE TABLE pequena (id INTEGER)")
_c.executemany("INSERT INTO pequena VALUES (?)", [(i,) for i in range(5)])
_c.commit()
_c.close()


def correr(frase, abre=True):
    r = sl.route(frase)
    assert r and r[0].folder == "datos", f"«{frase}» no llega a datos: {r and (r[0].folder, r[1])}"
    skill, intent, m = r
    abiertos = []
    orig = webbrowser.open
    webbrowser.open = lambda url, *a, **k: (abiertos.append(url) or abre)
    try:
        res = asyncio.run(skill.module.handle(intent, frase, m, None))
    finally:
        webbrowser.open = orig
    return res.get("reply", ""), abiertos


def filas_en_bd():
    c = sqlite3.connect(DB)
    n = c.execute("SELECT count(*) FROM t").fetchone()[0]
    c.close()
    return n


reply, _ = correr(f"conéctate a la bd sqlite://{DB.as_posix()}")
check("Conectado a SQLITE" in reply, "conecta a una BD que existe")

# 1) solo lectura: ninguna escritura prospera
ESCRITURAS = [
    "REPLACE INTO t VALUES (1000, 'x')",
    "INSERT INTO t VALUES (1001, 'x')",
    "UPDATE t SET name = 'x'",
    "DELETE FROM t",
    "DROP TABLE t",
    "CREATE TABLE nueva (a INTEGER)",
    f"ATTACH DATABASE '{(TMP / 'adjunta.db').as_posix()}' AS otra",
    f"VACUUM INTO '{(TMP / 'copia.db').as_posix()}'",
    "PRAGMA user_version = 42",
    "SELECT 1; DELETE FROM t",
    "WITH x AS (SELECT 1) INSERT INTO t SELECT 1, 'x'",
    "SELECT * INTO copia FROM t",
    "COPY t TO 'salida.csv'",
]
for sql in ESCRITURAS:
    reply, _ = correr(f"consulta: {sql}")
    check(reply.startswith("Solo lectura"), f"rechaza: {sql[:48]}")
check(filas_en_bd() == 120, "la tabla sigue con 120 filas tras todos los intentos")
check(not (TMP / "adjunta.db").exists() and not (TMP / "copia.db").exists(),
      "no se creó ningún fichero (ATTACH / VACUUM INTO)")

# 2) el motor TAMBIÉN es de solo lectura (por si algo se colara del validador)
try:
    datos._sql("INSERT INTO t VALUES (2000, 'directo')")
    escribio = True
except Exception:
    escribio = False
check(not escribio, "motor: un INSERT directo sobre la conexión falla (conexión de solo lectura)")
check(filas_en_bd() == 120, "motor: la tabla sigue intacta")

# 3) lo legítimo SÍ funciona (incluida la palabra «update» dentro de un texto)
for sql, esperado in [("SELECT 'please update me' AS x", "please update me"),
                      ("select count(*) from t", "120"),
                      ("WITH c AS (SELECT 7 AS a) SELECT a FROM c", "7"),
                      ("SELECT 'delete' AS palabra -- ojo", "delete"),
                      ("SELECT name FROM t WHERE id = 3", "fila-3")]:
    reply, _ = correr(f"consulta: {sql}")
    check(not reply.startswith("Solo lectura") and esperado in reply, f"permite: {sql[:48]}")

# 4) una ruta que no existe no crea nada
falta = TMP / "no_existe.db"
reply, _ = correr(f"conéctate a la bd sqlite://{falta.as_posix()}")
check("no existe" in reply.lower() and "Conectado" not in reply, "ruta inexistente: dice que no existe")
check(not falta.exists(), "ruta inexistente: NO crea el fichero")
reply, _ = correr(f"conéctate a la bd sqlite://{DB.as_posix()}")

# 5) recuentos honestos
reply, _ = correr("consulta: SELECT * FROM t")
check("más de 50" in reply and "12" in reply, "120 filas: dice «más de 50» y que muestra 12")
check(not reply.startswith("50 filas"), "120 filas: no presenta el tope de lectura como el tamaño del resultado")
reply, _ = correr("consulta: SELECT * FROM pequena")
check(reply.startswith("5 filas") and "más de" not in reply, "5 filas: se dice tal cual")

reply, abiertos = correr("gráfico de: SELECT id, id FROM t")
html = Path(re.search(r"data/reports/([\w\-.]+\.html)", reply).group(1)) if "data/reports/" in reply else None
archivo = next(iter(sorted((TMP / "reports").glob("dash-*.html"))), None)
texto = archivo.read_text(encoding="utf-8") if archivo else ""
check("20" in reply and "50" in reply, "gráfico: la respuesta dice cuántas filas dibuja y cuántas leyó")
check("primeras 20" in texto, "gráfico: el título del propio gráfico dice «primeras 20»")

# 6) navegador honesto
reply, _ = correr("gráfico de: SELECT id, id FROM t", abre=False)
check("no pude abrir el navegador" in reply.lower() and "data/reports/" in reply
      and "abierto en el navegador" not in reply.lower(),
      "gráfico sin navegador: no dice «abierto» y da la ruta del archivo")
reply, _ = correr("gráfico de: SELECT id, id FROM t", abre=True)
check("abierto en el navegador" in reply.lower(), "gráfico con navegador: sigue diciendo «abierto»")

import backend.core.infraestructura.llm as _llm  # noqa: E402


async def _ask(*a, **k):
    return ("observación de prueba", None)


orig_ask = _llm.ask_llm
_llm.ask_llm = _ask
try:
    reply, _ = correr("dashboard de la tabla t", abre=False)
    check("no pude abrir el navegador" in reply.lower() and "abierto en el navegador" not in reply.lower(),
          "dashboard sin navegador: no dice «abierto»")
    reply, _ = correr("dashboard de la tabla t", abre=True)
    check("abierto en el navegador" in reply.lower(), "dashboard con navegador: sigue diciendo «abierto»")
finally:
    _llm.ask_llm = orig_ask

print(f"\ndatos honesty: {_pass} OK, {len(_fail)} FAIL")
sys.exit(1 if _fail else 0)
